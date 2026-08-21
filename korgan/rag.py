from __future__ import annotations

from urllib.parse import urlparse

TRUSTED_HOSTS = {"adilet.zan.kz"}


def is_trusted_source(url: str) -> bool:
    """Compatibility helper kept for fail-closed tests.

    The active legal workflow is implemented in ``korgan.openai_legal`` and
    uses OpenAI Web Search restricted to configured official domains.
    """
    try:
        host = (urlparse(url).hostname or "").lower()
    except ValueError:
        return False
    return host in TRUSTED_HOSTS
