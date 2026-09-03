from __future__ import annotations

from korgan import miniapp_calculation_advisory_runtime as runtime
from korgan.legal_types import ClaimDraft, VerificationStatus


def _draft() -> ClaimDraft:
    return ClaimDraft(
        status=VerificationStatus.VERIFIED,
        title="Иск",
        court="Суд",
        claimant=["Истец"],
        defendant=["Ответчик"],
        price_of_claim="1 000 000 тенге",
        facts=["Основной долг подтверждён."],
        legal_basis=[],
        requests=["Взыскать основной долг 1 000 000 тенге."],
        attachments=[],
        verification_notes=[],
        source_urls=[],
    )


def test_fields_keep_optional_calculation_uncertainty_separate_from_legal_status() -> None:
    draft = _draft()
    draft.late_interest = (
        "Неустойка в цену иска и просительную часть не включена. "
        "Требует уточнения: не удалось однозначно установить дату начала просрочки."
    )

    fields = runtime._fields(draft, "ru")

    assert draft.status == VerificationStatus.VERIFIED
    assert fields["calculation_todo"]
    assert "Неустойка" in fields["calculation_todo"][0]
    assert "советую обратиться к юристу KORGAN" in fields["calculation_advisory"]


def test_merge_client_todo_preserves_existing_filing_tasks_and_adds_lawyer_cta() -> None:
    payload = {
        "filing_ready": True,
        "release_status": "verified",
        "todo_before_filing": ["проверить банковские реквизиты"],
        "calculation_todo": ["Неустойка: уточнить дату начала просрочки."],
    }

    result = runtime._merge_client_todo(payload, "ru")

    assert result["filing_ready"] is True
    assert result["release_status"] == "verified"
    assert result["todo_before_filing"][0] == "проверить банковские реквизиты"
    assert "Неустойка: уточнить дату начала просрочки." in result["todo_before_filing"]
    assert any("советую обратиться к юристу KORGAN" in item for item in result["todo_before_filing"])


def test_lawyer_cta_and_calculation_survive_crowded_existing_checklist() -> None:
    payload = {
        "todo_before_filing": [f"обычная задача {index}" for index in range(12)],
        "calculation_todo": ["Неустойка: уточнить дату начала просрочки."],
    }

    result = runtime._merge_client_todo(payload, "ru")

    assert len(result["todo_before_filing"]) == runtime._MAX_CLIENT_TODO
    assert "Неустойка: уточнить дату начала просрочки." in result["todo_before_filing"]
    assert "советую обратиться к юристу KORGAN" in result["todo_before_filing"][-1]


def test_merge_client_todo_is_noop_when_calculations_are_confirmed() -> None:
    payload = {
        "filing_ready": True,
        "release_status": "verified",
        "todo_before_filing": [],
        "calculation_todo": [],
    }

    result = runtime._merge_client_todo(payload, "ru")

    assert result["todo_before_filing"] == []
    assert "calculation_advisory" not in result


def test_kazakh_ready_list_uses_korgan_lawyer_recommendation() -> None:
    payload = {
        "todo_before_filing": [],
        "calculation_todo": ["Тұрақсыздық айыбы: мерзімнің басталу күнін нақтылау қажет."],
    }

    result = runtime._merge_client_todo(payload, "kk")

    assert any("KORGAN заңгеріне" in item for item in result["todo_before_filing"])
