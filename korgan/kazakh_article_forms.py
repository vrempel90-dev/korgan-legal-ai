from __future__ import annotations

import re


def install_kazakh_article_forms() -> None:
    """Accept both «722-бап» and inflected «722-бабы/722-бабында» forms."""
    from korgan import claim_quality_hotfix, document_quality, professional_claim_finalizer
    from korgan import kazakh_legal_bridge

    article = re.compile(
        r"(?i)(?:(?:стать[ьяиеёю]\w*|ст\.)\s*\d+(?:-\d+)?|"
        r"\b\d+(?:-\d+)?\s*[-–]?\s*ба[пб](?:ы|тың|тің|та|те|қа|ке|пен|ында|інде|ынан|інен)?\b)"
    )
    reference = re.compile(
        r"(?P<article>\d+(?:-\d+)?)\s*[-–]?\s*ба[пб](?:ы|тың|тің|та|те|қа|ке|пен|ында|інде|ынан|інен)?"
        r"(?:\s*(?:ның|нің)?\s*(?P<part>\d+)\s*[-–]?\s*(?:тармағ\w*|бөліг\w*))?",
        re.IGNORECASE,
    )

    kazakh_legal_bridge._ARTICLE_BILINGUAL = article
    kazakh_legal_bridge._KK_REFERENCE_RE = reference
    document_quality._ARTICLE_RE = article
    claim_quality_hotfix._ARTICLE_TOKEN_RE = article
    professional_claim_finalizer._ARTICLE_RE = article
