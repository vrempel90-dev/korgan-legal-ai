# Statement of Claim / Исковое заявление

# Mandatory pre-check

Before any statement of claim:
1. Run FACT LOCK.
2. Run ROLE LOCK.
3. Create the role chain: who performed → who owed → who breached → who is creditor → who is debtor → who is plaintiff → who is defendant → what flows from whom to whom.
4. Freeze the roles.
5. Do not draft until this chain is internally consistent.

After drafting, the prayer for relief must be compared against the locked role chain.


## Purpose

Produce high-quality court pleadings for Kazakhstan matters without inventing facts or procedure.

This module applies whenever the user asks to:
- prepare an иск / исковое заявление;
- sue a person/company/state body;
- recover money/damages/debt;
- invalidate or terminate an agreement;
- recognize a right;
- compel performance;
- challenge an act/decision;
- prepare a filing-ready civil or administrative pleading.

## Phase 1 — Intake

Before drafting, extract:

### Parties
- claimant/plaintiff;
- defendant/respondent;
- third parties, if any;
- representative;
- identifiers and addresses;
- legal/entity status.

### Dispute
- legal relationship;
- what happened;
- chronology;
- breach / contested act;
- amount or non-monetary remedy;
- what the user wants the court to order.

### Procedure
- proposed court;
- jurisdiction/venue;
- mandatory pre-trial / conciliation step;
- limitation/deadline;
- state duty;
- representation authority.

### Evidence
For each material fact, identify supporting evidence.

## Phase 2 — Missing-data gate

Classify missing data as:

### BLOCKING
Without this, do not create a final-form filing:
- identity of defendant;
- core factual basis;
- requested remedy;
- court/procedural route where current law makes it material;
- crucial dates affecting limitation/deadline;
- адрес ответчика, когда он определяет подсудность (см. ниже).

#### Адрес ответчика и подсудность

Адрес ответчика BLOCKING, если он необходим для определения подсудности и подсудность ещё не зафиксирована. Если адрес известен третьей стороне/пользователю не указан — задать уточняющий вопрос ДО генерации, а не подставлять плейсхолдер.

Суд не может быть определён без адреса ответчика — это одна причина блокировки, а не две независимые.

Практические следствия:
- не выносить «уточнить наименование суда» и «уточнить адрес ответчика» как два отдельных вопроса и не показывать их как два независимых пробела в документе;
- не считать пробел закрытым, если получено только одно из двух: пока адреса нет, поле суда невосполнимо, и наоборот;
- не подставлять `[ТРЕБУЕТ УТОЧНЕНИЯ: точное наименование суда]` как способ выпустить документ — это плейсхолдер вместо блокировки, а не вместо реквизита.

Адрес ответчика перестаёт быть BLOCKING только когда подсудность уже зафиксирована на ином основании, и это основание прямо указано в проекте:
- договорная подсудность по условию договора;
- исключительная подсудность (например, по месту нахождения имущества);
- иное специальное правило подсудности, верифицированное по официальному источнику.

### NON-BLOCKING
May use placeholders:
- IIN/BIN;
- exact annex numbering;
- representative details;
- bank details;
- адрес истца, если он не влияет на подсудность;
- адрес ответчика, если подсудность уже зафиксирована на ином основании;
- formal requisites not yet supplied.

If BLOCKING information is missing, ask focused questions first — до генерации документа, а не после неё.

## Phase 3 — Claim theory

Build a private case theory:

1. What legal relationship exists?
2. What duty/right is asserted?
3. What act/omission constitutes the breach?
4. What injury/loss/legal consequence resulted?
5. What remedy follows?
6. What evidence proves each link?
7. What defenses are foreseeable?
8. What fact or legal issue is weakest?

Do not expose internal chain-of-thought; only provide concise conclusions where useful.

## Phase 4 — Structure of the pleading

Use this structure when applicable:

### Header
- court;
- plaintiff;
- defendant;
- third parties;
- representative;
- claim value;
- state duty status.

### Title
`ИСКОВОЕ ЗАЯВЛЕНИЕ`
Use a short subject line in parentheses when useful.

### I. Factual circumstances
Write chronologically.
One fact per paragraph when possible.
Reference supporting document after the relevant fact.

### II. Pre-trial / procedural compliance
State what was done only if supported by facts/documents.
If not verified, use a placeholder or mark for verification.

### III. Legal grounds
Use only verified legal provisions for exact article citations.
Do not paste long legal quotations.
Explain why the rule applies to these facts.

### IV. Calculation
For monetary claims, provide a clear calculation block.

### V. Requested relief
Use numbered requests.
Each request must be specific and supported.

### VI. Attachments
List every document actually referenced or expected to be attached.

### Signature block
- date;
- plaintiff/representative;
- signature placeholder.

## Drafting style

Use:
- precise legal Russian or Kazakh;
- neutral tone;
- short factual paragraphs;
- no emotional accusations;
- no rhetorical questions;
- no excessive quotations;
- no unsupported legal labels.

Avoid:
- "очевидно";
- "безусловно";
- "грубейшее нарушение" unless legally and factually justified;
- threats to the defendant;
- unnecessary criminal-law references in a civil claim.

## Legal citation discipline

For an exact article citation:
- official source verification is required;
- cite only provisions that materially support the claim;
- do not include a long list of irrelevant articles;
- distinguish substantive law from procedural law.

If current procedure is unverified, label:
`[ТРЕБУЕТ ПРОВЕРКИ ПО ДЕЙСТВУЮЩЕЙ РЕДАКЦИИ ЗАКОНОДАТЕЛЬСТВА РК]`

## Evidence map

Before finalizing, create an internal mapping:

| Allegation | Evidence | Status |
|---|---|---|
| Contract existed | Contract dated ... | Available |
| Payment due | Invoice / act / contract clause | Available |
| Non-payment | Bank statement / reconciliation | Missing/Available |
| Pre-trial notice | Notice + delivery proof | Missing/Available |

Do not include the table in the final pleading unless requested, but use it to prevent unsupported allegations.

## Monetary claims

Never calculate from guessed values.

Show:
- principal;
- contractual penalty;
- statutory penalty/interest;
- damages;
- moral damages if legally applicable and requested;
- court expenses;
- total.

Each component must have:
- legal basis;
- factual basis;
- formula;
- period;
- source data.

## Multiple remedies

When several remedies are possible:
- separate primary and alternative claims only when procedure allows and this is verified;
- do not combine mutually inconsistent remedies without explanation.

## Counterparty defenses

Before finalizing, identify likely objections:
- limitation/deadline;
- lack of evidence;
- improper defendant;
- wrong court;
- lack of pre-trial procedure;
- payment already made;
- invalidity/termination clause;
- force majeure;
- offset/set-off;
- claimant's own breach.

Strengthen the draft only with facts/evidence the user actually has.

## Filing-readiness levels

Use one of:

### `PRELIMINARY DRAFT`
Facts or procedure are materially incomplete.

### `LAWYER-REVIEW DRAFT`
Core facts and structure are complete, but a KORGAN lawyer should verify procedure/citations/calculations.

### `READY FOR FINAL HUMAN REVIEW`
All required facts, official-source checks, calculations, and attachments appear complete.

Never call an AI-generated pleading "ready to file" without final human review.

## Final checklist

Before output:
- court verified or flagged;
- parties correct;
- chronology consistent;
- legal basis verified or flagged;
- pre-trial requirements checked;
- limitation/deadline checked;
- amount calculation reconciled;
- relief precise;
- attachments complete;
- no invented evidence;
- no invented article numbers;
- no unsupported criminal allegations;
- placeholders clearly visible;
- filing-readiness level shown.


## Procedural consequence precision

When describing the consequence of an unmet mandatory pre-trial/out-of-court procedure, verify the exact current procedural consequence from the official Civil Procedure Code. Do not use generic wording such as "иск могут оставить без движения/вернуть".

If Article 152 applies to the facts and current law, state the consequence as return of the claim, subject to the verified statutory conditions.
