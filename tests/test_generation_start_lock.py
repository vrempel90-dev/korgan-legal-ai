from __future__ import annotations

import asyncio

import korgan.payment_operation_lock as locks


class _Connection:
    def __init__(self) -> None:
        self.calls: list[str] = []

    async def execute(self, sql: str, *_args: object) -> None:
        self.calls.append(sql)


class _Acquire:
    def __init__(self, connection: _Connection) -> None:
        self.connection = connection

    async def __aenter__(self) -> _Connection:
        return self.connection

    async def __aexit__(self, *_args: object) -> None:
        return None


class _Pool:
    def __init__(self) -> None:
        self.connection = _Connection()

    def acquire(self) -> _Acquire:
        return _Acquire(self.connection)


class _ForbiddenSlots:
    async def acquire(self) -> None:
        raise AssertionError("short generation enqueue must not wait on the long-operation semaphore")

    def release(self) -> None:
        raise AssertionError("short generation enqueue must not release a semaphore it did not acquire")


def test_generation_start_bypasses_long_operation_semaphore(monkeypatch) -> None:
    pool = _Pool()
    monkeypatch.setattr(locks, "_LOCAL_SLOTS", _ForbiddenSlots())

    async def scenario() -> None:
        async with locks.payment_operation_lock(
            pool,
            "miniapp-generation-start",
            "user:case",
        ):
            pass

    asyncio.run(scenario())

    assert pool.connection.calls == [
        "SELECT pg_advisory_lock($1)",
        "SELECT pg_advisory_unlock($1)",
    ]
