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

Exact articles, deadlines, state duty, jurisdiction/court and current legal status must not be guessed. If they cannot be verified from an allowed official source, the draft keeps an explicit `[ТРЕБУЕТ УТОЧНЕНИЯ: ...]` / verification note.

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
