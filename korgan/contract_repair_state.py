from __future__ import annotations

from contextvars import ContextVar

_contract_repair_completed: ContextVar[bool] = ContextVar(
    "korgan_contract_repair_completed",
    default=False,
)


def reset_contract_repair_state() -> None:
    """Start one contract-generation request with no completed repair."""
    _contract_repair_completed.set(False)


def mark_contract_repair_completed() -> None:
    """Record that the lower production contract pipeline completed its repair."""
    _contract_repair_completed.set(True)


def contract_repair_completed() -> bool:
    """Return whether the current async request already consumed its repair pass."""
    return _contract_repair_completed.get()
