"""Non-blocking refresh of the official Kazakhstan legal SQLite corpus.

Adilet remains the primary source. If Railway cannot reach Adilet with verified
TLS, KORGAN falls back per act to the Ministry of Justice ZAN.GOV.KZ electronic
reference bank. TLS verification is never disabled for either source.

A complete refresh is always built in a temporary database. The live corpus is
atomically replaced only after every supported act has passed source, identity,
language and article validation. If both official sources fail for any act, the
existing corpus remains untouched.
"""

from __future__ import annotations

import asyncio
import hashlib
import http.client
import logging
import os
import re
import socket
import ssl
import time
import urllib.request
from collections.abc import Callable
from datetime import datetime
from io import BytesIO
from pathlib import Path
from urllib.parse import urljoin, urlparse

from pypdf import PdfReader

from korgan.legal.corpus import DEFAULT_DB_PATH, KNOWN_ACTS, LegalCorpus
from korgan.legal.official_sources import (
    ZAN_IDENTITY_MARKERS,
    is_allowed_adilet_url,
    is_allowed_zan_pdf_url,
    zan_pdf_url,
    zan_pdf_url_details,
)
from scripts.load_corpus import ACT_ARTICLE_FILTER, act_url, load_act, load_act_text

LOGGER = logging.getLogger(__name__)

AUTOLOAD_ENV = "KORGAN_CORPUS_AUTOLOAD"
REFRESH_HOURS_ENV = "KORGAN_CORPUS_REFRESH_HOURS"
_TRUTHY = {"1", "true", "yes", "on"}
DEFAULT_REFRESH_HOURS = 24.0
MAX_ZAN_PDF_BYTES = 80 * 1024 * 1024
MIN_ZAN_PDF_BYTES = 1024

# GoGetSSL's official intermediate/root page publishes this exact PEM/TXT file.
# SHA-256 is over the DER certificate and is also present in public CA metadata.
_PINNED_INTERMEDIATES: tuple[tuple[str, str], ...] = (
    (
        "https://gogetssl-cdn.s3.eu-central-1.amazonaws.com/wiki/GoGetSSL_G2_TLS_RSA4096_SHA256_2022_CA-1.txt",
        "8AADF068A1B7C04B3E346F7C97FD9619FFF14ECC6C82C2F15594B9732F3F3E72",
    ),
)
_PINNED_CA_URLS = frozenset(url for url, _ in _PINNED_INTERMEDIATES)
_EDITION_RE = re.compile(r"Дата\s+редакции\s+(\d{2}\.\d{2}\.\d{4})", re.IGNORECASE)

# Обрыв соединения на середине ответа. Не ошибка запроса и не отказ сервера —
# adilet регулярно закрывает соединение раньше, чем дослал документ:
#
#     act=ZPP_RK ... + pinned CA: IncompleteRead: IncompleteRead(44742 bytes read)
#
# Остальные пять актов в том же прогоне и через тот же контекст TLS грузятся,
# поэтому повторная попытка — правильный ответ, а вот принять недочитанный
# текст закона нельзя ни при каких условиях: это молча превратит половину
# акта в «весь акт».
_TRANSIENT_READ_ERRORS: tuple[type[BaseException], ...] = (
    http.client.IncompleteRead,
    http.client.RemoteDisconnected,
    ConnectionResetError,
    socket.timeout,
    TimeoutError,
)
_FETCH_ATTEMPTS = 3
_RETRY_PAUSE_SECONDS = 2.0

# Насколько акт может «похудеть» за одну сверку. Отмена отдельных статей — это
# единицы процентов; потеря более трети статей означает не поправку, а
# недочитанный или подменённый документ.
_MIN_ACT_RETENTION = 0.65


class _AllowlistedRedirectHandler(urllib.request.HTTPRedirectHandler):
    """Reject every redirect target before urllib can contact it."""

    def __init__(self, allow_url: Callable[[str], bool]) -> None:
        super().__init__()
        self._allow_url = allow_url

    def redirect_request(self, req, fp, code, msg, headers, newurl):  # type: ignore[no-untyped-def]
        absolute = urljoin(req.full_url, newurl)
        if not self._allow_url(absolute):
            raise RuntimeError(f"redirect target rejected before request: {absolute}")
        return super().redirect_request(req, fp, code, msg, headers, absolute)


def _open_allowlisted(
    request: urllib.request.Request,
    *,
    context: ssl.SSLContext,
    timeout: int,
    allow_url: Callable[[str], bool],
):
    """Open one HTTPS request with source-specific pre-request redirect validation."""
    if not allow_url(request.full_url):
        raise RuntimeError(f"URL rejected before request: {request.full_url}")
    opener = urllib.request.build_opener(
        urllib.request.HTTPSHandler(context=context),
        _AllowlistedRedirectHandler(allow_url),
    )
    return opener.open(request, timeout=timeout)  # noqa: S310 - strict allowlist handler


def autoload_enabled() -> bool:
    return os.getenv(AUTOLOAD_ENV, "").strip().lower() in _TRUTHY


def refresh_hours() -> float:
    raw = os.getenv(REFRESH_HOURS_ENV, str(DEFAULT_REFRESH_HOURS)).strip()
    try:
        value = float(raw)
    except ValueError:
        return DEFAULT_REFRESH_HOURS
    return max(1.0, min(value, 24.0 * 30.0))


def _is_allowed_adilet_url(url: str) -> bool:
    """Compatibility wrapper used by existing tests and callers."""
    return is_allowed_adilet_url(url)


def _act_id_for_adilet_url(url: str) -> str | None:
    for act_id in KNOWN_ACTS:
        if is_allowed_adilet_url(url, act_id=act_id):
            return act_id
    return None


def _read_https(
    url: str,
    *,
    context: ssl.SSLContext,
    act_id: str,
    timeout: int = 60,
) -> tuple[str, str]:
    allow_url = lambda target: is_allowed_adilet_url(target, act_id=act_id)
    request = urllib.request.Request(url, headers={"User-Agent": "KORGAN-corpus-loader/1.4"})
    with _open_allowlisted(
        request,
        context=context,
        timeout=timeout,
        allow_url=allow_url,
    ) as response:
        final_url = response.geturl()
        if not allow_url(final_url):
            raise RuntimeError(f"Adilet redirect rejected: {final_url}")
        charset = response.headers.get_content_charset() or "utf-8"
        return response.read().decode(charset, errors="replace"), final_url


def _is_allowed_pinned_ca_url(url: str) -> bool:
    """Pinned CA downloads may use only the exact fingerprint-bound URL."""
    return url in _PINNED_CA_URLS


def _download_pinned_intermediate(url: str, expected_sha256: str) -> str:
    if not _is_allowed_pinned_ca_url(url):
        raise RuntimeError(f"CA download URL rejected: {url}")

    request = urllib.request.Request(url, headers={"User-Agent": "KORGAN-corpus-loader/1.4"})
    with _open_allowlisted(
        request,
        timeout=30,
        context=_trusted_context(),
        allow_url=_is_allowed_pinned_ca_url,
    ) as response:
        final_url = response.geturl()
        if not _is_allowed_pinned_ca_url(final_url):
            raise RuntimeError(f"CA redirect rejected: {final_url}")
        pem = response.read().decode("ascii").strip()

    if "-----BEGIN CERTIFICATE-----" not in pem or "-----END CERTIFICATE-----" not in pem:
        raise RuntimeError(f"CA payload is not PEM: {url}")
    der = ssl.PEM_cert_to_DER_cert(pem)
    actual = hashlib.sha256(der).hexdigest().upper()
    if actual != expected_sha256.upper():
        raise RuntimeError(
            f"CA fingerprint mismatch for {url}: expected {expected_sha256}, got {actual}"
        )
    return pem


def _trusted_context() -> ssl.SSLContext:
    """Контекст TLS с максимально полным набором корневых сертификатов.

    Системное хранилище образа Railway проверяет api.telegram.org и
    api.openai.com, но цепочку adilet.zan.kz — не всегда: в логах это
    выглядит как

        CERTIFICATE_VERIFY_FAILED: unable to get local issuer certificate

    и заканчивается тем, что корпус норм не грузится, а без корпуса гейт
    цитат не выпускает ни одного документа. Набор certifi обновляется
    вместе с пакетом и содержит корни, которых в образе может не быть.

    Проверка TLS при этом НЕ ослабляется: certifi лишь добавляет корни,
    verify_mode и проверка имени хоста остаются по умолчанию. Если certifi
    недоступен, поведение прежнее — системное хранилище, поэтому явной
    зависимости в requirements не требуется (certifi приходит с openai).
    """
    try:
        import certifi

        return ssl.create_default_context(cafile=certifi.where())
    except Exception:
        LOGGER.warning("KORGAN certifi недоступен, используется системное хранилище сертификатов")
        return ssl.create_default_context()


def _adilet_context_with_pinned_intermediates() -> ssl.SSLContext:
    context = _trusted_context()
    loaded = 0
    for url, fingerprint in _PINNED_INTERMEDIATES:
        try:
            pem = _download_pinned_intermediate(url, fingerprint)
            context.load_verify_locations(cadata=pem)
            loaded += 1
        except Exception as exc:
            LOGGER.warning("KORGAN CA supplement skipped url=%s error=%s", url, exc)
    if loaded == 0:
        raise RuntimeError("No pinned Adilet intermediate could be loaded")
    LOGGER.info("KORGAN TLS context supplemented with %d fingerprint-pinned CA(s)", loaded)
    return context


def _read_with_retry(
    url: str,
    *,
    context: ssl.SSLContext,
    act_id: str,
    timeout: int,
    label: str,
) -> tuple[str, str]:
    """Прочитать акт, переспрашивая при обрыве соединения.

    Повтор делается ТОЛЬКО на транзиентных обрывах. Отказ TLS, отклонённый
    редирект и неверный адрес — состояния устойчивые, их повтор не лечит, и
    попытка тратится впустую. Усечённый ответ никогда не принимается как
    текст акта: если все попытки оборвались, акт считается незагруженным и
    переносится из живого корпуса (см. _carry_over_act).
    """
    last: BaseException | None = None
    for attempt in range(1, _FETCH_ATTEMPTS + 1):
        try:
            return _read_https(url, context=context, act_id=act_id, timeout=timeout)
        except _TRANSIENT_READ_ERRORS as exc:
            last = exc
            LOGGER.warning(
                "KORGAN Adilet оборвал ответ act=%s попытка=%d/%d %s: %s: %s",
                act_id,
                attempt,
                _FETCH_ATTEMPTS,
                label,
                type(exc).__name__,
                exc,
            )
            if attempt < _FETCH_ATTEMPTS:
                time.sleep(_RETRY_PAUSE_SECONDS * attempt)
    raise RuntimeError(
        f"обрыв ответа {_FETCH_ATTEMPTS} раз подряд: {type(last).__name__}: {last}"
    )


def fetch_adilet(url: str, timeout: int = 60) -> tuple[str, str]:
    """Fetch one expected Adilet act with verified TLS and bound redirects."""
    act_id = _act_id_for_adilet_url(url)
    if act_id is None:
        raise RuntimeError(f"Adilet URL rejected or not bound to a known act: {url}")

    parsed = urlparse(url)
    alt_host = (
        "www.adilet.zan.kz" if parsed.hostname == "adilet.zan.kz" else "adilet.zan.kz"
    )
    candidates = [url, parsed._replace(netloc=alt_host).geturl()]

    standard = _trusted_context()
    errors: list[str] = []
    for candidate in candidates:
        try:
            return _read_with_retry(
                candidate,
                context=standard,
                act_id=act_id,
                timeout=timeout,
                label=candidate,
            )
        except Exception as exc:
            errors.append(f"{candidate}: {type(exc).__name__}: {exc}")

    supplemented = _adilet_context_with_pinned_intermediates()
    for candidate in candidates:
        try:
            return _read_with_retry(
                candidate,
                context=supplemented,
                act_id=act_id,
                timeout=timeout,
                label=f"{candidate} + pinned CA",
            )
        except Exception as exc:
            errors.append(f"{candidate} + pinned CA: {type(exc).__name__}: {exc}")

    raise RuntimeError("Adilet fetch failed with verified TLS: " + " | ".join(errors))


def _read_zan_pdf(act_id: str, *, timeout: int = 90) -> tuple[bytes, str]:
    """Download one allowlisted ZAN PDF using the platform trust store."""
    url = zan_pdf_url(act_id)
    allow_url = lambda target: is_allowed_zan_pdf_url(target, act_id=act_id)
    if not allow_url(url):
        raise RuntimeError(f"ZAN URL rejected before request: {url}")

    request = urllib.request.Request(
        url,
        headers={"User-Agent": "KORGAN-corpus-loader/1.4", "Accept": "application/pdf"},
    )
    with _open_allowlisted(
        request,
        timeout=timeout,
        context=_trusted_context(),
        allow_url=allow_url,
    ) as response:
        final_url = response.geturl()
        if not allow_url(final_url):
            raise RuntimeError(f"ZAN redirect rejected: {final_url}")
        content_type = (response.headers.get_content_type() or "").lower()
        if content_type not in {"application/pdf", "application/octet-stream"}:
            raise RuntimeError(f"ZAN response is not PDF content-type: {content_type or 'missing'}")
        declared = response.headers.get("Content-Length")
        if declared:
            try:
                if int(declared) > MAX_ZAN_PDF_BYTES:
                    raise RuntimeError(f"ZAN PDF exceeds size limit: {declared}")
            except ValueError:
                raise RuntimeError(f"ZAN invalid Content-Length: {declared}") from None
        payload = response.read(MAX_ZAN_PDF_BYTES + 1)

    if len(payload) > MAX_ZAN_PDF_BYTES:
        raise RuntimeError("ZAN PDF exceeds size limit")
    if len(payload) < MIN_ZAN_PDF_BYTES:
        raise RuntimeError(f"ZAN PDF is unexpectedly small: {len(payload)} bytes")
    if not payload.startswith(b"%PDF-"):
        raise RuntimeError("ZAN payload does not have PDF magic")
    return payload, final_url


def _extract_zan_pdf_text(payload: bytes) -> str:
    try:
        reader = PdfReader(BytesIO(payload), strict=True)
        if reader.is_encrypted:
            raise RuntimeError("ZAN PDF is encrypted")
        chunks = [page.extract_text() or "" for page in reader.pages]
    except RuntimeError:
        raise
    except Exception as exc:
        raise RuntimeError(f"ZAN PDF parse failed: {type(exc).__name__}: {exc}") from exc
    text = "\n".join(chunks).strip()
    if len(text) < 1000:
        raise RuntimeError(f"ZAN PDF extracted text is unexpectedly short: {len(text)} chars")
    return text


def _identity_normalized(value: str) -> str:
    text = (value or "").replace("ё", "е").replace("Ё", "Е").lower()
    text = text.replace("–", "-").replace("—", "-").replace("‑", "-").replace("−", "-")
    return re.sub(r"\s+", " ", text).strip()


def _zan_revision_date(text: str) -> tuple[str, str]:
    match = _EDITION_RE.search(text or "")
    if match is None:
        raise RuntimeError("ZAN PDF does not contain 'Дата редакции'")
    raw = match.group(1)
    try:
        iso = datetime.strptime(raw, "%d.%m.%Y").date().isoformat()
    except ValueError as exc:
        raise RuntimeError(f"ZAN invalid revision date: {raw}") from exc
    return raw, iso


def _validate_zan_identity(act_id: str, text: str, final_url: str) -> str:
    """Bind a fixed ZAN document ID, document body and revision URL together."""
    if not is_allowed_zan_pdf_url(final_url, act_id=act_id):
        raise RuntimeError(f"ZAN final URL identity mismatch for {act_id}: {final_url}")
    normalized = _identity_normalized(text)
    missing = [
        marker
        for marker in ZAN_IDENTITY_MARKERS[act_id]
        if _identity_normalized(marker) not in normalized
    ]
    if missing:
        raise RuntimeError(f"ZAN document identity mismatch for {act_id}: missing {missing}")

    raw_revision, iso_revision = _zan_revision_date(text)
    details = zan_pdf_url_details(final_url)
    if details is None:
        raise RuntimeError(f"ZAN final URL rejected after fetch: {final_url}")
    _, url_revision = details
    if url_revision and url_revision != raw_revision:
        raise RuntimeError(
            f"ZAN revision mismatch for {act_id}: url={url_revision}, document={raw_revision}"
        )
    return iso_revision


def fetch_zan(act_id: str, timeout: int = 90) -> tuple[str, str, str]:
    """Fetch and validate the official current ZAN PDF for one known act."""
    if act_id not in KNOWN_ACTS:
        raise RuntimeError(f"Unknown act for ZAN fallback: {act_id}")
    payload, final_url = _read_zan_pdf(act_id, timeout=timeout)
    text = _extract_zan_pdf_text(payload)
    revision_date = _validate_zan_identity(act_id, text, final_url)
    return text, final_url, revision_date


def _load_from_official_sources(corpus: LegalCorpus, act_id: str) -> tuple[int, str, str]:
    """Load one act from Adilet first, then ZAN only if the primary path fails."""
    canonical_url = act_url(act_id)
    try:
        html, final_url = fetch_adilet(canonical_url)
        loaded = load_act(
            corpus,
            act_id,
            html,
            url=final_url,
            articles=ACT_ARTICLE_FILTER.get(act_id),
        )
        return loaded, "adilet", final_url
    except Exception as adilet_exc:
        LOGGER.warning(
            "KORGAN Adilet primary failed act=%s error=%s; trying official ZAN fallback",
            act_id,
            f"{type(adilet_exc).__name__}: {adilet_exc}",
        )

    try:
        text, zan_url, source_revision = fetch_zan(act_id)
        loaded = load_act_text(
            corpus,
            act_id,
            text,
            source_url=zan_url,
            # Filing-facing links remain the stable canonical act URL. The act
            # row records ZAN as the actual refresh provenance.
            citation_url=canonical_url,
            edition_date=source_revision,
            articles=ACT_ARTICLE_FILTER.get(act_id),
        )
        LOGGER.info(
            "KORGAN ZAN fallback verified act=%s source_revision=%s source=%s",
            act_id,
            source_revision,
            zan_url,
        )
        return loaded, "zan", zan_url
    except Exception as zan_exc:
        raise RuntimeError(
            f"Both official sources failed for {act_id}; ZAN error: {type(zan_exc).__name__}: {zan_exc}"
        ) from zan_exc


def _act_provision_count(target: Path, act_id: str) -> int:
    """Сколько норм этого акта лежит в живом корпусе."""
    if not target.exists():
        return 0
    try:
        with LegalCorpus(target) as corpus:
            return corpus.count(act_id)
    except Exception:
        return 0


def _carry_over_act(corpus: LegalCorpus, act_id: str, source: Path) -> int:
    """Перенести акт из живого корпуса в собираемый.

    Зачем
    -----
    Проверка «частичная сборка беднее существующей» считает нормы ЦЕЛИКОМ, по
    всему корпусу. Этого мало. Если ЗПП РК не загрузился (−186 норм), а ГК РК
    в новой редакции прибавил 200, сумма растёт, подмена проходит — и закон о
    защите прав потребителей молча исчезает из корпуса. Сегодня она сработала
    только потому, что арифметика случайно сошлась: 5441 против 5627.

    Последствие исчезновения не абстрактное: гейт цитат отвечает «нашлась /
    не нашлась», и без акта ни одна ссылка на него не подтверждается. Каждый
    потребительский иск после этого выходит «предварительным проектом» — при
    том, что написан он правильно.

    Что делает
    ----------
    Недоступный акт не пропускается, а переносится из живого корпуса как есть,
    вместе с прежними url и edition_date. Ссылка остаётся подтверждённой, а
    дата редакции в документе честно показывает, на какую версию он опирается.
    Это строго лучше двух других вариантов: потерять акт или принять
    недочитанный текст.
    """
    if not source.exists():
        return 0
    try:
        with LegalCorpus(source) as live:
            act_row = live.connection.execute(
                "SELECT act_id, adilet_id, title_ru, url, edition_date, loaded_at "
                "FROM acts WHERE act_id = ?",
                (act_id,),
            ).fetchone()
            if act_row is None:
                return 0
            rows = live.connection.execute(
                "SELECT article_no, item_no, heading, body, edition_date, url, sort_key "
                "FROM provisions WHERE act_id = ? ORDER BY sort_key",
                (act_id,),
            ).fetchall()
    except Exception:
        LOGGER.warning("KORGAN не удалось перенести акт %s из живого корпуса", act_id)
        return 0

    if not rows:
        return 0

    corpus.upsert_act(
        act_id=act_row["act_id"],
        adilet_id=act_row["adilet_id"],
        title_ru=act_row["title_ru"],
        url=act_row["url"],
        edition_date=act_row["edition_date"],
        loaded_at=act_row["loaded_at"],
    )
    for row in rows:
        corpus.upsert_provision(
            act_id=act_id,
            article_no=row["article_no"],
            item_no=row["item_no"],
            heading=row["heading"],
            body=row["body"],
            edition_date=row["edition_date"],
            url=row["url"],
            sort_key=row["sort_key"],
        )
    return len(rows)


def _existing_provision_count(target: Path) -> int:
    """Сколько норм в уже лежащем корпусе. Ошибка чтения = считаем пустым."""
    if not target.exists():
        return 0
    try:
        with LegalCorpus(target) as corpus:
            return corpus.count()
    except Exception:
        LOGGER.warning("KORGAN не удалось прочитать существующий корпус %s", target)
        return 0


def refresh_corpus_once(path: Path | str = DEFAULT_DB_PATH) -> int:
    """Собрать корпус и подменить им живой.

    Раньше подмена происходила только если загрузились ВСЕ акты, иначе
    временная база удалялась. На свежем контейнере это означало отсутствие
    корпуса целиком из-за одного недоступного акта — а adilet отдаёт
    таймауты регулярно. Без корпуса гейт цитат не подтверждает ни одной
    статьи и не выпускает ни одного документа.

    Теперь частичная загрузка сохраняется. Это безопасно: каждая норма несёт
    свой акт, источник и дату редакции, а проверка ссылки отвечает только
    «нашлась / не нашлась». Недостающий акт означает, что его статьи
    остаются неподтверждёнными — ровно то же, что при пустом корпусе, но
    только для этого акта, а не для всех.

    Недостающий акт при этом не теряется: если он уже есть в живом корпусе,
    он переносится в новую сборку как есть (см. _carry_over_act). Иначе
    достаточно одного удачного дня у соседнего акта, чтобы сумма выросла,
    подмена прошла и недоступный акт исчез навсегда.

    Три границы сохранены:
    * ни один акт не загрузился заново — живой корпус не трогаем;
    * частичная сборка беднее уже лежащей — тоже не трогаем, чтобы
      неудачная сверка не обменяла полный корпус на урезанный;
    * отдельный акт похудел больше чем на треть — считаем это усечением
      ответа, а не поправкой, и берём его прежнюю редакцию.
    """
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_name(target.name + ".refreshing")
    temporary.unlink(missing_ok=True)

    total = 0
    loaded_acts = 0
    failures: list[str] = []
    carried: list[str] = []
    source_counts = {"adilet": 0, "zan": 0}
    try:
        with LegalCorpus(temporary) as corpus:
            for act_id in sorted(KNOWN_ACTS):
                live_count = _act_provision_count(target, act_id)
                try:
                    loaded, source_kind, source_url = _load_from_official_sources(corpus, act_id)
                    # Акт, внезапно похудевший на треть, — это не поправка, а
                    # недочитанный документ. Такой «успех» опаснее отказа:
                    # ссылки на выпавшие статьи перестанут подтверждаться, а в
                    # логах будет стоять SUCCESS.
                    if live_count and loaded < live_count * _MIN_ACT_RETENTION:
                        raise RuntimeError(
                            f"акт усечён: {loaded} норм против {live_count} в живом корпусе"
                        )
                except Exception as exc:
                    failures.append(act_id)
                    corpus.clear_act(act_id)
                    rescued = _carry_over_act(corpus, act_id, target)
                    if rescued:
                        total += rescued
                        carried.append(act_id)
                        LOGGER.warning(
                            "KORGAN corpus refresh act=%s источник недоступен (%s: %s); "
                            "перенесён из живого корпуса provisions=%d",
                            act_id,
                            type(exc).__name__,
                            exc,
                            rescued,
                        )
                    else:
                        LOGGER.warning(
                            "KORGAN corpus refresh act=%s НЕ загружен: %s: %s; остальные акты продолжаем",
                            act_id,
                            type(exc).__name__,
                            exc,
                        )
                    continue
                total += loaded
                loaded_acts += 1
                source_counts[source_kind] += 1
                LOGGER.info(
                    "KORGAN corpus refresh act=%s provisions=%d provider=%s source=%s",
                    act_id,
                    loaded,
                    source_kind,
                    source_url,
                )

            if loaded_acts <= 0:
                raise RuntimeError(
                    f"Ни один акт не загружен: acts=0/{len(KNOWN_ACTS)}; живой корпус сохранён"
                )

            existing = _existing_provision_count(target)
            if failures and existing > total:
                raise RuntimeError(
                    f"Частичная сборка ({total} норм, актов {loaded_acts}/{len(KNOWN_ACTS)}) "
                    f"беднее существующего корпуса ({existing} норм); живой корпус сохранён"
                )

        os.replace(temporary, target)
        if failures:
            lost = [act_id for act_id in failures if act_id not in carried]
            LOGGER.warning(
                "KORGAN corpus refresh PARTIAL acts=%d/%d provisions=%d "
                "перенесены из живого корпуса=%s потеряны=%s path=%s",
                loaded_acts,
                len(KNOWN_ACTS),
                total,
                ",".join(carried) or "нет",
                ",".join(lost) or "нет",
                target,
            )
        else:
            LOGGER.info(
                "KORGAN corpus refresh SUCCESS acts=%d provisions=%d adilet=%d zan=%d path=%s",
                loaded_acts,
                total,
                source_counts["adilet"],
                source_counts["zan"],
                target,
            )
        return total
    except Exception:
        temporary.unlink(missing_ok=True)
        raise


async def corpus_refresh_loop() -> None:
    """Refresh immediately, then periodically; never propagate refresh failures."""
    while True:
        try:
            await asyncio.to_thread(refresh_corpus_once)
        except asyncio.CancelledError:
            raise
        except Exception:
            LOGGER.exception(
                "KORGAN corpus refresh failed safely — existing corpus/web search remains active"
            )
        await asyncio.sleep(refresh_hours() * 3600)


def start_corpus_refresh_task() -> asyncio.Task[None] | None:
    if not autoload_enabled():
        LOGGER.info("KORGAN corpus autoload disabled")
        return None
    LOGGER.info("KORGAN corpus autoload enabled refresh_hours=%.1f", refresh_hours())
    return asyncio.create_task(corpus_refresh_loop(), name="korgan-corpus-refresh")
