from __future__ import annotations

import json
import logging

from korgan.claim_quality_gate import MIN_READY_SCORE, assess_claim_quality
from korgan.fast_v2_production_legal import _deterministic_pre_qa
from korgan.instant_claim_runtime import InstantClaimProductionService
from korgan.late_interest_hotfix import _apply_verified_article_353, _today_kz
from korgan.legal_types import ClaimDraft, LegalResearch, VerificationStatus
from korgan.openai_legal import _CLAIM_SCHEMA

LOGGER = logging.getLogger(__name__)


class QualityClaimProductionService(InstantClaimProductionService):
    """Instant claim service with a mandatory 8.5/10 release-quality target.

    The fast path stays fast: research + first draft only. A second model call is
    made only when deterministic scoring finds that the first draft is below the
    product quality bar. The repair is source-bound: it may use only facts from
    the case and legal propositions already present in VERIFIED research.
    """

    async def draft_claim(
        self,
        case_context: str,
        research: LegalResearch,
        language: str = "ru",
    ) -> ClaimDraft:
        draft = await super().draft_claim(case_context, research, language=language)
        first = assess_claim_quality(case_context, research, draft)
        LOGGER.info(
            "CLAIM_QUALITY first=%.1f ready=%s categories=%s issues=%s",
            first.score,
            first.ready,
            first.category_scores,
            first.issues[:8],
        )
        if first.ready:
            return draft

        verified = "\n".join(f"- {item}" for item in research.verified_claims) or "нет подтвержденных выводов"
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
        }
        prompt = (
            "Доработай судебный проект иска KORGAN до внутреннего качества не ниже 8.5/10. "
            "Исправь ТОЛЬКО перечисленные дефекты. Не добавляй факты, суммы, даты, доказательства или нормы по памяти.\n\n"
            "ОБЯЗАТЕЛЬНО:\n"
            "1. Все известные сведения из материалов сохрани дословно по смыслу; неизвестные не выдумывай.\n"
            "2. Для юридического лица не требуй ФИО стороны: используй полное наименование, БИН и место нахождения, если они известны.\n"
            "3. Не требуй банковские реквизиты истца-физлица как обязательный реквизит иска.\n"
            "4. Правовое обоснование должно содержать конкретные статьи только из VERIFIED и объяснять, почему именно они поддерживают заявленное требование.\n"
            "5. Не подменяй требование соседней нормой. Для возврата денег по действующему договору проверь логическую связь с отказом/расторжением/прекращением основания только в пределах VERIFIED и фактов. Не утверждай, что отказ уже был направлен, если этого нет в материалах.\n"
            "6. Неосновательное обогащение используй только если в тексте проекта объяснено отпадение/отсутствие основания и это подтверждается VERIFIED; иначе убери его.\n"
            "7. Не выдумывай конкретный суд и госпошлину. Если их нельзя безопасно определить из материалов/VERIFIED, оставь точную короткую пометку в соответствующем поле, а не юридическую догадку.\n"
            "8. Просительная часть должна быть юридически связана с фактами и правовым обоснованием; не добавляй новые самостоятельные требования без опоры в материалах/VERIFIED.\n"
            "9. Приложения — только реально упомянутые доказательства и процессуально необходимые копии, без выдуманных документов.\n"
            "10. Никаких URL, Markdown, чатовых советов или служебных фраз в теле иска.\n\n"
            f"МАТЕРИАЛЫ ДЕЛА:\n{case_context[:self.settings.max_case_text_chars]}\n\n"
            f"VERIFIED:\n{verified}\n\n"
            f"ПРОБЛЕМЫ QUALITY GATE:\n{json.dumps(first.issues, ensure_ascii=False)}\n\n"
            f"ТЕКУЩИЙ ПРОЕКТ:\n{json.dumps(current, ensure_ascii=False)}"
        )
        payload, _ = await self._structured_response(
            model=self.settings.openai_model,
            instructions=(
                "Ты старший судебный редактор KORGAN по праву Республики Казахстан. "
                "Твоя задача — повысить качество уже существующего иска без правовой фантазии и без изменения фактов. "
                f"Язык: {'казахский' if language == 'kk' else 'русский'}."
            ),
            content=[{"role": "user", "content": [{"type": "input_text", "text": prompt}]}],
            schema_name="korgan_quality_repaired_claim",
            schema=_CLAIM_SCHEMA,
        )

        repaired = ClaimDraft(
            status=research.status,
            source_urls=list(research.source_urls),
            **payload,
        )
        _deterministic_pre_qa(case_context, research, repaired)
        _apply_verified_article_353(
            case_context,
            research,
            repaired,
            filing_date=_today_kz(),
        )

        second = assess_claim_quality(case_context, research, repaired)
        LOGGER.info(
            "CLAIM_QUALITY repaired=%.1f ready=%s categories=%s issues=%s",
            second.score,
            second.ready,
            second.category_scores,
            second.issues[:8],
        )
        if not second.ready:
            repaired.status = VerificationStatus.NEEDS_VERIFICATION
            note = (
                f"KORGAN quality gate: проект набрал {second.score:.1f}/10 при целевом пороге "
                f"{MIN_READY_SCORE:.1f}/10; перед подачей требуется проверить: "
                + "; ".join(second.issues[:5])
            )
            if note not in repaired.verification_notes:
                repaired.verification_notes.append(note)
        return repaired
