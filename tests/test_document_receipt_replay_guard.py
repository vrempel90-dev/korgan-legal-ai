from __future__ import annotations

import asyncio

from korgan import document_receipt_replay_guard as guard


class FakePool:
    def __init__(self, *, insert_result: str, row=None) -> None:
        self.insert_result = insert_result
        self.row = row
        self.executed = 0
        self.fetches = 0

    async def execute(self, *_args, **_kwargs) -> str:
        self.executed += 1
        return self.insert_result

    async def fetchrow(self, *_args, **_kwargs):
        self.fetches += 1
        return self.row


def test_new_verified_receipt_is_reserved(monkeypatch) -> None:
    pool = FakePool(insert_result="INSERT 0 1")
    monkeypatch.setattr(guard, "_POOL", pool)
    allowed = asyncio.run(
        guard.reserve_verified_document_receipt(
            receipt_hash="hash-1",
            transaction_id="tx-1",
            user_id=100,
            request_id="request-1",
            document_kind="claim",
        )
    )
    assert allowed is True
    assert pool.executed == 1
    assert pool.fetches == 0


def test_same_receipt_same_request_retry_is_idempotently_allowed(monkeypatch) -> None:
    pool = FakePool(
        insert_result="INSERT 0 0",
        row={
            "receipt_hash": "hash-1",
            "transaction_id": "tx-1",
            "user_id": 100,
            "request_id": "request-1",
            "document_kind": "claim",
        },
    )
    monkeypatch.setattr(guard, "_POOL", pool)
    allowed = asyncio.run(
        guard.reserve_verified_document_receipt(
            receipt_hash="hash-1",
            transaction_id="tx-1",
            user_id=100,
            request_id="request-1",
            document_kind="claim",
        )
    )
    assert allowed is True


def test_same_receipt_for_different_request_stays_blocked(monkeypatch) -> None:
    pool = FakePool(
        insert_result="INSERT 0 0",
        row={
            "receipt_hash": "hash-1",
            "transaction_id": "tx-1",
            "user_id": 100,
            "request_id": "request-old",
            "document_kind": "claim",
        },
    )
    monkeypatch.setattr(guard, "_POOL", pool)
    allowed = asyncio.run(
        guard.reserve_verified_document_receipt(
            receipt_hash="hash-1",
            transaction_id="tx-1",
            user_id=100,
            request_id="request-new",
            document_kind="claim",
        )
    )
    assert allowed is False