from __future__ import annotations

import logging
import os

from korgan.claim_pipeline_v2 import MODE_ENV
from korgan.config import Settings

LOGGER = logging.getLogger(__name__)


def apply_token_budget_guard(settings: Settings) -> str:
    """Keep the proven production claim path when the budget guard is enabled.

    ClaimPipelineV2 is intentionally experimental and can add multiple model calls
    before/after the normal source-bound legal workflow. Under the four-month
    budget, it stays off unless an operator explicitly opts in with
    ``ALLOW_EXTRA_AI_PIPELINE_CALLS=true``. This does not downgrade the model used
    for legal research, drafting, validation, citation checks, or DOCX release.
    """
    requested = os.getenv(MODE_ENV, "off").strip().lower() or "off"
    if not settings.token_budget_guard_enabled:
        return requested
    if requested == "off" or settings.allow_extra_ai_pipeline_calls:
        return requested

    LOGGER.warning(
        "TOKEN_BUDGET_GUARD forcing %s=off requested=%s monthly_budget_usd=%.2f; "
        "set ALLOW_EXTRA_AI_PIPELINE_CALLS=true only for an explicit quality experiment",
        MODE_ENV,
        requested,
        settings.monthly_ai_budget_usd,
    )
    os.environ[MODE_ENV] = "off"
    return "off"
