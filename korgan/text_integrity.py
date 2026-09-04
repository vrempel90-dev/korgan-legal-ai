"""Detect text that was cut or glued together between pipeline steps.

The reported artefact was «...не предусмотрено иное».евидно» — a closing quote
with the tail of a word welded to it, the head of that word gone. Whatever
produced it (a truncated model response, a re-glued fragment), the document must
not ship carrying it, and the check has to run on every document type rather
than on the section where it was spotted.

These are shape checks on the finished text. They are deliberately narrow: each
pattern describes damage that correct legal Russian does not produce, so a
finding means the text is broken, not merely unusual.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

_LOWER = "а-яёa-z"

_UPPER = "А-ЯЁA-Z"

# The damage is always *missing whitespace*: a closing quote or a sentence end
# welded straight onto the next word. Legal Russian never does that, while
# «Астана Логистик», БИН — quote, punctuation, space — is perfectly ordinary and
# must not be flagged. Every pattern below is therefore anchored on the absence
# of a space and is case-sensitive on purpose.
_PATTERNS: tuple[tuple[str, str, str], ...] = (
    (
        "closing_quote_glued",
        rf"[»”][.,;:]?[{_LOWER}{_UPPER}]",
        "к закрывающей кавычке приклеено слово без пробела (например «».евидно»)",
    ),
    (
        "sentence_glued",
        rf"[{_LOWER}]{{3,}}\.[{_LOWER}{_UPPER}]{{2}}",
        "точка между словами без пробела — склейка двух фрагментов текста",
    ),
    (
        "opening_quote_glued",
        rf"[{_LOWER}{_UPPER}]«",
        "открывающая кавычка приклеена к предыдущему слову",
    ),
    (
        # Not `[.,;:]{2,}`: «Сериков А.Б., ИИН» and «…» are ordinary. Only
        # sequences that no correct text produces are flagged.
        "repeated_punctuation",
        r",{2,}|;{2,}|:{2,}|,\.",
        "повторяющаяся пунктуация — след склейки фрагментов",
    ),
    (
        "space_before_punctuation",
        r"\s+[,;:]",
        "пробел перед знаком препинания",
    ),
)

# Abbreviations and identifiers where a dot legitimately sits inside a token.
_ALLOWED = re.compile(
    r"|".join(
        (
            r"\b(?:т\.е|т\.к|т\.д|т\.п|и\.о|см\.|стр\.|гл\.|ст\.|п\.п|пп\.|руб\.|тг\.)",
            # Initials: «Сериков А.Б.» — a dot inside the token is correct here.
            r"\b[А-ЯЁ]\.\s?[А-ЯЁ]\.",
            r"\b(?:kz|ru|com|org|net|gov)\b",
            r"\d+\.\d+",
            r"https?://\S+",
            # Адрес электронной почты и доменное имя устроены как «слово.слово»:
            # точка внутри токена здесь правильна. Статья 148 ГПК РК требует
            # указывать сведения о сторонах, поэтому такие реквизиты в иске
            # обычны, а сообщение о «склейке» из-за них не позволяло выпустить
            # уже готовый документ. E-mail стоит первым: доменная альтернатива
            # иначе закрыла бы только хвост адреса и оставила «test.claimant»
            # видимым для проверки склеек.
            r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+",
            r"\b[\w-]+(?:\.[\w-]+)*\.(?:kz|ru|com|org|net|gov|edu)\b",
        )
    ),
    re.IGNORECASE,
)


@dataclass(slots=True)
class IntegrityFinding:
    code: str
    description: str
    excerpt: str

    def as_note(self) -> str:
        return f"{self.description}: «{self.excerpt}»"


def _mask_allowed(text: str) -> str:
    """Mask spans where the suspicious shape is legitimate, preserving offsets.

    The filler must not be whitespace: masking «Сериков А.Б., ИИН» with spaces
    would manufacture a space before the comma and report damage that is not
    there. `_` matches none of the patterns above.
    """
    return _ALLOWED.sub(lambda match: "_" * len(match.group(0)), text)


def unbalanced_quotes(text: str) -> bool:
    return text.count("«") != text.count("»")


def integrity_findings(text: str) -> list[IntegrityFinding]:
    """Return every structural damage found in ``text``."""
    if not text:
        return []

    masked = _mask_allowed(text)
    findings: list[IntegrityFinding] = []

    for code, pattern, description in _PATTERNS:
        # Case-sensitive: lower/upper distinction is what separates damage from
        # ordinary punctuation here.
        for match in re.finditer(pattern, masked):
            start = max(0, match.start() - 40)
            end = min(len(text), match.end() + 40)
            excerpt = " ".join(text[start:end].split())
            findings.append(IntegrityFinding(code, description, excerpt))

    if unbalanced_quotes(text):
        findings.append(
            IntegrityFinding(
                "unbalanced_quotes",
                "непарные кавычки — цитата оборвана",
                f"«: {text.count('«')}, »: {text.count('»')}",
            )
        )

    return findings


def is_intact(text: str) -> bool:
    return not integrity_findings(text)
