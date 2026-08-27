from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
from typing import Any

import asyncpg
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF


class MiniAppStore:
    """Dedicated encrypted Mini App state store.

    The production Telegram bot does not read or write this table. Telegram user
    ids are never persisted directly: only an HMAC-SHA256 lookup key is stored.
    Case state is AES-256-GCM encrypted before it reaches PostgreSQL.
    """

    def __init__(self, database_url: str, *, secret: str, retention_days: int = 30) -> None:
        self.database_url = database_url.strip()
        self.secret = secret.encode("utf-8")
        self.retention_days = max(1, min(int(retention_days), 365))
        self.pool: asyncpg.Pool | None = None
        self.memory: dict[str, dict[str, Any]] = {}
        self._encryption_key = HKDF(
            algorithm=hashes.SHA256(),
            length=32,
            salt=b"korgan-miniapp-state-v1",
            info=b"korgan-miniapp-aes-256-gcm",
        ).derive(self.secret)

    def user_key(self, user_id: str) -> str:
        return hmac.new(self.secret, str(user_id).encode("utf-8"), hashlib.sha256).hexdigest()

    def _encode_state(self, state: dict[str, Any], *, aad: str) -> dict[str, str | int]:
        plaintext = json.dumps(state, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        nonce = os.urandom(12)
        ciphertext = AESGCM(self._encryption_key).encrypt(nonce, plaintext, aad.encode("ascii"))
        return {
            "v": 1,
            "alg": "AES-256-GCM",
            "nonce": base64.b64encode(nonce).decode("ascii"),
            "ciphertext": base64.b64encode(ciphertext).decode("ascii"),
        }

    def _decode_state(self, value: Any, *, aad: str) -> tuple[dict[str, Any], bool]:
        if isinstance(value, str):
            value = json.loads(value)
        if not isinstance(value, dict):
            return {"consent": None, "cases": {}}, False

        # Backward-compatible one-time migration for the first staging rows that
        # were written before encryption was enabled.
        if value.get("v") != 1 or value.get("alg") != "AES-256-GCM":
            return dict(value), True

        try:
            nonce = base64.b64decode(str(value["nonce"]), validate=True)
            ciphertext = base64.b64decode(str(value["ciphertext"]), validate=True)
            plaintext = AESGCM(self._encryption_key).decrypt(nonce, ciphertext, aad.encode("ascii"))
            decoded = json.loads(plaintext.decode("utf-8"))
        except Exception as exc:
            raise RuntimeError("Mini App state decryption failed") from exc
        if not isinstance(decoded, dict):
            raise RuntimeError("Mini App state payload is invalid")
        return decoded, False

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
        state, needs_migration = self._decode_state(row["state_json"], aad=key)
        if needs_migration:
            await self.save(user_id, state)
        return state

    async def save(self, user_id: str, state: dict[str, Any]) -> None:
        key = self.user_key(user_id)
        if self.pool is None:
            # Keep development fallback semantics simple; memory never leaves the
            # process, while PostgreSQL always receives encrypted state.
            self.memory[key] = json.loads(json.dumps(state, ensure_ascii=False))
            return
        envelope = json.dumps(self._encode_state(state, aad=key), separators=(",", ":"))
        async with self.pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO korgan_miniapp_state(user_key, state_json, updated_at)
                VALUES($1, $2::jsonb, NOW())
                ON CONFLICT(user_key) DO UPDATE
                SET state_json=EXCLUDED.state_json, updated_at=NOW()
                """,
                key,
                envelope,
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
