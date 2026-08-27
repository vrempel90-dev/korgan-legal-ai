from __future__ import annotations

from datetime import datetime

from korgan import consultation_quota as quota
from korgan.consultation_quota import ConsultationOrder


async def get_consultation_order_created_at(order_id: int, *, user_id: int) -> datetime | None:
    return await quota._require_pool().fetchval(
        "SELECT created_at FROM consultation_payment_orders WHERE id=$1 AND user_id=$2",
        order_id,
        user_id,
    )


async def get_latest_open_consultation_order(user_id: int) -> ConsultationOrder | None:
    row = await quota._require_pool().fetchrow(
        """
        SELECT id, user_id, chat_id, question, case_context, language, amount_kzt, status
        FROM consultation_payment_orders
        WHERE user_id=$1 AND status IN ('pending', 'paid')
        ORDER BY id DESC
        LIMIT 1
        """,
        user_id,
    )
    return quota._order_from_row(row) if row is not None else None


async def accept_ai_verified_consultation_receipt(
    *,
    order_id: int,
    user_id: int,
    receipt_hash: str,
    transaction_id: str,
) -> bool:
    """Bind a verified consultation receipt idempotently to its current order."""
    txid = transaction_id.strip() or None
    pool = quota._require_pool()
    async with pool.acquire() as connection:
        async with connection.transaction():
            order = await connection.fetchrow(
                """
                SELECT status, receipt_hash, transaction_id
                FROM consultation_payment_orders
                WHERE id=$1 AND user_id=$2
                FOR UPDATE
                """,
                order_id,
                user_id,
            )
            if order is None:
                return False
            status = str(order["status"] or "")
            if status == "paid":
                return bool(
                    str(order["receipt_hash"] or "") == receipt_hash
                    and str(order["transaction_id"] or "") == str(txid or "")
                )
            if status != "pending":
                return False

            inserted = await connection.fetchrow(
                """
                INSERT INTO consultation_receipts(receipt_hash, transaction_id, user_id, order_id)
                VALUES($1,$2,$3,$4)
                ON CONFLICT DO NOTHING
                RETURNING order_id
                """,
                receipt_hash,
                txid,
                user_id,
                order_id,
            )
            if inserted is None:
                existing = await connection.fetchrow(
                    """
                    SELECT user_id, order_id
                    FROM consultation_receipts
                    WHERE receipt_hash=$1
                       OR ($2::text IS NOT NULL AND transaction_id=$2)
                    LIMIT 1
                    """,
                    receipt_hash,
                    txid,
                )
                if (
                    existing is None
                    or int(existing["user_id"]) != user_id
                    or int(existing["order_id"]) != order_id
                ):
                    return False

            updated = await connection.execute(
                """
                UPDATE consultation_payment_orders
                SET status='paid', receipt_hash=$3, transaction_id=$4, paid_at=NOW()
                WHERE id=$1 AND user_id=$2 AND status='pending'
                """,
                order_id,
                user_id,
                receipt_hash,
                txid,
            )
            return updated.endswith("1")
