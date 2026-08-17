"""Feature-flagged, law-aware entry into the local Kazakhstan corpus.

The local database is a retrieval accelerator, never an authority shortcut.
Every candidate still goes through KORGAN's existing source-bound verification.
When the corpus is absent, empty or irrelevant the caller falls back to official
web research.
"""

from __future__ import annotations

import logging
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from korgan.legal.corpus import DEFAULT_DB_PATH, LegalCorpus, Provision
from korgan.legal.rk_catalog import KNOWN_ACTS
from korgan.legal.validator import build_offer

LOGGER = logging.getLogger(__name__)

FLAG_ENV = "KORGAN_LOCAL_CORPUS"
_TRUTHY = {"1", "true", "yes", "on"}
DEFAULT_LIMIT = 12

_ROUTE_RULES: tuple[tuple[re.Pattern[str], tuple[str, ...]], ...] = (
    (re.compile(r"(?i)заработ|зарплат|трудов|работник|работодател|увольнен|отпуск|еңбек|жалақ|жұмыс беруш"), ("TK_RK", "GPK_RK")),
    (re.compile(r"(?i)потребител|магазин|товар|услуг|подряд|ремонт|заказчик|тұтынуш"), ("ZPP_RK", "GK_RK_OSOBENNAYA", "GK_RK_OBSHAYA", "GPK_RK")),
    (re.compile(r"(?i)займ|за[её]м|расписк|долг|қарыз|борыш"), ("GK_RK_OSOBENNAYA", "GK_RK_OBSHAYA", "GPK_RK")),
    (re.compile(r"(?i)семь|брак|супруг|развод|алимент|ребен|отцовств|неке|отбасы|алимент"), ("FAMILY_RK", "GPK_RK")),
    (re.compile(r"(?i)административн\w*\s+(?:иск|суд|орган|акт)|аппк|кас\s*рк|әкімшілік.*(?:сот|орган|акт)"), ("APPC_RK",)),
    (re.compile(r"(?i)административн\w*\s+правонаруш|коап|штраф\w*\s+(?:полици|адм)|әкімшілік\s+құқық\s*бұз"), ("KOAP_RK",)),
    (re.compile(r"(?i)уголовн|преступлен|подозреваем|обвиняем|ук\s*рк|қылмы"), ("CRIMINAL_RK", "CRIMINAL_PROCEDURE_RK")),
    (re.compile(r"(?i)исполнительн\w*\s+производ|судебн\w*\s+исполнител|чси\b|атқаруш"), ("ENFORCEMENT_RK", "GPK_RK")),
    (re.compile(r"(?i)жилищ|квартир|выселен|кск|оси\b|тұрғын\s*үй"), ("HOUSING_RK", "GK_RK_OBSHAYA", "GPK_RK")),
    (re.compile(r"(?i)банк\w*|кредит|ипотек|микрокредит|мфо|коллектор|несие"), ("BANKS_RK", "MICROFINANCE_RK", "COLLECTION_RK", "GK_RK_OBSHAYA", "GPK_RK")),
    (re.compile(r"(?i)банкротств\w*\s+граждан|неплатежеспособ|төлем\s*қабілет"), ("CITIZEN_BANKRUPTCY_RK",)),
    (re.compile(r"(?i)нотариус|нотариаль|исполнительн\w*\s+надпис|нотариат"), ("NOTARIAT_RK",)),
    (re.compile(r"(?i)земел|участок|землепольз|жер\s+учас"), ("LAND_RK",)),
    (re.compile(r"(?i)госзакуп|государственн\w*\s+закуп|мемлекеттік\s+сатып"), ("PUBLIC_PROCUREMENT_RK",)),
    (re.compile(r"(?i)предпринимател|бизнес|ип\b|тоо\b|кәсіпкер"), ("ENTREPRENEUR_RK", "GK_RK_OBSHAYA", "GPK_RK")),
    (re.compile(r"(?i)социальн|пенси|пособ|соцвыплат|әлеуметтік|зейнет"), ("SOCIAL_RK",)),
    (re.compile(r"(?i)медицин|здоров|пациент|денсаулық"), ("HEALTH_RK",)),
    (re.compile(r"(?i)конституц|конституциялық"), ("CONSTITUTION_RK",)),
)

_EXPLICIT_ACTS: tuple[tuple[re.Pattern[str], tuple[str, ...]], ...] = (
    (re.compile(r"(?i)\bгпк\s*рк\b|гражданск\w*\s+процессуальн\w*\s+кодекс"), ("GPK_RK",)),
    (re.compile(r"(?i)\bтк\s*рк\b|трудов\w*\s+кодекс"), ("TK_RK",)),
    (re.compile(r"(?i)\bаппк\s*рк\b|\bкас\s*рк\b|административн\w*\s+процедурно"), ("APPC_RK",)),
    (re.compile(r"(?i)\bкоап\s*рк\b|кодекс.*административн\w*\s+правонаруш"), ("KOAP_RK",)),
    (re.compile(r"(?i)\bупк\s*рк\b|уголовно-процессуальн\w*\s+кодекс"), ("CRIMINAL_PROCEDURE_RK",)),
    (re.compile(r"(?i)\bук\s*рк\b|уголовн\w*\s+кодекс"), ("CRIMINAL_RK",)),
    (re.compile(r"(?i)\bгк\s*рк\b|гражданск\w*\s+кодекс"), ("GK_RK_OBSHAYA", "GK_RK_OSOBENNAYA")),
)
_ARTICLE_NO_RE = re.compile(r"(?i)(?:стать(?:я|и|е|ю|ёй|ей)|ст\.|бап(?:тың|қа|та|та)?|бабы)\s*(\d+(?:-\d+)?)")


def local_corpus_enabled() -> bool:
    return os.getenv(FLAG_ENV, "").strip().lower() in _TRUTHY


def route_act_ids(query: str) -> tuple[str, ...]:
    value = str(query or "")
    explicit: list[str] = []
    for pattern, act_ids in _EXPLICIT_ACTS:
        if pattern.search(value):
            explicit.extend(act_ids)
    if explicit:
        if "GPK_RK" not in explicit and not any(
            x in explicit for x in ("APPC_RK", "CRIMINAL_PROCEDURE_RK", "KOAP_RK")
        ):
            explicit.append("GPK_RK")
        return tuple(dict.fromkeys(x for x in explicit if x in KNOWN_ACTS))

    routed: list[str] = []
    for pattern, act_ids in _ROUTE_RULES:
        if pattern.search(value):
            routed.extend(act_ids)
    return tuple(dict.fromkeys(x for x in routed if x in KNOWN_ACTS))


@dataclass(frozen=True, slots=True)
class CorpusResearch:
    provisions: tuple[Provision, ...]
    offered_ids: frozenset[str]
    prompt_block: str

    @property
    def source_urls(self) -> list[str]:
        urls: list[str] = []
        for provision in self.provisions:
            if provision.url not in urls:
                urls.append(provision.url)
        return urls


def open_corpus(path: Path | str | None = None) -> LegalCorpus | None:
    db_path = Path(path or DEFAULT_DB_PATH)
    if not db_path.exists():
        LOGGER.info("KORGAN local corpus not found at %s — using web search", db_path)
        return None
    corpus = LegalCorpus(db_path)
    try:
        if corpus.count() == 0:
            LOGGER.info("KORGAN local corpus is empty — using web search")
            corpus.close()
            return None
    except Exception:
        LOGGER.exception("KORGAN local corpus unreadable — using web search")
        corpus.close()
        return None
    return corpus


def _explicit_article_candidates(active: LegalCorpus, query: str, routed: tuple[str, ...]) -> list[Provision]:
    numbers = list(dict.fromkeys(_ARTICLE_NO_RE.findall(query or "")))
    if not numbers or not routed or len(routed) > 3:
        return []
    found: list[Provision] = []
    for act_id in routed:
        for number in numbers[:4]:
            for provision in active.get_article(act_id, number):
                if provision not in found:
                    found.append(provision)
    return found


def research_from_corpus(
    query: str,
    *,
    corpus: LegalCorpus | None = None,
    act_id: str | None = None,
    limit: int = DEFAULT_LIMIT,
    required_article_ids: Iterable[str] | None = None,
) -> CorpusResearch | None:
    if not local_corpus_enabled():
        return None

    owned = corpus is None
    active = corpus or open_corpus()
    if active is None:
        return None

    try:
        routed = (act_id,) if act_id else route_act_ids(query)
        provisions = active.search_many(query, routed or None, limit=limit)
        exact = _explicit_article_candidates(active, query, routed)
        if exact:
            exact_ids = {x.article_id for x in exact}
            provisions = [*exact, *[item for item in provisions if item.article_id not in exact_ids]]
            provisions = provisions[: max(limit, len(exact))]

        seen = {provision.article_id for provision in provisions}
        for article_id in required_article_ids or ():
            if article_id in seen:
                continue
            provision = active.get(article_id)
            if provision is None:
                continue
            if act_id is not None and provision.act_id != act_id:
                continue
            provisions.append(provision)
            seen.add(article_id)
    finally:
        if owned:
            active.close()

    if not provisions:
        LOGGER.info("KORGAN local corpus returned nothing for %r — using web search", query[:80])
        return None

    LOGGER.info(
        "KORGAN routed corpus query acts=%s provisions=%d",
        ",".join(routed) if routed else "ALL",
        len(provisions),
    )
    offered_ids, prompt_block = build_offer(provisions)
    return CorpusResearch(
        provisions=tuple(provisions),
        offered_ids=frozenset(offered_ids),
        prompt_block=prompt_block,
    )
