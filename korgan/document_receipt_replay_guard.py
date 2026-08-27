from __future__ import annotations

import hashlib

import asyncpg

from korgan.config import Settings

_POOL: asyncpg.Pool | None = None

_SCHEMA = """
CREATE TABLE IF NOT EXISTS korgan_document_receipt_replay_guard (
    receipt_hash TEXT PRIMARY KEY,
    transaction_id TEXT,
    user_id BIGINT NOT NULL,
    request_id TEXT NOT NULL,
    document_kind TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE UNIQUE INDEX IF NOT EXISTS korgan_document_receipt_tx_unique
ON korgan_document_receipt_replay_guard(transaction_id)
WHERE transaction_id IS NOT NULL AND transaction_id <> '';
"""


def receipt_fingerprint(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


async def init_document_receipt_replay_guard(settings: Settings) -> None:
    global _POOL
    if not settings.payments_enabled:
        return
    if not settings.database_url.strip():
        raise RuntimeError("PAYMENTS_ENABLED requires DATABASE_URL for document receipt anti-replay")
    if _POOL is not None:
        return
    _POOL = await asyncpg.create_pool(
        dsn=settings.database_url,
        min_size=1,
        max_size=2,
        command_timeout=15,
    )
    async with _POOL.acquire() as connection:
        await connection.execute(_SCHEMA)


async def close_document_receipt_replay_guard() -> None:
    global _POOL
    if _POOL is not None:
        await _POOL.close()
        _POOL = None


def _same_request(row: asyncpg.Record | None, *, user_id: int, request_id: str, document_kind: str) -> bool:
    if row is None:
        return False
    return (
        int(row["user_id"]) == int(user_id)
        and str(row["request_id"]) == str(request_id)
        and str(row["document_kind"]) == str(document_kind)
    )


async def _existing_reservation(receipt_hash: str, transaction_id: str | None) -> asyncpg.Record | None:
    if _POOL is None:
        raise RuntimeError("Document receipt anti-replay guard is not initialized")
    row = await _POOL.fetchrow(
        """
        SELECT receipt_hash, transaction_id, user_id, request_id, document_kind
        FROM korgan_document_receipt_replay_guard
        WHERE receipt_hash = $1
        """,
        receipt_hash,
    )
    if row is None and transaction_id:
        row = await _POOL.fetchrow(
            """
            SELECT receipt_hash, transaction_id, user_id, request_id, document_kind
            FROM korgan_document_receipt_replay_guard
            WHERE transaction_id = $1
            """,
            transaction_id,
        )
    return row


async def reserve_verified_document_receipt(
    *,
    receipt_hash: str,
    transaction_id: str,
    user_id: int,
    request_id: str,
    document_kind: str,
) -> bool:
    """Reserve a verified receipt once, while allowing safe same-request retries."""
    if _POOL is None:
        raise RuntimeError("Document receipt anti-replay guard is not initialized")
    txid = transaction_id.strip() or None
    try:
        result = await _POOL.execute(
            """
            INSERT INTO korgan_document_receipt_replay_guard(
                receipt_hash, transaction_id, user_id, request_id, document_kind
            ) VALUES($1,$2,$3,$4,$5)
            ON CONFLICT (receipt_hash) DO NOTHING
            """,
            receipt_hash,
            txid,
            int(user_id),
            str(request_id),
            str(document_kind),
        )
        if result.endswith("1"):
            return True
    except asyncpg.UniqueViolationError:
        # A repeated transaction id with different file bytes is replay unless it
        # belongs to the exact same user/request/kind and is only being retried.
        pass

    existing = await _existing_reservation(receipt_hash, txid)
    return _same_request(
        existing,
        user_id=user_id,
        request_id=request_id,
        document_kind=document_kind,
    )