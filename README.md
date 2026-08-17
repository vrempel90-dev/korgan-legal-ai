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

### What blocks a document and what only marks it

Fail-closed means "do not assert what is not proven", not "do not produce a document". Only two classes of defect stop the DOCX (`korgan/claim_qa_policy.py`):

1. fabrication or substitution — a fact, amount, date, role or document that is not in the case materials;
2. chat/service text leaking into the court document.

Everything else is a gap and is marked inside the document instead: a missing second piece of evidence, an unsent pre-trial claim, an unverified article. A receipt (расписка) is a self-sufficient written proof of handing over money under a loan between individuals, and a pre-trial claim is not generally mandatory for such a debt — neither may block drafting.

### Refusal diagnostics

Every refusal carries a machine-readable reason (`korgan/claim_failure.py`): stage (`research`/`draft`/`qa`/`render`), code, the concrete fields and the failed checks. It is written to the log as a single line — `CLAIM_FAIL stage=… code=… fields=… issues=…` — and shown to the user as the actual cause instead of a generic message.

## Deterministic calculations

Everything computable from a rate fixed in law is computed in `korgan/legal_calc.py`, not by the model. The state duty for a monetary claim follows статья 665 НК РК (Кодекс РК № 214-VIII): 1% of the claim price for individuals, 3% for legal entities, capped at 10 000 МРП (4 325 ₸ in 2026, Закон РК № 239-VIII).

When the claim price or the payer type cannot be established from the materials, the document carries `[ТРЕБУЕТ РАСЧЁТА ГОСПОШЛИНЫ]` instead of a guessed number. Both rate constants are year-bound and must be re-verified when the next budget law enters into force.

## Local corpus (feature-flagged)

`korgan/legal/` holds the local-corpus path: provisions in SQLite + FTS5, a citation validator, Python-only calculations, requirement checklists and a ГПК form check. It is **off by default** — the existing OpenAI web-search research runs unchanged until the flag is set:

```bash
python scripts/load_corpus.py --all          # requires network access to adilet.zan.kz
KORGAN_LOCAL_CORPUS=1 python -m korgan.bot
```

The loader accepts only adilet's Russian edition: the URL must be on `/rus/`, and the text must actually read as Russian, because an English translation of a code parses just as cleanly. Rates used by the calculators live in `korgan/data/rates.json` with the date they were current on — update the file, not the code.

With the flag off, an unbuilt corpus, or a query with no matches, the pipeline falls back to web search rather than emitting a claim with no legal basis.

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
ADMIN_TELEGRAM_IDS=123456789
```

`ADMIN_TELEGRAM_IDS` is a comma-separated allow-list of Telegram user IDs, for example `123456789,987654321`. If it is empty or malformed, administrator access is denied.

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

### Administrator menu

- `/admin` opens the KORGAN administrator panel only for IDs listed in `ADMIN_TELEGRAM_IDS`.
- Every administrator callback is re-authorized by Telegram user ID; possession of callback data alone does not grant access.
- API keys are never rendered in Telegram.
- The legal fail-closed policy cannot be disabled from the administrator panel.
- Users who are not administrators receive only `Команда недоступна.` and never receive the panel or its data.

## Privacy note

OpenAI requests are sent with `store=False`. Uploaded case material is held only in the bot's in-memory FSM for the current process in this MVP; `/clear` removes current-session case material. Production persistence/retention should be added only with explicit consent and encryption.
