from __future__ import annotations

import logging
import os

from korgan.claim_pipeline_v2 import MODE_ENV
from korgan.config import Settings

LOGGER = logging.getLogger(__name__)


def apply_token_budget_guard(settings: Settings) -> str:
    """Prevent accidental extra AI pipeline calls without downgrading legal models."""
    requested = os.getenv(MODE_ENV, "off").strip().lower() or "off"
    if not settings.token_budget_guard_enabled:
        return requested
    if requested == "off" or settings.allow_extra_ai_pipeline_calls:
        return requested

    LOGGER.warning(
        "TOKEN_BUDGET_GUARD forcing %s=off requested=%s monthly_target_usd=%.2f",
        MODE_ENV,
        requested,
        settings.monthly_ai_budget_usd,
    )
    os.environ[MODE_ENV] = "off"
    return "off"
