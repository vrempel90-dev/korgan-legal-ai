from __future__ import annotations

from typing import Any

from korgan.fast_professional_litigation import FastProfessionalLitigationService


_ORIGINAL_QUALITY_REPAIR = FastProfessionalLitigationService._quality_repair


def merge_repair_payload(
    current_payload: dict[str, Any],
    repaired_payload: dict[str, Any],
) -> dict[str, Any]:
    """Overlay a targeted model repair on the last valid claim payload.

    A repair call is allowed to return only the fields it actually changed.
    The previous implementation passed that partial mapping directly to
    ``ClaimDraft`` and crashed when required fields such as ``legal_basis`` or
    ``requests`` were omitted. Keeping the last valid payload as the base
    preserves FACT LOCK and the already verified structure while still letting
    every explicit repair value win.
    """
    merged = dict(current_payload or {})
    merged.update(dict(repaired_payload or {}))
    return merged


async def _quality_repair_preserving_required_fields(
    self: FastProfessionalLitigationService,
    *args: Any,
    **kwargs: Any,
) -> dict[str, Any]:
    current_payload = dict(kwargs.get("current_payload") or {})
    repaired = await _ORIGINAL_QUALITY_REPAIR(self, *args, **kwargs)
    if not isinstance(repaired, dict):
        return repaired
    return merge_repair_payload(current_payload, repaired)


# Patch only the fast professional litigation service. Other document types and
# the underlying provider/client remain untouched.
FastProfessionalLitigationService._quality_repair = _quality_repair_preserving_required_fields
