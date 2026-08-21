from __future__ import annotations

import inspect

import korgan.document_menu_entry as document_menu_entry
import korgan.strict_bot as strict_bot


def test_document_reply_button_is_navigation_in_both_languages() -> None:
    assert document_menu_entry.is_document_menu_button("📄 Документ") is True
    assert document_menu_entry.is_document_menu_button("📄 Құжат") is True
    assert document_menu_entry.is_document_menu_button("Ответчик должен 600 000 тенге") is False


def test_priority_document_router_is_registered_before_all_request_consumers() -> None:
    source = inspect.getsource(strict_bot.main)
    priority = source.index("dp.include_router(document_menu_entry_router)")

    # Any of these routers can legitimately consume free text depending on the
    # active FSM mode. Navigation must run before every one of them so the first
    # tap can never become claim/pretrial/response/contract/payment input.
    for router_call in (
        "dp.include_router(payment_router)",
        "dp.include_router(kazakh_router)",
        "dp.include_router(document_category_router)",
        "dp.include_router(pretrial_response_router)",
        "dp.include_router(pretrial_router)",
        "dp.include_router(universal_claim_router)",
        "dp.include_router(universal_document_router)",
        "dp.include_router(reply_menu_router)",
        "dp.include_router(consultation_quota_router)",
        "dp.include_router(base_bot.router)",
    ):
        assert priority < source.index(router_call), router_call


def test_priority_handler_only_opens_menu_and_never_generates_document() -> None:
    source = inspect.getsource(document_menu_entry.open_document_menu)
    assert "documents_menu(" in source
    assert "message.answer(" in source
    assert "answer_document(" not in source
    assert "_generate" not in source
    assert "_send_claim" not in source
    assert "_send_contract" not in source
