from __future__ import annotations

import asyncio
from types import SimpleNamespace

from korgan.pretrial_runtime import _Intent, _Waiting
from korgan.ui import documents_menu


class _State:
    def __init__(self, mode: str = "main") -> None:
        self.mode = mode

    async def get_data(self) -> dict[str, str]:
        return {"mode": self.mode}


def _message(text: str) -> SimpleNamespace:
    return SimpleNamespace(text=text)


def _callbacks(language: str) -> list[str | None]:
    menu = documents_menu(language)
    return [button.callback_data for row in menu.inline_keyboard for button in row]


def test_documents_menu_contains_pretrial_in_both_languages() -> None:
    assert "doc:pretrial" in _callbacks("ru")
    assert "doc:pretrial" in _callbacks("kk")


def test_pretrial_router_does_not_steal_claim_when_case_mentions_prior_pretrial() -> None:
    text = (
        "Досудебная претензия об оплате задолженности направлена ответчику 10 августа 2026 года. "
        "Основная задолженность 600 000 тенге. Подготовь исковое заявление о взыскании 600 000 тенге "
        "задолженности по договору оказания услуг."
    )
    result = asyncio.run(_Intent()(_message(text), _State("main")))
    assert result is False


def test_waiting_pretrial_flow_also_yields_to_explicit_claim_request() -> None:
    text = "Подготовь исковое заявление о взыскании задолженности по договору оказания услуг."
    result = asyncio.run(_Waiting()(_message(text), _State("pretrial_waiting")))
    assert result is False


def test_explicit_pretrial_request_still_routes_to_pretrial() -> None:
    text = "Подготовь досудебную претензию о взыскании задолженности по договору оказания услуг."
    result = asyncio.run(_Intent()(_message(text), _State("main")))
    assert result is True
