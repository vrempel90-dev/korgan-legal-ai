# KORGAN Legal AI

Production-oriented legal drafting core for the Republic of Kazakhstan, delivered through a Telegram
bot.

Exact legal citations, state-duty rates, procedural deadlines and jurisdiction conclusions are never
invented: until verified by the legal-research layer they remain in `NEEDS_VERIFICATION`.

## What it produces

Eight document types are registered — claim, pretrial demand, response, motion, complaint, appeal,
contract and consultation. Each is declared as a blueprint: its sections, party labels, applicable
procedural checks, closing demands and the interview questions that collect its facts. Adding a
category of case is a registry entry, not a change to the engine.

Every document is delivered as text plus a formatted `.docx`, alongside a separate list of the
points a lawyer still has to check.

## How facts are collected

- **Guided dialogue** — one validated question at a time, derived from the chosen document type.
  Answers are parsed by deterministic code, so no model participates in producing the facts.
  Generation is blocked until every required answer is present.
- **Free text** — the user describes the case in prose; Fact Lock extracts the facts and grounding
  validation rejects anything not present in the source text.
- **Documents** — PDF, DOCX, JPG and PNG are converted to source text first; values read only from a
  scan require confirmation before they can become locked facts.

## Safety invariants

- **Money and time are code.** No model computes an amount or a deadline. Debt is derived from the
  contract sum minus every payment credited against it; penalties accrue per period on the balance
  actually outstanding, and each period is printed so the figure can be re-derived.
- **No plausible law.** An article, rate or jurisdiction rule appears only with a verified source
  from an official Kazakhstan domain. Otherwise the document says what must be checked.
- **No false alarms.** A NEEDS_VERIFICATION marker on a fact the user supplied is treated as a
  defect, not as harmless caution.
- **Not ready to file.** The strongest machine status is `READY FOR FINAL HUMAN REVIEW`; the filing
  decision remains a lawyer's.

## Local setup

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e '.[dev]'
cp .env.example .env
pytest
```

The test suite needs no API key and no network. Database-backed tests skip unless `TEST_DATABASE_URL`
points at PostgreSQL with pgvector.

To use OpenAI, set `OPENAI_API_KEY`. Models are configured by environment variables rather than
hard-coded throughout the codebase.

## Quality gates

```bash
pytest tests/test_eval_suite.py            # 8 cases, 48 criteria, all must pass
python scripts/generate_quality_report.py  # regenerates QUALITY_REPORT.md
```

`QUALITY_REPORT.md` is generated from an actual run and covers the calculation checked against a
hand-written formula, the numeric trap cases, NEEDS_VERIFICATION discipline and each document's
conformance to the eleven house-style rules. See `docs/EVALUATION.md` for what it does and does not
establish.

## Documentation

| Document | Covers |
|---|---|
| `docs/ARCHITECTURE.md` | Pipeline, blueprints, corpora, safety invariants |
| `docs/EVALUATION.md` | Evaluation suite and quality gates |
| `docs/TELEGRAM_RUNTIME.md` | Bot runtime, dialogue, sessions, privacy |
| `docs/REFERENCE_CORPUS_ARCHITECTURE.md` | How the private reference corpus stays out of this repo |
