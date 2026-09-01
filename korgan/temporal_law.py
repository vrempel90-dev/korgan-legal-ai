"""Проверка применимости нормы к конкретному правоотношению во времени.

Действующая сегодня редакция статьи и норма, подлежащая применению к спору, —
это не одно и то же. Договор 2019 года исполняется по закону 2019 года: статья
4 ГК РК прямо говорит, что акт гражданского законодательства не имеет обратной
силы и применяется к отношениям, возникшим после введения его в действие.
Процессуальные нормы работают наоборот — по ним оценивается процессуальное
действие на дату его совершения, то есть на дату подачи.

Из этого следует то, ради чего написан модуль: сослаться на сегодняшнюю
редакцию статьи в споре из старого договора — не мелкая неточность, а ошибка
в применимом праве, и суд снимает такой довод целиком.

Модуль не ищет норм и не хранит законодательство. Он получает уже найденную
норму с её датами и решает единственный вопрос: можно ли применять именно её
именно к этому делу. Ответ «не знаю» здесь допустим и обязателен —
``NEEDS_VERIFICATION`` с названной причиной. Ответ «наверное, да» — нет:
память модели источником права не является, и уверенная ссылка на статью,
которой к моменту спора уже не было, неотличима в тексте от верной.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date
from enum import StrEnum

from korgan.citation_audit import is_official_source


class NormKind(StrEnum):
    """Материальная норма или процессуальная — от этого зависит, какая дата
    определяет подлежащую применению редакцию."""

    SUBSTANTIVE = "substantive"
    PROCEDURAL = "procedural"


class LegalSourceStatus(StrEnum):
    VERIFIED = "verified"
    NEEDS_VERIFICATION = "needs_verification"


@dataclass(frozen=True, slots=True)
class LegalDates:
    """Юридически значимые даты дела.

    Заполняется тем, что установлено по документам. Неизвестная дата остаётся
    ``None`` и приводит к отказу в подтверждении, а не к подстановке сегодняшней.
    """

    #: Возникновение правоотношения.
    relationship_started: date | None = None
    contract_signed: date | None = None
    #: Наступление срока исполнения.
    performance_due: date | None = None
    #: Нарушение, с которого началась просрочка.
    breach: date | None = None
    #: Направление претензии.
    claim_sent: date | None = None
    #: Подача иска в суд.
    filing: date | None = None

    def governing_date(self, kind: NormKind) -> date | None:
        """Дата, на которую определяется подлежащая применению редакция.

        Для материальной нормы — возникновение правоотношения; договор здесь
        служит запасным ориентиром, потому что чаще всего именно он это
        правоотношение и порождает. Для процессуальной — дата подачи.
        """
        if kind is NormKind.PROCEDURAL:
            return self.filing
        return self.relationship_started or self.contract_signed


@dataclass(frozen=True, slots=True)
class NormVersion:
    """Конкретная редакция конкретной нормы с её сроком действия."""

    act: str
    article: str
    part: str = ""
    #: Ссылка на официальный источник — Adilet.
    source_url: str = ""
    #: С какой даты действует эта редакция.
    in_force_from: date | None = None
    #: По какую дату действовала; ``None`` — действует до сих пор.
    in_force_to: date | None = None
    #: Каким законом введена редакция. Обязательно, если норма уже изменилась.
    redaction: str = ""
    kind: NormKind = NormKind.SUBSTANTIVE
    #: Какие правоотношения охватывает норма: «поставка», «защита прав
    #: потребителей», «трудовой спор». Пустой набор означает, что круг
    #: отношений не устанавливался.
    covers: tuple[str, ...] = ()
    #: Если норма специальная — ссылка на общую, которую она вытесняет.
    special_to: str = ""
    #: Переходные положения, если они есть. Их применение решает юрист.
    transitional: str = ""

    def reference(self) -> str:
        part = f"пункт {self.part} " if self.part else ""
        return f"{part}статьи {self.article} {self.act}".strip()


@dataclass(frozen=True, slots=True)
class NormCheck:
    status: LegalSourceStatus
    norm: NormVersion
    governing_date: date | None = None
    reasons: tuple[str, ...] = ()

    @property
    def applicable(self) -> bool:
        return self.status is LegalSourceStatus.VERIFIED


def check_norm(
    norm: NormVersion,
    dates: LegalDates,
    *,
    relationship: str = "",
    competing: Sequence[NormVersion] = (),
) -> NormCheck:
    """Установить, подлежит ли норма применению к этому делу.

    ``relationship`` — квалификация спорного отношения, ``competing`` — иные
    найденные нормы, среди которых может оказаться специальная, вытесняющая
    заявленную общую.
    """
    reasons: list[str] = []
    governing = dates.governing_date(norm.kind)

    if not is_official_source(norm.source_url):
        reasons.append(
            f"{norm.reference()}: норма не подтверждена официальным источником "
            f"(требуется adilet.zan.kz)"
        )

    if governing is None:
        reasons.append(
            f"{norm.reference()}: не установлена дата, на которую определяется "
            f"подлежащая применению редакция"
        )

    if norm.in_force_from is None:
        reasons.append(f"{norm.reference()}: не установлена дата введения нормы в действие")

    if governing is not None and norm.in_force_from is not None:
        if governing < norm.in_force_from:
            reasons.append(
                f"{norm.reference()} введена в действие {norm.in_force_from.strftime('%d.%m.%Y')}, "
                f"а правоотношение возникло {governing.strftime('%d.%m.%Y')}: "
                f"к нему применяется редакция, действовавшая на эту дату"
            )
        elif norm.in_force_to is not None and governing > norm.in_force_to:
            reasons.append(
                f"{norm.reference()} утратила силу {norm.in_force_to.strftime('%d.%m.%Y')}, "
                f"то есть до {governing.strftime('%d.%m.%Y')}"
            )

    # Норма применялась к правоотношению, но к моменту подачи уже изменилась.
    # Ссылаться на неё можно, однако документ обязан назвать редакцию, иначе
    # читающий сверит текст с действующим и не найдёт совпадения.
    if (
        norm.in_force_to is not None
        and dates.filing is not None
        and dates.filing > norm.in_force_to
        and not norm.redaction.strip()
    ):
        reasons.append(
            f"{norm.reference()} изменилась к моменту подачи "
            f"({dates.filing.strftime('%d.%m.%Y')}): не указана применяемая редакция"
        )

    if relationship.strip() and norm.covers and relationship.strip() not in norm.covers:
        reasons.append(
            f"{norm.reference()} регулирует {', '.join(norm.covers)}, "
            f"а спор квалифицирован как «{relationship.strip()}»"
        )

    for other in competing:
        if other.special_to.strip() and other.special_to.strip() == norm.reference():
            reasons.append(
                f"{other.reference()} является специальной по отношению к "
                f"{norm.reference()} и имеет приоритет"
            )

    if norm.transitional.strip():
        reasons.append(
            f"{norm.reference()}: действуют переходные положения "
            f"({norm.transitional.strip()}) — применение требует проверки"
        )

    if reasons:
        return NormCheck(
            status=LegalSourceStatus.NEEDS_VERIFICATION,
            norm=norm,
            governing_date=governing,
            reasons=tuple(reasons),
        )
    return NormCheck(
        status=LegalSourceStatus.VERIFIED, norm=norm, governing_date=governing
    )


@dataclass(frozen=True, slots=True)
class LawGateResult:
    ready: bool
    checks: tuple[NormCheck, ...] = ()
    reasons: tuple[str, ...] = ()


def check_applicable_law(
    norms: Sequence[NormVersion],
    dates: LegalDates,
    *,
    relationship: str = "",
) -> LawGateResult:
    """Проверить весь состав норм документа.

    Достаточно одной неподтверждённой нормы, чтобы документ не был готов:
    в тексте иска все ссылки выглядят одинаково уверенно, и читающий не
    отличит проверенную от непроверенной.
    """
    if not norms:
        return LawGateResult(
            ready=False,
            reasons=("применимое право не установлено: документ не ссылается ни на одну норму",),
        )

    checks = tuple(
        check_norm(norm, dates, relationship=relationship, competing=norms)
        for norm in norms
    )
    reasons = tuple(reason for check in checks for reason in check.reasons)
    return LawGateResult(ready=not reasons, checks=checks, reasons=reasons)
