from korgan import upload_followup_guard


def test_upload_followup_is_document_neutral() -> None:
    assert "попросить подготовить иск" in upload_followup_guard._OLD_FOLLOWUP
    assert "попросить подготовить иск" not in upload_followup_guard._NEW_FOLLOWUP
    assert "продолжить подготовку выбранного документа" in upload_followup_guard._NEW_FOLLOWUP
