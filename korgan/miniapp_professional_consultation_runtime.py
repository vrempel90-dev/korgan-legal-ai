from __future__ import annotations

import logging
from typing import Any, Awaitable, Callable

from korgan import miniapp_api_v2 as core
from korgan.professional_consultation import ProfessionalConsultationAdapter

LOGGER = logging.getLogger(__name__)
_INSTALLED = False


def install_professional_consultation_runtime() -> None:
    """Upgrade consult() without replacing the production legal service chain.

    Mini App parity depends on ``core.service`` remaining the exact
    ClaimPipelineV2Adapter/ClaimServiceMux chain used by strict_bot. Replacing
    that object just to improve consultations changes runtime ownership for all
    document methods as a side effect. Instead, bind only the consultation
    method on the already-constructed service instance. Its type, identity,
    inner claim mux and document-generation methods remain untouched.
    """
    global _INSTALLED
    if _INSTALLED:
        return

    current = core.service
    adapter = ProfessionalConsultationAdapter(current)
    professional_consult: Callable[..., Awaitable[tuple[str, list[str]]]] = adapter.consult
    setattr(current, "consult", professional_consult)

    _INSTALLED = True
    LOGGER.info(
        "Installed source-bound professional consultation on existing service=%s",
        type(current).__name__,
    )


install_professional_consultation_runtime()
