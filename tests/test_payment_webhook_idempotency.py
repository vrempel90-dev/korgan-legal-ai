"""Один успешный платёж — один одобренный заказ, одна задача, один документ.

Провайдер вправе прислать уведомление дважды, клиент — переоткрыть приложение,
а связь — оборваться сразу после оплаты. Ни одно из этих событий не должно
превращаться во второе списание, второе дело или вторую подготовку.
"""

from __future__ import annotations

import asyncio
import inspect
import pathlib

from korgan import miniapp_document_payments as document_store
from korgan import miniapp_generation_jobs as jobs
from korgan import miniapp_tole_payments as tole


class _Pool:
    def __init__(self) -> None:
        self.updates: list[tuple] = []

    async def execute(self, sql, *args):
        self.updates.append((" ".join(str(sql).split()), args))
        return "UPDATE 1"

    async def fetchrow(self, *_args):
        return None


def test_repeated_webhook_approves_only_a_pending_order(monkeypatch) -> None:
    """Повторное уведомление не одобряет уже одобренный заказ второй раз."""
    pool = _Pool()
    monkeypatch.setattr(document_store, "_require_pool", lambda: pool)

    class _Lock:
        async def __aenter__(self): return self
        async def __aexit__(self, *_exc): return False

    monkeypatch.setattr(tole, "payment_operation_lock", lambda *_a, **_k: _Lock())

    asyncio.run(tole._approve_order_from_tole(91, provider_intent_id="intent-1"))
    asyncio.run(tole._approve_order_from_tole(91, provider_intent_id="intent-1"))

    assert len(pool.updates) == 2, "оба уведомления должны дойти до базы"
    for sql, _args in pool.updates:
        # Переход разрешён только из ожидания оплаты: второй раз он не сработает,
        # потому что заказ уже не в этом состоянии.
        assert "WHERE id=$1 AND status='pending_receipt'" in sql


def test_approval_is_serialized_by_order() -> None:
    """Два уведомления одновременно не могут одобрить заказ дважды.

    Читается исходник модуля, а не объект функции: в боевой сборке одобрение
    обёрнуто слоем автозапуска подготовки, и `inspect.getsource` показал бы
    обёртку вместо самой операции.
    """
    source = pathlib.Path(inspect.getfile(tole)).read_text(encoding="utf-8")
    start = source.index("async def _approve_order_from_tole(")
    body = source[start:source.index("\nasync def ", start + 1)]

    assert "payment_operation_lock" in body
    assert "tole-approve-document" in body


def test_paid_order_starts_preparation_without_a_second_charge() -> None:
    """Одобренная оплата сама запускает подготовку — клиенту нечего нажимать."""
    from korgan import miniapp_paid_autostart_runtime as autostart

    source = pathlib.Path(inspect.getfile(autostart)).read_text(encoding="utf-8")
    assert "_ORIGINAL_APPROVE" in source, "автозапуск больше не навешан на одобрение оплаты"
    assert "start_paid_generation" in source, "одобренная оплата больше не запускает подготовку"


def test_one_paid_order_can_hold_only_one_job() -> None:
    """Вторая задача за ту же оплату невозможна на уровне схемы."""
    assert "payment_order_id BIGINT NOT NULL UNIQUE" in jobs._SCHEMA
    body = inspect.getsource(jobs.create_or_get_job)
    assert "ON CONFLICT (payment_order_id) DO UPDATE" in body
    assert "INSERT INTO korgan_miniapp_generation_jobs" in body


def test_payment_is_consumed_once_per_job() -> None:
    """Уже списанный ордер этой же задачи — основание продолжить, а не платить снова."""
    body = inspect.getsource(jobs._claim_payment)
    assert "consume_document_order" in body
    assert '"consumed"' in body or "'consumed'" in body
    assert "Повторно не платите" in body


def test_retry_reuses_the_same_job_instead_of_creating_another() -> None:
    """Повтор после сбоя — переход состояния той же строки, а не новая задача."""
    body = inspect.getsource(jobs.reset_failed_job)
    assert "WHERE id=$1 AND status='failed'" in body
    assert "INSERT" not in body


def test_only_one_worker_can_run_a_job() -> None:
    """Право на работу выдаёт переход состояния в базе, и выигрывает его один."""
    body = inspect.getsource(jobs.claim_job)
    assert "WHERE id=$1 AND status='queued'" in body
    assert "SET status='running'" in body
