# KORGAN Legal AI — Telegram / OpenAI only

Production-oriented MVP for Kazakhstan legal consultations, document intake and court-claim drafting.

## Current workflow

1. User describes the dispute in Telegram.
2. User can attach PDF/DOCX/TXT or photo/scan (JPG/PNG/WEBP).
3. OpenAI extracts only visible facts and marks unreadable/missing data.
4. KORGAN researches legal basis with OpenAI Web Search restricted to official Kazakhstan legal domains (default: `adilet.zan.kz`).
5. A separate drafting pass builds a structured claim.
6. A separate validation pass checks facts, legal support and missing required fields.
7. The bot returns a DOCX and marks it `VERIFIED` or `NEEDS_VERIFICATION`.

## Fail-closed rule

Exact articles, deadlines, jurisdiction/court and current legal status must not be guessed. If they cannot be verified from an allowed official source, the draft keeps an explicit `[ТРЕБУЕТ УТОЧНЕНИЯ: ...]` / verification note.

A concrete court name is never accepted from the model unless the case materials name it: matching an address to a court district/specialisation is not derivable from law, so it goes to `NEEDS_VERIFICATION`.

## Deterministic calculations

Everything computable from a rate fixed in law is computed in `korgan/legal_calc.py`, not by the model. The state duty for a monetary claim follows статья 665 НК РК (Кодекс РК № 214-VIII): 1% of the claim price for individuals, 3% for legal entities, capped at 10 000 МРП (4 325 ₸ in 2026, Закон РК № 239-VIII).

When the claim price or the payer type cannot be established from the materials, the document carries `[ТРЕБУЕТ РАСЧЁТА ГОСПОШЛИНЫ]` instead of a guessed number. Both rate constants are year-bound and must be re-verified when the next budget law enters into force.

Late-payment interest under статья 353 ГК РК is computed the same way: principal × NB RK base rate × days of delay / 365, over an explicit period, with the prayer for relief asking for the amount as of the filing date plus continuing accrual until actual payment. The base-rate table lists only confirmed decisions — a delay starting before the earliest entry flags the *rate* as unverified and keeps the provision itself.

## Local corpus (feature-flagged)

`korgan/legal/` holds the local-corpus path: provisions in SQLite + FTS5, a citation validator, Python-only calculations, requirement checklists and a ГПК form check. It is **off by default** — the existing OpenAI web-search research runs unchanged until the flag is set:

```bash
python scripts/load_corpus.py --all          # requires network access to adilet.zan.kz
KORGAN_LOCAL_CORPUS=1 python -m korgan.bot
```

The loader accepts only adilet's Russian edition: the URL must be on `/rus/`, and the text must actually read as Russian, because an English translation of a code parses just as cleanly. Rates used by the calculators live in `korgan/data/rates.json` with the date they were current on — update the file, not the code.

With the flag off, an unbuilt corpus, or a query with no matches, the pipeline falls back to web search rather than emitting a claim with no legal basis.

## Provision corpus

`korgan/legal_corpus.py` holds provisions stable enough to cite from code, each with its act, article number, source URL and check date. It exists because research runs per-pass: a provision confirmed during consultation was otherwise re-derived by the document pass and, on a weaker search, downgraded to `NEEDS_VERIFICATION`. Articles cited in a consultation answer are also carried into the case materials.

Corpus entries were checked against secondary legal databases, not read from adilet.zan.kz by the shipping code, so every claim citing them carries a note asking for an official-source check before filing.

## Stack

- Python 3.11+
- aiogram 3
- OpenAI Responses API (text, images/files, structured outputs, web search)
- python-docx
- Railway-ready long polling

No Pinecone, MongoDB, Gemini, Groq, DeepSeek or OpenRouter is required for this MVP.

## Environment

```env
TELEGRAM_BOT_TOKEN=...
OPENAI_API_KEY=...
OPENAI_MODEL=gpt-5.1
OPENAI_VISION_MODEL=gpt-5.1
OPENAI_VALIDATION_MODEL=gpt-5.1
OFFICIAL_LEGAL_DOMAINS=adilet.zan.kz
```

## Run

```bash
pip install -r requirements.txt
python -m korgan.bot
```

## Telegram

- `/start`
- `/ru`, `/kk`
- `/claim`
- `/clear`
- Send text for consultation / facts
- Send PDF/DOCX/TXT or photo/scan to add evidence to current case

## Privacy note

OpenAI requests are sent with `store=False`. Uploaded case material is held only in the bot's in-memory FSM for the current process in this MVP; `/clear` removes current-session case material. Production persistence/retention should be added only with explicit consent and encryption.
