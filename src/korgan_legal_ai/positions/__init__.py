"""Recorded firm positions on questions the law leaves open.

Kept apart from the corpus of norms: a norm is the text of the law, a position is a reading of it.
Mixing them would let an interpretation be cited as if it were legislation.
"""

from korgan_legal_ai.positions.models import LegalPosition
from korgan_legal_ai.positions.registry import (
    KNOWN_QUESTIONS,
    PositionRegistry,
    load_positions,
    save_position,
)

__all__ = [
    "KNOWN_QUESTIONS",
    "LegalPosition",
    "PositionRegistry",
    "load_positions",
    "save_position",
]
