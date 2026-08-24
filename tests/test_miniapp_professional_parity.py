from __future__ import annotations

import hashlib
import hmac
import json
import time
from urllib.parse import urlencode

from fastapi.testclient import TestClient

from korgan import miniapp_api_v2
from korgan.legal_types import VerificationStatus


def _telegram_init_data(user_id: int = -900000077) -> str:
    pairs = {
        "auth_date": str(int(time.time())),
        "query_id": "korgan-miniapp-professional",
        "user": json.dumps(
            {"id": user_id, "first_name": "KORGAN", "language_code": "ru"},
            ensure_ascii=False,
            separators=(",", ":"),
        ),
    }
    data_check_string = "\n".join(f"{key}={pairs[key]}" for key in sorted(pairs))
    secret_key = hmac.new(
        b"WebAppData",
        miniapp_api_v2.settings.telegram_bot_token.encode(),
        hashlib.sha256,
    ).digest()
    pairs["hash"] = hmac.new(secret_key, data_check_string.encode(), hashlib.sha256).hexdigest()
    return urlencode(pairs)


def test_professional_runtime_reports_same_strict_legal_core() -> None:
    with TestClient(miniapp_api_v2.app) as client:
        payload = client.get("/health").json()
    assert payload["status"] == "ok"
    assert payload["legal_runtime"] == "strict_bot"
    assert payload["word_quality_target"] == "10/10"
    assert payload["preliminary_fallback"] is True


def test_upload_only_case_can_be_created_without_synthetic_facts() -> None:
    headers = {"X-Telegram-Init-Data": _telegram_init_data()}
    with TestClient(miniapp_api_v2.app) as client:
        accepted = client.post(
            "/miniapp/consent",
            headers=headers,
            json={"accepted": True, "terms_version": "2026-08-16-v1"},
        )
        assert accepted.status_code == 200

        created = client.post(
            "/miniapp/cases",
            headers=headers,
            json={"description": "", "document_type": "claim", "language": "ru"},
        )
        assert created.status_code == 200
        case = created.json()["case"]
        assert case["description"] == ""
        assert case["filing_ready"] is False
        assert case["release_status"] == "not_generated"

        removed = client.delete(f"/miniapp/cases/{case['id']}", headers=headers)
        assert removed.status_code == 200
        client.delete("/miniapp/me", headers=headers)


def test_material_context_keeps_source_boundary_and_excludes_ai_answers() -> None:
    case = {
        "description": "Истец сообщил о просрочке поставки.",
        "materials": [
            {"filename": "dogovor.pdf", "context": "Договор поставки №15."},
            {"filename": "pretenziya.docx", "context": "Требование оплатить 500 000 тенге."},
        ],
        "conversation": [
            {"role": "user", "text": "Оплата должна была быть 1 августа."},
            {"role": "ai", "text": "Неподтвержденная сумма штрафа 999 999 тенге."},
        ],
    }
    context = miniapp_api_v2._case_context(case)
    assert "ИСТОЧНИК МАТЕРИАЛА: dogovor.pdf" in context
    assert "ИСТОЧНИК МАТЕРИАЛА: pretenziya.docx" in context
    assert "Оплата должна была быть 1 августа" in context
    assert "Неподтвержденная сумма штрафа" not in context


def test_release_status_recognizes_only_verified_enum() -> None:
    assert miniapp_api_v2._is_verified(VerificationStatus.VERIFIED) is True
    assert miniapp_api_v2._is_verified(VerificationStatus.NEEDS_VERIFICATION) is False
