from pathlib import Path


def test_contract_callback_waits_for_user_details() -> None:
    source = Path("korgan/reply_menu_handlers.py").read_text(encoding="utf-8")
    callback_start = source.index('async def document_contract_callback')
    callback_end = source.index('@router.callback_query(F.data == "menu:main")')
    callback_block = source[callback_start:callback_end]
    assert 'mode="contract_details"' in callback_block
    assert '_send_contract_as_word(callback.message, state)' not in callback_block
