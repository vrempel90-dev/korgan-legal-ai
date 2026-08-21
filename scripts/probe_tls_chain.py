#!/usr/bin/env python3
"""Print peer certificate-chain metadata for Kazakhstan legal-source hosts.

Diagnostic only: no page content is fetched or trusted. OpenSSL is allowed to
complete a handshake even when verification fails so KORGAN can identify the
exact leaf/intermediate issuer that Railway is being presented with.
"""
from __future__ import annotations

import re
import subprocess
import tempfile
from pathlib import Path

HOSTS = ("adilet.zan.kz", "zan.gov.kz", "law.gov.kz")
_CERT_RE = re.compile(r"-----BEGIN CERTIFICATE-----.*?-----END CERTIFICATE-----", re.S)


def cert_meta(pem: str) -> str:
    with tempfile.NamedTemporaryFile("w", suffix=".pem", delete=False) as handle:
        handle.write(pem)
        path = Path(handle.name)
    try:
        proc = subprocess.run(
            [
                "openssl", "x509", "-in", str(path), "-noout",
                "-subject", "-issuer", "-serial", "-dates", "-fingerprint", "-sha256",
            ],
            capture_output=True,
            text=True,
            timeout=15,
            check=False,
        )
        return (proc.stdout + proc.stderr).strip().replace("\n", " | ")
    finally:
        path.unlink(missing_ok=True)


def probe(host: str) -> None:
    try:
        proc = subprocess.run(
            [
                "openssl", "s_client", "-connect", f"{host}:443", "-servername", host,
                "-showcerts", "-verify_return_error",
            ],
            input="",
            capture_output=True,
            text=True,
            timeout=25,
            check=False,
        )
    except Exception as exc:
        print("TLS_PROBE_ERROR", host, type(exc).__name__, exc)
        return

    combined = proc.stdout + "\n" + proc.stderr
    certs = _CERT_RE.findall(combined)
    verify_lines = [
        line.strip() for line in combined.splitlines()
        if "Verify return code" in line or "verify error" in line.lower()
    ]
    print("TLS_HOST", host, "returncode", proc.returncode, "chain_certs", len(certs))
    for index, pem in enumerate(certs):
        print("TLS_CERT", host, index, cert_meta(pem))
    for line in verify_lines[-6:]:
        print("TLS_VERIFY", host, line)


def main() -> int:
    for host in HOSTS:
        probe(host)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
