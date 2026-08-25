"""Cost/latency optimizations that preserve KORGAN's legal quality gates.

The optimizer deliberately does not change the production model, payment flow,
consultation routing, tariff data, fact locks or filing quality threshold.

It removes avoidable latency/cost in four safe places:
1. publish individually verified corpus acts progressively when the live corpus
   is missing/incomplete, while keeping the existing all-or-nothing atomic
   refresh once a complete corpus exists;
2. use low web-search context only when the prompt already contains a strong
   local official-law RAG set (material code + GPK); fallback remains medium;
3. do not spend a repair-model call on defects that AI cannot legally repair
   without new facts/source verification (missing court/requisites/duty proof);
4. extend the already-verified local court registry to the common TОО-vs-ТОО
   economic-court route so an exact court does not trigger a futile repair.
"""

from __future__ import annotations

import copy
import json
import logging
import re
import sqlite3
from pathlib import Path
from typing import Any, Awaitable, Callable

from korgan.legal.corpus import DEFAULT_DB_PATH, KNOWN_ACTS, LegalCorpus
from korgan.legal_types import ClaimDraft, LegalResearch

LOGGER = logging.getLogger(__name__)
_INSTALLED = False


# ---------------------------------------------------------------------------
# Local corpus: publish only individually source-validated acts during bootstrap
# ---------------------------------------------------------------------------


def _corpus_act_ids(path: Path | str = DEFAULT_DB_PATH) -> set[str]:
    target = Path(path)
    if not target.exists():
        return set()
    try:
        connection = sqlite3.connect(target)
        try:
            rows = connection.execute("SELECT act_id FROM acts").fetchall()
        finally:
            connection.close()
    except (sqlite3.DatabaseError, OSError):
        return set()
    return {str(row[0]) for row in rows}


def _corpus_is_complete(path: Path | str = DEFAULT_DB_PATH) -> bool:
    return _corpus_act_ids(path) >= set(KNOWN_ACTS)


def _merge_staged_act(target: Path, staged: Path, act_id: str) -> int:
    """Atomically copy one fully validated staged act into the live corpus."""
    with LegalCorpus(target) as live:
        connection = live.connection
        connection.execute("ATTACH DATABASE ? AS staged_db", (str(staged),))
        try:
            act_row = connection.execute(
                """
                SELECT adilet_id, title_ru, url, edition_date, loaded_at, lang
                FROM staged_db.acts WHERE act_id = ?
                """,
                (act_id,),
            ).fetchone()
            rows = connection.execute(
                """
                SELECT article_id, act_id, article_no, item_no, heading, body,
                       edition_date, url, sort_key
                FROM staged_db.provisions
                WHERE act_id = ?
                ORDER BY sort_key, article_id
                """,
                (act_id,),
            ).fetchall()
            if act_row is None or not rows:
                raise RuntimeError(f"staged corpus has no complete act {act_id}")

            connection.execute("BEGIN IMMEDIATE")
            connection.execute(
                """
                INSERT INTO acts (act_id, adilet_id, title_ru, url, edition_date, loaded_at, lang)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(act_id) DO UPDATE SET
                    adilet_id = excluded.adilet_id,
                    title_ru = excluded.title_ru,
                    url = excluded.url,
                    edition_date = excluded.edition_date,
                    loaded_at = excluded.loaded_at,
                    lang = excluded.lang
                """,
                (act_id, *tuple(act_row)),
            )
            connection.execute("DELETE FROM provisions WHERE act_id = ?", (act_id,))
            connection.executemany(
                """
                INSERT INTO provisions
                    (article_id, act_id, article_no, item_no, heading, body,
                     edition_date, url, sort_key)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [tuple(row) for row in rows],
            )
            connection.commit()
            return len(rows)
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.execute("DETACH DATABASE staged_db")


def _progressive_refresh_factory(
    original: Callable[[Path | str], int],
    loader: Callable[[LegalCorpus, str], tuple[int, str, str]],
) -> Callable[[Path | str], int]:
    """Keep complete-corpus semantics, but bootstrap missing acts independently."""

    def progressive(path: Path | str = DEFAULT_DB_PATH) -> int:
        target = Path(path)
        if _corpus_is_complete(target):
            return original(path)

        target.parent.mkdir(parents=True, exist_ok=True)
        successful = 0
        failures: list[str] = []

        for act_id in sorted(KNOWN_ACTS):
            staged = target.with_name(f"{target.name}.{act_id}.verified")
            staged.unlink(missing_ok=True)
            try:
                with LegalCorpus(staged) as staged_corpus:
                    loaded, source_kind, source_url = loader(staged_corpus, act_id)
                merged = _merge_staged_act(target, staged, act_id)
                if loaded <= 0 or merged <= 0:
                    raise RuntimeError(f"empty verified act {act_id}")
                successful += 1
                LOGGER.info(
                    "KORGAN corpus progressive act=%s provisions=%d provider=%s source=%s",
                    act_id,
                    merged,
                    source_kind,
                    source_url,
                )
            except Exception as exc:
                failures.append(f"{act_id}: {type(exc).__name__}: {exc}")
                LOGGER.warning(
                    "KORGAN corpus progressive skipped act=%s error=%s; already verified acts remain usable",
                    act_id,
                    f"{type(exc).__name__}: {exc}",
                )
            finally:
                staged.unlink(missing_ok=True)

        act_ids = _corpus_act_ids(target)
        if not act_ids:
            raise RuntimeError(
                "progressive corpus bootstrap produced no verified acts"
                + (f": {' | '.join(failures[:3])}" if failures else "")
            )

        try:
            with LegalCorpus(target) as corpus:
                total = corpus.count()
        except Exception:
            total = 0

        LOGGER.info(
            "KORGAN corpus progressive READY acts=%d/%d provisions=%d successful_this_run=%d failures=%d",
            len(act_ids),
            len(KNOWN_ACTS),
            total,
            successful,
            len(failures),
        )
        return total

    return progressive


# ---------------------------------------------------------------------------
# Research: compact web context only when local official-law coverage is strong
# ---------------------------------------------------------------------------


def _content_text(content: Any) -> str:
    try:
        return json.dumps(content, ensure_ascii=False)
    except (TypeError, ValueError):
        return str(content)


def _strong_rag_prompt(content: Any) -> bool:
    text = _content_text(content)
    if "ЛОКАЛЬНЫЕ RAG-КАНДИДАТЫ ИЗ КОРПУСА ADILET" not in text:
        return False
    # A low-context verification pass is safe only when the local prompt already
    # carries both material law and civil procedure, with several concrete
    # article candidates. Otherwise the original medium search remains intact.
    candidate_count = text.count("article_id:")
    has_material = "GK_RK_OBSHAYA:" in text or "GK_RK_OSOBENNAYA:" in text
    has_procedure = "GPK_RK:" in text
    return candidate_count >= 6 and has_material and has_procedure


def _install_rag_search_context_optimizer() -> None:
    from korgan import fast_professional_litigation as litigation

    cls = litigation.FastProfessionalLitigationService
    current = cls._structured_response
    if getattr(current, "_korgan_cost_speed_search", False):
        return

    async def optimized_structured_response(
        self: Any,
        *,
        model: str,
        instructions: str,
        content: list[dict[str, Any]] | str,
        schema_name: str,
        schema: dict[str, Any],
        tools: list[dict[str, Any]] | None = None,
    ):
        effective_tools = tools
        if (
            schema_name == "korgan_fast_professional_rk_research"
            and tools
            and _strong_rag_prompt(content)
        ):
            effective_tools = copy.deepcopy(tools)
            changed = False
            for tool in effective_tools:
                if tool.get("type") == "web_search" and tool.get("search_context_size") == "medium":
                    tool["search_context_size"] = "low"
                    changed = True
            if changed:
                LOGGER.info(
                    "KORGAN COST_SPEED research web_context=low reason=strong_local_rag; official-source verification preserved"
                )
        return await current(
            self,
            model=model,
            instructions=instructions,
            content=content,
            schema_name=schema_name,
            schema=schema,
            tools=effective_tools,
        )

    optimized_structured_response._korgan_cost_speed_search = True  # type: ignore[attr-defined]
    cls._structured_response = optimized_structured_response


def _install_research_scope_optimizer() -> None:
    """Stop ordinary state-duty arithmetic from consuming web-search budget."""
    from korgan import fast_professional_litigation as litigation

    current = litigation._professional_research_prompt
    if getattr(current, "_korgan_cost_speed_scope", False):
        return

    def scoped_prompt(case_context: str, *, max_chars: int, checked_on: str, **kwargs: Any) -> str:
        prompt = current(
            case_context,
            max_chars=max_chars,
            checked_on=checked_on,
            **kwargs,
        )
        return (
            prompt
            + "\n\nОПТИМИЗАЦИЯ БЕЗ ПОТЕРИ КАЧЕСТВА:\n"
            "21. Обычную арифметику государственной пошлины и стандартную ставку имущественного иска не трать web-search: "
            "финальный deterministic state-duty engine KORGAN считает их из отдельно верифицированной актуальной таблицы ставок. "
            "Через официальный поиск проверяй налоговую норму только когда факты указывают на льготу, отсрочку, освобождение или специальную категорию.\n"
            "22. Не открывай дополнительные общие статьи 'для полноты'. Для конечного иска достаточно точных норм, которые реально поддерживают "
            "квалификацию, заявленные способы защиты и подсудность."
        )

    scoped_prompt._korgan_cost_speed_scope = True  # type: ignore[attr-defined]
    litigation._professional_research_prompt = scoped_prompt


# ---------------------------------------------------------------------------
# Repair: never pay an LLM to invent information that must remain unknown
# ---------------------------------------------------------------------------

_EXTERNAL_ONLY_MARKERS = (
    "не определено конкретное наименование суда",
    "точное наименование суда",
    "не подтверждено наименование суда",
    "не определена госпошлина или подтвержденная льгота",
    "государственная пошлина требует проверки",
    "не установлен статус истца",
    "неизвестен бин",
    "неизвестен иин",
    "не указан бин",
    "не указан иин",
    "не указан адрес",
    "отсутствует адрес",
    "требует уточнения реквизит",
)

_SUBSTANTIVE_MARKERS = (
    "правовое обоснование",
    "материально-прав",
    "неустойк",
    "пеню",
    "пеня",
    "353",
    "прось",
    "прошу суд",
    "требование исчезло",
    "расчет",
    "расчёт",
    "приложен",
    "факт",
    "доказатель",
    "цитат",
)


def _issue_is_external_only(issue: str) -> bool:
    low = str(issue or "").casefold()
    if any(marker in low for marker in _SUBSTANTIVE_MARKERS):
        return False
    if any(marker in low for marker in _EXTERNAL_ONLY_MARKERS):
        return True
    if "остались нерешённые вопросы проверки" in low:
        return any(
            marker in low
            for marker in ("суд", "адрес", "бин", "иин", "реквизит", "госпошлин", "льгот")
        )
    return False


def _all_issues_external_only(issues: list[str]) -> bool:
    return bool(issues) and all(_issue_is_external_only(issue) for issue in issues)


def _install_futile_repair_skip() -> None:
    from korgan import fast_professional_litigation as litigation

    cls = litigation.FastProfessionalLitigationService
    current = cls._quality_repair
    if getattr(current, "_korgan_cost_speed_repair", False):
        return

    async def optimized_quality_repair(
        self: Any,
        *,
        schema_name: str,
        schema: dict[str, Any],
        case_context: str,
        research: LegalResearch,
        current_payload: dict[str, Any],
        issues: list[str],
        language: str,
        document_label: str,
        extra_rules: str,
    ) -> dict[str, Any]:
        if schema_name == "korgan_fast_professional_repair" and _all_issues_external_only(issues):
            LOGGER.info(
                "KORGAN COST_SPEED skipped_nonrepairable_ai_call schema=%s issues=%s",
                schema_name,
                issues[:4],
            )
            # Returning the unchanged schema-shaped payload lets the existing
            # deterministic second preflight mark the document preliminary. It
            # cannot manufacture a court/address/payment proof that is absent.
            return copy.deepcopy(current_payload)
        return await current(
            self,
            schema_name=schema_name,
            schema=schema,
            case_context=case_context,
            research=research,
            current_payload=current_payload,
            issues=issues,
            language=language,
            document_label=document_label,
            extra_rules=extra_rules,
        )

    optimized_quality_repair._korgan_cost_speed_repair = True  # type: ignore[attr-defined]
    cls._quality_repair = optimized_quality_repair


# ---------------------------------------------------------------------------
# Court registry: deterministic common economic venue, same authority as Алматы
# ---------------------------------------------------------------------------

_LEGAL_ENTITY_RE = re.compile(
    r"(?:\bТОО\b|товариществ\w*\s+с\s+ограниченн\w*\s+ответственност\w*|\bАО\b|акционерн\w*\s+обществ\w*)",
    re.IGNORECASE,
)
_ART27_RE = re.compile(r"(?:стать(?:я|и)|ст\.)\s*27\b", re.IGNORECASE)
_ART29_RE = re.compile(r"(?:стать(?:я|и)|ст\.)\s*29\b", re.IGNORECASE)


def _party_is_legal_entity(values: list[str]) -> bool:
    return bool(_LEGAL_ENTITY_RE.search(" ".join(str(value or "") for value in values)))


def _economic_city(case_context: str, draft: ClaimDraft, registry: list[dict[str, str]]) -> str:
    cities = sorted(
        {
            str(item.get("city", "")).strip()
            for item in registry
            if str(item.get("jurisdiction", "")).strip().lower() == "economic"
            and str(item.get("city", "")).strip()
        },
        key=len,
        reverse=True,
    )
    defendant = " ".join(str(value or "") for value in draft.defendant)
    for city in cities:
        if re.search(rf"\b{re.escape(city)}\b", defendant, re.IGNORECASE):
            return city

    context = case_context or ""
    for city in cities:
        # Safe shared-location formulation used by intake/tests, e.g. both TОО
        # are registered in Astana. This is still a user fact, not an inference.
        shared = re.search(
            rf"(?:обе|оба).{{0,80}}(?:компан|сторон|тоо).{{0,120}}(?:зарегистрирован|находят).{{0,80}}\b{re.escape(city)}\b",
            context,
            re.IGNORECASE | re.DOTALL,
        )
        respondent = re.search(
            rf"ответчик.{{0,220}}\b{re.escape(city)}\b",
            context,
            re.IGNORECASE | re.DOTALL,
        )
        if shared or respondent:
            return city
    return ""


def _load_court_registry() -> list[dict[str, str]]:
    from korgan import professional_claim_finalizer as finalizer

    try:
        payload = json.loads(finalizer._DATA_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    return [dict(item) for item in payload.get("entries", []) if isinstance(item, dict)]


def _economic_court_candidate(
    case_context: str,
    research: LegalResearch,
    draft: ClaimDraft,
) -> dict[str, str] | None:
    if not (_party_is_legal_entity(draft.claimant) and _party_is_legal_entity(draft.defendant)):
        return None
    verified = "\n".join(str(item) for item in research.verified_claims)
    if not (_ART27_RE.search(verified) and _ART29_RE.search(verified)):
        return None
    registry = _load_court_registry()
    city = _economic_city(case_context, draft, registry)
    if not city:
        return None
    for item in registry:
        if (
            str(item.get("city", "")).casefold() == city.casefold()
            and str(item.get("jurisdiction", "")).casefold() == "economic"
        ):
            return item
    return None


def _install_economic_court_registry() -> None:
    from korgan import professional_claim_finalizer as finalizer

    current = finalizer._resolve_court
    if getattr(current, "_korgan_cost_speed_court", False):
        return

    def resolve_with_economic_registry(
        case_context: str,
        research: LegalResearch,
        draft: ClaimDraft,
    ) -> None:
        current(case_context, research, draft)
        # Preserve any already resolved concrete court.
        existing = str(draft.court or "").strip()
        if existing and "ТРЕБУЕТ" not in existing.upper() and "УТОЧН" not in existing.upper():
            # If it is already a registry court there is nothing to do. A model
            # guess is still handled by existing downstream verification gates.
            registry_names = {str(item.get("court", "")).strip() for item in _load_court_registry()}
            if existing in registry_names:
                return

        candidate = _economic_court_candidate(case_context, research, draft)
        if candidate is None:
            return
        court = str(candidate.get("court", "")).strip()
        if not court:
            return
        draft.court = court
        note = f"VERIFIED_COURT: {court}"
        if note not in research.notes:
            research.notes.append(note)
        source = str(candidate.get("source_url", "")).strip()
        if source and source not in research.source_urls:
            research.source_urls.append(source)
        draft.verification_notes = [
            value
            for value in draft.verification_notes
            if not (
                "суд" in str(value).casefold()
                and any(token in str(value).casefold() for token in ("уточн", "не подтверж", "наименован"))
            )
        ]
        LOGGER.info("KORGAN COST_SPEED court_registry resolved=%s city=%s", court, candidate.get("city", ""))

    resolve_with_economic_registry._korgan_cost_speed_court = True  # type: ignore[attr-defined]
    finalizer._resolve_court = resolve_with_economic_registry


# ---------------------------------------------------------------------------
# Installer
# ---------------------------------------------------------------------------


def install_production_cost_speed_optimizer() -> None:
    global _INSTALLED
    if _INSTALLED:
        return

    from korgan.legal import corpus_refresh

    current_refresh = corpus_refresh.refresh_corpus_once
    if not getattr(current_refresh, "_korgan_progressive_bootstrap", False):
        progressive = _progressive_refresh_factory(
            current_refresh,
            corpus_refresh._load_from_official_sources,
        )
        progressive._korgan_progressive_bootstrap = True  # type: ignore[attr-defined]
        corpus_refresh.refresh_corpus_once = progressive

    _install_research_scope_optimizer()
    _install_rag_search_context_optimizer()
    _install_futile_repair_skip()
    _install_economic_court_registry()

    _INSTALLED = True
    LOGGER.info(
        "Installed KORGAN production cost/speed optimizer: progressive verified corpus + RAG-low web + futile-repair skip + economic court registry; models/quality gates unchanged"
    )
