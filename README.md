# KORGAN Legal AI

Production-oriented legal drafting core for the Republic of Kazakhstan.

The project starts with the legal engine, not Telegram/UI. The first end-to-end workflow is a debt-recovery claim. Exact legal citations, state-duty rates, procedural deadlines and jurisdiction conclusions are never invented: until verified by the legal-research layer they remain in `NEEDS_VERIFICATION`.

## Implemented in the foundation

- Fact & Role Lock with structured output contracts.
- Task Router.
- Legal Research / Citation Gateway interface with fail-closed behavior.
- Procedural Check scaffold.
- Evidence Map.
- Deterministic monetary calculation layer.
- Debt-claim Drafting Engine.
- Declarative Final Legal QA gate.
- Output Contract with readiness status and `NEEDS_VERIFICATION`.
- Hash-chained audit trail integration point.
- Unit tests that do not require an API key.

## Local setup

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e '.[dev]'
cp .env.example .env
pytest
```

To use OpenAI, set `OPENAI_API_KEY`. Models are configured by environment variables rather than hard-coded throughout the codebase.

## Safety invariant

A generated document is not labelled "ready to file". The strongest machine status is `READY FOR FINAL HUMAN REVIEW`; an actual filing decision remains with a human lawyer.
