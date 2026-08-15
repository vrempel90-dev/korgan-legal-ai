# KORGAN Legal AI

Telegram legal AI assistant for the Republic of Kazakhstan.

## MVP architecture

Telegram -> strict RAG -> Pinecone -> official Adilet sources -> OpenAI -> answer with verification status.

### Safety invariant

KORGAN is fail-closed. Concrete legal facts (articles, deadlines, state duties, jurisdiction and similar claims) must be grounded in retrieved trusted sources. If the system cannot confirm them, it returns `NEEDS_VERIFICATION` rather than guessing.

## Required environment variables

Copy `.env.example` to `.env` locally or configure the same variables in Railway.

- `TELEGRAM_BOT_TOKEN`
- `OPENAI_API_KEY`
- `OPENAI_MODEL`
- `OPENAI_EMBEDDING_MODEL`
- `PINECONE_API_KEY`
- `PINECONE_INDEX_NAME`
- `RAG_MIN_SCORE`

No Gemini, Groq, DeepSeek or OpenRouter keys are used.

## Run the Telegram worker

```bash
pip install -r requirements.txt
python -m korgan.bot
```

## Index an official legal act

Only `https://adilet.zan.kz` URLs are accepted:

```bash
python -m korgan.ingest "https://adilet.zan.kz/..."
```

The Pinecone index dimension must match the selected OpenAI embedding model.

## Railway

Use the start command:

```text
python -m korgan.bot
```

Store all secrets in Railway Variables. Never commit `.env`.
