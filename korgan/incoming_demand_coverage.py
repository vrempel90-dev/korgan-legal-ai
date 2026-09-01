"""Полнота ответа на каждое требование исходного документа.

Непустой пересказ и несколько возражений не доказывают полноту: из пяти
требований модель может разобрать четыре и потерять пятое. Поэтому исходный
петитум извлекается только из явно обозначенной просительной части материалов,
а каждый его пункт должен быть узнаваем в содержательной позиции адресата.

Извлечение намеренно консервативно. Сумма из фабулы, цена договора или платёж
не становятся требованием. Если в материалах нет явного маркера вроде
«ИСКОВЫЕ ТРЕБОВАНИЯ», «ПРОШУ СУД» или «истец просит взыскать», проверка ничего
не угадывает. Пересказ входящих требований также не считается ответом на них:
владельцы документа передают сюда только разделы признания, оспаривания,
позиции, возражений, разбора расчёта и итоговой просьбы.
"""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass

from korgan.legal_calc import parse_all_amounts_kzt

_SPACE_RE = re.compile(r"\s+")
_NUMBERING_RE = re.compile(r"^\s*(?:[-–—•*]|\(?\d{1,2}[.)])\s*")

# Самостоятельный заголовок просительной части. Он запускает закрытый блок;
# произвольные суммы до него и разделы после него не читаются как требования.
_DEMAND_HEADING_RE = re.compile(
    r"(?i)^\s*(?:"
    r"исков\w*\s+требован\w*|просительн\w*\s+часть|"
    r"требован\w*\s+(?:иск\w*|претензи\w*|заявител\w*|кредитор\w*)|"
    r"просим\s+суд|прошу\s+суд|просим|прошу|требуем|требую"
    r")\s*:?[\s]*$"
)

# Явное требование внутри обычного абзаца. В отличие от одного слова
# «требование», здесь обязательно названы субъект и волеизъявление.
_DIRECT_DEMAND_RE = re.compile(
    r"(?i)(?:"
    r"(?:истец|заявитель|кредитор|взыскатель|отправитель\s+претензии)\s+"
    r"(?:просит|требует|заявляет\s+требование)|"
    r"(?:в\s+претензи\w*|в\s+иск\w*)\s+(?:просит|требует)|"
    r"просим\s+взыскать|прошу\s+взыскать|требуем\s+(?:уплатить|вернуть|возместить)"
    r")"
)

_STOP_HEADING_RE = re.compile(
    r"(?i)^\s*(?:"
    r"приложени\w*|перечень\s+приложен\w*|правов\w*\s+обоснован\w*|"
    r"обстоятельств\w*\s+дела|доказательств\w*|расч[её]т\w*|"
    r"дата|подпись|представитель|ходатайств\w*"
    r")\s*:?[\s]*$"
)

# Граница между двумя требованиями в одной строке. Разделяем запятую только
# перед новой суммой, а «и» — только перед распознаваемым самостоятельным
# предметом, чтобы не дробить «договор и накладную».
_COMPONENT_SEPARATOR_RE = re.compile(
    r"\s*;\s*|"
    r",\s*(?=\d{1,3}(?:[\s ]\d{3})|\d+\s*(?:тенге|теңге|тг\b|₸|kzt))|"
    r"\s+и\s+(?=(?:"
    r"(?:основн\w*\s+)?долг\w*|задолженност\w*|неустойк\w*|пен\w*|штраф\w*|"
    r"убыт\w*|моральн\w*\s+вред\w*|процент\w*|возврат\w*|вернут\w*|"
    r"расход\w*|издерж\w*|расторг\w*|признат\w*|обязат\w*"
    r"))",
    re.IGNORECASE,
)

_ACTION_RE = re.compile(
    r"(?i)(?:взыска\w*|уплат\w*|оплат\w*|возмест\w*|компенсир\w*|"
    r"верну\w*|переда\w*|обяза\w*|устран\w*|расторг\w*|призна\w*|"
    r"высели\w*|освободи\w*|предостав\w*|прекрат\w*)"
)

_CATEGORY_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("debt", re.compile(r"(?i)(?:основн\w*\s+долг\w*|задолженност\w*|сумм\w*\s+долг\w*)")),
    ("penalty", re.compile(r"(?i)(?:неустойк\w*|пен(?:я|и|ю|ей|е)\b|штраф\w*)")),
    ("damages", re.compile(r"(?i)(?:убыт\w*|реальн\w*\s+ущерб\w*|упущенн\w*\s+выгод\w*)")),
    ("representative_expense", re.compile(r"(?i)(?:представител\w*|адвокат\w*|юридическ\w*\s+(?:услуг\w*|помощ\w*))")),
    ("expert_expense", re.compile(r"(?i)(?:экспертиз\w*|эксперт\w*|оценщик\w*|оценк\w*\s+(?:стоимост\w*|ущерб\w*))")),
    ("state_duty", re.compile(r"(?i)(?:государственн\w*\s+пошлин\w*|мемлекеттік\s+баж\w*)")),
    ("moral_damage", re.compile(r"(?i)(?:моральн\w*\s+вред\w*)")),
    ("interest", re.compile(r"(?i)(?:процент\w*\s+(?:за\s+пользован\w*|по\s+стать\w*\s*353)|стать\w*\s*353)")),
    ("return_property", re.compile(r"(?i)(?:возврат\w*|верну\w*|переда\w*).{0,80}(?:имуществ\w*|оборудован\w*|товар\w*|документ\w*)|(?:имуществ\w*|оборудован\w*|товар\w*|документ\w*).{0,80}(?:возврат\w*|верну\w*|переда\w*)")),
    ("defects", re.compile(r"(?i)(?:устран\w*\s+недостат\w*|исправ\w*\s+дефект\w*)")),
    ("termination", re.compile(r"(?i)(?:расторг\w*|прекращени\w*)\s+(?:договор\w*|соглашени\w*)")),
    ("invalidity", re.compile(r"(?i)(?:призна\w*).{0,60}(?:недействительн\w*|незаконн\w*)")),
)

_STOPWORDS = {
    "истец", "ответчик", "заявитель", "кредитор", "взыскатель", "суд", "просит", "просим",
    "прошу", "требует", "требуем", "требование", "требования", "взыскать", "взыскание",
    "уплатить", "оплатить", "возместить", "обязать", "ответчика", "истца", "размере", "сумме",
    "тенге", "теңге", "основным", "основаниям", "удовлетворении", "отказать", "исковых",
}
_WORD_RE = re.compile(r"[0-9A-Za-zА-Яа-яЁёӘәҒғҚқҢңӨөҰұҮүҺһІі-]+")


@dataclass(frozen=True, slots=True)
class IncomingDemand:
    """Один самостоятельный пункт входящей просительной части."""

    text: str
    amounts: tuple[int, ...]
    categories: tuple[str, ...]
    key_terms: tuple[str, ...]


def _clean(value: str) -> str:
    return _SPACE_RE.sub(" ", str(value or "")).strip(" \t\r\n;,.:")


def _category_codes(text: str) -> tuple[str, ...]:
    return tuple(code for code, pattern in _CATEGORY_PATTERNS if pattern.search(text))


def _term_key(word: str) -> str:
    value = word.lower().replace("ё", "е")
    if value.isdigit() or len(value) < 5 or value in _STOPWORDS:
        return ""
    # Не морфологический анализ, а устойчивый идентификатор предмета. Семь
    # букв сохраняют «оборудов-», «накладн-», марки и номера остаются целиком.
    return value if any(ch.isdigit() for ch in value) else value[:7]


def _key_terms(text: str) -> tuple[str, ...]:
    result: list[str] = []
    for word in _WORD_RE.findall(text):
        key = _term_key(word)
        if key and key not in result:
            result.append(key)
    return tuple(result)


def _split_components(line: str) -> list[str]:
    cleaned = _clean(_NUMBERING_RE.sub("", line))
    if not cleaned:
        return []
    return [part for part in (_clean(item) for item in _COMPONENT_SEPARATOR_RE.split(cleaned)) if part]


def _looks_like_demand(text: str, *, inside_block: bool) -> bool:
    if _DIRECT_DEMAND_RE.search(text):
        return True
    if not inside_block:
        return False
    return bool(_ACTION_RE.search(text) or parse_all_amounts_kzt(text) or _category_codes(text))


def _raw_demand_lines(case_context: str) -> list[str]:
    """Извлечь только строки явно обозначенной просительной части."""
    result: list[str] = []
    inside_block = False
    found_in_block = False

    for raw in str(case_context or "").splitlines():
        line = _clean(raw)
        if not line:
            continue
        if _DEMAND_HEADING_RE.fullmatch(line):
            inside_block = True
            found_in_block = False
            continue
        if inside_block and _STOP_HEADING_RE.fullmatch(line):
            inside_block = False
            found_in_block = False
            continue

        if inside_block:
            candidate = _NUMBERING_RE.sub("", line).strip()
            if _looks_like_demand(candidate, inside_block=True):
                result.append(candidate)
                found_in_block = True
                continue
            # После начавшегося списка первый обычный абзац завершает блок. Так
            # пояснение, доказательство или подпись не превращаются в петитум.
            if found_in_block:
                inside_block = False
                found_in_block = False

        if _DIRECT_DEMAND_RE.search(line):
            result.append(line)

    return result


def incoming_demands(case_context: str) -> list[IncomingDemand]:
    """Самостоятельные пункты явной просительной части входящих материалов."""
    demands: list[IncomingDemand] = []
    seen: set[str] = set()
    for line in _raw_demand_lines(case_context):
        for component in _split_components(line):
            normalized = re.sub(r"\W+", "", component.lower())
            if not normalized or normalized in seen:
                continue
            seen.add(normalized)
            demands.append(
                IncomingDemand(
                    text=component,
                    amounts=tuple(parse_all_amounts_kzt(component)),
                    categories=_category_codes(component),
                    key_terms=_key_terms(component),
                )
            )
    return demands


def _response_evidence(response_lines: list[str], summaries: list[str] | None) -> tuple[str, set[int], set[str], set[str]]:
    summary_keys = {re.sub(r"\W+", "", str(item or "").lower()) for item in summaries or []}
    lines = [
        _clean(line)
        for line in response_lines or []
        if _clean(line) and re.sub(r"\W+", "", str(line or "").lower()) not in summary_keys
    ]
    text = "\n".join(lines)
    return (
        text,
        set(parse_all_amounts_kzt(text)),
        set(_category_codes(text)),
        set(_key_terms(text)),
    )


def uncovered_incoming_demands(
    case_context: str,
    response_lines: list[str],
    *,
    summaries: list[str] | None = None,
) -> list[str]:
    """Вернуть входящие требования без узнаваемого содержательного ответа.

    ``response_lines`` должны принадлежать именно позиции адресата. Поле
    claim_summary передавать нельзя: копия входящего петитума — ещё не признание,
    возражение или разбор. ``summaries`` служит страховкой для вызывающего кода,
    который собирает линии обобщённо: точные строки пересказа будут исключены.
    """
    demands = incoming_demands(case_context)
    if not demands:
        return []

    _, response_amounts, response_categories, response_terms = _response_evidence(
        response_lines, summaries
    )
    amount_counts = Counter(amount for demand in demands for amount in set(demand.amounts))

    missing: list[str] = []
    for demand in demands:
        unique_amount_hit = any(
            amount_counts[amount] == 1 and amount in response_amounts for amount in demand.amounts
        )
        category_hit = bool(set(demand.categories) & response_categories)
        # Нераспознанный неденежный предмет (например, конкретная вещь) можно
        # связать только по его содержательным словам. Одного общего термина
        # достаточно лишь при отсутствии более надёжной суммы/категории.
        term_hit = bool(set(demand.key_terms) & response_terms) if not demand.amounts and not demand.categories else False
        if unique_amount_hit or category_hit or term_hit:
            continue
        missing.append(
            "по входящему требованию не дан содержательный ответ: " + demand.text[:220]
        )
    return missing
