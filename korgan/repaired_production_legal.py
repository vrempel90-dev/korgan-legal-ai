from __future__ import annotations

import re

from korgan.legal_types import ClaimDraft, LegalResearch
from korgan.production_legal import ProductionOpenAILegalService as _BaseProductionOpenAILegalService


_CLAIMANT_ROLE_MARKERS = (
    "истец",
    "истца",
    "истцу",
    "займодав",
    "кредитор",
)

_DEFENDANT_ROLE_MARKERS = (
    "ответчик",
    "ответчика",
    "ответчику",
    "заемщик",
    "заёмщик",
    "должник",
)


def _normalize(value: str) -> str:
    return re.sub(r"[^0-9a-zа-яё]+", "", value.lower())


def _party_for_prefix(prefix: str) -> str | None:
    lowered = prefix.lower()
    if any(marker in lowered for marker in _CLAIMANT_ROLE_MARKERS):
        return "claimant"
    if any(marker in lowered for marker in _DEFENDANT_ROLE_MARKERS):
        return "defendant"
    return None


def _append_if_missing(target: list[str], label: str, value: str) -> None:
    clean = value.strip()
    if not clean or clean.lower() == "не установлено":
        return
    normalized_existing = _normalize("\n".join(target))
    if _normalize(clean) in normalized_existing:
        return
    target.append(f"{label}: {clean}")


def _restore_role_bound_bucket(
    case_context: str,
    draft: ClaimDraft,
    bucket: str,
    label: str,
) -> None:
    for line in case_context.splitlines():
        if not line.startswith(bucket):
            continue
        raw = line.split(":", 1)[1].strip()
        if not raw or raw.lower() == "не установлено":
            continue

        for value in raw.split(";"):
            candidate = value.strip()
            if ":" not in candidate:
                continue
            prefix, remainder = candidate.split(":", 1)
            party = _party_for_prefix(prefix)
            if party == "claimant":
                _append_if_missing(draft.claimant, label, remainder)
            elif party == "defendant":
                _append_if_missing(draft.defendant, label, remainder)


def _remove_unsupported_conditionals(draft: ClaimDraft) -> None:
    """Drop optional court-text items that the model itself marked as conditional.

    A filing-ready claim must not contain things such as "доверенность — при наличии".
    If the source materials do not establish such an item, omitting it is safer than
    releasing a conditional instruction inside the court document.
    """

    for field_name in ("facts", "legal_basis", "requests", "attachments"):
        values = list(getattr(draft, field_name))
        cleaned = [item for item in values if "при наличии" not in item.lower()]
        setattr(draft, field_name, cleaned)


def _prepare_draft_for_validation(case_context: str, draft: ClaimDraft) -> None:
    _remove_unsupported_conditionals(draft)

    # Restore only requisites that the extractor explicitly bound to one party.
    # Generic locations/contacts are intentionally ignored to avoid role mixups.
    _restore_role_bound_bucket(case_context, draft, "Адреса:", "Адрес")
    _restore_role_bound_bucket(case_context, draft, "Идентификаторы:", "ИИН/БИН")
    _restore_role_bound_bucket(case_context, draft, "Контакты:", "Контакт")


class ProductionOpenAILegalService(_BaseProductionOpenAILegalService):
    """Production service with deterministic pre-QA repair and the original hard gate."""

    async def validate_claim(
        self,
        case_context: str,
        research: LegalResearch,
        draft: ClaimDraft,
    ) -> dict[str, list[str]]:
        _prepare_draft_for_validation(case_context, draft)
        return await super().validate_claim(case_context, research, draft)
