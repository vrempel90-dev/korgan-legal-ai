from __future__ import annotations

import re

from korgan.document_category_router import preferred_document_category

# Direct requests without a drafting verb are still supported, but the contract
# noun must be the object of the request itself. This deliberately does NOT match
# factual phrases such as «хочу отказаться от договора» or «нужно взыскать деньги
# по договору».
_DIRECT_CONTRACT_REQUEST = re.compile(
    r"(?:"
    r"\b(?:(?:мне|нам)\s+)?(?:нужен|нужна|нужно|хочу|прошу)\s+(?:проект\s+)?"
    r"(?:договор\w*|соглашени\w*|контракт\w*|nda)\b|"
    r"^\s*(?:договор\w*|соглашени\w*|контракт\w*|nda)\s*$"
    r")",
    re.IGNORECASE,
)
_ADVICE_ONLY = re.compile(
    r"^\s*(?:как|каким образом|что нужно(?:,)? чтобы|что нужно для)\s+(?:подготов\w*|состав\w*|сдел\w*|оформ\w*)",
    re.IGNORECASE,
)


def is_contract_drafting_request(text: str | None) -> bool:
    """Return True only when the client actually asks KORGAN for a contract.

    Contract disputes naturally contain many mentions of a договор. The old
    detector treated any drafting verb anywhere in the message plus any later
    mention of a contract as a contract request, so an иск about a contract could
    be hijacked. The shared strict category classifier now owns every explicit
    drafting command. Direct no-verb requests are accepted only when the contract
    itself is the requested object.
    """
    if not text:
        return False
    cleaned = " ".join(text.split())
    if _ADVICE_ONLY.search(cleaned):
        return False

    explicit_category = preferred_document_category(cleaned)
    if explicit_category is not None:
        return explicit_category == "contract"

    return bool(_DIRECT_CONTRACT_REQUEST.search(cleaned))
