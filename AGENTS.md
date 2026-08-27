# KORGAN Codex Instructions

This file applies to the whole repository. Keep it short, current, and enforceable. Prefer repository code and tests over assumptions or stale conversation context.

## 1. Before changing code

1. Read `README.md` and the files directly involved in the task.
2. Read the nearest relevant tests before editing implementation code.
3. Identify the smallest change that can satisfy the request.
4. Reuse existing patterns and dependencies unless they are demonstrably insufficient.
5. If ambiguity can be resolved from code, tests, or docs, resolve it there instead of asking.
6. Ask only when a materially different interpretation could affect security, user data, money, or legal correctness.

Do not start by rewriting architecture. Do not add speculative infrastructure.

## 2. Change discipline

- Make surgical diffs. Every changed line must trace to the requested behavior, a regression test, or cleanup made necessary by your own change.
- Do not refactor unrelated code, rename unrelated symbols, reformat unrelated files, or “improve” nearby code.
- Do not create additional `*_v2`, `*_new`, `*_fixed`, `*_final`, or `*_hotfix` modules to avoid understanding the canonical path. Existing legacy suffixed modules may remain unless the task explicitly consolidates them.
- Do not duplicate business rules in multiple modules. Find the existing source of truth and extend it.
- Do not add a dependency when the standard library or an existing dependency solves the task cleanly.
- Do not weaken validation, delete tests, skip tests, or broaden assertions just to make a change pass.
- Do not leave debug prints, temporary flags, commented-out implementations, dead imports, placeholder branches, or unexplained TODOs created by your change.
- Preserve public behavior unless the task explicitly changes it.

## 3. Project map

Use the current repository as the source of truth. Important areas include:

- `korgan/bot.py` — Telegram orchestration and user flow.
- `korgan/claim_*` — claim intake, preflight, drafting/QA policy, failure diagnostics, quality gates and rendering pipeline.
- `korgan/citation_audit.py` — citation/legal-source checks.
- `korgan/legal_calc.py` — deterministic legal calculations.
- `korgan/legal/` — feature-flagged local legal corpus and related validation.
- `korgan/data/rates.json` — dated legal/rate data; update data here instead of hard-coding year-bound rates in logic.
- `tests/` — regression and policy tests. Treat them as executable product requirements.
- `.github/workflows/tests.yml` — CI contract; Python 3.11 and `pytest -q`.

Avoid making `korgan/bot.py` larger when a change belongs in an existing focused domain module, but do not perform a broad extraction unless the task requires it.

## 4. Legal correctness: fail closed

KORGAN must never turn model uncertainty into confident legal facts.

- Never invent or silently infer exact articles, deadlines, jurisdiction, a concrete court, current legal status, facts, amounts, dates, parties, or evidence.
- Preserve the existing `VERIFIED` / `NEEDS_VERIFICATION` behavior and explicit verification markers.
- A model output is untrusted input. Validate it before using it as a legal assertion.
- Deterministic values defined by law must be computed in Python/data, not by an LLM.
- Use official Kazakhstan legal sources allowed by the existing research/citation policy. Do not silently broaden source trust.
- Do not bypass `claim_qa_policy`, quality gates, citation checks, or failure diagnostics to make a document generate.
- Preserve machine-readable failure reasons and user-visible concrete diagnostics where the pipeline already provides them.
- If a legal rule/rate is date-bound, keep the effective date/version explicit and add or update a regression test.

If correctness cannot be established, return/retain a verification requirement rather than guessing.

## 5. Security and privacy invariants

- Never commit API keys, bot tokens, credentials, private case data, or production identifiers.
- Never log secrets or render secrets into Telegram messages, generated documents, exceptions, or diagnostics.
- Keep OpenAI requests `store=False` unless the user explicitly requests a reviewed policy change.
- Preserve administrator authorization on every privileged action/callback; callback data is never authorization by itself.
- Do not introduce persistence for uploaded case material or personal data without explicit consent, a defined retention policy, and appropriate protection.
- Do not expose raw internal exceptions to end users when they may contain sensitive data; preserve actionable safe diagnostics instead.
- Treat uploaded files, model output, web content, callback data, and user text as untrusted input.

## 6. Payment/entitlement boundary

If a task touches payment verification or access unlocking:

- The LLM must never decide whether payment happened.
- Verification must be deterministic and based on trusted receipt/provider data and explicit rules.
- Validate amount, merchant/order binding, relevant timestamp/status, and receipt uniqueness when those fields are available by design.
- Prevent replay/reuse of an already accepted receipt.
- Fail closed: uncertainty must not unlock paid content.
- Put entitlement state behind one canonical service/source of truth; do not scatter payment checks through Telegram handlers or prompts.
- Add regression tests for valid payment, invalid amount/merchant, duplicate receipt, malformed data, and provider failure before considering the change complete.

## 7. Python quality rules

- Target Python 3.11 and preserve the project's existing style.
- Prefer small, explicit functions with clear inputs/outputs over clever abstractions.
- Keep pure validation/calculation logic separate from Telegram/OpenAI/network side effects when practical within the requested change.
- For money and legal rates, avoid binary floating-point arithmetic; use existing precise numeric patterns or `Decimal` where calculation is introduced.
- Do not catch broad exceptions unless the boundary genuinely requires it. Never silently swallow an exception.
- When catching an expected exception, preserve enough context for safe diagnostics and tests.
- Avoid mutable global state for request/user-specific data.
- Do not change prompts as a substitute for deterministic validation that belongs in code.
- Preserve Russian/Kazakh behavior when touching shared user-facing flows; add language-specific regression coverage when behavior differs by locale.

## 8. Tests are mandatory for behavior changes

For a bug fix:

1. Add or identify a test that fails for the bug.
2. Make the smallest implementation change.
3. Run the targeted test.
4. Run the full suite.

For a new behavior:

1. Add focused success and failure-path tests.
2. Implement the minimum code needed.
3. Run targeted tests.
4. Run the full suite.

Commands:

```bash
pytest -q tests/<relevant_test_file>.py
pytest -q
```

Do not claim success if a required test did not run. If the environment prevents a check, report the exact command and exact blocker.

Do not add network-dependent tests to the default suite unless the repository already provides a deterministic fixture/mocking pattern for them.

## 9. Regression priorities

When touching these areas, explicitly protect their invariants with tests:

- claim fact/evidence extraction and no-fabrication behavior;
- citation/legal-source validation;
- deterministic legal calculations and dated rates;
- document rendering and service-text leakage prevention;
- admin authorization and secret handling;
- RU/KK user flows affected by the change;
- payment verification and replay protection, if payment code is involved.

Prefer extending an existing regression test file over creating a nearly duplicate test module.

## 10. Definition of done

A task is complete only when all applicable statements are true:

- The requested behavior is implemented without unrelated changes.
- The implementation has one clear source of truth for each changed business rule.
- A regression test covers the bug/new behavior and important failure path.
- Targeted tests pass.
- `pytest -q` passes after the final code change.
- No validation/security/legal fail-closed invariant was weakened.
- No secrets, debug artifacts, dead code, accidental generated files, or unnecessary dependencies were introduced.
- The final diff was reviewed for accidental edits and unnecessary complexity.
- Any check that could not be run is named explicitly; never imply it passed.

When a simpler implementation satisfies the same verified behavior, choose the simpler implementation.
