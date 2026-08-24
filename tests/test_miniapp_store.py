from __future__ import annotations

import json

import pytest

from korgan.miniapp_store import MiniAppStore


def test_user_key_is_deterministic_hmac_not_plain_id() -> None:
    store = MiniAppStore("", secret="test-secret")
    key1 = store.user_key("123456789")
    key2 = store.user_key("123456789")
    assert key1 == key2
    assert key1 != "123456789"
    assert len(key1) == 64


def test_state_envelope_encrypts_sensitive_content_and_roundtrips() -> None:
    store = MiniAppStore("", secret="test-secret")
    aad = store.user_key("42")
    state = {
        "consent": {"accepted": True},
        "cases": {"KOR-1": {"description": "Секретные материалы дела 8 500 000 ₸"}},
    }

    envelope = store._encode_state(state, aad=aad)
    raw = json.dumps(envelope, ensure_ascii=False)
    assert "Секретные материалы" not in raw
    assert envelope["alg"] == "AES-256-GCM"

    decoded, needs_migration = store._decode_state(envelope, aad=aad)
    assert decoded == state
    assert needs_migration is False


def test_tampered_ciphertext_is_rejected() -> None:
    store = MiniAppStore("", secret="test-secret")
    aad = store.user_key("42")
    envelope = store._encode_state({"consent": None, "cases": {}}, aad=aad)
    envelope["ciphertext"] = envelope["ciphertext"][:-4] + "AAAA"
    with pytest.raises(RuntimeError, match="decryption failed"):
        store._decode_state(envelope, aad=aad)


def test_plain_staging_state_is_marked_for_encryption_migration() -> None:
    store = MiniAppStore("", secret="test-secret")
    old = {"consent": {"accepted": True}, "cases": {}}
    decoded, needs_migration = store._decode_state(old, aad=store.user_key("7"))
    assert decoded == old
    assert needs_migration is True
