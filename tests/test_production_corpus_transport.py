from __future__ import annotations

import http.client
import ssl

import pytest

import korgan.legal.corpus_refresh as refresh
from korgan.legal.corpus import ACT_GK_SPECIAL, ACT_GPK
from scripts.load_corpus import act_url


def test_adilet_retries_transient_incomplete_transfer(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = 0
    expected_url = act_url(ACT_GPK)

    def flaky_read(url: str, *, context, act_id: str, timeout: int = 60):
        nonlocal calls
        del context, timeout
        assert act_id == ACT_GPK
        assert url == expected_url
        calls += 1
        if calls == 1:
            raise http.client.IncompleteRead(b"partial", 100)
        return "<html>complete official act</html>", url

    monkeypatch.setattr(refresh, "_read_https", flaky_read)

    payload, final_url = refresh.fetch_adilet(expected_url)

    assert payload == "<html>complete official act</html>"
    assert final_url == expected_url
    assert calls == 2


def test_adilet_does_not_retry_non_transport_failure_on_same_candidate(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[str] = []
    contexts = [ssl.create_default_context(), ssl.create_default_context()]

    def rejected_read(url: str, *, context, act_id: str, timeout: int = 60):
        del context, act_id, timeout
        calls.append(url)
        raise RuntimeError("source validation failed")

    monkeypatch.setattr(refresh, "_read_https", rejected_read)
    monkeypatch.setattr(refresh, "_adilet_context_with_pinned_intermediates", lambda: contexts[1])

    with pytest.raises(RuntimeError, match="Adilet fetch failed with verified TLS"):
        refresh.fetch_adilet(act_url(ACT_GK_SPECIAL))

    # Two allowlisted hosts x two verified trust contexts. A validation failure
    # is tried once per candidate/context, never three times like a transport reset.
    assert len(calls) == 4


def test_zan_retries_with_fingerprint_pinned_verified_context(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    attempts = 0
    supplemented = ssl.create_default_context()
    payload = b"%PDF-" + b"x" * 2048
    expected_url = refresh.zan_pdf_url(ACT_GPK)

    def fake_read(act_id: str, *, context: ssl.SSLContext, timeout: int):
        nonlocal attempts
        del timeout
        assert act_id == ACT_GPK
        attempts += 1
        if attempts == 1:
            raise ssl.SSLCertVerificationError("missing issuer")
        assert context is supplemented
        return payload, expected_url

    monkeypatch.setattr(refresh, "_read_zan_pdf_with_context", fake_read)
    monkeypatch.setattr(refresh, "_adilet_context_with_pinned_intermediates", lambda: supplemented)

    actual_payload, final_url = refresh._read_zan_pdf(ACT_GPK)

    assert actual_payload == payload
    assert final_url == expected_url
    assert attempts == 2
