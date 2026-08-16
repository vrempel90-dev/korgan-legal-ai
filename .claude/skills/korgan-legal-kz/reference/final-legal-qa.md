# FINAL LEGAL QA

## Purpose

Independent final control before KORGAN releases a consultation or document.

## QA must compare against the locked source facts

### A. Party/role integrity
- Are claimant/defendant roles correct?
- Creditor/debtor correct?
- Provider/customer correct?
- Employer/employee correct?
- Does money flow in the correct direction?

Any reversal = `FAIL_CRITICAL`.

### B. Fact integrity
- No invented dates?
- No invented amounts?
- No invented communications?
- No invented delivery/service?
- No unsupported admission?
- No inconsistent chronology?

### C. Legal authority
- Exact current-law claims verified?
- Official sources only for verified law?
- Correct effective version?
- No irrelevant article dumping?
- No secondary-source authority?

### D. Procedure
For filings:
- correct route/court/body verified or flagged?
- pre-trial/conciliation checked?
- deadline checked?
- standing/status checked?
- fee/duty checked?
- mandatory attachments checked?

### E. Evidence
- Every material allegation mapped to evidence?
- Unsupported allegations softened/removed?
- Evidence gaps disclosed?

### F. Relief
- Requests precise?
- Legally coherent?
- Supported by facts?
- Correct party ordered to do/pay something?
- No contradictory remedies?

### G. Calculations
- components correct?
- totals reconcile?
- formula/rate/dates verified?

### H. Document integrity
- names consistent;
- numbering consistent;
- annexes match references;
- placeholders visible;
- no internal notes accidentally left in filing text unless intentionally marked;
- шапка не содержит дублирующихся меток: `В суд:`, `Истец:`, `Ответчик:`, `Цена иска:` выводятся ровно один раз, и значение реквизита не повторяет саму метку (`Истец: Истец: Иванов И.И.` = `FAIL`);
- нумерация приложений независима от просительной части — см. Release Gate, проверка 3;
- **преамбула содержит полную идентификацию обеих сторон и основание полномочий подписанта** — обязательный чек для договоров, см. Release Gate, проверка 4;
- номер раздела или пункта выводится ровно один раз: `1. 1. Предмет Договора`, `1.1. 1.1. По настоящему Договору...`, `3.2. 3.1.1. ...` = `FAIL` (раздел H). Нумерует только экспорт — см. [contracts.md](contracts.md), раздел «Нумерация разделов и пунктов».

### I. Language
- professional Russian/Kazakh;
- no slang;
- no unnecessary aggression;
- no fake certainty.

## QA result

Compute:
- `PASS`
- `PASS_WITH_FLAGS`
- `FAIL`
- `FAIL_CRITICAL`

The status itself is computed internally, but its outcome is published — see Release Gate.

If `FAIL` or `FAIL_CRITICAL`, revise before release.

## Release Gate

FINAL LEGAL QA — это блокирующий шлюз, а не чек-лист «для сведения». Его результат управляет тем, что физически уходит пользователю. QA, который зафиксировал нарушение, но не остановил выдачу, считается непройденным.

### Блокировка выдачи

`QA result` = `FAIL` или `FAIL_CRITICAL` = документ НЕ передаётся пользователю как финальный.

Вместо документа агент возвращает:

**(а)** список конкретных нарушенных пунктов QA — с указанием раздела (A–I) и того, что именно не выполнено;

**(б)** точные уточняющие вопросы или перечень недостающих данных и документов;

**(в)** статус `PRELIMINARY DRAFT`.

Запрещено:
- выдавать документ «как есть» с оговоркой, что его надо проверить перед подачей;
- прятать нарушения в сноску, футер, служебный комментарий или caption файла;
- заменять недостающий BLOCKING-реквизит плейсхолдером, чтобы обойти `FAIL`;
- повышать `readiness_status`, пока хотя бы один пункт QA не пройден;
- отправлять файл документа, когда результат QA — `FAIL` или `FAIL_CRITICAL`.

Если рабочий черновик всё же показывается пользователю, он маркируется `PRELIMINARY DRAFT`, сопровождается пунктами (а) и (б) и прямо обозначается как непригодный к подаче.

### Видимый QA-отчёт

Каждый финальный документ обязан сопровождаться видимым (не скрытым) QA-отчётом:
- пройденные и непройденные пункты по разделам A–I;
- по каждому непройденному пункту — конкретная причина, а не общая формулировка;
- итоговый `readiness_status`.

Отчёт показывается пользователю сразу после документа. Внутренний QA без видимого отчёта считается непройденным. Формат вывода — см. [output-contract.md](output-contract.md).

### Обязательные проверки перед выдачей

Выполняются до формирования итогового ответа. Невыполнение любой из них = `FAIL`.

#### 1. Evidence-map cross-check

Каждый факт, требующий документального подтверждения (платёж, передача денег, уведомление), должен иметь соответствующий пункт в разделе «Приложения». Если факта в приложениях нет — либо добавить его в список недостающих документов, либо смягчить формулировку факта в тексте иска.

Проверять построчно: для каждого утверждения фактической части найти приложение, которое его доказывает.

Типовые факты, требующие приложения:
- передача или получение денег, платёж, частичное погашение;
- направление и вручение претензии, уведомления, требования;
- приёмка работ или услуг;
- заключение, изменение, расторжение договора.

Утверждение такого факта как доказанного при отсутствии приложения = `FAIL`. Относится к разделу E.

#### 2. Госпошлина

Для любого искового заявления с денежным требованием обязателен расчёт госпошлины через `legal_calc.py` (используя действующие ставки НК РК) ЛИБО явная пометка `[ТРЕБУЕТ РАСЧЁТА ГОСПОШЛИНЫ]`, но не полное отсутствие упоминания.

- полное отсутствие упоминания госпошлины = `FAIL`;
- размер госпошлины без верифицированной действующей ставки = `FAIL`;
- пометка `[ТРЕБУЕТ РАСЧЁТА ГОСПОШЛИНЫ]` допустима и не блокирует выдачу, но понижает `readiness_status` минимум до `LAWYER-REVIEW DRAFT`.

Относится к разделу D.

#### 3. Нумерация приложений

Нумерация приложений начинается заново с 1 и не продолжает нумерацию просительной части.

Просительная часть и «Приложения» — два независимых нумерованных списка. Приложение, начинающееся с номера, следующего за последним требованием, = `FAIL`. Относится к разделу H.

#### 4. Преамбула договора

Для любого договора преамбула обязана содержать полную идентификацию обеих сторон и основание полномочий подписанта. Проверяется наличие по каждой стороне:

- организационно-правовой формы и полного наименования (либо ФИО для физического лица);
- роли по договору — «именуемое(-ый) в дальнейшем «...»»;
- лица, подписывающего договор, — «в лице [должность] [ФИО]»;
- основания полномочий — «действующего на основании [устава / доверенности № и дата / свидетельства о государственной регистрации ИП № и дата]».

Переход от места и даты заключения сразу к формуле «совместно именуемые «Стороны», заключили настоящий Договор» = `FAIL`. Реквизиты сторон в конце документа преамбулу не заменяют.

Если данные неизвестны, структура абзаца сохраняется целиком, а на месте недостающего выводится `[ТРЕБУЕТ УТОЧНЕНИЯ: ...]`; такой договор выпускается со статусом `PRELIMINARY DRAFT`. Полное отсутствие блока = `FAIL`. Относится к разделу H. Формат — см. [contracts.md](contracts.md), раздел «Преамбула (идентификация сторон)».

## Mandatory repair loop

When QA fails:
1. identify exact failed checks;
2. return to the responsible module;
3. regenerate only the affected sections where possible;
4. rerun QA;
5. release only after pass/pass_with_flags.

Если дефект нельзя устранить регенерацией, потому что не хватает исходных данных, цикл не зацикливается: выход происходит через Release Gate — пользователю уходят нарушенные пункты, уточняющие вопросы и статус `PRELIMINARY DRAFT`, а не документ.

## User-facing status

Expose drafting readiness:
- `PRELIMINARY DRAFT`
- `LAWYER-REVIEW DRAFT`
- `READY FOR FINAL HUMAN REVIEW`

Статус выводится всегда и вместе с QA-отчётом, а не вместо него.
