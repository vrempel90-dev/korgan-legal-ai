"""Dated corpus of verified provision texts.

A provision quoted from model memory is a quotation of whatever the training
data contained, which for amended articles is the old wording. Часть 2 статьи 166
ГПК РК shipped in quotation marks in its pre-amendment form for exactly that
reason: the article number was checked, the sentence was recalled.

So a wording may only be quoted if it exists here, and every record carries
where it came from and when it was checked. Records are data, not code:
`korgan/data/provisions.json` is meant to be refreshed on a schedule, and the
`verified_on` date of each record is shown to the user rather than hidden.

Two record levels, because they license different things:

* ``VERIFIED``  — the text was read from the official source on ``verified_on``.
  It may be quoted verbatim.
* ``REPORTED``  — the text reached KORGAN some other way (operator entry, user
  correction) and has not been read from the official source. It may be used,
  but never silently: the document carries a visible verification marker.

Anything absent from the corpus may not be quoted or paraphrased with
confidence at all — only the article number, plus NEEDS_VERIFICATION.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import date
from functools import lru_cache
from pathlib import Path

CORPUS_PATH = Path(__file__).with_name("data") / "provisions.json"

VERIFIED = "VERIFIED"
REPORTED = "REPORTED"


@dataclass(frozen=True, slots=True)
class ProvisionRecord:
    """One provision text, with its provenance."""

    act: str
    act_aliases: tuple[str, ...]
    article: str
    part: str
    text: str
    source_url: str
    verified_on: str
    level: str
    provenance: str

    @property
    def key(self) -> str:
        return provision_key(self.act, self.article, self.part)

    @property
    def citable_verbatim(self) -> bool:
        return self.level == VERIFIED

    def reference(self) -> str:
        part = f"часть {self.part} " if self.part else ""
        return f"{part}статьи {self.article} {self.act}".strip()


def normalize_text(value: str) -> str:
    """Normalize for symmetric comparison: spacing, ё, quote glyphs, dashes."""
    text = (value or "").replace("ё", "е").replace("Ё", "Е")
    text = text.replace("«", '"').replace("»", '"').replace("“", '"').replace("”", '"')
    text = text.replace("—", "-").replace("–", "-")
    text = re.sub(r"\s+", " ", text)
    return text.strip().lower()


def provision_key(act: str, article: str, part: str) -> str:
    return f"{normalize_text(act)}|{article.strip()}|{(part or '').strip()}"


@lru_cache(maxsize=1)
def _load() -> tuple[dict[str, ProvisionRecord], str]:
    if not CORPUS_PATH.exists():
        return {}, ""
    raw = json.loads(CORPUS_PATH.read_text(encoding="utf-8"))
    records: dict[str, ProvisionRecord] = {}
    for item in raw.get("provisions", []):
        record = ProvisionRecord(
            act=str(item["act"]),
            act_aliases=tuple(str(x) for x in item.get("act_aliases", [])),
            article=str(item["article"]),
            part=str(item.get("part", "")),
            text=str(item["text"]),
            source_url=str(item.get("source_url", "")),
            verified_on=str(item.get("verified_on", "")),
            level=str(item.get("level", REPORTED)),
            provenance=str(item.get("provenance", "")),
        )
        records[record.key] = record
        for alias in record.act_aliases:
            records.setdefault(provision_key(alias, record.article, record.part), record)
    return records, str(raw.get("corpus_checked_on", ""))


def reload_corpus() -> None:
    """Drop the cache — used by tests and after a corpus refresh."""
    _load.cache_clear()


def corpus_checked_on() -> str:
    """Date the corpus as a whole was last reconciled with official sources."""
    return _load()[1]


def lookup(act: str, article: str, part: str = "") -> ProvisionRecord | None:
    records, _ = _load()
    return records.get(provision_key(act, article, part))


def all_records() -> list[ProvisionRecord]:
    records, _ = _load()
    return sorted(set(records.values()), key=lambda record: (record.act, record.article, record.part))


def stale_records(*, today: date | None = None, max_age_days: int = 180) -> list[ProvisionRecord]:
    """Records whose verification is old enough to need re-checking."""
    reference = today or date.today()
    stale: list[ProvisionRecord] = []
    for record in all_records():
        try:
            checked = date.fromisoformat(record.verified_on)
        except ValueError:
            stale.append(record)
            continue
        if (reference - checked).days > max_age_days:
            stale.append(record)
    return stale
