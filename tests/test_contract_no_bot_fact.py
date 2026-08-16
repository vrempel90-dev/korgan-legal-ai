from pathlib import Path


def test_fact_saver_rejects_bot_authored_messages() -> None:
    source = Path("korgan/reply_menu_handlers.py").read_text(encoding="utf-8")
    start = source.index("async def _save_user_text_as_facts")
    end = source.index("async def _send_claim_as_word")
    block = source[start:end]
    assert "message.from_user" in block
    assert "message.from_user.is_bot" in block
