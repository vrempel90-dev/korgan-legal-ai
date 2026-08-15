# Host Application Output Contract

## Client consultation

Preferred order:
1. Direct answer
2. Short legal reasoning
3. Risks / uncertainties
4. What to do now
5. Missing information, if any

## Document draft

Return:
- document title;
- complete draft;
- placeholders for missing facts;
- short "Before filing/signing" checklist.

Do not add commentary inside the formal document unless clearly marked as `[Комментарий для проверки]`.

### Обязательные блоки после документа

Всегда прикладывать блок «QA-отчёт» и «Уровень готовности» (`PRELIMINARY DRAFT` / `LAWYER-REVIEW DRAFT` / `READY FOR FINAL HUMAN REVIEW`) сразу после документа, видимо для пользователя, а не только внутренне.

Порядок вывода:
1. документ;
2. `QA-отчёт` — пройденные и непройденные пункты по разделам A–I, по каждому непройденному пункту конкретная причина;
3. `Уровень готовности` — один из трёх статусов;
4. недостающие данные и уточняющие вопросы, если они есть.

Эти блоки:
- размещаются вне тела документа и не попадают в файл, передаваемый в суд;
- не сворачиваются, не сокращаются и не заменяются общей фразой о необходимости проверки перед подачей;
- не переносятся в footer, caption файла или служебные примечания.

Если QA дал `FAIL` или `FAIL_CRITICAL`, финальный документ не выдаётся вовсе — вместо него уходят нарушенные пункты, уточняющие вопросы и статус `PRELIMINARY DRAFT`. См. Release Gate в [final-legal-qa.md](final-legal-qa.md).

## Document review

Return a prioritized list or table-equivalent structure:
- clause;
- severity;
- issue;
- consequence;
- proposed fix.

Then provide:
- top 3 risks;
- negotiation priorities;
- whether human review is recommended.

## Source status

Where the host app supports structured metadata, classify legal basis as one of:
- `VERIFIED`
- `PARTIALLY_VERIFIED`
- `NEEDS_VERIFICATION`

Never represent `NEEDS_VERIFICATION` as filing-ready law.

## Suggested machine-readable fields

When the host application requests structured output, use fields conceptually equivalent to:

- `language`
- `task_type`
- `summary`
- `facts`
- `assumptions`
- `legal_analysis`
- `verified_sources`
- `risks`
- `recommended_actions`
- `missing_information`
- `draft_document`
- `verification_status`
- `human_review_recommended`

Only emit JSON when the host application explicitly asks for JSON.


## Full-agent task types

When structured output is requested, `task_type` may include:
- CONSULTATION
- STATEMENT_OF_CLAIM
- PRETRIAL_CLAIM
- COMPLAINT
- MOTION_APPLICATION
- APPEAL
- CONTRACT_DRAFTING
- CONTRACT_REVIEW
- DOCUMENT_REVIEW
- EVIDENCE_ANALYSIS
- LEGAL_RESEARCH

Recommended additional fields for high-impact documents:
- `locked_facts`
- `locked_roles`
- `procedural_checks`
- `evidence_map`
- `calculation`
- `qa_status`
- `readiness_status`
