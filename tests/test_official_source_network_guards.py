from __future__ import annotations

import http.server
import ssl
import threading
import urllib.request
from pathlib import Path

import pytest

from korgan.legal.corpus import ACT_GK_SPECIAL, ACT_GPK, LegalCorpus
from korgan.legal.corpus_refresh import _AllowlistedRedirectHandler, _open_allowlisted
from korgan.legal.official_sources import is_allowed_adilet_url
from scripts.load_corpus import SourceRejected, load_act_text, strip_html

FIXTURES = Path(__file__).resolve().parent / "fixtures"
GPK_URL = "https://adilet.zan.kz/rus/docs/K1500000377"
GK_SPECIAL_URL = "https://adilet.zan.kz/rus/docs/K990000409_"


def test_adilet_url_is_bound_to_expected_act() -> None:
    assert is_allowed_adilet_url(GPK_URL, act_id=ACT_GPK)
    assert not is_allowed_adilet_url(GPK_URL, act_id=ACT_GK_SPECIAL)
    assert is_allowed_adilet_url(GK_SPECIAL_URL, act_id=ACT_GK_SPECIAL)
    assert not is_allowed_adilet_url(GK_SPECIAL_URL, act_id=ACT_GPK)


def test_direct_wrong_adilet_document_is_rejected_before_storage(tmp_path: Path) -> None:
    text = strip_html((FIXTURES / "adilet_gk_osobennaya.html").read_text(encoding="utf-8"))

    with LegalCorpus(tmp_path / "corpus.sqlite3") as corpus:
        with pytest.raises(SourceRejected, match="не соответствует акту"):
            load_act_text(
                corpus,
                ACT_GPK,
                text,
                source_url=GK_SPECIAL_URL,
            )
        assert corpus.count() == 0


def test_cross_act_adilet_redirect_is_rejected_before_request_creation() -> None:
    handler = _AllowlistedRedirectHandler(
        lambda url: is_allowed_adilet_url(url, act_id=ACT_GPK)
    )
    request = urllib.request.Request(GPK_URL)

    with pytest.raises(RuntimeError, match="redirect target rejected before request"):
        handler.redirect_request(
            request,
            None,
            302,
            "Found",
            {},
            GK_SPECIAL_URL,
        )


def test_loopback_redirect_target_is_never_contacted() -> None:
    target_hits = 0

    class TargetHandler(http.server.BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802
            nonlocal target_hits
            target_hits += 1
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b"target")

        def log_message(self, *_args: object) -> None:
            return

    target = http.server.ThreadingHTTPServer(("127.0.0.1", 0), TargetHandler)
    target_url = f"http://127.0.0.1:{target.server_port}/target"

    class SourceHandler(http.server.BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802
            self.send_response(302)
            self.send_header("Location", target_url)
            self.end_headers()

        def log_message(self, *_args: object) -> None:
            return

    source = http.server.ThreadingHTTPServer(("127.0.0.1", 0), SourceHandler)
    source_url = f"http://127.0.0.1:{source.server_port}/start"

    source_thread = threading.Thread(target=source.serve_forever, daemon=True)
    target_thread = threading.Thread(target=target.serve_forever, daemon=True)
    source_thread.start()
    target_thread.start()
    try:
        request = urllib.request.Request(source_url)
        with pytest.raises(RuntimeError, match="redirect target rejected before request"):
            with _open_allowlisted(
                request,
                context=ssl.create_default_context(),
                timeout=2,
                allow_url=lambda url: url == source_url,
            ) as response:
                response.read()
        assert target_hits == 0
    finally:
        source.shutdown()
        target.shutdown()
        source.server_close()
        target.server_close()
        source_thread.join(timeout=2)
        target_thread.join(timeout=2)
