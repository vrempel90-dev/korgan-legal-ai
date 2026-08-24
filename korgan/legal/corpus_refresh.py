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
import ssl
import urllib.error
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
ADILET_TRANSFER_ATTEMPTS = 3

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
    request = urllib.request.Request(url, headers={"User-Agent": "KORGAN-corpus-loader/1.5"})
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


def _is_retryable_transfer_error(exc: BaseException) -> bool:
    """Retry only transient transport truncation/reset/timeout failures.

    Certificate verification, redirect validation, source identity and parsing
    errors are deliberately non-retryable here. They must fail closed instead of
    being hidden by a retry loop.
    """
    if isinstance(exc, (http.client.IncompleteRead, TimeoutError, ConnectionResetError)):
        return True
    if isinstance(exc, urllib.error.URLError):
        reason = exc.reason
        return isinstance(reason, (TimeoutError, ConnectionResetError))
    return False


def _is_allowed_pinned_ca_url(url: str) -> bool:
    """Pinned CA downloads may use only the exact fingerprint-bound URL."""
    return url in _PINNED_CA_URLS


def _download_pinned_intermediate(url: str, expected_sha256: str) -> str:
    if not _is_allowed_pinned_ca_url(url):
        raise RuntimeError(f"CA download URL rejected: {url}")

    request = urllib.request.Request(url, headers={"User-Agent": "KORGAN-corpus-loader/1.5"})
    with _open_allowlisted(
        request,
        timeout=30,
        context=ssl.create_default_context(),
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


def _adilet_context_with_pinned_intermediates() -> ssl.SSLContext:
    context = ssl.create_default_context()
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


def _read_adilet_with_retries(
    candidate: str,
    *,
    context: ssl.SSLContext,
    act_id: str,
    timeout: int,
    label: str,
    errors: list[str],
) -> tuple[str, str] | None:
    for attempt in range(1, ADILET_TRANSFER_ATTEMPTS + 1):
        try:
            return _read_https(
                candidate,
                context=context,
                act_id=act_id,
                timeout=timeout,
            )
        except Exception as exc:
            errors.append(
                f"{candidate}{label} attempt={attempt}: {type(exc).__name__}: {exc}"
            )
            if not _is_retryable_transfer_error(exc) or attempt >= ADILET_TRANSFER_ATTEMPTS:
                return None
            LOGGER.warning(
                "KORGAN Adilet transient transfer failure act=%s url=%s attempt=%d/%d error=%s",
                act_id,
                candidate,
                attempt,
                ADILET_TRANSFER_ATTEMPTS,
                f"{type(exc).__name__}: {exc}",
            )
    return None


def fetch_adilet(url: str, timeout: int = 60) -> tuple[str, str]:
    """Fetch one expected Adilet act with verified TLS and bounded transfer retries."""
    act_id = _act_id_for_adilet_url(url)
    if act_id is None:
        raise RuntimeError(f"Adilet URL rejected or not bound to a known act: {url}")

    parsed = urlparse(url)
    alt_host = (
        "www.adilet.zan.kz" if parsed.hostname == "adilet.zan.kz" else "adilet.zan.kz"
    )
    candidates = [url, parsed._replace(netloc=alt_host).geturl()]

    standard = ssl.create_default_context()
    errors: list[str] = []
    for candidate in candidates:
        result = _read_adilet_with_retries(
            candidate,
            context=standard,
            act_id=act_id,
            timeout=timeout,
            label="",
            errors=errors,
        )
        if result is not None:
            return result

    supplemented = _adilet_context_with_pinned_intermediates()
    for candidate in candidates:
        result = _read_adilet_with_retries(
            candidate,
            context=supplemented,
            act_id=act_id,
            timeout=timeout,
            label=" + pinned CA",
            errors=errors,
        )
        if result is not None:
            return result

    raise RuntimeError("Adilet fetch failed with verified TLS: " + " | ".join(errors))


def _read_zan_pdf_with_context(
    act_id: str,
    *,
    context: ssl.SSLContext,
    timeout: int,
) -> tuple[bytes, str]:
    url = zan_pdf_url(act_id)
    allow_url = lambda target: is_allowed_zan_pdf_url(target, act_id=act_id)
    if not allow_url(url):
        raise RuntimeError(f"ZAN URL rejected before request: {url}")

    request = urllib.request.Request(
        url,
        headers={"User-Agent": "KORGAN-corpus-loader/1.5", "Accept": "application/pdf"},
    )
    with _open_allowlisted(
        request,
        timeout=timeout,
        context=context,
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


def _read_zan_pdf(act_id: str, *, timeout: int = 90) -> tuple[bytes, str]:
    """Download one allowlisted ZAN PDF with verified TLS only.

    The platform trust store is tried first. If the server omits the same
    fingerprint-pinned GoGetSSL intermediate already observed on the official
    legal infrastructure, the supplemented context is attempted as a verified
    fallback. Certificate verification is never disabled.
    """
    errors: list[str] = []
    try:
        return _read_zan_pdf_with_context(
            act_id,
            context=ssl.create_default_context(),
            timeout=timeout,
        )
    except Exception as exc:
        errors.append(f"platform trust: {type(exc).__name__}: {exc}")

    try:
        supplemented = _adilet_context_with_pinned_intermediates()
        return _read_zan_pdf_with_context(
            act_id,
            context=supplemented,
            timeout=timeout,
        )
    except Exception as exc:
        errors.append(f"pinned CA: {type(exc).__name__}: {exc}")

    raise RuntimeError("ZAN fetch failed with verified TLS: " + " | ".join(errors))


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


def refresh_corpus_once(path: Path | str = DEFAULT_DB_PATH) -> int:
    """Build a complete verified corpus and atomically swap it into place."""
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_name(target.name + ".refreshing")
    temporary.unlink(missing_ok=True)

    total = 0
    loaded_acts = 0
    source_counts = {"adilet": 0, "zan": 0}
    try:
        with LegalCorpus(temporary) as corpus:
            for act_id in sorted(KNOWN_ACTS):
                loaded, source_kind, source_url = _load_from_official_sources(corpus, act_id)
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

            if loaded_acts != len(KNOWN_ACTS) or total <= 0:
                raise RuntimeError(
                    f"Incomplete corpus refresh: acts={loaded_acts}/{len(KNOWN_ACTS)}, provisions={total}"
                )

        os.replace(temporary, target)
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
