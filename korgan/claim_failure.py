"""Машиночитаемые причины отказа в пайплайне генерации иска.

Fail-closed обязан объяснять себя. Раньше все три этапа (исследование права,
составление проекта, рендеринг DOCX) были накрыты одним ``except Exception`` в
``korgan.bot``: в лог уходил только traceback, а пользователь получал одну и ту
же фразу «Проверьте материалы и повторите запрос» независимо от того, отказала
модель, сработал QA-гейт или упал шаблонизатор.

Здесь описан единый контракт отказа: этап, код, конкретные замечания и
конкретные поля. Он пишется в лог одной структурированной строкой и
разворачивается в осмысленное сообщение пользователю.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum


class ClaimStage(StrEnum):
    """Этап пайплайна, на котором произошёл отказ."""

    PREFLIGHT = "preflight"
    RESEARCH = "research"
    DRAFT = "draft"
    QA = "qa"
    RENDER = "render"


class ClaimFailureCode(StrEnum):
    """Причина отказа. Значение попадает в лог и пригодно для алертинга."""

    RESEARCH_FAILED = "RESEARCH_FAILED"
    DRAFT_FAILED = "DRAFT_FAILED"
    DRAFT_MALFORMED = "DRAFT_MALFORMED"
    QA_BLOCKED = "QA_BLOCKED"
    MISSING_DOCUMENT_FIELD = "MISSING_DOCUMENT_FIELD"
    RENDER_FAILED = "RENDER_FAILED"
    UNKNOWN = "UNKNOWN"


_USER_HEADLINE: dict[ClaimFailureCode, str] = {
    ClaimFailureCode.RESEARCH_FAILED: (
        "Не удалось проверить право по официальным источникам Казахстана."
    ),
    ClaimFailureCode.DRAFT_FAILED: "Не удалось составить проект иска.",
    ClaimFailureCode.DRAFT_MALFORMED: (
        "Проект иска вернулся в неверном формате и не может быть безопасно собран в Word."
    ),
    ClaimFailureCode.QA_BLOCKED: (
        "Финальная проверка нашла в проекте дефекты, которые нельзя исправить автоматически."
    ),
    ClaimFailureCode.MISSING_DOCUMENT_FIELD: (
        "Для сборки документа не хватает обязательных полей."
    ),
    ClaimFailureCode.RENDER_FAILED: "Не удалось собрать файл Word из готового проекта.",
    ClaimFailureCode.UNKNOWN: "Не удалось сформировать документ.",
}

_USER_NEXT_STEP: dict[ClaimFailureCode, str] = {
    ClaimFailureCode.RESEARCH_FAILED: (
        "Повторите запрос через минуту: KORGAN не составляет иск на неподтверждённом праве."
    ),
    ClaimFailureCode.DRAFT_FAILED: "Повторите запрос или уточните обстоятельства дела.",
    ClaimFailureCode.DRAFT_MALFORMED: "Повторите запрос.",
    ClaimFailureCode.QA_BLOCKED: (
        "KORGAN не отправляет в чат сырой текст иска. Уточните перечисленные пункты и повторите запрос."
    ),
    ClaimFailureCode.MISSING_DOCUMENT_FIELD: (
        "Пришлите недостающие сведения одним сообщением — я продолжу подготовку иска автоматически."
    ),
    ClaimFailureCode.RENDER_FAILED: "Повторите запрос.",
    ClaimFailureCode.UNKNOWN: "Повторите запрос.",
}


def _clean(items: list[str] | tuple[str, ...] | None) -> list[str]:
    return [str(item).strip() for item in (items or []) if str(item).strip()]


@dataclass(slots=True)
class ClaimFailure:
    """Полное описание отказа: что именно и на каком поле не прошло."""

    stage: ClaimStage
    code: ClaimFailureCode
    issues: list[str] = field(default_factory=list)
    fields: list[str] = field(default_factory=list)
    detail: str = ""

    def __post_init__(self) -> None:
        self.issues = _clean(self.issues)
        self.fields = _clean(self.fields)
        self.detail = self.detail.strip()

    def log_line(self) -> str:
        """Одна строка для лога — grep-абельная и без traceback-шума."""
        parts = [
            f"CLAIM_FAIL stage={self.stage.value}",
            f"code={self.code.value}",
            f"fields={self.fields or '-'}",
            f"issues={self.issues[:12] or '-'}",
        ]
        if self.detail:
            parts.append(f"detail={self.detail}")
        return " ".join(parts)

    def user_message(self) -> str:
        """Конкретная причина для пользователя вместо generic-отказа."""
        lines = [f"⚠️ {_USER_HEADLINE[self.code]}"]

        if self.fields:
            lines.append("")
            lines.append("Не хватает данных:")
            lines.extend(f"• {item}" for item in self.fields)

        visible_issues = [item for item in self.issues if item not in self.fields]
        if visible_issues:
            lines.append("")
            lines.append("Что именно не прошло проверку:")
            lines.extend(f"• {item}" for item in visible_issues[:6])

        lines.append("")
        lines.append(_USER_NEXT_STEP[self.code])
        return "\n".join(lines)


class ClaimPipelineError(RuntimeError):
    """Отказ пайплайна, несущий машиночитаемую причину.

    Принимает либо готовый :class:`ClaimFailure`, либо — ради обратной
    совместимости со старым ``raise CourtDocumentQualityError("текст")`` —
    обычную строку, которая тогда трактуется как блокировка на этапе QA.
    """

    def __init__(self, failure: ClaimFailure | str) -> None:
        if isinstance(failure, ClaimFailure):
            resolved = failure
        else:
            resolved = ClaimFailure(
                stage=ClaimStage.QA,
                code=ClaimFailureCode.QA_BLOCKED,
                issues=[part.strip() for part in str(failure).split(";") if part.strip()],
            )
        super().__init__(resolved.log_line())
        self.failure = resolved


class CourtDocumentQualityError(ClaimPipelineError):
    """Проект иска не прошёл детерминированные проверки судебного качества."""


def failure_from_exception(exc: BaseException, *, stage: ClaimStage) -> ClaimFailure:
    """Свести любое исключение к описанию отказа для лога и пользователя."""
    if isinstance(exc, ClaimPipelineError):
        return exc.failure

    code = {
        ClaimStage.RESEARCH: ClaimFailureCode.RESEARCH_FAILED,
        ClaimStage.DRAFT: ClaimFailureCode.DRAFT_FAILED,
        ClaimStage.QA: ClaimFailureCode.QA_BLOCKED,
        ClaimStage.RENDER: ClaimFailureCode.RENDER_FAILED,
    }.get(stage, ClaimFailureCode.UNKNOWN)

    # Схема ответа модели не сошлась с dataclass проекта иска — это технический,
    # а не юридический дефект, и он должен читаться в логе именно так.
    if isinstance(exc, (TypeError, ValueError)) and stage is ClaimStage.DRAFT:
        code = ClaimFailureCode.DRAFT_MALFORMED

    return ClaimFailure(
        stage=stage,
        code=code,
        detail=f"{type(exc).__name__}: {exc}",
    )
