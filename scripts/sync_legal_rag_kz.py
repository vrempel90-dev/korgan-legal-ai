#!/usr/bin/env python3
"""Build/refresh KORGAN's retrieval-only Kazakhstan corpus from the pinned upstream release."""

from __future__ import annotations

import argparse
import json

from korgan.legal.upstream_rag import sync_upstream_rag


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--force", action="store_true", help="rebuild even when the pinned commit is already loaded")
    args = parser.parse_args()
    status = sync_upstream_rag(force=args.force)
    print(json.dumps(status.as_dict(), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
