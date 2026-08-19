from __future__ import annotations

import asyncio
from types import SimpleNamespace

from korgan.claim_pipeline_v2 import (
    ClaimPipelinePacket,
    ClaimPipelineV2Adapter,
    _augment_research_context,
    claim_pipeline_v2_mode,
)
from korgan.legal_types import ClaimDraft, LegalResearch, VerificationStatus


def _research() -> LegalResearch:
    return LegalResearch(
        status=VerificationStatus.VERIFIED,
        applicable_law=[],
        procedural_requirements=[],
        verified_claims=["Обязательство подтверждено [основание: ст. 272 ГК РК; текст нормы: тест; источник: https://adilet.zan.kz/rus/docs/K940001000_]"],
        unverified_claims=[],
        source_urls=["https://adilet.zan.kz/rus/docs/K940001000_"],
        notes=[],
    )


def _draft() -> ClaimDraft:
    return ClaimDraft(
        status=VerificationStatus.VERIFIED,
        title="Исковое заявление",
        court="[ТРЕБУЕТ УТОЧНЕНИЯ: суд]",
        claimant=["ТОО Истец"],
        defendant=["ТОО Ответчик"],
        price_of_claim="1000 тенге",
        facts=["Ответчик не исполнил обязательство."],
        legal_basis=["Обязательство подлежит исполнению."],
        requests=["Взыскать 1000 тенге."],
        attachments=["Договор"],
        verification_notes=[],
        source_urls=["https://adilet.zan.kz/rus/docs/K940001000_"],
    )


def _packet() -> ClaimPipelinePacket:
    return ClaimPipelinePacket(
        facts={
            "стороны": [{"роль": "истец"}, {"роль": "ответчик"}],
            "основание": {},
            "хронология": [],
            "обязательства": [],
            "нарушение": {},
            "суммы": [],
            "досудебный_порядок": {},
            "дефицит_данных": [],
        },
        qualification={
            "вид_правоотношений": "договорные",
            "требования": [{"формулировка": "взыскание долга", "поисковые_запросы_НПА": ["исполнение обязательства"]}],
        },
        applicability={
            "нормы": [
                {
                    "article_id": "GK_RK_OBSHAYA:272",
                    "применима": True,
                }
            ],
            "норма_не_найдена": [],
        },
        candidate_norms=[
            {
                "article_id": "GK_RK_OBSHAYA:272",
                "акт": "Гражданский кодекс",
                "статья": "272",
                "пункт": "",
                "заголовок": "Надлежащее исполнение",
                "текст": "Тестовый текст нормы",
                "редакция_из_корпуса": "2026-01-01",
                "источник": "https://adilet.zan.kz/rus/docs/K940001000_",
            }
        ],
    )


class _FakeInner:
    def __init__(self) -> None:
        self.settings = SimpleNamespace(
            openai_validation_model="validation-model",
            max_case_text_chars=60000,
        )
        self.research_inputs: list[str] = []
        self.draft_inputs: list[str] = []
        self.other_calls = 0

    async def research_case(self, case_context: str, language: str = "ru") -> LegalResearch:
        self.research_inputs.append(case_context)
        return _research()

    async def draft_claim(self, case_context: str, research: LegalResearch, language: str = "ru") -> ClaimDraft:
        self.draft_inputs.append(case_context)
        return _draft()

    async def research_pretrial(self, case_context: str, language: str = "ru") -> LegalResearch:
        self.other_calls += 1
        return _research()

    async def _structured_response(self, **kwargs):  # pragma: no cover - must not run in off tests
        raise AssertionError("unexpected structured call")


def test_mode_defaults_to_off(monkeypatch) -> None:
    monkeypatch.delenv("KORGAN_CLAIM_PIPELINE_V2_MODE", raising=False)
    assert claim_pipeline_v2_mode() == "off"
    monkeypatch.setenv("KORGAN_CLAIM_PIPELINE_V2_MODE", "unknown")
    assert claim_pipeline_v2_mode() == "off"


def test_off_mode_is_exact_legacy_delegate(monkeypatch) -> None:
    monkeypatch.setenv("KORGAN_CLAIM_PIPELINE_V2_MODE", "off")
    inner = _FakeInner()
    adapter = ClaimPipelineV2Adapter(inner)

    research = asyncio.run(adapter.research_case("RAW CASE", language="ru"))
    draft = asyncio.run(adapter.draft_claim("RAW CASE", research, language="ru"))
    pretrial = asyncio.run(adapter.research_pretrial("PRETRIAL", language="ru"))

    assert inner.research_inputs == ["RAW CASE"]
    assert inner.draft_inputs == ["RAW CASE"]
    assert draft.title == "Исковое заявление"
    assert pretrial.status == VerificationStatus.VERIFIED
    assert inner.other_calls == 1


def test_active_augments_only_research_and_keeps_raw_draft_context(monkeypatch) -> None:
    monkeypatch.setenv("KORGAN_CLAIM_PIPELINE_V2_MODE", "active")
    inner = _FakeInner()
    adapter = ClaimPipelineV2Adapter(inner)

    async def build_packet(case_context: str, language: str) -> ClaimPipelinePacket:
        assert case_context == "RAW CASE"
        return _packet()

    async def critic(packet, research, draft, language):
        return {
            "несуществующие_или_устаревшие_ссылки": [],
            "статьи_без_фактической_опоры": [],
            "факты_без_доказательств": [],
            "нарушения_формы_и_содержания_иска": [],
            "риск_возврата_иска": {"есть": False, "почему": ""},
            "арифметика": [],
            "двойное_взыскание_неустойки": {"есть": False, "почему": ""},
            "уязвимости_для_возражений": [],
            "вердикт": "подавать",
        }

    monkeypatch.setattr(adapter, "_build_packet", build_packet)
    monkeypatch.setattr(adapter, "_critic", critic)

    research = asyncio.run(adapter.research_case("RAW CASE", language="ru"))
    draft = asyncio.run(adapter.draft_claim("RAW CASE", research, language="ru"))

    assert len(inner.research_inputs) == 1
    assert inner.research_inputs[0].startswith("RAW CASE")
    assert "<структурированные_факты_pipeline_v2>" in inner.research_inputs[0]
    assert "GK_RK_OBSHAYA:272" in inner.research_inputs[0]
    assert inner.draft_inputs == ["RAW CASE"]
    assert draft.status == VerificationStatus.VERIFIED
    assert draft.verification_notes == []


def test_pipeline_failure_falls_back_to_stable_raw_research(monkeypatch) -> None:
    monkeypatch.setenv("KORGAN_CLAIM_PIPELINE_V2_MODE", "active")
    inner = _FakeInner()
    adapter = ClaimPipelineV2Adapter(inner)

    async def fail(case_context: str, language: str) -> ClaimPipelinePacket:
        raise RuntimeError("v2 unavailable")

    monkeypatch.setattr(adapter, "_build_packet", fail)
    research = asyncio.run(adapter.research_case("RAW CASE", language="ru"))

    assert research.status == VerificationStatus.VERIFIED
    assert inner.research_inputs == ["RAW CASE"]


def test_enforce_critic_marks_draft_without_rewriting(monkeypatch) -> None:
    monkeypatch.setenv("KORGAN_CLAIM_PIPELINE_V2_MODE", "enforce")
    inner = _FakeInner()
    adapter = ClaimPipelineV2Adapter(inner)
    adapter._remember("unused", _packet())

    async def build_packet(case_context: str, language: str) -> ClaimPipelinePacket:
        return _packet()

    async def critic(packet, research, draft, language):
        return {
            "несуществующие_или_устаревшие_ссылки": ["Ссылка требует повторной проверки"],
            "статьи_без_фактической_опоры": [],
            "факты_без_доказательств": [],
            "нарушения_формы_и_содержания_иска": [],
            "риск_возврата_иска": {"есть": False, "почему": ""},
            "арифметика": [],
            "двойное_взыскание_неустойки": {"есть": False, "почему": ""},
            "уязвимости_для_возражений": [],
            "вердикт": "доработать",
        }

    monkeypatch.setattr(adapter, "_build_packet", build_packet)
    monkeypatch.setattr(adapter, "_critic", critic)

    research = asyncio.run(adapter.research_case("RAW CASE", language="ru"))
    draft = asyncio.run(adapter.draft_claim("RAW CASE", research, language="ru"))

    assert draft.status == VerificationStatus.NEEDS_VERIFICATION
    assert draft.requests == ["Взыскать 1000 тенге."]
    assert any("Дополнительная процессуальная проверка" in note for note in draft.verification_notes)


def test_augmented_context_warns_current_corpus_is_not_historical_verification() -> None:
    text = _augment_research_context("RAW", _packet())
    assert "НЕ являются VERIFIED" in text
    assert "историческую редакцию" in text
