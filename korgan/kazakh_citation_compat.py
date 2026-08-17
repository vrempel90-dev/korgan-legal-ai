from __future__ import annotations

import importlib
import re

_KK_ARTICLE = re.compile(r"\b(?P<article>\d+(?:-\d+)?)\s*[-–]?\s*ба[пб](?:ы|тың|тің|та|те|қа|ке|пен|ында|інде|ынан|інен)?\b", re.IGNORECASE)


def install_kazakh_citation_compat() -> None:
    """Accept Kazakh legal morphology in the existing fail-closed gates."""
    from korgan import citation_audit

    citation_audit._REFERENCE_RE = re.compile(
        r"(?=(?:(?:(?:част[ьияею]\w*|ч\.|подпункт\w*|пп\.|пункт\w*|п\.)\s*\d+\s*)?(?:стать[ияеёю]\w*|ст\.)|\d+(?:-\d+)?\s*[-–]?\s*ба[пб]))"
        r"(?:(?:част[ьияею]\w*|ч\.|подпункт\w*|пп\.|пункт\w*|п\.)\s*(?P<part>\d+)\s*)?"
        r"(?:(?:стать[ияеёю]\w*|ст\.)\s*)?(?P<article>\d+(?:-\d+)?)"
        r"(?:\s*[-–]?\s*ба[пб](?:ы|тың|тің|та|те|қа|ке|пен|ында|інде|ынан|інен)?)?"
        r"(?P<tail>[^.;)\n]{0,60})",
        re.IGNORECASE,
    )
    citation_audit._ACT_PATTERNS = citation_audit._ACT_PATTERNS + (
        (r"қр\s*апк|азаматтық\s+процестік\s+кодекс", "ГПК РК"),
        (r"қр\s*ак|азаматтық\s+кодекс", "ГК РК"),
        (r"қр\s*ск|салық\s+кодекс", "НК РК"),
        (r"қр\s*ек|еңбек\s+кодекс", "ТК РК"),
        (r"қр\s*әрпк|әкімшілік\s+рәсімдік", "КАС РК"),
        (r"қр\s*әкқбтк|әкімшілік\s+құқық\s+бұзушылық", "КоАП РК"),
    )

    bilingual = re.compile(r"(?i)(?:(?:стать[ьяиеёю]\w*|ст\.)\s*\d+(?:-\d+)?|\b\d+(?:-\d+)?\s*[-–]?\s*ба[пб](?:ы|тың|тің|та|те|қа|ке|пен|ында|інде|ынан|інен)?\b)")
    for module_name, attribute in (("korgan.document_quality", "_ARTICLE_RE"), ("korgan.claim_quality_hotfix", "_ARTICLE_TOKEN_RE")):
        try:
            module = importlib.import_module(module_name)
        except ImportError:
            continue
        if hasattr(module, attribute):
            setattr(module, attribute, bilingual)

    try:
        from korgan import response_legal
        original_has_166 = response_legal._has_article_166
        original_allowed = response_legal._allowed_article_numbers
        original_in_text = response_legal._article_numbers_in_text

        def has_166_bilingual(claims: list[str]) -> bool:
            return original_has_166(claims) or any(m.group("article") == "166" for item in claims for m in _KK_ARTICLE.finditer(item or ""))

        def allowed_bilingual(claims: list[str]) -> set[str]:
            result = set(original_allowed(claims))
            result.update(m.group("article") for item in claims for m in _KK_ARTICLE.finditer(item or ""))
            return result

        def in_text_bilingual(text: str) -> set[str]:
            result = set(original_in_text(text))
            result.update(m.group("article") for m in _KK_ARTICLE.finditer(text or ""))
            return result

        response_legal._has_article_166 = has_166_bilingual
        response_legal._allowed_article_numbers = allowed_bilingual
        response_legal._article_numbers_in_text = in_text_bilingual
    except (ImportError, AttributeError):
        pass

    try:
        from korgan import response_menu_handlers
        original_claim_materials = response_menu_handlers._looks_like_claim_materials

        def looks_like_claim_materials_bilingual(context: str) -> bool:
            if original_claim_materials(context):
                return True
            text = " ".join((context or "").split()).lower()
            return bool(
                ("талап қою" in text or "талап-арыз" in text)
                and ("талап қоюшы" in text or "талапкер" in text)
                and "жауапкер" in text
            )

        response_menu_handlers._looks_like_claim_materials = looks_like_claim_materials_bilingual
    except (ImportError, AttributeError):
        pass
