"""Small bridges that keep late production stages on the v2 invariant policy."""

from __future__ import annotations

import logging
import re
from types import SimpleNamespace
from typing import Any

from korgan.production_invariants_v2 import review_marker

LOGGER = logging.getLogger(__name__)
_ARTICLE_RE = re.compile(r"(?i)(?:стать(?:я|и|е|ю|ёй|ей)|ст\.)\s*\d+(?:-\d+)?")


def install_finalized_policy_bridge_v2() -> None:
    """Use the same claim QA/preflight policy before and after finalization.

    ``FastProfessionalLitigationService`` is intentionally patched by
    claim_quality_hotfix without mutating document_quality globally.  The later
    FinalizedProductionClaimService historically bypassed that scoped policy by
    reading document_quality/senior_claim_preflight modules directly, which can
    make a document score lower even when its text did not regress.
    """
    from korgan import fast_professional_litigation as fast
    from korgan import finalized_litigation as finalized

    if getattr(finalized, "_korgan_finalized_policy_v2", False):
        return

    # Replace only the module-local references used by finalized_litigation;
    # do not mutate document_quality or senior_claim_preflight globally.
    finalized._dq = SimpleNamespace(assess_document_quality=fast.assess_document_quality)
    finalized._sp = SimpleNamespace(deterministic_claim_preflight=fast.deterministic_claim_preflight)
    finalized._korgan_finalized_policy_v2 = True
    LOGGER.info("FINALIZATION_POLICY aligned_with_repaired_preflight=1")


def install_consultation_invariants_v2(service_cls: type[Any]) -> None:
    """Make consultation degradations visible instead of log/prompt-only.

    Consultation is text rather than DOCX, so its equivalent of [СВЕРИТЬ] is a
    visible line appended to the answer.  Precise article references without an
    official source URL are never allowed to look silently verified.
    """
    if getattr(service_cls, "_korgan_consultation_invariants_v2", False):
        return
    original = service_cls.consult

    async def consult(
        self: Any,
        question: str,
        case_context: str = "",
        language: str = "ru",
    ) -> tuple[str, list[str]]:
        answer, urls = await original(self, question, case_context=case_context, language=language)
        issues: list[str] = []
        upper = answer.upper()
        if "NEEDS_VERIFICATION" in upper:
            for raw in answer.splitlines():
                if "NEEDS_VERIFICATION" in raw.upper():
                    issues.append(" ".join(raw.split())[:500])
                    break
        if _ARTICLE_RE.search(answer) and not urls:
            issues.append("точная статья указана без source-bound официального URL в текущем ответе")

        issues = list(dict.fromkeys(x for x in issues if x))
        if issues and "[СВЕРИТЬ:" not in answer:
            answer = answer.rstrip() + "\n\n" + "\n".join(review_marker(item) for item in issues[:4])
        LOGGER.info(
            "UNIVERSAL_WORD_QUALITY kind=consultation issues_after=%d delivered=1 user_visible=%d",
            len(issues),
            1 if issues else 0,
        )
        return answer, urls

    service_cls.consult = consult
    service_cls._korgan_consultation_invariants_v2 = True
