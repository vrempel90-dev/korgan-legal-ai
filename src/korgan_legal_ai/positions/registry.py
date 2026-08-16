from __future__ import annotations

from datetime import date
from functools import lru_cache
from pathlib import Path

import yaml

from korgan_legal_ai.positions.models import LegalPosition

# Bundled inside the package, like the house-style rule sets: the file must be present wherever
# the code runs, including an installed wheel with no repository checkout around it.
POSITIONS_DIR = Path(__file__).resolve().parent
DEFAULT_VERSION = 1

# Questions the engine must have an answer to before it can compute. Each one is a real ambiguity
# that surfaced from a case, not a hypothetical: the engine cannot proceed without picking a
# reading, so the reading is recorded rather than buried in a branch.
KNOWN_QUESTIONS: dict[str, tuple[str, tuple[str, ...], str]] = {
    "penalty_cap_base": (
        "От какой суммы считается договорный потолок неустойки вида «не более N% от суммы "
        "задолженности»: от долга на дату наступления просрочки или от остатка долга на дату "
        "расчёта?",
        ("defaulted_debt", "remaining_balance"),
        "defaulted_debt",
    ),
}


class PositionRegistry:
    """Loaded set of firm positions, pinned by version."""

    def __init__(self, version: int, positions: dict[str, LegalPosition]) -> None:
        self.version = version
        self._positions = positions

    def get(self, key: str) -> LegalPosition | None:
        return self._positions.get(key)

    def decision(self, key: str) -> str:
        """The recorded decision, or the engine's documented default if none is recorded yet.

        A missing record is not an error: it means nobody has ruled on the question, and the
        default is what the engine has always done. The calculation reports the ambiguity
        separately, so an unrecorded question is visible rather than silent.
        """
        position = self._positions.get(key)
        if position is not None:
            return position.decision
        known = KNOWN_QUESTIONS.get(key)
        if known is None:
            raise KeyError(f"Unknown legal position: {key}")
        return known[2]

    def all(self) -> tuple[LegalPosition, ...]:
        return tuple(self._positions.values())

    def unanswered(self) -> tuple[str, ...]:
        return tuple(key for key in KNOWN_QUESTIONS if key not in self._positions)


def _path(version: int) -> Path:
    return POSITIONS_DIR / f"legal_positions.v{version}.yaml"


def _parse(payload: dict) -> dict[str, LegalPosition]:
    positions: dict[str, LegalPosition] = {}
    for item in payload.get("positions") or []:
        key = str(item["key"])
        known = KNOWN_QUESTIONS.get(key)
        options = tuple(item.get("options") or (known[1] if known else ()))
        decided_at = item["decided_at"]
        positions[key] = LegalPosition(
            key=key,
            question=str(item.get("question") or (known[0] if known else "")),
            decision=str(item["decision"]),
            options=options,
            rationale=str(item.get("rationale") or ""),
            decided_by=str(item.get("decided_by") or ""),
            decided_at=decided_at if isinstance(decided_at, date) else date.fromisoformat(str(decided_at)),
            practice_reference=str(item.get("practice_reference") or ""),
            confirmed=bool(item.get("confirmed", False)),
        )
    return positions


@lru_cache(maxsize=8)
def load_positions(version: int = DEFAULT_VERSION) -> PositionRegistry:
    path = _path(version)
    if not path.is_file():
        return PositionRegistry(version=version, positions={})
    payload = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return PositionRegistry(version=int(payload.get("version", version)), positions=_parse(payload))


def save_position(position: LegalPosition, *, version: int = DEFAULT_VERSION) -> Path:
    """Write or replace one position, keeping the file readable and diffable.

    The file lives in the repository rather than a database on purpose: an interpretive choice that
    changes what the system computes should go through the same review as code, and the calculation
    layer must stay usable without a database.
    """
    problems = position.validate()
    if problems:
        raise ValueError("; ".join(problems))

    path = _path(version)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = yaml.safe_load(path.read_text(encoding="utf-8")) if path.is_file() else None
    payload = payload or {"version": version, "positions": []}
    entries = [item for item in (payload.get("positions") or []) if item.get("key") != position.key]
    entries.append(
        {
            "key": position.key,
            "question": position.question,
            "decision": position.decision,
            "options": list(position.options),
            "rationale": position.rationale,
            "practice_reference": position.practice_reference,
            "decided_by": position.decided_by,
            "decided_at": position.decided_at.isoformat(),
            "confirmed": position.confirmed,
        }
    )
    payload["positions"] = sorted(entries, key=lambda item: item["key"])
    payload["version"] = version
    path.write_text(
        yaml.safe_dump(payload, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )
    load_positions.cache_clear()
    return path
