from __future__ import annotations

import asyncio
from datetime import date
from types import SimpleNamespace

from korgan import document_latency_budget_runtime as latency
from korgan import fast_local_consultation as fast
from korgan import generation_progress
from korgan import miniapp_legal_workspace as workspace
from korgan.legal.corpus import Provision
from korgan.legal_calc import LatePaymentPenalty


class FakeCorpus:
    def __init__(self, provisions):
        self.provisions = list(provisions)
        self.closed = False

    def search(self, query: str, *, limit: int = 20):
        assert query
        return self.provisions[:limit]

    def close(self):
        self.closed = True


class FakeInner:
    def __init__(self, payload):
        self.settings = SimpleNamespace(openai_model="gpt-test")
        self.payload = payload
        self.calls = []

    async def _structured_response(self, **kwargs):
        self.calls.append(kwargs)
        return self.payload, SimpleNamespace()


def provision() -> Provision:
    return Provision(
        article_id="GK_RK_OBSHAYA:1",
        act_id="GK_RK_OBSHAYA",
        act_title="Гражданский кодекс Республики Казахстан",
        article_no="1",
        item_no=None,
        heading="Гражданское законодательство",
        body="Гражданское законодательство регулирует имущественные отношения участников гражданского оборота.",
        edition_date="2026-09-01",
        url="https://adilet.zan.kz/rus/docs/K940001000_",
    )


def test_fast_consult_uses_local_corpus_without_web_tools(monkeypatch):
    corpus = FakeCorpus([provision()])
    monkeypatch.setattr(fast, "open_corpus", lambda: corpus)
    fallback_calls = []

    async def fallback(*args, **kwargs):
        fallback_calls.append((args, kwargs))
        return "web", []

    verified_statement = (
        "Гражданское законодательство регулирует имущественные отношения участников гражданского оборота."
    )
    inner = FakeInner(
        {
            "summary": "Модель утверждает свободный вывод, который не должен попасть клиенту.",
            "legal_points": [
                {
                    "statement": verified_statement,
                    "article_id": "GK_RK_OBSHAYA:1",
                }
            ],
            "actions": [{"text": "Сохраните имеющиеся документы.", "basis_statement": ""}],
            "risks": [],
            "unknowns": [],
        }
    )
    adapter = fast.FastLocalConsultationAdapter(inner, fallback=fallback)
    text, sources = asyncio.run(adapter.consult("Как взыскать долг?", language="ru"))

    assert fallback_calls == []
    assert corpus.closed is True
    assert len(inner.calls) == 1
    assert "tools" not in inner.calls[0]
    assert verified_statement in text
    assert "свободный вывод" not in text
    assert "Сохраните имеющиеся документы" in text
    assert sources == ["https://adilet.zan.kz/rus/docs/K940001000_"]


def test_fast_consult_rejects_article_not_offered(monkeypatch):
    monkeypatch.setattr(fast, "open_corpus", lambda: FakeCorpus([provision()]))

    async def fallback(*args, **kwargs):
        raise AssertionError("web fallback must not be used when corpus is available")

    inner = FakeInner(
        {
            "summary": "Проверено.",
            "legal_points": [
                {"statement": "Выдуманный вывод.", "article_id": "GK_RK_OBSHAYA:999"}
            ],
            "actions": [],
            "risks": [],
            "unknowns": ["Норма не подтверждена"],
        }
    )
    text, sources = asyncio.run(
        fast.FastLocalConsultationAdapter(inner, fallback=fallback).consult("Вопрос", language="ru")
    )

    assert sources == []
    assert "не удалось подтвердить норму" in text
    assert "Выдуманный вывод" not in text


def test_fast_consult_drops_normative_action_not_linked_to_accepted_statement(monkeypatch):
    monkeypatch.setattr(fast, "open_corpus", lambda: FakeCorpus([provision()]))

    async def fallback(*args, **kwargs):
        raise AssertionError("fallback not expected")

    verified_statement = (
        "Гражданское законодательство регулирует имущественные отношения участников гражданского оборота."
    )
    inner = FakeInner(
        {
            "summary": "Свободный вывод.",
            "legal_points": [
                {"statement": verified_statement, "article_id": "GK_RK_OBSHAYA:1"}
            ],
            "actions": [
                {
                    "text": "Вы обязаны подать иск в течение десяти дней.",
                    "basis_statement": "Несуществующий подтверждённый тезис.",
                },
                {"text": "Сохраните расписку.", "basis_statement": ""},
            ],
            "risks": [],
            "unknowns": [],
        }
    )
    text, _ = asyncio.run(
        fast.FastLocalConsultationAdapter(inner, fallback=fallback).consult("Вопрос", language="ru")
    )

    assert "обязаны подать иск" not in text
    assert "Сохраните расписку" in text


def test_old_110_second_setting_is_lifted_to_safety_floor(monkeypatch):
    monkeypatch.setenv("KORGAN_DOCUMENT_GENERATION_TIMEOUT_SECONDS", "110")
    assert latency.document_generation_timeout_seconds() == 240.0


def test_progress_report_is_request_local():
    seen = []
    generation_progress.report("legal_research", 12)
    with generation_progress.bind(lambda stage, progress: seen.append((stage, progress))):
        generation_progress.report("legal_research", 12)
        generation_progress.report("document_render", 96)
    generation_progress.report("completed", 100)
    assert seen == [("legal_research", 12), ("document_render", 96)]


def test_penalty_workspace_defaults_rate_date_to_period_end(monkeypatch):
    async def identity(_header: str):
        return "u", {}

    captured = {}

    def calculate(principal, start, end, *, rate_date):
        captured["rate_date"] = rate_date
        return LatePaymentPenalty(
            principal=principal,
            start=start,
            end=end,
            rate_date=rate_date,
            days=(end - start).days + 1,
            rate_percent=16.75,
            amount=1000,
        )

    monkeypatch.setattr(workspace, "_require_identity", identity)
    monkeypatch.setattr(workspace.legal_calc, "calc_late_payment_penalty", calculate)
    monkeypatch.setattr(workspace.legal_calc, "nb_rate_source_url_on", lambda _day: "https://nationalbank.kz/")

    payload = workspace.LatePenaltyRequest(
        principal_kzt=500000,
        start_date=date(2026, 3, 11),
        end_date=date(2026, 9, 4),
    )
    result = asyncio.run(workspace.late_penalty_353(payload, "tg"))

    assert captured["rate_date"] == date(2026, 9, 4)
    assert result["rate_date_basis"] == "end_or_filing_date"
