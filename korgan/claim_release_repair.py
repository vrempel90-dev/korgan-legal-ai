from __future__ import annotations

import copy
import logging
from typing import Any

import korgan.claim_quality_hotfix as claim_quality_hotfix
from korgan.citation_audit import ProvisionReference, extract_references
from korgan.fast_v2_production_legal import _deterministic_pre_qa
from korgan.instant_claim_runtime import _strip_reference_token
from korgan.late_interest_hotfix import _apply_verified_article_353, _today_kz
from korgan.legal_types import ClaimDraft, LegalResearch
from korgan.openai_legal import _CLAIM_SCHEMA
from korgan.pipeline_invariants_v2 import (
    annotate_internal_quality,
    exact_client_diagnostics,
    split_issues,
)

LOGGER = logging.getLogger(__name__)
_PATCHED = False


def _repair_service() -> Any | None:
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
    issues = [
        "FINAL_RELEASE_CITATION: " + finding.as_note()
        for finding in list(release.citations.blocking)[:6]
    ]
    issues.extend(
        "FINAL_RELEASE_INTEGRITY: " + finding.as_note()
        for finding in list(release.integrity)[:4]
    )
    return list(dict.fromkeys(issues))


def _blocking_refs(release: Any) -> list[ProvisionReference]:
    refs: list[ProvisionReference] = []
    for finding in list(release.citations.blocking):
        ref = ProvisionReference(finding.act, finding.article, finding.part)
        if ref not in refs:
            refs.append(ref)
    return refs


def _has_ref(text: str, refs: list[ProvisionReference]) -> bool:
    found = extract_references(text or "")
    return any(wanted.matches(actual) for wanted in refs for actual in found)


def _rewrite_internal_release_defects(draft: ClaimDraft, release: Any) -> None:
    """Rewrite an internal citation defect into an explicit preliminary marker.

    This is not deletion: factual/remedy prose is kept and only the unsafe
    citation token is stripped.  A defective legal-basis proposition itself is
    replaced by a visible [СВЕРИТЬ] marker because KORGAN must not keep asserting
    a proposition it knows it cannot verify.
    """
    issues = _release_issues(release)
    refs = _blocking_refs(release)
    marker = "[СВЕРИТЬ: формулировка правовой нормы требует проверки юристом]"

    if refs:
        rebuilt_basis: list[str] = []
        for raw in draft.legal_basis or []:
            text = str(raw)
            if _has_ref(text, refs):
                if marker not in rebuilt_basis:
                    rebuilt_basis.append(marker)
                continue
            rebuilt_basis.append(text)
        draft.legal_basis = rebuilt_basis

        for attr in ("facts", "requests", "attachments"):
            rebuilt: list[str] = []
            for raw in getattr(draft, attr, []) or []:
                text = str(raw)
                for ref in refs:
                    if any(ref.matches(actual) for actual in extract_references(text)):
                        text = _strip_reference_token(text, ref)
                if text.strip():
                    rebuilt.append(text.strip())
            setattr(draft, attr, rebuilt)

        if draft.late_interest:
            text = draft.late_interest
            for ref in refs:
                if any(ref.matches(actual) for actual in extract_references(text)):
                    text = _strip_reference_token(text, ref)
            draft.late_interest = text.strip()

    annotate_internal_quality(draft, issues)
    LOGGER.warning(
        "PIPELINE_QUALITY_REWRITE kind=claim class=INTERNAL_QUALITY rewritten_refs=%s issues=%s",
        [ref.label() for ref in refs],
        issues[:6],
    )


async def repair_claim_release(
    *,
    context: str,
    research: LegalResearch,
    draft: ClaimDraft,
    language: str,
    release: Any,
) -> ClaimDraft | None:
    """Run one bounded repair for defects discovered by the final release gate."""
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
            "Неподтвержденный или неверный пересказ статьи нельзя сохранять: замени его формулировкой, прямо следующей из VERIFIED текущего дела. "
            "9. Не подбирай другую статью по памяти и не добавляй новую норму, которой нет в VERIFIED. "
            "10. Не удаляй факты, стороны, суммы, требования или приложения ради прохождения проверки. "
            "Если юридическую формулировку нельзя восстановить из VERIFIED, оставь явный [СВЕРИТЬ] маркер вместо выдумывания."
        ),
    )
    repaired = ClaimDraft(
        status=research.status,
        source_urls=list(research.source_urls),
        **payload,
    )

    from korgan.claim_release_invariants import enforce_claim_release_invariants
    from korgan.professional_claim_finalizer import finalize_professional_claim
    from korgan.universal_word_quality_guard import finalize_claim_for_release

    finalize_professional_claim(context, research, repaired, language=language)
    enforce_claim_release_invariants(context, repaired, language=language)
    _deterministic_pre_qa(context, research, repaired)
    _apply_verified_article_353(context, research, repaired, filing_date=_today_kz())
    finalize_professional_claim(context, research, repaired, language=language)
    enforce_claim_release_invariants(context, repaired, language=language)
    _deterministic_pre_qa(context, research, repaired)
    finalize_claim_for_release(context, repaired, language=language)
    claim_quality_hotfix.polish_claim_before_quality(context, research, repaired)
    enforce_claim_release_invariants(context, repaired, language=language)
    return repaired


def _client_user_data_message(issues: list[str], language: str) -> str:
    diagnostics = exact_client_diagnostics("claim", issues)
    if language == "kk":
        return "Құжатты аяқтау үшін пайдаланушыдан қосымша деректер қажет:\n\n" + diagnostics
    return "Иск пока не выпущен: нужны данные, которые может предоставить только пользователь.\n\n" + diagnostics


def install_claim_release_repair() -> None:
    """Layer targeted repair + Goal-v2 blocker classes around claim release."""
    global _PATCHED
    if _PATCHED:
        return

    original_install = claim_quality_hotfix.install_runtime_hotfix

    def patched_install_runtime_hotfix() -> None:
        original_install()

        from korgan import bot as base_bot
        from korgan import universal_claim_runtime as runtime
        from korgan.request_scope import request_is_current

        # Internal legal-source quality is allowed to reach the client only as a
        # PRELIMINARY document with an explicit [СВЕРИТЬ] marker. Missing
        # executable relief remains a hard block because no document exists.
        current_core = runtime.core_claim_release_blockers
        if not getattr(current_core, "_korgan_goal_v2", False):
            def core_with_internal_markers(research: LegalResearch, draft: ClaimDraft) -> list[str]:
                blockers = current_core(research, draft)
                visible_internal = any(
                    str(note).startswith("[СВЕРИТЬ:") or "INTERNAL_QUALITY" in str(note)
                    for note in draft.verification_notes or []
                ) or any("[СВЕРИТЬ:" in str(line) for line in draft.legal_basis or [])
                if not visible_internal:
                    return blockers
                kept = [
                    blocker for blocker in blockers
                    if "исполнимая просительная часть" in blocker
                ]
                if len(kept) != len(blockers):
                    LOGGER.warning(
                        "PIPELINE_INVARIANT I3 internal_core_blockers_marked_not_blocked blockers=%s",
                        blockers,
                    )
                return kept
            core_with_internal_markers._korgan_goal_v2 = True  # type: ignore[attr-defined]
            runtime.core_claim_release_blockers = core_with_internal_markers

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

                candidate = repaired if repaired is not None else snapshot
                candidate_release = runtime._downgrade_unverified_citations_live(candidate, research)
                if not candidate_release.citations.blocking and not candidate_release.integrity:
                    LOGGER.info("CLAIM_FINAL_RELEASE_REPAIR_OK request_id=%s", request_id)
                    draft = candidate
                else:
                    remaining = _release_issues(candidate_release)
                    user_issues, internal_issues = split_issues(remaining)
                    if user_issues:
                        LOGGER.error(
                            "CLAIM_FINAL_RELEASE_REPAIR_BLOCKED request_id=%s block_class=NEEDS_USER_DATA issues=%s",
                            request_id,
                            user_issues[:6],
                        )
                        await message.answer(
                            _client_user_data_message(user_issues, language),
                            reply_markup=base_bot.MENU,
                        )
                        return

                    # Citation/paraphrase/integrity failures are KORGAN's own
                    # quality problem. Do not tell the client to repair our law.
                    _rewrite_internal_release_defects(candidate, candidate_release)
                    diagnostics = exact_client_diagnostics("claim", internal_issues)
                    LOGGER.error(
                        "CLAIM_FINAL_RELEASE_REPAIR_DEGRADED request_id=%s block_class=INTERNAL_QUALITY action=DELIVER_WITH_MARKER issues=%s",
                        request_id,
                        internal_issues[:6],
                    )
                    await message.answer(
                        "⚠️ KORGAN не смог автоматически исправить собственную правовую формулировку. "
                        "Иск будет выдан как PRELIMINARY с явным маркером [СВЕРИТЬ].\n\n" + diagnostics,
                        reply_markup=base_bot.MENU,
                    )
                    draft = candidate

            await original_send(
                message,
                state,
                context=context,
                research=research,
                draft=draft,
                request_id=request_id,
            )

        runtime._send_claim = _send_claim_with_release_repair
        LOGGER.info("Installed Goal-v2 final release repair for claims")

    claim_quality_hotfix.install_runtime_hotfix = patched_install_runtime_hotfix
    _PATCHED = True
