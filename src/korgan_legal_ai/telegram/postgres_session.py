from __future__ import annotations

import logging
import time
from datetime import datetime, timedelta, timezone

from sqlalchemy import Engine, text

from korgan_legal_ai.telegram.crypto import SessionCrypto, SessionCryptoError
from korgan_legal_ai.telegram.session import SessionState, TelegramSession

logger = logging.getLogger(__name__)

SUPPORTED_LANGUAGES = ("ru", "kk")


class UnreadableSession(RuntimeError):
    """A stored session cannot be trusted and must be destroyed rather than guessed."""


class PostgresSessionStore:
    """Encrypted persistent Telegram sessions with pseudonymized subjects."""

    def __init__(
        self,
        engine: Engine,
        crypto: SessionCrypto,
        *,
        ttl_seconds: int = 86400,
        max_sessions: int = 5000,
        purge_interval_seconds: float = 60.0,
    ) -> None:
        if ttl_seconds <= 0:
            raise ValueError("Session TTL must be positive")
        if max_sessions <= 0:
            raise ValueError("Session capacity must be positive")
        self.engine = engine
        self.crypto = crypto
        self.ttl_seconds = ttl_seconds
        self.max_sessions = max_sessions
        self.purge_interval_seconds = purge_interval_seconds
        self._last_purge_at = 0.0

    @staticmethod
    def _now() -> datetime:
        return datetime.now(timezone.utc)

    def _expiry(self, now: datetime) -> datetime:
        return now + timedelta(seconds=self.ttl_seconds)

    def purge_expired(self) -> int:
        """Delete expired sessions and enforce the configured capacity ceiling."""
        with self.engine.begin() as connection:
            removed = int(
                connection.execute(
                    text("DELETE FROM telegram_sessions WHERE expires_at <= now()")
                ).rowcount
                or 0
            )
            # TTL alone does not bound the table: a burst of new subjects can outrun expiry,
            # so the oldest sessions beyond the ceiling are dropped as well.
            removed += int(
                connection.execute(
                    text(
                        """
                        DELETE FROM telegram_sessions
                        WHERE subject_hmac IN (
                            SELECT subject_hmac
                            FROM telegram_sessions
                            ORDER BY updated_at DESC
                            OFFSET :max_sessions
                        )
                        """
                    ),
                    {"max_sessions": self.max_sessions},
                ).rowcount
                or 0
            )
        self._last_purge_at = time.monotonic()
        return removed

    def _maybe_purge_expired(self) -> None:
        """Purge on a timer instead of on every read to keep one write per incoming update."""
        if time.monotonic() - self._last_purge_at >= self.purge_interval_seconds:
            self.purge_expired()

    def _decode(self, subject: bytes, row: dict) -> TelegramSession:
        encrypted_case = row["encrypted_case"]
        nonce = row["case_nonce"]
        case_buffer: str | None = None
        if encrypted_case is not None or nonce is not None:
            if encrypted_case is None or nonce is None:
                raise UnreadableSession("ciphertext metadata is inconsistent")
            try:
                case_buffer = self.crypto.decrypt_case(
                    subject,
                    bytes(encrypted_case),
                    bytes(nonce),
                )
            except SessionCryptoError as exc:
                raise UnreadableSession("ciphertext failed integrity verification") from exc

        try:
            state = SessionState(str(row["state"]))
        except ValueError as exc:
            raise UnreadableSession("unknown dialogue state") from exc

        language = str(row["language"])
        if language not in SUPPORTED_LANGUAGES:
            raise UnreadableSession("unsupported interface language")

        return TelegramSession(
            language=language,
            consent_version=row["consent_version"],
            state=state,
            case_buffer=case_buffer,
            updated_at=time.monotonic(),
        )

    def get(self, user_id: int) -> TelegramSession:
        self._maybe_purge_expired()
        subject = self.crypto.subject_hmac(user_id)
        now = self._now()
        # One atomic statement reads the session and slides its TTL, so a concurrent writer
        # cannot interleave between a separate SELECT and UPDATE. Expired rows are excluded
        # here as well, independently of when the timed purge last ran.
        with self.engine.begin() as connection:
            row = (
                connection.execute(
                    text(
                        """
                        UPDATE telegram_sessions
                        SET updated_at = :updated_at, expires_at = :expires_at
                        WHERE subject_hmac = :subject_hmac AND expires_at > now()
                        RETURNING language, consent_version, state, encrypted_case, case_nonce
                        """
                    ),
                    {
                        "updated_at": now,
                        "expires_at": self._expiry(now),
                        "subject_hmac": subject,
                    },
                )
                .mappings()
                .first()
            )

        if row is None:
            # A pseudonymous row is still personal data, so reading state for an unknown
            # subject must not create one. Persistence happens only when the dialogue
            # actually changes something through save().
            return TelegramSession(updated_at=time.monotonic())

        try:
            return self._decode(subject, dict(row))
        except UnreadableSession as exc:
            # Fail closed: unreadable stored state (tampering, corruption, key rotation) is
            # destroyed instead of being repaired or partially trusted. The reason never
            # carries session content.
            self.delete(user_id)
            logger.warning("Telegram session discarded, restarting dialogue: %s", exc)
            return TelegramSession(updated_at=time.monotonic())

    def save(self, user_id: int, session: TelegramSession) -> None:
        if session.language not in SUPPORTED_LANGUAGES:
            raise ValueError("Unsupported Telegram session language")

        subject = self.crypto.subject_hmac(user_id)
        encrypted_case: bytes | None = None
        nonce: bytes | None = None
        if session.case_buffer is not None:
            # A fresh nonce is generated on every write; ciphertext is never reused or updated
            # in place under an old nonce.
            encrypted = self.crypto.encrypt_case(subject, session.case_buffer)
            encrypted_case = encrypted.ciphertext
            nonce = encrypted.nonce

        now = self._now()
        expires_at = self._expiry(now)
        with self.engine.begin() as connection:
            connection.execute(
                text(
                    """
                    INSERT INTO telegram_sessions (
                        subject_hmac, language, consent_version, state,
                        encrypted_case, case_nonce, updated_at, expires_at
                    ) VALUES (
                        :subject_hmac, :language, :consent_version, :state,
                        :encrypted_case, :case_nonce, :updated_at, :expires_at
                    )
                    ON CONFLICT (subject_hmac) DO UPDATE SET
                        language = EXCLUDED.language,
                        consent_version = EXCLUDED.consent_version,
                        state = EXCLUDED.state,
                        encrypted_case = EXCLUDED.encrypted_case,
                        case_nonce = EXCLUDED.case_nonce,
                        updated_at = EXCLUDED.updated_at,
                        expires_at = EXCLUDED.expires_at
                    """
                ),
                {
                    "subject_hmac": subject,
                    "language": session.language,
                    "consent_version": session.consent_version,
                    "state": session.state.value,
                    "encrypted_case": encrypted_case,
                    "case_nonce": nonce,
                    "updated_at": now,
                    "expires_at": expires_at,
                },
            )
        session.updated_at = time.monotonic()

    def reset(self, user_id: int, *, language: str = "ru") -> TelegramSession:
        session = TelegramSession(language=language, updated_at=time.monotonic())
        self.save(user_id, session)
        return session

    def clear_case(self, user_id: int) -> TelegramSession:
        session = self.get(user_id)
        session.case_buffer = None
        session.state = SessionState.MENU if session.consent_version else SessionState.PRIVACY
        self.save(user_id, session)
        return session

    def delete(self, user_id: int) -> None:
        subject = self.crypto.subject_hmac(user_id)
        with self.engine.begin() as connection:
            connection.execute(
                text("DELETE FROM telegram_sessions WHERE subject_hmac = :subject_hmac"),
                {"subject_hmac": subject},
            )

    def ping(self) -> bool:
        with self.engine.connect() as connection:
            connection.execute(text("SELECT 1"))
        return True
