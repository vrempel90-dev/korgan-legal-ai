from __future__ import annotations

from dataclasses import dataclass
from datetime import date


@dataclass(frozen=True)
class LegalPosition:
    """The firm's answer to a legal question the law does not settle on its own.

    This is not law and is never presented as law. It is an interpretive choice — which reading of
    an ambiguous contractual or statutory phrase the system applies — recorded so that the choice
    is visible, attributable and changeable without touching code.

    ``rationale`` carries either a reference to court practice or an explicit statement that this
    is the legal department's own position. The distinction matters to whoever reviews it later.
    """

    key: str
    question: str
    decision: str
    options: tuple[str, ...]
    rationale: str
    decided_by: str
    decided_at: date
    practice_reference: str = ""
    confirmed: bool = False

    def validate(self) -> list[str]:
        problems: list[str] = []
        if self.decision not in self.options:
            problems.append(
                f"решение «{self.decision}» не входит в допустимые варианты: "
                + ", ".join(self.options)
            )
        for name in ("question", "rationale", "decided_by"):
            if not str(getattr(self, name) or "").strip():
                problems.append(f"не заполнено обязательное поле: {name}")
        return problems

    @property
    def source_label(self) -> str:
        return self.practice_reference or "внутренняя позиция юридического отдела"
