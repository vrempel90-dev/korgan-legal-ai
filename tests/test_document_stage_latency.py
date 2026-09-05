"""Постадийная латентность: измеряется то, что решает вопрос «что ускорять».

Общий бюджет генерации измерялся и раньше, но одним числом. Здесь проверяется,
что production-конвейер пишет длительность каждой стадии по её фактической
границе — включая стадию, на которой генерация упала: именно она обычно и
съедает бюджет.
"""

from __future__ import annotations

import asyncio
import logging

import pytest

from korgan import document_stage_latency as stage_latency


def _minimal_docx() -> bytes:
    """Настоящий Word: слои выпуска открывают отданные байты, а не верят им."""
    import io

    from docx import Document

    document = Document()
    document.add_paragraph("Исковое заявление")
    buffer = io.BytesIO()
    document.save(buffer)
    return buffer.getvalue()


def test_stage_timings_report_every_measured_stage_and_total() -> None:
    timings = stage_latency.StageTimings("claim")
    timings.record(stage_latency.LEGAL_RESEARCH, 12.5)
    timings.record(stage_latency.DRAFTING, 40.0)
    timings.record(stage_latency.DOCX_RENDER, 1.25)

    line = timings.as_log_line(status="ok")

    assert "document_type=claim" in line
    assert "LEGAL_RESEARCH=12.50" in line
    assert "DRAFTING=40.00" in line
    assert "DOCX_RENDER=1.25" in line
    assert "TOTAL=" in line
    # Незамеренная стадия не выдумывается: ноль там означал бы «прошла мгновенно».
    assert stage_latency.CALCULATIONS not in line


def test_failed_stage_is_still_measured() -> None:
    timings = stage_latency.StageTimings("claim")

    with pytest.raises(RuntimeError):
        with timings.stage(stage_latency.DRAFTING):
            raise RuntimeError("drafting failed")

    assert stage_latency.DRAFTING in timings.seconds


def test_production_generate_logs_stage_latency(monkeypatch, caplog) -> None:
    """Реальный production `_generate` пишет стадии, а не только TOTAL."""
    from korgan import miniapp_api_v2 as core

    from korgan.legal_types import ClaimDraft, VerificationStatus

    def _draft() -> ClaimDraft:
        """Настоящий черновик: рендер Word обёрнут слоями выпуска, и они
        обращаются к реальным полям, а не к заглушке с двумя атрибутами."""
        return ClaimDraft(
            status=VerificationStatus.NEEDS_VERIFICATION,
            title="Исковое заявление о взыскании задолженности",
            court="Специализированный межрайонный экономический суд города Алматы",
            claimant=["ТОО «Алтын Курылыс», БИН 123456789012"],
            defendant=["ТОО «Мега Строй», БИН 210987654321"],
            price_of_claim="4 500 000 тенге",
            facts=["Поставка по накладной № 44 от 20.01.2025 не оплачена."],
            legal_basis=[],
            requests=["Взыскать 4 500 000 тенге основного долга."],
            attachments=["Копия накладной № 44 от 20.01.2025"],
            verification_notes=[],
            source_urls=[],
        )

    async def fake_research(context, language="ru"):
        return object()

    async def fake_draft(context, research, language="ru"):
        return _draft()

    monkeypatch.setattr(core.service, "research_case", fake_research)
    monkeypatch.setattr(core.service, "draft_claim", fake_draft)
    monkeypatch.setattr(
        core,
        "_release_metadata",
        lambda *a, **k: {"filing_ready": False, "verification_notes": [], "quality_score": 5.0,
                         "quality_issues": [], "release_status": "preliminary"},
    )

    with caplog.at_level(logging.INFO, logger="korgan.document_stage_latency"):
        asyncio.run(core._generate("claim", "материалы дела", "ru"))

    line = next(m for m in caplog.messages if m.startswith("DOCUMENT_STAGE_LATENCY"))
    for stage in (
        stage_latency.LEGAL_RESEARCH,
        stage_latency.DRAFTING,
        stage_latency.LEGAL_QA,
        stage_latency.DOCX_RENDER,
    ):
        assert f"{stage}=" in line, f"стадия {stage} не измерена: {line}"
    assert "status=ok" in line


def test_stage_latency_is_recorded_when_generation_fails(monkeypatch, caplog) -> None:
    """Упавшая генерация обязана оставить след о том, где она стояла."""
    from korgan import miniapp_api_v2 as core

    async def fake_research(context, language="ru"):
        return object()

    async def exploding_draft(context, research, language="ru"):
        raise RuntimeError("drafting provider failed")

    monkeypatch.setattr(core.service, "research_case", fake_research)
    monkeypatch.setattr(core.service, "draft_claim", exploding_draft)

    with caplog.at_level(logging.INFO, logger="korgan.document_stage_latency"):
        with pytest.raises(RuntimeError):
            asyncio.run(core._generate("claim", "материалы дела", "ru"))

    line = next(m for m in caplog.messages if m.startswith("DOCUMENT_STAGE_LATENCY"))
    assert "status=error" in line
    assert f"{stage_latency.DRAFTING}=" in line
    assert f"{stage_latency.DOCX_RENDER}=" not in line


def test_delivery_stage_and_job_total_are_logged_for_every_job(monkeypatch, caplog) -> None:
    """Выдача документа тоже должна быть видна в логах после деплоя.

    Юридический конвейер измеряет себя сам, но списание оплаты и сохранение
    состояния происходят за его границей. Без стадии DELIVERY из логов нельзя
    сказать, укладывается ли в бюджет весь путь до клиента или только
    подготовка Word.
    """
    import asyncio
    from contextlib import asynccontextmanager

    from korgan import miniapp_generation_jobs as jobs

    class _Pool:
        @asynccontextmanager
        async def acquire(self):
            yield self

        async def execute(self, *args):
            return "UPDATE 1"

        async def fetchrow(self, *args):
            return None

    class _Store:
        def __init__(self) -> None:
            self.state = {"cases": {"case-1": {"id": "case-1"}}}

        def user_key(self, _identity):
            return "user-key"

        async def load(self, _identity):
            return self.state

        async def save(self, _identity, state):
            self.state = state

    job = jobs.GenerationJob(
        id="job-latency",
        payment_order_id=7,
        user_key="user-key",
        case_id="case-1",
        status="queued",
        stage="queued",
        progress=0,
        error_detail="",
    )

    async def fake_claim(job_id):
        return job

    async def fake_update(job_id, *, status, stage, progress, error_detail=""):
        return None

    async def fake_payload(document_type, context, language, *, case_id, report_stage):
        return {"status": "document_ready", "document_base64": "ZmlsZQ==", "filename": "claim.docx"}

    async def fake_consume(order_id, *, user_key):
        return True

    monkeypatch.setattr(jobs, "_POOL", _Pool())
    monkeypatch.setattr(jobs, "claim_job", fake_claim)
    monkeypatch.setattr(jobs, "update_job", fake_update)
    monkeypatch.setattr(jobs, "_generate_payload", fake_payload)
    monkeypatch.setattr(jobs.document_store, "consume_document_order", fake_consume)

    with caplog.at_level(logging.INFO, logger="korgan.miniapp_generation_jobs"):
        asyncio.run(
            jobs.run_job(
                job,
                identity="identity",
                store=_Store(),
                document_type="claim",
                context="материалы",
                language="ru",
            )
        )

    line = next(m for m in caplog.messages if m.startswith(stage_latency.JOB_LABEL))
    assert f"{stage_latency.DELIVERY}=" in line
    assert f"{stage_latency.TOTAL}=" in line
    assert "status=ok" in line
