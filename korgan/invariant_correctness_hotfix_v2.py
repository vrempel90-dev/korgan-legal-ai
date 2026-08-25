"""Correctness fixes for the production-invariants v2 runtime.

This module is intentionally small and installed after the broader invariant
layer.  It addresses failure modes found by PR review without widening changes
into payment/admin/consultation handlers.
"""

from __future__ import annotations

import asyncio
import contextvars
import logging
import re
from datetime import date
from typing import Any, Awaitable, Callable

from aiogram import BaseMiddleware
from aiogram.types import CallbackQuery, Message, TelegramObject

from korgan.legal_calc import format_kzt, parse_all_amounts_kzt, parse_amount_kzt
from korgan.legal_types import ClaimDraft, VerificationStatus

LOGGER = logging.getLogger(__name__)

# Only the task explicitly registered by a document-generation entrypoint is
# cancellable.  Ordinary payment/admin/quota handlers are never put here.
_ACTIVE_GENERATIONS: dict[int, asyncio.Task[Any]] = {}
_ACTIVE_GENERATIONS_LOCK = asyncio.Lock()

# These are raw-input facts.  They outrank article/citation words in the same
# issue because a sentence like "не указан адрес ответчика для ст. 148 ГПК" is
# still user-resolvable missing data, not an internal citation defect.
_USER_FACT_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"(?i)\[ДАННЫЕ:\s*"),
    re.compile(r"(?i)не\s+(?:указан|указана|указаны|заполнен[аы]?|идентифицирован[аы]?)\s+.*?(?:отправител|адресат|истец|ответчик|сторон|фио|бин|иин|адрес|реквизит)"),
    re.compile(r"(?i)не\s+идентифицированы\s+обе\s+стороны\s+договора"),
    re.compile(r"(?i)нет\s+реквизитов/подписного\s+блока\s+обеих\s+сторон"),
    re.compile(r"(?i)не\s+заполнены\s+место/дата\s+заключения\s+договора"),
    re.compile(r"(?i)не\s+хватает.*?(?:даты|срока|суммы|адреса|фио|бин|иин|реквизит|сторон)"),
    re.compile(r"(?i)(?:дата\s+начала\s+просрочки|срок\s+исполнения).*?(?:не\s+установ|уточн|отсутств)"),
    re.compile(r"(?i)нет\s+фактическ\w*\s+(?:основан|обстоятельств)"),
    re.compile(r"(?i)не\s+указан\s+(?:отправитель|адресат)\s+претензии"),
    re.compile(r"(?i)в\s+отзыве\s+не\s+идентифицированы\s+истец\s+и\s+ответчик"),
)
_INTERNAL_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"(?i)стать(?:я|и|е|ю|ёй|ей)|\bст\.\s*\d"),
    re.compile(r"(?i)правов\w*\s+(?:основан|ссыл|норм|позици|конструкц)"),
    re.compile(r"(?i)пересказ|source-bound|verified|цитат|норм\w*\s+права"),
    re.compile(r"(?i)служебн\w*\s+фраз|целостност|поврежден|повреждён|экспорт"),
    re.compile(r"(?i)не\s+(?:сформулирован|сформирована|перенесен|перенесены|определен|определена).*?(?:требован|проситель|правов|вид/название|условия)"),
    re.compile(r"(?i)не\s+определено\s+конкретное\s+наименование\s+суда"),
    re.compile(r"(?i)в\s+отзыве\s+не\s+указан\s+конкретный\s+суд"),
)

_LABELLED_PRINCIPAL_RE = re.compile(
    r"(?i)(?:основн\w*\s+долг|сумм\w*\s+долг\w*|задолженн\w*|предоплат\w*|"
    r"предварительн\w*\s+оплат\w*|аванс\w*)[^\n.;]{0,100}?"
    r"(?P<amount>\d[\d\s\u00a0]*(?:[.,]\d{1,2})?)\s*(?:тенге|теңге|тг\b|₸|kzt)",
    re.IGNORECASE,
)
_REVERSE_LABELLED_PRINCIPAL_RE = re.compile(
    r"(?i)(?P<amount>\d[\d\s\u00a0]*(?:[.,]\d{1,2})?)\s*(?:тенге|теңге|тг\b|₸|kzt)"
    r"[^\n.;]{0,100}?(?:основн\w*\s+долг|сумм\w*\s+долг\w*|задолженн\w*|"
    r"предоплат\w*|предварительн\w*\s+оплат\w*|аванс\w*)",
    re.IGNORECASE,
)
_PENALTY_RE = re.compile(r"(?i)неустойк\w*|пен[яию]\b|штрафн\w*|просроч\w*")


def classify_issue_v2(issue: str):
    """Classify against actual production quality strings, facts first."""
    from korgan.production_invariants_v2 import BlockerClass, ClassifiedIssue, _compact, _issue_action

    text = _compact(issue)
    if any(pattern.search(text) for pattern in _USER_FACT_PATTERNS):
        return ClassifiedIssue(text, BlockerClass.NEEDS_USER_DATA, _issue_action(text))
    if any(pattern.search(text) for pattern in _INTERNAL_PATTERNS):
        return ClassifiedIssue(text, BlockerClass.INTERNAL_QUALITY, "KORGAN должен исправить/пометить это сам")
    # Unknown quality defects remain internal.  Blocking is reserved for an
    # explicit, recognized missing input; this preserves I3 fail-open-with-marker.
    return ClassifiedIssue(text, BlockerClass.INTERNAL_QUALITY, "KORGAN должен исправить/пометить это сам")


def classify_issues_v2(issues: list[str] | tuple[str, ...]):
    from korgan.production_invariants_v2 import BlockerClass, _compact

    unique = list(dict.fromkeys(_compact(item) for item in issues if _compact(item)))
    classified = [classify_issue_v2(item) for item in unique]
    return (
        [item for item in classified if item.blocker_class == BlockerClass.NEEDS_USER_DATA],
        [item for item in classified if item.blocker_class == BlockerClass.INTERNAL_QUALITY],
    )


def _principal_from_context(case_context: str) -> int | None:
    text = case_context or ""
    for pattern in (_LABELLED_PRINCIPAL_RE, _REVERSE_LABELLED_PRINCIPAL_RE):
        match = pattern.search(text)
        if match:
            amount = parse_amount_kzt(match.group("amount") + " тенге")
            if amount:
                return amount
    amounts = list(dict.fromkeys(parse_all_amounts_kzt(text)))
    # With a single monetary value there is no ambiguity about which input
    # amount must at least reach the ledger/document propagation stage.
    return amounts[0] if len(amounts) == 1 else None


def _contains_amount(lines: list[str], amount: int) -> bool:
    return any(amount in parse_all_amounts_kzt(str(line)) for line in lines)


def _principal_label(case_context: str) -> str:
    lower = (case_context or "").lower()
    if "предоплат" in lower or "предварительн" in lower or "аванс" in lower:
        return "сумму предварительной оплаты"
    if "задолж" in lower or "долг" in lower:
        return "сумму основного долга"
    return "основную денежную сумму"


def _principal_demand(case_context: str, principal: int, *, claim: bool) -> str:
    label = _principal_label(case_context)
    if claim:
        return f"Взыскать с ответчика в пользу истца {label} в размере {format_kzt(principal)}."
    return f"Уплатить {label} в размере {format_kzt(principal)}."


def _penalty_line(penalty: Any, *, claim: bool) -> str:
    prefix = "Взыскать с ответчика в пользу истца" if claim else "Уплатить"
    text = (
        f"{prefix} неустойку в размере {format_kzt(penalty.amount)} за период "
        f"с {penalty.start.strftime('%d.%m.%Y')} по {penalty.as_of.strftime('%d.%m.%Y')} "
        f"из расчёта {penalty.daily_rate_percent:g}% в день"
    )
    if penalty.cap_amount is not None and penalty.cap_reached_on is not None:
        if penalty.as_of >= penalty.cap_reached_on:
            text += (
                f"; договорный предел {penalty.cap_percent:g}% = {format_kzt(penalty.cap_amount)} "
                f"достигнут {penalty.cap_reached_on.strftime('%d.%m.%Y')}"
            )
        else:
            text += f"; договорный предел {penalty.cap_percent:g}% = {format_kzt(penalty.cap_amount)} ещё не достигнут"
    return text + "."


def apply_money_ledger_to_claim_v2(case_context: str, draft: ClaimDraft, *, as_of: date | None = None):
    from korgan import production_invariants_v2 as prod

    checked_on = as_of or prod._today_kz()
    principal = _principal_from_context(case_context)
    ledger = prod.build_money_ledger(case_context, draft, as_of=checked_on)

    if principal is not None and not _contains_amount(list(draft.requests), principal):
        draft.requests.insert(0, _principal_demand(case_context, principal, claim=True))
        LOGGER.info("MONEY_PROPAGATION kind=claim principal=%d action=inserted_from_user_input", principal)
    elif principal is None and ledger.input_amounts:
        note = "[ДАННЫЕ: подтвердите, какая из указанных денежных сумм является основным требованием]"
        if note not in draft.verification_notes:
            draft.verification_notes.append(note)
        LOGGER.warning("MONEY_PROPAGATION kind=claim action=needs_user_data input_amounts=%s", ledger.input_amounts)

    penalty = ledger.penalty
    if penalty is not None and _PENALTY_RE.search(case_context or ""):
        line = _penalty_line(penalty, claim=True)
        rebuilt: list[str] = []
        replaced = False
        for request in draft.requests:
            if _PENALTY_RE.search(str(request)):
                if not replaced:
                    rebuilt.append(line)
                    replaced = True
                continue
            rebuilt.append(str(request))
        if not replaced:
            rebuilt.append(line)
        draft.requests = rebuilt

    effective_principal = principal or ledger.principal
    if effective_principal:
        total = effective_principal + (penalty.amount if penalty is not None else 0)
        draft.price_of_claim = format_kzt(total)

    # Rebuild after propagation so the logged ledger represents what can be
    # found in the final prayer, not a synthetic pre-propagation fallback row.
    final_ledger = prod.build_money_ledger(case_context, draft, as_of=checked_on)
    LOGGER.info(
        "CLAIM_MONEY_AUTHORITY price=%r input_amounts=%d ledger_total=%d principal=%r penalty=%r unresolved=%d propagated=%d",
        draft.price_of_claim,
        len(final_ledger.input_amounts),
        final_ledger.total,
        effective_principal,
        penalty.amount if penalty else None,
        len(final_ledger.unresolved),
        1 if effective_principal and _contains_amount(list(draft.requests), effective_principal) else 0,
    )
    return final_ledger


def apply_money_ledger_to_pretrial_v2(case_context: str, draft: Any, *, as_of: date | None = None):
    from korgan import production_invariants_v2 as prod

    checked_on = as_of or prod._today_kz()
    principal = _principal_from_context(case_context)
    ledger = prod.build_money_ledger(case_context, None, as_of=checked_on)
    demands = [str(value) for value in list(getattr(draft, "demands", []) or [])]

    if principal is not None and not _contains_amount(demands, principal):
        demands.insert(0, _principal_demand(case_context, principal, claim=False))
        LOGGER.info("MONEY_PROPAGATION kind=pretrial principal=%d action=inserted_from_user_input", principal)
    elif principal is None and ledger.input_amounts:
        marker = "[ДАННЫЕ: подтвердите, какая из указанных денежных сумм является основным требованием]"
        if marker not in demands:
            demands.insert(0, marker)
        LOGGER.warning("MONEY_PROPAGATION kind=pretrial action=needs_user_data input_amounts=%s", ledger.input_amounts)

    penalty = ledger.penalty
    if penalty is not None and _PENALTY_RE.search(case_context or ""):
        line = _penalty_line(penalty, claim=False)
        rebuilt: list[str] = []
        replaced = False
        for demand in demands:
            if _PENALTY_RE.search(demand):
                if not replaced:
                    rebuilt.append(line)
                    replaced = True
                continue
            rebuilt.append(demand)
        if not replaced:
            rebuilt.append(line)
        demands = rebuilt
    draft.demands = demands

    LOGGER.info(
        "PRETRIAL_MONEY_AUTHORITY input_amounts=%d ledger_total=%d principal=%r penalty=%r unresolved=%d propagated=%d",
        len(ledger.input_amounts),
        ledger.total,
        principal or ledger.principal,
        penalty.amount if penalty else None,
        len(ledger.unresolved),
        1 if principal and _contains_amount(demands, principal) else 0,
    )
    return ledger


async def _register_generation(message: Message, label: str, call: Callable[[], Awaitable[Any]]) -> Any:
    """Run one heavy document generation as the only cancellable task per chat."""
    from korgan import production_invariants_v2 as prod

    chat_id = message.chat.id
    current = asyncio.current_task()
    if current is None:
        return await call()

    async with _ACTIVE_GENERATIONS_LOCK:
        previous = _ACTIVE_GENERATIONS.get(chat_id)
        if previous is not None and previous is not current and not previous.done():
            previous.cancel()
            LOGGER.info("STALE_GENERATION_CANCELLED chat_id=%s next=%s", chat_id, label)
        _ACTIVE_GENERATIONS[chat_id] = current

    run_token = prod._RUN_ID.set(f"{chat_id}:message:{message.message_id}:{label}")
    repair_token = prod._REPAIR_BLOCKER_SETS.set(frozenset())
    delivery_token = prod._DELIVERED_KINDS.set(frozenset())
    try:
        return await call()
    except asyncio.CancelledError:
        LOGGER.info("STALE_GENERATION_STOPPED run=%s", prod._RUN_ID.get())
        return None
    finally:
        prod._RUN_ID.reset(run_token)
        prod._REPAIR_BLOCKER_SETS.reset(repair_token)
        prod._DELIVERED_KINDS.reset(delivery_token)
        async with _ACTIVE_GENERATIONS_LOCK:
            if _ACTIVE_GENERATIONS.get(chat_id) is current:
                _ACTIVE_GENERATIONS.pop(chat_id, None)


class CancelActiveGenerationMiddleware(BaseMiddleware):
    """A new update cancels a generation, never an arbitrary prior handler."""

    @staticmethod
    def _chat_id(event: TelegramObject) -> int | None:
        if isinstance(event, Message):
            return event.chat.id
        if isinstance(event, CallbackQuery) and event.message is not None:
            return event.message.chat.id
        return None

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        chat_id = self._chat_id(event)
        current = asyncio.current_task()
        if chat_id is not None and current is not None:
            async with _ACTIVE_GENERATIONS_LOCK:
                previous = _ACTIVE_GENERATIONS.get(chat_id)
                if previous is not None and previous is not current and not previous.done():
                    previous.cancel()
                    LOGGER.info("STALE_GENERATION_CANCEL_REQUEST chat_id=%s", chat_id)
        return await handler(event, data)


def _wrap_generation_entry(module: Any, attribute: str, label: str) -> None:
    original = getattr(module, attribute)
    marker = f"_korgan_generation_guard_{attribute}"
    if getattr(module, marker, False):
        return

    async def wrapped(message: Message, *args: Any, **kwargs: Any) -> Any:
        return await _register_generation(
            message,
            label,
            lambda: original(message, *args, **kwargs),
        )

    setattr(module, attribute, wrapped)
    setattr(module, marker, True)


def install_invariant_correctness_hotfix_v2() -> None:
    """Install review fixes after all v2 runtime adapters are in place."""
    from korgan import production_invariants_v2 as prod
    from korgan import universal_document_invariants_v2 as universal_docs
    from korgan import pretrial_runtime, universal_claim_runtime, universal_document_runtime

    prod.classify_issue = classify_issue_v2
    prod.classify_issues = classify_issues_v2
    prod.apply_money_ledger_to_claim = apply_money_ledger_to_claim_v2
    prod.apply_money_ledger_to_pretrial = apply_money_ledger_to_pretrial_v2
    universal_docs.classify_issue = classify_issue_v2
    universal_docs.classify_issues = classify_issues_v2

    # Register only known heavy document-generation entrypoints.  The outer
    # middleware may cancel these tasks, but payment/admin/quota handlers are not
    # registered and therefore cannot be cancelled by a later Telegram update.
    _wrap_generation_entry(universal_claim_runtime, "_generate_now", "claim")
    _wrap_generation_entry(pretrial_runtime, "_generate", "pretrial")
    _wrap_generation_entry(universal_document_runtime, "_send_contract", "contract")
    _wrap_generation_entry(universal_document_runtime, "_send_response", "response_to_claim")

    LOGGER.info("Installed KORGAN invariant correctness hotfix v2")
