from __future__ import annotations

from contextvars import ContextVar

_contract_repair_attempted: ContextVar[bool] = ContextVar(
    "korgan_contract_repair_attempted",
    default=False,
)
_contract_repair_completed: ContextVar[bool] = ContextVar(
    "korgan_contract_repair_completed",
    default=False,
)


def reset_contract_repair_state() -> None:
    """Start one contract-generation request with no attempted or completed repair."""
    _contract_repair_attempted.set(False)
    _contract_repair_completed.set(False)


def reset_contract_repair_attempted() -> None:
    """Reset only the lower-pipeline attempt marker before entering that layer."""
    _contract_repair_attempted.set(False)


def mark_contract_repair_attempted() -> None:
    """Record that the lower production pipeline received a parsed repair payload."""
    _contract_repair_attempted.set(True)


def contract_repair_attempted() -> bool:
    """Return whether the current async request entered a parsed lower repair pass."""
    return _contract_repair_attempted.get()


def mark_contract_repair_completed() -> None:
    """Record that lower repair, reconstruction, and revalidation all completed."""
    _contract_repair_completed.set(True)


def contract_repair_completed() -> bool:
    """Return whether the current async request fully completed its lower repair pass."""
    return _contract_repair_completed.get()
