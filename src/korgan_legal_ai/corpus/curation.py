from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, timezone

from korgan_legal_ai.blueprints.registry import supported_document_types
from korgan_legal_ai.corpus.models import (
    CorpusStatus,
    LegalNorm,
    default_next_review,
)
from korgan_legal_ai.corpus.repository import LegalNormRepository
from korgan_legal_ai.research.gateway import TRUSTED_KZ_DOMAINS, is_trusted_official_url


class CurationError(ValueError):
    """A submission that must be corrected before it can enter the corpus."""


@dataclass(frozen=True)
class SourceCheck:
    """Result of checking where a norm's text was taken from."""

    url: str
    official: bool
    message: str


@dataclass(frozen=True)
class NormSubmission:
    """What a lawyer supplies to record one norm.

    Every field required to cite the norm later is required here. A record that cannot support a
    citation has no reason to be in the corpus: it would sit there looking verified while being
    unusable, which is worse than its absence.
    """

    code_id: str
    article_number: str
    text: str
    effective_from: date
    source_url: str
    reviewed_by: str
    law_name: str | None = None
    title: str | None = None
    part: str = ""
    point: str = ""
    effective_to: date | None = None
    applicable_document_types: tuple[str, ...] = ()
    next_review_date: date | None = None
    review_months: int = 6

    REQUIRED = ("code_id", "article_number", "text", "source_url", "reviewed_by")

    def validate(self) -> list[str]:
        """Collect every problem at once, so a lawyer fixes one form rather than five rejections."""
        problems: list[str] = []
        for name in self.REQUIRED:
            if not str(getattr(self, name) or "").strip():
                problems.append(f"не заполнено обязательное поле: {name}")

        if self.effective_to is not None and self.effective_to < self.effective_from:
            problems.append("дата окончания редакции не может быть раньше даты вступления в силу")
        if len(self.text.strip()) < 40:
            # A citation quotes the norm. A few words cannot be the wording of an article, and a
            # truncated quote is a misquote.
            problems.append(
                "текст нормы слишком короткий для дословной цитаты — нужен полный текст статьи "
                "(части, пункта)"
            )
        known = {value.value for value in supported_document_types()}
        unknown = [item for item in self.applicable_document_types if item not in known]
        if unknown:
            problems.append(
                "неизвестные типы дел: " + ", ".join(unknown) + ". Допустимо: " + ", ".join(sorted(known))
            )
        if self.next_review_date is not None and self.next_review_date <= date.today():
            problems.append("дата плановой переверификации должна быть в будущем")
        return problems

    def to_norm(self, *, reviewed_at: datetime | None = None) -> LegalNorm:
        moment = reviewed_at or datetime.now(timezone.utc)
        return LegalNorm(
            code_id=self.code_id.strip(),
            law_name=(self.law_name or "").strip() or None,
            article_number=self.article_number.strip(),
            title=(self.title or "").strip() or None,
            part=self.part.strip(),
            point=self.point.strip(),
            text=self.text.strip(),
            effective_from=self.effective_from,
            effective_to=self.effective_to,
            source_url=self.source_url.strip(),
            status=CorpusStatus.CANONICAL,
            reviewed_by=self.reviewed_by.strip(),
            reviewed_at=moment,
            applicable_document_types=list(self.applicable_document_types),
            next_review_date=self.next_review_date
            or default_next_review(moment.date(), months=self.review_months),
        )


@dataclass
class CurationResult:
    norm: LegalNorm
    source: SourceCheck
    superseded: LegalNorm | None = None
    warnings: list[str] = field(default_factory=list)


def check_source(url: str) -> SourceCheck:
    """Report whether a source is one of the official Kazakhstan publishers.

    This is advisory at entry time. It is not advisory later: the citation gateway refuses to mark
    a citation VERIFIED unless its source is on the allow-list, so a norm recorded from elsewhere
    will never reach a document. Saying so here saves the lawyer from discovering it downstream.
    """
    cleaned = (url or "").strip()
    if not cleaned:
        return SourceCheck(url=cleaned, official=False, message="Ссылка на источник не указана.")
    if is_trusted_official_url(cleaned):
        return SourceCheck(
            url=cleaned,
            official=True,
            message="Источник официальный.",
        )
    return SourceCheck(
        url=cleaned,
        official=False,
        message=(
            "Источник не входит в список официальных ("
            + ", ".join(TRUSTED_KZ_DOMAINS)
            + ") и должен использовать https. Норма будет сохранена, но Citation Gateway "
            "не сможет пометить ссылку на неё как проверенную, поэтому в документах она "
            "не появится."
        ),
    )


class CorpusCurator:
    """Lawyer-facing operations on the canonical corpus.

    Everything here is deliberately explicit: nothing is created from a partial record, and a new
    redaction never overwrites the previous one, so a document filed under the old wording stays
    reproducible.
    """

    def __init__(self, repository: LegalNormRepository) -> None:
        self.repository = repository

    def add(self, submission: NormSubmission, *, allow_unofficial_source: bool = False) -> CurationResult:
        problems = submission.validate()
        if problems:
            raise CurationError("; ".join(problems))

        source = check_source(submission.source_url)
        if not source.official and not allow_unofficial_source:
            raise CurationError(
                source.message + " Чтобы всё равно сохранить запись, повторите с флагом "
                "--allow-unofficial-source."
            )

        existing = self.repository.get_by_locator(
            code_id=submission.code_id,
            article_number=submission.article_number,
            part=submission.part,
            point=submission.point,
        )
        clash = [item for item in existing if item.effective_from == submission.effective_from]
        if clash:
            raise CurationError(
                "Норма с этой датой вступления в силу уже есть в корпусе. Для новой редакции "
                "используйте update-norm с новой датой; для исправления опечатки — update-norm "
                "--correct-in-place."
            )

        norm = submission.to_norm()
        self.repository.upsert(norm)
        warnings = [] if source.official else [source.message]
        if not submission.applicable_document_types:
            warnings.append(
                "Типы дел не указаны: норма попадёт в поиск, но не будет учтена в отчёте покрытия."
            )
        return CurationResult(norm=norm, source=source, warnings=warnings)

    def update(
        self,
        submission: NormSubmission,
        *,
        allow_unofficial_source: bool = False,
        correct_in_place: bool = False,
    ) -> CurationResult:
        """Record a new redaction, or correct an existing one in place.

        The default is a new redaction: the previous wording is closed the day before the new one
        takes effect and stays in the corpus. In-place correction is for a transcription error in a
        wording that never changed, and has to be asked for explicitly.
        """
        problems = submission.validate()
        if problems:
            raise CurationError("; ".join(problems))

        source = check_source(submission.source_url)
        if not source.official and not allow_unofficial_source:
            raise CurationError(
                source.message + " Чтобы всё равно сохранить запись, повторите с флагом "
                "--allow-unofficial-source."
            )

        existing = self.repository.get_by_locator(
            code_id=submission.code_id,
            article_number=submission.article_number,
            part=submission.part,
            point=submission.point,
        )
        if not existing:
            raise CurationError(
                "Такой нормы в корпусе нет. Для первой записи используйте add-norm."
            )

        superseded: LegalNorm | None = None
        if correct_in_place:
            if not any(item.effective_from == submission.effective_from for item in existing):
                raise CurationError(
                    "Исправление на месте требует ту же дату вступления в силу, что и у "
                    "существующей записи."
                )
        else:
            if any(item.effective_from == submission.effective_from for item in existing):
                raise CurationError(
                    "Новая редакция должна иметь новую дату вступления в силу. Если это "
                    "исправление опечатки — используйте --correct-in-place."
                )
            superseded = self.repository.supersede_open_version(
                code_id=submission.code_id,
                article_number=submission.article_number,
                part=submission.part,
                point=submission.point,
                new_effective_from=submission.effective_from,
            )

        norm = submission.to_norm()
        self.repository.upsert(norm)
        warnings = [] if source.official else [source.message]
        if superseded is None and not correct_in_place:
            warnings.append(
                "Предыдущая открытая редакция не найдена — новая запись добавлена как отдельная "
                "версия. Проверьте диапазоны дат."
            )
        return CurationResult(
            norm=norm, source=source, superseded=superseded, warnings=warnings
        )

    def due_for_review(self, *, as_of: date | None = None, limit: int = 200) -> list[LegalNorm]:
        return self.repository.list_due_for_review(as_of=as_of or date.today(), limit=limit)
