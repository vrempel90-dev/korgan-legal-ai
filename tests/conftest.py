from __future__ import annotations

from datetime import date as _RealDate

import pytest


class _LegacyCorpusFixtureDate(_RealDate):
    @classmethod
    def today(cls) -> "_LegacyCorpusFixtureDate":
        # These two legacy filing fixtures were created with loaded_at=2026-08-22.
        # Freeze only their corpus-health clock to the last valid day so they
        # keep testing filing/finalizer behaviour instead of expiring by wall
        # clock. Dedicated corpus-freshness tests remain untouched.
        return cls(2026, 8, 29)


@pytest.fixture(autouse=True)
def _freeze_legacy_filing_fixture_clock(request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch):
    filename = request.node.path.name
    if filename not in {
        "test_claim_filing_accuracy_all_cases.py",
        "test_professional_claim_finalizer.py",
    }:
        return

    import korgan.claim_corpus_health as corpus_health

    monkeypatch.setattr(corpus_health, "date", _LegacyCorpusFixtureDate)
