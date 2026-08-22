"""Requirement checklists: what a claim of a given type must decide about.

Lawful demands were being dropped — a consumer claim would ask for the debt and
silently omit the ЗПП penalty, the duty exemption or the claimant-favourable
venue. The cause is that nothing forced a decision: an omitted demand and a
deliberately waived one looked identical.

So a checklist is not advice, it is a set of questions the pipeline must answer.
Each item gets an explicit decision — claimed, or not claimed with a reason.
An item left without a decision raises: silence is the failure mode this exists
to catch, and treating it as "probably not applicable" would reintroduce it.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Any


class DisputeType(StrEnum):
    CONSUMER_CONTRACTOR = "consumer_contractor"
    SUPPLY = "supply"
    SERVICES = "services"
    DEBT_RECOVERY = "debt_recovery"


DISPUTE_TITLES: dict[DisputeType, str] = {
    DisputeType.CONSUMER_CONTRACTOR: "потребительский подряд",
    DisputeType.SUPPLY: "поставка",
    DisputeType.SERVICES: "оказание услуг",
    DisputeType.DEBT_RECOVERY: "взыскание задолженности",
}


class Decision(StrEnum):
    CLAIMED = "claimed"
    NOT_CLAIMED = "not_claimed"


@dataclass(frozen=True, slots=True)
class ChecklistItem:
    key: str
    title: str
    hint: str


@dataclass(frozen=True, slots=True)
class ItemDecision:
    key: str
    decision: Decision
    reason: str = ""

    @property
    def claimed(self) -> bool:
        return self.decision is Decision.CLAIMED


class ChecklistIncomplete(RuntimeError):
    """An item was left without a decision, or refused without a reason."""


_PRINCIPAL = ChecklistItem(
    key="principal_debt",
    title="основной долг",
    hint="сумма, фактически переданная или недоплаченная по договору",
)
_MONEY_INTEREST = ChecklistItem(
    key="money_use_interest",
    title="проценты за пользование чужими деньгами",
    hint="начисляются на денежное обязательство за период просрочки",
)
_SECURING = ChecklistItem(
    key="claim_securing",
    title="обеспечение иска",
    hint="ходатайство о наложении ареста на имущество или счета ответчика",
)
_LEGAL_COSTS = ChecklistItem(
    key="legal_costs",
    title="судебные расходы",
    hint="госпошлина и иные подтверждённые расходы по делу",
)

CHECKLISTS: dict[DisputeType, tuple[ChecklistItem, ...]] = {
    DisputeType.CONSUMER_CONTRACTOR: (
        _PRINCIPAL,
        ChecklistItem(
            key="consumer_penalty",
            title="неустойка по Закону «О защите прав потребителей»",
            hint="за каждый день просрочки, с ограничением ценой заказа",
        ),
        _MONEY_INTEREST,
        ChecklistItem(
            key="moral_damages",
            title="моральный вред",
            hint="неимущественное требование, в цену иска не входит",
        ),
        _SECURING,
        ChecklistItem(
            key="duty_exemption",
            title="освобождение от государственной пошлины",
            hint="истец по иску о защите прав потребителей пошлину не платит",
        ),
        ChecklistItem(
            key="claimant_venue",
            title="альтернативная подсудность в пользу истца",
            hint="иск потребителя может подаваться по месту жительства истца",
        ),
        _LEGAL_COSTS,
    ),
    DisputeType.SUPPLY: (
        _PRINCIPAL,
        ChecklistItem(
            key="contract_penalty",
            title="договорная неустойка",
            hint="только если её размер согласован в договоре поставки",
        ),
        _MONEY_INTEREST,
        ChecklistItem(
            key="losses",
            title="убытки",
            hint="подтверждённые расходы сверх неустойки",
        ),
        ChecklistItem(
            key="pretrial_order",
            title="досудебный порядок",
            hint="соблюдён ли претензионный порядок, если он обязателен по договору",
        ),
        _SECURING,
        _LEGAL_COSTS,
    ),
    DisputeType.SERVICES: (
        _PRINCIPAL,
        ChecklistItem(
            key="contract_penalty",
            title="договорная неустойка",
            hint="только если она предусмотрена договором оказания услуг",
        ),
        _MONEY_INTEREST,
        ChecklistItem(
            key="acceptance_evidence",
            title="доказательства приёмки услуг",
            hint="акт или переписка, подтверждающая принятие результата",
        ),
        _SECURING,
        _LEGAL_COSTS,
    ),
    DisputeType.DEBT_RECOVERY: (
        _PRINCIPAL,
        _MONEY_INTEREST,
        ChecklistItem(
            key="contract_penalty",
            title="договорная неустойка",
            hint="только если она согласована сторонами",
        ),
        ChecklistItem(
            key="limitation_period",
            title="исковая давность",
            hint="не истёк ли срок и с какого момента он течёт",
        ),
        _SECURING,
        _LEGAL_COSTS,
    ),
}


def items_for(dispute_type: DisputeType) -> tuple[ChecklistItem, ...]:
    return CHECKLISTS[DisputeType(dispute_type)]


def checklist_schema(dispute_type: DisputeType) -> dict[str, Any]:
    """JSON Schema forcing a decision on every item of this dispute type."""
    keys = [item.key for item in items_for(dispute_type)]
    return {
        "type": "object",
        "properties": {
            "decisions": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "key": {"type": "string", "enum": keys},
                        "decision": {"type": "string", "enum": [Decision.CLAIMED, Decision.NOT_CLAIMED]},
                        "reason": {"type": "string"},
                    },
                    "required": ["key", "decision", "reason"],
                    "additionalProperties": False,
                },
            }
        },
        "required": ["decisions"],
        "additionalProperties": False,
    }


def checklist_prompt(dispute_type: DisputeType) -> str:
    lines = [
        f"Тип спора: {DISPUTE_TITLES[DisputeType(dispute_type)]}. "
        "По каждому пункту верни решение: claimed (заявлено) либо not_claimed с причиной."
    ]
    lines.extend(f"- {item.key}: {item.title} — {item.hint}" for item in items_for(dispute_type))
    return "\n".join(lines)


def parse_decisions(raw: list[dict[str, Any]]) -> list[ItemDecision]:
    decisions: list[ItemDecision] = []
    for entry in raw:
        key = str(entry.get("key", "")).strip()
        value = str(entry.get("decision", "")).strip()
        if not key or value not in tuple(Decision):
            continue
        decisions.append(
            ItemDecision(key=key, decision=Decision(value), reason=str(entry.get("reason", "")).strip())
        )
    return decisions


def validate_decisions(
    dispute_type: DisputeType,
    decisions: list[ItemDecision],
) -> dict[str, ItemDecision]:
    """Every item decided, every refusal explained — otherwise the pipeline fails.

    Raising is the point: a demand omitted without a reason is exactly the
    defect this checklist exists to surface, and a lenient default would hide it
    again.
    """
    expected = {item.key: item for item in items_for(dispute_type)}
    by_key = {decision.key: decision for decision in decisions}

    unknown = sorted(set(by_key) - set(expected))
    if unknown:
        raise ChecklistIncomplete(
            f"решения по неизвестным пунктам чек-листа: {', '.join(unknown)}"
        )

    missing = [expected[key].title for key in expected if key not in by_key]
    if missing:
        raise ChecklistIncomplete(
            f"пропущены без решения: {', '.join(missing)}"
        )

    unexplained = [
        expected[decision.key].title
        for decision in by_key.values()
        if decision.decision is Decision.NOT_CLAIMED and not decision.reason
    ]
    if unexplained:
        raise ChecklistIncomplete(
            f"отказ от требования без причины: {', '.join(unexplained)}"
        )

    return by_key


def waived_notes(dispute_type: DisputeType, decisions: dict[str, ItemDecision]) -> list[str]:
    """Lines for the verification block: which lawful demands were not raised, and why."""
    expected = {item.key: item for item in items_for(dispute_type)}
    return [
        f"Не заявлено — {expected[key].title}: {decision.reason}"
        for key, decision in decisions.items()
        if decision.decision is Decision.NOT_CLAIMED
    ]
