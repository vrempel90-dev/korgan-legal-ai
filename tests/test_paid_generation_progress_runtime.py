from __future__ import annotations

import asyncio

from korgan import generation_progress
from korgan import miniapp_paid_generation_progress_runtime as runtime


def test_paid_progress_uses_real_pipeline_events_and_never_moves_backwards(monkeypatch) -> None:
    seen: list[tuple[str, int]] = []
    model_calls: list[str] = []

    async def fake_payload(document_type, context, language, *, case_id, on_stage):
        model_calls.append(case_id)
        # Existing coarse milestone.
        await on_stage("legal_research", 20)
        # Actual synchronous boundaries emitted by the legal pipeline.
        generation_progress.report("legal_research", 42)
        generation_progress.report("legal_research", 45)
        generation_progress.report("legal_research", 75)
        generation_progress.report("quality_control", 88)
        generation_progress.report("document_render", 98)
        # A stale coarse milestone after the real pipeline must be ignored.
        await on_stage("quality_control", 80)
        await on_stage("document_render", 90)
        return {"filename": "claim.docx"}

    async def on_stage(stage: str, value: int) -> None:
        seen.append((stage, value))

    monkeypatch.setattr(runtime, "_ORIGINAL_GENERATE_PAYLOAD", fake_payload)

    result = asyncio.run(
        runtime._generate_payload_with_real_progress(
            "claim",
            "facts",
            "ru",
            case_id="case-progress",
            on_stage=on_stage,
        )
    )

    assert result == {"filename": "claim.docx"}
    assert model_calls == ["case-progress"], "progress must not add a second generation/model pass"
    values = [value for _, value in seen]
    assert values == [20, 42, 45, 75, 88, 98]
    assert values == sorted(values)


def test_progress_write_failure_does_not_abort_document(monkeypatch) -> None:
    calls = 0

    async def fake_payload(document_type, context, language, *, case_id, on_stage):
        generation_progress.report("legal_research", 42)
        generation_progress.report("quality_control", 88)
        return {"filename": "contract.docx"}

    async def flaky_stage(stage: str, value: int) -> None:
        nonlocal calls
        calls += 1
        if calls == 1:
            raise RuntimeError("temporary status-store failure")

    monkeypatch.setattr(runtime, "_ORIGINAL_GENERATE_PAYLOAD", fake_payload)

    result = asyncio.run(
        runtime._generate_payload_with_real_progress(
            "contract",
            "facts",
            "ru",
            case_id="case-progress-failure",
            on_stage=flaky_stage,
        )
    )

    assert result["filename"] == "contract.docx"
    assert calls == 2
