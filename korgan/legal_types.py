from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from korgan.contract_numbering import split_leading_number, strip_leading_number


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
        return "\n".join([
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
        ])


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
    state_duty: str = ""
    late_interest: str = ""


@dataclass(slots=True)
class ArgumentClause:
    text: str
    subclauses: list[str] = field(default_factory=list)
    prose: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        self.text = strip_leading_number(self.text)
        self.subclauses = [cleaned for cleaned in (strip_leading_number(x) for x in self.subclauses) if cleaned]
        self.prose = [cleaned for cleaned in (strip_leading_number(x) for x in self.prose) if cleaned]

    def text_lines(self) -> list[str]:
        return [self.text, *self.subclauses, *self.prose]


def normalize_argument_clauses(raw: Any) -> list[ArgumentClause]:
    clauses: list[ArgumentClause] = []
    for item in raw or []:
        if isinstance(item, ArgumentClause):
            clauses.append(item)
            continue
        if isinstance(item, dict):
            text = str(item.get("text", ""))
            subclauses = [str(x) for x in item.get("subclauses", []) or []]
            prose = [str(x) for x in item.get("prose", []) or []]
        else:
            text, subclauses, prose = str(item), [], []
        depth, _ = split_leading_number(text)
        clause = ArgumentClause(text=text, subclauses=subclauses, prose=prose)
        if not clause.text:
            continue
        if depth >= 3 and clauses:
            clauses[-1].subclauses.append(clause.text)
            clauses[-1].subclauses.extend(clause.subclauses)
            clauses[-1].prose.extend(clause.prose)
            continue
        clauses.append(clause)
    return clauses


@dataclass(slots=True)
class ContractClause:
    text: str
    subclauses: list[str] = field(default_factory=list)


def _normalize_clause(item: Any) -> tuple[int, str, list[str]]:
    if isinstance(item, ContractClause):
        raw_text, raw_subs = item.text, list(item.subclauses)
    elif isinstance(item, dict):
        raw_text = str(item.get("text", ""))
        raw_subs = [str(x) for x in item.get("subclauses", []) or []]
    else:
        raw_text, raw_subs = str(item), []
    depth, text = split_leading_number(raw_text)
    subclauses = [cleaned for cleaned in (strip_leading_number(sub) for sub in raw_subs) if cleaned]
    return depth, text.strip(), subclauses


def normalize_clauses(raw: Any) -> list[ContractClause]:
    clauses: list[ContractClause] = []
    for item in raw or []:
        depth, text, subclauses = _normalize_clause(item)
        if not text:
            continue
        if depth >= 3 and clauses:
            clauses[-1].subclauses.append(text)
            clauses[-1].subclauses.extend(subclauses)
            continue
        clauses.append(ContractClause(text=text, subclauses=subclauses))
    return clauses


@dataclass(slots=True)
class ContractSection:
    heading: str
    clauses: list[ContractClause] = field(default_factory=list)

    def __post_init__(self) -> None:
        self.heading = strip_leading_number(self.heading)
        self.clauses = normalize_clauses(self.clauses)

    def text_lines(self) -> list[str]:
        lines: list[str] = []
        for clause in self.clauses:
            lines.append(clause.text)
            lines.extend(clause.subclauses)
        return lines


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

    def body_lines(self) -> list[str]:
        lines = [self.contract_type, self.title, self.place_and_date, *self.party_a, *self.party_b, *self.preamble]
        for section in self.sections:
            lines.append(section.heading)
            lines.extend(section.text_lines())
        lines.extend(self.requisites_a)
        lines.extend(self.requisites_b)
        return lines

    @classmethod
    def from_payload(cls, *, status: VerificationStatus, source_urls: list[str], payload: dict) -> "ContractDraft":
        sections = [
            ContractSection(heading=str(item.get("heading", "")).strip(), clauses=list(item.get("clauses", []) or []))
            for item in payload.get("sections", []) if isinstance(item, dict)
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


@dataclass(slots=True)
class ResponseDraft:
    status: VerificationStatus
    title: str
    court: str
    case_reference: str
    plaintiff: list[str]
    defendant: list[str]
    introduction: list[str]
    circumstances: list[str]
    objections: list[ArgumentClause]
    legal_basis: list[str]
    requests: list[str]
    attachments: list[str]
    verification_notes: list[str]
    source_urls: list[str]

    def __post_init__(self) -> None:
        self.objections = normalize_argument_clauses(self.objections)

    def body_lines(self) -> list[str]:
        lines = [self.title, self.court, self.case_reference, *self.plaintiff, *self.defendant, *self.introduction, *self.circumstances]
        for objection in self.objections:
            lines.extend(objection.text_lines())
        lines.extend(self.legal_basis)
        lines.extend(self.requests)
        lines.extend(self.attachments)
        return lines

    @classmethod
    def from_payload(cls, *, status: VerificationStatus, source_urls: list[str], payload: dict) -> "ResponseDraft":
        def strings(key: str) -> list[str]:
            return [str(x).strip() for x in payload.get(key, []) or [] if str(x).strip()]
        return cls(
            status=status,
            title=str(payload.get("title", "")).strip(),
            court=str(payload.get("court", "")).strip(),
            case_reference=str(payload.get("case_reference", "")).strip(),
            plaintiff=strings("plaintiff"),
            defendant=strings("defendant"),
            introduction=strings("introduction"),
            circumstances=strings("circumstances"),
            objections=normalize_argument_clauses(payload.get("objections", []) or []),
            legal_basis=strings("legal_basis"),
            requests=strings("requests"),
            attachments=strings("attachments"),
            verification_notes=strings("verification_notes"),
            source_urls=list(source_urls),
        )
