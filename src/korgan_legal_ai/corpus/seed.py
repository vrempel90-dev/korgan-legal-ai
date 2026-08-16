from __future__ import annotations

from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse

import yaml

from korgan_legal_ai.corpus.models import CorpusStatus, LegalNorm
from korgan_legal_ai.corpus.repository import LegalNormRepository

CANONICAL_HOST = "adilet.zan.kz"


def load_canonical_seed(path: str | Path, repository: LegalNormRepository) -> list[LegalNorm]:
    """Load a reviewed batch of norms from a YAML file.

    A batch may declare ``next_review_date``. The shipped batches set it in the past on purpose:
    their wording was recorded before the curation tooling existed, and no named reviewer stands
    behind any individual entry. Marking the whole batch as due for re-verification means every one
    of them appears in ``list-pending`` and carries a visible warning in drafted documents, instead
    of looking freshly confirmed because it happens to sit in the canonical table.
    """
    payload = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    reviewed_by = payload["reviewed_by"]
    reviewed_at = datetime.fromisoformat(payload["reviewed_at"])
    batch_review_date = payload.get("next_review_date")
    loaded: list[LegalNorm] = []
    for raw in payload["norms"]:
        if urlparse(raw["source_url"]).hostname != CANONICAL_HOST:
            raise ValueError("Canonical seed source must be adilet.zan.kz")
        fields = dict(raw)
        fields.setdefault("next_review_date", batch_review_date)
        norm = LegalNorm(
            **fields,
            status=CorpusStatus.CANONICAL,
            reviewed_by=reviewed_by,
            reviewed_at=reviewed_at,
        )
        repository.upsert(norm)
        loaded.append(norm)
    return loaded
