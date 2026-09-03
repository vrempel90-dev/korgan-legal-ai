from __future__ import annotations

from typing import Any

from fastapi import Header

from korgan import miniapp_api_v4 as v4
from korgan import miniapp_document_consultation as _miniapp_document_consultation  # noqa: F401
from korgan.consultation_quota import consultation_usage

app = v4.app
core = v4.core
settings = v4.settings


@app.get("/miniapp/consultation/quota")
async def consultation_quota_status(
    x_telegram_init_data: str = Header(default=""),
) -> dict[str, Any]:
    """Return the authenticated user's real daily consultation quota state.

    This endpoint is deterministic and never calls the legal model. When the
    quota feature is disabled there is no finite remaining count.
    """
    identity = core.legacy._identity(x_telegram_init_data)
    await core.legacy._require_consent(identity)
    limit = int(settings.free_consultations_per_day)
    if not settings.consultation_limit_enabled:
        return {
            "enabled": False,
            "limit": limit,
            "remaining": None,
        }

    used = await consultation_usage(v4._quota_user_id(identity))
    return {
        "enabled": True,
        "limit": limit,
        "used": used,
        "remaining": max(limit - used, 0),
    }
