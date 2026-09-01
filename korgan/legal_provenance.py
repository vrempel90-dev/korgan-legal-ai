"""Внутреннее происхождение фактов и fail-closed проверка реквизитов.

Источник утверждения хранится отдельно от его текста. Это не служебная метка
для DOCX, а граница полномочий: факт из пользователя/документа можно повторить,
расчёт можно вывести детерминированно, право — только верифицировать, а
``MISSING_FACT`` не имеет значения и никогда не заполняется догадкой.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import StrEnum

from korgan.legal_calc import parse_all_amounts_kzt


class FactOrigin(StrEnum):
    FACT_FROM_USER = "FACT_FROM_USER"
    FACT_FROM_DOCUMENT = "FACT_FROM_DOCUMENT"
    DERIVED_CALCULATION = "DERIVED_CALCULATION"
    VERIFIED_LAW = "VERIFIED_LAW"
    LEGAL_ANALYSIS = "LEGAL_ANALYSIS"
    MISSING_FACT = "MISSING_FACT"


@dataclass(frozen=True, slots=True)
class ProvenancedFact:
    value: str
    origin: FactOrigin
    source: str = ""

    def __post_init__(self) -> None:
        value = str(self.value or "").strip()
        source = str(self.source or "").strip()
        if self.origin is FactOrigin.MISSING_FACT and value:
            raise ValueError("MISSING_FACT не может содержать конкретное значение")
        if self.origin is not FactOrigin.MISSING_FACT and not value:
            raise ValueError("Факт с установленным происхождением должен иметь значение")
        object.__setattr__(self, "value", value)
        object.__setattr__(self, "source", source)

    @property
    def usable(self) -> bool:
        return self.origin is not FactOrigin.MISSING_FACT and bool(self.value)


def render_fact(fact: ProvenancedFact, *, missing_marker: str = "") -> str:
    """Вернуть только значение; происхождение никогда не является текстом документа."""
    if not fact.usable:
        return str(missing_marker or "")
    return fact.value


_NAME_LABEL_RE = re.compile(
    r"(?i)\b(?:истец|ответчик|заявитель|адресат|отправитель|получатель|"
    r"покупатель|продавец|заказчик|исполнитель)\s*:\s*"
    r"(?P<value>(?!ТОО\b|АО\b|ИП\b|РГП\b|РГУ\b|КГУ\b|КГП\b|ОО\b)"
    r"[А-ЯЁӘҒҚҢӨҰҮҺІ][а-яёәғқңөұүһі-]+(?:\s+[А-ЯЁӘҒҚҢӨҰҮҺІ][а-яёәғқңөұүһі-]+){1,2})"
)
_ID_RE = re.compile(r"(?i)\b(?:ИИН|БИН)\s*[:№]?\s*(?P<value>\d{12})(?!\d)")
_ADDRESS_RE = re.compile(
    r"(?i)\b(?:адрес\w*|прожива\w*|находи\w*)\s*(?:ответчик\w*|истц\w*)?\s*:\s*"
    r"(?P<value>[^\n]+)"
)
_CONTRACT_NUMBER_RE = re.compile(
    r"(?i)\b(?:договор|контракт|соглашени\w*)[^\n.;]{0,40}?"
    r"(?:№|номер)\s*(?P<value>[A-Za-zА-Яа-я0-9/-]+)"
)
# Дата — это день, а не строка символов. «15.01.2026», «15 января 2026 года»,
# «2026-01-15» и «2026 жылғы 15 қаңтар» называют один и тот же день, и договоры,
# письма и судебные документы пользуются всеми этими формами. Сверка по одной
# только цифровой записи давала ошибку в обе стороны: верно перенесённая из
# договора дата объявлялась выдуманной, а дата словами не проверялась вовсе.
_MONTHS: dict[str, int] = {}
for _index, _names in enumerate(
    (
        ("январ", "қаңтар"),
        ("феврал", "ақпан"),
        ("март", "наурыз"),
        ("апрел", "сәуір", "сеуір"),
        ("мая", "май", "мамыр"),
        ("июн", "маусым"),
        ("июл", "шілде", "шилде"),
        ("август", "тамыз"),
        ("сентябр", "қыркүйек"),
        ("октябр", "қазан"),
        ("ноябр", "қараша"),
        ("декабр", "желтоқсан"),
    ),
    start=1,
):
    for _name in _names:
        _MONTHS[_name] = _index

_MONTH_ALTERNATION = "|".join(
    sorted((re.escape(name) for name in _MONTHS), key=len, reverse=True)
)
_DAY = r"0?[1-9]|[12]\d|3[01]"
_DATE_RE = re.compile(
    # 15.01.2026 / 15-01-2026 / 15/01/2026
    rf"(?<!\d)(?P<day>{_DAY})[./-](?P<month>0?[1-9]|1[0-2])[./-](?P<year>\d{{4}})(?!\d)"
    # 2026-01-15
    rf"|(?<!\d)(?P<iso_year>\d{{4}})-(?P<iso_month>0?[1-9]|1[0-2])-(?P<iso_day>{_DAY})(?!\d)"
    # «15» января 2026 года / 15 қаңтар 2026 жылы
    rf"|(?<!\d)[«\"]?(?P<text_day>{_DAY})[»\"]?\s*(?:-?\s*(?:ші|шы|ы|і))?\s+"
    rf"(?P<text_month>{_MONTH_ALTERNATION})[а-яёәғқңөұүһі]*\s+(?P<text_year>\d{{4}})(?!\d)"
    # 2026 жылғы 15 қаңтар
    rf"|(?<!\d)(?P<kk_year>\d{{4}})\s+жыл\w*\s+[«\"]?(?P<kk_day>{_DAY})[»\"]?\s*"
    rf"(?:-?\s*(?:ші|шы|ы|і))?\s+(?P<kk_month>{_MONTH_ALTERNATION})[а-яёәғқңөұүһі]*",
    re.IGNORECASE,
)
# «акт» перечисляет окончания, а не берёт хвост через \w*, поэтому правая
# граница обязательна: без неё «активы» и «актуальный» давали тот же токен, что
# и настоящий акт, и выдуманный акт выполненных работ проходил шлюз, опираясь на
# постороннее слово во входящих материалах.
_EVIDENCE_RE = re.compile(
    r"(?i)\b(?:акт(?:ами|ах|ов|ом|ы|а|у|е)?\b|накладн\w*|плат[её]жн\w*\s+поручени\w*|"
    r"квитанци\w*|расписк\w*|выписк\w*|чек\w*|переписк\w*|"
    r"экспертн\w*\s+заключени\w*)"
    r"(?:\s+(?:выполненн\w*\s+работ\w*))?"
    r"(?:\s*(?:№|номер)\s*(?P<number>[A-Za-zА-Яа-я0-9/-]+))?"
)
_SENTENCE_RE = re.compile(r"(?<=[.!?;])\s+|\n+")
# «Платёжное поручение» — вид доказательства, его проверяет _EVIDENCE_RE.
# Здесь речь о самом событии платежа.
_PAYMENT_EVENT_RE = re.compile(
    r"(?i)(?<!\w)(?:оплат\w*|уплат\w*|плат[её]ж(?!н\w*\s+поручени)\w*|"
    r"перечисл\w*|погаш\w*|погас\w*|внес(?:ен|ён|л)\w*)"
)
# Утверждение «оплата не произведена» — это заявление о неисполнении, а не
# утверждение о состоявшемся платеже. Смешивать их нельзя: первое — обычное
# основание иска, второе меняет объём долга в пользу оппонента.
_PAYMENT_NEGATIVE_RE = re.compile(
    r"(?i)(?:"
    r"\bне\s+(?:\w+\s+){0,2}?(?:оплат\w*|уплат\w*|перечисл\w*|погаш\w*|погас\w*|"
    r"внес\w*|поступ\w*|возврат\w*|возвращ\w*)|"
    r"(?:оплат\w*|уплат\w*|плат[её]ж\w*|перечислен\w*|погашен\w*)[^.;]{0,60}?"
    r"\bне\s+(?:произв\w*|поступ\w*|осуществ\w*|внес\w*|получен\w*|последовал\w*)|"
    r"(?:оплат\w*|уплат\w*)[^.;]{0,40}?отсутств\w*"
    r")"
)
_PRETRIAL_SEND_RE = re.compile(
    r"(?i)\b(?:претензи\w*|талап\s+хат\w*)[^\n.;]{0,100}?"
    r"(?:направ\w*|отправ\w*|вруч\w*|получ\w*)"
)


def _sentences(text: str) -> list[str]:
    return [item.strip() for item in _SENTENCE_RE.split(str(text or "")) if item.strip()]


def _normalized(value: str) -> str:
    return re.sub(r"[^0-9a-zа-яёәғқңөұүһі]+", "", str(value or "").lower().replace("ё", "е"))


def _contains(materials: str, value: str) -> bool:
    needle = _normalized(value)
    return bool(needle) and needle in _normalized(materials)


def _date_token(match: re.Match[str]) -> str:
    """Свести любую форму записи к одному дню.

    Токен намеренно не хранит исходное написание: сравниваются дни, а не строки.
    """
    groups = match.groupdict()
    for day_key, month_key, year_key in (
        ("day", "month", "year"),
        ("iso_day", "iso_month", "iso_year"),
        ("text_day", "text_month", "text_year"),
        ("kk_day", "kk_month", "kk_year"),
    ):
        day = groups.get(day_key)
        if day is None:
            continue
        raw_month = groups[month_key] or ""
        month = _MONTHS.get(raw_month.lower()) if not raw_month.isdigit() else int(raw_month)
        if month is None:
            continue
        return f"{int(day):02d}.{month:02d}.{groups[year_key]}"
    raise ValueError(f"неизвестная форма даты: {match.group(0)!r}")


def _evidence_token(match: re.Match[str]) -> str:
    label = _normalized(match.group(0))
    number = _normalized(match.groupdict().get("number") or "")
    # Суффикс падежа различается («квитанция» / «квитанцией»), но вид
    # доказательства и его номер должны совпасть.
    stem_match = re.match(
        r"(?:акт|накладн|платежн.*?поручени|квитанц|расписк|выписк|чек|переписк|экспертн.*?заключени)",
        label,
    )
    stem = stem_match.group(0) if stem_match else label
    return stem if not number else f"{stem}:{number}"


def forbidden_fact_findings(statements: list[str] | None, materials: str) -> list[str]:
    """Найти запрещённые реквизиты/факты, которых нет во входящих материалах.

    Это консервативный детектор высокорисковых сущностей, а не общий semantic
    entailment. Детерминированные расчёты и правовой анализ проходят отдельными
    владельцами и сюда не передаются как факты из источника.
    """
    findings: list[str] = []
    source = str(materials or "")
    for raw in statements or []:
        text = str(raw or "").strip()
        if not text:
            continue

        for match in _NAME_LABEL_RE.finditer(text):
            value = match.group("value")
            if not _contains(source, value):
                findings.append(f"ФИО отсутствует во входящих материалах: {value}")
        for match in _ID_RE.finditer(text):
            value = match.group("value")
            if not _contains(source, value):
                findings.append(f"ИИН/БИН отсутствует во входящих материалах: {value}")
        for match in _ADDRESS_RE.finditer(text):
            value = match.group("value")
            if not _contains(source, value):
                findings.append(f"адрес отсутствует во входящих материалах: {value}")
        for match in _CONTRACT_NUMBER_RE.finditer(text):
            value = match.group("value")
            source_numbers = {item.group("value").lower() for item in _CONTRACT_NUMBER_RE.finditer(source)}
            if value.lower() not in source_numbers:
                findings.append(f"номер договора отсутствует во входящих материалах: {value}")
        source_dates = {_date_token(item) for item in _DATE_RE.finditer(source)}
        for match in _DATE_RE.finditer(text):
            value = _date_token(match)
            if value not in source_dates:
                findings.append(f"дата отсутствует во входящих материалах: {value}")

        source_amounts = set(parse_all_amounts_kzt(source))
        for value in parse_all_amounts_kzt(text):
            if value not in source_amounts:
                findings.append(f"сумма отсутствует во входящих материалах: {value:,}".replace(",", " "))

        source_evidence = {_evidence_token(item) for item in _EVIDENCE_RE.finditer(source)}
        for match in _EVIDENCE_RE.finditer(text):
            value = _evidence_token(match)
            if value not in source_evidence:
                findings.append(f"доказательство отсутствует во входящих материалах: {match.group(0)}")

        for sentence in _sentences(text):
            if _PAYMENT_NEGATIVE_RE.search(sentence) or not _PAYMENT_EVENT_RE.search(sentence):
                continue
            sentence_amounts = set(parse_all_amounts_kzt(sentence))
            source_payment = any(
                _PAYMENT_EVENT_RE.search(item) and not _PAYMENT_NEGATIVE_RE.search(item)
                for item in _sentences(source)
            )
            if not source_payment or not sentence_amounts <= source_amounts:
                findings.append("факт оплаты отсутствует во входящих материалах: " + sentence[:180])
        if _PRETRIAL_SEND_RE.search(text):
            statement_dates = {_date_token(item) for item in _DATE_RE.finditer(text)}
            if not _PRETRIAL_SEND_RE.search(source) or not statement_dates <= source_dates:
                findings.append("факт направления претензии отсутствует во входящих материалах: " + text[:180])

    return list(dict.fromkeys(findings))
