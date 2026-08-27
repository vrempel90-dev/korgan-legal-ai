from __future__ import annotations

import os

# Mini App modules instantiate Settings at import time. CI intentionally has no
# production secrets, so provide inert test-only defaults before test collection.
os.environ.setdefault("TELEGRAM_BOT_TOKEN", "000000:test-only-token")
os.environ.setdefault("OPENAI_API_KEY", "test-only-openai-key")
