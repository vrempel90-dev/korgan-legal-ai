"""Deterministic guided fact collection.

The free-text path asks a model to extract facts from prose. This path asks the user one validated
question at a time, so every amount, date, party and document is typed by a human and parsed by
deterministic code. No model participates in producing the locked case, which means the guided path
cannot misread a figure, and completeness is checked before drafting starts rather than discovered
afterwards.
"""

from korgan_legal_ai.interview.answers import ParsedAnswer, parse_answer
from korgan_legal_ai.interview.builder import build_locked_case, build_routing, classify_evidence
from korgan_legal_ai.interview.state import STATE_MARKER, InterviewState

__all__ = [
    "STATE_MARKER",
    "InterviewState",
    "ParsedAnswer",
    "build_locked_case",
    "build_routing",
    "classify_evidence",
    "parse_answer",
]
