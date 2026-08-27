from __future__ import annotations

from datetime import datetime
from typing import Any

import asyncpg

from korgan import miniapp_document_payments as legacy


async def get_document_order_created_at(order_id: int, *, user_key: str) -> datetime | None:
    """Return the immutable payment-offer timestamp used by receipt validation."""
    return await legacy._require_pool().fetchval(
        "SELECT created_at FROM korgan_miniapp_document_orders WHERE id=$1 AND user_key=$2",
        order_id,
        user_key,
    )


async def accept_ai_verified_document_receipt(
    *,
    order_id: int,
    user_key: str,
    receipt_hash: str,
    transaction_id: str,
    receipt_check: dict[str, Any],
) -> bool:
    """Atomically bind one verified receipt to one order and mark it approved.

    The same receipt/order pair is idempotent. Reuse for another order remains
    blocked by the global receipt hash / transaction-id uniqueness constraints.
    """
    txid = transaction_id.strip() or None
    pool = legacy._require_pool()
    async with pool.acquire() as connection:
        async with connection.transaction():
            order = await connection.fetchrow(
                """
                SELECT id, status, receipt_hash, transaction_id
                FROM korgan_miniapp_document_orders
                WHERE id=$1 AND user_key=$2
                FOR UPDATE
                """,
                order_id,
                user_key,
            )
            if order is None:
                return False

            status = str(order["status"] or "")
            if status == "approved":
                same_hash = str(order["receipt_hash"] or "") == receipt_hash
                same_tx = str(order["transaction_id"] or "") == str(txid or "")
                return bool(same_hash and same_tx)
            if status not in {"pending_receipt", "awaiting_admin"}:
                return False

            try:
                await connection.execute(
                    """
                    INSERT INTO korgan_miniapp_document_receipts(receipt_hash, transaction_id, order_id)
                    VALUES($1,$2,$3)
                    """,
                    receipt_hash,
                    txid,
                    order_id,
                )
            except asyncpg.UniqueViolationError:
                existing = await connection.fetchrow(
                    """
                    SELECT receipt_hash, transaction_id, order_id
                    FROM korgan_miniapp_document_receipts
                    WHERE receipt_hash=$1
                       OR ($2::text IS NOT NULL AND transaction_id=$2)
                    LIMIT 1
                    """,
                    receipt_hash,
                    txid,
                )
                if existing is None or int(existing["order_id"]) != order_id:
                    return False

            updated = await connection.execute(
                """
                UPDATE korgan_miniapp_document_orders
                SET status='approved', receipt_hash=$3, transaction_id=$4,
                    receipt_check=$5::jsonb, receipt_at=COALESCE(receipt_at, NOW()),
                    decided_at=NOW(), decision_note='AI receipt verification passed'
                WHERE id=$1 AND user_key=$2
                  AND status IN ('pending_receipt', 'awaiting_admin')
                """,
                order_id,
                user_key,
                receipt_hash,
                txid,
                __import__("json").dumps(receipt_check, ensure_ascii=False),
            )
            if updated.endswith("1"):
                return True

            final = await connection.fetchrow(
                """
                SELECT status, receipt_hash, transaction_id
                FROM korgan_miniapp_document_orders
                WHERE id=$1 AND user_key=$2
                """,
                order_id,
                user_key,
            )
            return bool(
                final
                and str(final["status"] or "") == "approved"
                and str(final["receipt_hash"] or "") == receipt_hash
                and str(final["transaction_id"] or "") == str(txid or "")
            )
