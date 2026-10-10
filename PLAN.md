# Compliance Sentinel Agent: Build Plan

A LangGraph agent that checks regulatory sources every day, stores new rules in a legal RAG index, audits a target codebase against them, and produces an audit-ready PDF report with citations. It sends a Slack or email alert when it finds a critical violation. Legal and engineering teams sign in through **Clerk**, and each team's repos, findings and reports stay inside its own Clerk organization.

---

## 1. Scope decisions (lock these first)

| Decision | Choice | Why |
|---|---|---|
| Regulatory domain | **Data privacy**: GDPR, CCPA/CPRA, and optionally HIPAA | Rules that map to code patterns you can check: PII logging, retention, consent, encryption, data residency |
| Sources | Federal Register API, EUR-Lex, ICO and EDPB guidance pages, California CPPA | Mix of API and HTML pages, which shows off Playwright properly |
| Target codebase | A demo repo you own with **seeded violations**, plus 1–2 public open-source repos | You can show known violations being found and measure accuracy |
| Language | **Python 3.12** for everything | LangGraph, Playwright, WeasyPrint and the `bullmq` Python package all run in one runtime |
| LLM | Claude via the Anthropic SDK, model name set in config | Strong at long-context code and legal reading |
| Embeddings | Voyage `voyage-law-2` for regulations, `voyage-code-3` for code; OpenAI `text-embedding-3-small` as a fallback | Domain-tuned embeddings improve legal retrieval |
| Auth | **Clerk** with Organizations, a small Next.js dashboard, FastAPI verifying Clerk session tokens | Hosted sign-in, team workspaces and roles without building auth yourself |
| Tenancy | Regulations are shared by everyone. Repos, runs, findings and reports belong to one Clerk organization | Scraping happens once, and each team only sees its own audits |

**Out of scope for v1:** auto-fix PRs, enterprise SSO, billing and custom sign-in screens. Clerk's prebuilt components cover sign-in.

---

## 2. Architecture

```
  ┌─────────────── Vercel ───────────────┐      ┌───────── Clerk ─────────┐
  │ Next.js dashboard                    │◄────►│ sign-in, organizations, │
  │ <SignIn/>, <OrganizationSwitcher/>   │      │ roles, session tokens   │
  └──────────────────┬───────────────────┘      └───────────┬─────────────┘
                  │ Bearer <Clerk session token>          │ webhooks (Svix)
                  ▼                                       ▼
            ┌──────────────── Fly.io ────────────────┐
 cron  ──►  │ scheduler (BullMQ repeatable jobs)      │
            │        │                                │
            │        ▼   Redis (Upstash)              │
            │  ┌─────────────┐   ┌──────────────────┐ │
            │  │ scrape      │──►│ ingest worker    │ │
            │  │ worker      │   │ parse→chunk→embed│ │
            │  │ (Playwright)│   └────────┬─────────┘ │
            │  └─────────────┘            ▼           │
            │                 Postgres + pgvector     │
            │                    ▲          │         │
            │  ┌─────────────────┴──────┐   │         │
            │  │ audit worker (LangGraph)│◄─┘         │
            │  └───────────┬────────────┘             │
            │              ▼                          │
            │  report worker (Jinja2 → WeasyPrint)    │
            │              ▼                          │
            │  object storage (Tigris) + Slack/email  │
            │                                         │
            │  FastAPI: /health /me /repos /runs      │
            │   /findings /reports /trigger           │
            │   /webhooks/clerk                       │
            └─────────────────────────────────────────┘
```

**Auth flow:** the dashboard gets a session token from Clerk and sends it to FastAPI. FastAPI checks the token's signature against Clerk's public keys, then reads the user ID, the active organization and the role from it. Every query is then filtered by that organization.

**Queues:** `scrape` → `ingest` → `audit` → `report` → `notify`. Each stage enqueues the next one, so any stage can be retried or replayed alone.

---

## 3. Repository layout

```
compliance-sentinel/
├── sentinel/
│   ├── config.py              # pydantic-settings
│   ├── db/                    # SQLAlchemy models + Alembic migrations
│   ├── scrapers/              # one module per source, common BaseScraper
│   ├── ingest/                # parse, chunk, embed, diff
│   ├── rag/                   # hybrid retriever, reranker
│   ├── agent/                 # LangGraph graph, nodes, state, prompts
│   ├── codebase/              # repo clone, tree-sitter index, static checks
│   ├── report/                # Jinja2 templates, CSS, WeasyPrint render
│   ├── notify/                # Slack webhook, email (Resend/SMTP)
│   ├── queue/                 # BullMQ queues, workers, schedules
│   ├── auth/                  # Clerk token check, org/role dependencies, webhook sync
│   └── api/                   # FastAPI app
├── web/                       # Next.js dashboard with Clerk (deployed to Vercel)
│   ├── app/                   # sign-in, org picker, repos, runs, findings, reports
│   └── proxy.ts               # clerkMiddleware route protection
├── evals/                     # golden set, scoring scripts
├── demo-target-repo/          # seeded-violation app (or separate repo)
├── tests/
├── Dockerfile
├── fly.toml
├── docker-compose.yml         # local Postgres+pgvector, Redis
└── README.md
```

---

## 4. Data model (Postgres)

- **organizations**: id, clerk_org_id, name, Slack webhook URL, alert emails, severity threshold. Kept in sync by Clerk webhooks.
- **users** and **memberships**: clerk_user_id, email, name, and each user's role in each organization. Kept in sync by Clerk webhooks.
- **sources**: id, name, url, type (api/html/pdf), jurisdiction, selector config. Shared by all organizations.
- **documents**: id, source_id, external_id, title, url, published_at, content_hash, raw_path, status.
- **document_versions**: links an amendment to the earlier version, with a stored text diff.
- **reg_chunks**: id, document_id, section_ref (e.g. "Art. 32(1)(a)"), text, embedding `vector(1024)`, tsvector for keyword search.
- **obligations**: rules pulled out of each chunk as structured fields: actor, action, condition, severity, code-checkable flag.
- **repos** and **code_chunks**: org_id, file path, symbol, line range, language, embedding.
- **audit_runs**: id, org_id, repo, commit sha, trigger (schedule or a user ID), status, timestamps, token cost.
- **findings**: org_id, run_id, obligation_id, file, lines, severity, status (violation / needs review / compliant / accepted risk), evidence, reasoning, confidence, reviewed_by user ID.
- **reports**: org_id, run_id, pdf_url, sha256 hash of the PDF, approved_by user ID.

Every table with an `org_id` gets an index on it. Postgres row-level security keyed on the current organization is an optional second safety net.

---

## 5. Component plan

### 5.1 Scraping (Playwright)
- Use a `BaseScraper` interface with `list_new(since) -> [DocRef]` and `fetch(ref) -> RawDoc`.
- Call APIs directly where they exist, such as the Federal Register. Use Playwright only for pages rendered with JavaScript.
- **Change detection:** hash the content and keep `ETag`/`Last-Modified` values. Unchanged pages are skipped.
- **Politeness:** respect robots.txt, throttle each domain, set a clear User-Agent, and retry with backoff.
- Save the raw HTML or PDF to object storage, so every citation can be traced to its source.

### 5.2 Ingest and Legal RAG
- **Parsing:** use `trafilatura` for HTML and `pymupdf` for PDFs. Keep the legal structure of articles, sections and paragraphs.
- **Chunking:** split along that structure, one chunk per paragraph or sub-article, with a parent-section summary added for context. Do not split at a fixed token count.
- **Obligation extraction:** an LLM pass turns each chunk into a typed `Obligation` using structured output. This is the key step that makes rules checkable.
- **Amendment diff:** compare each new version with the stored one. Only changed obligations trigger a re-audit.
- **Retrieval:** hybrid search that combines pgvector cosine similarity with Postgres full-text BM25, merged by reciprocal rank fusion, then a reranker (Voyage or Cohere rerank).

### 5.3 Codebase indexing
- Clone the target repo at a pinned commit.
- Parse it with **tree-sitter** into function-level chunks, then embed them.
- Run cheap static checks first as evidence for the agent: **Semgrep** with custom privacy rules, regex PII detectors, and a dependency scan. The LLM then judges these hits instead of reading every file.

### 5.4 LangGraph agent

**State:** run_id, repo, the list of changed obligations, the current obligation, candidate code locations, findings, and errors.

**Nodes:**
1. `load_obligations`: get the new or changed obligations marked code-checkable.
2. `plan_checks`: for each obligation, the LLM writes search queries and picks Semgrep rules.
3. `retrieve_code`: run hybrid code search and static check hits for that obligation.
4. `assess`: the LLM compares obligation text with code evidence and returns a typed `Finding` with a confidence score.
5. `verify`: a second LLM pass, or a deterministic check, confirms each violation and the exact file and lines. Low-confidence results become "needs review".
6. `aggregate`: remove duplicates, score severity, and map findings to obligations.
7. `route`: if any critical finding exists, branch to notify. Always continue to the report.

**Patterns to show:** run obligations in parallel with LangGraph's `Send` API, use the Postgres checkpointer so a run can resume, and add an optional human-in-the-loop interrupt before the report is sent.

**Tracing:** LangSmith or Langfuse for every run, with token cost logged to `audit_runs`.

### 5.5 Report (WeasyPrint)
- Build the HTML with Jinja2 and print CSS, then render it to PDF.
- **Sections:** cover page, executive summary, scope (repo, commit, regulations, date), findings table sorted by severity, detailed findings, changed regulations appendix, method, and a signature block.
- **Audit-ready details:** every finding cites the regulation section with a source URL and retrieval date. Every finding shows the code snippet with file and line numbers. The PDF carries a SHA-256 hash, the run ID and the commit SHA, so the report can be reproduced.

### 5.6 Alerts
- Slack incoming webhook with Block Kit: severity, count, top three findings, and a link to the PDF.
- Email through Resend or SMTP with the PDF attached.
- Each organization sets its own Slack webhook, recipients and severity threshold in the dashboard.
- Send at most one alert per obligation and repo, to avoid repeat noise.

### 5.7 Scheduling and deployment
- BullMQ repeatable job: `scrape-all` every day at 06:00 UTC. Separate queues for each stage, with retries and a dead-letter queue.
- **Fly.io:** one app with process groups for `api`, `worker` and `scheduler`. Fly Postgres or Neon with pgvector. Upstash Redis. Tigris for object storage. Secrets set with `fly secrets`.
- The Docker image is based on the official Playwright Python image, plus the system libraries WeasyPrint needs (Pango, Cairo).
- The Next.js dashboard deploys to Vercel. Its Clerk keys live in Vercel, and the API's Clerk keys live in `fly secrets`.

### 5.8 Authentication and teams (Clerk)

**Dashboard (Next.js, `web/`)**
- Wrap the app in `<ClerkProvider>` and protect every route except sign-in with `clerkMiddleware`.
- Use Clerk's prebuilt `<SignIn/>`, `<UserButton/>` and `<OrganizationSwitcher/>`. Require users to belong to an organization.
- Pages: repos, runs, findings with filters, report downloads, and organization alert settings.
- Server components call FastAPI with `Authorization: Bearer` and a token from Clerk's `getToken()`.

**API (FastAPI, `sentinel/auth/`)**
- Verify the session token with Clerk's Python SDK (`clerk-backend-api`). Check the signature against Clerk's public key, the expiry, and the allowed origins of the dashboard.
- FastAPI dependencies: `current_user`, `current_org` and `require_role("org:admin")`. A request with no active organization is rejected.
- Every database query takes the organization from the token, never from the request body or URL.

**Roles**

| Role | Can do |
|---|---|
| `org:admin` | Add and remove repos, change alert settings, trigger runs, invite members |
| `org:auditor` (custom) | Approve reports, mark findings as accepted risk or false positive |
| `org:member` | View runs and findings, download reports |

**Ties into the agent**
- The LangGraph human-in-the-loop step from 5.4 becomes a real approval. A run pauses before the report is sent, and an `org:auditor` approves it in the dashboard.
- The approver's name and approval time from Clerk go into the PDF signature block, which makes the report more audit-ready.
- A manual run records the user who triggered it. Scheduled runs record "schedule".

**Webhooks**
- `POST /webhooks/clerk` checks the Svix signature with the `svix` Python package, then copies `user.*`, `organization.*` and `organizationMembership.*` events into Postgres.
- Use the `svix-id` header as an idempotency key, because Svix retries failed deliveries.

**Secrets:** `CLERK_PUBLISHABLE_KEY` and `CLERK_SECRET_KEY` on Vercel. `CLERK_SECRET_KEY`, `CLERK_JWT_KEY` and `CLERK_WEBHOOK_SIGNING_SECRET` on Fly.

---

## 6. Evaluation (what makes this portfolio-grade)

- **Golden set:** 25–40 seeded violations in the demo repo, each labelled with its obligation, file and lines. Add compliant decoys that look like violations.
- **Metrics:** precision, recall and F1 on findings; citation accuracy (does the cited section really support the finding); RAG recall@k on 50 hand-written legal questions.
- **Cost and speed:** tokens and time per audit run.
- Run evals in CI on every PR and publish the scores in the README.
- **Tenant isolation tests:** create two organizations in tests and check that neither can read the other's repos, findings or reports through any endpoint.

---

## 7. Milestones

| Phase | Deliverable | Est. |
|---|---|---|
| **0. Setup** | Repo, docker-compose with Postgres and Redis, config, CI with lint and tests | 0.5 day |
| **1. Scrapers** | 3 sources working, raw files stored, change detection | 2 days |
| **2. Legal RAG** | Structured chunking, embeddings, hybrid search, obligation extraction, recall@k eval | 3 days |
| **3. Code index** | tree-sitter chunks, Semgrep privacy rules, demo repo with seeded violations | 2 days |
| **4. Agent** | LangGraph graph end to end on the demo repo, checkpointer, tracing | 3 days |
| **5. Report and alerts** | WeasyPrint PDF, Slack and email | 1.5 days |
| **6. Pipeline** | BullMQ queues and daily schedule, FastAPI endpoints | 1.5 days |
| **6b. Clerk and dashboard** | Clerk app with Organizations and roles, token check in FastAPI, webhook sync, Next.js pages, report approval, tenant isolation tests | 3 days |
| **7. Deploy** | Fly.io running daily, dashboard on Vercel, secrets, monitoring | 1 day |
| **8. Evals and polish** | Golden set scores, README, architecture diagram, sample PDF | 2 days |
| **9. Demo** | Loom video, GitHub release | 0.5 day |

**Total:** about 20 working days, or 4–5 weeks part time.

**Thin slice first:** before building every phase fully, get one source, one regulation, one obligation, one seeded violation and one PDF working end to end. Then widen each stage. Add Clerk after the pipeline works, but put `org_id` on the tables from Phase 0 so you don't need a migration later.

---

## 8. Demo script (Loom, 4–5 minutes)

1. The problem: legal teams review rule changes by hand against fast-moving codebases.
2. The architecture diagram, in 30 seconds.
3. Sign in to the dashboard and switch between two organizations. Show that each one sees only its own repos.
4. Trigger a run live. Show the scraper finding an amendment.
5. Show the LangGraph trace in LangSmith, with parallel obligation checks.
6. A Slack alert arrives for a critical finding.
7. Approve the report as an auditor. Open the PDF and walk through one finding from the regulation citation to the exact code lines and the signature block.
8. Show the eval scores and the cost per run.

---

## 9. Risks and mitigations

| Risk | Mitigation |
|---|---|
| Sites block scraping or change layout | Prefer official APIs, keep selectors in config, add scraper health checks and alerts |
| LLM hallucinates violations | Static evidence first, a verify step, confidence thresholds, "needs review" status, measured precision |
| Legal claims could mislead | Clear disclaimer in the report: decision support, not legal advice |
| Cost grows on large repos | Re-audit only changed obligations, filter with static checks first, cache embeddings by content hash |
| WeasyPrint and Playwright system libraries on Fly | Use a tested Dockerfile early, in Phase 0 |
| One team sees another team's findings | Take the organization only from the verified token, filter every query by it, and run tenant isolation tests in CI |
| Clerk webhooks arrive late or twice | Treat the token as the source of truth for access. Use webhooks only for display data, and deduplicate by `svix-id` |

---

## 10. On the "40+ hours/week saved" claim

Back this number with your own measurement, or reword it. One option is to time a manual review of 10 rule changes against the demo repo, then compare it with the agent's run time. Put the method in the README. A sourced claim reads much stronger to reviewers than a bare one.

---

## 11. Stretch goals
- Auto-generated fix PRs for simple violations.
- Watch GitHub webhooks so each new commit is audited against the current rules.
- Dashboard charts showing findings over time and how often findings are accepted.
- Enterprise SSO through Clerk for larger legal teams.
- More regulation packs: SOC 2, PCI DSS, EU AI Act.
