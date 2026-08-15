from __future__ import annotations

import json
from dataclasses import dataclass, field

from korgan_legal_ai.blueprints.interview import UNKNOWN, InterviewField, field_by_id
from korgan_legal_ai.blueprints.models import DocumentBlueprint
from korgan_legal_ai.blueprints.registry import blueprint_by_key

# The interview lives inside the same encrypted unfinished-case buffer as free-text case data, so it
# inherits that buffer's encryption, TTL and deletion rules instead of introducing a second store of
# client answers. The marker distinguishes a structured interview from plain case text.
STATE_MARKER = "KORGAN_INTERVIEW_V1"


@dataclass
class InterviewState:
    """Answers collected so far for one guided document request."""

    blueprint_key: str
    answers: dict[str, object] = field(default_factory=dict)
    asked: list[str] = field(default_factory=list)

    @property
    def blueprint(self) -> DocumentBlueprint:
        return blueprint_by_key(self.blueprint_key)

    def applicable_fields(self) -> list[InterviewField]:
        """Questions that apply given the answers already given.

        A dependent question only exists once its trigger has an answer, so the dialogue never asks
        about a power of attorney when the signatory is the director, or about a pretrial demand
        date when the contract requires no pretrial step.
        """
        result: list[InterviewField] = []
        for field_id in self.blueprint.interview_fields:
            spec = field_by_id(field_id)
            if not self._depends_satisfied(spec):
                continue
            result.append(spec)
        return result

    def _depends_satisfied(self, spec: InterviewField) -> bool:
        if not spec.depends_on:
            return True
        actual = self.answers.get(spec.depends_on)
        if actual is None or actual == UNKNOWN:
            return False
        expected = spec.depends_value
        if expected.startswith("!"):
            return str(actual) != expected[1:]
        return str(actual) == expected

    def next_field(self) -> InterviewField | None:
        for spec in self.applicable_fields():
            if spec.id not in self.answers:
                return spec
        return None

    def missing_required(self) -> list[InterviewField]:
        """Required questions that are still unanswered.

        Generation is blocked while this is non-empty. A question answered "не знаю" counts as
        answered: the user has told us the value is undetermined, which the document reports as
        NEEDS_VERIFICATION rather than silently filling in.
        """
        return [
            spec
            for spec in self.applicable_fields()
            if spec.required and spec.id not in self.answers
        ]

    def record(self, field_id: str, value: object) -> None:
        self.answers[field_id] = value
        if field_id not in self.asked:
            self.asked.append(field_id)
        # An answer can invalidate a dependent question that was already answered — for example
        # switching the signatory to the director drops the power-of-attorney answer.
        applicable = {spec.id for spec in self.applicable_fields()}
        for stale in [key for key in self.answers if key not in applicable]:
            del self.answers[stale]

    def progress(self) -> tuple[int, int]:
        applicable = self.applicable_fields()
        answered = sum(1 for spec in applicable if spec.id in self.answers)
        return answered, len(applicable)

    def serialize(self) -> str:
        payload = {"blueprint": self.blueprint_key, "answers": self.answers, "asked": self.asked}
        return f"{STATE_MARKER}\n{json.dumps(payload, ensure_ascii=False)}"

    @classmethod
    def deserialize(cls, buffer: str | None) -> InterviewState | None:
        if not buffer or not buffer.startswith(STATE_MARKER):
            return None
        _, _, raw = buffer.partition("\n")
        try:
            payload = json.loads(raw)
            state = cls(
                blueprint_key=str(payload["blueprint"]),
                answers=dict(payload.get("answers") or {}),
                asked=list(payload.get("asked") or []),
            )
            state.blueprint  # noqa: B018 - validates that the stored blueprint still exists
        except (ValueError, KeyError, TypeError):
            # Unreadable stored state is never partially trusted; the caller restarts the dialogue.
            return None
        return state
