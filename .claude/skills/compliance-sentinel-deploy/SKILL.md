---
name: compliance-sentinel-deploy
description: Deploy Compliance Sentinel to production - the FastAPI api and BullMQ worker on Fly.io, the Next.js dashboard in web/ on Vercel. Use when deploying, setting Fly secrets or Vercel env vars, running migrations in production, or troubleshooting a deploy. Adapted from the turfstack-deploy skill in private-skills-main.
---

# Compliance Sentinel Deployment

## Architecture

```
Vercel (web/, Next.js + Clerk) --Bearer Clerk token--> Fly app (fra)
                                                        ├─ api    process: FastAPI, port 8080, auto-stops when idle
                                                        └─ worker process: BullMQ, must stay up (daily scrape + audits)
                                                             ├─ Postgres with pgvector (Fly Postgres or Neon)
                                                             ├─ Redis (Upstash via `fly redis create`)
                                                             └─ Tigris bucket (PDF reports, raw documents)
```

Region is `fra`: EU personal data stays in the EU. Never change it casually.

## Resolve names first

| Value | Where it comes from |
|---|---|
| `FLY_APP` | `grep '^app' fly.toml` (Fly app names are global; pick another if taken and update fly.toml) |
| Vercel project / scope | `web/.vercel/project.json` after `vercel link`, or `vercel whoami` |

## Backend: Fly.io

Deploy from the repo root (the Dockerfile and fly.toml live there).

### First-time setup

```bash
fly launch --no-deploy --copy-config --name $FLY_APP --region fra
# Postgres: Fly Postgres in fra, or a Neon project in an EU region (use the pooled URL).
# Then: CREATE EXTENSION IF NOT EXISTS vector;
fly redis create            # Upstash, region fra
fly storage create -a $FLY_APP   # Tigris: sets AWS_ACCESS_KEY_ID, AWS_SECRET_ACCESS_KEY,
                                 # AWS_ENDPOINT_URL_S3, AWS_REGION, BUCKET_NAME secrets
```

### Secrets

The app refuses to start with `ENVIRONMENT=production` and `AUTH_MODE=dev`, or without Clerk keys.
`ENVIRONMENT`, `AUTH_MODE`, `STORAGE_BACKEND` and `REQUIRE_APPROVAL` are already in `fly.toml [env]`.

| Secret | Required | Notes |
|---|---|---|
| `DATABASE_URL` | yes | `postgresql+psycopg://...` - the `+psycopg` driver prefix is required |
| `REDIS_URL` | yes | from `fly redis create` / `fly redis status` |
| `S3_BUCKET` | yes | same value as Tigris's `BUCKET_NAME` |
| `CLERK_SECRET_KEY` | yes (or `CLERK_JWT_KEY`) | must be from the same Clerk instance as the dashboard |
| `CLERK_AUTHORIZED_PARTIES` | yes | the Vercel URL, comma-separated; also drives CORS |
| `DASHBOARD_URL` | yes | the Vercel URL, used in alert links |
| `INTERNAL_API_TOKEN` | yes | generate with `openssl rand -hex 32` |
| `CLERK_WEBHOOK_SIGNING_SECRET` | for webhooks | without it `POST /webhooks/clerk` rejects events |
| `ANTHROPIC_API_KEY` | optional | without it the offline heuristic engine runs |
| `VOYAGE_API_KEY` | optional | without it the hash embedder runs (weaker retrieval) |
| `RESEND_API_KEY` | optional | email alerts |

Set them without echoing values into the terminal or chat: put them in a gitignored file and run
`fly secrets import -a $FLY_APP < .env.production`, or `fly secrets set --stage ...` before the first deploy.

### Deploy

```bash
fly deploy --remote-only --ha=false -a $FLY_APP
```

- `--ha=false`: otherwise Fly creates two machines per process group.
- The `release_command` runs `sentinel db-upgrade && sentinel scheduler`: migrations and the daily
  scrape schedule happen on every deploy. A failed migration aborts the deploy.
- The image is based on the Playwright image; its tag must match `playwright` in `uv.lock`.

### Verify

```bash
fly status -a $FLY_APP                        # api and worker machines, health checks
curl https://$FLY_APP.fly.dev/health          # {"status":"ok"}
curl -i https://$FLY_APP.fly.dev/runs         # 401 without a token = Clerk auth is on
fly logs -a $FLY_APP --no-tail | grep -i worker
```

## Dashboard: Vercel

The Vercel project's root directory is `web/`.

```bash
cd web
vercel link --yes
# Set each value without trailing newlines (printf, not echo):
printf '%s' "https://$FLY_APP.fly.dev" | vercel env add SENTINEL_API_URL production
printf 'clerk' | vercel env add SENTINEL_AUTH_MODE production
# plus NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY, CLERK_SECRET_KEY and the NEXT_PUBLIC_CLERK_SIGN_IN/UP URLs
vercel --prod --yes
```

`SENTINEL_AUTH_MODE` must be `clerk` in production; `dev` makes the dashboard send `x-dev-*`
headers that a production API ignores.

After the first Vercel deploy, put its URL into the Fly secrets `CLERK_AUTHORIZED_PARTIES` and
`DASHBOARD_URL` (this redeploys the Fly machines).

## Deployment order

1. Fly backend (migrations run in the release step)
2. Vercel dashboard
3. Fly secrets updated with the Vercel URL
4. Clerk: add the Vercel domain, create the `org:auditor` role, point a webhook at `https://$FLY_APP.fly.dev/webhooks/clerk`

## Smoke test

1. `/health` on Fly returns 200; `/runs` without a token returns 401.
2. Vercel URL loads and redirects to sign-in; sign in, select an org.
3. Add a repo and trigger a run; watch it in `fly logs` and on `/runs`.

## Troubleshooting

| Issue | Check |
|---|---|
| Release command fails | `fly logs --no-tail`; usually `DATABASE_URL` wrong or `vector` extension missing |
| `Clerk keys are required in production` | `CLERK_SECRET_KEY` or `CLERK_JWT_KEY` not set on Fly |
| Dashboard gets 401 from API | Clerk keys on Fly and Vercel from different instances, or Vercel URL missing in `CLERK_AUTHORIZED_PARTIES` |
| CORS errors | `CLERK_AUTHORIZED_PARTIES` must contain the exact dashboard origin |
| Runs stay queued | worker machine stopped or `REDIS_URL` wrong: `fly machines list` |
| Redis bill growing while idle | BullMQ polling; see the `idle-cost-audit` skill |
| PDF upload fails | Tigris secrets missing or `S3_BUCKET` differs from `BUCKET_NAME` |

## Key commands

```bash
fly status -a $FLY_APP
fly logs -a $FLY_APP --no-tail
fly machines list -a $FLY_APP
fly secrets list -a $FLY_APP
fly ssh console -a $FLY_APP -C "sentinel db-upgrade"
vercel ls
```
