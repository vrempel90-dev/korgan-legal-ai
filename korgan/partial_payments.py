"""Обнаружение частичных оплат в материалах дела.

Неустойка после частичной оплаты начисляется на остаток, а не на первоначальный
долг. Расчёт одной формулой этого не различает: он берёт сумму долга и умножает
на все дни периода, поэтому платёж середины периода в него не попадает вовсе, а
требование выходит завышенным. Заметить это по тексту иска нельзя — там стоит
правдоподобное число.

Модуль отвечает на два разных вопроса, и второй важнее первого:

* удалось ли извлечь платежи как пары «дата — сумма»;
* упоминается ли частичная оплата вообще.

Упоминание без разбора — не пустой результат, а запрет считать: раз оплата была,
а её размер или дату установить не удалось, любое посчитанное число заведомо
неверно. Разбор намеренно узкий: берутся только предложения с прямым указанием
на погашение части долга, где ровно одна сумма и ровно одна дата. Догадка здесь
занижала бы или завышала требование клиента, и обе ошибки одинаково незаметны.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime

from korgan.penalty_engine import PrincipalEvent

_MONTHS = {
    "января": 1,
    "февраля": 2,
    "марта": 3,
    "апреля": 4,
    "мая": 5,
    "июня": 6,
    "июля": 7,
    "августа": 8,
    "сентября": 9,
    "октября": 10,
    "ноября": 11,
    "декабря": 12,
}

_DATE_TOKEN = (
    r"(?:\d{1,2}[./-]\d{1,2}[./-]\d{4}|"
    r"\d{1,2}\s+(?:января|февраля|марта|апреля|мая|июня|июля|августа|"
    r"сентября|октября|ноября|декабря)\s+\d{4}(?:\s+года)?)"
)
_DATE_RE = re.compile(_DATE_TOKEN, re.IGNORECASE)

_AMOUNT_RE = re.compile(
    r"(?<!\d)(?P<amount>\d[\d\s ]*(?:[.,]\d{1,2})?)\s*(?:тенге|теңге|тг\b|₸|kzt)",
    re.IGNORECASE,
)

# Прямое указание на погашение части долга. Общие слова об оплате сюда не
# входят: «обязался оплатить» и «оплата не произведена» — это не платёж.
_PARTIAL_RE = re.compile(
    r"частичн\w*|в\s+счет\s+(?:погашени|оплат)\w*|в\s+счёт\s+(?:погашени|оплат)\w*|"
    r"част[ьи]\s+(?:долга|задолженност\w*|суммы)|"
    r"ішінара|қарызды[нң]\s+бір\s+бөлігі\w*",
    re.IGNORECASE,
)

_PAID_RE = re.compile(
    r"оплат\w*|оплач\w*|уплат\w*|уплач\w*|погас\w*|погаш\w*|перечисл\w*|"
    r"внес\w*|внёс|вернул\w*|төле\w*|өтед\w*|аудар\w*",
    re.IGNORECASE,
)

# Отрицание рядом с платежом: «частично не оплачено», «оплата не поступила».
_NEGATION_RE = re.compile(r"\bне\s|\bне[а-я]*оплач|төлемеді|жоқ\b", re.IGNORECASE)

# Точка между цифрами — часть даты, а не конец предложения: иначе «11.03.2026»
# разрывается на три обрывка, и платёж теряет либо дату, либо сумму.
_SENTENCE_SPLIT_RE = re.compile(r"(?<!\d)\.(?!\d)|[;\n]")


@dataclass(frozen=True, slots=True)
class PartialPaymentScan:
    """Что удалось и что не удалось установить о частичных оплатах."""

    #: Частичная оплата упоминается в материалах дела.
    mentioned: bool = False
    #: Уверенно разобранные платежи, готовые для расчёта по интервалам.
    payments: tuple[PrincipalEvent, ...] = ()
    #: Фрагменты, где оплата названа, но пару «дата — сумма» извлечь не удалось.
    unparsed: tuple[str, ...] = ()

    @property
    def blocks_single_interval_calculation(self) -> bool:
        """Можно ли считать неустойку одной формулой на весь период.

        Нельзя, как только частичная оплата упомянута: либо платежи разобраны и
        период надо делить, либо не разобраны и считать нечего.
        """
        return self.mentioned


def _parse_date(raw: str) -> date | None:
    text = (raw or "").strip().lower().replace(" года", "")
    for fmt in ("%d.%m.%Y", "%d/%m/%Y", "%d-%m-%Y"):
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            pass
    match = re.fullmatch(r"(\d{1,2})\s+([а-яё]+)\s+(\d{4})", text)
    if not match:
        return None
    month = _MONTHS.get(match.group(2))
    if not month:
        return None
    try:
        return date(int(match.group(3)), month, int(match.group(1)))
    except ValueError:
        return None


def _parse_amount(raw: str) -> int | None:
    text = (raw or "").replace(" ", "").replace(" ", "").replace(",", ".")
    try:
        value = float(text)
    except ValueError:
        return None
    return int(value) if value > 0 else None


def find_partial_payments(text: str) -> PartialPaymentScan:
    """Найти частичные оплаты в описании дела."""
    source = text or ""
    if not _PARTIAL_RE.search(source):
        return PartialPaymentScan()

    payments: list[PrincipalEvent] = []
    unparsed: list[str] = []

    for chunk in _SENTENCE_SPLIT_RE.split(source):
        sentence = (chunk or "").strip()
        if not _PARTIAL_RE.search(sentence) or not _PAID_RE.search(sentence):
            continue
        if _NEGATION_RE.search(sentence):
            # «частично не оплачено» — это не платёж, но и не повод молчать:
            # формулировка двусмысленная, и решать её должен юрист.
            unparsed.append(sentence)
            continue

        amounts = [
            value
            for value in (_parse_amount(m.group("amount")) for m in _AMOUNT_RE.finditer(sentence))
            if value
        ]
        dates = [
            value
            for value in (_parse_date(m.group(0)) for m in _DATE_RE.finditer(sentence))
            if value
        ]
        if len(amounts) == 1 and len(dates) == 1:
            payments.append(
                PrincipalEvent(dates[0], -amounts[0], basis=sentence, kind="payment")
            )
        else:
            unparsed.append(sentence)

    return PartialPaymentScan(
        mentioned=True, payments=tuple(payments), unparsed=tuple(unparsed)
    )
