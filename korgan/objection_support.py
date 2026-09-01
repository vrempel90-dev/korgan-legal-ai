"""Материальная опора для возражений, которые нельзя заявлять наугад.

Дата и статья, написанные самим отзывом, не делают довод подтверждённым. Для
исковой давности исходные даты должны существовать в материалах дела, правило о
длительности — в source-bound VERIFIED-тексте нормы, а заявленная дата окончания
должна совпадать с детерминированным календарным расчётом.

Остальные процессуальные возражения пока сохраняют прежний fail-closed минимум:
в самом доводе нужна конкретная дата или норма. Это отдельный класс вопросов —
он не должен ослаблять более строгий инвариант исковой давности.
"""

from __future__ import annotations

import re
from datetime import date

from korgan.citation_audit import runtime_provisions

_LIMITATION_RE = re.compile(
    r"(?i)(?:исков\w*\s+давност\w*|срок\w*\s+давност\w*|талап\s+қою\s+мерзім\w*)"
)
_GUARDED_PROCEDURAL_RE = re.compile(
    r"(?i)(?:пропущен\w*\s+срок|"
    r"нарушен\w*\s+(?:процессуальн\w*|порядок\s+подач\w*)|"
    r"подсудност\w*\s+наруш\w*)"
)
_DATE_RE = re.compile(r"(?<!\d)(?P<day>0?[1-9]|[12]\d|3[01])[./-](?P<month>0?[1-9]|1[0-2])[./-](?P<year>\d{4})(?!\d)")
_ARTICLE_RE = re.compile(r"(?i)(?:стать(?:я|и|е|ю|ёй|ей)|ст\.)\s*\d+(?:-\d+)?")
_DURATION_RE = re.compile(
    r"(?i)(?P<value>\d{1,2}|один|два|две|три|четыре|пять|шесть|семь|восемь|девять|десять)"
    r"\s*(?:год|года|лет)\b"
)
_START_RE = re.compile(
    r"(?i)(?:"
    r"(?:течени\w*\s+срок\w*|срок\w*|течени\w*)\s+(?:начал\w*|исчисля\w*)|"
    r"(?:начал\w*|исчисля\w*)\s+(?:течени\w*|срок\w*)"
    r")[^\n.;]{0,100}?(?P<date>\d{1,2}[./-]\d{1,2}[./-]\d{4})"
)
_EXPIRY_RE = re.compile(
    r"(?i)(?:срок\w*(?:\s+исков\w*\s+давност\w*)?[^\n.;]{0,80}?"
    r"(?:ист[её]к\w*|окончил\w*)|истечени\w*\s+срок\w*)"
    r"[^\n.;]{0,80}?(?P<date>\d{1,2}[./-]\d{1,2}[./-]\d{4})"
)

# «три» и «3» приводятся к одному числу. Для сроков исковой давности нужны
# малые целые значения; расширять словарь без отдельного правового сценария нет
# смысла — неизвестная формулировка должна остаться fail-closed.
_DURATION_WORDS = {
    "один": 1,
    "два": 2,
    "две": 2,
    "три": 3,
    "четыре": 4,
    "пять": 5,
    "шесть": 6,
    "семь": 7,
    "восемь": 8,
    "девять": 9,
    "десять": 10,
}


def _parse_date(value: str) -> date | None:
    match = _DATE_RE.search(value or "")
    if not match:
        return None
    try:
        return date(int(match.group("year")), int(match.group("month")), int(match.group("day")))
    except ValueError:
        return None


def _dates(text: str) -> set[date]:
    return {parsed for match in _DATE_RE.finditer(text or "") if (parsed := _parse_date(match.group(0)))}


def _duration_years(text: str) -> set[int]:
    result: set[int] = set()
    for match in _DURATION_RE.finditer(text or ""):
        raw = match.group("value").lower().replace("ё", "е")
        try:
            years = int(raw)
        except ValueError:
            years = _DURATION_WORDS.get(raw, 0)
        if years > 0:
            result.add(years)
    return result


def _verified_limitation_years(verified_claims: list[str] | None) -> set[int]:
    """Сроки только из source-bound норм, а не из model-authored legal_basis."""
    years: set[int] = set()
    for provision in runtime_provisions(verified_claims):
        if _LIMITATION_RE.search(provision.text):
            years.update(_duration_years(provision.text))
    return years


def _same_calendar_day_plus_years(start: date, end: date, years: int) -> bool:
    try:
        return start.replace(year=start.year + years) == end
    except ValueError:
        # 29 февраля + N лет: гражданско-правовой расчёт может требовать
        # специального правила. Не угадываем его — такой довод не проходит
        # автоматический шлюз и остаётся на проверку юриста.
        return False


def _limitation_finding(
    objection: str,
    *,
    case_context: str,
    verified_claims: list[str] | None,
) -> str | None:
    text = str(objection or "")
    material_dates = _dates(case_context)
    objection_dates = _dates(text)
    if not objection_dates and not _ARTICLE_RE.search(text):
        return "возражение заявлено без подтверждающих дат или нормы: " + text[:120]

    unsupported_dates = sorted(objection_dates - material_dates)
    if unsupported_dates:
        rendered = ", ".join(value.strftime("%d.%m.%Y") for value in unsupported_dates)
        return (
            "возражение об исковой давности опирается на даты, которых нет в материалах дела: "
            + rendered
        )

    verified_years = _verified_limitation_years(verified_claims)
    stated_years = _duration_years(text)
    if not verified_years:
        return (
            "для возражения об исковой давности нет source-bound VERIFIED нормы "
            "о применяемом сроке"
        )
    if stated_years and not (stated_years & verified_years):
        return (
            "заявленная длительность срока исковой давности не подтверждена "
            "source-bound VERIFIED нормой"
        )

    start_match = _START_RE.search(text)
    expiry_match = _EXPIRY_RE.search(text)
    if not start_match or not expiry_match:
        return (
            "возражение об исковой давности не называет дату начала и дату окончания срока"
        )
    start = _parse_date(start_match.group("date"))
    expiry = _parse_date(expiry_match.group("date"))
    if start is None or expiry is None:
        return "возражение об исковой давности содержит некорректную календарную дату"
    if start not in material_dates or expiry not in material_dates:
        return "даты возражения об исковой давности не подтверждены материалами дела"

    applicable = stated_years & verified_years if stated_years else verified_years
    if not any(_same_calendar_day_plus_years(start, expiry, years) for years in applicable):
        return (
            "детерминированный расчёт срока исковой давности не совпадает с заявленной датой окончания"
        )
    return None


def unsupported_objections(
    objections: list[str],
    *,
    case_context: str = "",
    verified_claims: list[str] | None = None,
) -> list[str]:
    """Возражения без внешней фактической и правовой опоры."""
    findings: list[str] = []
    for raw in objections or []:
        item = str(raw or "").strip()
        if not item:
            continue
        if _LIMITATION_RE.search(item):
            if not case_context and verified_claims is None:
                # Совместимость чистой low-level проверки: без материалов она
                # по-прежнему отвечает только на вопрос о наличии конкретики.
                if not (_DATE_RE.search(item) or _ARTICLE_RE.search(item)):
                    findings.append(
                        "возражение заявлено без подтверждающих дат или нормы: " + item[:120]
                    )
                continue
            finding = _limitation_finding(
                item,
                case_context=case_context,
                verified_claims=verified_claims,
            )
            if finding:
                findings.append(finding)
            continue
        if _GUARDED_PROCEDURAL_RE.search(item) and not (
            _DATE_RE.search(item) or _ARTICLE_RE.search(item)
        ):
            findings.append(
                "возражение заявлено без подтверждающих дат или нормы: " + item[:120]
            )
    return findings
