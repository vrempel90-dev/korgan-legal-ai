"""Deterministic legal arithmetic for KORGAN.

Anything computable from a rate fixed in law belongs here, not in a model
prompt. The model may not invent, round or "remember" these numbers.

Rate source: статья 665 Налогового кодекса РК (Кодекс РК от 18.07.2025
№ 214-VIII, adilet id K2500000214), действует с 01.01.2026 — ставка по искам
имущественного характера: 1% от суммы иска для физических лиц, 3% для
юридических лиц, но не более 10 000 МРП.

МРП source: Закон РК от 08.12.2025 № 239-VIII «О республиканском бюджете на
2026 - 2028 годы» (adilet id Z2500000239) — 4 325 тенге с 01.01.2026.

Both constants are year-bound and must be re-verified against the official
source when the budget law for the next year enters into force.
"""

from __future__ import annotations

import re

RATE_SOURCE_ARTICLE = "статья 665 Налогового кодекса РК (Кодекс РК № 214-VIII)"
RATE_SOURCE_URL = "https://adilet.zan.kz/rus/docs/K2500000214"
MRP_SOURCE_URL = "https://adilet.zan.kz/rus/docs/Z2500000239"

MRP_2026 = 4325
RATE_INDIVIDUAL = 0.01
RATE_LEGAL_ENTITY = 0.03
CAP_MRP = 10_000

NEEDS_CALCULATION_MARKER = "[ТРЕБУЕТ РАСЧЁТА ГОСПОШЛИНЫ]"

_LEGAL_ENTITY_MARKERS = (
    "бин",
    "тоо",
    "товарищество с ограниченной ответственностью",
    "ао ",
    "акционерное общество",
    "юридическое лицо",
    "юридического лица",
    "индивидуальный предприниматель",
    " ип ",
)

# «2 400 000 тенге», «2400000 тг», «2 400 000 (два миллиона...) тенге».
_AMOUNT_PATTERN = re.compile(
    r"(\d[\d\s ]*(?:[.,]\d{1,2})?)\s*(?:\([^)]*\)\s*)?(?:тенге|тг\b|kzt)",
    re.IGNORECASE,
)


def calc_gosposhlina_claim(amount: int, is_individual: bool) -> int:
    """State duty for a monetary claim, in tenge.

    ``round`` is Python's banker's rounding, which matters only for a claim
    price ending in exactly half a tiyn — acceptable for a duty stated in
    whole tenge.
    """
    if amount < 0:
        raise ValueError("Сумма иска не может быть отрицательной")
    rate = RATE_INDIVIDUAL if is_individual else RATE_LEGAL_ENTITY
    cap = CAP_MRP * MRP_2026
    return min(round(amount * rate), cap)


def parse_amount_kzt(text: str) -> int | None:
    """Extract a tenge amount from free text; None when it is not unambiguous."""
    if not text:
        return None
    match = _AMOUNT_PATTERN.search(text)
    if not match:
        return None
    digits = re.sub(r"[\s ]", "", match.group(1)).replace(",", ".")
    try:
        value = float(digits)
    except ValueError:
        return None
    if value <= 0:
        return None
    return int(value)


def format_kzt(value: int) -> str:
    """Render 24000 as «24 000 тенге»."""
    return f"{value:,}".replace(",", " ") + " тенге"


def claimant_is_individual(case_context: str) -> bool | None:
    """Decide the duty rate from the case materials, fail-closed.

    Returns None when anything in the materials points at a legal entity: the
    1% / 3% choice then depends on facts the code cannot establish, so the duty
    must not be computed at all.
    """
    if not case_context:
        return None
    lowered = f" {case_context.lower()} "
    if any(marker in lowered for marker in _LEGAL_ENTITY_MARKERS):
        return None
    if "иин" not in lowered:
        return None
    return True


def gosposhlina_line(case_context: str, price_of_claim: str) -> str:
    """Court-ready state duty line, or the explicit «needs calculation» marker.

    Never guesses: if either the claim price or the payer type cannot be
    established deterministically, the marker is returned instead of a number.
    """
    amount = parse_amount_kzt(price_of_claim)
    if amount is None:
        return NEEDS_CALCULATION_MARKER

    is_individual = claimant_is_individual(case_context)
    if is_individual is None:
        return NEEDS_CALCULATION_MARKER

    duty = calc_gosposhlina_claim(amount, is_individual)
    percent = "1%" if is_individual else "3%"
    return f"{format_kzt(duty)} ({percent} от цены иска, {RATE_SOURCE_ARTICLE})"
