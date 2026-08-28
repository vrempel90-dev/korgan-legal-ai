from __future__ import annotations

import json
import logging
from typing import Any

from korgan.contract_repair_state import contract_repair_completed, reset_contract_repair_state
from korgan.document_quality import MIN_READY_SCORE, assess_document_quality
from korgan.fast_v2_production_legal import _deterministic_pre_qa
from korgan.instant_claim_runtime import InstantClaimProductionService
from korgan.late_interest_hotfix import _apply_verified_article_353, _today_kz
from korgan.legal_types import ClaimDraft, ContractDraft, LegalResearch, VerificationStatus
from korgan.openai_legal import _CLAIM_SCHEMA
from korgan.response_legal import _RESPONSE_DRAFT_SCHEMA
from korgan.response_types import ResponseToClaimDraft
from korgan.robust_production_legal import _CONTRACT_SCHEMA
from korgan.pro_claim_sections import pro_payload

LOGGER = logging.getLogger(__name__)


def _quality_note(score: float, issues: list[str]) -> str:
    details = "; ".join(issues[:6]) or "остались вопросы, требующие проверки"
    return (
        f"KORGAN QUALITY: {score:.1f}/10, ниже целевого порога {MIN_READY_SCORE:.1f}/10. "
        f"Документ является предварительным: {details}"
    )


class UniversalQualityProductionService(InstantClaimProductionService):
    """One quality policy for every production Word document.

    The first draft stays on the fast path. A single source-bound repair call is
    added only when deterministic quality assessment is below 8.5/10 or has a
    hard blocker. Repair may use only user facts and already VERIFIED law.
    """

    async def _quality_repair(
        self,
        *,
        schema_name: str,
        schema: dict[str, Any],
        case_context: str,
        research: LegalResearch,
        current_payload: dict[str, Any],
        issues: list[str],
        language: str,
        document_label: str,
        extra_rules: str,
    ) -> dict[str, Any]:
        verified = "\n".join(f"- {item}" for item in research.verified_claims) or "нет подтвержденных выводов"
        prompt = (
            f"Доработай {document_label} KORGAN до внутреннего качества не ниже {MIN_READY_SCORE:.1f}/10. "
            "Исправляй только перечисленные дефекты. Не меняй установленные факты и не добавляй право по памяти.\n\n"
            "УНИВЕРСАЛЬНЫЕ ПРАВИЛА:\n"
            "1. FACT LOCK: суммы, даты, стороны, идентификаторы, события и доказательства только из материалов пользователя.\n"
            "2. ROLE LOCK: не меняй процессуальные и договорные роли сторон. Для юрлица не требуй человеческое ФИО, для физлица не придумывай БИН.\n"
            "3. LAW LOCK: конкретные статьи и юридические выводы только из VERIFIED; соседняя или тематически похожая статья не заменяет норму, поддерживающую требование/позицию.\n"
            "4. Если обязательный факт реально неизвестен, не выдумывай его. Такой пробел должен остаться явным и не маскироваться под готовность.\n"
            "5. Просительная часть/позиция/условия должны логически следовать из фактов и правового основания.\n"
            "6. Не добавляй URL, Markdown, служебные пояснения KORGAN или советы пользователю в тело юридического документа.\n"
            "7. Не добавляй документы, платежи, уведомления, претензии, доверенности или доказательства, которых нет в материалах.\n"
            f"{extra_rules}\n\n"
            f"МАТЕРИАЛЫ:\n{case_context[:self.settings.max_case_text_chars]}\n\n"
            f"VERIFIED:\n{verified}\n\n"
            f"ДЕФЕКТЫ QUALITY GATE:\n{json.dumps(issues, ensure_ascii=False)}\n\n"
            f"ТЕКУЩИЙ ДОКУМЕНТ:\n{json.dumps(current_payload, ensure_ascii=False)}"
        )
        payload, _ = await self._structured_response(
            model=self.settings.openai_model,
            instructions=(
                "Ты старший юридический редактор KORGAN по праву Республики Казахстан. "
                "Цель — исправить проверяемые дефекты без юридической фантазии. "
                f"Язык документа: {'казахский' if language == 'kk' else 'русский'}."
            ),
            content=[{"role": "user", "content": [{"type": "input_text", "text": prompt}]}],
            schema_name=schema_name,
            schema=schema,
        )
        return payload

    async def draft_claim(
        self,
        case_context: str,
        research: LegalResearch,
        language: str = "ru",
    ) -> ClaimDraft:
        draft = await super().draft_claim(case_context, research, language=language)
        first = assess_document_quality("claim", case_context, research, draft)
        LOGGER.info(
            "DOCUMENT_QUALITY kind=claim stage=first score=%.1f ready=%s blockers=%s",
            first.score,
            first.ready,
            first.hard_blockers[:6],
        )
        if first.ready:
            return draft

        current = {
            "title": draft.title,
            "court": draft.court,
            "claimant": draft.claimant,
            "defendant": draft.defendant,
            "price_of_claim": draft.price_of_claim,
            "facts": draft.facts,
            "legal_basis": draft.legal_basis,
            "requests": draft.requests,
            "attachments": draft.attachments,
            "verification_notes": draft.verification_notes,
            **pro_payload(draft),
        }
        payload = await self._quality_repair(
            schema_name="korgan_universal_quality_claim",
            schema=_CLAIM_SCHEMA,
            case_context=case_context,
            research=research,
            current_payload=current,
            issues=first.repair_issues(),
            language=language,
            document_label="исковое заявление",
            extra_rules=(
                "8. Для иска отдельно проверь подсудность, цену иска, госпошлину, правовую квалификацию и связь каждой нормы с каждым требованием. "
                "Конкретный суд и сумму госпошлины не угадывай: детерминированные поля повторно обработает код."
            ),
        )
        repaired = ClaimDraft(status=research.status, source_urls=list(research.source_urls), **payload)
        _deterministic_pre_qa(case_context, research, repaired)
        _apply_verified_article_353(case_context, research, repaired, filing_date=_today_kz())

        second = assess_document_quality("claim", case_context, research, repaired)
        LOGGER.info(
            "DOCUMENT_QUALITY kind=claim stage=repaired score=%.1f ready=%s blockers=%s",
            second.score,
            second.ready,
            second.hard_blockers[:6],
        )
        if not second.ready:
            repaired.status = VerificationStatus.NEEDS_VERIFICATION
            note = _quality_note(second.score, second.repair_issues())
            if note not in repaired.verification_notes:
                repaired.verification_notes.append(note)
        return repaired

    async def draft_contract(
        self,
        case_context: str,
        research: LegalResearch,
        language: str = "ru",
    ) -> ContractDraft:
        """Run at most one contract repair while preserving every quality gate."""
        reset_contract_repair_state()
        draft = await super().draft_contract(case_context, research, language=language)
        lower_repaired = contract_repair_completed()
        first = assess_document_quality("contract", case_context, research, draft)
        LOGGER.info(
            "DOCUMENT_QUALITY kind=contract stage=first score=%.1f ready=%s blockers=%s lower_repaired=%s",
            first.score,
            first.ready,
            first.hard_blockers[:6],
            lower_repaired,
        )
        if first.ready:
            return draft

        if lower_repaired:
            # The lower production contract pipeline already ran its bounded AI
            # repair and revalidated the repaired result. Never spend a second
            # repair call on the same request. The deterministic >=8.5 gate is
            # still authoritative: unresolved defects remain PRELIMINARY.
            draft.status = VerificationStatus.NEEDS_VERIFICATION
            note = _quality_note(first.score, first.repair_issues())
            if note not in draft.verification_notes:
                draft.verification_notes.append(note)
            LOGGER.info(
                "DOCUMENT_QUALITY kind=contract duplicate_outer_repair_skipped score=%.1f blockers=%s",
                first.score,
                first.hard_blockers[:6],
            )
            return draft

        current = {
            "contract_type": draft.contract_type,
            "title": draft.title,
            "place_and_date": draft.place_and_date,
            "party_a": draft.party_a,
            "party_b": draft.party_b,
            "preamble": draft.preamble,
            "sections": [
                {
                    "heading": section.heading,
                    "clauses": [
                        {"text": clause.text, "subclauses": list(clause.subclauses)}
                        for clause in section.clauses
                    ],
                }
                for section in draft.sections
            ],
            "requisites_a": draft.requisites_a,
            "requisites_b": draft.requisites_b,
            "verification_notes": draft.verification_notes,
        }
        payload = await self._quality_repair(
            schema_name="korgan_universal_quality_contract",
            schema=_CONTRACT_SCHEMA,
            case_context=case_context,
            research=research,
            current_payload=current,
            issues=first.repair_issues(),
            language=language,
            document_label="договор",
            extra_rules=(
                "8. Для договора обязательно сохрани правильный вид договора, идентификацию и роли обеих сторон, предмет, существенные условия, "
                "порядок исполнения/приемки/оплаты/прекращения и подписной блок. Коммерческие условия, которых пользователь не задавал и закон не устанавливает, не выдумывай."
            ),
        )
        repaired = ContractDraft.from_payload(
            status=research.status,
            source_urls=list(research.source_urls),
            payload=payload,
        )
        second = assess_document_quality("contract", case_context, research, repaired)
        LOGGER.info(
            "DOCUMENT_QUALITY kind=contract stage=repaired score=%.1f ready=%s blockers=%s",
            second.score,
            second.ready,
            second.hard_blockers[:6],
        )
        if not second.ready:
            repaired.status = VerificationStatus.NEEDS_VERIFICATION
            note = _quality_note(second.score, second.repair_issues())
            if note not in repaired.verification_notes:
                repaired.verification_notes.append(note)
        return repaired

    async def draft_response_to_claim(
        self,
        case_context: str,
        research: LegalResearch,
        language: str = "ru",
    ) -> ResponseToClaimDraft:
        draft = await super().draft_response_to_claim(case_context, research, language=language)
        first = assess_document_quality("response_to_claim", case_context, research, draft)
        LOGGER.info(
            "DOCUMENT_QUALITY kind=response_to_claim stage=first score=%.1f ready=%s blockers=%s",
            first.score,
            first.ready,
            first.hard_blockers[:6],
        )
        if first.ready:
            return draft

        current = {
            "title": draft.title,
            "court": draft.court,
            "case_number": draft.case_number,
            "claimant": draft.claimant,
            "defendant": draft.defendant,
            "claim_summary": draft.claim_summary,
            "position": draft.position,
            "objections": [
                {"text": item.text, "subclauses": item.subclauses, "prose": item.prose}
                for item in draft.objections
            ],
            "legal_basis": draft.legal_basis,
            "requests": draft.requests,
            "attachments": draft.attachments,
            "verification_notes": draft.verification_notes,
        }
        payload = await self._quality_repair(
            schema_name="korgan_universal_quality_response",
            schema=_RESPONSE_DRAFT_SCHEMA,
            case_context=case_context,
            research=research,
            current_payload=current,
            issues=first.repair_issues(),
            language=language,
            document_label="отзыв на иск",
            extra_rules=(
                "8. Для отзыва точно отрази требования истца, позицию ответчика и отдельные возражения по каждому существенному требованию. "
                "Не признавай и не оспаривай факты без позиции пользователя и не превращай отзыв во встречный иск."
            ),
        )
        repaired = ResponseToClaimDraft(
            status=research.status,
            source_urls=list(research.source_urls),
            **payload,
        )
        second = assess_document_quality("response_to_claim", case_context, research, repaired)
        LOGGER.info(
            "DOCUMENT_QUALITY kind=response_to_claim stage=repaired score=%.1f ready=%s blockers=%s",
            second.score,
            second.ready,
            second.hard_blockers[:6],
        )
        if not second.ready:
            repaired.status = VerificationStatus.NEEDS_VERIFICATION
            note = _quality_note(second.score, second.repair_issues())
            if note not in repaired.verification_notes:
                repaired.verification_notes.append(note)
        return repaired
