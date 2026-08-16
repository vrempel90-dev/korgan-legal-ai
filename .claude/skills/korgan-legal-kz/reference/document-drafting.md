# Legal Document Drafting

## General rule

Never invent missing party details, dates, amounts, addresses, identifiers, contract numbers, evidence, legal citations, or requested relief.

Use visible placeholders when data is missing:
- `[ФИО]`
- `[ИИН/БИН]`
- `[адрес]`
- `[дата]`
- `[сумма]`
- `[номер договора]`
- `[наименование суда/органа]`

## Нумерация: структура и проза — разные вещи

Правило общее для всех типов документов, а не только для договоров.

Номер получает только **структурный пункт** — раздел, пункт, подпункт вида
`1.`, `1.1.`, `1.1.1.`, а также самостоятельные нумерованные списки просительной
части и приложений. Нумерацию проставляет экспорт по позиции элемента; в тексте
пункта номер не пишется.

**Свободная проза номера не получает никогда.** Повествовательные абзацы —
изложение обстоятельств, развитие довода внутри возражения, правовое
рассуждение — это обычный текст. Они не входят в нумерованный список, даже если
идут подряд и даже если находятся внутри нумерованного пункта.

Смешанная структура — норма для состязательных документов: пронумерованное
возражение, под ним несколько абзацев прозы, затем следующее возражение.
Правильный результат: возражения имеют номера 1., 2., 3.; абзацы под ними — нет.
Признак дефекта: номер перед обычным повествовательным предложением
(«3. Согласно позиции Ответчика...»).

Просительная часть и приложения — два независимых списка; приложения начинают
нумерацию заново с 1.

Проверяется визуально в рендере PDF перед выпуском — см.
[final-legal-qa.md](final-legal-qa.md), Release Gate, проверка 6.

## Пересказ нормы

Любое положение закона, изложенное пересказом, а не дословной цитатой, сверяется
построчно с официальным текстом нормы до того, как попадёт в документ. Верный
номер статьи не подтверждает верность пересказа. Порядок и запреты — см.
[source-verification.md](source-verification.md), раздел «Paraphrase
verification».

## Before drafting

Determine:
- document type;
- sender/applicant/plaintiff;
- recipient/respondent/defendant;
- factual chronology;
- legal basis from verified context;
- evidence;
- exact request/remedy;
- attachments;
- procedural destination and deadline, if verified.

## Core document architecture

For claims/complaints/applications where applicable:

1. Addressee / court / authority
2. Parties and identifiers
3. Document title
4. Concise factual chronology
5. Legal basis
6. Application of law to facts
7. Requested relief
8. Attachments
9. Date/signature placeholders

## Contract drafting

Договор всегда открывается преамбулой с полной идентификацией обеих сторон и
основанием полномочий подписантов; номера разделов и пунктов проставляет экспорт, а не
текст. Обязательные форматы и проверки — см. [contracts.md](contracts.md).

For contracts, check or include as relevant:
- parties and authority;
- subject;
- scope/specification;
- price and payment;
- deadlines;
- acceptance;
- warranties;
- liability;
- force majeure;
- confidentiality;
- personal data;
- IP rights;
- termination;
- notices;
- dispute resolution;
- governing law;
- requisites/signatures.

Do not add clauses merely to make the contract longer.

## Claims and pre-trial notices

State:
- obligation/breach;
- supporting documents;
- requested cure;
- amount calculation if known;
- deadline only if verified or contractually supported;
- consequence of non-compliance without threats or exaggeration.

## Court documents

Before producing a filing-ready version, verify:
- jurisdiction/venue;
- party status;
- remedy;
- procedural form;
- mandatory attachments;
- fees/exemptions if relevant;
- deadline.

If any are not verified, mark the draft as requiring procedural verification.

## Final drafting quality check

Check:
- chronology is consistent;
- defined terms are used consistently;
- no missing party;
- no invented authority;
- no duplicated or contradictory requests;
- amounts and dates match source facts;
- tone is professional and restrained.


## Court claim handoff

If the requested document is an иск / исковое заявление / court pleading, apply `statement-of-claim.md` in addition to this file.

A court pleading must never be generated as a generic template when facts are sufficient for a tailored draft. Conversely, when blocking facts are missing, ask for them rather than silently filling them in.
