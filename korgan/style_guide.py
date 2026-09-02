"""Правила STYLE_GUIDE.md в машинной форме.

Файл ``STYLE_GUIDE.md`` — не промпт и не памятка: каждое его правило имеет
здесь реализацию и проверяется post-generation линтером. Разделение сделано
намеренно. Человек читает обоснование правила в Markdown; код проверяет
документ и не пересказывает обоснование заново. Тест сверяет два списка
идентификаторов и версию, поэтому правило нельзя добавить в текст, не
реализовав, и нельзя реализовать, не описав.

Проверки детерминированные. Ни одна из них не спрашивает модель, соответствует
ли документ стилю: соответствие проверяется по структуре черновика, а
контрольная сумма ИИН/БИН — арифметикой, которую тем же способом выполняет суд.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

#: Версия набора правил. Сверяется с заголовком STYLE_GUIDE.md.
STYLE_GUIDE_VERSION = "1.0.0"


@dataclass(frozen=True, slots=True)
class StyleRule:
    rule_id: str
    title: str
    #: Что предложить исправить, когда правило нарушено.
    fix: str


RULES: tuple[StyleRule, ...] = (
    StyleRule(
        "SG-01",
        "Вступительная ссылка на статью 8 ГПК РК — только подтверждённая",
        "снять номер статьи и оставить формулировку о праве на судебную защиту "
        "без ссылки либо подтвердить норму по официальному источнику",
    ),
    StyleRule(
        "SG-02",
        "Судебные расходы — отдельный пункт просительной части",
        "вынести возмещение государственной пошлины и издержек в самостоятельный "
        "пункт просительной части",
    ),
    StyleRule(
        "SG-03",
        "Родовая и территориальная подсудность разведены",
        "назвать статью 27 ГПК РК как основание родовой подсудности, а статью 29 — "
        "как основание территориальной, разными предложениями",
    ),
    StyleRule(
        "SG-04",
        "Шапка документа несёт корректные реквизиты сторон",
        "убрать номер, не проходящий контрольную сумму, либо взять реквизит из "
        "материалов дела; выдуманный БИН/ИИН недопустим",
    ),
    StyleRule(
        "SG-05",
        "Обязательные разделы проверяются по структуре, а не по строке",
        "заполнить отсутствующий раздел документа",
    ),
    StyleRule(
        "SG-06",
        "Правила версионируются и тестируются",
        "привести STYLE_GUIDE.md и korgan/style_guide.py к одному набору правил",
    ),
)

RULE_IDS: tuple[str, ...] = tuple(rule.rule_id for rule in RULES)
_BY_ID: dict[str, StyleRule] = {rule.rule_id: rule for rule in RULES}


def rule(rule_id: str) -> StyleRule:
    return _BY_ID[rule_id]


# --------------------------------------------------------------------------
# SG-04. Контрольная сумма ИИН/БИН
# --------------------------------------------------------------------------

_WEIGHTS_1 = (1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11)
_WEIGHTS_2 = (3, 4, 5, 6, 7, 8, 9, 10, 11, 1, 2)

_ID_NUMBER_RE = re.compile(r"\b(?:ИИН|БИН)\s*[:\-–]?\s*(?P<value>\d{12})\b", re.IGNORECASE)
_BARE_12_RE = re.compile(r"(?<!\d)(?P<value>\d{12})(?!\d)")


def id_number_is_valid(value: str) -> bool:
    """Проверить контрольный разряд ИИН/БИН по правилам Республики Казахстан.

    Проверка ровно та же, которую выполняет суд и любой государственный реестр,
    поэтому выдуманный номер отсеивается здесь, а не при возврате иска.
    Двухступенчатый алгоритм: если первая свёртка даёт 10, применяется второй
    набор весов; повторная 10 означает, что такого номера не существует.
    """
    digits = [int(char) for char in (value or "").strip() if char.isdigit()]
    if len(digits) != 12:
        return False

    checksum = sum(digit * weight for digit, weight in zip(digits[:11], _WEIGHTS_1)) % 11
    if checksum == 10:
        checksum = sum(digit * weight for digit, weight in zip(digits[:11], _WEIGHTS_2)) % 11
        if checksum == 10:
            return False
    return checksum == digits[11]


def id_numbers_in(text: str) -> list[str]:
    """Все ИИН/БИН строки — и помеченные, и стоящие без метки."""
    values: list[str] = []
    for match in _ID_NUMBER_RE.finditer(text or ""):
        value = match.group("value")
        if value not in values:
            values.append(value)
    for match in _BARE_12_RE.finditer(text or ""):
        value = match.group("value")
        if value not in values:
            values.append(value)
    return values


# --------------------------------------------------------------------------
# SG-02, SG-03, SG-05 — распознаватели
# --------------------------------------------------------------------------

_COURT_COST_RE = re.compile(
    r"(?:государственн\w*\s+пошлин\w*|госпошлин\w*|судебн\w*\s+(?:расход\w*|издерж\w*))",
    re.IGNORECASE,
)
_MONEY_RELIEF_RE = re.compile(
    r"(?:основн\w*\s+долг\w*|задолженност\w*|неустойк\w*|пен[яию]\b|убытк\w*)",
    re.IGNORECASE,
)
_ARTICLE_8_GPK_RE = re.compile(
    r"стать[ияеёю]\w*\s*8\s*(?:гпк\s*рк|гражданск\w*\s+процессуальн\w*\s+кодекс)|"
    r"ст\.\s*8\s*(?:гпк\s*рк|гражданск\w*\s+процессуальн\w*\s+кодекс)",
    re.IGNORECASE,
)
# Номера статей вместе с перечислением: «статьями 27 и 29 ГПК РК» называет обе,
# и правило о разделении подсудностей обязано это видеть — иначе смешение
# проходит именно в той форме, в которой его чаще всего и пишут.
_GPK_ARTICLES_RE = re.compile(
    r"(?:стать[ияеёюям]\w*|ст\.)\s*(?P<numbers>\d+(?:\s*(?:,|и)\s*\d+)*)",
    re.IGNORECASE,
)
_NUMBER_RE = re.compile(r"\d+")
_SUBJECT_MATTER_RE = re.compile(r"родов\w*\s+подсудност|подсудност\w*\s+по\s+родов", re.IGNORECASE)
_TERRITORIAL_RE = re.compile(r"территориальн\w*\s+подсудност|подсудност\w*\s+по\s+мест", re.IGNORECASE)
_SENTENCE_SPLIT_RE = re.compile(r"(?<!\d)[.;](?!\d)|\n")

_LEGAL_ENTITY_RE = re.compile(
    r"\b(?:ТОО|АО|ГУ|РГП|КГП|ПК|ОЮЛ|ИП)\b|товарищество\s+с\s+ограниченной|"
    r"акционерн\w*\s+обществ\w*|государственн\w*\s+учреждени",
    re.IGNORECASE,
)
_ADDRESS_RE = re.compile(
    r"адрес|\bг\.\s|\bгород\b|улиц\w*|\bул\.|проспект|\bпр\.|микрорайон|\bмкр\.|"
    r"\bд\.\s*\d|\bкв\.\s*\d|(?<!\d)\d{6}(?!\d)",
    re.IGNORECASE,
)
_BIN_LABEL_RE = re.compile(r"\bБИН\b", re.IGNORECASE)


def party_is_legal_entity(text: str) -> bool:
    return bool(_LEGAL_ENTITY_RE.search(text or ""))


def party_has_address(text: str) -> bool:
    return bool(_ADDRESS_RE.search(text or ""))


def party_has_bin(text: str) -> bool:
    return bool(_BIN_LABEL_RE.search(text or ""))


def mentions_article_8_gpk(text: str) -> bool:
    return bool(_ARTICLE_8_GPK_RE.search(text or ""))


def _named_articles(text: str) -> set[str]:
    """Номера статей, названные в тексте, включая перечисления."""
    numbers: set[str] = set()
    for match in _GPK_ARTICLES_RE.finditer(text or ""):
        numbers.update(_NUMBER_RE.findall(match.group("numbers")))
    return numbers


def jurisdiction_mixes_venue_rules(text: str) -> bool:
    """Смешаны ли родовая и территориальная подсудность в одном предложении.

    Правило срабатывает только когда названы обе статьи: раздел, объясняющий
    одну подсудность, не обязан упоминать вторую.
    """
    value = text or ""
    if not {"27", "29"} <= _named_articles(value):
        return False
    for sentence in _SENTENCE_SPLIT_RE.split(value):
        if not {"27", "29"} <= _named_articles(sentence):
            continue
        # Обе статьи в одном предложении допустимы, только если их роли названы.
        if _SUBJECT_MATTER_RE.search(sentence) and _TERRITORIAL_RE.search(sentence):
            continue
        return True
    return False


def has_separate_court_cost_request(requests: list[str]) -> bool:
    """Есть ли самостоятельный пункт о судебных расходах.

    Требование, в котором расходы упомянуты рядом с долгом или неустойкой,
    самостоятельным пунктом не считается: суд разрешает их отдельно.
    """
    for raw in requests or []:
        text = str(raw)
        if not _COURT_COST_RE.search(text):
            continue
        if _MONEY_RELIEF_RE.search(text):
            continue
        return True
    return False


def missing_structural_sections(draft: Any, *, monetary: bool) -> list[str]:
    """Пустые обязательные разделы — по структуре черновика, а не по заголовкам."""
    required = [
        ("facts", "обстоятельства дела"),
        ("legal_basis", "правовое обоснование"),
        ("requests", "просительная часть"),
        ("attachments", "приложения"),
    ]
    if monetary:
        required.append(("calculation", "расчёт взыскиваемых сумм"))

    missing: list[str] = []
    for attribute, label in required:
        values = getattr(draft, attribute, None)
        if not isinstance(values, list) or not [item for item in values if str(item).strip()]:
            missing.append(label)
    return missing
