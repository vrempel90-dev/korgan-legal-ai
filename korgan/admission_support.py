"""Внешняя опора для признаний в состязательных документах.

Признание нельзя доказывать текстом самого отзыва. ``admitted_circumstances``,
``position`` и ``settlement_offer`` пишет одна модель; повтор между ними не
создаёт волеизъявление доверителя. Поэтому денежное, обязательственное или иное
процессуально значимое признание проходит только при прямой признательной фразе
во входящих материалах от лица отвечающей стороны.

Нейтральное обстоятельство (например, факт заключения названного договора)
можно перенести без отдельного глагола «признаю», но только если его ключевые
реквизиты и смысл присутствуют в материалах. Неизвестный номер, дата, сумма,
исполнение, нарушение или качество закрывают этот мягкий путь.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from korgan.legal_calc import parse_all_amounts_kzt

_SENTENCE_RE = re.compile(r"(?<=[.!?;])\s+|\n+")
_WORD_RE = re.compile(r"[0-9A-Za-zА-Яа-яЁёӘәҒғҚқҢңӨөҰұҮүҺһІі-]+")
_IDENTIFIER_RE = re.compile(r"(?i)(?<!\w)(?:№|номер)\s*(?P<value>[A-Za-zА-Яа-я0-9/-]+)")
_DATE_RE = re.compile(
    r"(?<!\d)(?P<day>0?[1-9]|[12]\d|3[01])[./-]"
    r"(?P<month>0?[1-9]|1[0-2])[./-](?P<year>\d{4})(?!\d)"
)

_ADMISSION_RE = re.compile(
    r"(?i)(?:"
    r"\bпризна(?:ю|ем|ём|ет|ют|ётся|ется|н|ны|на)\b|"
    r"\bне\s+оспарива(?:ю|ем|ет|ют|ется|ются)\b|"
    r"\bсоглас(?:ен|на|ны)\b|"
    r"\bподтвержда(?:ю|ем|ет|ют)\b|"
    r"\bготов(?:ы|а)?\s+(?:оплатить|уплатить|исполнить|вернуть)|"
    r"\bмойында(?:ймын|ймыз|йды|лған)\b|\bдаулама(?:ймын|ймыз|йды)\b"
    r")"
)

# То, что нельзя переносить как нейтральный факт. Здесь признание меняет объём
# спора или подтверждает юридически значимое исполнение/нарушение.
_SENSITIVE_RE = re.compile(
    r"(?i)(?:"
    r"долг\w*|задолженност\w*|неустойк\w*|пен(?:я|и|ю|ей|е)\b|штраф\w*|"
    r"убыт\w*|ущерб\w*|обязан\w*|требован\w*|исков\w*|"
    r"исполнен\w*|неисполнен\w*|нарушен\w*|просроч\w*|"
    r"выполнен\w*|оказан\w*|поставлен\w*|передан\w*|принят\w*|"
    r"оплачен\w*|уплачен\w*|получен\w*|подписан\w*|"
    r"качествен\w*|надлежащ\w*|недостат\w*|дефект\w*|"
    r"ответственност\w*|вина\w*|правонаруш\w*"
    r")"
)

# Только заголовки источника позиции, а не реквизит стороны «Ответчик: ...».
# Иначе обычный блок идентификации помечал бы всю следующую прозу как прямое
# волеизъявление доверителя.
_ROLE_LABEL_RE = re.compile(
    r"(?i)^\s*(?:"
    r"позици\w*\s+(?:ответчик\w*|адресат\w*|получател\w*|доверител\w*)|"
    r"(?:ответчик|адресат\s+претензи\w*|получатель\s+претензи\w*|доверитель)\s+"
    r"(?:сообща\w*|указыва\w*|подтвержда\w*|призна\w*)"
    r")\s*:"
)
_OPPONENT_LABEL_RE = re.compile(
    r"(?i)^\s*(?:позици\w*\s+(?:истц\w*|заявител\w*|кредитор\w*)|"
    r"истец|заявитель|кредитор|взыскатель)\s*:"
)

_STOPWORDS = {
    "факт", "обстоятельство", "ответчик", "адресат", "получатель", "доверитель",
    "признает", "признаёт", "признаем", "признаём", "признан", "признано",
    "оспаривается", "оспариваем", "оспаривает", "согласен", "согласны",
    "заключения", "заключен", "заключён", "между", "сторонами", "имеется",
    "размере", "сумме", "тенге", "теңге", "основной", "части",
}


@dataclass(frozen=True, slots=True)
class _Admission:
    text: str
    amounts: tuple[int, ...]
    keys: tuple[str, ...]
    sensitive: bool


def _sentences(text: str) -> list[str]:
    return [item.strip() for item in _SENTENCE_RE.split(str(text or "")) if item.strip()]


def _key(word: str) -> str:
    value = word.lower().replace("ё", "е")
    if value.isdigit() or len(value) < 4 or value in _STOPWORDS:
        return ""
    return value if any(ch.isdigit() for ch in value) else value[:7]


def _keys(text: str) -> tuple[str, ...]:
    result: list[str] = []
    for word in _WORD_RE.findall(text):
        value = _key(word)
        if value and value not in result:
            result.append(value)
    return tuple(result)


def _requisites(text: str) -> tuple[str, ...]:
    """Точные номера и даты, которые нельзя сравнивать как общую лексику."""
    result: list[str] = []
    for match in _IDENTIFIER_RE.finditer(text or ""):
        value = "номер:" + match.group("value").lower()
        if value not in result:
            result.append(value)
    for match in _DATE_RE.finditer(text or ""):
        value = (
            f"дата:{int(match.group('day')):02d}."
            f"{int(match.group('month')):02d}.{match.group('year')}"
        )
        if value not in result:
            result.append(value)
    return tuple(result)


def _admission(text: str) -> _Admission:
    return _Admission(
        text=str(text or "").strip(),
        amounts=tuple(parse_all_amounts_kzt(text)),
        keys=_keys(text),
        sensitive=bool(_SENSITIVE_RE.search(text) or parse_all_amounts_kzt(text)),
    )


def _affirmative_material_sentences(case_context: str) -> list[str]:
    """Прямые признания отвечающей стороны, но не утверждения оппонента."""
    result: list[str] = []
    current_role = ""
    for sentence in _sentences(case_context):
        # В одной строке могут находиться два самостоятельных предложения:
        # «...не сообщал. Позиция ответчика: признаём...». Ищем явную метку не
        # только в начале чанка, но сохраняем лишь текст после самой метки.
        if match := _ROLE_LABEL_RE.search(sentence):
            current_role = "client"
            sentence = sentence[match.end() :].strip()
        elif match := _OPPONENT_LABEL_RE.match(sentence):
            current_role = "opponent"
            sentence = sentence[match.end() :].strip()
        elif re.match(r"(?i)^\s*(?:истец|заявитель|кредитор)\s+(?:утвержда\w*|счита\w*)", sentence):
            current_role = "opponent"
        if current_role == "opponent":
            continue
        if current_role == "client" and _ADMISSION_RE.search(sentence):
            result.append(sentence)
    return result


def _supported_sensitive(item: _Admission, case_context: str) -> bool:
    for sentence in _affirmative_material_sentences(case_context):
        support_amounts = set(parse_all_amounts_kzt(sentence))
        if item.amounts and not set(item.amounts) <= support_amounts:
            continue
        common = set(item.keys) & set(_keys(sentence))
        # Сумма + предмет либо два предметных ключа: одной общей леммы
        # «долг» недостаточно, если сторона признала другой компонент.
        required = 1 if item.amounts else 2
        if len(common) >= required:
            return True
    return False


def _supported_neutral(item: _Admission, case_context: str) -> bool:
    context_keys = set(_keys(case_context))
    context_amounts = set(parse_all_amounts_kzt(case_context))
    if item.amounts and not set(item.amounts) <= context_amounts:
        return False
    # Все содержательные реквизиты нейтрального факта должны существовать во
    # входе: неизвестный № 99 не пройдёт за счёт общих слов «договор поставки».
    if not set(_requisites(item.text)) <= set(_requisites(case_context)):
        return False
    return bool(item.keys) and set(item.keys) <= context_keys


def unsupported_admissions(
    admissions: list[str] | None,
    case_context: str,
    model_authored_materials: list[str] | None = None,
) -> list[str]:
    """Признания без прямой опоры во входящих материалах.

    ``model_authored_materials`` намеренно не участвует в подтверждении. Аргумент
    оставлен явным, чтобы вызывающий код не мог случайно смешать внешний контекст
    с другими разделами того же черновика и считать повтор признания доказательством.
    """
    del model_authored_materials
    findings: list[str] = []
    for raw in admissions or []:
        item = _admission(raw)
        if not item.text:
            continue
        supported = (
            _supported_sensitive(item, case_context)
            if item.sensitive
            else _supported_neutral(item, case_context)
        )
        if supported:
            continue
        findings.append(
            "признание не подтверждено прямой позицией доверителя во входящих материалах: "
            + item.text[:220]
        )
    return findings
