from __future__ import annotations

from datetime import datetime
import json
from typing import Any

from korgan import miniapp_document_payments as legacy
from korgan.miniapp_document_payments import DocumentPaymentOrder


def _one_row(command_tag: str) -> bool:
    try:
        return int(command_tag.rsplit(" ", 1)[-1]) == 1
    except (ValueError, IndexError):
        return False


async def get_document_order_created_at(order_id: int, *, user_key: str) -> datetime | None:
    """Return the immutable payment-offer timestamp used by receipt validation."""
    return await legacy._require_pool().fetchval(
        "SELECT created_at FROM korgan_miniapp_document_orders WHERE id=$1 AND user_key=$2",
        order_id,
        user_key,
    )


async def create_document_order_preserving_paid_scope(
    *,
    user_key: str,
    case_id: str,
    case_fingerprint: str,
    document_type: str,
    language: str,
    amount_kzt: int,
) -> DocumentPaymentOrder:
    """Create a current-scope order without cancelling an already paid scope."""
    pool = legacy._require_pool()
    async with pool.acquire() as connection:
        async with connection.transaction():
            # Only an unpaid offer can be invalidated by a changed factual scope.
            # AI-verified/legacy-held payments remain durable and retryable for
            # the exact scope they purchased.
            await connection.execute(
                """
                UPDATE korgan_miniapp_document_orders
                SET status='cancelled', decided_at=NOW(), decision_note='case scope changed before payment'
                WHERE user_key=$1 AND case_id=$2
                  AND case_fingerprint<>$3
                  AND status='pending_receipt'
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
                return legacy._from_row(existing)
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
    return legacy._from_row(row)


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

            inserted = await connection.fetchrow(
                """
                INSERT INTO korgan_miniapp_document_receipts(receipt_hash, transaction_id, order_id)
                VALUES($1,$2,$3)
                ON CONFLICT DO NOTHING
                RETURNING receipt_hash, transaction_id, order_id
                """,
                receipt_hash,
                txid,
                order_id,
            )
            if inserted is None:
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
                json.dumps(receipt_check, ensure_ascii=False),
            )
            if _one_row(updated):
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
