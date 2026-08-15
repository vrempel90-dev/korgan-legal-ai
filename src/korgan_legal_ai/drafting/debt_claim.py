from __future__ import annotations

from pydantic import BaseModel

from korgan_legal_ai.domain.models import (
    CalculationResult,
    DocumentType,
    DraftDocument,
    EvidenceMap,
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
                    "Do not introduce any article/amount/deadline/court rule whose status is not VERIFIED."
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
        facts = "\n".join(f"- {fact.statement}" for fact in case.facts)
        total = f"{calculation.total} {calculation.currency}"
        procedural_lines = "\n".join(
            f"- {item.name}: {item.conclusion} [{item.status}]"
            for item in procedural.items
        )
        verified_citations = [
            citation
            for item in procedural.items
            for citation in item.sources
            if citation.status == VerificationStatus.VERIFIED
        ]
        citation_lines = "\n".join(
            f"- {citation.law_name or citation.source_title}, статья {citation.article}: "
            f"{citation.source_url}"
            for citation in verified_citations
            if citation.article and citation.source_url
        )
        if not citation_lines:
            citation_lines = "- Точные нормы не добавлены: подтвержденных citations для этого проекта нет."

        return f"""В ______________________________ суд

Истец: {claimant.name}
Ответчик: {defendant.name}

ИСКОВОЕ ЗАЯВЛЕНИЕ
о взыскании задолженности

ОБСТОЯТЕЛЬСТВА ДЕЛА
{facts}

РАСЧЕТ ТРЕБОВАНИЙ
Основной долг: {calculation.principal} {calculation.currency}
Неустойка: {calculation.penalty} {calculation.currency}
Проценты: {calculation.interest} {calculation.currency}
Иные суммы: {calculation.other} {calculation.currency}
Итого: {total}

ПРОЦЕССУАЛЬНАЯ ПРОВЕРКА
{procedural_lines}

ПОДТВЕРЖДЕННЫЕ НОРМЫ
{citation_lines}

ПРАВОВОЕ ОБОСНОВАНИЕ
Требования основываются на обязательстве, описанном в зафиксированных фактах дела. В проект
включены только те точные процессуальные нормы и расчеты, которые имеют статус VERIFIED.
Вопросы со статусом NEEDS_VERIFICATION не заменяются предположениями и подлежат проверке
до финальной юридической проверки человеком.

ПРОШУ СУД:
1. Взыскать с {defendant.name} в пользу {claimant.name} сумму требований в размере {total}.
2. Разрешить вопрос о судебных расходах в соответствии с применимым законодательством после
   проверки состава и документального подтверждения расходов.

ПРИЛОЖЕНИЯ:
Перечень приложений формируется по фактически предоставленным доказательствам и после
процессуальной проверки обязательного состава приложений.
"""
