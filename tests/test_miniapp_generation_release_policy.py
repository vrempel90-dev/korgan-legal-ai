"""Generated Word is always delivered; QA controls filing readiness, not file existence."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

from korgan import miniapp_generation_jobs as jobs
from korgan import miniapp_professional_release as release


class FakeStore:
    def __init__(self, state: dict[str, object] | None = None) -> None:
        self.state = state if state is not None else {"cases": {}}
        self.saved: list[tuple[str, dict[str, object]]] = []

    async def load(self, _identity: str) -> dict[str, object]:
        return self.state

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


def test_review_draft_is_delivered_even_if_legacy_flag_is_off(monkeypatch) -> None:
    """Environment flags may not bring back the old 422/purge behaviour."""
    _install_generate(monkeypatch, filing_ready=False, release_status="draft")
    monkeypatch.setenv(release.FLAG_ENV, "off")

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
    assert payload["document_base64"]
    assert payload["filename"] == "claim.docx"


def test_review_draft_is_stored_and_job_succeeds(monkeypatch) -> None:
    """A successful generation remains a successful job even when QA has warnings."""
    _install_generate(monkeypatch, filing_ready=False, release_status="draft")
    monkeypatch.setenv(release.FLAG_ENV, "off")
    state: dict[str, object] = {"cases": {"case-1": {"id": "case-1"}}}
    store = FakeStore(state)
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
    consumed: list[int] = []

    async def fake_update(_job_id: str, **values):
        updates.append(values)

    async def fake_consume(order_id: int, **kwargs):
        consumed.append(order_id)
        return True

    async def fake_claim(_job_id: str):
        return job

    monkeypatch.setattr(jobs, "claim_job", fake_claim)
    monkeypatch.setattr(jobs, "update_job", fake_update)
    monkeypatch.setattr(jobs.document_store, "consume_document_order", fake_consume)

    asyncio.run(
        jobs.run_job(
            job,
            identity="identity",
            store=store,
            document_type="claim",
            context="Проверяемые факты",
            language="ru",
        )
    )

    saved_case = state["cases"]["case-1"]
    assert consumed == [91]
    assert store.saved
    assert saved_case["document_base64"]
    assert saved_case["release_status"] == "preliminary"
    assert saved_case["filing_ready"] is False
    assert updates[-1]["status"] == "succeeded"
    assert updates[-1]["progress"] == 100


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


def test_legacy_exception_text_is_client_safe() -> None:
    """Compatibility exception must never expose internal gate vocabulary."""
    blocked = release.ReleaseBlocked(
        [
            "FILING_ACTION: указать банковские реквизиты истца",
            "не определена госпошлина или подтвержденная льгота",
        ]
    )
    detail = str(blocked)

    assert "FILING_ACTION" not in detail
    assert "указать банковские реквизиты истца" in detail
    assert "государственной пошлины" in detail
    assert "проверки перед подачей" in detail


def test_untranslatable_gate_wording_is_not_shown_raw() -> None:
    detail = str(release.ReleaseBlocked(["gate_7 assertion failed: anchors=0"]))

    assert "gate_7" not in detail
    assert "anchors" not in detail
    assert "проверки перед подачей" in detail


def test_release_policy_is_one_shared_rule() -> None:
    """Direct and background paths use the same release semantics."""
    verified = {"filing_ready": True, "release_status": "verified"}
    assert release.apply_release_policy(dict(verified), case_id="case-1") == verified

    review = {
        "filing_ready": False,
        "release_status": "draft",
        "quality_issues": ["есть правовая ссылка, не прошедшая source-bound/corpus проверку"],
        "verification_notes": [],
        "document_base64": "docx",
    }
    released = release.apply_release_policy(review, case_id="case-2")
    assert released["release_status"] == "preliminary"
    assert released["document_base64"] == "docx"
