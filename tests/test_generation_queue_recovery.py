"""Оплаченная работа не может остаться без исполнителя.

Задачу запускает тот процесс, который принял запрос на подготовку, и реестр
исполнителей живёт в его памяти. Если процесс перезапустился сразу после
создания задачи — или запрос пришёл в одну реплику, а опрос идёт в другую, —
подхватить её на месте некому. Разгребает такие случаи фоновый цикл: сами
одобренные заказы и есть устойчивая очередь работы.

Набор фиксирует этот механизм, потому что без него клиент ждал бы документ,
который никто не готовит, — и никакой опрос состояния этого не изменил бы.
"""

from __future__ import annotations

import inspect
import pathlib

from korgan import miniapp_generation_jobs as jobs
from korgan import miniapp_paid_autostart_runtime as autostart


def _source(module) -> str:
    return pathlib.Path(inspect.getfile(module)).read_text(encoding="utf-8")


def test_queued_jobs_and_orderless_payments_are_both_picked_up() -> None:
    body = inspect.getsource(autostart.reconcile_paid_work)

    assert "o.status IN ('approved', 'consumed')" in body, "очередь работы больше не строится по оплатам"
    assert "j.id IS NULL OR j.status='queued'" in body, "задача, оставшаяся в очереди, больше не подхватывается"


def test_recovery_runs_on_a_schedule_not_only_at_startup() -> None:
    """Перезапуск — не единственный момент, когда очередь может осиротеть."""
    assert autostart._RECONCILE_INTERVAL_SECONDS > 0
    assert autostart._RECONCILE_INTERVAL_SECONDS <= 60, "осиротевшая задача ждала бы исполнителя слишком долго"
    loop = inspect.getsource(autostart._reconciliation_loop)
    assert "while True" in loop
    assert "asyncio.sleep(_RECONCILE_INTERVAL_SECONDS)" in loop


def test_recovery_never_creates_a_second_worker() -> None:
    """Подхват безопасен: право на работу выдаёт переход состояния в базе."""
    assert "payment_order_id BIGINT NOT NULL UNIQUE" in jobs._SCHEMA
    claim = inspect.getsource(jobs.claim_job)
    assert "WHERE id=$1 AND status='queued'" in claim
    assert "SET status='running'" in claim


def test_startup_recovery_leaves_queued_jobs_to_the_scheduler() -> None:
    """Восстановление при старте не хоронит то, что ещё можно запустить."""
    body = inspect.getsource(jobs.recover_interrupted_jobs)
    assert "WHERE status='running'" in body
    assert "status IN ('queued'" not in body


def test_lease_outlasts_the_generation_budget() -> None:
    """Работа, которой разрешено идти десять минут, не мертва через две.

    Раньше бюджет подготовки был 600 секунд, а задача объявлялась прерванной
    после 120 секунд молчания: любая пауза в событийном цикле дольше двух минут
    превращала идущую подготовку в «сервис перезапустился».
    """
    from korgan.document_latency_budget_runtime import document_generation_timeout_seconds

    lease = jobs.lease_seconds()
    assert lease > document_generation_timeout_seconds()
    assert lease > jobs._HEARTBEAT_SECONDS * 3
    assert lease >= jobs._MIN_LEASE_SECONDS
