from __future__ import annotations

import asyncio
from types import SimpleNamespace
from urllib.parse import unquote

from aiogram import Bot
from aiogram.types import BufferedInputFile

from korgan import consultation_cta, localized_transport, pretrial
from korgan.additive_legal_guard import _pretrial_basis_coverage
from korgan.consultation_cta import (
    WHATSAPP_NUMBER,
    ConsultationReference,
    build_consultation_reference,
    consultation_keyboard,
    consultation_text,
    is_generated_document,
    whatsapp_url,
)
from korgan.legal_types import LegalResearch, VerificationStatus
from korgan.localized_transport import LocalizedClientSafeBot
from korgan.material_law_guard import (
    has_material_basis,
    has_material_verified,
    is_material_law_line,
    requires_material_law,
)
from korgan.pretrial import PretrialDraft, pretrial_release_blockers

GPK_113 = (
    "Расходы по оплате помощи представителя возмещаются в установленных пределах. "
    "[основание: статья 113 ГПК РК; текст нормы: суд присуждает расходы по оплате помощи представителя; "
    "источник: https://adilet.zan.kz/rus/docs/K1500000377]"
)
GK_272 = (
    "Должник обязан исполнить денежное обязательство надлежащим образом. "
    "[основание: статья 272 ГК РК; текст нормы: обязательство должно исполняться надлежащим образом; "
    "источник: https://adilet.zan.kz/rus/docs/K940001000_]"
)
CLIENT_CASE = (
    "Между ТОО Gnatho.center и ТОО Easy Way Innovation сложились договорные отношения по оказанию услуг. "
    "У Easy Way Innovation образовалась задолженность за оказанные услуги 4 025 000 тенге. "
    "Нужно потребовать погашение основного долга."
)


def _research(*verified: str) -> LegalResearch:
    return LegalResearch(
        status=VerificationStatus.VERIFIED,
        applicable_law=[],
        procedural_requirements=[],
        verified_claims=list(verified),
        unverified_claims=[],
        source_urls=["https://adilet.zan.kz/rus/docs/K1500000377"],
        notes=[],
    )


def _pretrial(legal_basis: list[str] | None = None) -> PretrialDraft:
    return PretrialDraft(
        status=VerificationStatus.VERIFIED,
        title="Претензия о добровольном погашении задолженности",
        sender=["ТОО Gnatho.center"],
        recipient=["ТОО Easy Way Innovation"],
        facts=["Задолженность за оказанные услуги составляет 4 025 000 тенге."],
        legal_basis=list(legal_basis or []),
        demands=["Уплатить основной долг в размере 4 025 000 тенге."],
        deadline="в разумный срок с момента получения претензии",
        consequences=["При неурегулировании спора кредитор вправе обратиться за судебной защитой."],
        attachments=[],
        verification_notes=[],
        source_urls=[],
    )


def test_gpk_representative_cost_rule_is_not_material_law() -> None:
    assert not is_material_law_line(GPK_113)
    assert not has_material_verified(_research(GPK_113))
    assert not has_material_basis(["Расходы представителя регулируются статьей 113 ГПК РК."])


def test_civil_code_obligation_rule_is_material_law() -> None:
    assert is_material_law_line(GK_272)
    assert has_material_verified(_research(GK_272))
    assert has_material_basis(["Обязательство подлежит надлежащему исполнению. Правовое основание: статья 272 ГК РК."])


def test_contractual_debt_requires_material_law() -> None:
    assert requires_material_law(CLIENT_CASE)


def test_client_regression_gpk_113_alone_cannot_release_debt_pretrial(monkeypatch) -> None:
    research = _research(GPK_113)
    draft = _pretrial(["Расходы представителя регулируются статьей 113 ГПК РК."])
    missing = _pretrial_basis_coverage(CLIENT_CASE, draft, research)

    assert "погашение договорной задолженности" in missing
    assert any("VERIFIED" in note for note in draft.verification_notes)

    monkeypatch.setattr(pretrial, "review_lines", lambda *args, **kwargs: SimpleNamespace(blocking=[]))
    blockers = pretrial_release_blockers(draft, research, CLIENT_CASE)
    assert any("материаль" in item.lower() for item in blockers)


def test_client_regression_verified_material_rule_is_restored_into_pretrial(monkeypatch) -> None:
    research = _research(GPK_113, GK_272)
    draft = _pretrial(["Расходы представителя регулируются статьей 113 ГПК РК."])
    missing = _pretrial_basis_coverage(CLIENT_CASE, draft, research)

    assert "погашение договорной задолженности" not in missing
    assert any("статья 272 ГК РК" in line for line in draft.legal_basis)

    monkeypatch.setattr(pretrial, "review_lines", lambda *args, **kwargs: SimpleNamespace(blocking=[]))
    blockers = pretrial_release_blockers(draft, research, CLIENT_CASE)
    assert not [item for item in blockers if "материаль" in item.lower()]


def test_whatsapp_cta_identifies_exact_document_without_personal_data() -> None:
    reference = ConsultationReference(
        case_id="KRG-A1B2C3",
        document_id="KRG-A1B2C3-D02",
        document_number=2,
        document_label="Досудебная претензия",
    )
    url = whatsapp_url("ru", reference)
    assert url.startswith(f"https://wa.me/{WHATSAPP_NUMBER}?text=")
    assert "+" not in url
    assert " " not in url
    assert "700-500" not in url

    decoded = unquote(url)
    assert "KRG-A1B2C3" in decoded
    assert "KRG-A1B2C3-D02" in decoded
    assert "Досудебная претензия" in decoded
    assert "ИИН" not in decoded
    assert "БИН" not in decoded

    text = consultation_text("ru", reference)
    assert "конкретному документу" in text.lower()
    assert reference.document_id in text
    assert reference.case_id in text
    assert WHATSAPP_NUMBER not in text
    assert "+7 700" not in text

    keyboard = consultation_keyboard("ru", reference)
    yes = keyboard.inline_keyboard[0][0]
    no = keyboard.inline_keyboard[1][0]
    assert yes.text == "💬 Консультация по этому документу"
    assert yes.url == url
    assert no.text == "Не сейчас"
    assert no.callback_data == "consultation:no"


def test_document_references_share_case_and_increment_until_case_is_cleared(monkeypatch) -> None:
    class FakeState:
        def __init__(self) -> None:
            self.data: dict[str, object] = {"language": "ru"}

        async def get_data(self) -> dict[str, object]:
            return dict(self.data)

        async def update_data(self, **kwargs: object) -> None:
            self.data.update(kwargs)

    state = FakeState()
    ids = iter(["a1b2c3", "d4e5f6"])
    monkeypatch.setattr(consultation_cta, "current_fsm_state", lambda: state)
    monkeypatch.setattr(consultation_cta.secrets, "token_hex", lambda _n: next(ids))

    async def scenario() -> tuple[ConsultationReference, ConsultationReference, ConsultationReference]:
        first = await build_consultation_reference(
            BufferedInputFile(b"doc", filename="KORGAN_dosudebnaya_pretenziya.docx"), "ru"
        )
        second = await build_consultation_reference(
            BufferedInputFile(b"doc", filename="KORGAN_iskovoe_zayavlenie.docx"), "ru"
        )
        # Simulates /clear: the real clear handler replaces the FSM data and
        # therefore removes both consultation reference keys.
        state.data = {"language": "ru", "documents": [], "facts": [], "mode": "main"}
        third = await build_consultation_reference(
            BufferedInputFile(b"doc", filename="KORGAN_dogovor.docx"), "ru"
        )
        return first, second, third

    first, second, third = asyncio.run(scenario())
    assert first.case_id == second.case_id == "KRG-A1B2C3"
    assert first.document_id == "KRG-A1B2C3-D01"
    assert second.document_id == "KRG-A1B2C3-D02"
    assert first.document_label == "Досудебная претензия"
    assert second.document_label == "Исковое заявление"
    assert third.case_id == "KRG-D4E5F6"
    assert third.document_id == "KRG-D4E5F6-D01"
    assert third.document_label == "Договор"


def test_only_generated_korgan_documents_trigger_cta() -> None:
    assert is_generated_document(BufferedInputFile(b"doc", filename="KORGAN_iskovoe_zayavlenie.docx"))
    assert is_generated_document(BufferedInputFile(b"doc", filename="KORGAN_dosudebnaya_pretenziya.pdf"))
    assert not is_generated_document(BufferedInputFile(b"doc", filename="dogovor_klienta.docx"))
    assert not is_generated_document("file_id_from_telegram")


def test_localized_transport_sends_one_cta_for_the_exact_generated_document(monkeypatch) -> None:
    sent_documents: list[str] = []
    ctas: list[tuple[int, str, str]] = []

    async def fake_send_document(self, chat_id, document, *args, **kwargs):
        sent_documents.append(str(getattr(document, "filename", "")))
        return SimpleNamespace(message_id=1)

    async def fake_cta(bot, chat_id, language="ru", *, document=None):
        ctas.append((int(chat_id), str(language), str(getattr(document, "filename", ""))))
        return SimpleNamespace(message_id=2)

    monkeypatch.setattr(Bot, "send_document", fake_send_document)
    monkeypatch.setattr(localized_transport, "send_consultation_cta", fake_cta)

    bot = LocalizedClientSafeBot(token="123456789:ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghi")

    async def scenario() -> None:
        await bot.send_document(
            123,
            BufferedInputFile(b"not-a-real-docx", filename="KORGAN_dogovor.docx"),
            caption="✅ Договор сформирован в Word (.docx).",
        )
        await bot.session.close()

    asyncio.run(scenario())
    assert sent_documents == ["KORGAN_dogovor.docx"]
    assert ctas == [(123, "ru", "KORGAN_dogovor.docx")]
