from __future__ import annotations

import hashlib
import hmac
import json
from datetime import timedelta
from typing import Any

import asyncpg


class MiniAppStore:
    """Dedicated Mini App state store.

    The production Telegram bot does not read or write this table. Telegram user
    ids are never persisted directly: only an HMAC-SHA256 lookup key is stored.
    """

    def __init__(self, database_url: str, *, secret: str, retention_days: int = 30) -> None:
        self.database_url = database_url.strip()
        self.secret = secret.encode("utf-8")
        self.retention_days = max(1, min(int(retention_days), 365))
        self.pool: asyncpg.Pool | None = None
        self.memory: dict[str, dict[str, Any]] = {}

    def user_key(self, user_id: str) -> str:
        return hmac.new(self.secret, str(user_id).encode("utf-8"), hashlib.sha256).hexdigest()

    async def open(self) -> None:
        if not self.database_url:
            return
        self.pool = await asyncpg.create_pool(self.database_url, min_size=1, max_size=5, command_timeout=30)
        async with self.pool.acquire() as conn:
            await conn.execute(
                """
                CREATE TABLE IF NOT EXISTS korgan_miniapp_state (
                    user_key TEXT PRIMARY KEY,
                    state_json JSONB NOT NULL,
                    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                )
                """
            )
            await conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_korgan_miniapp_state_updated_at "
                "ON korgan_miniapp_state(updated_at)"
            )
        await self.purge_expired()

    async def close(self) -> None:
        if self.pool is not None:
            await self.pool.close()
            self.pool = None

    async def load(self, user_id: str) -> dict[str, Any]:
        key = self.user_key(user_id)
        if self.pool is None:
            return dict(self.memory.get(key) or {"consent": None, "cases": {}})
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT state_json FROM korgan_miniapp_state WHERE user_key=$1",
                key,
            )
        if row is None:
            return {"consent": None, "cases": {}}
        value = row["state_json"]
        if isinstance(value, str):
            value = json.loads(value)
        return dict(value or {"consent": None, "cases": {}})

    async def save(self, user_id: str, state: dict[str, Any]) -> None:
        key = self.user_key(user_id)
        payload = json.dumps(state, ensure_ascii=False, separators=(",", ":"))
        if self.pool is None:
            self.memory[key] = json.loads(payload)
            return
        async with self.pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO korgan_miniapp_state(user_key, state_json, updated_at)
                VALUES($1, $2::jsonb, NOW())
                ON CONFLICT(user_key) DO UPDATE
                SET state_json=EXCLUDED.state_json, updated_at=NOW()
                """,
                key,
                payload,
            )

    async def delete(self, user_id: str) -> None:
        key = self.user_key(user_id)
        self.memory.pop(key, None)
        if self.pool is None:
            return
        async with self.pool.acquire() as conn:
            await conn.execute("DELETE FROM korgan_miniapp_state WHERE user_key=$1", key)

    async def purge_expired(self) -> int:
        if self.pool is None:
            return 0
        async with self.pool.acquire() as conn:
            result = await conn.execute(
                "DELETE FROM korgan_miniapp_state WHERE updated_at < NOW() - ($1 * INTERVAL '1 day')",
                self.retention_days,
            )
        try:
            return int(result.rsplit(" ", 1)[-1])
        except (ValueError, IndexError):
            return 0
