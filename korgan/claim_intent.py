from __future__ import annotations

import re

_CLAIM_NOUN = re.compile(
    r"(?:"
    r"\bиск(?:а|у|ом|е|и|ов|ами|ах)?\b|\bисков\w*\s+заявлен\w*|"
    r"\bталап\s+қою\s+арыз\w*|\bталап\s+арыз\w*|\bталап-арыз\w*"
    r")",
    re.IGNORECASE,
)
_CLAIM_ACTION = re.compile(
    r"\b(?:"
    r"подготов\w*|состав\w*|сдел\w*|сформир\w*|напиш\w*|напис\w*|созда\w*|сгенерир\w*|оформ\w*|"
    r"дайында\w*|жаса\w*|құрастыр\w*|әзірле\w*|жаз\w*|қалыптастыр\w*"
    r")\b",
    re.IGNORECASE,
)
_CLAIM_WANT = re.compile(
    r"(?:"
    r"\b(?:мне\s+)?(?:нужен|нужно|нужна|хочу|прошу)\b.{0,120}(?:\bиск(?:а|у|ом|е|и)?\b|\bисков\w*\s+заявлен\w*)|"
    r"\b(?:маған|бізге)\b.{0,80}\b(?:талап\s+қою\s+арыз\w*|талап\s+арыз\w*)\b"
    r")",
    re.IGNORECASE | re.DOTALL,
)
_ADVICE_ONLY = re.compile(
    r"^\s*(?:"
    r"как|каким образом|что нужно(?:,)? чтобы|что нужно для|"
    r"қалай|не істеу керек|не қажет"
    r")\s+(?:подготов\w*|состав\w*|сдел\w*|оформ\w*|дайында\w*|жаса\w*|құрастыр\w*|әзірле\w*)",
    re.IGNORECASE,
)


def is_claim_drafting_request(text: str | None) -> bool:
    """True when the user asks KORGAN to actually prepare a court claim."""
    if not text:
        return False
    cleaned = " ".join(text.split())
    if not _CLAIM_NOUN.search(cleaned):
        return False
    if _ADVICE_ONLY.search(cleaned):
        return False
    return bool(_CLAIM_ACTION.search(cleaned) or _CLAIM_WANT.search(cleaned))
