from __future__ import annotations

from string import Formatter
from typing import Callable

from korgan_legal_ai.blueprints.models import AddresseeKind, SectionKind
from korgan_legal_ai.domain.models import (
    FilingMode,
    Party,
    RepresentativeKind,
    VerificationStatus,
)
from korgan_legal_ai.drafting.context import DraftContext

NEEDS = "NEEDS_VERIFICATION"

_REPRESENTATIVE_LABELS = {
    RepresentativeKind.DIRECTOR: "руководитель",
    RepresentativeKind.EMPLOYEE: "штатный работник",
    RepresentativeKind.ADVOCATE: "адвокат",
    RepresentativeKind.LEGAL_CONSULTANT: "юридический консультант",
    RepresentativeKind.OTHER: "представитель",
}


def _money(value, currency: str) -> str:
    return f"{value} {currency}"


def _need(reason: str) -> str:
    return f"{NEEDS} — {reason}"


def _verified_or_need(item, *, verified_prefix: str = "") -> str:
    if item is None:
        return f"{NEEDS} — вопрос не был проверен."
    if item.status == VerificationStatus.VERIFIED:
        return f"{verified_prefix}{item.conclusion}"
    return _need(item.conclusion)


def _party_block(label: str, party: Party) -> str:
    lines = [f"{label}: {party.name}"]
    if party.iin_bin:
        lines.append(f"БИН/ИИН: {party.iin_bin}")
    if party.address:
        lines.append(f"Адрес: {party.address}")
    return "\n".join(lines)


def render_addressee(ctx: DraftContext) -> str | None:
    kind = ctx.blueprint.addressee
    if kind == AddresseeKind.NONE:
        return None
    if kind == AddresseeKind.COUNTERPARTY:
        opponent = ctx.opponent()
        lines = [f"Кому: {opponent.name}"]
        if opponent.address:
            lines.append(f"Адрес: {opponent.address}")
        else:
            lines.append(
                _need("адрес получателя претензии не зафиксирован и не может быть подставлен.")
            )
        return "\n".join(lines)

    jurisdiction = ctx.item("jurisdiction")
    if jurisdiction is not None and jurisdiction.status == VerificationStatus.VERIFIED:
        return "В ______________________________ суд\n" f"Подсудность: {jurisdiction.conclusion}"
    if kind == AddresseeKind.APPEAL_COURT:
        reason = (
            jurisdiction.conclusion
            if jurisdiction is not None
            else "определить суд апелляционной инстанции, компетентный пересматривать обжалуемый акт."
        )
        return f"В: {_need(reason)}"
    reason = (
        jurisdiction.conclusion
        if jurisdiction is not None
        else "определить компетентный суд и территориальную подсудность."
    )
    return f"В: {_need(reason)}"


def render_parties(ctx: DraftContext) -> str:
    presentation = ctx.blueprint.parties
    return "\n\n".join(
        (
            _party_block(presentation.author_label, ctx.author()),
            _party_block(presentation.opponent_label, ctx.opponent()),
        )
    )


def render_title(ctx: DraftContext) -> str:
    return ctx.blueprint.subject


def render_claim_price(ctx: DraftContext) -> str | None:
    if not ctx.blueprint.monetary:
        return None
    total = _money(ctx.calculation.total, ctx.calculation.currency)
    lines = [f"ЦЕНА ИСКА: {total}"]

    state_duty = ctx.item("state_duty")
    if state_duty is not None and state_duty.status == VerificationStatus.VERIFIED:
        lines.append(f"Государственная пошлина: {state_duty.conclusion}")
    elif state_duty is not None:
        lines.append(f"Государственная пошлина: {_need(state_duty.conclusion)}")
    else:
        lines.append(
            "Государственная пошлина: "
            + _need("определить размер по действующему законодательству Республики Казахстан.")
        )
    return "\n".join(lines)


def render_opening_formula(ctx: DraftContext) -> str | None:
    """Print the house-style opening quote only when the corpus confirmed its wording."""
    citation = ctx.style_citation("8")
    if citation is None or not citation.text_excerpt:
        return None
    law = citation.law_name or citation.source_title
    return f"«{citation.text_excerpt.strip()}»\n({law}, статья {citation.article})"


def render_facts(ctx: DraftContext) -> str:
    lines = [f"- {fact.statement}" for fact in ctx.case.facts]
    body = "\n".join(lines) if lines else _need("обстоятельства дела не зафиксированы.")
    due = ctx.case.procedure.obligation_due_date
    if due is not None:
        body += "\nСрок исполнения обязательства: " + due.strftime("%d.%m.%Y")
    return body


def render_position(ctx: DraftContext) -> str:
    return (
        "Ответчик не признает заявленные требования по обстоятельствам, изложенным выше. "
        "Каждое возражение подлежит подтверждению приложенными доказательствами."
    )


def render_grounds(ctx: DraftContext) -> str:
    lines = [f"- {fact.statement}" for fact in ctx.case.facts]
    return "\n".join(lines) if lines else _need("основания не зафиксированы.")


def render_pretrial(ctx: DraftContext) -> str:
    item = ctx.item("pretrial")
    body = _verified_or_need(item)
    sent = ctx.case.procedure.pretrial_demand_sent_date
    if sent is not None:
        body += " Дата направления претензии: " + sent.strftime("%d.%m.%Y") + "."
    return body


def render_calculation(ctx: DraftContext) -> str | None:
    if not ctx.blueprint.monetary:
        return None
    calculation = ctx.calculation
    currency = calculation.currency
    lines: list[str] = []
    # The debt is presented as derived so the contract sum is visibly an input to the balance,
    # never a second claimable position.
    if calculation.contract_amount is not None:
        lines.append(f"Стоимость по договору: {_money(calculation.contract_amount, currency)}")
        lines.append(f"Оплачено: {_money(calculation.payments_total, currency)}")
    lines.append(f"Основной долг: {_money(calculation.principal, currency)}")
    lines.append(f"Неустойка: {_money(calculation.penalty, currency)}")
    # Each accrual period is printed so a reader can re-derive the penalty instead of trusting it.
    for period in calculation.penalty_periods:
        if period.amount <= 0:
            continue
        lines.append(
            f"  за период с {period.start.strftime('%d.%m.%Y')} по {period.end.strftime('%d.%m.%Y')} "
            f"({period.days} дн.) на остаток {_money(period.outstanding, currency)}: "
            f"{_money(period.amount, currency)}"
        )
    if calculation.penalty_cap_applied and calculation.penalty_cap_amount is not None:
        lines.append(
            f"  применено договорное ограничение неустойки: "
            f"{_money(calculation.penalty_cap_amount, currency)}"
        )
    # A zero row is not printed at all: the category exists only for amounts that are genuinely
    # outside the debt, and an empty row invites a duplicate to be filled into it.
    if calculation.interest > 0:
        lines.append(f"Проценты: {_money(calculation.interest, currency)}")
    if calculation.other > 0:
        lines.append(f"Иные суммы: {_money(calculation.other, currency)}")
    lines.append(f"Итого: {_money(calculation.total, currency)}")
    return "\n".join(lines)


def render_terms(ctx: DraftContext) -> str:
    if ctx.blueprint.addressee == AddresseeKind.COUNTERPARTY:
        return _need(
            "срок добровольного исполнения определяется договором или законом и должен быть "
            "проверен по действующей редакции до направления претензии."
        )
    return _need(
        "существенные условия договора должны быть согласованы сторонами и проверены юристом; "
        "система не подставляет типовые формулировки без верифицированного шаблона."
    )


def render_legal_grounds(ctx: DraftContext) -> str:
    citations = ctx.verified_citations()
    lines = [
        f"- {citation.law_name or citation.source_title}, статья {citation.article}: "
        f"{citation.source_url}"
        for citation in citations
        if citation.article and citation.source_url
    ]
    if lines:
        return "\n".join(lines)
    return _need(
        "конкретные нормы материального и процессуального права должны быть определены только "
        "после проверки действующей редакции по верифицированному источнику."
    )


def render_closing_formula(ctx: DraftContext) -> str:
    """The KORGAN closing formula, naming only norms the corpus actually verified."""
    citations = ctx.verified_citations()
    references = [
        f"статьей {citation.article} {citation.law_name or citation.source_title}"
        for citation in citations
        if citation.article
    ]
    if not references:
        return (
            "Руководствуясь нормами законодательства Республики Казахстан, точные статьи которых "
            f"подлежат проверке ({NEEDS} — применимые нормы не подтверждены по верифицированному "
            "источнику),"
        )
    return "Руководствуясь " + ", ".join(references) + ","


def _placeholders(template: str) -> list[str]:
    return [name for _, name, _, _ in Formatter().parse(template) if name]


def _prayer_values(ctx: DraftContext) -> dict[str, str | None]:
    calculation = ctx.calculation
    # Naming the demand after what is actually claimed keeps a fully repaid debt from being
    # demanded again as "задолженность" when only the penalty survives.
    if calculation.principal > 0:
        claim_subject = "задолженность"
    elif calculation.penalty > 0:
        claim_subject = "неустойку"
    else:
        claim_subject = "задолженность"

    duty_suffix = "" if ctx.is_verified("state_duty") else f" ({NEEDS}: размер пошлины не подтвержден)"
    motion_request = next(
        (fact.statement for fact in ctx.case.facts if fact.statement.strip()),
        None,
    )
    return {
        "author": ctx.author().name,
        "opponent": ctx.opponent().name,
        "total": _money(calculation.total, calculation.currency),
        "claim_subject": claim_subject,
        "duty_suffix": duty_suffix,
        "motion_request": motion_request,
    }


def render_prayer(ctx: DraftContext) -> str | None:
    templates = ctx.blueprint.prayer_items
    if not templates:
        return None
    values = _prayer_values(ctx)

    items: list[str] = []
    for template in templates:
        missing = [name for name in _placeholders(template) if not values.get(name)]
        if missing:
            items.append(
                _need(
                    "требование не может быть сформулировано без подтвержденных данных: "
                    + ", ".join(sorted(missing))
                )
            )
            continue
        items.append(template.format(**values))

    # Representative costs are a KORGAN house-style demand, but they rest on an exact procedural
    # norm. The demand appears only when that norm was verified for the relevant date.
    costs_citation = ctx.style_citation("113")
    if costs_citation is not None:
        items.append(
            f"Взыскать с {values['opponent']} в пользу {values['author']} расходы на оплату помощи "
            f"представителя в подтвержденном размере (статья {costs_citation.article} "
            f"{costs_citation.law_name or costs_citation.source_title})."
        )

    return "\n".join(f"{index}. {item}" for index, item in enumerate(items, start=1))


def render_attachments(ctx: DraftContext) -> str:
    titles = [evidence.title for evidence in ctx.case.evidence]
    if (
        ctx.case.procedure.filing_mode == FilingMode.PAPER
        and ctx.case.procedure.copies_prepared is True
    ):
        titles.append("Копии иска и приложений по числу ответчиков и третьих лиц")
    lines = [f"{index}. {title}" for index, title in enumerate(dict.fromkeys(titles), start=1)]

    item = ctx.item("attachments")
    if item is not None and item.status != VerificationStatus.VERIFIED:
        lines.append(f"{len(lines) + 1}. {_need(item.conclusion)}")
    if not lines:
        lines.append(f"1. {_need('перечень фактически предоставленных приложений отсутствует.')}")
    return "\n".join(lines)


def render_signature(ctx: DraftContext) -> str | None:
    authority = ctx.item("authority")
    if authority is not None and authority.status != VerificationStatus.VERIFIED:
        return _need(authority.conclusion)

    procedure = ctx.case.procedure
    kind = procedure.representative_kind
    if kind is None and not procedure.representative_name:
        return None

    label = _REPRESENTATIVE_LABELS.get(kind, "представитель") if kind else "представитель"
    name = procedure.representative_name or _need("ФИО подписанта не зафиксировано.")
    lines = [f"Подписант: {name} ({label})"]
    if procedure.filing_mode == FilingMode.ELECTRONIC:
        lines.append("Документ подписывается ЭЦП при подаче через судебный кабинет.")
    elif procedure.filing_mode == FilingMode.PAPER:
        lines.append("Подпись: ______________________")
    return "\n".join(lines)


RENDERERS: dict[SectionKind, Callable[[DraftContext], str | None]] = {
    SectionKind.ADDRESSEE: render_addressee,
    SectionKind.PARTIES: render_parties,
    SectionKind.TITLE: render_title,
    SectionKind.CLAIM_PRICE: render_claim_price,
    SectionKind.OPENING_FORMULA: render_opening_formula,
    SectionKind.FACTS: render_facts,
    SectionKind.POSITION: render_position,
    SectionKind.GROUNDS: render_grounds,
    SectionKind.PRETRIAL: render_pretrial,
    SectionKind.CALCULATION: render_calculation,
    SectionKind.TERMS: render_terms,
    SectionKind.LEGAL_GROUNDS: render_legal_grounds,
    SectionKind.CLOSING_FORMULA: render_closing_formula,
    SectionKind.PRAYER: render_prayer,
    SectionKind.ATTACHMENTS: render_attachments,
    SectionKind.SIGNATURE: render_signature,
}
