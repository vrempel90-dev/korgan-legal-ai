"""Payment-off documents use the canonical generation routes.

Free generation is a product mode, not an ASGI route patch. These regressions
protect authentication, duplicate suppression, immutable case scope and the
two-minute containment boundary without touching any payment store.
"""

from __future__ import annotations

import asyncio

import pytest
from fastapi import HTTPException

from korgan import miniapp_generation_api as generation_api


@pytest.fixture(autouse=True)
def _clear_free_jobs() -> None:
    generation_api._FREE_JOBS.clear()
    generation_api._FREE_CASE_JOB.clear()
    yield
    generation_api._FREE_JOBS.clear()
    generation_api._FREE_CASE_JOB.clear()


def _install_free_identity(monkeypatch) -> dict[str, object]:
    monkeypatch.setattr(generation_api.settings, "payments_enabled", False)
    state: dict[str, object] = {
        "cases": {
            "case-1": {
                "id": "case-1",
                "description": "Ответчик не исполнил обязательство по договору.",
                "document_type": "claim",
                "language": "ru",
            }
        }
    }
    monkeypatch.setattr(generation_api.core.legacy, "_identity", lambda _raw: "identity")

    async def require_consent(_identity: str):
        return state

    monkeypatch.setattr(generation_api.core.legacy, "_require_consent", require_consent)
    monkeypatch.setattr(generation_api.core.store, "user_key", lambda _identity: "user-key")
    return state


def _request():
    return generation_api.core.GenerateRequest(
        case_id="case-1",
        document_type="claim",
        language="ru",
    )


def test_payment_off_starts_free_job_without_touching_payment_store(monkeypatch) -> None:
    _install_free_identity(monkeypatch)
    scheduled: list[generation_api.FreeGenerationJob] = []

    def schedule(job, *, context: str) -> None:
        assert "Ответчик" in context
        scheduled.append(job)

    async def forbidden(*args, **kwargs):
        raise AssertionError("payment persistence must not be touched in free mode")

    monkeypatch.setattr(generation_api, "_schedule_free_job", schedule)
    monkeypatch.setattr(generation_api.jobs, "latest_job_for_case", forbidden)
    monkeypatch.setattr(generation_api.document_store, "get_scope_order", forbidden)

    result = asyncio.run(
        generation_api.generate_document_job(_request(), x_telegram_init_data="signed")
    )

    assert result["payment_required"] is False
    assert result["generation_started"] is True
    assert result["job"]["job_id"].startswith("free-")
    assert len(scheduled) == 1


def test_duplicate_free_start_reuses_one_job_for_same_materials(monkeypatch) -> None:
    _install_free_identity(monkeypatch)
    scheduled: list[str] = []
    monkeypatch.setattr(
        generation_api,
        "_schedule_free_job",
        lambda job, **_kwargs: scheduled.append(job.id),
    )

    first = asyncio.run(
        generation_api.generate_document_job(_request(), x_telegram_init_data="signed")
    )
    second = asyncio.run(
        generation_api.generate_document_job(_request(), x_telegram_init_data="signed")
    )

    assert first["job"]["job_id"] == second["job"]["job_id"]
    assert scheduled == [first["job"]["job_id"]]


def test_material_change_does_not_publish_or_duplicate_in_flight_free_job(monkeypatch) -> None:
    state = _install_free_identity(monkeypatch)
    monkeypatch.setattr(generation_api, "_schedule_free_job", lambda *args, **kwargs: None)
    asyncio.run(generation_api.generate_document_job(_request(), x_telegram_init_data="signed"))

    state["cases"]["case-1"]["description"] = "Новые существенные материалы дела."
    with pytest.raises(HTTPException) as raised:
        asyncio.run(
            generation_api.generate_document_job(_request(), x_telegram_init_data="signed")
        )

    assert raised.value.status_code == 409
    assert "изменились" in str(raised.value.detail)


def test_completed_free_document_is_recovered_from_encrypted_case(monkeypatch) -> None:
    state = _install_free_identity(monkeypatch)
    case = state["cases"]["case-1"]
    scope = generation_api.v5.v4._document_scope(case, "claim", "ru")
    case.update(
        {
            "status": "document_ready",
            "title": "Исковое заявление",
            "filename": "claim.docx",
            "document_base64": "ZmlsZQ==",
            "filing_ready": False,
            "release_status": "preliminary",
            "verification_status": "needs_verification",
            "verification_notes": ["Проверить подсудность"],
            "quality_score": 8.7,
            "quality_issues": ["Уточнить суд"],
            generation_api._FREE_SCOPE_FIELD: scope,
            generation_api._FREE_JOB_FIELD: "free-persisted",
        }
    )

    result = asyncio.run(
        generation_api.case_generation_status("case-1", x_telegram_init_data="signed")
    )

    assert result["job"]["job_id"] == "free-persisted"
    assert result["job"]["document_ready"] is True
    assert result["document"]["filename"] == "claim.docx"
    assert "document_base64" not in result["document"]


def test_free_worker_is_hard_bounded_to_two_minutes(monkeypatch) -> None:
    _install_free_identity(monkeypatch)
    monkeypatch.setattr(generation_api, "FREE_GENERATION_TIMEOUT_SECONDS", 0.001)

    async def stalled_generate(*args, **kwargs):
        await asyncio.Event().wait()

    monkeypatch.setattr(generation_api.core, "_generate", stalled_generate)
    job = generation_api.FreeGenerationJob(
        id="free-timeout",
        identity="identity",
        case_id="case-1",
        case_fingerprint="scope",
        document_type="claim",
        language="ru",
    )

    with pytest.raises(TimeoutError):
        asyncio.run(generation_api._run_free_generation(job, context="Факты"))

    assert job.status == "failed"
    assert "две минуты" in job.error
