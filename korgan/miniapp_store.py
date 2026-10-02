from __future__ import annotations

import base64
import hashlib
import hmac
import json
import logging
import os
from typing import Any

import asyncpg
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF


LOGGER = logging.getLogger(__name__)


class MiniAppStore:
    """Dedicated encrypted Mini App state store.

    The production Telegram bot does not read or write this table. Telegram user
    ids are never persisted directly: only an HMAC-SHA256 lookup key is stored.
    Case state is AES-256-GCM encrypted before it reaches PostgreSQL.
    """

    def __init__(
        self,
        database_url: str,
        *,
        secret: str,
        legacy_secrets: tuple[str, ...] = (),
        retention_days: int = 30,
    ) -> None:
        self.database_url = database_url.strip()
        self.secret = secret.encode("utf-8")
        if not self.secret:
            raise ValueError("Mini App state secret must not be empty")
        legacy: list[bytes] = []
        for candidate in legacy_secrets:
            encoded = str(candidate or "").encode("utf-8")
            if encoded and encoded != self.secret and encoded not in legacy:
                legacy.append(encoded)
        self._legacy_secrets = tuple(legacy)
        self.retention_days = max(1, min(int(retention_days), 365))
        self.pool: asyncpg.Pool | None = None
        self.memory: dict[str, dict[str, Any]] = {}
        self._encryption_key = self._derive_encryption_key(self.secret)
        self._legacy_encryption_keys = tuple(
            self._derive_encryption_key(candidate) for candidate in self._legacy_secrets
        )

    @staticmethod
    def _derive_encryption_key(secret: bytes) -> bytes:
        return HKDF(
            algorithm=hashes.SHA256(),
            length=32,
            salt=b"korgan-miniapp-state-v1",
            info=b"korgan-miniapp-aes-256-gcm",
        ).derive(secret)

    @staticmethod
    def _hmac_user_key(secret: bytes, user_id: str) -> str:
        return hmac.new(secret, str(user_id).encode("utf-8"), hashlib.sha256).hexdigest()

    def user_key(self, user_id: str) -> str:
        return self._hmac_user_key(self.secret, user_id)

    def _candidate_user_keys(self, user_id: str) -> tuple[str, ...]:
        keys = [self.user_key(user_id)]
        for secret in self._legacy_secrets:
            candidate = self._hmac_user_key(secret, user_id)
            if candidate not in keys:
                keys.append(candidate)
        return tuple(keys)

    @staticmethod
    def _validated_user_key(user_key: str) -> str:
        key = str(user_key or "").strip().lower()
        if len(key) != 64 or any(char not in "0123456789abcdef" for char in key):
            raise ValueError("Invalid Mini App user key")
        return key

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
        except Exception as exc:
            raise RuntimeError("Mini App state envelope is invalid") from exc

        last_error: Exception | None = None
        candidate_keys = (self._encryption_key, *self._legacy_encryption_keys)
        for index, encryption_key in enumerate(candidate_keys):
            try:
                plaintext = AESGCM(encryption_key).decrypt(
                    nonce,
                    ciphertext,
                    aad.encode("ascii"),
                )
            except Exception as exc:
                last_error = exc
                continue

            try:
                decoded = json.loads(plaintext.decode("utf-8"))
            except Exception as exc:
                raise RuntimeError("Mini App state payload is invalid") from exc
            if not isinstance(decoded, dict):
                raise RuntimeError("Mini App state payload is invalid")
            return decoded, index > 0

        raise RuntimeError("Mini App state decryption failed") from last_error

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
            await conn.execute(
                """
                CREATE TABLE IF NOT EXISTS korgan_miniapp_state_quarantine (
                    id BIGSERIAL PRIMARY KEY,
                    user_key TEXT NOT NULL,
                    state_json JSONB NOT NULL,
                    reason TEXT NOT NULL,
                    quarantined_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                )
                """
            )
            await conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_korgan_miniapp_state_quarantine_user_key "
                "ON korgan_miniapp_state_quarantine(user_key)"
            )
        await self.purge_expired()

    async def close(self) -> None:
        if self.pool is not None:
            await self.pool.close()
            self.pool = None

    async def _quarantine_unreadable_state(self, key: str, reason: str) -> bool:
        """Atomically preserve an unreadable row and remove it from the hot path."""
        if self.pool is None:
            return self.memory.pop(key, None) is not None

        async with self.pool.acquire() as conn:
            async with conn.transaction():
                row = await conn.fetchrow(
                    "DELETE FROM korgan_miniapp_state WHERE user_key=$1 RETURNING state_json",
                    key,
                )
                if row is None:
                    return False
                payload = json.dumps(row["state_json"], ensure_ascii=False, separators=(",", ":"))
                await conn.execute(
                    """
                    INSERT INTO korgan_miniapp_state_quarantine(user_key, state_json, reason, quarantined_at)
                    VALUES($1, $2::jsonb, $3, NOW())
                    """,
                    key,
                    payload,
                    str(reason or "unreadable state")[:500],
                )
        return True

    async def _load_existing_by_user_key(self, user_key: str) -> dict[str, Any] | None:
        key = self._validated_user_key(user_key)
        if self.pool is None:
            if key not in self.memory:
                return None
            return json.loads(json.dumps(self.memory[key], ensure_ascii=False))

        async with self.pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT state_json FROM korgan_miniapp_state WHERE user_key=$1",
                key,
            )
        if row is None:
            return None

        try:
            state, needs_migration = self._decode_state(row["state_json"], aad=key)
        except RuntimeError as exc:
            quarantined = await self._quarantine_unreadable_state(key, str(exc))
            LOGGER.warning(
                "Mini App state quarantined user_key_prefix=%s quarantined=%s reason=%s",
                key[:12],
                quarantined,
                exc,
            )
            return None

        if needs_migration:
            # Re-encrypt in place with the permanent primary state key. This
            # preserves the persisted HMAC lookup key used by already-created
            # payment orders while removing dependence on a rotated bot token.
            await self.save_by_user_key(key, state)
        return state

    async def load_by_user_key(self, user_key: str) -> dict[str, Any]:
        """Load encrypted state using only the persisted HMAC lookup key.

        Background payment jobs may hold a legacy HMAC key. The stored row is
        therefore decrypted with the primary key first and legacy keys second;
        successful legacy decrypts are transparently re-encrypted in place.
        """
        state = await self._load_existing_by_user_key(user_key)
        return state if state is not None else {"consent": None, "cases": {}}

    async def save_by_user_key(self, user_key: str, state: dict[str, Any]) -> None:
        """Persist encrypted state by its HMAC lookup key for background work."""
        key = self._validated_user_key(user_key)
        if self.pool is None:
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

    async def load(self, user_id: str) -> dict[str, Any]:
        keys = self._candidate_user_keys(user_id)
        primary_key = keys[0]
        for index, key in enumerate(keys):
            state = await self._load_existing_by_user_key(key)
            if state is None:
                continue
            if index > 0:
                # Migrate the lookup key as soon as the user returns. Existing
                # payment orders keep their legacy row key until they finish,
                # so the old row is intentionally retained.
                await self.save_by_user_key(primary_key, state)
            return state
        return {"consent": None, "cases": {}}

    async def save(self, user_id: str, state: dict[str, Any]) -> None:
        await self.save_by_user_key(self.user_key(user_id), state)

    async def delete(self, user_id: str) -> None:
        keys = self._candidate_user_keys(user_id)
        for key in keys:
            self.memory.pop(key, None)
        if self.pool is None:
            return
        async with self.pool.acquire() as conn:
            await conn.execute(
                "DELETE FROM korgan_miniapp_state WHERE user_key = ANY($1::text[])",
                list(keys),
            )

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
