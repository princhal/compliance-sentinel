---
name: docs-implementation-sync
description: Keep project documentation synchronized with implementation changes. Use when code, APIs, workflows, deployment, auth, testing, or architecture changes are introduced and docs must be updated in the same session before completion.
---

# Docs Implementation Sync

## Purpose

Prevent documentation drift by enforcing a "code + docs together" workflow in every implementation task.

## When To Trigger

Apply this skill when any of the following changes:
- API routes, request/response contracts, auth behavior
- New module pages, user workflow, or role permissions
- Infra/deployment behavior, environment variables, CI/CD
- Test strategy, test commands, coverage reports
- Product capabilities visible to users or stakeholders

If uncertain, update docs.

## Required Workflow

Use this checklist and keep it current during implementation:

```text
Docs Sync Checklist
- [ ] Identify changed surfaces (API/UI/auth/deploy/test)
- [ ] Map each surface to docs that should change
- [ ] Update docs in the same PR/commit as code
- [ ] Add "what changed" + "how to verify" sections
- [ ] Remove stale statements and dead references
- [ ] Run quick validation commands
- [ ] Summarize doc updates in final response
```

## Doc Mapping Rules

### Product/Workflow Changes
- Update `README.md`
- Add or update detailed docs under `docs/`

### Deploy/Infra/Runtime Changes
- Update `DEPLOYMENT.md`
- Update deployment runbooks under `docs/`

### Test and Quality Changes
- Update test commands in `package.json` references
- Update `tests/README.md` and generated reports like `E2E_COVERAGE.md` if relevant

### Major Decision/Tradeoff
- Add short rationale section to the touched doc
- Include rollback/known-gap notes when applicable

## Writing Standard

Every doc update should include:
1. **Current behavior** (what it does now)
2. **Operator action** (what commands/steps to run)
3. **Verification** (how to know it worked)
4. **Known limits** (if any)

Prefer concise, operational language over marketing language.

## Drift Detection Heuristics

Before finishing implementation, check for stale content:
- Mentions removed folders/modules/routes
- Auth provider or env vars that no longer match code
- Old test commands or outdated pipeline behavior
- Architecture statements that conflict with live deployment

If found, fix immediately.

## Completion Gate

Do not declare task complete until:
- Relevant docs are updated
- Stale references removed
- Validation command(s) succeed
- Final response lists updated docs explicitly

## Recommended Validation Commands

Run only what matches current changes:
- `npm run typecheck`
- `npm run test`
- `npm run test:e2e:coverage` (when E2E behavior changed)

