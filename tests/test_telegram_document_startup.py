from __future__ import annotations

import pytest

from korgan_legal_ai.telegram.main import main


def test_document_capable_startup_requires_openai_key_before_connecting(monkeypatch, tmp_path) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "123456:TEST")
    monkeypatch.setenv("DATABASE_URL", "postgresql+psycopg://postgres@localhost/korgan")
    monkeypatch.setenv("TELEGRAM_SESSION_MASTER_KEY", "not-used-before-openai-check")
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)

    with pytest.raises(RuntimeError, match="OPENAI_API_KEY"):
        main()
