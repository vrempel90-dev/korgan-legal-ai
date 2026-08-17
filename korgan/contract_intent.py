from __future__ import annotations

import re

_CONTRACT_NOUN = re.compile(r"(?:\bдоговор\w*\b|\bсоглашени\w*\b|\bконтракт\w*\b|\bnda\b|\bшарт\w*\b|\bкелісім\w*\b)", re.IGNORECASE)
_CONTRACT_ACTION = re.compile(
    r"\b(?:подготов\w*|состав\w*|сдел\w*|сформир\w*|напиш\w*|напис\w*|созда\w*|сгенерир\w*|оформ\w*|разработ\w*|дайында\w*|жаса\w*|құрастыр\w*|әзірле\w*|жаз\w*|қалыптастыр\w*)\b",
    re.IGNORECASE,
)
_CONTRACT_WANT = re.compile(
    r"(?:\b(?:мне\s+)?(?:нужен|нужно|нужна|хочу|прошу)\b.{0,160}(?:\bдоговор\w*\b|\bсоглашени\w*\b|\bконтракт\w*\b|\bnda\b)|\b(?:маған|бізге)\b.{0,100}\b(?:шарт\w*|келісім\w*)\b)",
    re.IGNORECASE | re.DOTALL,
)
_ADVICE_ONLY = re.compile(
    r"^\s*(?:как|каким образом|что нужно(?:,)? чтобы|что нужно для|қалай|не істеу керек|не қажет)\s+(?:подготов\w*|состав\w*|сдел\w*|оформ\w*|дайында\w*|жаса\w*|құрастыр\w*|әзірле\w*)",
    re.IGNORECASE,
)


def is_contract_drafting_request(text: str | None) -> bool:
    if not text:
        return False
    cleaned = " ".join(text.split())
    if not _CONTRACT_NOUN.search(cleaned):
        return False
    if _ADVICE_ONLY.search(cleaned):
        return False
    return bool(_CONTRACT_ACTION.search(cleaned) or _CONTRACT_WANT.search(cleaned))
