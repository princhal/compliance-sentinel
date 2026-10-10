---
name: parallel-phase-shipping
description: "Ship a project phase-by-phase with parallel subagents inside each phase, where every feature must pass a strict gate (implement → test → commit → push → CI → deploy → live E2E) before the next feature starts. Use when the user wants to build a product systematically, ship incrementally, run multiple independent features in parallel, or asks for a 'phase-wise plan' / 'parallel agent plan' / 'feature-by-feature' workflow. Ensures every feature is verified on a real server before moving on, not just locally."
risk: medium
source: ChairOS authored
date_added: "2026-05-08"
when_to_use: any time the user asks for a phased build, parallel-subagent plan, feature-by-feature shipping, or wants live-server verification per feature
---

# Parallel Phase Shipping

The user's preferred build rhythm is:

1. **A phased plan.** Break the project into 3–6 sequential phases. Each phase has a clear exit criterion.
2. **Parallel subagents inside a phase.** Within a phase, identify which features are truly independent and dispatch them to separate subagents to ship simultaneously.
3. **A strict per-feature gate.** Every feature must clear the gate before the next feature starts:
   `implement → tests → lint/typecheck → commit → push → CI green → deploy to live server → E2E test on live URL → mark done`
4. **No exceptions.** "It works locally" is not the gate. Live E2E is the gate.

Operate this skill like a release train. The point is not speed-of-typing; it's speed-of-verified-shipping.

---

## When this skill fires

Trigger if the user says any of:

- "phase-wise plan", "phased plan", "phase plan"
- "parallel subagents", "dispatch in parallel", "build in parallel"
- "ship feature by feature", "feature-by-feature", "one feature at a time"
- "implement, commit, push, deploy, then test"
- "build [project] systematically"
- "ship the MVP", "build out [phase X]"
- They've already given you a spec or introspection and now want execution

If the user asks only to _plan_ (no implementation), use the `writing-plans` skill instead. If they ask only to _implement one specific change_, do it directly without invoking this loop.

---

## The mental model

```
PHASE 1 ───────────────────────► PHASE 2 ───────────────────────► PHASE 3
  │                                │                                │
  ├── feature A (subagent) ──┐     ├── feature D (subagent) ──┐     ├── ...
  ├── feature B (subagent) ──┼─►   ├── feature E (subagent) ──┼─►
  └── feature C (subagent) ──┘     └── feature F (subagent) ──┘
       │                                │
       └─ each one passes the gate      └─ each one passes the gate
          before phase advances            before phase advances
```

- **Phases are sequential** — Phase N+1 depends on Phase N's work being live and verified.
- **Features inside a phase are parallel where independent**, sequential where they share state (DB schema, shared file, API contract).
- **The gate is per-feature**, not per-phase. A feature that fails the gate is rolled back and retried; the rest of the phase keeps moving.

---

## The per-feature gate (memorize this)

Every feature passes through these 11 stations, in order, no skipping:

| #   | Station                    | Tool / skill                                                                      | Failure means                                               |
| --- | -------------------------- | --------------------------------------------------------------------------------- | ----------------------------------------------------------- |
| 1   | **Plan slot in phase**     | TodoWrite                                                                         | Feature wasn't actually scoped; pause and re-plan           |
| 2   | **Implement**              | direct edit or `Task` subagent                                                    | Bugs surface; iterate                                       |
| 3   | **Tests written**          | `writing-tests`, `test-driven-development`                                        | Coverage gap; add tests before merge                        |
| 4   | **Lint + typecheck clean** | `auto-type-checking`, `tk-biome` if available                                     | Fix before commit                                           |
| 5   | **Local smoke pass**       | Run dev server, hit the new flow once                                             | Regression; fix                                             |
| 6   | **Commit**                 | `writing-commit-messages`                                                         | Bad message; rewrite                                        |
| 7   | **Push**                   | `git push` (use `git-ops` skill if it exists)                                     | Auth, network                                               |
| 8   | **CI green**               | `babysitting-pr`, `parallel-ci-triage` if multi-job                               | Fix forward                                                 |
| 9   | **Deploy to live**         | Vercel preview, Fly app, staging URL                                              | Build fails on prod env (env vars, runtime mismatch)        |
| 10  | **E2E on live URL**        | `webapp-testing`, `anthropic-webapp-testing`, Playwright pointing at the live URL | Bug only reproduces with prod data/network                  |
| 11  | **Verification**           | `verification-before-completion`                                                  | Run the verification command, observe the output, mark done |

**Until station 11 prints success, the feature is not done.** Don't move to the next feature.

---

## How to dispatch parallel subagents inside a phase

### Step A — Build the parallelism map

For each phase, list every feature, then mark each as:

- **`[par]`** — independent. No shared files, no schema overlap, no API contract collision. Can run in a separate subagent.
- **`[seq]`** — depends on a previous feature in this phase. Must wait.
- **`[gate]`** — a synchronization point. Block until all preceding `[par]` features pass their gate.

```
Phase 2 — Core flows
  [par]  Chair CRUD              ──┐
  [par]  Salon CRUD              ──┼──► [gate] all schemas & APIs live
  [par]  Contract CRUD           ──┘
  [seq]  Session report form         (depends on Chair + Salon CRUD)
  [par]  Payout calc lib         ──┐
  [par]  Razorpay webhook        ──┼──► [gate] payout system testable end-to-end
  [par]  Razorpay payout route   ──┘
  [seq]  BullMQ payout worker        (depends on payout route)
  [par]  Contract PDF gen        ──┐
  [par]  Invoice PDF gen         ──┘
  [gate] full happy-path E2E on live
```

### Step B — Dispatch the `[par]` block

For each independent feature, spawn a `Task` subagent. **Two non-negotiable rules:**

1. **Each parallel subagent gets its own git worktree.** Use `using-git-worktrees`. This prevents file-level merge conflicts at the cost of some disk space. Trying to parallelize without worktrees on the same checkout is the most common way this workflow self-destructs.
2. **Each subagent owns its full feature gate.** It is responsible for stations 2–11 of the gate, not just the implementation. The parent agent only owns the dispatch and the merge.

Dispatch pattern (parent agent):

```
For each [par] feature in phase:
  - Create worktree: feature/<name>
  - Spawn Task subagent with:
      • subagent_type = "generalPurpose"
      • prompt = "<full feature spec> + 'Pass the per-feature gate stations 2-11 from .claude/skills/parallel-phase-shipping/SKILL.md. Do not return until station 11 prints success.'"
      • run_in_background = true
  - TodoWrite: mark feature as in_progress

Wait for completion notifications.

For each completed feature:
  - Verify the live URL responds correctly (one curl/HEAD check)
  - Merge worktree branch into main
  - TodoWrite: mark feature as completed
  - Run a quick smoke E2E that touches all the parallel features together
```

### Step C — Synchronize at `[gate]`

Don't advance to `[seq]` features until every `[par]` predecessor has its branch merged AND the live server passes the cross-feature smoke E2E. If a parallel feature fails its gate, fix it (or roll back its branch and replan) before opening the gate.

---

## Phase rhythm (the outer loop)

```
For each phase in plan:
  1. Phase kickoff:
     - Read the phase spec
     - Build the parallelism map (Step A above)
     - TodoWrite: one todo per feature with [par]/[seq]/[gate] label
     - Print the map for the user; let them confirm before dispatching

  2. Phase execution:
     - For each [par] block: dispatch parallel subagents (Step B)
     - At each [gate]: synchronize, run cross-feature E2E, fix anything broken
     - For each [seq] feature: implement directly or single subagent

  3. Phase closeout:
     - Run a full happy-path E2E on the live server covering everything in the phase
     - Tag the deploy: `git tag phase-N-complete`
     - Update AGENTS.md or CHANGELOG.md with what shipped in this phase
     - Brief retrospective: what new patterns emerged? Worth a Cursor rule?
     - Move to next phase only after the user confirms (or auto-advance if they said "go all the way")
```

---

## Live E2E — what "test on live server" actually means

This is the most-skipped station. The bar:

1. **Run against the deployed URL** (Vercel preview / staging / production), not localhost.
2. **Use real auth** — request an Auth.js magic link to a seeded test inbox (or use Playwright to read the AgentMail inbox programmatically and click the link).
3. **Touch the database** — create real rows; clean up after if it's prod, leave them if it's a sandbox env.
4. **Cover the happy path + at least one error path** for the new feature.

### Default tooling

- **Playwright pointed at the live URL.** Set `baseURL` from env: `PLAYWRIGHT_BASE_URL=https://<your-vercel-app>.vercel.app pnpm playwright test`.
- **Webhook events:** trigger from the third party's dashboard (Razorpay test mode → "Trigger event" in Webhook settings).
- **For background jobs:** queue a real job, watch BullMQ admin or Fly logs to see it run.

### Live E2E template (per feature)

```typescript
// e2e/phase-<n>/<feature>.spec.ts
import { test, expect } from "@playwright/test";

test("@phase-2 @feature:salon-crud creates a salon partner end-to-end", async ({ page }) => {
  await page.goto("/sign-in");
  await page.fill('[name="email"]', process.env.E2E_OWNER_EMAIL!);
  // Auth.js magic link: request, then poll AgentMail inbox for the verify link, then visit it
  // ...
  await page.goto("/salons/invite");
  await page.fill('[name="salonName"]', `Test Salon ${Date.now()}`);
  await page.fill('[name="email"]', `e2e+${Date.now()}@example.com`);
  await page.click('button[type="submit"]');
  await expect(page.getByText("Invite sent")).toBeVisible();

  // Optional: assert via API that the SalonPartner row exists
  const res = await page.request.get("/api/salons");
  expect(res.ok()).toBeTruthy();
});
```

If the test passes against the deployed URL, the feature is done. If not, you don't have a feature; you have a regression.

---

## Common failure modes (and how to spot them)

| Symptom                                                                                       | Root cause                                             | Fix                                                                                              |
| --------------------------------------------------------------------------------------------- | ------------------------------------------------------ | ------------------------------------------------------------------------------------------------ |
| Two parallel agents step on each other's `prisma/schema.prisma`                               | They're not really independent; schema is shared state | Mark one as `[seq]` after the other, or split the schema migration into one upfront `[seq]` task |
| Parallel agents work but merging surfaces conflicts in `pnpm-lock.yaml` / `package-lock.json` | Each added different deps                              | Resolve at `[gate]` by running `pnpm install` after merge; commit the regenerated lockfile       |
| Feature passes locally, fails on Vercel                                                       | Env var missing in Vercel project settings             | Add a station-9.5 check: `vercel env ls` before deploying                                        |
| Live E2E flaky                                                                                | Cold-start latency, missing test data                  | Bump Playwright timeouts for cold paths; seed test data in a setup hook                          |
| CI green but live deploy doesn't update                                                       | Wrong deploy hook, branch not auto-deploy              | Verify Vercel git integration; check the deploy hook URL in build logs                           |
| Webhook E2E impossible because Razorpay can't reach localhost                                 | Trying to live-test webhooks against a local box       | Use the deployed URL only; never run webhook E2E on localhost                                    |
| Subagent claims "done" but station 11 never ran                                               | The subagent skipped verification                      | Reject the result; respawn with explicit "show me the verification output" instruction           |
| Phase grows unbounded                                                                         | New features keep getting added mid-phase              | Push new asks to a future phase; close the current phase first                                   |

---

## Templates

### Template 1 — Phase kickoff message (parent agent uses this)

```
## Phase <N>: <name>

### Goal
<one sentence>

### Exit criterion
<measurable; e.g. "an owner can complete the full month-end payout flow on live URL">

### Parallelism map
- [par] <feature 1> — owner: subagent A — branch: feature/<name-1>
- [par] <feature 2> — owner: subagent B — branch: feature/<name-2>
- [par] <feature 3> — owner: subagent C — branch: feature/<name-3>
- [gate] cross-feature E2E
- [seq] <feature 4> — depends on 1+2
- [par] <feature 5> — owner: subagent D — branch: feature/<name-5>
- [par] <feature 6> — owner: subagent E — branch: feature/<name-6>
- [gate] phase E2E

### Tooling for each subagent
- Reads spec from @<spec-file>
- Owns full per-feature gate (stations 2–11)
- Reports back with: branch name, commit SHAs, deploy URL, E2E command, verification output
```

### Template 2 — Per-feature commit message

Conventional commits, one feature per commit (or short series, all on the feature branch). The body always references the phase + feature name + station 11 verification.

```
feat(<phase-N>/<feature>): <one-line description>

What:
- <bullet of what shipped>

Why:
- <bullet of business reason; reference the phase exit criterion>

Verified on live (<URL>):
- E2E test: e2e/<phase>/<feature>.spec.ts → 1 passed
- Manual smoke: <one-line of what you clicked>

Refs: phase-<N>, plan @<plan-file>
```

### Template 3 — The verification command (run before declaring done)

```bash
# Substitute project-specific values
BASE_URL="${VERCEL_PREVIEW_URL:-https://<your-vercel-app>.vercel.app}"
FEATURE_TAG="@phase-2 @feature:salon-crud"

# 1. Health check
curl -fsS "$BASE_URL/api/health" || { echo "live URL down"; exit 1; }

# 2. Run the live E2E for this feature only
PLAYWRIGHT_BASE_URL="$BASE_URL" pnpm playwright test --grep "$FEATURE_TAG" --reporter=line

# 3. If exit 0, mark feature done in TodoWrite. Else, fix and retry.
```

### Template 4 — Subagent dispatch prompt (parent → child)

When spawning a `Task` subagent for a `[par]` feature, the prompt should always include this footer:

```
You are responsible for shipping <feature> through stations 2–11 of the per-feature gate
defined in .claude/skills/parallel-phase-shipping/SKILL.md.

Required deliverables in your final response:
1. Branch name (feature/<slug>)
2. List of commit SHAs you pushed
3. Deploy URL of the live preview
4. Exact `pnpm playwright test --grep ...` command that proves it works
5. Output of that command (must show "passed")
6. Any open follow-up tasks for the parent to handle at the [gate]

Do NOT return success until you have run the live E2E against the deploy URL and seen it pass.
"It works locally" is not acceptance.
```

---

## ChairOS phase breakdown — worked example

Use this as the starting plan; refine the parallelism map per phase before dispatch.

### Phase 0 — Pre-flight (mostly already done in the introspection)

- [seq] Apply schema corrections from introspection (BigInt paise, SessionEvent, WebhookEvent, AuditLog, idempotency keys)
- [seq] Confirm RazorpayX (not Route) is the chosen payouts product
- [seq] Decide PII strategy: store only Razorpay IDs, not bank numbers
- [gate] Schema and decisions documented in AGENTS.md / CHANGELOG.md

### Phase 1 — Scaffold

- [seq] `pnpm create next-app` + Tailwind + shadcn baseline + Biome
- [seq] Prisma schema + first migration + seed
- [par] Auth.js v5 setup (route handler + options + middleware, EmailProvider wired to AgentMail, role assignment in `events.createUser`) // env validation lib (`zod` parsed env) // Sentry + PostHog wiring
- [par] (auth) layouts + sign-in/up // (owner) shell + sidebar // (salon) shell // (technician) shell
- [par] `lib/currency.ts` (BigInt paise utils) // `lib/revenue.ts` (with negative-share fix + tests) // `lib/razorpay.ts` client
- [gate] Live E2E: each role can sign up via Auth.js magic link (delivered through AgentMail) and lands on the right shell on the deployed URL
- Skills to invoke: `nextjs-best-practices`, `prisma-expert`, `auth-implementation-patterns`, `shadcn`, `tailwind-design-system`, `zod-validation-expert`, `agentmail` (source skills), `adding-error-tracking`, `adding-analytics`

### Phase 2 — Core flows (the meat)

- [par] Chair CRUD (owner) // Salon CRUD (owner) // Technician CRUD (owner)
- [par] Contract CRUD + PDF generation // Document upload to Supabase Storage
- [gate] All entity APIs return 200 on live; basic admin pages render
- [par] Session report submission (salon UI + API) // Session report verification (owner UI + API) // Daily breakdown JSON validation (zod schema)
- [par] Razorpay Contact + Fund Account onboarding (in salon onboarding wizard) // RazorpayX payout API route (with idempotency header) // Razorpay webhook handler (with `WebhookEvent` dedup)
- [seq] BullMQ workers: payout processor + reminder + maintenance scheduler
- [par] GST tax invoice PDF generator // Audit log writer for payout events
- [gate] Live E2E: invite salon → onboard → submit session report → owner verifies → payout processes via RazorpayX (test mode) → invoice generated → audit row written
- Skills to invoke: `razorpay-integration`, `bullmq-specialist`, `anthropic-pdf`, `ws-payment-processing/skills/billing-automation`, `ws-signed-audit-trails`, `saas-multi-tenant`

### Phase 3 — AI insights

- [par] Claude prompt for `generateFleetInsight` (with prompt caching) // Claude prompt for `detectRevenueAnomaly` // AIInsight model migration with FKs to chair/salon
- [seq] Weekly cron that generates fleet insight + writes to AIInsight
- [par] Insights UI page (owner) // Anomaly toast/notification (in-app)
- [gate] Live E2E: trigger insight generation, see it on the live insights page; trigger anomaly via test data, see notification
- Skills to invoke: `anthropic-claude-api`, `ws-llm-application-dev/skills/prompt-engineering-patterns`, `ws-llm-application-dev/skills/llm-evaluation`

### Phase 4 — Quality, security, ship

- [par] Security audit (rate limit webhooks, RLS or query-layer tenant guards, secret rotation) // Performance audit (Recharts virtualization, query N+1) // Accessibility audit
- [par] Reconciliation script (Razorpay settlements ↔ Payout sum) // TDS quarterly export script // Penny-drop validation in onboarding
- [seq] Production deploy: domain, env vars, alerting, runbook
- [seq] Soft launch with 1 real salon partner, watch dashboards for 1 week
- [gate] Production deploy stable for 7 days with no payout incidents
- Skills to invoke: `auditing-security`, `auditing-performance`, `accessibility-auditing`, `ws-security-scanning`, `ws-incident-response`, `ws-deployment-strategies`, `verification-before-completion`

---

## Anti-patterns (don't do these)

- **"Let me get all features implemented first, then I'll commit and test."** No. The gate is per-feature.
- **"I'll skip the live E2E because the unit tests pass."** No. Live E2E is station 11. It catches env config, build issues, deploy issues, and prod-only race conditions that nothing else catches.
- **"I'll dispatch 6 parallel subagents on the same checkout."** No. Use git worktrees or sequence them.
- **"This phase is taking too long, let me push the cross-feature E2E to the next phase."** No. The phase isn't done until its gate passes. Half-done phases compound.
- **"The deploy is fine, the build went green."** Build green ≠ feature working. Run the E2E against the live URL.
- **"Let me bundle 3 features into one PR for efficiency."** No. Per-feature gate requires per-feature shippability. Bundling makes rollback impossible.

---

## Skills this one composes with (call them as needed)

- `writing-plans` — write the phase plan before kickoff
- `dispatching-parallel-agents` — the dispatch primitive
- `using-git-worktrees` — required for true parallel work
- `subagent-driven-development` — patterns for spawning + handing off
- `writing-tests`, `test-driven-development`, `condition-based-waiting` — station 3
- `auto-type-checking`, `tk-biome` — station 4
- `writing-commit-messages` — station 6
- `creating-pr`, `babysitting-pr`, `parallel-ci-triage` — stations 7–8
- `monitoring-terminal-errors`, `tailing-build-output` — station 9
- `webapp-testing`, `anthropic-webapp-testing` — station 10 (Playwright on live URL)
- `verification-before-completion` — station 11
- `root-cause-tracing`, `systematic-debugging`, `when-stuck` — when a feature fails the gate

---

## Quick start (read this when invoked)

1. Read the project spec / introspection file.
2. If no phased plan exists, draft one (use `writing-plans`). Show it to the user; get a "go".
3. Open Phase 1: build the parallelism map. Show it. Get a "go".
4. Dispatch the first `[par]` block as parallel subagents in git worktrees.
5. As each finishes, verify station 11 and merge.
6. At each `[gate]`, run the cross-feature E2E. Don't advance until it's green on live.
7. Repeat per phase. Tag each phase complete (`git tag phase-N-complete`).
8. Don't end the loop until every phase exit criterion has been observed live.

---

_Authored 2026-05-08 for the ChairOS workflow. The opinion is: ship verified, in parallel where safe, in sequence where shared. Anything else is theatre._
