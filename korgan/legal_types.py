from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum


class VerificationStatus(StrEnum):
    VERIFIED = "VERIFIED"
    NEEDS_VERIFICATION = "NEEDS_VERIFICATION"


@dataclass(slots=True)
class ExtractedDocument:
    filename: str
    document_type: str = ""
    text_summary: str = ""
    parties: list[str] = field(default_factory=list)
    identifiers: list[str] = field(default_factory=list)
    addresses: list[str] = field(default_factory=list)
    contacts: list[str] = field(default_factory=list)
    dates: list[str] = field(default_factory=list)
    amounts: list[str] = field(default_factory=list)
    obligations: list[str] = field(default_factory=list)
    violations: list[str] = field(default_factory=list)
    evidence: list[str] = field(default_factory=list)
    important_facts: list[str] = field(default_factory=list)
    missing_or_unclear: list[str] = field(default_factory=list)

    def as_context(self) -> str:
        def line(label: str, values: list[str]) -> str:
            return f"{label}: {'; '.join(values) if values else 'не установлено'}"

        return "\n".join(
            [
                f"Файл: {self.filename}",
                f"Тип: {self.document_type or 'не установлен'}",
                f"Кратко: {self.text_summary or 'нет'}",
                line("Стороны", self.parties),
                line("Идентификаторы", self.identifiers),
                line("Адреса", self.addresses),
                line("Контакты", self.contacts),
                line("Даты", self.dates),
                line("Суммы", self.amounts),
                line("Обязательства", self.obligations),
                line("Возможные нарушения по фактам документа", self.violations),
                line("Доказательства", self.evidence),
                line("Важные факты", self.important_facts),
                line("Неясно/отсутствует", self.missing_or_unclear),
            ]
        )


@dataclass(slots=True)
class LegalResearch:
    status: VerificationStatus
    applicable_law: list[str]
    procedural_requirements: list[str]
    verified_claims: list[str]
    unverified_claims: list[str]
    source_urls: list[str]
    notes: list[str]


@dataclass(slots=True)
class ClaimDraft:
    status: VerificationStatus
    title: str
    court: str
    claimant: list[str]
    defendant: list[str]
    price_of_claim: str
    facts: list[str]
    legal_basis: list[str]
    requests: list[str]
    attachments: list[str]
    verification_notes: list[str]
    source_urls: list[str]
    # Filled deterministically by korgan.legal_calc, never by the model.
    state_duty: str = ""


@dataclass(slots=True)
class ContractSection:
    heading: str
    clauses: list[str] = field(default_factory=list)


@dataclass(slots=True)
class ContractDraft:
    status: VerificationStatus
    contract_type: str
    title: str
    place_and_date: str
    party_a: list[str]
    party_b: list[str]
    preamble: list[str]
    sections: list[ContractSection]
    requisites_a: list[str]
    requisites_b: list[str]
    verification_notes: list[str]
    source_urls: list[str]

    @classmethod
    def from_payload(
        cls,
        *,
        status: VerificationStatus,
        source_urls: list[str],
        payload: dict,
    ) -> "ContractDraft":
        sections = [
            ContractSection(
                heading=str(item.get("heading", "")).strip(),
                clauses=[str(x).strip() for x in item.get("clauses", []) if str(x).strip()],
            )
            for item in payload.get("sections", [])
            if isinstance(item, dict)
        ]
        return cls(
            status=status,
            contract_type=str(payload.get("contract_type", "")).strip(),
            title=str(payload.get("title", "")).strip(),
            place_and_date=str(payload.get("place_and_date", "")).strip(),
            party_a=[str(x).strip() for x in payload.get("party_a", []) if str(x).strip()],
            party_b=[str(x).strip() for x in payload.get("party_b", []) if str(x).strip()],
            preamble=[str(x).strip() for x in payload.get("preamble", []) if str(x).strip()],
            sections=sections,
            requisites_a=[str(x).strip() for x in payload.get("requisites_a", []) if str(x).strip()],
            requisites_b=[str(x).strip() for x in payload.get("requisites_b", []) if str(x).strip()],
            verification_notes=[str(x).strip() for x in payload.get("verification_notes", []) if str(x).strip()],
            source_urls=list(source_urls),
        )
