# Kazakhstan Legal Research

## Objective

Supply verified, current legal authority for KORGAN outputs.

## Source hierarchy

Use approved official Kazakhstan sources supplied/retrieved by the host application.

Preferred:
1. official consolidated legal act;
2. official effective-date/publication metadata;
3. official court/judicial guidance;
4. official competent authority guidance;
5. KORGAN-approved internal legal knowledge.

## Never treat as authority

- commercial legal sites;
- blogs;
- aggregators;
- unofficial code mirrors;
- news articles;
- forums;
- social posts;
- unattributed summaries.

## Research workflow

For each legal proposition:

1. State the exact proposition to verify.
2. Identify the governing act.
3. Retrieve the current/effective provision.
4. Verify article/paragraph/subparagraph.
5. Verify effective status/date if material.
6. Capture enough source context to avoid cherry-picking.
7. **Capture the provision's own words** — скопируй дословный текст именно той
   части/пункта, на которую будешь ссылаться. Без этого текста шаг 8 выполнить
   нельзя.
8. **Provision-text lock** — сверь свою формулировку с этим текстом построчно,
   до того как она попадёт в документ. См. раздел «Paraphrase lock» ниже и
   [source-verification.md](source-verification.md).
9. Map the provision to the proposition.
10. Mark:
   - `VERIFIED`
   - `PARTIALLY_VERIFIED`
   - `NEEDS_VERIFICATION`

## Paraphrase lock

Верный номер статьи не делает верным её пересказ. Норма может быть найдена
правильно, действовать, открываться по официальной ссылке — и всё равно быть
изложена неточно. Это отдельный отказ, и он не ловится проверкой номера.

Правило действует для **любой** нормы, изложенной пересказом, а не дословной
цитатой, и во **всех** типах документов: иски, отзывы, претензии, жалобы,
ходатайства, апелляции, договоры со ссылками на ГК РК, консультации.

Перед тем как написать пересказ нормы в тело документа:

1. Получи точный текст части/пункта из официального источника. Если получить его
   не удалось — пересказ запрещён; допустима только пометка
   `NEEDS_VERIFICATION` с указанием, что именно требует проверки.
2. Разбей собственную формулировку на отдельные смысловые утверждения и сверь
   **каждое** с текстом нормы: кто обязан, что именно, при каких условиях, с
   какими последствиями, к какому кругу лиц или документов это относится.
3. Заблокируй вывод и перепиши точнее либо понизь статус до
   `NEEDS_VERIFICATION`, если формулировка:
   - добавляет требование, которого в тексте нормы нет;
   - подменяет предмет требования (например, норма требует ссылку на
     доказательства, а пересказ говорит о ссылке на нормы права);
   - обобщает узкое условие до общего правила — условие, ограниченное субъектом
     («если документ подписан представителем»), случаем, сроком или видом
     документа, обязано сохраниться в пересказе;
   - превращает право («вправе») в обязанность («обязан») или наоборот;
   - опускает альтернативу, исключение или оговорку, меняющую результат.

Расширение области действия нормы — самый частый и самый незаметный вид этой
ошибки: документ выглядит грамотно, ссылка формально верна, а утверждение
неверно. При малейшем сомнении в объёме нормы понижай статус, а не сглаживай
формулировку.

Дословная цитата **не** снимает требование сверки — она его ужесточает. Цитата в
кавычках допускается только при симметричном, строка в строку, совпадении с
актуальным текстом нормы; частичное совпадение недопустимо. Порядок — см.
[source-verification.md](source-verification.md), раздел «Дословные цитаты».

## Обязательный проход по всем ссылкам

Проверка нормы — не шаг, который выполняется один раз при составлении. Она
выполняется столько раз, сколько в документе ссылок на нормы.

Когда черновик готов, пройди по нему заново и обработай **каждую** ссылку
отдельно: получить актуальный текст части/пункта → сравнить с тем, что написано в
документе → вынести вердикт. Документ, в котором две нормы процитированы точно, а
третья — по отменённой редакции, — это не документ с «в целом проверенным
правом»: сбой происходит на уровне отдельной цитаты, и ловится он только
поцитатным проходом.

Правило действует для всех восьми типов документов: иски, отзывы, претензии,
жалобы, ходатайства, апелляционные жалобы, договоры со ссылками на ГК РК и
консультации.

## High-risk items

Always verify before asserting:
- procedural deadlines;
- limitation periods;
- jurisdiction/venue;
- mandatory conciliation/pre-trial procedure;
- state duty/fee;
- penalty/interest formulas;
- criminal/admin liability;
- rights to suspend/refuse performance;
- mandatory attachments;
- appellate route.

## Conflict handling

If two official sources appear inconsistent:
- compare dates/effective status;
- do not choose silently;
- flag unresolved conflict for human review.

## Legal quotations

Avoid long quotations.
Use concise paraphrase and exact citation when supported.

## No-source behavior

If current law is necessary but official verification is not available:
- give only a preliminary legal explanation;
- do not invent article numbers;
- state exactly what must be verified.


## Resolve-first rule

When official-source browsing/retrieval is available, actively resolve verifiable items before final output. Do not leave article numbers, jurisdiction rules, procedural consequences, or fees as `NEEDS_VERIFICATION` merely to be cautious if they can be verified from approved official sources during the task.

## Civil pre-trial procedure

For Kazakhstan civil proceedings, if a mandatory pre-trial or out-of-court procedure applies, verify the current Civil Procedure Code consequence precisely. Do not conflate:
- return of the claim;
- refusal to accept;
- leaving without movement;
- leaving without consideration.

Use the exact consequence supported by the effective procedural rule.
