# KORGAN Legal AI — Telegram / OpenAI only

Production-oriented MVP for Kazakhstan legal consultations, document intake and court-claim drafting.

## Current workflow

1. User describes the dispute in Telegram — once, in their own words.
2. User can attach PDF/DOCX/TXT or photo/scan (JPG/PNG/WEBP).
3. OpenAI extracts only visible facts and marks unreadable/missing data.
4. KORGAN researches legal basis with OpenAI Web Search restricted to official Kazakhstan legal domains (default: `adilet.zan.kz`).
5. A separate drafting pass builds a structured claim.
6. A separate validation pass checks facts, legal support and missing required fields.
7. The bot returns a DOCX and marks it `VERIFIED` or `NEEDS_VERIFICATION`.

### One message in, one document out

There is no field-by-field questionnaire (`korgan/claim_intake_policy.py`). Gaps
in the materials are split by consequence, not by form:

* **critical** — who is suing, whom, over what, and for how much. Without these
  the document is meaningless, so they are asked for **once**, all in a single
  message. Whatever that one answer does not produce becomes a placeholder too:
  a second round never happens.
* **filing requisites** — date of birth, ИИН/БИН, party addresses, bank details,
  the exact court, the state duty. These never block drafting. The draft is
  delivered with `[ТРЕБУЕТ УТОЧНЕНИЯ: ...]` in their place, exactly as contract
  templates already work, and the user fills them in the file in one pass.

### The provision must prove the relief

Citation checking and provision *choice* are different failures, and
`korgan/legal_basis_fit.py` covers the second. On a claim for the return of a
2 300 000 ₸ prepayment for work never performed, the legal reasoning consisted of
the rule on acceptance of a work result — a real article, quoted correctly, and
about the customer's own duty rather than any ground for recovering money from
the contractor.

So the provision is matched to the relief in the prayer for relief: withdrawal
from the contract with return of the advance, contractor liability or unjust
enrichment support that claim; the acceptance rule does not and may never be its
sole legal basis. When nothing in the document supports the relief, KORGAN does
not substitute a plausible-looking article — the document says a lawyer must pick
the exact provision.

A provision the user agreed to keep as `NEEDS_VERIFICATION` is stored on the
case, not on the draft it was granted for, and re-applied on every path into the
renderer. A rebuild that drops the disputed article gets it back, with its number
present and its content unasserted.

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
