from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

from korgan.miniapp_store import MiniAppStore


def test_store_background_access_keeps_hmac_key_and_encryption_contract() -> None:
    async def scenario() -> None:
        store = MiniAppStore("", secret="test-secret")
        user_key = store.user_key("telegram-user-42")
        state = {"consent": True, "cases": {"case-1": {"text": "Факты дела"}}}

        await store.save_by_user_key(user_key, state)
        restored = await store.load_by_user_key(user_key)

        assert restored == state
        assert "telegram-user-42" not in store.memory
        assert user_key in store.memory

        with pytest.raises(ValueError):
            await store.load_by_user_key("telegram-user-42")

    asyncio.run(scenario())


def test_paid_order_schedules_generation_without_second_client_request(monkeypatch: pytest.MonkeyPatch) -> None:
    import korgan.miniapp_paid_autostart_runtime as runtime

    async def scenario() -> None:
        runtime._AUTO_TASKS.clear()
        order = SimpleNamespace(
            id=71,
            user_key="a" * 64,
            case_id="case-paid",
            case_fingerprint="scope-1",
            document_type="claim",
            language="ru",
            status="approved",
        )
        job = runtime.jobs.GenerationJob(
            id="11111111-1111-1111-1111-111111111111",
            payment_order_id=71,
            user_key="a" * 64,
            case_id="case-paid",
            status="queued",
            stage="queued",
            progress=0,
            error_detail="",
        )
        scheduled: list[tuple[int, str]] = []
        release = asyncio.Event()

        async def get_order(order_id: int):
            assert order_id == 71
            return order

        async def create_job(**kwargs):
            assert kwargs["payment_order_id"] == 71
            assert kwargs["case_fingerprint"] == "scope-1"
            return job

        async def load_state(user_key: str):
            assert user_key == "a" * 64
            return {
                "consent": True,
                "cases": {
                    "case-paid": {
                        "document_type": "claim",
                        "language": "ru",
                        "description": "Взыскать подтвержденную задолженность",
                    }
                },
            }

        async def fake_run(job_arg, *, order, context):
            scheduled.append((order.id, context))
            await release.wait()

        monkeypatch.setattr(runtime.document_store, "get_document_order", get_order)
        monkeypatch.setattr(runtime.jobs, "create_or_get_job", create_job)
        monkeypatch.setattr(runtime.generation_runtime.core.store, "load_by_user_key", load_state)
        monkeypatch.setattr(runtime.v5.v4, "_document_scope", lambda case, document_type, language: "scope-1")
        monkeypatch.setattr(runtime.generation_runtime.core, "_case_context", lambda case: "trusted case context")
        monkeypatch.setattr(runtime, "_run_paid_job", fake_run)

        result = await runtime.start_paid_generation(71)
        assert result == job
        await asyncio.sleep(0)
        assert scheduled == [(71, "trusted case context")]

        # A duplicate webhook/reconcile that arrives while the durable job is
        # running must reuse that same task instead of scheduling another legal
        # generation.
        result_again = await runtime.start_paid_generation(71)
        assert result_again == job
        await asyncio.sleep(0)
        assert scheduled == [(71, "trusted case context")]

        release.set()
        await asyncio.gather(*list(runtime._AUTO_TASKS.values()), return_exceptions=True)
        await asyncio.sleep(0)

    asyncio.run(scenario())


def test_paid_order_with_changed_case_scope_fails_closed_without_generation(monkeypatch: pytest.MonkeyPatch) -> None:
    import korgan.miniapp_paid_autostart_runtime as runtime

    async def scenario() -> None:
        runtime._AUTO_TASKS.clear()
        order = SimpleNamespace(
            id=72,
            user_key="b" * 64,
            case_id="case-changed",
            case_fingerprint="paid-scope",
            document_type="claim",
            language="ru",
            status="approved",
        )
        queued = runtime.jobs.GenerationJob(
            id="22222222-2222-2222-2222-222222222222",
            payment_order_id=72,
            user_key="b" * 64,
            case_id="case-changed",
            status="queued",
            stage="queued",
            progress=0,
            error_detail="",
        )
        failed = runtime.jobs.GenerationJob(
            id=queued.id,
            payment_order_id=72,
            user_key="b" * 64,
            case_id="case-changed",
            status="failed",
            stage="failed",
            progress=0,
            error_detail=runtime._SCOPE_CHANGED,
        )
        updates: list[str] = []

        async def get_order(order_id: int):
            return order

        async def create_job(**kwargs):
            return queued

        async def load_state(user_key: str):
            return {"consent": True, "cases": {"case-changed": {"description": "новые факты"}}}

        async def update_job(job_id: str, **kwargs):
            updates.append(kwargs["error_detail"])

        async def require_job(job_id: str, *, user_key: str):
            return failed

        monkeypatch.setattr(runtime.document_store, "get_document_order", get_order)
        monkeypatch.setattr(runtime.jobs, "create_or_get_job", create_job)
        monkeypatch.setattr(runtime.jobs, "update_job", update_job)
        monkeypatch.setattr(runtime.jobs, "require_job", require_job)
        monkeypatch.setattr(runtime.generation_runtime.core.store, "load_by_user_key", load_state)
        monkeypatch.setattr(runtime.v5.v4, "_document_scope", lambda case, document_type, language: "changed-scope")

        result = await runtime.start_paid_generation(72)

        assert result == failed
        assert updates == [runtime._SCOPE_CHANGED]
        assert not runtime._AUTO_TASKS

    asyncio.run(scenario())


def test_verified_tole_approval_immediately_attempts_autostart(monkeypatch: pytest.MonkeyPatch) -> None:
    import korgan.miniapp_paid_autostart_runtime as runtime

    async def scenario() -> None:
        calls: list[tuple[str, int, str]] = []

        async def approve(order_id: int, *, provider_intent_id: str) -> None:
            calls.append(("approve", order_id, provider_intent_id))

        async def start(order_id: int):
            calls.append(("start", order_id, ""))
            return None

        monkeypatch.setattr(runtime, "_ORIGINAL_APPROVE", approve)
        monkeypatch.setattr(runtime, "start_paid_generation", start)

        await runtime._approve_and_autostart(99, provider_intent_id="tole-paid-99")

        assert calls == [
            ("approve", 99, "tole-paid-99"),
            ("start", 99, ""),
        ]

    asyncio.run(scenario())
