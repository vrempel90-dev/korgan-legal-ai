from __future__ import annotations

import logging
from dataclasses import dataclass

import asyncpg

from korgan.config import Settings

LOGGER = logging.getLogger(__name__)
_POOL: asyncpg.Pool | None = None


@dataclass(frozen=True)
class AdminPaymentOrder:
    id: int
    status: str


def _pool() -> asyncpg.Pool:
    if _POOL is None:
        raise RuntimeError("Admin payment store is not initialized")
    return _POOL


async def init_admin_payment_store(settings: Settings) -> None:
    """Connect the Telegram admin bot to the MiniApp payment database only."""
    global _POOL
    if _POOL is not None:
        return
    dsn = str(settings.database_url or "").strip()
    if not dsn:
        raise RuntimeError("Admin payment decisions require DATABASE_URL")
    _POOL = await asyncpg.create_pool(
        dsn=dsn,
        min_size=1,
        max_size=2,
        command_timeout=15,
    )
    # Do not create or mutate the MiniApp schema here. The MiniApp API owns it.
    async with _POOL.acquire() as connection:
        exists = await connection.fetchval(
            "SELECT to_regclass('public.korgan_miniapp_document_orders') IS NOT NULL"
        )
        if not exists:
            await close_admin_payment_store()
            raise RuntimeError("MiniApp document payment table is not initialized")


async def close_admin_payment_store() -> None:
    global _POOL
    pool = _POOL
    _POOL = None
    if pool is not None:
        await pool.close()


async def get_admin_payment_order(order_id: int) -> AdminPaymentOrder | None:
    row = await _pool().fetchrow(
        "SELECT id, status FROM korgan_miniapp_document_orders WHERE id=$1",
        int(order_id),
    )
    if row is None:
        return None
    return AdminPaymentOrder(id=int(row["id"]), status=str(row["status"]))


async def decide_admin_payment_order(
    order_id: int,
    *,
    approved: bool,
    admin_id: int,
) -> bool:
    """Atomically decide an awaiting_admin order; repeat clicks are no-ops."""
    pool = _pool()
    note = f"telegram admin {int(admin_id)}: {'approved' if approved else 'rejected'}"
    async with pool.acquire() as connection:
        async with connection.transaction():
            status = await connection.fetchval(
                "SELECT status FROM korgan_miniapp_document_orders WHERE id=$1 FOR UPDATE",
                int(order_id),
            )
            if status != "awaiting_admin":
                return False
            if approved:
                result = await connection.execute(
                    """
                    UPDATE korgan_miniapp_document_orders
                    SET status='approved', decided_at=NOW(), decision_note=$2
                    WHERE id=$1 AND status='awaiting_admin'
                    """,
                    int(order_id),
                    note[:500],
                )
            else:
                # Re-open this same order for a fresh receipt. The rejected
                # receipt stays registered in the anti-replay table.
                result = await connection.execute(
                    """
                    UPDATE korgan_miniapp_document_orders
                    SET status='pending_receipt', receipt_hash=NULL, transaction_id=NULL,
                        receipt_check=NULL, decided_at=NOW(), decision_note=$2
                    WHERE id=$1 AND status='awaiting_admin'
                    """,
                    int(order_id),
                    note[:500],
                )
            changed = result.endswith("1")
            if changed:
                LOGGER.info(
                    "ADMIN_PAYMENT_DB_DECISION order_id=%s admin_id=%s approved=%s",
                    order_id,
                    admin_id,
                    approved,
                )
            return changed
