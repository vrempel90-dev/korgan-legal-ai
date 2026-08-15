from korgan.rag import is_trusted_source


def test_adilet_is_trusted() -> None:
    assert is_trusted_source("https://adilet.zan.kz/rus/docs/K1400000226")


def test_non_adilet_is_not_trusted() -> None:
    assert not is_trusted_source("https://example.com/law")


def test_adilet_lookalike_is_not_trusted() -> None:
    assert not is_trusted_source("https://adilet.zan.kz.evil.example/law")
