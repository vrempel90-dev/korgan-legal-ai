"""Non-blocking refresh of the official Adilet-backed SQLite corpus.

Refreshing the corpus is deliberately decoupled from deployment.  A broken
network path or an incomplete TLS chain at adilet.zan.kz must never prevent the
Telegram bot from starting.  A complete refresh is built into a temporary
database and atomically replaces the live file only after every supported act
has loaded successfully.

TLS verification is never disabled.  When Adilet omits an intermediate CA that
the runtime cannot build automatically, KORGAN may supplement the trust context
with public DigiCert intermediate certificates.  Those certificates are
downloaded from DigiCert over verified HTTPS and accepted only when their
SHA-256 fingerprints match the values published by DigiCert.
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import os
import ssl
import urllib.error
import urllib.request
from pathlib import Path
from urllib.parse import urlparse

from korgan.legal.corpus import DEFAULT_DB_PATH, KNOWN_ACTS, LegalCorpus
from scripts.load_corpus import ACT_ARTICLE_FILTER, act_url, load_act

LOGGER = logging.getLogger(__name__)

AUTOLOAD_ENV = "KORGAN_CORPUS_AUTOLOAD"
REFRESH_HOURS_ENV = "KORGAN_CORPUS_REFRESH_HOURS"
_TRUTHY = {"1", "true", "yes", "on"}
DEFAULT_REFRESH_HOURS = 24.0

# Exact PEM endpoints were obtained from DigiCert's official CA certificate
# page.  Fingerprints are SHA-256 over the DER certificate.
_PINNED_INTERMEDIATES: tuple[tuple[str, str], ...] = (
    (
        "https://cacerts.digicert.com/GeoTrustEVRSACAG2.crt.pem",
        "2D140F20B8A96E2B4D2F1CC5ACA5E5A1E7DC56A7491E510906960F38D2D21AEF",
    ),
    (
        "https://cacerts.digicert.com/GeoTrustTLSRSACAG1.crt.pem",
        "C06E307F7CFC1D32FA72A4C033C87B90019AF216F0775D64978A2ECA6C8A230E",
    ),
    (
        "https://cacerts.digicert.com/DigiCertEVRSACAG2.crt.pem",
        "9588EF74199E45ACEFCCCFC0C47010E9F2A37A1DD44C61A4E1C6B334DA5AF614",
    ),
)


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
    try:
        parsed = urlparse(url)
    except ValueError:
        return False
    return (
        parsed.scheme == "https"
        and (parsed.hostname or "").lower() in {"adilet.zan.kz", "www.adilet.zan.kz"}
        and parsed.path.startswith("/rus/")
    )


def _read_https(url: str, *, context: ssl.SSLContext, timeout: int = 60) -> tuple[str, str]:
    request = urllib.request.Request(url, headers={"User-Agent": "KORGAN-corpus-loader/1.1"})
    with urllib.request.urlopen(request, timeout=timeout, context=context) as response:  # noqa: S310
        final_url = response.geturl()
        if not _is_allowed_adilet_url(final_url):
            raise RuntimeError(f"Adilet redirect rejected: {final_url}")
        charset = response.headers.get_content_charset() or "utf-8"
        return response.read().decode(charset, errors="replace"), final_url


def _download_pinned_intermediate(url: str, expected_sha256: str) -> str:
    parsed = urlparse(url)
    if parsed.scheme != "https" or parsed.hostname != "cacerts.digicert.com":
        raise RuntimeError(f"CA download host rejected: {url}")

    request = urllib.request.Request(url, headers={"User-Agent": "KORGAN-corpus-loader/1.1"})
    with urllib.request.urlopen(
        request,
        timeout=30,
        context=ssl.create_default_context(),
    ) as response:  # noqa: S310
        final = urlparse(response.geturl())
        if final.scheme != "https" or final.hostname != "cacerts.digicert.com":
            raise RuntimeError(f"CA redirect rejected: {response.geturl()}")
        pem = response.read().decode("ascii")

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
        raise RuntimeError("No pinned DigiCert intermediates could be loaded")
    LOGGER.info("KORGAN TLS context supplemented with %d pinned DigiCert CA(s)", loaded)
    return context


def fetch_adilet(url: str, timeout: int = 60) -> tuple[str, str]:
    """Fetch an official Russian Adilet page with TLS verification always on."""
    if not _is_allowed_adilet_url(url):
        raise RuntimeError(f"Adilet URL rejected: {url}")

    parsed = urlparse(url)
    alt_host = (
        "www.adilet.zan.kz" if parsed.hostname == "adilet.zan.kz" else "adilet.zan.kz"
    )
    candidates = [url, parsed._replace(netloc=alt_host).geturl()]

    standard = ssl.create_default_context()
    errors: list[str] = []
    for candidate in candidates:
        try:
            return _read_https(candidate, context=standard, timeout=timeout)
        except Exception as exc:
            errors.append(f"{candidate}: {type(exc).__name__}: {exc}")

    supplemented = _adilet_context_with_pinned_intermediates()
    for candidate in candidates:
        try:
            return _read_https(candidate, context=supplemented, timeout=timeout)
        except Exception as exc:
            errors.append(f"{candidate} + pinned CA: {type(exc).__name__}: {exc}")

    raise RuntimeError("Adilet fetch failed with verified TLS: " + " | ".join(errors))


def refresh_corpus_once(path: Path | str = DEFAULT_DB_PATH) -> int:
    """Build a complete corpus and atomically swap it into place."""
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_name(target.name + ".refreshing")
    temporary.unlink(missing_ok=True)

    total = 0
    loaded_acts = 0
    try:
        with LegalCorpus(temporary) as corpus:
            for act_id in sorted(KNOWN_ACTS):
                canonical_url = act_url(act_id)
                html, final_url = fetch_adilet(canonical_url)
                loaded = load_act(
                    corpus,
                    act_id,
                    html,
                    url=final_url,
                    articles=ACT_ARTICLE_FILTER.get(act_id),
                )
                total += loaded
                loaded_acts += 1
                LOGGER.info(
                    "KORGAN corpus refresh act=%s provisions=%d source=%s",
                    act_id,
                    loaded,
                    final_url,
                )

            if loaded_acts != len(KNOWN_ACTS) or total <= 0:
                raise RuntimeError(
                    f"Incomplete corpus refresh: acts={loaded_acts}/{len(KNOWN_ACTS)}, provisions={total}"
                )

        os.replace(temporary, target)
        LOGGER.info(
            "KORGAN corpus refresh SUCCESS acts=%d provisions=%d path=%s",
            loaded_acts,
            total,
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
