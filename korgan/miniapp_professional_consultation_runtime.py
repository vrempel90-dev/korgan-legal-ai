from __future__ import annotations

import logging

from korgan import miniapp_api as legacy
from korgan import miniapp_api_v2 as core
from korgan.professional_consultation import ProfessionalConsultationAdapter

LOGGER = logging.getLogger(__name__)
_INSTALLED = False


def install_professional_consultation_runtime() -> None:
    global _INSTALLED
    if _INSTALLED:
        return

    current = core.service
    if isinstance(current, ProfessionalConsultationAdapter):
        adapter = current
    else:
        adapter = ProfessionalConsultationAdapter(current)

    # miniapp_api_v2 consults through its module-level service. Its legacy
    # helper methods also resolve document services through miniapp_api.service,
    # so both references must point at the same adapter. __getattr__ forwards all
    # document-generation methods unchanged; only consult() is replaced.
    core.service = adapter
    legacy.service = adapter
    _INSTALLED = True
    LOGGER.info("Installed source-bound professional Mini App consultation runtime")


install_professional_consultation_runtime()
