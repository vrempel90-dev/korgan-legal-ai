"""Guard against paraphrasing a legal provision into something it does not say.

The failure this closes: a document cited «часть 4 статьи 166 ГПК РК» correctly —
right act, right article, right part, live official source — and then paraphrased
its content wrongly, turning a requirement to reference *evidence* into a
requirement to reference *statutes*, and promoting a rule that is limited to
filings signed by a representative into a rule about every filing. The article
number was verified; the sentence built on it was not.

Verifying the number is therefore not enough. A verified point must carry the
provision's own words, and the paraphrase must be checked against them. This
module performs the mechanical half of that check:

* a paraphrase without the provision text cannot be `VERIFIED` at all;
* a qualifier that narrows the provision (a subject, a condition, an exception)
  must survive into the paraphrase, otherwise the paraphrase generalised it;
* a substantive term that appears in the paraphrase but nowhere in the
  provision text is a requirement the model added.

These are heuristics over wording, not legal reasoning: they catch the
mechanical drift that produced the defect above, and they fail *soft* — a
finding downgrades the point to NEEDS_VERIFICATION rather than asserting the
paraphrase is wrong. The substantive line-by-line comparison remains the model's
obligation under reference/source-verification.md, and the lawyer's after that.
"""

from __future__ import annotations

import re

# Qualifiers that narrow a provision. If the provision text carries one and the
# paraphrase does not, the paraphrase has widened the rule.
_SCOPE_QUALIFIERS: tuple[tuple[str, str], ...] = (
    (r"представител", "норма ограничена случаем участия представителя"),
    (r"прокурор", "норма ограничена участием прокурора"),
    (r"несовершеннолетн", "норма ограничена несовершеннолетними"),
    (r"иностранн", "норма ограничена иностранным субъектом"),
    (r"\bтольк[оа]\b", "норма содержит ограничение «только»"),
    (r"исключительн", "норма содержит ограничение «исключительно»"),
    (r"при услови", "норма действует при определённом условии"),
    (r"в случа[еях]", "норма привязана к конкретному случаю"),
    (r"\bлибо\b", "норма предлагает альтернативу, а не единственный вариант"),
    (r"\bвправе\b", "норма формулирует право, а не обязанность"),
    (r"\bобяза[нно]", "норма формулирует обязанность, а не право"),
    (r"\bне\s+(?:вправе|допускается|может)\b", "норма содержит запрет"),
)

# Substantive anchors that are routinely swapped for one another in paraphrase.
_SUBSTANTIVE_ANCHORS: tuple[tuple[str, str], ...] = (
    (r"доказательств", "доказательства"),
    (r"нормативн", "нормативные правовые акты"),
    (r"\bзакон", "закон"),
    (r"срок", "срок"),
    (r"пошлин", "государственная пошлина"),
    (r"подсудност", "подсудность"),
    (r"подведомственност", "подведомственность"),
    (r"неустойк", "неустойка"),
    (r"штраф", "штраф"),
    (r"процент", "проценты"),
    (r"убытк", "убытки"),
    (r"расторжен", "расторжение"),
    (r"письменн", "письменная форма"),
    (r"нотариальн", "нотариальная форма"),
    (r"возврат", "возврат"),
    (r"отказ", "отказ"),
)


# ─── Величины: срок, ставка, размер ───────────────────────────────────────────
#
# Норма о сроке называет срок, норма о ставке называет ставку. Если пересказ
# называет величину, а в тексте нормы её нет, то либо пересказ выдумал цифру,
# либо — что случается чаще — верное утверждение ушло под чужим номером статьи.
# Оба исхода одинаково недопустимы, и оба видны механически.

_NUMERAL_WORDS: tuple[tuple[str, int, bool], ...] = (
    # форма, значение, требуется ли закрывающая граница слова.
    # Косвенные формы граница не замыкает: «трёх» должно находиться и внутри
    # «трёхдневный», иначе норма, сформулированная одним словом, читалась бы
    # как молчащая о сроке.
    ("одного", 1, False), ("одному", 1, False), ("одна", 1, True), ("одну", 1, True),
    ("одно", 1, True), ("один", 1, True),
    ("двух", 2, False), ("двум", 2, False), ("две", 2, True), ("два", 2, True),
    ("трех", 3, False), ("трем", 3, False), ("три", 3, True),
    ("четырех", 4, False), ("четырем", 4, False), ("четыре", 4, True),
    ("пяти", 5, False), ("пять", 5, True),
    ("шести", 6, False), ("шесть", 6, True),
    ("семи", 7, False), ("семь", 7, True),
    ("восьми", 8, False), ("восемь", 8, True),
    ("девяти", 9, False), ("девять", 9, True),
    ("десяти", 10, False), ("десять", 10, True),
    ("одиннадцати", 11, False), ("одиннадцать", 11, True),
    ("двенадцати", 12, False), ("двенадцать", 12, True),
    ("пятнадцати", 15, False), ("пятнадцать", 15, True),
    ("двадцати", 20, False), ("двадцать", 20, True),
    ("тридцати", 30, False), ("тридцать", 30, True),
    ("сорока", 40, False), ("сорок", 40, True),
    ("пятидесяти", 50, False), ("пятьдесят", 50, True),
    ("шестидесяти", 60, False), ("шестьдесят", 60, True),
    ("девяноста", 90, False), ("девяносто", 90, True),
    ("ста", 100, True), ("сто", 100, True),
)

# Единицы, по которым величина вообще имеет юридический смысл. Номер статьи,
# пункта или дела единицей не является и в пары не попадает.
_UNIT_CLASSES: tuple[tuple[str, str, str], ...] = (
    # код, что ищем в тексте, как назвать в замечании
    ("year", r"год\w*|лет\b|летн\w*|годичн\w*|годов\w*", "года"),
    ("month", r"месяц\w*|месячн\w*", "месяцев"),
    ("week", r"недел\w*|недельн\w*", "недель"),
    ("day", r"дн[еяиюё]\w*|дней\b|дневн\w*|сут(?:ки|ок|очн\w*)", "дней"),
    ("percent", r"процент\w*|%", "процентов"),
    ("mrp", r"\bмрп\b|месячн\w*\s+расчетн\w*\s+показател\w*", "МРП"),
)

_UNIT_LOOKUP: tuple[tuple[str, re.Pattern[str], str], ...] = tuple(
    (code, re.compile(pattern), label) for code, pattern, label in _UNIT_CLASSES
)

_TOKEN_RE = re.compile(r"[a-zа-я0-9]+(?:[,.]\d+)?|%", re.IGNORECASE)


def _normalize(text: str) -> str:
    return (text or "").replace("ё", "е").replace("Ё", "Е").lower()


def _present(pattern: str, text: str) -> bool:
    return re.search(pattern, text) is not None


_FACT_APPLICATION_RE = re.compile(
    r"(?:обстоятельств\w*\s*\d|"                     # «(обстоятельство 4)»
    r"\bистц?\w*\b|\bответчик\w*\b|\bстороны?\b|\bсторон\w*\b|"
    r"договор\w*\s*№|\bп\.\s*\d|\bпункт\w*\s+\d|"
    r"\d{1,2}\s+(?:январ|феврал|март|апрел|ма[йя]|июн|июл|август|сентябр|октябр|ноябр|декабр)\w*|"
    r"\d{2}\.\d{2}\.\d{4}|"
    r"\d[\d\s ]*(?:тенге|теңге|₸))",
    re.IGNORECASE,
)


def _norm_claim_only(statement: str) -> str:
    """Оставить только предложения, описывающие содержание нормы.

    Строка правового обоснования состоит из двух разных утверждений:

        «Неустойкой признаётся определённая договором денежная сумма…»   ← о норме
        «…её размер согласован сторонами в пункте 6.3 (обстоятельство 6)» ← о деле

    Сверять с текстом нормы имеет смысл только первое. Второе называет
    обстоятельства дела, и любое его слово неизбежно отсутствует в тексте
    закона.

    Если по этому признаку не осталось ни одного предложения, возвращается
    исходное утверждение целиком: лучше лишняя проверка, чем пропущенная.
    """
    text = str(statement or "")
    sentences = [part.strip() for part in re.split(r"(?<=[.;])\s+", text) if part.strip()]
    norm_sentences = [part for part in sentences if not _FACT_APPLICATION_RE.search(part)]
    if not norm_sentences:
        return text
    return " ".join(norm_sentences)


def _numeral_value(token: str) -> str:
    """Каноническое значение числительного: цифрами или словом — безразлично."""
    if re.fullmatch(r"\d+(?:[,.]\d+)?", token):
        return token.replace(",", ".").rstrip("0").rstrip(".") if "," in token or "." in token else token
    for form, value, closed in _NUMERAL_WORDS:
        if token == form if closed else token.startswith(form):
            return str(value)
    return ""


def _value_forms(value: str) -> str:
    """Регулярное выражение всех написаний величины — цифрами и словами."""
    forms = [rf"\b{re.escape(value)}\b"]
    if "." in value:
        forms.append(rf"\b{re.escape(value.replace('.', ','))}\b")
    for form, numeral, closed in _NUMERAL_WORDS:
        if str(numeral) != value:
            continue
        forms.append(rf"\b{form}\b" if closed else rf"\b{form}")
    return "|".join(forms)


def _magnitudes(text: str) -> list[tuple[str, str, str, str]]:
    """Пары «величина + единица», названные в тексте.

    Возвращает (значение, код единицы, как записано числительное, как записана
    единица). Единица ищется в пределах двух слов после числительного: «три
    года», «десяти календарных дней», «один процент от суммы иска».
    """
    tokens = _TOKEN_RE.findall(text)
    found: list[tuple[str, str, str, str]] = []
    for index, token in enumerate(tokens):
        value = _numeral_value(token)
        if not value:
            continue
        for unit_token in tokens[index + 1 : index + 4]:
            code, label = "", ""
            for unit_code, pattern, unit_label in _UNIT_LOOKUP:
                if pattern.fullmatch(unit_token):
                    code, label = unit_code, unit_label
                    break
            if not code:
                continue
            item = (value, code, token, unit_token)
            if item not in found:
                found.append(item)
            break
    return found


def _magnitude_defects(norm_claim: str, provision: str) -> list[str]:
    """Величины, которые пересказ утверждает, а текст нормы не содержит."""
    defects: list[str] = []
    for value, code, numeral_token, unit_token in _magnitudes(norm_claim):
        unit_pattern = next(pattern for unit_code, pattern, _ in _UNIT_LOOKUP if unit_code == code)
        if re.search(_value_forms(value), provision) and unit_pattern.search(provision):
            continue
        defects.append(
            f"пересказ называет величину «{numeral_token} {unit_token}», которой нет в тексте нормы: "
            "либо величина взята не из закона, либо верное утверждение приведено "
            "со ссылкой на другую статью"
        )
    return defects


def paraphrase_defects(statement: str, provision_text: str) -> list[str]:
    """Compare a paraphrase against the provision's own words.

    Returns human-readable findings; an empty list means the mechanical check
    found no drift. It never returns "correct" — only "no drift detected".
    """
    claim = _normalize(statement)
    provision = _normalize(provision_text)

    if not claim.strip():
        return ["пустое юридическое утверждение"]
    if not quote_is_usable(provision_text):
        return [
            "нет пригодной дословной выдержки части/пункта нормы: пересказ невозможно сверить "
            "построчно, статус не может быть выше NEEDS_VERIFICATION"
        ]

    defects: list[str] = []

    for pattern, explanation in _SCOPE_QUALIFIERS:
        if _present(pattern, provision) and not _present(pattern, claim):
            defects.append(
                f"пересказ обобщает узкое условие нормы: {explanation}, но в формулировке это ограничение отсутствует"
            )

    # Якоря ищут выдуманное требование закона, поэтому сверяются только с той
    # частью утверждения, которая говорит О НОРМЕ. Предложение, применяющее
    # норму к делу, обязано называть обстоятельства — срок по договору,
    # возврат аванса, отказ ответчика, — и раньше каждое такое слово читалось
    # как «пересказ вводит требование, которого нет в тексте нормы».
    # Профессионально составленный документ блокировался именно за то, что
    # связывает норму с фактом; см. _norm_claim_only.
    norm_claim = _norm_claim_only(statement)
    defects.extend(_magnitude_defects(_normalize(norm_claim), provision))
    for pattern, label in _SUBSTANTIVE_ANCHORS:
        if _present(pattern, norm_claim) and not _present(pattern, provision):
            defects.append(
                f"пересказ вводит требование «{label}», которого нет в тексте нормы"
            )

    return defects


def is_paraphrase_safe(statement: str, provision_text: str) -> bool:
    return not paraphrase_defects(statement, provision_text)


def quote_is_usable(provision_text: str, *, min_chars: int = 40) -> bool:
    """A provision quote must be substantial enough to check a paraphrase against."""
    return len((provision_text or "").strip()) >= min_chars


def verified_claim_line(statement: str, article: str, provision_text: str, source_url: str) -> str:
    """Format an accepted point so the drafter sees the provision's own words.

    The drafting step must be able to re-check its own wording, so the quote
    travels with the conclusion instead of being dropped after research.
    """
    quote = " ".join((provision_text or "").split())[:400]
    return f"{statement} [основание: {article}; текст нормы: «{quote}»; источник: {source_url}]"
