from __future__ import annotations

import logging
from typing import Awaitable, Callable

from korgan import miniapp_api_v2 as core
from korgan.fast_local_consultation import FastLocalConsultationAdapter
from korgan.professional_consultation import ProfessionalConsultationAdapter

LOGGER = logging.getLogger(__name__)
_INSTALLED = False


def install_professional_consultation_runtime() -> None:
    """Bind a fast local-first consultation without replacing the legal service.

    Normal consultations use KORGAN's refreshed local Adilet corpus plus one
    structured model call and therefore do not wait for live web search. The
    previous web-bound professional consultation is retained strictly as a
    fallback when the local corpus is unavailable or the fast model call fails.
    Document-generation methods and service identity remain untouched.
    """
    global _INSTALLED
    if _INSTALLED:
        return

    current = core.service
    web_adapter = ProfessionalConsultationAdapter(current)
    web_consult: Callable[..., Awaitable[tuple[str, list[str]]]] = web_adapter.consult
    fast_adapter = FastLocalConsultationAdapter(current, fallback=web_consult)
    fast_consult: Callable[..., Awaitable[tuple[str, list[str]]]] = fast_adapter.consult
    setattr(current, "consult", fast_consult)

    _INSTALLED = True
    LOGGER.info(
        "Installed fast local-Adilet consultation with web fallback on service=%s",
        type(current).__name__,
    )


install_professional_consultation_runtime()
