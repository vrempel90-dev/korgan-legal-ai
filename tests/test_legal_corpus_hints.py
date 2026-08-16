from korgan.legal_corpus import PROVISION_HINTS, extract_cited_articles


def test_extract_consultation_articles() -> None:
    text = "Применимы статья 353 ГК РК и ст. 29 ГПК РК."
    assert extract_cited_articles(text) == ["ст. 353 ГК", "ст. 29 ГПК"]


def test_hint_registry_points_to_official_sources_but_does_not_mark_verified() -> None:
    hint = PROVISION_HINTS["ст. 353 ГК"]
    assert hint.article == "353"
    assert "adilet.zan.kz" in hint.source_url
    assert not hasattr(hint, "as_verified_claim")
