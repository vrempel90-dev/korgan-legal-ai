from __future__ import annotations

import base64
import hashlib
import hmac

import pytest

from korgan_legal_ai.telegram.crypto import SessionCrypto, SessionCryptoError


def test_session_crypto_roundtrip_and_subject_pseudonymization() -> None:
    root = bytes(range(32))
    crypto = SessionCrypto(root)
    subject = crypto.subject_hmac(123456789)

    assert len(subject) == 32
    assert b"123456789" not in subject

    encrypted = crypto.encrypt_case(subject, "Секретный текст дела")
    assert encrypted.ciphertext != "Секретный текст дела".encode("utf-8")
    assert len(encrypted.nonce) == 12
    assert crypto.decrypt_case(subject, encrypted.ciphertext, encrypted.nonce) == "Секретный текст дела"


def test_session_crypto_detects_tampering_and_wrong_subject() -> None:
    crypto = SessionCrypto(bytes(range(32)))
    subject = crypto.subject_hmac(100)
    encrypted = crypto.encrypt_case(subject, "case")

    tampered = bytearray(encrypted.ciphertext)
    tampered[-1] ^= 1
    with pytest.raises(SessionCryptoError):
        crypto.decrypt_case(subject, bytes(tampered), encrypted.nonce)

    with pytest.raises(SessionCryptoError):
        crypto.decrypt_case(crypto.subject_hmac(101), encrypted.ciphertext, encrypted.nonce)


def test_session_crypto_base64_key_validation() -> None:
    encoded = base64.b64encode(bytes(range(32))).decode("ascii")
    assert len(SessionCrypto.from_base64(encoded).subject_hmac(1)) == 32

    with pytest.raises(ValueError):
        SessionCrypto.from_base64("not base64!!")

    with pytest.raises(ValueError):
        SessionCrypto(b"short")


def test_session_crypto_rejects_non_random_master_key() -> None:
    # A long but degenerate key would pass a pure length check while weakening every derived key.
    with pytest.raises(ValueError):
        SessionCrypto(b"\x00" * 32)
    with pytest.raises(ValueError):
        SessionCrypto(b"AB" * 32)


def test_every_encryption_uses_a_fresh_nonce() -> None:
    crypto = SessionCrypto(bytes(range(32)))
    subject = crypto.subject_hmac(4242)

    nonces = {crypto.encrypt_case(subject, "одинаковый текст дела").nonce for _ in range(64)}
    ciphertexts = {crypto.encrypt_case(subject, "одинаковый текст дела").ciphertext for _ in range(64)}

    assert len(nonces) == 64
    assert len(ciphertexts) == 64


def test_hmac_and_encryption_keys_are_separated_by_hkdf() -> None:
    root = bytes(range(32))
    crypto = SessionCrypto(root)

    # The pseudonym must not be a plain HMAC under the raw master key: the subject key is a
    # separate HKDF branch, so compromising one derived key does not yield the other.
    naive = hmac.new(root, b"777", hashlib.sha256).digest()
    assert crypto.subject_hmac(777) != naive

    # An independently built instance derives the same keys, which is what makes restart-resume
    # and cross-process decryption work.
    assert SessionCrypto(root).subject_hmac(777) == crypto.subject_hmac(777)


def test_case_ciphertext_is_bound_to_its_subject_via_aad() -> None:
    crypto = SessionCrypto(bytes(range(32)))
    victim = crypto.subject_hmac(1000)
    attacker = crypto.subject_hmac(2000)
    encrypted = crypto.encrypt_case(victim, "чужой текст дела")

    # Copying another subject's row into your own record must not make it readable.
    with pytest.raises(SessionCryptoError):
        crypto.decrypt_case(attacker, encrypted.ciphertext, encrypted.nonce)


def test_nonce_substitution_is_rejected() -> None:
    crypto = SessionCrypto(bytes(range(32)))
    subject = crypto.subject_hmac(1)
    first = crypto.encrypt_case(subject, "первый текст")
    second = crypto.encrypt_case(subject, "второй текст")

    with pytest.raises(SessionCryptoError):
        crypto.decrypt_case(subject, first.ciphertext, second.nonce)
