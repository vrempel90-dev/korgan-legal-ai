from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

import asyncpg

from korgan.config import Settings

_POOL: asyncpg.Pool | None = None

_SCHEMA = """
CREATE TABLE IF NOT EXISTS korgan_miniapp_document_orders (
    id BIGSERIAL PRIMARY KEY,
    user_key TEXT NOT NULL,
    case_id TEXT NOT NULL,
    case_fingerprint TEXT NOT NULL,
    document_type TEXT NOT NULL,
    language TEXT NOT NULL DEFAULT 'ru',
    amount_kzt INTEGER NOT NULL CHECK (amount_kzt > 0),
    status TEXT NOT NULL DEFAULT 'pending_receipt'
        CHECK (status IN ('pending_receipt', 'awaiting_admin', 'approved', 'consumed', 'cancelled')),
    receipt_hash TEXT,
    transaction_id TEXT,
    receipt_check JSONB,
    decision_note TEXT NOT NULL DEFAULT '',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    receipt_at TIMESTAMPTZ,
    decided_at TIMESTAMPTZ,
    consumed_at TIMESTAMPTZ
);

CREATE TABLE IF NOT EXISTS korgan_miniapp_document_receipts (
    receipt_hash TEXT PRIMARY KEY,
    transaction_id TEXT,
    order_id BIGINT NOT NULL REFERENCES korgan_miniapp_document_orders(id),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE UNIQUE INDEX IF NOT EXISTS korgan_miniapp_document_receipts_tx_unique
ON korgan_miniapp_document_receipts(transaction_id)
WHERE transaction_id IS NOT NULL AND transaction_id <> '';

CREATE INDEX IF NOT EXISTS korgan_miniapp_document_orders_owner_idx
ON korgan_miniapp_document_orders(user_key, case_id, created_at DESC);

CREATE INDEX IF NOT EXISTS korgan_miniapp_document_orders_admin_idx
ON korgan_miniapp_document_orders(status, created_at DESC);
"""


@dataclass(frozen=True)
class DocumentPaymentOrder:
    id: int
    user_key: str
    case_id: str
    case_fingerprint: str
    document_type: str
    language: str
    amount_kzt: int
    status: str
    transaction_id: str
    receipt_check: dict[str, Any]
    decision_note: str


def _require_pool() -> asyncpg.Pool:
    if _POOL is None:
        raise RuntimeError("Mini App document payment store is not initialized")
    return _POOL


async def init_document_payment_store(settings: Settings) -> None:
    """Admin bot always connects to the shared payment database.

    The Telegram process no longer owns any customer payment/AI flow, but it
    must be able to decide orders created by the MiniApp API even if the old
    PAYMENTS_ENABLED flag on the agent service differs from the API service.
    """
    global _POOL
    if not settings.database_url.strip():
        raise RuntimeError("Admin payment decisions require DATABASE_URL")
    if _POOL is not None:
        return
    _POOL = await asyncpg.create_pool(
        dsn=settings.database_url,
        min_size=1,
        max_size=4,
        command_timeout=15,
    )
    async with _POOL.acquire() as connection:
        await connection.execute(_SCHEMA)


async def close_document_payment_store() -> None:
    global _POOL
    if _POOL is not None:
        await _POOL.close()
        _POOL = None


def _from_row(row: Any) -> DocumentPaymentOrder:
    raw_check = row["receipt_check"]
    if isinstance(raw_check, str):
        raw_check = json.loads(raw_check)
    return DocumentPaymentOrder(
        id=int(row["id"]),
        user_key=str(row["user_key"]),
        case_id=str(row["case_id"]),
        case_fingerprint=str(row["case_fingerprint"]),
        document_type=str(row["document_type"]),
        language=str(row["language"] or "ru"),
        amount_kzt=int(row["amount_kzt"]),
        status=str(row["status"]),
        transaction_id=str(row["transaction_id"] or ""),
        receipt_check=dict(raw_check or {}),
        decision_note=str(row["decision_note"] or ""),
    )


async def get_document_order(order_id: int, *, user_key: str | None = None) -> DocumentPaymentOrder | None:
    if user_key is None:
        row = await _require_pool().fetchrow(
            """
            SELECT id, user_key, case_id, case_fingerprint, document_type, language,
                   amount_kzt, status, transaction_id, receipt_check, decision_note
            FROM korgan_miniapp_document_orders
            WHERE id=$1
            """,
            order_id,
        )
    else:
        row = await _require_pool().fetchrow(
            """
            SELECT id, user_key, case_id, case_fingerprint, document_type, language,
                   amount_kzt, status, transaction_id, receipt_check, decision_note
            FROM korgan_miniapp_document_orders
            WHERE id=$1 AND user_key=$2
            """,
            order_id,
            user_key,
        )
    return _from_row(row) if row is not None else None


async def decide_document_order(
    order_id: int,
    *,
    approved: bool,
    note: str = "",
) -> bool:
    pool = _require_pool()
    if approved:
        updated = await pool.execute(
            """
            UPDATE korgan_miniapp_document_orders
            SET status='approved', decided_at=NOW(), decision_note=$2
            WHERE id=$1 AND status='awaiting_admin'
            """,
            order_id,
            note[:500],
        )
    else:
        updated = await pool.execute(
            """
            UPDATE korgan_miniapp_document_orders
            SET status='pending_receipt', receipt_hash=NULL, transaction_id=NULL,
                receipt_check=NULL, decided_at=NOW(), decision_note=$2
            WHERE id=$1 AND status='awaiting_admin'
            """,
            order_id,
            note[:500] or "payment not confirmed",
        )
    return updated.endswith("1")
