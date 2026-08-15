from __future__ import annotations

from pydantic import BaseModel

from korgan_legal_ai.blueprints.models import DocumentBlueprint
from korgan_legal_ai.domain.models import (
    CalculationResult,
    DraftDocument,
    EvidenceMap,
    LockedCase,
    ProceduralReport,
    ReadinessStatus,
)
from korgan_legal_ai.drafting.context import DraftContext
from korgan_legal_ai.drafting.sections import RENDERERS
from korgan_legal_ai.llm.base import LLMProvider
from korgan_legal_ai.prompts.document import build_system_prompt


class DraftText(BaseModel):
    text: str


class DocumentDrafter:
    """Blueprint-driven drafter shared by every document type.

    The deterministic renderer is the floor: it can always produce a safe, fully attributed draft
    from locked facts alone. An LLM, when configured, produces the polished version of the same
    structure and is still subject to Final Legal QA, which can send the request back to the
    deterministic floor.
    """

    def __init__(
        self,
        blueprint: DocumentBlueprint,
        provider: LLMProvider | None = None,
        model: str | None = None,
    ) -> None:
        self.blueprint = blueprint
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

    def _document(
        self,
        *,
        text: str,
        procedural: ProceduralReport,
        evidence_map: EvidenceMap,
        calculation: CalculationResult,
        summary: str,
    ) -> DraftDocument:
        needs = self._verification_needs(procedural, evidence_map, calculation)
        readiness = (
            ReadinessStatus.LAWYER_REVIEW_DRAFT
            if needs
            else ReadinessStatus.READY_FOR_FINAL_HUMAN_REVIEW
        )
        return DraftDocument(
            document_type=self.blueprint.document_type,
            text=text,
            readiness=readiness,
            needs_verification=needs,
            summary=summary,
        )

    def render(self, context: DraftContext) -> str:
        """Assemble the document from the blueprint's sections.

        A renderer returning ``None`` means the section does not apply to this case at all, so the
        block is dropped rather than printed empty. An empty block is exactly the kind of filler a
        later editor fills with a duplicate figure.
        """
        blocks: list[str] = []
        for section in self.blueprint.sections:
            renderer = RENDERERS.get(section.kind)
            if renderer is None:
                continue
            body = renderer(context)
            if body is None:
                continue
            parts = [part for part in (section.heading, section.intro, body) if part]
            blocks.append("\n".join(parts))
        return "\n\n".join(blocks) + "\n"

    def _context(
        self,
        case: LockedCase,
        procedural: ProceduralReport,
        evidence_map: EvidenceMap,
        calculation: CalculationResult,
    ) -> DraftContext:
        return DraftContext(
            blueprint=self.blueprint,
            case=case,
            procedural=procedural,
            evidence_map=evidence_map,
            calculation=calculation,
        )

    def draft(
        self,
        case: LockedCase,
        procedural: ProceduralReport,
        evidence_map: EvidenceMap,
        calculation: CalculationResult,
    ) -> DraftDocument:
        context = self._context(case, procedural, evidence_map, calculation)
        if self.provider is not None and self.model:
            payload = {
                "locked_case": case.model_dump(mode="json"),
                "procedural": procedural.model_dump(mode="json"),
                "evidence_map": evidence_map.model_dump(mode="json"),
                "calculation": calculation.model_dump(mode="json"),
                "deterministic_reference_draft": self.render(context),
                "instruction": (
                    "Produce a polished lawyer-review document with the same structure, the same "
                    "figures and the same NEEDS_VERIFICATION markers as the deterministic reference "
                    "draft. Improve the prose only. Do not introduce any article, amount, date, "
                    "deadline, court rule, attachment or representative power that the reference "
                    "draft does not already contain."
                ),
            }
            generated = self.provider.parse(
                model=self.model,
                system=build_system_prompt(self.blueprint),
                user=str(payload),
                schema=DraftText,
            )
            text = generated.text
        else:
            text = self.render(context)

        return self._document(
            text=text,
            procedural=procedural,
            evidence_map=evidence_map,
            calculation=calculation,
            summary=self.blueprint.summary,
        )

    def safe_fallback(
        self,
        case: LockedCase,
        procedural: ProceduralReport,
        evidence_map: EvidenceMap,
        calculation: CalculationResult,
    ) -> DraftDocument:
        """Build a deterministic fail-closed document after an LLM draft fails Final Legal QA.

        The fallback deliberately contains visible NEEDS_VERIFICATION markers instead of guessing.
        It is still a lawyer-review draft and must pass the same Final Legal QA before release.
        """
        context = self._context(case, procedural, evidence_map, calculation)
        return self._document(
            text=self.render(context),
            procedural=procedural,
            evidence_map=evidence_map,
            calculation=calculation,
            summary=(
                "Сформирован безопасный резервный проект документа после отклонения первоначального "
                "текста Final Legal QA. Неподтвержденные вопросы оставлены как NEEDS_VERIFICATION."
            ),
        )
