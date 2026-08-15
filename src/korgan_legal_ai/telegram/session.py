from __future__ import annotations

import time
from dataclasses import dataclass
from enum import StrEnum
from threading import RLock
from typing import Protocol


class SessionState(StrEnum):
    LANGUAGE = "language"
    PRIVACY = "privacy"
    MENU = "menu"
    AWAITING_CLAIM = "awaiting_claim"
    AWAITING_CLARIFICATION = "awaiting_clarification"
    AWAITING_DOCUMENTS = "awaiting_documents"
    AWAITING_DOCUMENT_CLARIFICATION = "awaiting_document_clarification"


@dataclass
class TelegramSession:
    language: str = "ru"
    consent_version: str | None = None
    state: SessionState = SessionState.LANGUAGE
    case_buffer: str | None = None
    updated_at: float = 0.0


class SessionStore(Protocol):
    def get(self, user_id: int) -> TelegramSession: ...

    def save(self, user_id: int, session: TelegramSession) -> None: ...

    def reset(self, user_id: int, *, language: str = "ru") -> TelegramSession: ...

    def clear_case(self, user_id: int) -> TelegramSession: ...

    def delete(self, user_id: int) -> None: ...


class InMemorySessionStore:
    """Development/test session backend.

    Production entrypoints use the encrypted PostgreSQL repository explicitly and do not silently
    downgrade to this in-memory backend when secure persistence is misconfigured.
    """

    def __init__(self, *, ttl_seconds: int = 86400, max_sessions: int = 5000) -> None:
        self.ttl_seconds = ttl_seconds
        self.max_sessions = max_sessions
        self._items: dict[int, TelegramSession] = {}
        self._lock = RLock()

    def _now(self) -> float:
        return time.monotonic()

    def _purge_expired(self, now: float) -> None:
        expired = [
            key for key, value in self._items.items()
            if value.updated_at and now - value.updated_at > self.ttl_seconds
        ]
        for key in expired:
            del self._items[key]

    def get(self, user_id: int) -> TelegramSession:
        now = self._now()
        with self._lock:
            self._purge_expired(now)
            session = self._items.get(user_id)
            if session is None:
                if len(self._items) >= self.max_sessions:
                    oldest = min(self._items, key=lambda key: self._items[key].updated_at)
                    del self._items[oldest]
                session = TelegramSession(updated_at=now)
                self._items[user_id] = session
            session.updated_at = now
            return session

    def save(self, user_id: int, session: TelegramSession) -> None:
        now = self._now()
        with self._lock:
            self._purge_expired(now)
            session.updated_at = now
            self._items[user_id] = session

    def reset(self, user_id: int, *, language: str = "ru") -> TelegramSession:
        session = TelegramSession(language=language, updated_at=self._now())
        self.save(user_id, session)
        return session

    def clear_case(self, user_id: int) -> TelegramSession:
        session = self.get(user_id)
        session.case_buffer = None
        session.state = SessionState.MENU if session.consent_version else SessionState.PRIVACY
        self.save(user_id, session)
        return session

    def delete(self, user_id: int) -> None:
        with self._lock:
            self._items.pop(user_id, None)
