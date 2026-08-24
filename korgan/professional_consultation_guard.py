"""Source-bound consultation guard for the live KORGAN Telegram agent.

A consultation is not allowed to cite law from model memory. One structured
Responses API call performs official-source research and returns candidate legal
points. A point becomes client-visible only when its claimed URL was actually
opened by the web-search tool and its paraphrase is mechanically compatible with
the provision text. When the act is covered by KORGAN's refreshed local corpus,
the exact act/article identity and quoted provision text are checked again
against that corpus before release.
"""

from __future__ import annotations

import logging
import re
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlparse
from zoneinfo import ZoneInfo

from korgan.legal.corpus import DEFAULT_DB_PATH, KNOWN_ACTS, LegalCorpus
from korgan.provision_check import paraphrase_defects
from korgan.robust_production_legal import _is_adilet_source, _is_court_source
from korgan.verified_openai import _actual_response_urls, _canonical_url

LOGGER = logging.getLogger(__name__)

_CONSULT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "recommended_actions": {"type": "array", "items": {"type": "string"}},
        "verified_points": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "statement": {"type": "string"},
                    "article": {"type": "string"},
                    "provision_text": {"type": "string"},
                    "source_url": {"type": "string"},
                },
                "required": ["statement", "article", "provision_text", "source_url"],
                "additionalProperties": False,
            },
        },
        "unverified_claims": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["recommended_actions", "verified_points", "unverified_claims"],
    "additionalProperties": False,
}

# Precise law belongs only to the source-bound verified block below. These
# patterns deliberately catch article numbers, legal rates/MRP and exact legal
# periods that a free-form action/unverified note could otherwise smuggle into
# the answer without a verified source binding.
_PRECISE_LAW_RE = re.compile(
    r"(?i)(?:"
    r"(?:стать[ьяеию]\w*|ст\.)\s*\d+"
    r"|\b\d+(?:-\d+)?\s*[-–]?\s*бап\b"
    r"|\b\d+(?:[.,]\d+)?\s*%"
    r"|\b\d+(?:[.,]\d+)?\s*(?:мрп|аек)\b"
    r"|(?:срок\w*|мерзім\w*|госпошлин\w*|мемлекеттік\s+баж\w*|подсудност\w*|соттыл\w*)[^\n]{0,40}\b\d+\b"
    r")"
)
_ARTICLE_NO_RE = re.compile(
    r"(?i)(?:(?:стать[ьяеию]\w*|ст\.)\s*(?P<ru>\d+(?:-\d+)?)|(?P<kk>\d+(?:-\d+)?)\s*[-–]?\s*бап\b)"
)


def _today_kz() -> str:
    return datetime.now(ZoneInfo("Asia/Almaty")).date().isoformat()


def _safe_free_text(value: str) -> str:
    """Keep operational prose only when it contains no precise unbound law."""
    text = " ".join(str(value or "").split()).strip()
    if not text or _PRECISE_LAW_RE.search(text):
        return ""
    return text


def _safe_free_lines(values: list[Any] | None) -> list[str]:
    result: list[str] = []
    for raw in values or []:
        line = _safe_free_text(str(raw))
        if line and line not in result:
            result.append(line)
    return result


def _is_russian_adilet(url: str) -> bool:
    try:
        parsed = urlparse(url)
    except ValueError:
        return False
    host = (parsed.hostname or "").lower()
    return (host == "adilet.zan.kz" or host.endswith(".adilet.zan.kz")) and parsed.path.startswith("/rus/docs/")


def _article_no(label: str) -> str:
    match = _ARTICLE_NO_RE.search(label or "")
    if not match:
        return ""
    return str(match.group("ru") or match.group("kk") or "")


def _act_id_from_adilet_url(url: str) -> str:
    """Map a current Adilet code page to one of the acts in the refreshed corpus."""
    path = urlparse(url).path
    for act_id, (adilet_id, _title) in KNOWN_ACTS.items():
        if f"/{adilet_id}" in path:
            return act_id
    return ""


def _normalize_quote(text: str) -> str:
    value = str(text or "").replace("ё", "е").replace("Ё", "Е").lower()
    value = re.sub(r"\s+", " ", value)
    return value.strip(" \t\r\n.;,«»\"")


def _corpus_article_check(article: str, source_url: str, provision_text: str) -> bool | None:
    """Check exact article identity when the refreshed local act is available.

    ``True`` means the article exists in the current local act and the model's
    quoted provision text is a literal normalized excerpt of that article/item.
    ``False`` means the local corpus contradicts the model's article identity or
    quote. ``None`` means the act/database is not available for this secondary
    check; the live source-bound check remains authoritative in that case.
    """
    act_id = _act_id_from_adilet_url(source_url)
    if not act_id:
        return None
    number = _article_no(article)
    if not number:
        return False

    db_path = Path(DEFAULT_DB_PATH)
    if not db_path.exists():
        return None

    corpus = LegalCorpus(db_path)
    try:
        rows = corpus.connection.execute(
            "SELECT body FROM provisions WHERE act_id = ? AND article_no = ? ORDER BY sort_key, item_no",
            (act_id, number),
        ).fetchall()
    except Exception:
        LOGGER.exception("Consultation corpus article check failed closed to live source only")
        return None
    finally:
        corpus.close()

    if not rows:
        return False
    quote = _normalize_quote(provision_text)
    if len(quote) < 40:
        return False
    bodies = [_normalize_quote(str(row["body"])) for row in rows]
    return any(quote in body or body in quote for body in bodies if body)


def _accept_verified_points(
    service: Any,
    payload: dict[str, Any],
    response: Any,
) -> tuple[list[tuple[str, str, str]], list[str], list[str]]:
    """Return (statement, article, source) only for source-bound verified law."""
    actual_urls = [
        url
        for url in _actual_response_urls(response)
        if service._is_current_official_source(url)
    ]
    actual_by_canonical = {
        _canonical_url(url): url
        for url in actual_urls
        if _canonical_url(url)
    }

    accepted: list[tuple[str, str, str]] = []
    rejected: list[str] = []
    used_urls: list[str] = []

    for point in payload.get("verified_points", []) or []:
        statement = " ".join(str(point.get("statement", "")).split()).strip()
        article = " ".join(str(point.get("article", "")).split()).strip()
        provision_text = " ".join(str(point.get("provision_text", "")).split()).strip()
        claimed_url = str(point.get("source_url", "")).strip()
        actual_url = actual_by_canonical.get(_canonical_url(claimed_url))

        if not statement or not article or not actual_url:
            if statement:
                rejected.append("Правовой вывод отброшен: нет связи с реально открытым официальным источником.")
            continue

        if _is_court_source(actual_url):
            if article.lower() != "официальный перечень судов":
                rejected.append("Правовой вывод отброшен: страница суда не подтверждает норму права.")
                continue
        else:
            if not _is_adilet_source(actual_url) or not _is_russian_adilet(actual_url):
                rejected.append("Правовой вывод отброшен: для нормы права нужна русская официальная страница Adilet.")
                continue
            drift = paraphrase_defects(statement, provision_text)
            if drift:
                rejected.append("Правовой вывод отброшен: пересказ не прошёл сверку с текстом нормы.")
                continue
            corpus_check = _corpus_article_check(article, actual_url, provision_text)
            if corpus_check is False:
                rejected.append("Правовой вывод отброшен: номер статьи или текст нормы не совпал с текущим локальным корпусом KORGAN.")
                continue

        item = (statement, article, actual_url)
        if item not in accepted:
            accepted.append(item)
        if actual_url not in used_urls:
            used_urls.append(actual_url)

    return accepted, rejected, used_urls


def _render_consultation(
    payload: dict[str, Any],
    accepted: list[tuple[str, str, str]],
    rejected: list[str],
    *,
    language: str,
) -> str:
    kk = language == "kk"
    actions = _safe_free_lines(payload.get("recommended_actions", []))
    unverified = _safe_free_lines(payload.get("unverified_claims", []))
    for item in rejected:
        safe = _safe_free_text(item)
        if safe and safe not in unverified:
            unverified.append(safe)

    if not accepted:
        if kk:
            base = (
                "Ресми дереккөзден құқықтық қорытындыны жеткілікті деңгейде растай алмадым. "
                "Тексерілмеген бапты немесе мерзімді заң ретінде көрсетпеймін."
            )
            if unverified:
                base += "\n\nҚосымша тексеру қажет:\n" + "\n".join(f"• {x}" for x in unverified[:5])
            return base
        base = (
            "Не удалось достаточно подтвердить правовой вывод по официальному источнику. "
            "Я не буду выдавать непроверенную статью, срок, ставку или подсудность как действующее право."
        )
        if unverified:
            base += "\n\nТребует дополнительной проверки:\n" + "\n".join(f"• {x}" for x in unverified[:5])
        return base

    law_title = "Расталған құқықтық негіз:" if kk else "Подтверждено по действующему праву РК:"
    basis_word = "Негіз" if kk else "Основание"
    law_lines = [f"• {statement} {basis_word}: {article}." for statement, article, _ in accepted[:8]]
    parts: list[str] = [law_title + "\n" + "\n".join(law_lines)]

    if actions:
        parts.append(("Практикалық қадамдар:\n" if kk else "Практические шаги:\n") + "\n".join(f"• {x}" for x in actions[:6]))
    if unverified:
        parts.append(("Қосымша тексеру қажет:\n" if kk else "Требует дополнительной проверки:\n") + "\n".join(f"• {x}" for x in unverified[:5]))

    checked = _today_kz()
    parts.append((f"Құқықтың өзектілігі тексерілген күн: {checked}." if kk else f"Актуальность права проверена: {checked}."))
    return "\n\n".join(parts)


async def _guarded_consult(
    self: Any,
    question: str,
    case_context: str = "",
    language: str = "ru",
) -> tuple[str, list[str]]:
    """One official source-bound call; no free-form legal citation is released."""
    tools = [{
        "type": "web_search",
        "filters": {"allowed_domains": self.settings.legal_domains},
        "search_context_size": "medium",
    }]
    prompt = (
        f"Дата проверки: {_today_kz()}. Ответь на юридический вопрос только по действующему праву Республики Казахстан.\n\n"
        "КРИТИЧЕСКИЙ ФОРМАТ:\n"
        "1. Любой юридический вывод, точная норма, срок, ставка, подсудность или право/обязанность помещается ТОЛЬКО в verified_points.\n"
        "2. Каждый verified_point: один конкретный правовой вывод + точная статья/пункт + существенная ДОСЛОВНАЯ выдержка provision_text без многоточий + URL официальной страницы, которую ты реально открыл.\n"
        "3. Материальное и процессуальное право подтверждай только по русской странице Adilet /rus/docs/. gov.kz/sud.gov.kz допускаются только для официального наименования/структуры суда; тогда article='официальный перечень судов'.\n"
        "4. recommended_actions — только операционные действия с доказательствами/документами и следующие шаги; без новых правовых выводов, номеров статей, законных сроков, ставок, МРП/АЕК или гарантий исхода.\n"
        "5. Если официальный источник не подтверждает вывод, помещай его в unverified_claims без выдуманного номера статьи или ставки.\n"
        "6. Не обещай исход дела. Отделяй факты пользователя от правовых выводов.\n\n"
        f"ВОПРОС:\n{question}\n\n"
        f"КОНТЕКСТ ДЕЛА:\n{case_context[:self.settings.max_case_text_chars] if case_context else 'нет'}"
    )
    payload, response = await self._structured_response(
        model=self.settings.openai_model,
        instructions=(
            "Ты ведущий юрист KORGAN по праву Республики Казахстан. Работай source-bound и fail-closed. "
            "Клиент увидит юридические выводы только из verified_points, поэтому не прячь право в других полях. "
            f"Язык: {'казахский' if language == 'kk' else 'русский'}."
        ),
        content=[{"role": "user", "content": [{"type": "input_text", "text": prompt}]}],
        schema_name="korgan_consult_research",
        schema=_CONSULT_SCHEMA,
        tools=tools,
    )

    accepted, rejected, used_urls = _accept_verified_points(self, payload, response)
    answer = _render_consultation(payload, accepted, rejected, language=language)
    LOGGER.info(
        "KORGAN_CONSULTATION_GATE verified=%d rejected=%d sources=%d",
        len(accepted),
        len(rejected),
        len(used_urls),
    )
    return answer, used_urls


def install_professional_consultation_guard() -> None:
    """Bind guarded consultations to the stable service used by strict_bot."""
    from korgan.stable_legal_release import StableLegalProductionService

    if getattr(StableLegalProductionService, "_korgan_professional_consultation_guard", False):
        return
    StableLegalProductionService.consult = _guarded_consult  # type: ignore[method-assign]
    StableLegalProductionService._korgan_professional_consultation_guard = True
    LOGGER.info("Installed KORGAN professional consultation citation gate")
