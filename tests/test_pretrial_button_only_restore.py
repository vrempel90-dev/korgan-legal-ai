import asyncio

from korgan.claim_intent import is_claim_drafting_request
from korgan.pretrial import PretrialProductionService
from korgan.pretrial_runtime import _Waiting
from korgan.ui import documents_menu


def _texts(markup):
    return [button.text for row in markup.inline_keyboard for button in row]


def test_pretrial_button_present_ru_and_kk():
    assert "📨 Досудебная претензия" in _texts(documents_menu("ru"))
    assert "📨 Сотқа дейінгі талап" in _texts(documents_menu("kk"))


def test_pretrial_service_does_not_override_claim_methods():
    assert "research_case" not in PretrialProductionService.__dict__
    assert "draft_claim" not in PretrialProductionService.__dict__


class _State:
    async def get_data(self):
        return {"mode": "pretrial_waiting"}


class _Message:
    def __init__(self, text):
        self.text = text


def test_pretrial_waiting_never_swallows_explicit_claim_request():
    text = "Досудебная претензия направлена ответчику. Подготовь исковое заявление о взыскании 600 000 тенге."
    assert is_claim_drafting_request(text)
    assert asyncio.run(_Waiting()(_Message(text), _State())) is False


def test_pretrial_waiting_accepts_normal_pretrial_facts_after_button():
    text = "Ответчик должен 600 000 тенге по договору оказания услуг."
    assert asyncio.run(_Waiting()(_Message(text), _State())) is True
