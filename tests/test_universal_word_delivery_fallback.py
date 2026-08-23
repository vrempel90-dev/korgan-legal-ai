from __future__ import annotations

import asyncio
from types import SimpleNamespace

from aiogram.fsm.context import FSMContext
from aiogram.fsm.storage.base import StorageKey
from aiogram.fsm.storage.memory import MemoryStorage

from korgan import bot as base_bot
from korgan.legal_types import (
    ContractClause,
    ContractDraft,
    ContractSection,
    LegalResearch,
    VerificationStatus,
)
from korgan.request_scope import start_new_document_request
from korgan.universal_document_runtime import _send_contract
from korgan.universal_word_quality_guard import TARGET_READY_SCORE


class _FakeBot:
    async def send_chat_action(self, _chat_id: int, _action: str) -> None:
        return None


class _FakeMessage:
    def __init__(self) -> None:
        self.text = (
            "Подготовить договор оказания консультационных услуг между ТОО А и ТОО Б. "
            "Стоимость 500 000 тенге, срок один месяц, оплата после оказания услуг."
        )
        self.from_user = SimpleNamespace(is_bot=False)
        self.chat = SimpleNamespace(id=1001)
        self.bot = _FakeBot()
        self.documents: list[tuple[object, str]] = []
        self.answers: list[str] = []

    async def answer(self, text: str, **_kwargs) -> None:
        self.answers.append(text)

    async def answer_document(self, document, *, caption: str = "", **_kwargs) -> None:
        self.documents.append((document, caption))


class _BelowTargetContractService:
    async def research_contract(self, _context: str, language: str = "ru") -> LegalResearch:
        return LegalResearch(
            status=VerificationStatus.NEEDS_VERIFICATION,
            applicable_law=[],
            procedural_requirements=[],
            verified_claims=[],
            unverified_claims=["Материально-правовая основа не подтверждена source-bound источником."],
            source_urls=[],
            notes=[],
        )

    async def draft_contract(
        self,
        _context: str,
        _research: LegalResearch,
        language: str = "ru",
    ) -> ContractDraft:
        return ContractDraft(
            status=VerificationStatus.NEEDS_VERIFICATION,
            contract_type="Договор оказания услуг",
            title="ДОГОВОР ОКАЗАНИЯ УСЛУГ",
            place_and_date="г. Астана",
            party_a=["ТОО А — Заказчик"],
            party_b=["ТОО Б — Исполнитель"],
            preamble=["Стороны заключили настоящий договор о нижеследующем."],
            sections=[
                ContractSection(
                    heading="Предмет договора",
                    clauses=[ContractClause(text="Исполнитель оказывает консультационные услуги.")],
                ),
                ContractSection(
                    heading="Цена и порядок оплаты",
                    clauses=[ContractClause(text="Стоимость услуг составляет 500 000 тенге.")],
                ),
            ],
            requisites_a=["ТОО А"],
            requisites_b=["ТОО Б"],
            verification_notes=["Правовое основание требует дополнительной проверки."],
            source_urls=[],
        )


def test_below_target_contract_still_delivers_preliminary_word() -> None:
    async def scenario() -> None:
        storage = MemoryStorage()
        state = FSMContext(
            storage=storage,
            key=StorageKey(bot_id=1, chat_id=1001, user_id=1001),
        )
        await state.set_data({"language": "ru", "facts": [], "documents": []})
        await start_new_document_request(state, kind="contract", mode="main")

        previous_service = base_bot.service
        base_bot.service = _BelowTargetContractService()  # type: ignore[assignment]
        message = _FakeMessage()
        try:
            await _send_contract(message, state)  # type: ignore[arg-type]
        finally:
            base_bot.service = previous_service
            await storage.close()

        assert TARGET_READY_SCORE == 10.0
        assert len(message.documents) == 1
        document, caption = message.documents[0]
        assert getattr(document, "filename", "") == "KORGAN_dogovor.docx"
        assert "PRELIMINARY" in caption
        assert "10.0/10" in caption
        assert not message.answers

    asyncio.run(scenario())
