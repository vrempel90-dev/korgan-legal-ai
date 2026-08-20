from pathlib import Path


def test_legacy_upload_copy_does_not_push_claim_after_every_document() -> None:
    source = Path("korgan/bot.py").read_text(encoding="utf-8")
    assert "можно добавить ещё документы или попросить подготовить иск" not in source
    assert "Готовый Word-файл выдаётся только после подтверждения оплаты" in source
