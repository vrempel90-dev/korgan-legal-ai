"""Non-blocking refresh of the official Adilet-backed SQLite corpus.

The six filing-critical acts are atomic CORE: a new database is promoted only
when all of them load.  The broader Kazakhstan catalogue is OPTIONAL and is
loaded best-effort into the same temporary database.  A temporary problem with
one peripheral act therefore cannot destroy a healthy production corpus.

TLS verification is never disabled.  Adilet currently omits its intermediate
certificate in Railway, so KORGAN supplements the system trust store with one
fingerprint-pinned GoGetSSL intermediate and still performs normal certificate
validation.
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import os
import ssl
import urllib.request
from pathlib import Path
from urllib.parse import urlparse

from korgan.legal.corpus import DEFAULT_DB_PATH, LegalCorpus
from korgan.legal.rk_catalog import CORE_ACT_IDS, OPTIONAL_ACT_IDS
from scripts.load_corpus import ACT_ARTICLE_FILTER, act_url, load_act

LOGGER = logging.getLogger(__name__)

AUTOLOAD_ENV = "KORGAN_CORPUS_AUTOLOAD"
REFRESH_HOURS_ENV = "KORGAN_CORPUS_REFRESH_HOURS"
_TRUTHY = {"1", "true", "yes", "on"}
DEFAULT_REFRESH_HOURS = 24.0

_PINNED_INTERMEDIATES: tuple[tuple[str, str], ...] = (
    (
        "https://gogetssl-cdn.s3.eu-central-1.amazonaws.com/wiki/GoGetSSL_G2_TLS_RSA4096_SHA256_2022_CA-1.txt",
        "8AADF068A1B7C04B3E346F7C97FD9619FFF14ECC6C82C2F15594B9732F3F3E72",
    ),
)
_PINNED_CA_HOSTS = {"gogetssl-cdn.s3.eu-central-1.amazonaws.com"}


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
    request = urllib.request.Request(url, headers={"User-Agent": "KORGAN-corpus-loader/1.3"})
    with urllib.request.urlopen(request, timeout=timeout, context=context) as response:  # noqa: S310
        final_url = response.geturl()
        if not _is_allowed_adilet_url(final_url):
            raise RuntimeError(f"Adilet redirect rejected: {final_url}")
        charset = response.headers.get_content_charset() or "utf-8"
        return response.read().decode(charset, errors="replace"), final_url


def _download_pinned_intermediate(url: str, expected_sha256: str) -> str:
    parsed = urlparse(url)
    if parsed.scheme != "https" or parsed.hostname not in _PINNED_CA_HOSTS:
        raise RuntimeError(f"CA download host rejected: {url}")
    request = urllib.request.Request(url, headers={"User-Agent": "KORGAN-corpus-loader/1.3"})
    with urllib.request.urlopen(request, timeout=30, context=ssl.create_default_context()) as response:  # noqa: S310
        final = urlparse(response.geturl())
        if final.scheme != "https" or final.hostname not in _PINNED_CA_HOSTS:
            raise RuntimeError(f"CA redirect rejected: {response.geturl()}")
        pem = response.read().decode("ascii").strip()
    if "-----BEGIN CERTIFICATE-----" not in pem or "-----END CERTIFICATE-----" not in pem:
        raise RuntimeError(f"CA payload is not PEM: {url}")
    der = ssl.PEM_cert_to_DER_cert(pem)
    actual = hashlib.sha256(der).hexdigest().upper()
    if actual != expected_sha256.upper():
        raise RuntimeError(f"CA fingerprint mismatch for {url}: expected {expected_sha256}, got {actual}")
    return pem


def _adilet_context_with_pinned_intermediates() -> ssl.SSLContext:
    context = ssl.create_default_context()
    loaded = 0
    for url, fingerprint in _PINNED_INTERMEDIATES:
        try:
            context.load_verify_locations(cadata=_download_pinned_intermediate(url, fingerprint))
            loaded += 1
        except Exception as exc:
            LOGGER.warning("KORGAN CA supplement skipped url=%s error=%s", url, exc)
    if loaded == 0:
        raise RuntimeError("No pinned Adilet intermediate could be loaded")
    LOGGER.info("KORGAN TLS context supplemented with %d fingerprint-pinned CA(s)", loaded)
    return context


def fetch_adilet(url: str, timeout: int = 60) -> tuple[str, str]:
    if not _is_allowed_adilet_url(url):
        raise RuntimeError(f"Adilet URL rejected: {url}")
    parsed = urlparse(url)
    alt_host = "www.adilet.zan.kz" if parsed.hostname == "adilet.zan.kz" else "adilet.zan.kz"
    candidates = [url, parsed._replace(netloc=alt_host).geturl()]
    errors: list[str] = []
    standard = ssl.create_default_context()
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


def _load_one(corpus: LegalCorpus, act_id: str) -> int:
    canonical_url = act_url(act_id)
    html, final_url = fetch_adilet(canonical_url)
    loaded = load_act(
        corpus,
        act_id,
        html,
        url=final_url,
        articles=ACT_ARTICLE_FILTER.get(act_id),
    )
    LOGGER.info("KORGAN corpus refresh act=%s provisions=%d source=%s", act_id, loaded, final_url)
    return loaded


def refresh_corpus_once(path: Path | str = DEFAULT_DB_PATH) -> int:
    """Build core atomically and enrich it with every optional act that succeeds."""
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_name(target.name + ".refreshing")
    temporary.unlink(missing_ok=True)

    total = 0
    core_loaded = 0
    optional_loaded = 0
    optional_failed: list[str] = []
    try:
        with LegalCorpus(temporary) as corpus:
            for act_id in sorted(CORE_ACT_IDS):
                total += _load_one(corpus, act_id)
                core_loaded += 1

            if core_loaded != len(CORE_ACT_IDS) or total <= 0:
                raise RuntimeError(
                    f"Incomplete core corpus refresh: acts={core_loaded}/{len(CORE_ACT_IDS)}, provisions={total}"
                )

            for act_id in sorted(OPTIONAL_ACT_IDS):
                try:
                    total += _load_one(corpus, act_id)
                    optional_loaded += 1
                except Exception as exc:
                    optional_failed.append(act_id)
                    LOGGER.warning(
                        "KORGAN optional corpus act skipped safely act=%s error=%s: %s",
                        act_id,
                        type(exc).__name__,
                        exc,
                    )

        os.replace(temporary, target)
        LOGGER.info(
            "KORGAN corpus refresh SUCCESS core=%d optional=%d optional_failed=%d provisions=%d path=%s",
            core_loaded,
            optional_loaded,
            len(optional_failed),
            total,
            target,
        )
        if optional_failed:
            LOGGER.info("KORGAN optional acts unavailable this refresh: %s", ",".join(optional_failed))
        return total
    except Exception:
        temporary.unlink(missing_ok=True)
        raise


async def corpus_refresh_loop() -> None:
    while True:
        try:
            await asyncio.to_thread(refresh_corpus_once)
        except asyncio.CancelledError:
            raise
        except Exception:
            LOGGER.exception("KORGAN corpus refresh failed safely — existing corpus/web search remains active")
        await asyncio.sleep(refresh_hours() * 3600)


def start_corpus_refresh_task() -> asyncio.Task[None] | None:
    if not autoload_enabled():
        LOGGER.info("KORGAN corpus autoload disabled")
        return None
    LOGGER.info("KORGAN corpus autoload enabled refresh_hours=%.1f", refresh_hours())
    return asyncio.create_task(corpus_refresh_loop(), name="korgan-corpus-refresh")
