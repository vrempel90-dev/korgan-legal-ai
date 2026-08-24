"""Monetary calculations for KORGAN documents — Python only, never the model.

Every rate here is set by law and changes on a schedule the code cannot know,
so rates, MRP and the NB RK base rate live in ``korgan/data/rates.json`` with
the date they were current on. Code reads that file; changing a rate is editing
data, not shipping a release.

Each result carries the rate it used, its source and whether that source has
been verified, so a document can state the basis of a number instead of
presenting it as self-evident. A rate with no entry for the requested date is
not approximated — the calculation returns nothing and the caller flags it.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date
from decimal import ROUND_HALF_UP, Decimal
from functools import lru_cache
from pathlib import Path

RATES_PATH = Path(__file__).resolve().parent.parent / "data" / "rates.json"

# Compatibility names used by existing call sites/tests. Their legal semantics
# are deliberately stricter than before: consumer claims are deferred under GPK
# Article 106(3), not exempt; pensioner status alone is not a general Article 668
# exemption. Article 668 currently exempts persons with disability generally.
EXEMPTION_CONSUMER = "consumer_protection"
EXEMPTION_DISABILITY = "disability_group_1_2"
EXEMPTION_PENSIONER = "old_age_pensioner"

FULL_EXEMPTIONS = frozenset({EXEMPTION_DISABILITY})
DEFERRALS = frozenset({EXEMPTION_CONSUMER})

EXEMPTION_LABELS = {
    EXEMPTION_CONSUMER: "гражданин по иску о защите прав потребителей",
    EXEMPTION_DISABILITY: "лицо с инвалидностью",
    EXEMPTION_PENSIONER: "пенсионер по возрасту",
}


class RateUnavailable(LookupError):
    """No rate is configured for the requested date."""


@dataclass(frozen=True, slots=True)
class DatedRate:
    effective_from: date
    value: float
    source: str
    verified: bool


@dataclass(frozen=True, slots=True)
class Rates:
    actual_on: date
    mrp: tuple[DatedRate, ...]
    nb_base_rate: tuple[DatedRate, ...]
    duty_individual_rate: float
    duty_legal_entity_rate: float
    duty_individual_cap_mrp: int
    duty_legal_entity_cap_mrp: int
    duty_nonproperty_mrp: float
    duty_source: str
    duty_verified: bool
    consumer_penalty_rate_per_day: float
    consumer_penalty_source: str
    consumer_penalty_verified: bool
    days_in_year: int

    @property
    def duty_cap_mrp(self) -> int:
        """Deprecated compatibility alias for the physical-person cap."""
        return self.duty_individual_cap_mrp

    def _on(self, table: tuple[DatedRate, ...], day: date, what: str) -> DatedRate:
        current: DatedRate | None = None
        for entry in table:
            if day >= entry.effective_from:
                current = entry
        if current is None:
            raise RateUnavailable(f"{what} на {day.isoformat()} не задан в {RATES_PATH.name}")
        return current

    def mrp_on(self, day: date) -> DatedRate:
        return self._on(self.mrp, day, "МРП")

    def base_rate_on(self, day: date) -> DatedRate:
        return self._on(self.nb_base_rate, day, "базовая ставка НБ РК")


def _parse_table(raw: list[dict]) -> tuple[DatedRate, ...]:
    entries = [
        DatedRate(
            effective_from=date.fromisoformat(item["from"]),
            value=float(item["value"]),
            source=str(item.get("source", "")),
            verified=bool(item.get("verified", False)),
        )
        for item in raw
    ]
    return tuple(sorted(entries, key=lambda entry: entry.effective_from))


@lru_cache(maxsize=4)
def load_rates(path: Path | str = RATES_PATH) -> Rates:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    duty = payload["state_duty"]
    penalty = payload["consumer_penalty"]
    return Rates(
        actual_on=date.fromisoformat(payload["actual_on"]),
        mrp=_parse_table(payload["mrp"]),
        nb_base_rate=_parse_table(payload["nb_base_rate"]),
        duty_individual_rate=float(duty["individual_rate"]),
        duty_legal_entity_rate=float(duty["legal_entity_rate"]),
        duty_individual_cap_mrp=int(duty["individual_cap_mrp"]),
        duty_legal_entity_cap_mrp=int(duty["legal_entity_cap_mrp"]),
        duty_nonproperty_mrp=float(duty["nonproperty_mrp"]),
        duty_source=str(duty.get("source", "")),
        duty_verified=bool(duty.get("verified", False)),
        consumer_penalty_rate_per_day=float(penalty["rate_per_day"]),
        consumer_penalty_source=str(penalty.get("source", "")),
        consumer_penalty_verified=bool(penalty.get("verified", False)),
        days_in_year=int(payload.get("days_in_year", 365)),
    )


def _round_tenge(value: Decimal) -> int:
    """Half-up, the way a person checking the arithmetic would round."""
    return int(value.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


# --- цена иска ---------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ClaimComponent:
    title: str
    amount: int
    pecuniary: bool = True


@dataclass(frozen=True, slots=True)
class ClaimPrice:
    total: int
    included: tuple[ClaimComponent, ...]
    excluded: tuple[ClaimComponent, ...]

    def breakdown(self) -> str:
        parts = [f"{item.title} — {format_kzt(item.amount)}" for item in self.included]
        return "; ".join(parts) + f". Итого цена иска: {format_kzt(self.total)}"


def claim_price(components: list[ClaimComponent]) -> ClaimPrice:
    """Sum only components that legally enter the property-claim price."""
    included = tuple(item for item in components if item.pecuniary)
    excluded = tuple(item for item in components if not item.pecuniary)
    for item in included:
        if item.amount < 0:
            raise ValueError(f"отрицательная сумма требования: {item.title}")
    return ClaimPrice(total=sum(item.amount for item in included), included=included, excluded=excluded)


# --- госпошлина --------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class DutyResult:
    amount: int
    rate: float
    cap: int
    exempt: bool
    deferred: bool
    exemptions: tuple[str, ...]
    deferrals: tuple[str, ...]
    source: str
    verified: bool

    @property
    def payable_now(self) -> int:
        return 0 if self.exempt or self.deferred else self.amount

    def explain(self) -> str:
        if self.exempt:
            reasons = ", ".join(EXEMPTION_LABELS.get(item, item) for item in self.exemptions)
            return f"Истец освобождён от уплаты государственной пошлины ({reasons}); {self.source}"
        if self.deferred:
            reasons = ", ".join(EXEMPTION_LABELS.get(item, item) for item in self.deferrals)
            return (
                f"Государственная пошлина рассчитана в размере {format_kzt(self.amount)}, "
                f"но её уплата отсрочена до принятия решения ({reasons}; статья 106 ГПК РК); {self.source}"
            )
        return f"{format_kzt(self.amount)} ({self.rate:.0%} от цены иска, {self.source})"


def state_duty(
    price: int,
    *,
    is_individual: bool = True,
    exemptions: list[str] | tuple[str, ...] = (),
    rates: Rates | None = None,
    day: date | None = None,
) -> DutyResult:
    """Court duty for an ordinary monetary property claim.

    This helper intentionally does not guess a special procedural category.
    Consumer status is represented as a deferral, not a zero-rate exemption.
    Pensioner status alone does not suppress the duty.
    """
    if price < 0:
        raise ValueError("цена иска не может быть отрицательной")

    config = rates or load_rates()
    applicable_exemptions = tuple(item for item in exemptions if item in FULL_EXEMPTIONS)
    applicable_deferrals = tuple(item for item in exemptions if item in DEFERRALS)
    rate = config.duty_individual_rate if is_individual else config.duty_legal_entity_rate
    cap_mrp = config.duty_individual_cap_mrp if is_individual else config.duty_legal_entity_cap_mrp
    cap = _round_tenge(Decimal(cap_mrp) * Decimal(str(config.mrp_on(day or date.today()).value)))
    amount = min(_round_tenge(Decimal(price) * Decimal(str(rate))), cap)

    if applicable_exemptions:
        return DutyResult(
            amount=0,
            rate=rate,
            cap=cap,
            exempt=True,
            deferred=False,
            exemptions=applicable_exemptions,
            deferrals=(),
            source=config.duty_source,
            verified=config.duty_verified,
        )

    return DutyResult(
        amount=amount,
        rate=rate,
        cap=cap,
        exempt=False,
        deferred=bool(applicable_deferrals),
        exemptions=(),
        deferrals=applicable_deferrals,
        source=config.duty_source,
        verified=config.duty_verified,
    )


def nonproperty_state_duty(*, demands: int = 1, rates: Rates | None = None, day: date | None = None) -> int:
    """Calculate the 0.5 MRP component for separately chargeable non-property demands."""
    if demands < 0:
        raise ValueError("количество неимущественных требований не может быть отрицательным")
    config = rates or load_rates()
    mrp = config.mrp_on(day or date.today()).value
    return _round_tenge(Decimal(str(mrp)) * Decimal(str(config.duty_nonproperty_mrp)) * Decimal(demands))


# --- неустойка по дням -------------------------------------------------------


@dataclass(frozen=True, slots=True)
class PenaltyResult:
    amount: int
    base: int
    rate_per_day: float
    days: int
    uncapped: int
    capped: bool
    cap: int | None
    source: str
    verified: bool

    def formula(self) -> str:
        line = (
            f"{format_kzt(self.base)} × {self.rate_per_day:.1%} × {self.days} дн. "
            f"= {format_kzt(self.uncapped)}"
        )
        if self.capped:
            line += f"; ограничено ценой заказа — {format_kzt(self.amount)}"
        return line


def daily_penalty(
    base: int,
    days: int,
    *,
    rate_per_day: float | None = None,
    cap: int | None = None,
    rates: Rates | None = None,
) -> PenaltyResult:
    """Contractual/statutory penalty accruing per day of delay."""
    if base <= 0:
        raise ValueError("база для неустойки должна быть положительной")
    if days < 0:
        raise ValueError("число дней просрочки не может быть отрицательным")

    config = rates or load_rates()
    rate = config.consumer_penalty_rate_per_day if rate_per_day is None else rate_per_day
    uncapped = _round_tenge(Decimal(base) * Decimal(str(rate)) * Decimal(days))
    amount = min(uncapped, cap) if cap is not None else uncapped

    return PenaltyResult(
        amount=amount,
        base=base,
        rate_per_day=rate,
        days=days,
        uncapped=uncapped,
        capped=cap is not None and uncapped > cap,
        cap=cap,
        source=config.consumer_penalty_source,
        verified=config.consumer_penalty_verified,
    )


# --- проценты за пользование чужими деньгами ---------------------------------


@dataclass(frozen=True, slots=True)
class InterestResult:
    amount: int
    principal: int
    annual_rate: float
    days: int
    start: date
    end: date
    source: str
    verified: bool

    def formula(self) -> str:
        return (
            f"{format_kzt(self.principal)} × {self.annual_rate:g}% × {self.days} дн. / 365 "
            f"= {format_kzt(self.amount)}"
        )

    def period(self) -> str:
        return f"с {self.start.strftime('%d.%m.%Y')} по {self.end.strftime('%d.%m.%Y')}"


def money_use_interest(
    principal: int,
    start: date,
    end: date,
    *,
    annual_rate: float | None = None,
    rates: Rates | None = None,
) -> InterestResult:
    """Interest for the use of another's money, at the NB RK base rate."""
    if principal <= 0:
        raise ValueError("сумма долга должна быть положительной")
    if end < start:
        raise ValueError("дата окончания периода раньше его начала")

    config = rates or load_rates()
    if annual_rate is None:
        entry = config.base_rate_on(start)
        annual_rate, source, verified = entry.value, entry.source, entry.verified
    else:
        source, verified = "ставка задана вручную", False

    days = (end - start).days + 1
    amount = _round_tenge(
        Decimal(principal) * Decimal(str(annual_rate)) / Decimal(100) * Decimal(days) / Decimal(config.days_in_year)
    )
    return InterestResult(
        amount=amount,
        principal=principal,
        annual_rate=annual_rate,
        days=days,
        start=start,
        end=end,
        source=source,
        verified=verified,
    )


def format_kzt(value: int) -> str:
    return f"{value:,}".replace(",", " ") + " тенге"
