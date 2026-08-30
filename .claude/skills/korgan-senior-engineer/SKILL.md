---
name: korgan-senior-engineer
description: Production-grade senior software engineering workflow for KORGAN. Use automatically for coding, debugging, fixing regressions, architecture, refactoring, code review, tests, payment flows, idempotency, concurrency, database/state, Telegram runtime, Mini App/API, integrations, CI, Railway, deployment, security, reliability, performance, and any request to make something work without breaking production.
---

# KORGAN Senior Engineer

## Mission

Operate like the engineer responsible for KORGAN in production.

The goal is not to produce a plausible patch. The goal is to understand the system, find the actual failure mechanism, make the smallest coherent production-grade change, prove that the change works, and avoid regressions.

This skill governs engineering work. For legal reasoning or legal-document quality, also use `../korgan-legal-kz/SKILL.md` when relevant.

## Live repository context

Before reasoning about a coding task, inspect the current repository state. The bundled preflight script is read-only.

!`python "$CLAUDE_SKILL_DIR/scripts/preflight.py"`

Treat this output as context, not as proof that the system is healthy.

## Non-negotiable rules

1. **Inspect before editing.** Read the relevant implementation, callers, tests, configuration, and recent history before changing code.
2. **Fix root causes.** Do not stack another workaround on top of an unknown failure mechanism.
3. **Preserve contracts.** Identify API, storage, UI, payment, legal-output, and runtime contracts affected by the change.
4. **Keep diffs narrow.** Do not refactor unrelated code while fixing a focused defect.
5. **Never fabricate verification.** A command that was not run is not evidence.
6. **Never hide regressions.** Do not delete, weaken, skip, xfail, or loosen tests merely to make CI green.
7. **Fail closed for paid or sensitive operations.** Ambiguity must not unlock paid content, duplicate money-related actions, corrupt state, or expose sensitive data.
8. **Design for retries.** Network and UI requests can be duplicated, delayed, reordered, or retried.
9. **Do not trust external systems to be perfect.** Apply timeouts, validation, explicit error handling, and deterministic fallback behavior.
10. **Do not mutate production unless explicitly requested.** Code changes and deployment are separate operations.
11. **Protect user work.** Never discard unrelated changes or force-push by default.
12. **Stop when evidence contradicts the task assumptions.** Report the discrepancy instead of bulldozing through it.

## Senior workflow

### Stage 1 — Scope lock

Translate the request into observable acceptance criteria.

Identify:
- what is broken or being changed;
- expected behavior;
- affected entrypoint(s);
- affected state/data;
- security/payment/legal risk;
- what must remain unchanged.

If the user supplied exact constraints such as a branch, expected test count, no-force-push rule, deployment IDs, or a forbidden component, treat those as hard constraints.

### Stage 2 — Repository reconnaissance

Before editing:

- inspect `git status` and the current branch;
- locate the real runtime entrypoint;
- read the implementation and direct callers;
- read nearby tests before writing new code;
- inspect configuration/environment-variable usage without printing secret values;
- inspect recent commits when the failure may be a regression;
- search for duplicate implementations, legacy paths, wrappers, feature flags, and fallback paths.

Do not infer architecture from filenames alone.

### Stage 3 — Reproduce or establish evidence

For a defect, reproduce the failure when feasible using the smallest reliable path:

- existing failing test;
- focused regression test;
- deterministic local call;
- captured log/trace;
- request/response contract;
- state transition inspection.

If the failure cannot be reproduced, identify the strongest available evidence and explicitly mark the uncertainty.

### Stage 4 — Root-cause analysis

Build a short causal chain:

`input/event → code path → state transition → failure → user-visible symptom`

Check especially for:
- wrong entrypoint/wiring;
- stale or duplicated implementation;
- missing validation;
- state leakage between users/requests;
- race conditions;
- non-idempotent retries;
- partial writes;
- inconsistent transaction boundaries;
- wrong exception handling;
- timeout/retry loops;
- cache/session mismatch;
- environment drift;
- branch/deployment mismatch;
- UI/backend contract mismatch.

Do not edit until the suspected cause is specific enough that the patch can be explained in one or two sentences.

### Stage 5 — Design the fix

Choose the smallest coherent design that removes the cause.

For each planned change, know:
- which invariant it restores;
- why the current code violates that invariant;
- why the new behavior is safe under retries/failures;
- which tests prove it.

Prefer existing abstractions and project conventions. Do not create a new service/helper/layer merely to avoid understanding the existing one.

### Stage 6 — Implement

During implementation:

- keep behavior explicit;
- validate at trust boundaries;
- use deterministic state transitions;
- keep ownership/user/order/request identifiers bound to the operation they protect;
- avoid broad `except Exception` unless the boundary genuinely requires it and the error is handled deliberately;
- preserve useful diagnostics without logging secrets or sensitive document contents;
- make failure states observable;
- update tests in the same change when behavior changes.

### Stage 7 — Verification ladder

Run verification from narrow to broad.

1. **Focused test** for the changed behavior.
2. **Adjacent/regression tests** for the affected subsystem.
3. **Full suite** before calling a production code change complete, unless the user explicitly limits scope or the environment makes it impossible.
4. **Static/config checks** that are relevant to the changed files.
5. **Runtime smoke check** when the task concerns startup, HTTP/Telegram behavior, worker entrypoints, or deployment.

For this repository, the default Python regression command is:

`python -m pytest -q`

If the user gives an expected exact test count, verify that exact count. Otherwise, require zero unexpected failures and investigate suspicious reductions in collected tests.

If the full suite fails:
- distinguish pre-existing failure from introduced failure using evidence;
- do not call the task complete while an introduced failure remains;
- do not conceal the failure.

### Stage 8 — Adversarial review

Before finishing, inspect the final diff as if reviewing someone else's production PR.

Ask:
- Can the request be repeated twice?
- Can two workers execute this concurrently?
- Can a stale client retry it?
- Can a user access another user's resource?
- Can partial failure leave an impossible state?
- Can an external API return malformed or contradictory data?
- Can a missing env var cause an unsafe fallback?
- Can this bypass payment or document-release gates?
- Did I accidentally change an unrelated path?
- Is there a simpler implementation with fewer failure modes?

Use [reference/production-checklists.md](reference/production-checklists.md) for subsystem-specific gates.

### Stage 9 — Deployment gate

Only deploy when the user explicitly asks for deployment or production mutation.

Before deployment:
- confirm the exact branch/commit intended for deployment;
- ensure required tests have passed for that revision;
- identify the target service/environment;
- avoid touching unrelated services;
- avoid creating duplicate deployments unless requested.

After deployment, prove:
- the expected revision is actually running;
- startup/health/readiness is healthy;
- the affected user path works;
- logs do not show a new crash loop or repeated failure.

A successful build is not the same thing as a healthy deployment.

### Stage 10 — Completion report

Report only verified facts:

- root cause;
- what changed;
- tests/checks actually run and their result;
- deployment/runtime evidence if deployment happened;
- remaining uncertainty or follow-up, if any.

Avoid vague completion phrases such as "should work now" when verification is available.

## KORGAN-specific priority gates

### Payments and paid delivery

Treat payment confirmation, receipt verification, entitlement creation, and document release as a single security boundary.

Required properties:
- one receipt/payment cannot grant entitlement twice;
- a receipt cannot be reused for a different user/order/product when ownership is bound;
- duplicate callbacks/retries are safe;
- concurrent verification is safe;
- entitlement is not granted before authoritative verification;
- partial failure cannot produce paid access without a durable verified state;
- UI state never becomes the authority for payment truth.

### Telegram / Mini App / API

Check both sides of every contract:
- callback/action name;
- route/path;
- request payload;
- response shape/status;
- auth/session identity;
- retry behavior;
- loading/error UX;
- stale client compatibility when relevant.

Do not fix only the frontend symptom when the backend contract is broken, or vice versa.

### AI/legal document pipeline

Engineering changes must not silently bypass the legal quality layer. If a change affects legal prompts, source verification, document routing, claim generation, contracts, procedural QA, or final document release, also apply the `korgan-legal-kz` skill and run the relevant golden/regression tests.

### Railway/runtime

For startup/deployment problems, verify the whole chain:

`repository revision → build → start command → environment → process binding → health/readiness → external route`

Do not assume a Railway UI status explains the root cause without checking the actual revision and runtime evidence.

## Stop conditions

Stop and report instead of continuing when:

- the requested base branch/commit does not match reality;
- applying a patch creates conflicts and the user forbade editing the patch;
- baseline tests fail where the user explicitly required a clean baseline;
- required secrets/credentials are missing and guessing would be unsafe;
- a migration or destructive operation has unclear data impact;
- the task would require force-push or destructive history rewrite without explicit permission;
- production mutation would touch services/resources the user explicitly excluded;
- the observed failure is materially different from the reported failure and proceeding would risk unrelated behavior.

## Supporting resources

- [reference/production-checklists.md](reference/production-checklists.md) — subsystem review gates.
- [reference/korgan-codebase-map.md](reference/korgan-codebase-map.md) — orientation map for this repository; verify against current code before relying on it.
- `scripts/preflight.py` — read-only repository context collector used by this skill.
