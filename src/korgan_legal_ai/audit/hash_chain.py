from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any


@dataclass(frozen=True)
class AuditEntry:
    timestamp: str
    event: str
    payload: dict[str, Any]
    previous_hash: str
    hash: str


class HashChainAuditLog:
    def __init__(self) -> None:
        self.entries: list[AuditEntry] = []

    @property
    def head(self) -> str:
        return self.entries[-1].hash if self.entries else "GENESIS"

    def append(self, event: str, payload: dict[str, Any]) -> AuditEntry:
        timestamp = datetime.now(timezone.utc).isoformat()
        previous_hash = self.head
        canonical = json.dumps(
            {"timestamp": timestamp, "event": event, "payload": payload, "previous_hash": previous_hash},
            ensure_ascii=False,
            sort_keys=True,
            default=str,
        )
        digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
        entry = AuditEntry(timestamp, event, payload, previous_hash, digest)
        self.entries.append(entry)
        return entry

    def verify(self) -> bool:
        previous = "GENESIS"
        for entry in self.entries:
            canonical = json.dumps(
                {
                    "timestamp": entry.timestamp,
                    "event": entry.event,
                    "payload": entry.payload,
                    "previous_hash": previous,
                },
                ensure_ascii=False,
                sort_keys=True,
                default=str,
            )
            if hashlib.sha256(canonical.encode("utf-8")).hexdigest() != entry.hash:
                return False
            previous = entry.hash
        return True
