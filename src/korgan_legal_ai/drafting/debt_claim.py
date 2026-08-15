from __future__ import annotations

from pydantic import BaseModel

from korgan_legal_ai.domain.models import (
    CalculationResult,
    DocumentType,
    DraftDocument,
    EvidenceMap,
    FilingMode,
    LockedCase,
    PartyRole,
    ProceduralReport,
    ReadinessStatus,
    VerificationStatus,
)
from korgan_legal_ai.llm.base import LLMProvider
from korgan_legal_ai.prompts.debt_claim import DEBT_CLAIM_SYSTEM


class DraftText(BaseModel):
    text: str


class DebtClaimDrafter:
    def __init__(self, provider: LLMProvider | None = None, model: str | None = None) -> None:
        self.provider = provider
        self.model = model

    def draft(
        self,
        case: LockedCase,
        procedural: ProceduralReport,
        evidence_map: EvidenceMap,
        calculation: CalculationResult,
    ) -> DraftDocument:
        needs = list(dict.fromkeys(procedural.needs_verification))
        if evidence_map.unsupported_fact_ids:
            needs.append("evidence_gaps")
        if calculation.mismatch_with_user_total:
            needs.append("claim_total_mismatch")

        if self.provider is not None and self.model:
            payload = {
                "locked_case": case.model_dump(mode="json"),
                "procedural": procedural.model_dump(mode="json"),
                "evidence_map": evidence_map.model_dump(mode="json"),
                "calculation": calculation.model_dump(mode="json"),
                "instruction": (
                    "Use VERIFIED procedural conclusions and exact citations as supplied. "
                    "Do not introduce any article, amount, date, deadline, court rule, attachment "
                    "or representative power whose status/fact is not explicitly VERIFIED/locked. "
                    "The debt prayer amount must exactly equal calculation.total. If state duty is "
                    "VERIFIED, state it separately as court costs and never add it to the claim price."
                ),
            }
            generated = self.provider.parse(
                model=self.model,
                system=DEBT_CLAIM_SYSTEM,
                user=str(payload),
                schema=DraftText,
            )
            text = generated.text
        else:
            text = self._deterministic_draft(case, calculation, procedural)

        readiness = (
            ReadinessStatus.LAWYER_REVIEW_DRAFT
            if needs
            else ReadinessStatus.READY_FOR_FINAL_HUMAN_REVIEW
        )
        return DraftDocument(
            document_type=DocumentType.CLAIM,
            text=text,
            readiness=readiness,
            needs_verification=needs,
            summary="Сформирован проект иска о взыскании задолженности на основе зафиксированных фактов.",
        )

    @staticmethod
    def _party_block(label: str, party) -> str:
        lines = [f"{label}: {party.name}"]
        if party.iin_bin:
            lines.append(f"БИН/ИИН: {party.iin_bin}")
        if party.address:
            lines.append(f"Адрес: {party.address}")
        return "\n".join(lines)

    @staticmethod
    def _item(procedural: ProceduralReport, name: str):
        return next((item for item in procedural.items if item.name == name), None)

    @staticmethod
    def _deterministic_draft(
        case: LockedCase,
        calculation: CalculationResult,
        procedural: ProceduralReport,
    ) -> str:
        claimant = next(
            (p for p in case.parties if p.role in {PartyRole.CLAIMANT, PartyRole.CREDITOR}),
            case.parties[0],
        )
        defendant = next(
            (p for p in case.parties if p.role in {PartyRole.DEFENDANT, PartyRole.DEBTOR}),
            case.parties[1],
        )
        claimant_block = DebtClaimDrafter._party_block("Истец", claimant)
        defendant_block = DebtClaimDrafter._party_block("Ответчик", defendant)
        facts = "\n".join(f"- {fact.statement}" for fact in case.facts)
        total = f"{calculation.total} {calculation.currency}"

        due_line = ""
        if case.procedure.obligation_due_date is not None:
            due_line = (
                "\nСрок исполнения обязательства: "
                + case.procedure.obligation_due_date.strftime("%d.%m.%Y")
            )

        pretrial = DebtClaimDrafter._item(procedural, "pretrial")
        pretrial_text = pretrial.conclusion if pretrial else "Не проверено."
        if case.procedure.pretrial_demand_sent_date is not None:
            pretrial_text += (
                " Дата направления претензии: "
                + case.procedure.pretrial_demand_sent_date.strftime("%d.%m.%Y")
                + "."
            )

        state_duty = DebtClaimDrafter._item(procedural, "state_duty")
        court_costs_section = ""
        if state_duty is not None and state_duty.status == VerificationStatus.VERIFIED:
            court_costs_section = f"\n\nСУДЕБНЫЕ РАСХОДЫ\n{state_duty.conclusion}"

        verified_citations = [
            citation
            for item in procedural.items
            for citation in item.sources
            if citation.status == VerificationStatus.VERIFIED
        ]
        unique_citations: list = []
        seen: set[tuple[str | None, str | None, str | None]] = set()
        for citation in verified_citations:
            key = (citation.law_name, citation.article, citation.source_url)
            if key in seen:
                continue
            seen.add(key)
            unique_citations.append(citation)
        citation_lines = "\n".join(
            f"- {citation.law_name or citation.source_title}, статья {citation.article}: "
            f"{citation.source_url}"
            for citation in unique_citations
            if citation.article and citation.source_url
        )
        if not citation_lines:
            citation_lines = "- Точные нормы не добавлены: подтвержденных citations для этого проекта нет."

        attachments = [evidence.title for evidence in case.evidence]
        if case.procedure.filing_mode == FilingMode.PAPER and case.procedure.copies_prepared is True:
            attachments.append("Копии иска и приложений по числу ответчиков и третьих лиц")
        attachment_lines = "\n".join(
            f"{index}. {title}" for index, title in enumerate(dict.fromkeys(attachments), start=1)
        ) or "1. Перечень фактически предоставленных приложений отсутствует."

        return f"""В ______________________________ суд

{claimant_block}

{defendant_block}

ИСК
о взыскании задолженности

ЦЕНА ИСКА: {total}

ОБСТОЯТЕЛЬСТВА ДЕЛА
{facts}{due_line}

СВЕДЕНИЯ О ДОСУДЕБНОМ ПОРЯДКЕ
{pretrial_text}

РАСЧЕТ ТРЕБОВАНИЙ
Основной долг: {calculation.principal} {calculation.currency}
Неустойка: {calculation.penalty} {calculation.currency}
Проценты: {calculation.interest} {calculation.currency}
Иные суммы: {calculation.other} {calculation.currency}
Итого: {total}{court_costs_section}

ПРАВОВОЕ ОБОСНОВАНИЕ
Требования основываются на обязательстве и доказательствах, изложенных выше. В настоящий
проект включаются только точные нормы, прошедшие проверку по canonical-корпусу и официальному
источнику.
{citation_lines}

ПРОШУ СУД:
1. Взыскать с {defendant.name} в пользу {claimant.name} задолженность в размере {total}.
2. Взыскать судебные расходы в подтвержденном размере в соответствии с применимым законодательством.

ПРИЛОЖЕНИЯ:
{attachment_lines}
"""
