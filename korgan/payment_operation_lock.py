from __future__ import annotations

import asyncio
import hashlib
from contextlib import asynccontextmanager
from typing import Any, AsyncIterator

# Keep at least two connections free in the payment pools (max_size=4) while a
# long legal generation/delivery is protected by a session advisory lock. This
# prevents lock-holder starvation under multiple concurrent paid operations.
_LOCAL_SLOTS = asyncio.Semaphore(2)


def payment_lock_key(namespace: str, identity: object) -> int:
    payload = f"korgan-payment:{namespace}:{identity}".encode("utf-8")
    digest = hashlib.sha256(payload).digest()
    return int.from_bytes(digest[:8], "big") & ((1 << 63) - 1)


@asynccontextmanager
async def payment_operation_lock(
    pool: Any,
    namespace: str,
    identity: object,
) -> AsyncIterator[None]:
    """Serialize one paid operation across processes/replicas.

    The PostgreSQL session advisory lock is the cross-process authority. The
    small local semaphore only bounds how many pool connections can be held by
    long operations so nested store calls cannot exhaust the four-connection
    payment pool.
    """
    key = payment_lock_key(namespace, identity)
    async with _LOCAL_SLOTS:
        async with pool.acquire() as connection:
            await connection.execute("SELECT pg_advisory_lock($1)", key)
            try:
                yield
            finally:
                await connection.execute("SELECT pg_advisory_unlock($1)", key)
