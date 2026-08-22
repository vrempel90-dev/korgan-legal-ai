from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

import korgan.universal_claim_runtime as runtime
from korgan.claim_core_release import core_claim_release_blockers
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

    async def answer_document(self, document, **_kwargs) -> None:
        self.documents.append(document)


def _research(*verified: str) -> LegalResearch:
    return LegalResearch(
        status=VerificationStatus.VERIFIED,
        applicable_law=[],
        procedural_requirements=[],
        verified_claims=list(verified),
        unverified_claims=[],
        source_urls=["https://adilet.zan.kz/rus/docs/K990000409_"],
        notes=[],
    )


def _draft(*, requests: list[str], legal_basis: list[str]) -> ClaimDraft:
    return ClaimDraft(
        status=VerificationStatus.VERIFIED,
        title="Исковое заявление о взыскании задолженности",
        court="Районный суд",
        claimant=["Истец: Иванов И.И."],
        defendant=["Ответчик: ТОО Альфа"],
        price_of_claim="500 000 ₸",
        facts=["Ответчик не возвратил 500 000 тенге по договору."],
        legal_basis=legal_basis,
        requests=requests,
        attachments=["Договор"],
        verification_notes=[],
        source_urls=[],
    )


def test_core_gate_blocks_empty_or_placeholder_prositelnaia() -> None:
    research = _research(
        "Кредитор вправе требовать исполнения обязательства [основание: ст. 272 ГК РК; текст нормы: обязательства должны исполняться надлежащим образом; источник: https://adilet.zan.kz/rus/docs/K940001000_#z272]"
    )
    for requests in ([], ["[ТРЕБУЕТ УТОЧНЕНИЯ: требования к ответчику]"]):
        blockers = core_claim_release_blockers(
            research,
            _draft(requests=requests, legal_basis=["Правовое основание: ст. 272 ГК РК."]),
        )
        assert "не сформирована исполнимая просительная часть" in blockers


def test_core_gate_blocks_procedural_law_without_material_basis() -> None:
    research = _research(
        "Иск предъявляется по месту нахождения ответчика [основание: ст. 29 ГПК РК; текст нормы: иск предъявляется по месту нахождения ответчика; источник: https://adilet.zan.kz/rus/docs/K1500000377#z29]"
    )
    blockers = core_claim_release_blockers(
        research,
        _draft(
            requests=["Взыскать с ответчика 500 000 тенге."],
            legal_basis=["Подсудность: ст. 29 ГПК РК."],
        ),
    )
    assert "материально-правовая основа не подтверждена source-bound официальным источником" in blockers


@pytest.mark.parametrize(
    ("verified", "basis"),
    [
        (
            "Обязательство подлежит исполнению [основание: ст. 272 ГК РК; текст нормы: обязательства должны исполняться надлежащим образом; источник: https://adilet.zan.kz/rus/docs/K940001000_#z272]",
            "Правовое основание: ст. 272 ГК РК.",
        ),
        (
            "Права потребителя подлежат защите [основание: статья 42 Закона РК О защите прав потребителей; текст нормы: потребитель вправе обратиться за защитой; источник: https://adilet.zan.kz/rus/docs/Z100000274_#z42]",
            "Правовое основание: статья 42 Закона РК «О защите прав потребителей».",
        ),
        (
            "Работник вправе требовать выплату [основание: ст. 113 ТК РК; текст нормы: заработная плата выплачивается своевременно; источник: https://adilet.zan.kz/rus/docs/K1500000414#z113]",
            "Правовое основание: ст. 113 ТК РК.",
        ),
    ],
)
def test_core_gate_accepts_supported_source_bound_material_law(verified: str, basis: str) -> None:
    blockers = core_claim_release_blockers(
        _research(verified),
        _draft(requests=["Взыскать с ответчика 500 000 тенге."], legal_basis=[basis]),
    )
    assert blockers == []


def test_runtime_does_not_build_or_send_word_when_core_claim_is_incomplete(monkeypatch: pytest.MonkeyPatch) -> None:
    async def scenario() -> None:
        state = _State({"language": "ru"})
        request_id = await start_new_document_request(state, kind="claim", mode="main")
        message = _Message()
        research = _research(
            "Обязательство подлежит исполнению [основание: ст. 272 ГК РК; текст нормы: обязательства должны исполняться надлежащим образом; источник: https://adilet.zan.kz/rus/docs/K940001000_#z272]"
        )
        draft = _draft(
            requests=["[ТРЕБУЕТ УТОЧНЕНИЯ: требования к ответчику]"],
            legal_basis=["Правовое основание: ст. 272 ГК РК."],
        )

        monkeypatch.setattr(runtime, "enforce_legal_basis_fit", lambda _draft: [])
        monkeypatch.setattr(
            runtime,
            "_downgrade_unverified_citations_live",
            lambda _draft, _research: SimpleNamespace(
                citations=SimpleNamespace(blocking=[]),
                integrity=[],
            ),
        )

        built = False

        def forbidden_build(_draft):
            nonlocal built
            built = True
            raise AssertionError("DOCX must not be built for a core-incomplete claim")

        monkeypatch.setattr(runtime, "build_claim_docx", forbidden_build)
        await runtime._send_claim(
            message,
            state,
            context="Ответчик должен 500 000 тенге",
            research=research,
            draft=draft,
            request_id=request_id,
        )

        assert built is False
        assert message.documents == []
        assert len(message.answers) == 1
        assert "не выпущен в Word" in message.answers[0]
        assert "просительная часть" in message.answers[0]

    asyncio.run(scenario())


def test_second_claim_request_automatically_drops_first_case_context() -> None:
    async def scenario() -> None:
        state = _State(
            {
                "language": "ru",
                "terms_accepted": True,
                "privacy_consent": True,
            }
        )
        first_id = await start_new_document_request(state, kind="claim", mode="main")
        await state.update_data(
            facts=["СТАРОЕ ДЕЛО: долг 500 000 тенге"],
            documents=["old-contract.pdf"],
            accepted_provisions=["GK_RK_OBSHAYA:272"],
            claim_draft={"requests": ["Взыскать старый долг"]},
        )

        second_id = await start_new_document_request(
            state,
            kind="claim",
            mode="universal_claim_waiting",
        )
        data = await state.get_data()

        assert second_id != first_id
        assert data["facts"] == []
        assert data["documents"] == []
        assert data["consulted_articles"] == []
        assert "accepted_provisions" not in data
        assert "claim_draft" not in data
        assert data["language"] == "ru"
        assert data["terms_accepted"] is True
        assert data["privacy_consent"] is True

    asyncio.run(scenario())
