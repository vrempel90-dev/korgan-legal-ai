"""Single source of truth for the price of a claim (цена иска).

The price of a pecuniary claim is the sum of the *structured* monetary demands
of the prayer for relief. It is not the sum of every number that happens to
appear in the rendered legal text: a prayer legitimately contains amounts that
must never be added together — a calculation formula and its own result, a
control total repeated after its parts, a non-pecuniary moral-damage
compensation, the state duty, or an alternative demand pleaded instead of the
main one.

Every request is therefore classified before any arithmetic happens, and only
components classified as pecuniary are summed. When the structured amount
cannot be established with certainty the resolver refuses to produce a number
(:class:`ClaimPriceStatus.AMBIGUOUS`) instead of guessing one, because a guessed
price silently becomes a deterministic-looking state duty downstream.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum

from korgan.legal_calc import parse_all_amounts_kzt
from korgan.legal_types import ClaimDraft

# The claim price never includes the state duty, the recovery of litigation
# costs, or an amount pleaded as an alternative to the main demand.
_STATE_DUTY_RE = re.compile(r"пошлин", re.IGNORECASE)
_COST_RE = re.compile(r"судебн\w*\s+расход|расход\w*\s+по\s+оплат", re.IGNORECASE)
_ALTERNATIVE_RE = re.compile(r"альтернативн", re.IGNORECASE)

# Compensation of moral/non-material harm is a non-pecuniary demand: it is not
# part of the price of a pecuniary claim and its duty is charged separately.
_NON_PECUNIARY_RE = re.compile(
    r"моральн\w*\s+вред|неимущественн\w*\s+вред|нравственн\w*\s+страдан|моральн\w*\s+страдан",
    re.IGNORECASE,
)

# A control total ("итого …") restates the sum of the other demands. It is a
# checksum, never an additional component.
_TOTAL_ASSERTION_RE = re.compile(
    r"\bитого\b|\bвсего\b|\bсовокупно\b|общ\w*\s+(?:сумм\w*|размер\w*)|цен\w*\s+иска",
    re.IGNORECASE,
)


# Wording note: ``production_legal._is_stale_duty_note`` deletes any note that
# mentions "пошлин" together with a marker such as "требует уточнени" once the
# duty has been computed. The notes below are deliberately worded to survive
# that cleanup, because they stay true after a duty number exists.
PRICE_UNRESOLVED_NOTE_PREFIX = "ТРЕБУЕТ УТОЧНЕНИЯ: цена иска не определена автоматически"

MIXED_CLAIM_NOTE = (
    "ВНИМАНИЕ: заявлена компенсация морального вреда — неимущественное требование. "
    "В цену иска оно не входит; государственная пошлина по нему исчисляется отдельно "
    "от пошлины по имущественному требованию."
)


def format_price_note(reason: str) -> str:
    """Explain to the reviewer why the claim price was left unresolved."""
    detail = reason.strip() or "сумма имущественных требований не определена"
    return f"{PRICE_UNRESOLVED_NOTE_PREFIX} — {detail}."


class ComponentRole(Enum):
    """What a single request contributes to the price of the claim."""

    PECUNIARY = "pecuniary"
    TOTAL_ASSERTION = "total_assertion"
    NON_PECUNIARY = "non_pecuniary"
    PROCEDURAL = "procedural"
    NON_MONETARY = "non_monetary"
    UNDETERMINED = "undetermined"


class ClaimPriceStatus(Enum):
    """Whether the price of the claim could be established from the structure."""

    RESOLVED = "resolved"
    AMBIGUOUS = "ambiguous"
    NO_MONETARY_RELIEF = "no_monetary_relief"


@dataclass(frozen=True, slots=True)
class ClaimComponent:
    """One classified demand of the prayer for relief."""

    role: ComponentRole
    amount: int | None
    text: str


@dataclass(frozen=True, slots=True)
class ClaimPrice:
    """Resolution of the claim price from the structured components."""

    status: ClaimPriceStatus
    total: int | None
    components: tuple[ClaimComponent, ...]
    reason: str = ""

    def pecuniary_components(self) -> tuple[ClaimComponent, ...]:
        return tuple(item for item in self.components if item.role is ComponentRole.PECUNIARY)

    def has_non_pecuniary_money(self) -> bool:
        return any(
            item.role is ComponentRole.NON_PECUNIARY and item.amount is not None
            for item in self.components
        )


def classify_request(text: str, amounts: list[int]) -> ComponentRole:
    """Classify one request; ``amounts`` are the currency amounts it contains.

    Order matters. Procedural and non-pecuniary demands are recognised even when
    they carry an amount, because their amounts must be kept out of the price.
    """
    if _STATE_DUTY_RE.search(text) or _COST_RE.search(text) or _ALTERNATIVE_RE.search(text):
        return ComponentRole.PROCEDURAL
    if _NON_PECUNIARY_RE.search(text):
        return ComponentRole.NON_PECUNIARY
    if not amounts:
        return ComponentRole.NON_MONETARY
    if len(amounts) > 1:
        # A formula and its result, a part and a repeated total, a principal
        # restated in a parenthetical — the structure is not decidable here.
        return ComponentRole.UNDETERMINED
    if _TOTAL_ASSERTION_RE.search(text):
        return ComponentRole.TOTAL_ASSERTION
    return ComponentRole.PECUNIARY


def _shorten(text: str, limit: int = 90) -> str:
    compact = " ".join(text.split())
    return compact if len(compact) <= limit else compact[: limit - 1] + "…"


def resolve_claim_price(draft: ClaimDraft) -> ClaimPrice:
    """Resolve the price of the claim from the structured pecuniary demands."""
    components: list[ClaimComponent] = []
    for request in draft.requests:
        text = str(request or "").strip()
        if not text:
            continue
        amounts = parse_all_amounts_kzt(text)
        role = classify_request(text, amounts)
        amount = amounts[0] if len(amounts) == 1 else None
        components.append(ClaimComponent(role=role, amount=amount, text=text))

    frozen = tuple(components)

    undetermined = [item for item in frozen if item.role is ComponentRole.UNDETERMINED]
    if undetermined:
        return ClaimPrice(
            status=ClaimPriceStatus.AMBIGUOUS,
            total=None,
            components=frozen,
            reason=(
                "требование содержит несколько сумм, и структура требования не позволяет "
                f"однозначно определить слагаемое цены иска: «{_shorten(undetermined[0].text)}»"
            ),
        )

    pecuniary = [item for item in frozen if item.role is ComponentRole.PECUNIARY]
    assertions = [item for item in frozen if item.role is ComponentRole.TOTAL_ASSERTION]

    if pecuniary:
        total = sum(item.amount or 0 for item in pecuniary)
        for assertion in assertions:
            if assertion.amount != total:
                return ClaimPrice(
                    status=ClaimPriceStatus.AMBIGUOUS,
                    total=None,
                    components=frozen,
                    reason=(
                        "итоговая сумма в просительной части не совпадает с суммой "
                        f"заявленных имущественных требований: «{_shorten(assertion.text)}»"
                    ),
                )
        return ClaimPrice(ClaimPriceStatus.RESOLVED, total, frozen)

    if assertions:
        values = {item.amount for item in assertions}
        if len(values) == 1:
            return ClaimPrice(ClaimPriceStatus.RESOLVED, values.pop(), frozen)
        return ClaimPrice(
            status=ClaimPriceStatus.AMBIGUOUS,
            total=None,
            components=frozen,
            reason="в просительной части заявлено несколько несовпадающих итоговых сумм",
        )

    if any(item.role is ComponentRole.NON_PECUNIARY and item.amount is not None for item in frozen):
        return ClaimPrice(
            status=ClaimPriceStatus.AMBIGUOUS,
            total=None,
            components=frozen,
            reason=(
                "заявлено только неимущественное денежное требование (компенсация морального "
                "вреда); цена имущественного иска из просительной части не определяется"
            ),
        )

    # Nothing monetary to compute from: the existing price stays untouched, as
    # it did before this resolver existed.
    return ClaimPrice(ClaimPriceStatus.NO_MONETARY_RELIEF, None, frozen)
