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
