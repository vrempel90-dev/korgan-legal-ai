"""Versioned corpus of Kazakhstan provisions KORGAN may cite without re-verifying.

This project has no vector store: `korgan.rag` is a trusted-host helper and
Pinecone ingestion was removed. Legal research runs through OpenAI web search
over adilet.zan.kz, which means a provision that the consultation pass already
confirmed gets re-checked — and silently downgraded to NEEDS_VERIFICATION — when
the document pass runs. This module is the deterministic half of that answer:
provisions stable enough to cite from code, each carrying its act id, article
number, source URL and the date its wording was last checked.

VERIFICATION STATUS: entries were checked on 2026-08-15 against secondary legal
databases only. adilet.zan.kz and sud.gov.kz are unreachable from this
environment (egress proxy), so no entry here has been read from the official
source by the code that ships it. `Provision.official_check_pending` marks that
explicitly: a lawyer must confirm each wording against adilet before release,
and the flag surfaces in the claim's verification notes.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date

CHECKED_ON = date(2026, 8, 15)

GK_GENERAL = "https://adilet.zan.kz/rus/docs/K940001000_"
GK_SPECIAL = "https://adilet.zan.kz/rus/docs/K990000409_"
GPK = "https://adilet.zan.kz/rus/docs/K1500000377"


@dataclass(frozen=True, slots=True)
class Provision:
    key: str
    act: str
    article: str
    title: str
    summary: str
    source_url: str
    checked_on: date = CHECKED_ON
    official_check_pending: bool = True

    def citation(self) -> str:
        """Wording for the claim's legal-basis section."""
        return f"{self.summary} ({self.article} {self.act})"

    def as_verified_claim(self) -> str:
        """Same shape research results use, so both paths stay comparable."""
        return f"{self.summary} [статья {self.article}; источник: {self.source_url}]"


LOAN_REPAYMENT = Provision(
    key="gk_715",
    act="ГК РК (Особенная часть)",
    article="715",
    title="Договор займа",
    summary=(
        "по договору займа заёмщик обязан возвратить займодателю предмет займа "
        "в срок и в порядке, которые предусмотрены договором"
    ),
    source_url=GK_SPECIAL,
)

LOAN_RETURN_ORDER = Provision(
    key="gk_722",
    act="ГК РК (Особенная часть)",
    article="722",
    title="Возврат предмета займа",
    summary="заёмщик обязан возвратить предмет займа в порядке и сроки, предусмотренные договором займа",
    source_url=GK_SPECIAL,
)

LOAN_INDIVIDUAL_BORROWER = Provision(
    key="gk_725_1",
    act="ГК РК (Особенная часть)",
    article="725-1",
    title="Особенности договора займа, заключаемого с заёмщиком — физическим лицом",
    summary=(
        "договор займа с заёмщиком — физическим лицом должен содержать годовую эффективную ставку "
        "вознаграждения; требования не распространяются на займодателей, указанных в пункте 2 статьи 718 "
        "ГК РК, и не применяются к договорам, заключённым до 16.07.2018"
    ),
    source_url=GK_SPECIAL,
)

LATE_PAYMENT_INTEREST = Provision(
    key="gk_353",
    act="ГК РК (Общая часть)",
    article="353",
    title="Ответственность за неправомерное пользование чужими деньгами",
    summary=(
        "за неправомерное пользование чужими деньгами вследствие просрочки в их уплате подлежит уплате "
        "неустойка, исчисляемая исходя из базовой ставки Национального Банка Республики Казахстан "
        "на день исполнения денежного обязательства; при взыскании долга в судебном порядке размер "
        "неустойки может определяться по выбору кредитора — на день предъявления иска, вынесения решения "
        "или фактического платежа"
    ),
    source_url=GK_GENERAL,
)

GENERAL_TERRITORIAL_JURISDICTION = Provision(
    key="gpk_29",
    act="ГПК РК",
    article="29",
    title="Предъявление иска по месту жительства ответчика",
    summary="иск предъявляется в суд по месту жительства ответчика",
    source_url=GPK,
)

CLAIM_FORM_AND_ATTACHMENTS = Provision(
    key="gpk_148_149",
    act="ГПК РК",
    article="148, 149",
    title="Форма и содержание искового заявления, прилагаемые документы",
    summary=(
        "исковое заявление должно соответствовать установленным требованиям к форме и содержанию, "
        "к нему прилагаются предусмотренные законом документы"
    ),
    source_url=GPK,
)

CORPUS: dict[str, Provision] = {
    provision.key: provision
    for provision in (
        LOAN_REPAYMENT,
        LOAN_RETURN_ORDER,
        LOAN_INDIVIDUAL_BORROWER,
        LATE_PAYMENT_INTEREST,
        GENERAL_TERRITORIAL_JURISDICTION,
        CLAIM_FORM_AND_ATTACHMENTS,
    )
}

PENDING_OFFICIAL_CHECK_NOTE = (
    "Нормы, подставленные из внутреннего корпуса KORGAN ({articles}), сверены по состоянию "
    "на {checked}, но не подтверждены прямым чтением adilet.zan.kz — перед подачей проверьте "
    "редакцию по официальному источнику."
)


def pending_check_note(provisions: list[Provision]) -> str:
    articles = ", ".join(f"ст. {item.article} {item.act}" for item in provisions)
    return PENDING_OFFICIAL_CHECK_NOTE.format(articles=articles, checked=CHECKED_ON.strftime("%d.%m.%Y"))


# «статья 353 ГК РК», «ст. 29 ГПК», «статьями 715 и 722 ГК РК».
_ARTICLE_PATTERN = re.compile(
    r"(?:стат(?:ья|ьи|ье|ьей|ьям|ьями|ей)|ст\.)\s*(\d+(?:-\d+)?)"
    r"(?:\s*(?:и|,)\s*(\d+(?:-\d+)?))*"
    r"[^.;:\n]{0,40}?(ГК|ГПК|НК|УК|АППК|КоАП)",
    re.IGNORECASE,
)


def extract_cited_articles(text: str) -> list[str]:
    """Articles a consultation answer relied on, e.g. «ст. 353 ГК».

    The consultation pass confirms provisions through web search, but its answer
    is free text that nothing carries into the document pass — so the same
    provision gets re-researched and, on a weaker search, downgraded. Extracting
    the citations lets the case keep them.
    """
    seen: list[str] = []
    for match in _ARTICLE_PATTERN.finditer(text or ""):
        code = match.group(match.lastindex).upper()
        for group in range(1, match.lastindex):
            number = match.group(group)
            if not number:
                continue
            citation = f"ст. {number} {code}"
            if citation not in seen:
                seen.append(citation)
    return seen
