from __future__ import annotations

import asyncio
import hashlib
from contextlib import asynccontextmanager
from typing import Any, AsyncIterator

# Keep at least two connections free in the payment pools (max_size=4) while a
# long legal generation/delivery is protected by a session advisory lock. This
# prevents lock-holder starvation under multiple concurrent paid operations.
_LOCAL_SLOTS = asyncio.Semaphore(2)

# These namespaces guard only the short, durable job enqueue/reset transaction.
# They must not wait behind unrelated long paid operations: doing so can keep
# POST /miniapp/documents/generate open until the client times out even though
# the persisted generation is later started and billed by the AI provider.
_SHORT_JOB_NAMESPACES = frozenset({
    "miniapp-generation-start",
    "miniapp-generation-retry",
})


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
    small local semaphore bounds only long operations. Durable generation job
    enqueue/reset is intentionally exempt: it is short and must return a job to
    the Mini App without waiting behind unrelated provider work.
    """
    key = payment_lock_key(namespace, identity)
    use_local_slot = namespace not in _SHORT_JOB_NAMESPACES
    if use_local_slot:
        await _LOCAL_SLOTS.acquire()
    try:
        async with pool.acquire() as connection:
            await connection.execute("SELECT pg_advisory_lock($1)", key)
            try:
                yield
            finally:
                await connection.execute("SELECT pg_advisory_unlock($1)", key)
    finally:
        if use_local_slot:
            _LOCAL_SLOTS.release()
