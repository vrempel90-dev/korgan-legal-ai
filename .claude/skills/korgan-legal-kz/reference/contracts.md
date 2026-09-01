# Contract Drafting

## Goal

Create contracts tailored to the transaction, not generic templates.

## Intake

Determine:
- parties and authority;
- transaction/business goal;
- subject/scope;
- deliverables;
- price;
- payment mechanics;
- milestones/deadlines;
- acceptance;
- warranties;
- responsibility allocation;
- confidentiality;
- data;
- IP;
- termination;
- force majeure;
- notices;
- dispute resolution;
- governing law;
- special industry risks.

## Преамбула (идентификация сторон)

Договор не может переходить от места и даты заключения сразу к формуле «совместно
именуемые «Стороны», заключили настоящий Договор». Вводный абзац обязателен и
идентифицирует обе стороны: организационно-правовую форму и наименование, роль по
договору, подписанта и основание его полномочий.

Обязательный формат:

> [Организационно-правовая форма и полное наименование], именуемое(-ый) в дальнейшем
> «Заказчик», в лице [должность] [ФИО], действующего на основании [Устава /
> доверенности № ... от ...], с одной стороны, и [ИП / ТОО], именуемый(-ое) в
> дальнейшем «Исполнитель», действующий на основании [свидетельства о государственной
> регистрации ИП № ... от ... / Устава], с другой стороны, совместно именуемые
> «Стороны», а по отдельности — «Сторона», заключили настоящий Договор о
> нижеследующем.

Основание полномочий по типу стороны:
- директор ТОО/АО — устав;
- иной представитель юридического лица — доверенность с номером и датой;
- индивидуальный предприниматель — свидетельство/уведомление о государственной
  регистрации ИП с номером и датой;
- физическое лицо — действует от своего имени, указываются ИИН и документ,
  удостоверяющий личность.

Если реквизиты, ФИО подписанта или основание полномочий на момент составления
неизвестны, структура абзаца сохраняется целиком, а неизвестное заменяется видимым
`[ТРЕБУЕТ УТОЧНЕНИЯ: ...]` на своём месте. Пропускать блок нельзя: реквизиты в конце
документа преамбулу не заменяют.

Проверка входит в FINAL LEGAL QA, раздел H — см.
[final-legal-qa.md](final-legal-qa.md).

## Нумерация разделов и пунктов

Единственный источник нумерации — код экспорта (`korgan/contract_numbering.py`,
вызывается из `korgan/contract_docx.py`). Модель передаёт только структуру:

- `sections[].heading` — название раздела без номера («Предмет Договора», а не
  «1. Предмет Договора»);
- `sections[].clauses[].text` — текст пункта без номера;
- `sections[].clauses[].subclauses[]` — подпункты; вложенность выражается этим полем,
  а не номером «3.1.1.» внутри текста.

Номера вида `1.`, `1.1.`, `1.1.1.` проставляются при сборке .docx по позиции элемента.
Любой номер, написанный литералом в тексте, срезается на границе с моделью
(`ContractSection.__post_init__`), поэтому «1. 1. Предмет Договора» и
«1.1. 1.1. По настоящему Договору...» невозможны конструктивно. Плоский пункт с
трёхуровневым литеральным номером сворачивается в подпункт предыдущего пункта, чтобы
не терять замысел вложенности.

## Drafting logic

For each material obligation define:
- who must act;
- what exactly must be done;
- when;
- how acceptance is confirmed;
- what happens if not done.

## Commercial balance

Identify clauses that are intentionally one-sided versus accidentally one-sided.
Do not silently favor one party unless the user asks.

## Payment

Specify:
- amount / formula;
- invoice/act trigger;
- due date;
- taxes if relevant and verified;
- consequences of delay only if legally/contractually supportable.

## Acceptance

Avoid ambiguous acceptance.
Define:
- deliverable;
- acceptance period;
- objections;
- correction;
- deemed acceptance only when intended and legally appropriate.

## Termination

Specify:
- grounds;
- notice;
- settlement of completed work;
- return/destruction of materials;
- survival clauses.

## Final contract QA

Check:
- преамбула содержит полную идентификацию обеих сторон и основание полномочий
  подписанта;
- номера разделов и пунктов не задваиваются (нумерует только экспорт);
- defined terms;
- cross-references;
- contradictions;
- missing commercial mechanics;
- impossible deadlines;
- asymmetric liability;
- blank annex references;
- language consistency.
