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
    global _POOL
    if not settings.payments_enabled:
        return
    if not settings.database_url.strip():
        raise RuntimeError("PAYMENTS_ENABLED requires DATABASE_URL for Mini App document payments")
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


async def get_scope_order(
    *,
    user_key: str,
    case_id: str,
    case_fingerprint: str,
) -> DocumentPaymentOrder | None:
    row = await _require_pool().fetchrow(
        """
        SELECT id, user_key, case_id, case_fingerprint, document_type, language,
               amount_kzt, status, transaction_id, receipt_check, decision_note
        FROM korgan_miniapp_document_orders
        WHERE user_key=$1 AND case_id=$2 AND case_fingerprint=$3
          AND status IN ('pending_receipt', 'awaiting_admin', 'approved')
        ORDER BY id DESC
        LIMIT 1
        """,
        user_key,
        case_id,
        case_fingerprint,
    )
    return _from_row(row) if row is not None else None


async def create_document_order(
    *,
    user_key: str,
    case_id: str,
    case_fingerprint: str,
    document_type: str,
    language: str,
    amount_kzt: int,
) -> DocumentPaymentOrder:
    pool = _require_pool()
    async with pool.acquire() as connection:
        async with connection.transaction():
            # Payment is bound to an immutable case scope. Any previous unpaid
            # scope for this same case becomes invalid as soon as facts change.
            await connection.execute(
                """
                UPDATE korgan_miniapp_document_orders
                SET status='cancelled', decided_at=NOW(), decision_note='case scope changed'
                WHERE user_key=$1 AND case_id=$2
                  AND case_fingerprint<>$3
                  AND status IN ('pending_receipt', 'awaiting_admin', 'approved')
                """,
                user_key,
                case_id,
                case_fingerprint,
            )
            existing = await connection.fetchrow(
                """
                SELECT id, user_key, case_id, case_fingerprint, document_type, language,
                       amount_kzt, status, transaction_id, receipt_check, decision_note
                FROM korgan_miniapp_document_orders
                WHERE user_key=$1 AND case_id=$2 AND case_fingerprint=$3
                  AND status IN ('pending_receipt', 'awaiting_admin', 'approved')
                ORDER BY id DESC LIMIT 1
                FOR UPDATE
                """,
                user_key,
                case_id,
                case_fingerprint,
            )
            if existing is not None:
                return _from_row(existing)
            row = await connection.fetchrow(
                """
                INSERT INTO korgan_miniapp_document_orders(
                    user_key, case_id, case_fingerprint, document_type, language, amount_kzt
                ) VALUES($1,$2,$3,$4,$5,$6)
                RETURNING id, user_key, case_id, case_fingerprint, document_type, language,
                          amount_kzt, status, transaction_id, receipt_check, decision_note
                """,
                user_key,
                case_id,
                case_fingerprint,
                document_type,
                language,
                amount_kzt,
            )
    assert row is not None
    return _from_row(row)


async def accept_document_receipt_precheck(
    *,
    order_id: int,
    user_key: str,
    receipt_hash: str,
    transaction_id: str,
    receipt_check: dict[str, Any],
) -> bool:
    txid = transaction_id.strip() or None
    pool = _require_pool()
    try:
        async with pool.acquire() as connection:
            async with connection.transaction():
                status = await connection.fetchval(
                    "SELECT status FROM korgan_miniapp_document_orders WHERE id=$1 AND user_key=$2 FOR UPDATE",
                    order_id,
                    user_key,
                )
                if status != "pending_receipt":
                    return False
                await connection.execute(
                    """
                    INSERT INTO korgan_miniapp_document_receipts(receipt_hash, transaction_id, order_id)
                    VALUES($1,$2,$3)
                    """,
                    receipt_hash,
                    txid,
                    order_id,
                )
                updated = await connection.execute(
                    """
                    UPDATE korgan_miniapp_document_orders
                    SET status='awaiting_admin', receipt_hash=$3, transaction_id=$4,
                        receipt_check=$5::jsonb, receipt_at=NOW(), decision_note=''
                    WHERE id=$1 AND user_key=$2 AND status='pending_receipt'
                    """,
                    order_id,
                    user_key,
                    receipt_hash,
                    txid,
                    json.dumps(receipt_check, ensure_ascii=False),
                )
                return updated.endswith("1")
    except asyncpg.UniqueViolationError:
        return False


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
        # Rejection reopens this same order for a fresh receipt. The rejected
        # receipt remains globally registered so it cannot be reused.
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


async def consume_document_order(order_id: int, *, user_key: str) -> bool:
    updated = await _require_pool().execute(
        """
        UPDATE korgan_miniapp_document_orders
        SET status='consumed', consumed_at=NOW()
        WHERE id=$1 AND user_key=$2 AND status='approved'
        """,
        order_id,
        user_key,
    )
    return updated.endswith("1")


async def list_document_orders_for_admin(*, status: str = "awaiting_admin", limit: int = 50) -> list[DocumentPaymentOrder]:
    allowed = {"pending_receipt", "awaiting_admin", "approved", "consumed", "cancelled"}
    wanted = status if status in allowed else "awaiting_admin"
    rows = await _require_pool().fetch(
        """
        SELECT id, user_key, case_id, case_fingerprint, document_type, language,
               amount_kzt, status, transaction_id, receipt_check, decision_note
        FROM korgan_miniapp_document_orders
        WHERE status=$1
        ORDER BY id DESC
        LIMIT $2
        """,
        wanted,
        max(1, min(int(limit), 100)),
    )
    return [_from_row(row) for row in rows]
