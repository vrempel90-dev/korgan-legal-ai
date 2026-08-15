from __future__ import annotations

from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse

import yaml

from korgan_legal_ai.corpus.models import CorpusStatus, LegalNorm
from korgan_legal_ai.corpus.repository import LegalNormRepository

CANONICAL_HOST = "adilet.zan.kz"


def load_canonical_seed(path: str | Path, repository: LegalNormRepository) -> list[LegalNorm]:
    payload = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    reviewed_by = payload["reviewed_by"]
    reviewed_at = datetime.fromisoformat(payload["reviewed_at"])
    loaded: list[LegalNorm] = []
    for raw in payload["norms"]:
        if urlparse(raw["source_url"]).hostname != CANONICAL_HOST:
            raise ValueError("Canonical seed source must be adilet.zan.kz")
        norm = LegalNorm(
            **raw,
            status=CorpusStatus.CANONICAL,
            reviewed_by=reviewed_by,
            reviewed_at=reviewed_at,
        )
        repository.upsert(norm)
        loaded.append(norm)
    return loaded
