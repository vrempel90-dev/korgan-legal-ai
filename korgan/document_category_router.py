from __future__ import annotations

import re

from aiogram import F, Router
from aiogram.filters import Filter
from aiogram.fsm.context import FSMContext
from aiogram.types import Message

router = Router(name="strict-document-category-router")

# This router does not generate anything itself. It only decides which existing,
# already-tested document workflow owns an explicit drafting request.
_ACTION = re.compile(
    r"(?i)\b(?:подготов\w*|состав\w*|сформир\w*|сдел\w*|напиш\w*|напис\w*|созда\w*|сгенерир\w*|оформ\w*|разработ\w*|"
    r"дайында\w*|жаса\w*|әзірле\w*|құрастыр\w*|жаз\w*|қалыптастыр\w*)\b"
)

_CATEGORY_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    (
        "pretrial_response",
        re.compile(
            r"(?i)(?:\bотзыв\w*\s+на\s+(?:досудебн\w*\s+)?претензи\w*|"
            r"\bответ\w*\s+на\s+(?:досудебн\w*\s+)?претензи\w*|"
            r"\bвозражен\w*\s+на\s+(?:досудебн\w*\s+)?претензи\w*|"
            r"\bсотқа\s+дейінгі\s+талап\w*\s+(?:жауап\w*|пікір\w*)|"
            r"\bталап\s+хат\w*\s+(?:жауап\w*|пікір\w*))"
        ),
    ),
    (
        "response",
        re.compile(
            r"(?i)(?:\bотзыв\w*\b.{0,35}\bиск\w*\b|\bвозражен\w*\b.{0,35}\bиск\w*\b|"
            r"\bответ\w*\b.{0,25}\bна\s+иск\w*\b|\bталап(?:\s+қою)?\s+арыз\w*\s+пікір\w*|\bталапқа\s+пікір\w*)"
        ),
    ),
    (
        "pretrial",
        re.compile(r"(?i)(?:\bдосудебн\w*\s+претензи\w*|\bпретензи\w*\b|\bсотқа\s+дейінгі\s+талап\w*|\bталап\s+хат\w*)"),
    ),
    (
        "contract",
        re.compile(r"(?i)(?:\bдоговор\w*\b|\bсоглашени\w*\b|\bконтракт\w*\b|\bnda\b|\bшарт\w*\b|\bкелісім\w*\b)"),
    ),
    (
        "claim",
        re.compile(r"(?i)(?:\bисков\w*\s+заявлен\w*|\bиск\w*\b|\bталап\s+қою\s+арыз\w*|\bталап-арыз\w*)"),
    ),
)


def preferred_document_category(text: str | None) -> str | None:
    """Return the category explicitly requested nearest to the last drafting verb.

    A case description can contain phrases such as «досудебная претензия
    направлена» or «договор заключён», while the final instruction is
    «подготовь иск». The document noun nearest to the last drafting verb owns the
    request, so factual mentions cannot steal another category's workflow.
    """
    value = " ".join((text or "").split())
    if not value:
        return None

    actions = list(_ACTION.finditer(value))
    if not actions:
        return None

    for action in reversed(actions):
        candidates: list[tuple[int, int, str]] = []
        for category, pattern in _CATEGORY_PATTERNS:
            for noun in pattern.finditer(value):
                if noun.start() >= action.end():
                    candidates.append((0, noun.start() - action.end(), category))
                elif action.start() >= noun.end():
                    candidates.append((1, action.start() - noun.end(), category))

        if not candidates:
            continue

        direction, gap, category = min(candidates, key=lambda item: (item[0], item[1]))
        if (direction == 0 and gap <= 120) or (direction == 1 and gap <= 60):
            return category

    return None


class PreferredDocumentCategory(Filter):
    async def __call__(self, message: Message, state: FSMContext):
        text = message.text or ""
        if not text or text.startswith("/"):
            return False

        data = await state.get_data()
        mode = data.get("mode")

        # Once the user entered the claim section and KORGAN is waiting for the
        # case description, the next text belongs to the claim workflow only.
        if mode == "universal_claim_waiting":
            return {"document_category": "claim"}

        # Other active sections already have their own state-bound handlers.
        if mode not in {None, "", "main"}:
            return False

        category = preferred_document_category(text)
        if category is None:
            return False
        return {"document_category": category}


@router.message(PreferredDocumentCategory(), F.text)
async def route_explicit_document_request(
    message: Message,
    state: FSMContext,
    document_category: str,
) -> None:
    # Lazy imports are deliberate. The morning production runtime installs its
    # quality/RAG hotfix layer before importing these generator modules; category
    # isolation must not change that initialization order.
    from korgan import pretrial_response_runtime, pretrial_runtime, universal_claim_runtime, universal_document_runtime

    data = await state.get_data()

    if document_category == "claim":
        if data.get("mode") == "universal_claim_waiting":
            await universal_claim_runtime.claim_description(message, state)
        else:
            await universal_claim_runtime.claim_from_one_message(message, state)
        return

    if document_category == "pretrial_response":
        await pretrial_response_runtime.pretrial_response_natural(message, state)
        return

    if document_category == "pretrial":
        await pretrial_runtime.pretrial_natural(message, state)
        return

    if document_category == "response":
        await universal_document_runtime.response_request(message, state)
        return

    if document_category == "contract":
        await universal_document_runtime.contract_request(message, state)
