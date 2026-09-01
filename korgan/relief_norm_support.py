"""Есть ли у заявленной санкции собственное основание.

Норма о надлежащем исполнении говорит одно: обязательство надо исполнить. Ни
неустойки, ни убытков, ни морального вреда из неё не следует — у каждого из этих
требований своё основание. Неустойка существует лишь там, где её предусмотрели
законодательство или договор; моральный вред — лишь там, где его допускает
закон.

Пайплайн этого не различал. Иск требовал 450 000 тенге неустойки, всё правовое
обоснование состояло из подтверждённой статьи 272 ГК РК, и документ уходил
клиенту с оценкой 10.0: статья настоящая, текст нормы подлинный, пересказ
точный. Проверка цитат такой дефект увидеть не может — она сверяет норму с
пересказом, а не требование с нормой.

Основанием здесь считается только то, что документ не может выписать себе сам:

* текст нормы, привязанный к официальному источнику (Adilet), — он приходит
  из исследования, а не из формулировки модели;
* условие договора, названное в материалах дела, — там, где закон допускает
  договорное основание.

Собственная фраза документа «ответчик обязан уплатить неустойку» основанием не
является: это ровно то утверждение, которое проверяется. Модуль не подбирает
норму и не удаляет требование — он не даёт назвать документ готовым, пока
основание требования не появилось.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from korgan.citation_audit import runtime_provisions


@dataclass(frozen=True, slots=True)
class Remedy:
    """Требование, которое не выводится из общей нормы об исполнении."""

    code: str
    label: str
    demanded: re.Pattern[str]
    authority: re.Pattern[str]
    contractual: bool
    guidance: str


REMEDIES: tuple[Remedy, ...] = (
    Remedy(
        code="penalty",
        label="неустойка (пеня, штраф)",
        demanded=re.compile(r"неустойк\w*|\bпен[яию]\b|\bпени\b|\bштраф\w*", re.IGNORECASE),
        authority=re.compile(r"неустойк\w*|\bпен[яию]\b|\bпени\b|\bштраф\w*", re.IGNORECASE),
        contractual=True,
        guidance=(
            "неустойка взыскивается только тогда, когда она предусмотрена законодательством "
            "или письменным договором: нужна норма о неустойке либо условие договора о ней"
        ),
    ),
    Remedy(
        code="damages",
        label="убытки",
        demanded=re.compile(r"убытк\w*|упущенн\w*\s+выгод\w*|реальн\w*\s+ущерб\w*", re.IGNORECASE),
        authority=re.compile(r"убытк\w*|упущенн\w*\s+выгод\w*|ущерб\w*|возмещени\w*\s+вред\w*", re.IGNORECASE),
        contractual=True,
        guidance=(
            "убытки взыскиваются по норме об их возмещении, с составом ответственности "
            "и причинной связью"
        ),
    ),
    Remedy(
        code="moral",
        label="компенсация морального вреда",
        demanded=re.compile(r"моральн\w*\s+вред\w*", re.IGNORECASE),
        authority=re.compile(r"моральн\w*\s+вред\w*|неимущественн\w*\s+вред\w*", re.IGNORECASE),
        # Моральный вред возникает из закона: условие договора его не создаёт.
        contractual=False,
        guidance="компенсация морального вреда возможна только в случаях, предусмотренных законом",
    ),
    Remedy(
        code="interest",
        label="проценты за пользование чужими деньгами",
        demanded=re.compile(
            r"процент\w*\s+за\s+пользован\w*|вознагражден\w*\s+за\s+пользован\w*", re.IGNORECASE
        ),
        authority=re.compile(r"процент\w*|вознагражден\w*|ставк\w*\s+рефинансирован\w*", re.IGNORECASE),
        contractual=True,
        guidance=(
            "проценты за пользование чужими деньгами взыскиваются по норме о них "
            "либо по условию договора"
        ),
    ),
)

_CONTRACT_CLAUSE_RE = re.compile(
    r"(?:пункт\w*|\bп\.|подпункт\w*|\bпп\.|раздел\w*|стать\w*)\s*[\d.]+\s*(?:договор\w*|соглашени\w*)|"
    r"(?:договор\w*|соглашени\w*)\w*\s+(?:предусмотрен\w*|установлен\w*|согласован\w*)|"
    r"(?:предусмотрен\w*|установлен\w*|согласован\w*)\s+(?:пункт\w*\s*[\d.]+\s*)?договор\w*",
    re.IGNORECASE,
)

_SENTENCE_SPLIT_RE = re.compile(r"(?<=[.;!?])\s+")


def _sentences(values: list[str] | None) -> list[str]:
    result: list[str] = []
    for value in values or []:
        for part in _SENTENCE_SPLIT_RE.split(str(value or "")):
            if part.strip():
                result.append(part.strip())
    return result


def _provision_texts(*sources: list[str] | None) -> list[str]:
    """Тексты норм, привязанные к официальному источнику.

    Берутся только через runtime_provisions: там уже проверено, что строка имеет
    канонический вид, ведёт на Adilet и несёт пригодную выдержку нормы. Любая
    другая строка — это формулировка модели, и основанием она быть не может.
    """
    texts: list[str] = []
    for source in sources:
        for provision in runtime_provisions(list(source or [])):
            if provision.text not in texts:
                texts.append(provision.text)
    return texts


def _has_statutory_support(remedy: Remedy, provisions: list[str]) -> bool:
    return any(remedy.authority.search(text) for text in provisions)


def _has_contract_support(remedy: Remedy, materials: list[str]) -> bool:
    """Условие договора о требовании, названное в материалах дела."""
    if not remedy.contractual:
        return False
    return any(
        remedy.authority.search(sentence) and _CONTRACT_CLAUSE_RE.search(sentence)
        for sentence in materials
    )


def unsupported_relief(
    *,
    requests: list[str] | None,
    legal_basis: list[str] | None = None,
    case_context: str = "",
    facts: list[str] | None = None,
    verified_claims: list[str] | None = None,
) -> list[str]:
    """Требования, у которых в деле нет собственного основания."""
    demanded = _sentences(requests)
    if not demanded:
        return []

    provisions = _provision_texts(verified_claims, legal_basis)
    materials = _sentences([case_context, *(facts or []), *(legal_basis or [])])

    findings: list[str] = []
    for remedy in REMEDIES:
        if not any(remedy.demanded.search(sentence) for sentence in demanded):
            continue
        if _has_statutory_support(remedy, provisions):
            continue
        if _has_contract_support(remedy, materials):
            continue
        findings.append(
            f"заявлено требование «{remedy.label}», но в деле нет его основания: "
            f"ни подтверждённой нормы об этом требовании, ни условия договора о нём; "
            f"{remedy.guidance}"
        )
    return findings
