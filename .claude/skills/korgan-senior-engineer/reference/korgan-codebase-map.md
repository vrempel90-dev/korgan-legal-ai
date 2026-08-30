# KORGAN codebase orientation map

This file is an orientation aid for Claude Code. It is intentionally not authoritative: verify every path and runtime relationship against the current branch before editing.

## Repository shape

- `korgan/` — Python application and domain/runtime modules.
- `tests/` — pytest regression suite, including payment, legal generation, Telegram/runtime, and document-quality guards.
- `.claude/skills/korgan-legal-kz/` — Kazakhstan legal reasoning/drafting/QA skill.
- `.github/workflows/` — focused CI workflows.
- `requirements.txt` — Python dependencies.
- `railway.json` / `Procfile` — deployment/startup configuration where present on the active branch.

## High-risk engineering areas

### Payment and paid delivery

Representative modules on the recovery branch include:
- `korgan/payment.py`
- `korgan/payment_gate.py`
- `korgan/payment_runtime.py`
- `korgan/payment_delivery_bridge.py`
- `korgan/payment_operation_lock.py`
- `korgan/payment_release_guard.py`
- `korgan/document_receipt_replay_guard.py`
- `korgan/prepayment_gate.py`
- `korgan/prepayment_runtime.py`
- `korgan/kaspi_ofd.py`

Do not assume one module is the sole authority. Trace the actual entrypoint and state ownership before editing.

Representative regression tests include payment gate, prepayment, replay/idempotency, paid delivery, OFD, and bypass tests under `tests/`.

### Legal/document pipeline

There are multiple layers for claim/document generation, quality gates, release, DOCX formatting, verified legal sources, and legacy/hotfix compatibility. Representative families include:
- `claim_*`
- `document_*`
- `universal_*`
- `professional_*`
- `legal/`
- `legal_*`
- `*_docx.py`

Because multiple generations of the pipeline coexist, always locate the active runtime path and tests before changing a similarly named module.

Apply `korgan-legal-kz` as well as this engineering skill when changing legal behavior or legal document quality.

### Telegram and user interaction

Representative areas include:
- `bot.py`
- `strict_bot.py`
- menu/reply handlers
- localization/i18n
- Telegram branding/text
- request/session scope guards

Trace handler registration and runtime entrypoint rather than assuming a handler is reachable.

### External legal sources / corpus

Representative areas include:
- `korgan/legal/official_sources.py`
- corpus refresh/storage modules
- local corpus runtime/bridge modules
- source/provision checking modules

Network and source-verification failure must fail safely and must not fabricate legal authority.

## Architecture warning: duplicate/legacy paths

The repository intentionally contains compatibility layers, hotfix modules, release guards, and several generations of legal/document services. A recurring engineering risk is fixing a file that looks relevant but is not on the deployed execution path.

For any bug:
1. find the external entrypoint;
2. follow imports/calls to the concrete implementation;
3. locate the tests that exercise that exact path;
4. search for alternate/legacy/fallback paths;
5. confirm deployment start command reaches the expected runtime.

## Test strategy

The repository uses pytest. Default full-suite verification:

`python -m pytest -q`

Use focused tests first, then adjacent subsystem tests, then the full suite for production code changes. If the task specifies an exact expected test count, that requirement overrides the generic rule.

## Updating this map

If architecture changes materially, update this map only after the code change is verified. Do not turn this file into a second implementation spec; authoritative behavior belongs in code, tests, and explicit contracts.
