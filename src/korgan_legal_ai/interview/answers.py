from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date
from decimal import Decimal, InvalidOperation

from korgan_legal_ai.blueprints.interview import UNKNOWN, FieldKind, InterviewField

# "I do not know" and "there is none" are different answers and must stay different. An unknown
# value becomes an explicit NEEDS_VERIFICATION item; an explicit "none" is a determined fact and
# must never be reported as unverified.
_UNKNOWN_TOKENS = {
    "не знаю",
    "незнаю",
    "не знаю точно",
    "неизвестно",
    "не известно",
    "нет данных",
    "не помню",
    "?",
    "-",
    "—",
    "білмеймін",
    "белгісіз",
    "деректер жоқ",
}
_NONE_TOKENS = {
    "нет",
    "не было",
    "отсутствует",
    "отсутствуют",
    "ничего",
    "0",
    "нету",
    "жоқ",
    "болған жоқ",
}
_YES_TOKENS = {"да", "yes", "иә", "ия", "+"}
_NO_TOKENS = {"нет", "no", "жоқ", "-"}

_RU_MONTHS = {
    "января": 1, "февраля": 2, "марта": 3, "апреля": 4, "мая": 5, "июня": 6,
    "июля": 7, "августа": 8, "сентября": 9, "октября": 10, "ноября": 11, "декабря": 12,
}
_DATE_TOKEN = re.compile(r"\b(\d{1,2}[./]\d{1,2}[./]\d{4}|\d{4}-\d{2}-\d{2})\b")
_RU_DATE = re.compile(r"\b(\d{1,2})\s+([а-яё]+)\s+(\d{4})\b", re.IGNORECASE)
_BIN_RE = re.compile(r"^\d{12}$")


@dataclass(frozen=True)
class ParsedAnswer:
    """Result of validating one dialogue answer.

    ``unknown`` records that the user explicitly does not know the value, which is a legitimate
    answer that flows through to NEEDS_VERIFICATION. ``error`` means the answer could not be
    understood at all and the question must be asked again — the system never guesses what the user
    meant by an unparseable amount or date.
    """

    value: object | None = None
    unknown: bool = False
    error: str = ""

    @property
    def ok(self) -> bool:
        return not self.error


def _normalize(raw: str) -> str:
    return " ".join(raw.replace(" ", " ").strip().lower().split())


def parse_date(raw: str) -> date | None:
    match = _DATE_TOKEN.search(raw)
    if match:
        token = match.group(1)
        parts = re.split(r"[./-]", token)
        try:
            if len(parts[0]) == 4:
                return date(int(parts[0]), int(parts[1]), int(parts[2]))
            return date(int(parts[2]), int(parts[1]), int(parts[0]))
        except ValueError:
            return None
    ru = _RU_DATE.search(raw)
    if ru:
        month = _RU_MONTHS.get(ru.group(2).lower())
        if month is not None:
            try:
                return date(int(ru.group(3)), month, int(ru.group(1)))
            except ValueError:
                return None
    return None


def parse_money(raw: str) -> Decimal | None:
    cleaned = re.sub(r"[^\d,.\-]", "", raw.replace(" ", ""))
    if not cleaned:
        return None
    # A comma is a decimal separator in Kazakhstan practice; thousands are written with spaces,
    # which the substitution above has already removed.
    cleaned = cleaned.replace(",", ".")
    if cleaned.count(".") > 1:
        head, _, tail = cleaned.rpartition(".")
        cleaned = head.replace(".", "") + "." + tail
    try:
        value = Decimal(cleaned)
    except InvalidOperation:
        return None
    return value if value >= 0 else None


def parse_payments(raw: str) -> list[tuple[Decimal, date | None]] | None:
    entries: list[tuple[Decimal, date | None]] = []
    for chunk in re.split(r"[;\n]+", raw):
        chunk = chunk.strip()
        if not chunk:
            continue
        paid_on = parse_date(chunk)
        without_date = _DATE_TOKEN.sub(" ", chunk)
        without_date = _RU_DATE.sub(" ", without_date)
        amount = parse_money(without_date)
        if amount is None or amount <= 0:
            return None
        entries.append((amount, paid_on))
    return entries or None


def parse_answer(field: InterviewField, raw: str) -> ParsedAnswer:
    """Validate one answer against its field definition."""
    text = raw.strip()
    if not text:
        return ParsedAnswer(error="Пустой ответ. Напишите значение или «не знаю».")

    normalized = _normalize(text)
    if normalized in _UNKNOWN_TOKENS:
        if not field.unknown_ok:
            return ParsedAnswer(
                error=(
                    "Без этого ответа документ составить нельзя — система не подставляет "
                    "предположения. Укажите значение."
                )
            )
        return ParsedAnswer(value=UNKNOWN, unknown=True)

    if field.kind == FieldKind.CHOICE:
        for choice in field.choices:
            if normalized in {
                choice.value,
                choice.label_ru.lower(),
                choice.label_kk.lower(),
            }:
                return ParsedAnswer(value=choice.value)
        if any(choice.value == "yes" for choice in field.choices):
            if normalized in _YES_TOKENS:
                return ParsedAnswer(value="yes")
            if normalized in _NO_TOKENS:
                return ParsedAnswer(value="no")
        options = ", ".join(choice.label_ru for choice in field.choices)
        return ParsedAnswer(error=f"Выберите один из вариантов: {options}.")

    if field.kind in {FieldKind.MONEY, FieldKind.PERCENT, FieldKind.INTEGER}:
        if normalized in _NONE_TOKENS:
            return ParsedAnswer(value=None)
        value = parse_money(text)
        if value is None:
            return ParsedAnswer(
                error="Не удалось прочитать число. Напишите только цифры, например 3600000."
            )
        if field.kind == FieldKind.INTEGER and value != value.to_integral_value():
            return ParsedAnswer(error="Укажите целое число дней.")
        return ParsedAnswer(value=str(value))

    if field.kind == FieldKind.MONEY_LIST:
        if normalized in _NONE_TOKENS:
            return ParsedAnswer(value=[])
        parsed = parse_payments(text)
        if parsed is None:
            return ParsedAnswer(
                error=(
                    "Не удалось прочитать оплаты. Формат: 1200000 от 15.03.2026; "
                    "600000 от 02.05.2026. Если оплат не было — «нет»."
                )
            )
        return ParsedAnswer(
            value=[
                {"amount": str(amount), "paid_on": paid_on.isoformat() if paid_on else None}
                for amount, paid_on in parsed
            ]
        )

    if field.kind == FieldKind.DATE:
        parsed = parse_date(text)
        if parsed is None:
            return ParsedAnswer(
                error="Не удалось прочитать дату. Формат: ДД.ММ.ГГГГ, например 03.06.2026."
            )
        return ParsedAnswer(value=parsed.isoformat())

    if field.kind == FieldKind.IDENTIFIER:
        if normalized in _NONE_TOKENS:
            return ParsedAnswer(value=None)
        digits = re.sub(r"\D", "", text)
        if not _BIN_RE.match(digits):
            return ParsedAnswer(
                error="БИН/ИИН состоит из 12 цифр. Проверьте значение или напишите «не знаю»."
            )
        return ParsedAnswer(value=digits)

    if field.kind == FieldKind.TEXT and len(text) > 300:
        return ParsedAnswer(error="Слишком длинный ответ для этого поля. Сократите до 300 символов.")
    if len(text) > 4000:
        return ParsedAnswer(error="Слишком длинный ответ. Сократите до 4000 символов.")
    return ParsedAnswer(value=text)
