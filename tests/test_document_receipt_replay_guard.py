from __future__ import annotations

import asyncio
import inspect

from korgan import document_receipt_replay_guard as guard


class _Pool:
    def __init__(self, result: str) -> None:
        self.result = result
        self.calls: list[tuple[str, tuple[object, ...]]] = []

    async def execute(self, sql: str, *args: object) -> str:
        self.calls.append((sql, args))
        return self.result


def test_receipt_fingerprint_is_stable_and_content_bound() -> None:
    assert guard.receipt_fingerprint(b"receipt-A") == guard.receipt_fingerprint(b"receipt-A")
    assert guard.receipt_fingerprint(b"receipt-A") != guard.receipt_fingerprint(b"receipt-B")


def test_verified_receipt_reservation_is_atomic(monkeypatch) -> None:
    pool = _Pool("INSERT 0 1")
    monkeypatch.setattr(guard, "_POOL", pool)

    accepted = asyncio.run(
        guard.reserve_verified_document_receipt(
            receipt_hash="hash-1",
            transaction_id="TX-1",
            user_id=123,
            request_id="request-1",
            document_kind="claim",
        )
    )

    assert accepted is True
    assert len(pool.calls) == 1
    _sql, args = pool.calls[0]
    assert args == ("hash-1", "TX-1", 123, "request-1", "claim")


def test_same_receipt_hash_is_rejected_when_insert_does_not_happen(monkeypatch) -> None:
    pool = _Pool("INSERT 0 0")
    monkeypatch.setattr(guard, "_POOL", pool)

    accepted = asyncio.run(
        guard.reserve_verified_document_receipt(
            receipt_hash="hash-1",
            transaction_id="TX-1",
            user_id=999,
            request_id="request-2",
            document_kind="contract",
        )
    )

    assert accepted is False


def test_schema_has_unique_hash_and_transaction_guards() -> None:
    source = inspect.getsource(guard)
    assert "receipt_hash TEXT PRIMARY KEY" in source
    assert "CREATE UNIQUE INDEX IF NOT EXISTS korgan_document_receipt_tx_unique" in source
    assert "ON CONFLICT (receipt_hash) DO NOTHING" in source
