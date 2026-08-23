from __future__ import annotations

import copy
import logging
from typing import Any

import korgan.claim_quality_hotfix as claim_quality_hotfix
from korgan.fast_v2_production_legal import _deterministic_pre_qa
from korgan.late_interest_hotfix import _apply_verified_article_353, _today_kz
from korgan.legal_types import ClaimDraft, LegalResearch
from korgan.openai_legal import _CLAIM_SCHEMA
from korgan.professional_claim_finalizer import finalize_professional_claim
from korgan.universal_word_quality_guard import finalize_claim_for_release

LOGGER = logging.getLogger(__name__)
_PATCHED = False


def _repair_service() -> Any | None:
    """Find the production drafting service that owns the existing quality repair."""
    from korgan import bot as base_bot

    service = base_bot.service
    visited: set[int] = set()
    while service is not None and id(service) not in visited:
        visited.add(id(service))
        if callable(getattr(service, "_quality_repair", None)):
            return service
        service = getattr(service, "inner", None)
    return None


def _claim_payload(draft: ClaimDraft) -> dict[str, Any]:
    """Return only fields accepted by the strict claim repair schema."""
    return {
        "title": draft.title,
        "court": draft.court,
        "claimant": list(draft.claimant),
        "defendant": list(draft.defendant),
        "price_of_claim": draft.price_of_claim,
        "facts": list(draft.facts),
        "legal_basis": list(draft.legal_basis),
        "requests": list(draft.requests),
        "attachments": list(draft.attachments),
        "verification_notes": list(draft.verification_notes),
    }


def _release_issues(release: Any) -> list[str]:
    """Convert final release findings into narrowly scoped repair instructions."""
    issues = [
        "FINAL_RELEASE_CITATION: " + finding.as_note()
        for finding in list(release.citations.blocking)[:6]
    ]
    issues.extend(
        "FINAL_RELEASE_INTEGRITY: " + finding.as_note()
        for finding in list(release.integrity)[:4]
    )
    return list(dict.fromkeys(issues))


async def repair_claim_release(
    *,
    context: str,
    research: LegalResearch,
    draft: ClaimDraft,
    language: str,
    release: Any,
) -> ClaimDraft | None:
    """Run one bounded repair for defects discovered only by the final release gate.

    The model is allowed to repair only citation/integrity defects. After that
    pass every deterministic filing invariant is re-applied in code so a model
    repair cannot silently drop a penalty, claim price, state duty, material-law
    basis, source-requested judicial costs or filing-risk note.
    """
    service = _repair_service()
    issues = _release_issues(release)
    if service is None or not issues:
        return None

    payload = await service._quality_repair(
        schema_name="korgan_claim_final_release_repair",
        schema=_CLAIM_SCHEMA,
        case_context=context,
        research=research,
        current_payload=_claim_payload(draft),
        issues=issues,
        language=language,
        document_label="исковое заявление",
        extra_rules=(
            "8. Это FINAL RELEASE REPAIR. Исправь только перечисленные final-release дефекты. "
            "Неподтвержденный или неверный пересказ статьи нельзя сохранять: либо замени его формулировкой, прямо следующей из VERIFIED текущего дела, либо убери неподтвержденное утверждение. "
            "9. Не подбирай другую статью по памяти и не добавляй новую норму, которой нет в VERIFIED. "
            "10. Не удаляй факты, стороны, суммы, требования или приложения только ради прохождения проверки. "
            "Если обязательный элемент нельзя восстановить из материалов пользователя и VERIFIED, оставь явный пробел/NEEDS_VERIFICATION вместо выдумывания."
        ),
    )
    repaired = ClaimDraft(
        status=research.status,
        source_urls=list(research.source_urls),
        **payload,
    )

    # IMPORTANT: the old production path stopped after the LLM repair here.
    # That let the last model pass undo deterministic work already performed by
    # FinalizedProductionClaimService. Re-run the same zero-call finalization
    # chain before the repaired draft is ever eligible for Word delivery.
    finalize_professional_claim(context, research, repaired)
    _deterministic_pre_qa(context, research, repaired)
    _apply_verified_article_353(context, research, repaired, filing_date=_today_kz())
    finalize_professional_claim(context, research, repaired)
    finalize_claim_for_release(context, repaired, language=language)
    _deterministic_pre_qa(context, research, repaired)
    claim_quality_hotfix.polish_claim_before_quality(context, research, repaired)
    return repaired


def _client_block_message(release: Any, language: str) -> str:
    """Return a short fail-closed message without leaking the generated draft."""
    citation = next(iter(release.citations.blocking), None)
    integrity = next(iter(release.integrity), None)
    if language == "kk":
        if citation is not None:
            return (
                "Құжат автоматты түрде қайта тексерілді, бірақ бір құқықтық сілтемені қауіпсіз түзету мүмкін болмады. "
                "KORGAN күмәнді нормамен Word бермейді. Іс деректері сақталды; құқықтық негізді нақтылап, құжатты қайта дайындаңыз."
            )
        if integrity is not None:
            return (
                "Құжат автоматты түрде қайта тексерілді, бірақ мәтін тұтастығының қатесі қалды. "
                "Қауіпсіз емес Word берілген жоқ; іс деректері сақталды."
            )
        return "Құжат финалдық тексеруден өтпеді; іс деректері сақталды."

    if citation is not None:
        return (
            "Документ автоматически перепроверен, но одну правовую ссылку не удалось безопасно исправить. "
            "KORGAN не выдаёт Word с сомнительной нормой. Данные дела сохранены — уточните правовое основание и повторите подготовку документа."
        )
    if integrity is not None:
        return (
            "Документ автоматически перепроверен, но в тексте осталась ошибка целостности. "
            "Небезопасный Word не выдан; данные дела сохранены."
        )
    return "Документ не прошёл финальную проверку; данные дела сохранены."


def install_claim_release_repair() -> None:
    """Layer a targeted release-repair retry around the existing claim hotfix."""
    global _PATCHED
    if _PATCHED:
        return

    original_install = claim_quality_hotfix.install_runtime_hotfix

    def patched_install_runtime_hotfix() -> None:
        original_install()

        from korgan import bot as base_bot
        from korgan import universal_claim_runtime as runtime
        from korgan.request_scope import request_is_current

        original_send = runtime._send_claim

        async def _send_claim_with_release_repair(
            message,
            state,
            *,
            context: str,
            research: LegalResearch,
            draft: ClaimDraft,
            request_id: str,
        ) -> None:
            if not await request_is_current(state, request_id, "claim"):
                LOGGER.info("STALE_DOCUMENT_SUPPRESSED kind=claim request_id=%s", request_id)
                return

            snapshot = copy.deepcopy(draft)
            release = runtime._downgrade_unverified_citations_live(draft, research)
            if release.citations.blocking or release.integrity:
                language = await base_bot._language(state)
                try:
                    repaired = await repair_claim_release(
                        context=context,
                        research=research,
                        draft=snapshot,
                        language=language,
                        release=release,
                    )
                except Exception:
                    LOGGER.exception("CLAIM_FINAL_RELEASE_REPAIR_FAILED request_id=%s", request_id)
                    repaired = None

                if not await request_is_current(state, request_id, "claim"):
                    LOGGER.info("STALE_DOCUMENT_SUPPRESSED kind=claim request_id=%s", request_id)
                    return

                if repaired is not None:
                    repaired_release = runtime._downgrade_unverified_citations_live(repaired, research)
                    if not repaired_release.citations.blocking and not repaired_release.integrity:
                        LOGGER.info("CLAIM_FINAL_RELEASE_REPAIR_OK request_id=%s", request_id)
                        draft = repaired
                    else:
                        LOGGER.error(
                            "CLAIM_FINAL_RELEASE_REPAIR_BLOCKED request_id=%s citations=%s integrity=%s",
                            request_id,
                            [x.as_note() for x in repaired_release.citations.blocking[:4]],
                            [x.as_note() for x in repaired_release.integrity[:4]],
                        )
                        await message.answer(
                            _client_block_message(repaired_release, language),
                            reply_markup=base_bot.MENU,
                        )
                        return
                else:
                    await message.answer(
                        _client_block_message(release, language),
                        reply_markup=base_bot.MENU,
                    )
                    return

            await original_send(
                message,
                state,
                context=context,
                research=research,
                draft=draft,
                request_id=request_id,
            )

        runtime._send_claim = _send_claim_with_release_repair
        LOGGER.info("Installed bounded final release repair for claims")

    claim_quality_hotfix.install_runtime_hotfix = patched_install_runtime_hotfix
    _PATCHED = True
