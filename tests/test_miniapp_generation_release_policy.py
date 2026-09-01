"""Фоновая задача выпускает документ по тем же правилам, что и прямой запрос.

Политика выпуска решает, что видит оплативший пользователь: полноценный
документ, честно помеченный предварительный проект или отказ с сохранённой
возможностью повтора. Пока подготовка шла внутри HTTP-запроса, правило стояло
одно — обёртка вокруг `core.generate_document`. Фоновая задача вызывает более
низкий слой, и без явной проверки она выпускала бы документ, который прямой
запрос выпустить отказался бы.
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

from korgan import miniapp_generation_jobs as jobs
from korgan import miniapp_professional_release as release


class FakeStore:
    def __init__(self) -> None:
        self.saved: list[tuple[str, dict[str, object]]] = []

    async def save(self, identity: str, state: dict[str, object]) -> None:
        self.saved.append((identity, state))


def _install_generate(monkeypatch, *, filing_ready: bool, release_status: str) -> None:
    from korgan import miniapp_api_v2 as core

    async def fake_generate(document_type: str, context: str, language: str):
        draft = SimpleNamespace(title="Исковое заявление", status="NEEDS_VERIFICATION")
        meta = {
            "verification_notes": ["не определена госпошлина или подтвержденная льгота"],
            "quality_score": 8.4,
            "quality_issues": ["FILING_ACTION: указать банковские реквизиты истца"],
            "filing_ready": filing_ready,
            "release_status": release_status,
        }
        return draft, b"docx-bytes", "claim.docx", meta

    monkeypatch.setattr(core, "_generate", fake_generate)


async def _noop_stage(_stage: str, _progress: int) -> None:
    return None


def test_job_marks_weak_draft_preliminary_instead_of_releasing_it(monkeypatch) -> None:
    _install_generate(monkeypatch, filing_ready=False, release_status="draft")
    monkeypatch.delenv(release.FLAG_ENV, raising=False)

    payload = asyncio.run(
        jobs._generate_payload(
            "claim",
            "Проверяемые факты",
            "ru",
            case_id="case-1",
            on_stage=_noop_stage,
        )
    )

    assert payload["release_status"] == "preliminary"
    assert payload["filing_ready"] is False
    assert payload["preliminary"] is True
    assert "указать банковские реквизиты истца" in payload["todo_before_filing"]
    assert payload["document_base64"]


def test_job_refuses_release_when_preliminary_delivery_is_off(monkeypatch) -> None:
    _install_generate(monkeypatch, filing_ready=False, release_status="draft")
    monkeypatch.setenv(release.FLAG_ENV, "off")

    with pytest.raises(release.ReleaseBlocked):
        asyncio.run(
            jobs._generate_payload(
                "claim",
                "Проверяемые факты",
                "ru",
                case_id="case-1",
                on_stage=_noop_stage,
            )
        )


def test_blocked_release_never_stores_document_and_keeps_payment(monkeypatch) -> None:
    _install_generate(monkeypatch, filing_ready=False, release_status="draft")
    monkeypatch.setenv(release.FLAG_ENV, "off")
    store = FakeStore()
    state: dict[str, object] = {"cases": {"case-1": {"id": "case-1"}}}
    job = jobs.GenerationJob(
        id="job-1",
        payment_order_id=91,
        user_key="user-key",
        case_id="case-1",
        status="queued",
        stage="queued",
        progress=0,
        error_detail="",
    )
    updates: list[dict[str, object]] = []

    async def fake_update(_job_id: str, **values):
        updates.append(values)

    async def forbidden_consume(*args, **kwargs):
        raise AssertionError("заблокированный выпуск не должен списывать оплату")

    monkeypatch.setattr(jobs, "update_job", fake_update)
    monkeypatch.setattr(jobs.document_store, "consume_document_order", forbidden_consume)

    with pytest.raises(release.ReleaseBlocked):
        asyncio.run(
            jobs.run_job(
                job,
                identity="identity",
                state=state,
                store=store,
                document_type="claim",
                context="Проверяемые факты",
                language="ru",
            )
        )

    assert store.saved == []
    assert "document_base64" not in state["cases"]["case-1"]
    assert updates[-1]["status"] == "failed"
    error = str(updates[-1]["error_detail"])
    assert "профессиональную проверку" in error
    assert "оплат" in error.lower()


def test_verified_document_passes_through_untouched(monkeypatch) -> None:
    _install_generate(monkeypatch, filing_ready=True, release_status="verified")
    monkeypatch.delenv(release.FLAG_ENV, raising=False)

    payload = asyncio.run(
        jobs._generate_payload(
            "claim",
            "Проверяемые факты",
            "ru",
            case_id="case-1",
            on_stage=_noop_stage,
        )
    )

    assert payload["release_status"] == "verified"
    assert payload["filing_ready"] is True
    assert "preliminary" not in payload


def test_release_policy_is_one_shared_rule() -> None:
    """Прямой запрос и фоновая задача обязаны решать одинаково."""
    verified = {"filing_ready": True, "release_status": "verified"}
    assert release.apply_release_policy(dict(verified), case_id="case-1") == verified
