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

    @staticmethod
    def _verification_needs(
        procedural: ProceduralReport,
        evidence_map: EvidenceMap,
        calculation: CalculationResult,
    ) -> list[str]:
        needs = list(dict.fromkeys(procedural.needs_verification))
        if evidence_map.unsupported_fact_ids:
            needs.append("evidence_gaps")
        if calculation.mismatch_with_user_total:
            needs.append("claim_total_mismatch")
        if calculation.principal_conflicts_with_payments:
            needs.append("principal_conflicts_with_payments")
        if calculation.other_excluded_as_duplicate:
            needs.append("other_amount_duplicated_debt")
        return list(dict.fromkeys(needs))

    @classmethod
    def _document(
        cls,
        *,
        text: str,
        procedural: ProceduralReport,
        evidence_map: EvidenceMap,
        calculation: CalculationResult,
        summary: str,
    ) -> DraftDocument:
        needs = cls._verification_needs(procedural, evidence_map, calculation)
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
            summary=summary,
        )

    def draft(
        self,
        case: LockedCase,
        procedural: ProceduralReport,
        evidence_map: EvidenceMap,
        calculation: CalculationResult,
    ) -> DraftDocument:
        if self.provider is not None and self.model:
            payload = {
                "locked_case": case.model_dump(mode="json"),
                "procedural": procedural.model_dump(mode="json"),
                "evidence_map": evidence_map.model_dump(mode="json"),
                "calculation": calculation.model_dump(mode="json"),
                "instruction": (
                    "Produce a polished lawyer-review claim. Use VERIFIED procedural conclusions "
                    "and exact citations as supplied. For every NEEDS_VERIFICATION procedural item, "
                    "keep the claim useful but put a visible `NEEDS_VERIFICATION — ...` marker in "
                    "the relevant field or section. Do not introduce any article, amount, date, "
                    "deadline, court rule, attachment or representative power whose status/fact is "
                    "not explicitly VERIFIED/locked. The debt prayer amount must exactly equal "
                    "calculation.total. If state duty is VERIFIED, state it separately as court "
                    "costs and never add it to the claim price."
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

        return self._document(
            text=text,
            procedural=procedural,
            evidence_map=evidence_map,
            calculation=calculation,
            summary="Сформирован проект иска о взыскании задолженности на основе зафиксированных фактов.",
        )

    def safe_fallback(
        self,
        case: LockedCase,
        procedural: ProceduralReport,
        evidence_map: EvidenceMap,
        calculation: CalculationResult,
    ) -> DraftDocument:
        """Build a deterministic fail-closed claim after an LLM draft fails Final Legal QA.

        The fallback deliberately contains visible NEEDS_VERIFICATION markers instead of guessing.
        It is still a lawyer-review draft and must pass the same Final Legal QA before release.
        """
        return self._document(
            text=self._deterministic_draft(case, calculation, procedural),
            procedural=procedural,
            evidence_map=evidence_map,
            calculation=calculation,
            summary=(
                "Сформирован безопасный резервный проект иска после отклонения первоначального "
                "текста Final Legal QA. Неподтвержденные вопросы оставлены как NEEDS_VERIFICATION."
            ),
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
    def _verified_or_need(item, *, verified_prefix: str = "") -> str:
        if item is None:
            return "NEEDS_VERIFICATION — вопрос не был проверен."
        if item.status == VerificationStatus.VERIFIED:
            return f"{verified_prefix}{item.conclusion}"
        return f"NEEDS_VERIFICATION — {item.conclusion}"

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
        # The debt is presented as derived so the contract sum is visibly an input to the balance,
        # never a second claimable position.
        derivation_line = ""
        if calculation.contract_amount is not None:
            derivation_line = (
                f"Стоимость по договору: {calculation.contract_amount} {calculation.currency}\n"
                f"Оплачено: {calculation.payments_total} {calculation.currency}\n"
            )
        # A zero "other" line is not printed at all: the category exists only for amounts that are
        # genuinely outside the debt, and an empty row invites a duplicate to be filled into it.
        other_line = ""
        if calculation.other > 0:
            other_line = f"Иные суммы: {calculation.other} {calculation.currency}\n"
        interest_line = ""
        if calculation.interest > 0:
            interest_line = f"Проценты: {calculation.interest} {calculation.currency}\n"

        jurisdiction = DebtClaimDrafter._item(procedural, "jurisdiction")
        if jurisdiction is not None and jurisdiction.status == VerificationStatus.VERIFIED:
            addressee = (
                "В ______________________________ суд\n"
                f"Подсудность: {jurisdiction.conclusion}"
            )
        else:
            reason = jurisdiction.conclusion if jurisdiction is not None else "определить компетентный суд и территориальную подсудность."
            addressee = f"В: NEEDS_VERIFICATION — {reason}"

        due_line = ""
        if case.procedure.obligation_due_date is not None:
            due_line = (
                "\nСрок исполнения обязательства: "
                + case.procedure.obligation_due_date.strftime("%d.%m.%Y")
            )

        pretrial = DebtClaimDrafter._item(procedural, "pretrial")
        pretrial_text = DebtClaimDrafter._verified_or_need(pretrial)
        if case.procedure.pretrial_demand_sent_date is not None:
            pretrial_text += (
                " Дата направления претензии: "
                + case.procedure.pretrial_demand_sent_date.strftime("%d.%m.%Y")
                + "."
            )

        state_duty = DebtClaimDrafter._item(procedural, "state_duty")
        if state_duty is not None and state_duty.status == VerificationStatus.VERIFIED:
            state_duty_line = f"Государственная пошлина: {state_duty.conclusion}"
        else:
            reason = state_duty.conclusion if state_duty is not None else "определить размер по действующему законодательству Республики Казахстан."
            state_duty_line = f"Государственная пошлина: NEEDS_VERIFICATION — {reason}"

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
            citation_lines = (
                "NEEDS_VERIFICATION — конкретные нормы материального и процессуального права "
                "должны быть определены только после проверки действующей редакции по "
                "верифицированному источнику."
            )

        attachments = [evidence.title for evidence in case.evidence]
        if case.procedure.filing_mode == FilingMode.PAPER and case.procedure.copies_prepared is True:
            attachments.append("Копии иска и приложений по числу ответчиков и третьих лиц")
        attachment_lines_list = [
            f"{index}. {title}" for index, title in enumerate(dict.fromkeys(attachments), start=1)
        ]
        attachments_item = DebtClaimDrafter._item(procedural, "attachments")
        if attachments_item is not None and attachments_item.status != VerificationStatus.VERIFIED:
            attachment_lines_list.append(
                f"{len(attachment_lines_list) + 1}. NEEDS_VERIFICATION — {attachments_item.conclusion}"
            )
        if not attachment_lines_list:
            attachment_lines_list.append(
                "1. NEEDS_VERIFICATION — перечень фактически предоставленных приложений отсутствует."
            )
        attachment_lines = "\n".join(attachment_lines_list)

        authority = DebtClaimDrafter._item(procedural, "authority")
        authority_line = ""
        if authority is not None and authority.status != VerificationStatus.VERIFIED:
            authority_line = f"\n\nПОДПИСАНТ / ПРЕДСТАВИТЕЛЬ\nNEEDS_VERIFICATION — {authority.conclusion}"

        return f"""{addressee}

{claimant_block}

{defendant_block}

ИСКОВОЕ ЗАЯВЛЕНИЕ
о взыскании задолженности

ЦЕНА ИСКА: {total}
{state_duty_line}

ОБСТОЯТЕЛЬСТВА ДЕЛА
{facts}{due_line}

СВЕДЕНИЯ О ДОСУДЕБНОМ ПОРЯДКЕ
{pretrial_text}

РАСЧЕТ ТРЕБОВАНИЙ
{derivation_line}Основной долг: {calculation.principal} {calculation.currency}
Неустойка: {calculation.penalty} {calculation.currency}
{interest_line}{other_line}Итого: {total}

ПРАВОВОЕ ОБОСНОВАНИЕ
Истец основывает требования на зафиксированных договорных обязательствах, факте их исполнения
со своей стороны и наличии непогашенной задолженности. Точные нормы указываются только при наличии
VERIFIED-источника.
{citation_lines}

ПРОШУ СУД:
1. Взыскать с {defendant.name} в пользу {claimant.name} задолженность в размере {total}.
2. Взыскать судебные расходы в подтвержденном размере в соответствии с применимым законодательством.

ПРИЛОЖЕНИЯ:
{attachment_lines}{authority_line}
"""
