from __future__ import annotations

import re
from datetime import date
from decimal import Decimal, InvalidOperation

from pydantic import BaseModel, Field

from korgan_legal_ai.domain.exceptions import ClarificationRequired
from korgan_legal_ai.domain.models import (
    Evidence,
    EvidenceKind,
    Fact,
    FilingMode,
    Financials,
    LockedCase,
    Party,
    PartyRole,
    ProcedureFacts,
    RepresentativeKind,
)
from korgan_legal_ai.llm.base import LLMProvider
from korgan_legal_ai.prompts.fact_lock import FACT_LOCK_SYSTEM


class FactLockExtraction(BaseModel):
    """Strict domain-shaped extraction after deterministic normalization."""

    parties: list[Party]
    facts: list[Fact]
    evidence: list[Evidence] = Field(default_factory=list)
    financials: Financials = Field(default_factory=Financials)
    procedure: ProcedureFacts = Field(default_factory=ProcedureFacts)
    ambiguities: list[str] = Field(default_factory=list)


class FactLockWireParty(BaseModel):
    name: str
    role: str
    iin_bin: str | None = None
    address: str | None = None


class FactLockWireFact(BaseModel):
    id: str = ""
    statement: str
    event_date: str | None = None


class FactLockWireEvidence(BaseModel):
    title: str
    description: str | None = None
    kind: str = "other"
    supports_fact_ids: list[str] = Field(default_factory=list)


class FactLockWireFinancials(BaseModel):
    """Primitive LLM boundary: no Decimal values are parsed by the SDK."""

    contract_amount: str | None = None
    payments: list[str] = Field(default_factory=list)
    principal: str | None = None
    penalty: str | None = None
    interest: str | None = None
    other: str | None = None
    user_stated_total: str | None = None
    currency: str = "KZT"
    penalty_rate_percent_per_day: str | None = None
    penalty_cap_percent_of_principal: str | None = None


class FactLockWireProcedureFacts(BaseModel):
    """Primitive LLM boundary: dates and enums remain strings until local validation."""

    obligation_due_date: str | None = None
    pretrial_required_by_contract: bool | None = None
    pretrial_demand_sent_date: str | None = None
    representative_kind: str | None = None
    representative_name: str | None = None
    representative_can_sign_claim: bool | None = None
    filing_mode: str | None = None
    third_party_count: int = 0
    copies_prepared: bool | None = None


class FactLockWireExtraction(BaseModel):
    """Structured-output transport schema intentionally limited to primitive JSON types."""

    parties: list[FactLockWireParty]
    facts: list[FactLockWireFact]
    evidence: list[FactLockWireEvidence] = Field(default_factory=list)
    financials: FactLockWireFinancials = Field(default_factory=FactLockWireFinancials)
    procedure: FactLockWireProcedureFacts = Field(default_factory=FactLockWireProcedureFacts)
    ambiguities: list[str] = Field(default_factory=list)


_MONTHS: dict[str, int] = {
    "январь": 1,
    "января": 1,
    "қаңтар": 1,
    "февраль": 2,
    "февраля": 2,
    "ақпан": 2,
    "март": 3,
    "марта": 3,
    "наурыз": 3,
    "апрель": 4,
    "апреля": 4,
    "сәуір": 4,
    "май": 5,
    "мая": 5,
    "мамыр": 5,
    "июнь": 6,
    "июня": 6,
    "маусым": 6,
    "июль": 7,
    "июля": 7,
    "шілде": 7,
    "август": 8,
    "августа": 8,
    "тамыз": 8,
    "сентябрь": 9,
    "сентября": 9,
    "қыркүйек": 9,
    "октябрь": 10,
    "октября": 10,
    "қазан": 10,
    "ноябрь": 11,
    "ноября": 11,
    "қараша": 11,
    "декабрь": 12,
    "декабря": 12,
    "желтоқсан": 12,
}
_DATE_WORD_RE = re.compile(
    r"^(?P<day>\d{1,2})\s+(?P<month>[а-яёәғқңөұүһі]+)\s+(?P<year>\d{4})"
    r"(?:\s*(?:г\.?|года|ж\.?|жыл(?:ы)?))?$",
    re.IGNORECASE,
)
_DATE_NUMERIC_RE = re.compile(
    r"^(?P<day>\d{1,2})[./](?P<month>\d{1,2})[./](?P<year>\d{4})$"
)
_DECIMAL_RE = re.compile(r"^[+-]?\d+(?:\.\d+)?$")


def _normalize_date(value: str | None, *, field_name: str, ambiguities: list[str]) -> date | None:
    if value is None or not value.strip():
        return None
    text = value.strip()
    try:
        return date.fromisoformat(text)
    except ValueError:
        pass

    numeric = _DATE_NUMERIC_RE.fullmatch(text)
    if numeric:
        try:
            return date(
                int(numeric.group("year")),
                int(numeric.group("month")),
                int(numeric.group("day")),
            )
        except ValueError:
            pass

    words = _DATE_WORD_RE.fullmatch(text.lower())
    if words:
        month = _MONTHS.get(words.group("month"))
        if month is not None:
            try:
                return date(int(words.group("year")), month, int(words.group("day")))
            except ValueError:
                pass

    ambiguities.append(f"Уточните дату для поля {field_name}: значение не удалось однозначно распознать.")
    return None


def _normalize_decimal(
    value: str | None, *, field_name: str, ambiguities: list[str]
) -> Decimal | None:
    if value is None or not value.strip():
        return None
    normalized = value.strip().lower()
    normalized = normalized.replace("\u00a0", "").replace("\u202f", "").replace(" ", "")
    normalized = normalized.replace("−", "-").replace("₸", "")
    normalized = re.sub(r"(kzt|тенге|тг)$", "", normalized, flags=re.IGNORECASE).strip()
    if "," in normalized and "." in normalized:
        ambiguities.append(f"Уточните денежное значение для поля {field_name}: неоднозначные разделители.")
        return None
    if "," in normalized:
        normalized = normalized.replace(",", ".")
    if not _DECIMAL_RE.fullmatch(normalized):
        ambiguities.append(f"Уточните денежное значение для поля {field_name}: значение не распознано.")
        return None
    try:
        return Decimal(normalized)
    except InvalidOperation:
        ambiguities.append(f"Уточните денежное значение для поля {field_name}: значение не распознано.")
        return None


def _enum_value(enum_type, value: str | None, *, field_name: str, ambiguities: list[str], default=None):
    if value is None or not value.strip():
        return default
    try:
        return enum_type(value.strip())
    except ValueError:
        ambiguities.append(f"Уточните значение поля {field_name}: получено неподдерживаемое значение.")
        return default


def _normalize_extraction(wire: FactLockWireExtraction) -> FactLockExtraction:
    ambiguities = list(wire.ambiguities)

    parties = [
        Party(
            name=item.name,
            role=_enum_value(
                PartyRole,
                item.role,
                field_name=f"роль стороны {item.name}",
                ambiguities=ambiguities,
                default=PartyRole.OTHER,
            ),
            iin_bin=item.iin_bin,
            address=item.address,
        )
        for item in wire.parties
    ]

    facts: list[Fact] = []
    seen_fact_ids: set[str] = set()
    for index, item in enumerate(wire.facts, start=1):
        fact_id = item.id.strip() or f"f{index}"
        if fact_id in seen_fact_ids:
            ambiguities.append("Не удалось надежно связать факты: обнаружены повторяющиеся идентификаторы.")
            continue
        seen_fact_ids.add(fact_id)
        facts.append(
            Fact(
                id=fact_id,
                statement=item.statement,
                event_date=_normalize_date(
                    item.event_date,
                    field_name=f"дата факта {fact_id}",
                    ambiguities=ambiguities,
                ),
            )
        )

    evidence: list[Evidence] = []
    for item in wire.evidence:
        unknown_ids = set(item.supports_fact_ids) - seen_fact_ids
        if unknown_ids:
            ambiguities.append("Не удалось надежно связать доказательство с фактом; требуется уточнение.")
            continue
        evidence.append(
            Evidence(
                title=item.title,
                description=item.description,
                kind=_enum_value(
                    EvidenceKind,
                    item.kind,
                    field_name=f"тип доказательства {item.title}",
                    ambiguities=ambiguities,
                    default=EvidenceKind.OTHER,
                ),
                supports_fact_ids=item.supports_fact_ids,
            )
        )

    money = wire.financials
    payments: list[Decimal] = []
    for index, payment in enumerate(money.payments, start=1):
        parsed = _normalize_decimal(payment, field_name=f"payments[{index}]", ambiguities=ambiguities)
        if parsed is not None:
            payments.append(parsed)

    financials = Financials(
        contract_amount=_normalize_decimal(money.contract_amount, field_name="contract_amount", ambiguities=ambiguities),
        payments=payments,
        principal=_normalize_decimal(money.principal, field_name="principal", ambiguities=ambiguities),
        penalty=_normalize_decimal(money.penalty, field_name="penalty", ambiguities=ambiguities),
        interest=_normalize_decimal(money.interest, field_name="interest", ambiguities=ambiguities),
        other=_normalize_decimal(money.other, field_name="other", ambiguities=ambiguities),
        user_stated_total=_normalize_decimal(
            money.user_stated_total, field_name="user_stated_total", ambiguities=ambiguities
        ),
        currency=money.currency,
        penalty_rate_percent_per_day=_normalize_decimal(
            money.penalty_rate_percent_per_day,
            field_name="penalty_rate_percent_per_day",
            ambiguities=ambiguities,
        ),
        penalty_cap_percent_of_principal=_normalize_decimal(
            money.penalty_cap_percent_of_principal,
            field_name="penalty_cap_percent_of_principal",
            ambiguities=ambiguities,
        ),
    )

    procedure_wire = wire.procedure
    procedure = ProcedureFacts(
        obligation_due_date=_normalize_date(
            procedure_wire.obligation_due_date,
            field_name="obligation_due_date",
            ambiguities=ambiguities,
        ),
        pretrial_required_by_contract=procedure_wire.pretrial_required_by_contract,
        pretrial_demand_sent_date=_normalize_date(
            procedure_wire.pretrial_demand_sent_date,
            field_name="pretrial_demand_sent_date",
            ambiguities=ambiguities,
        ),
        representative_kind=_enum_value(
            RepresentativeKind,
            procedure_wire.representative_kind,
            field_name="representative_kind",
            ambiguities=ambiguities,
        ),
        representative_name=procedure_wire.representative_name,
        representative_can_sign_claim=procedure_wire.representative_can_sign_claim,
        filing_mode=_enum_value(
            FilingMode,
            procedure_wire.filing_mode,
            field_name="filing_mode",
            ambiguities=ambiguities,
        ),
        third_party_count=procedure_wire.third_party_count,
        copies_prepared=procedure_wire.copies_prepared,
    )

    return FactLockExtraction(
        parties=parties,
        facts=facts,
        evidence=evidence,
        financials=financials,
        procedure=procedure,
        ambiguities=ambiguities,
    )


class FactLockService:
    def __init__(self, provider: LLMProvider, model: str) -> None:
        self.provider = provider
        self.model = model

    def lock(self, raw_text: str) -> LockedCase:
        wire = self.provider.parse(
            model=self.model,
            system=FACT_LOCK_SYSTEM,
            user=raw_text,
            schema=FactLockWireExtraction,
        )
        extracted = _normalize_extraction(wire)
        if extracted.ambiguities:
            raise ClarificationRequired(extracted.ambiguities)
        return LockedCase(raw_text=raw_text, **extracted.model_dump())
