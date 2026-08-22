from __future__ import annotations

import asyncio
import subprocess
import sys
from types import SimpleNamespace

import pytest

from korgan.claim_core_release import core_claim_release_blockers
from korgan.claim_core_release_runtime import send_with_core_release_guard
from korgan.kazakh_legal_bridge import install_kazakh_legal_bridge
from korgan.legal_types import ClaimDraft, LegalResearch, VerificationStatus
from korgan.request_scope import start_new_document_request


class _State:
    def __init__(self, data: dict | None = None) -> None:
        self.data = dict(data or {})

    async def get_data(self) -> dict:
        return dict(self.data)

    async def set_data(self, data: dict) -> None:
        self.data = dict(data)

    async def update_data(self, **kwargs) -> None:
        self.data.update(kwargs)


class _Message:
    def __init__(self) -> None:
        self.answers: list[str] = []
        self.documents: list[object] = []

    async def answer(self, text: str, **_kwargs) -> None:
        self.answers.append(str(text))


def _research(line: str) -> LegalResearch:
    return LegalResearch(
        status=VerificationStatus.VERIFIED,
        applicable_law=[],
        procedural_requirements=[],
        verified_claims=[line],
        unverified_claims=[],
        source_urls=["https://adilet.zan.kz/rus/docs/K940001000_"],
        notes=[],
    )


def _draft(*, basis: str, request: str) -> ClaimDraft:
    return ClaimDraft(
        status=VerificationStatus.VERIFIED,
        title="Исковое заявление",
        court="Районный суд",
        claimant=["Истец"],
        defendant=["Ответчик"],
        price_of_claim="500 000 ₸",
        facts=["Долг не возвращён."],
        legal_basis=[basis],
        requests=[request],
        attachments=["Договор"],
        verification_notes=[],
        source_urls=[],
    )


def _gk272() -> str:
    return (
        "Обязательство подлежит исполнению [основание: ст. 272 ГК РК; "
        "текст нормы: «обязательства должны исполняться надлежащим образом в соответствии с условиями обязательства»; "
        "источник: https://adilet.zan.kz/rus/docs/K940001000_#z272]"
    )


def test_standard_proshu_prefix_remains_executable() -> None:
    blockers = core_claim_release_blockers(
        _research(_gk272()),
        _draft(basis="Основание: ст. 272 ГК РК.", request="Прошу: взыскать с ответчика 500 000 тенге."),
    )
    assert blockers == []


@pytest.mark.parametrize("norm_text", ["", "[ТРЕБУЕТ ПРОВЕРКИ]"])
def test_consumer_source_requires_usable_norm_text(norm_text: str) -> None:
    verified = (
        "Права потребителя защищаются [основание: статья 42 Закона РК О защите прав потребителей; "
        f"текст нормы: «{norm_text}»; источник: https://adilet.zan.kz/rus/docs/Z100000274_#z42]"
    )
    blockers = core_claim_release_blockers(
        _research(verified),
        _draft(
            basis="Основание: статья 42 Закона РК «О защите прав потребителей».",
            request="Взыскать с ответчика 500 000 тенге.",
        ),
    )
    assert "материально-правовая основа не подтверждена source-bound официальным источником" in blockers


def test_article_level_evidence_does_not_verify_required_part() -> None:
    blockers = core_claim_release_blockers(
        _research(_gk272()),
        _draft(
            basis="Основание: часть 2 статьи 272 ГК РК.",
            request="Взыскать с ответчика 500 000 тенге.",
        ),
    )
    assert "материально-правовая основа не подтверждена source-bound официальным источником" in blockers


def test_kazakh_material_basis_and_executable_relief_use_same_verified_core() -> None:
    install_kazakh_legal_bridge()
    verified = (
        "Қарыз алушы қарызды қайтаруға міндетті [основание: ст. 722 ГК РК; "
        "текст нормы: «заемщик обязан возвратить заимодателю полученную сумму займа в предусмотренный срок»; "
        "источник: https://adilet.zan.kz/rus/docs/K990000409_#z722]"
    )
    blockers = core_claim_release_blockers(
        _research(verified),
        _draft(
            basis="ҚР АК 722-бабы бойынша қарыз алушы қарызды қайтаруға міндетті.",
            request="Жауапкерден талап қоюшының пайдасына 500 000 теңге қарыз сомасын өндіріп алу.",
        ),
    )
    assert blockers == []


def test_guard_blocks_before_installed_sender_is_called(monkeypatch: pytest.MonkeyPatch) -> None:
    async def scenario() -> None:
        state = _State({"language": "ru"})
        request_id = await start_new_document_request(state, kind="claim", mode="main")
        message = _Message()
        called = False

        async def downstream(*_args, **_kwargs):
            nonlocal called
            called = True

        import korgan.claim_core_release_runtime as guard_runtime

        async def language(_state) -> str:
            return "ru"

        monkeypatch.setattr(guard_runtime, "request_is_current", guard_runtime.request_is_current)
        from korgan import bot as base_bot
        monkeypatch.setattr(base_bot, "_language", language)

        await send_with_core_release_guard(
            downstream,
            message,
            state,
            context="Долг",
            research=_research(_gk272()),
            draft=_draft(
                basis="Основание: ст. 272 ГК РК.",
                request="Прошу рассмотреть дело.",
            ),
            request_id=request_id,
        )

        assert called is False
        assert len(message.answers) == 1
        assert "не выпущен в Word" in message.answers[0]

    asyncio.run(scenario())


def test_strict_bot_installs_core_guard_on_actual_sender() -> None:
    script = (
        "import korgan.strict_bot; "
        "import korgan.universal_claim_runtime as r; "
        "assert getattr(r._send_claim, '_korgan_claim_core_release_guard', False)"
    )
    result = subprocess.run(
        [sys.executable, "-c", script],
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert result.returncode == 0, result.stderr or result.stdout
