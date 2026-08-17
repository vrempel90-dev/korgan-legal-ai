#!/usr/bin/env python3
"""One-shot Railway diagnostic for the public zan.gov.kz document API.

Prints only endpoint structure and JavaScript snippets around the search API;
no KORGAN secrets or user data are read.
"""
from __future__ import annotations

import json
import re
import ssl
import urllib.parse
import urllib.request

BASE = "https://zan.gov.kz"
UA = "KORGAN-zan-api-probe/1.0"


def get(url: str) -> tuple[str, str, int]:
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "*/*"})
    with urllib.request.urlopen(req, timeout=30, context=ssl.create_default_context()) as r:  # noqa: S310
        raw = r.read()
        return raw.decode("utf-8", errors="replace"), r.headers.get("content-type", ""), r.status


def main() -> int:
    try:
        text, ctype, status = get(f"{BASE}/client/")
        print("ZAN_CLIENT", status, ctype, "bytes", len(text.encode("utf-8")))
    except Exception as exc:
        print("ZAN_CLIENT_ERROR", type(exc).__name__, exc)
        return 0

    srcs = re.findall(r'<script[^>]+src=["\']([^"\']+)["\']', text, flags=re.I)
    print("ZAN_SCRIPTS", len(srcs))
    found = 0
    for src in srcs[-30:]:
        url = urllib.parse.urljoin(f"{BASE}/client/", src)
        try:
            js, _, _ = get(url)
        except Exception as exc:
            print("ZAN_JS_ERROR", url, type(exc).__name__, exc)
            continue
        needle = "/api/documents/search"
        idx = js.find(needle)
        if idx >= 0:
            found += 1
            lo = max(0, idx - 2500)
            hi = min(len(js), idx + 2500)
            print("ZAN_SEARCH_JS_BEGIN", url)
            print(js[lo:hi].replace("\x00", ""))
            print("ZAN_SEARCH_JS_END")
            if found >= 3:
                break
    print("ZAN_SEARCH_JS_FOUND", found)

    known = f"{BASE}/api/documents/200655/rus?withHtml=false&page=1"
    try:
        body, ctype, status = get(known)
        print("ZAN_KNOWN_DOC", status, ctype, "chars", len(body))
        try:
            parsed = json.loads(body)
            if isinstance(parsed, dict):
                print("ZAN_KNOWN_KEYS", sorted(parsed.keys()))
            elif isinstance(parsed, list):
                print("ZAN_KNOWN_LIST", len(parsed))
            print("ZAN_KNOWN_JSON", json.dumps(parsed, ensure_ascii=False)[:5000])
        except Exception:
            print("ZAN_KNOWN_TEXT", body[:5000])
    except Exception as exc:
        print("ZAN_KNOWN_ERROR", type(exc).__name__, exc)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
