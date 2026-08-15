from __future__ import annotations

import copy
import json
import logging
import re
import time

from korgan.legal_routing import detect_claim_profile
from korgan.legal_types import LegalResearch, VerificationStatus
from korgan.robust_production_legal import ProductionOpenAILegalService as _RobustService
from korgan.verified_openai import _actual_response_urls

LOGGER = logging.getLogger(__name__)

_DUTY_MARKERS = (
    "госпошлин",
    "государственной пошлин",
    "государственную пошлин",
    "налогового кодекса",
    "налоговый кодекс",
    "статья 610",
    "ст. 610",
    "статья 665",
    "ст. 665",
    "статья 668",
    "ст. 668",
)


def _is_state_duty_text(value: str) -> bool:
    lowered = (value or "").lower()
    return any(marker in lowered for marker in _DUTY_MARKERS)


def _sanitize_civil_research(research: LegalResearch) -> LegalResearch:
    """Keep state-duty law outside the civil-claim legal qualification.

    State duty is calculated by korgan.legal_calc.  It must not be allowed to
    change the material-law qualification of a civil claim or block the DOCX
    because a web-search result mentioned a stale Tax Code article.
    """
    verified = [item for item in research.verified_claims if not _is_state_duty_text(item)]
    unverified = [item for item in research.unverified_claims if not _is_state_duty_text(item)]
    applicable = [item for item in research.applicable_law if not _is_state_duty_text(item)]
    procedural = [item for item in research.procedural_requirements if not _is_state_duty_text(item)]

    status = (
        VerificationStatus.VERIFIED
        if verified and research.source_urls and not unverified
        else VerificationStatus.NEEDS_VERIFICATION
    )
    return LegalResearch(
        status=status,
        applicable_law=applicable,
        procedural_requirements=procedural,
        verified_claims=verified,
        unverified_claims=unverified,
        source_urls=list(research.source_urls),
        notes=list(research.notes),
    )


def _has_article(research: LegalResearch, article: str) -> bool:
    text = "\n".join(research.verified_claims)
    return bool(re.search(rf"(?<!\d){re.escape(article)}(?!\d)", text))


def _core_profile_supported(profile_code: str, research: LegalResearch) -> bool:
    if not research.verified_claims or not research.source_urls:
        return False
    # For a loan/debt claim, 715 establishes the loan relation and 722 the
    # return obligation.  Article 716 is important where form is disputed, but
    # absence of 716 alone must not trigger a second 20-40 second web search.
    if profile_code == "loan_debt":
        return _has_article(research, "715") and _has_article(research, "722")
    return True


class ProductionOpenAILegalService(_RobustService):
    """Production hotfix for civil claims: no stale-tax QA conflicts, fewer retries."""

    async def _structured_response(
        self,
        *,
        model: str,
        instructions: str,
        content,
        schema_name: str,
        schema,
        tools=None,
    ):
        # Research JSON was repeatedly being cut at the old 2300-token cap,
        # forcing a full second Responses API call. Give only legal research a
        # safer cap; all other calls keep the tuned robust runtime behavior.
        if schema_name != "korgan_verified_legal_research":
            return await super()._structured_response(
                model=model,
                instructions=instructions,
                content=content,
                schema_name=schema_name,
                schema=schema,
                tools=tools,
            )

        kwargs = {
            "model": model,
            "instructions": instructions,
            "input": content,
            "text": self._json_schema(schema_name, schema),
            "store": False,
            "prompt_cache_key": "korgan:korgan_verified_legal_research:v5",
            "max_output_tokens": 3600,
        }
        if model == "gpt-5.1" or model.startswith("gpt-5.1-"):
            kwargs["reasoning"] = {"effort": "none"}
        if tools:
            kwargs["tools"] = tools
            kwargs["tool_choice"] = "required"
            kwargs["include"] = ["web_search_call.action.sources"]

        started = time.perf_counter()
        response = await self.client.responses.create(**kwargs)
        elapsed = time.perf_counter() - started
        try:
            payload = json.loads(response.output_text)
        except json.JSONDecodeError:
            # Rare safety retry.  Unlike the old path, the first attempt already
            # has enough room for normal research, so this should be exceptional.
            retry_kwargs = dict(kwargs)
            retry_kwargs["max_output_tokens"] = 5600
            response = await self.client.responses.create(**retry_kwargs)
            payload = json.loads(response.output_text)
            LOGGER.warning("KORGAN civil research JSON required one safety retry")

        LOGGER.info(
            "KORGAN civil research call seconds=%.2f actual_web_urls=%d",
            elapsed,
            len(_actual_response_urls(response)),
        )
        return payload, response

    async def research_case(self, case_context: str, language: str = "ru") -> LegalResearch:
        profile = detect_claim_profile(case_context)
        cache_key = self._claim_cache_key(case_context, language)
        cached = self._claim_research_cache.get(cache_key)
        now = time.monotonic()
        if cached and now - cached[0] <= 15 * 60:
            LOGGER.info("KORGAN civil claim research cache HIT profile=%s", profile.code)
            return cached[1]

        started = time.perf_counter()
        # A loan case gets medium context once.  This is much cheaper than the
        # previous low pass followed by a mandatory high-context second pass.
        search_size = "medium" if profile.code == "loan_debt" else profile.search_context_size
        research = await self._profiled_claim_research(
            case_context,
            language,
            search_context_size=search_size,
        )
        research = _sanitize_civil_research(research)

        # Fail closed only when the actual material-law backbone is missing.
        # Do not repeat research merely because a non-core article was omitted.
        if not _core_profile_supported(profile.code, research):
            LOGGER.info("KORGAN civil claim one targeted fallback profile=%s", profile.code)
            research = await self._profiled_claim_research(
                case_context,
                language,
                search_context_size="high",
            )
            research = _sanitize_civil_research(research)

        self._claim_research_cache[cache_key] = (time.monotonic(), research)
        LOGGER.info(
            "KORGAN civil claim research total seconds=%.2f profile=%s verified=%d",
            time.perf_counter() - started,
            profile.code,
            len(research.verified_claims),
        )
        return research

    async def validate_claim(self, case_context: str, research: LegalResearch, draft):
        """FINAL LEGAL QA checks the civil claim, not the tax calculator.

        A deterministic state-duty line/request is intentionally removed from
        the model QA copy.  The real draft is untouched and still receives the
        amount from legal_calc.  This prevents stale Tax Code search snippets
        from blocking an otherwise correct civil claim.
        """
        qa_research = _sanitize_civil_research(research)
        qa_draft = copy.deepcopy(draft)
        qa_draft.state_duty = ""
        qa_draft.requests = [
            item for item in qa_draft.requests if "госпошлин" not in item.lower()
        ]
        qa_draft.legal_basis = [
            item for item in qa_draft.legal_basis if not _is_state_duty_text(item)
        ]
        return await super().validate_claim(case_context, qa_research, qa_draft)
