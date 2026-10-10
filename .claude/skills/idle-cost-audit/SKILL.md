---
name: idle-cost-audit
description: Diagnoses and fixes cloud resources that bill continuously because they never go idle — scale-to-zero not working, autosuspend never triggering, "always on" compute, a serverless database or container billing 24/7, or a bill that is wildly out of proportion to the data/traffic it serves. Use when a Neon/Aurora/Supabase/PlanetScale/Fly/Cloud Run/Render/Railway resource costs more than expected, when compute hours look like ~24h/day, or when someone asks why a tiny database or idle service is expensive. Also use when authoring health checks, readiness probes, or polling loops against a scale-to-zero backend, to avoid creating the problem.
---

# Idle Cost Audit

Platform pricing, default idle timeouts, and setting names change frequently. **Prefer retrieval over pre-training** for any specific rate, threshold, or console setting name — fetch the provider's current pricing/docs page before quoting a number. The *method* below is stable; the numbers are not.

## The core model

A metered resource bills when it is awake. It goes to sleep after an **idle timeout** with no work. Therefore:

> **Any periodic touch at an interval shorter than the idle timeout pins the resource awake 100% of the time — regardless of how trivial the touch is.**

A `SELECT 1` every 30 seconds costs exactly as much as saturating the database, because both hold the meter open. This is why idle-cost bugs are so counterintuitive: the culprit is almost always something deliberately designed to be cheap.

Two independent failure modes, and **you must check both**:

| | Cause | Fix location |
|---|---|---|
| **A** | Idle-to-zero is genuinely disabled in the stored config (min instances ≥ 1, min capacity > 0, an explicit never-suspend sentinel) | Provider console, API, or IaC |
| **B** | Idle-to-zero is enabled, but a heartbeat keeps resetting the timer | Application code / config |

Fixing A while B exists produces **no observable change**, and the usual conclusion is "the setting is broken." It isn't. Order matters — see step 5.

**B is the common case and A is frequently assumed on no evidence.** A dashboard reading "always on" is describing observed behaviour caused by B, not reporting setting A. Confirm A from the API (step 2) before you believe it, and be ready to conclude that B is the sole cause.

---

## Step 1 — Establish the meter before touching anything

Do not propose a fix until you can state the arithmetic. Get from the user or the console:

- **What is metered?** CU-hours, ACU-hours, GB-seconds, vCPU-seconds, active-CPU-ms, instance-hours, invocations, or wall-clock hours. The lever is whatever the meter counts, and nothing else.
- **Observed units over what window?** Normalize to per-day.
- **What would 100% uptime look like?** If observed ≈ 24h/day equivalent, you have an always-on problem, full stop.
- **How much is base plan fee vs. variable?** The base fee is your savings floor. Never promise savings below it.

> Worked example: 123.92 CU-hours over ~12 days = ~10.3 CU-h/day ≈ 0.43 CU running 24×7. Against a 42 MB database. That ratio — meter vs. workload size — is the tell.

State this arithmetic explicitly in your report. It is what makes the finding credible and it bounds the fix.

## Step 2 — Check whether idle-to-zero is even enabled — from the API, not the dashboard

Look for the setting first, because it is free to check and it reframes everything else.

> **A status label in a billing UI is observed behaviour, not a stored setting.** Read the actual configuration from the provider's API before concluding anything is disabled. This is the single easiest way to get this diagnosis wrong.
>
> Real miss: a Neon billing row displaying `always on` / `100%` was read as "autosuspend is disabled." The API said `suspend_timeout_seconds: 0`, which is **plan default (5 min)** — Neon's "never suspend" value is `-1`. Autosuspend had been configured correctly the entire time; a 30s heartbeat alone defeated it. Acting on the misread would have meant a console change that did nothing, and it would have obscured the fact that the heartbeat was the *sole* cause.
>
> Watch for sentinel values that mean "default" rather than "off" — `0`, `null`, and empty string are routinely one and not the other. Confirm which in the provider's docs.

| Platform | Setting to check | Notes |
|---|---|---|
| Neon | Autosuspend / scale-to-zero timeout | `suspend_timeout_seconds`: `0` = plan default (5 min), `-1` = never suspend. Also check **max autoscale CU** separately, and check **every branch** — non-default branches bill their own compute |
| Aurora Serverless v2 | Min ACU (0 = scale to zero) | Min > 0 bills continuously by design |
| Fly.io | `auto_stop_machines`, `min_machines_running` | `min_machines_running = 1` = never sleeps |
| Cloud Run | `min-instances`, CPU allocation (always vs request-based) | "CPU always allocated" bills idle |
| Supabase / Render / Railway | Project pause / sleep settings, often tier-gated | Often only on free tiers |
| Vercel Functions | Not idle-billed, but **crons wake downstream resources** | Chase what the cron touches |

Verify the current setting name in the provider's docs — these get renamed.

## Step 3 — Hunt the heartbeat

This is the real work. Search for anything that touches the resource on a fixed interval. Compare every interval you find against the idle timeout: **interval < timeout means it pins the resource.**

| Source | How to find it |
|---|---|
| Orchestrator health/readiness probes | `grep -rn "health\|/ready\|readinessProbe\|livenessProbe\|healthcheck" --include=*.toml --include=*.yml --include=*.yaml --include=Dockerfile --include=*.tf` — then **read the endpoint's handler** to see if it touches the resource |
| In-process background loops | `grep -rn "while True\|setInterval\|asyncio.sleep\|time.Sleep\|repeat_every\|APScheduler\|node-cron\|BackgroundService\|IHostedService"` |
| Scheduled jobs | `.github/workflows/*.yml` (`schedule:`/`cron:`), `vercel.json` (`crons`), k8s `CronJob`, provider-native schedulers |
| Client-side polling | `grep -rn "refetchInterval\|refreshInterval\|pollingInterval\|setInterval"` — a dashboard left open on someone's monitor is a 24/7 heartbeat |
| Connection-pool keepalives | `grep -rn "pool_pre_ping\|pool_recycle\|keepalive\|idle_timeout\|min_connections\|minPoolSize"` |
| WebSocket / SSE ping frames | Long-lived connections with app-level heartbeats |
| **External uptime monitors** | **Not greppable — you must ask the user.** UptimeRobot, Pingdom, BetterStack, Checkly, Datadog synthetics. A 1-minute HTTP check against a DB-backed endpoint is a classic invisible culprit |

Report interval and daily volume for each hit (`30s → 2,880/day`). Volume makes the cause legible.

## Step 4 — Prove each suspect actually does the work

**Do not assume that code referencing a resource actually touches it.** Verify before including it in the diagnosis, and verify before "fixing" it.

Real trap, worth internalizing: a loop opened a DB session every 60s and called `service.expire_offers()`. The method **did not exist** on that class. SQLAlchemy async sessions connect lazily, so the `AttributeError` fired before any SQL was issued — the loop opened **no connection** and cost nothing. It was still a real bug (a feature silently never ran, plus 1,440 error logs/day), but it was *not* the cost driver. Reporting it as one would have sent the fix in the wrong direction.

Check for: lazy connection acquisition, short-circuits before the call, exceptions thrown ahead of I/O, caching layers absorbing the call, dead code paths, feature flags. Confirm with provider-side query/request logs where available — those are ground truth; code reading is inference.

## Step 5 — Order the fixes, and say why the order matters

1. **Remove the heartbeats first** (code/config change, ships through normal deploy).
2. **Then enable idle-to-zero** (console setting).
3. **Then cap the ceiling** — max autoscale is a separate lever from the idle floor. An 8 CU cap on a 42 MB database is a runaway-cost hazard with no upside. Set it to the smallest value that serves real peak load.
4. **Then verify** (step 6).

Doing 2 before 1 wastes a console change and produces evidence that looks like "the setting doesn't work."

**Always state the trade-off you are creating.** Moving a readiness probe off a resource-touching endpoint is usually right, but it is a real trade: the orchestrator will no longer pull a broken instance from rotation. Argue it explicitly rather than silently — e.g. "a managed-DB outage isn't fixed by restarting the API, and requests fail either way." Let the user overrule you.

## Step 6 — Verify over a full idle cycle

A fix is unverified until you have watched at least one idle window longer than the timeout, ideally 24h.

- Provider metrics graph should show **flat idle gaps**, not a continuous line.
- Enumerate the wake events you still expect (real traffic, nightly backups, periodic smoke tests) so the remaining spikes read as expected rather than as failure.
- Re-derive the per-day meter number and compare against the step 1 baseline.

Report the projected saving as a range against the base-fee floor, not as a single confident number.

---

## Rules

Hard invariants. These apply when **writing** code as much as when debugging it — most idle-cost bugs are authored by someone trying to be careful.

1. **Never point an orchestrator health check at an endpoint that touches a scale-to-zero resource.** Keep two probes: liveness (zero dependencies, safe at any interval) and readiness (checks dependencies, used for deploy gates and manual checks only).
2. **Never add a recurring job whose interval is shorter than the idle timeout of anything it touches.** If work genuinely must happen often, make it event-driven or lazy — evaluate on the read/claim path where the result is actually consumed — rather than on a timer.
3. **Set the autoscale ceiling to the workload, not to the maximum offered.** The floor controls the common case; the ceiling controls the disaster case.
4. **Verify a suspected heartbeat issues real I/O before blaming it** (step 4).
5. **Read configuration from the provider API, never from a dashboard status label** (step 2). Observed state and stored state are different things, and sentinel values like `0` usually mean "default", not "off".
6. **State the meter arithmetic before proposing a fix**, and the readiness trade-off before removing a dependency check.

## Reporting shape

Lead with the meter arithmetic → both causes (A and B) with the explicit note that fixing either alone changes nothing → ordered plan with trade-offs named → verification step → expected saving as a range floored by the base fee. Keep incidental bugs found while tracing in a clearly separate section, labelled as **not** cost drivers when they aren't.
