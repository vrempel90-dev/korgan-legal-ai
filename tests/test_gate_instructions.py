"""Replies on the verification-gate step are classified before they are parsed.

The bug: the gate blocked a document over статья 616 ГК РК and told the user
that marking it NEEDS_VERIFICATION was permissible. The user wrote exactly that
back and got «не получилось распознать ни одно из запрошенных полей» — the field
parser had been handed a command. The only ways out were restarting the case or
a human lawyer.
"""

from __future__ import annotations

import asyncio

import pytest

from korgan import bot as korgan_bot
from korgan.citation_audit import ProvisionReference, extract_references
from korgan.document_release import review_lines
from korgan.gate_instructions import (
    ReplyIntent,
    apply_citation_waiver,
    classify_reply,
)
from korgan.legal_types import ClaimDraft, VerificationStatus
from tests.test_field_intake import Dialog, FakeMessage, run

_ISSUES = [
    "статья 616 ГК РК: текста нормы нет в проверенном корпусе KORGAN — содержание не "
    "подтверждено; допустимо указать только номер статьи и пометить NEEDS_VERIFICATION",
]

_BLOCKING_BASIS = (
    "В силу статьи 616 ГК РК заказчик обязан оплатить выполненные работы в полном объёме."
)


def _blocked_draft() -> ClaimDraft:
    return ClaimDraft(
        status=VerificationStatus.NEEDS_VERIFICATION,
        title="ИСКОВОЕ ЗАЯВЛЕНИЕ о взыскании задолженности",
        court="СМЭС города Алматы",
        claimant=["Иванов Иван Иванович, ИИН 990303300123, г. Алматы, ул. Абая, д. 15"],
        defendant=["Петров Пётр Петрович, г. Астана, ул. Кенесары, д. 40"],
        price_of_claim="800 000 тенге",
        facts=["Между сторонами заключён договор подряда от 12.01.2026."],
        legal_basis=[_BLOCKING_BASIS],
        requests=["Взыскать с ответчика 800 000 тенге."],
        attachments=["Копия договора подряда от 12.01.2026"],
        verification_notes=[],
        source_urls=[],
        state_duty="8 000 тенге",
    )


# --- classification --------------------------------------------------------


@pytest.mark.parametrize(
    "text",
    [
        "продолжай, статью 616 ГК РК пометь как NEEDS_VERIFICATION",
        "Оставь статью 616 ГК РК с пометкой NEEDS_VERIFICATION и сформируй документ",
        "пометь эту статью 616 ГК РК как needs_verification и продолжи",
        "согласен, ст. 616 ГК РК оставь непроверенной",
    ],
)
def test_instructions_about_a_listed_defect_are_recognised(text: str) -> None:
    decision = classify_reply(text, gate_issues=_ISSUES)
    assert decision.intent is ReplyIntent.ACCEPT_NEEDS_VERIFICATION
    assert decision.targets and decision.targets[0].article == "616"


def test_bare_continue_applies_to_everything_the_gate_listed() -> None:
    decision = classify_reply("продолжай", gate_issues=_ISSUES)
    assert decision.intent is ReplyIntent.ACCEPT_NEEDS_VERIFICATION
    assert decision.applies_to_all
    assert [ref.article for ref in decision.targets] == ["616"]


def test_removal_instruction_is_distinguished_from_a_waiver() -> None:
    decision = classify_reply("убери статью 616 ГК РК из документа", gate_issues=_ISSUES)
    assert decision.intent is ReplyIntent.DROP_PROVISION


def test_case_data_is_still_treated_as_case_data() -> None:
    decision = classify_reply(
        "Дата рождения истца: 03.03.1999", gate_issues=_ISSUES, pending_fields=["дата рождения истца"]
    )
    assert decision.intent is ReplyIntent.FIELD_DATA


def test_instruction_about_an_unlisted_article_is_kept_separate() -> None:
    decision = classify_reply("пометь статью 999 ГК РК как NEEDS_VERIFICATION", gate_issues=_ISSUES)
    assert not decision.targets
    assert [ref.article for ref in decision.unknown_targets] == ["999"]


def test_a_question_is_not_mistaken_for_an_instruction() -> None:
    decision = classify_reply("а почему нельзя сослаться на эту статью?", gate_issues=_ISSUES)
    assert decision.intent is ReplyIntent.QUESTION


# --- applying the waiver ---------------------------------------------------


def test_waiver_stops_the_document_asserting_the_provision() -> None:
    target = ProvisionReference("ГК РК", "616")
    lines, applied = apply_citation_waiver([_BLOCKING_BASIS], [target])
    assert applied == [target]
    assert "[ТРЕБУЕТ ПРОВЕРКИ" in lines[0]
    assert "содержание нормы не утверждается" in lines[0]
    # The article number survives — only the claim about its content does not.
    assert extract_references(lines[0])


def test_waiver_removes_a_verbatim_quotation() -> None:
    quoted = (
        "Согласно статье 616 ГК РК «заказчик обязан уплатить подрядчику обусловленную цену "
        "после окончательной сдачи результатов работы»."
    )
    lines, _ = apply_citation_waiver([quoted], [ProvisionReference("ГК РК", "616")])
    assert "«" not in lines[0].replace("«Стороны»", "")
    assert "содержание нормы не воспроизводится" in lines[0]


def test_waiver_unblocks_the_release_gate() -> None:
    draft = _blocked_draft()
    assert not review_lines([draft.title, *draft.legal_basis]).released

    lines, _ = apply_citation_waiver(draft.legal_basis, [ProvisionReference("ГК РК", "616")])
    assert review_lines([draft.title, *lines]).released


def test_waiver_is_idempotent() -> None:
    target = ProvisionReference("ГК РК", "616")
    once, _ = apply_citation_waiver([_BLOCKING_BASIS], [target])
    twice, applied = apply_citation_waiver(once, [target])
    assert twice == once
    assert not applied


# --- the dialogue ----------------------------------------------------------


class GateDialog(Dialog):
    """Drives the gate step with a pre-blocked draft in state."""

    async def block(self) -> list[str]:
        message = FakeMessage("")
        draft = _blocked_draft()
        report = review_lines(korgan_bot._claim_release_lines(draft))
        assert not report.released
        await korgan_bot._enter_verification_gate(message, self.state, draft, report)
        self.transcript.extend(("bot", reply) for reply in message.sent)
        return message.sent


def test_the_reported_scenario_now_resolves(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(korgan_bot, "service", object())
    sent_documents: list[str] = []

    async def scenario() -> None:
        dialog = GateDialog()
        await dialog.start_case()
        blocked = await dialog.block()
        assert "616" in " ".join(blocked)
        assert (await dialog.state.get_data())["mode"] == "verification_gate"

        message = FakeMessage("пометь статью 616 ГК РК как NEEDS_VERIFICATION и продолжи")

        async def capture(document, **kwargs):
            sent_documents.append(kwargs.get("caption", ""))

        message.answer_document = capture  # type: ignore[attr-defined]
        dialog.transcript.append(("user", message.text))
        data = await dialog.state.get_data()
        await korgan_bot._handle_verification_gate_reply(message, dialog.state, data)
        dialog.transcript.extend(("bot", reply) for reply in message.sent)

        assert message.sent, "бот промолчал"
        assert "не получилось распознать" not in " ".join(message.sent).lower()
        assert "Принято" in message.sent[0]
        assert sent_documents, "документ так и не был выдан"

        data = await dialog.state.get_data()
        assert data["mode"] == "main"

    run(scenario())


def test_unclear_instruction_gets_a_conversational_reply_not_the_field_template(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(korgan_bot, "service", object())

    async def scenario() -> None:
        dialog = GateDialog()
        await dialog.start_case()
        await dialog.block()

        message = FakeMessage("сделай что-нибудь с этим")
        data = await dialog.state.get_data()
        await korgan_bot._handle_verification_gate_reply(message, dialog.state, data)

        reply = " ".join(message.sent)
        assert "не получилось распознать" not in reply.lower()
        assert "ни одно из запрошенных полей" not in reply.lower()
        assert "Не понял, что сделать" in reply

    run(scenario())


def test_instruction_about_an_unlisted_article_says_so(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(korgan_bot, "service", object())

    async def scenario() -> None:
        dialog = GateDialog()
        await dialog.start_case()
        await dialog.block()

        message = FakeMessage("пометь статью 999 ГК РК как NEEDS_VERIFICATION")
        data = await dialog.state.get_data()
        await korgan_bot._handle_verification_gate_reply(message, dialog.state, data)

        reply = " ".join(message.sent)
        assert "В замечаниях не было" in reply
        assert "999" in reply

    run(scenario())


def test_case_data_on_the_gate_step_still_reaches_the_field_parser(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(korgan_bot, "service", object())

    async def scenario() -> None:
        dialog = GateDialog()
        await dialog.start_case()
        await dialog.block()
        await dialog.state.update_data(pending_fields=["дата рождения истца"])

        message = FakeMessage("Дата рождения истца: 03.03.1999")
        data = await dialog.state.get_data()
        await korgan_bot._handle_verification_gate_reply(message, dialog.state, data)

        facts = (await dialog.state.get_data())["facts"]
        assert any("03.03.1999" in fact for fact in facts)

    run(scenario())
