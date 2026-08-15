from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import os
from dataclasses import dataclass

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF


class SessionCryptoError(RuntimeError):
    pass


@dataclass(frozen=True)
class EncryptedValue:
    ciphertext: bytes
    nonce: bytes


class SessionCrypto:
    """Pseudonymize Telegram subjects and encrypt unfinished case text."""

    def __init__(self, root_key: bytes) -> None:
        if len(root_key) < 32:
            raise ValueError("Session master key must contain at least 32 random bytes")
        if len(set(root_key)) < 8:
            # Catches placeholder keys such as all-zero or repeated-byte values that would
            # otherwise pass the length check and silently weaken every derived key.
            raise ValueError("Session master key does not look like random bytes")
        self._subject_key = HKDF(
            algorithm=hashes.SHA256(),
            length=32,
            salt=None,
            info=b"korgan.telegram.sessions.subject-hmac.v1",
        ).derive(root_key)
        self._data_key = HKDF(
            algorithm=hashes.SHA256(),
            length=32,
            salt=None,
            info=b"korgan.telegram.sessions.aes-gcm.v1",
        ).derive(root_key)
        self._aes = AESGCM(self._data_key)

    @classmethod
    def from_base64(cls, encoded_key: str) -> "SessionCrypto":
        try:
            raw = base64.b64decode(encoded_key, validate=True)
        except (ValueError, binascii.Error):
            # The key itself is never included in the error: it must not reach logs.
            raise ValueError("TELEGRAM_SESSION_MASTER_KEY must be valid base64") from None
        return cls(raw)

    def subject_hmac(self, telegram_user_id: int) -> bytes:
        if telegram_user_id <= 0:
            raise ValueError("Telegram user id must be positive")
        return hmac.new(
            self._subject_key,
            str(telegram_user_id).encode("ascii"),
            hashlib.sha256,
        ).digest()

    @staticmethod
    def _aad(subject_hmac: bytes) -> bytes:
        return b"korgan.telegram.session.case.v1:" + subject_hmac

    def encrypt_case(self, subject_hmac: bytes, plaintext: str) -> EncryptedValue:
        nonce = os.urandom(12)
        ciphertext = self._aes.encrypt(
            nonce,
            plaintext.encode("utf-8"),
            self._aad(subject_hmac),
        )
        return EncryptedValue(ciphertext=ciphertext, nonce=nonce)

    def decrypt_case(self, subject_hmac: bytes, ciphertext: bytes, nonce: bytes) -> str:
        try:
            plaintext = self._aes.decrypt(
                nonce,
                ciphertext,
                self._aad(subject_hmac),
            )
            return plaintext.decode("utf-8")
        except Exception:
            # Fail closed and never surface partially decrypted bytes or the original error,
            # which could echo ciphertext or plaintext fragments into logs.
            raise SessionCryptoError(
                "Encrypted Telegram session failed integrity verification"
            ) from None
