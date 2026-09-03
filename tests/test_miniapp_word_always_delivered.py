from korgan.miniapp_professional_release import apply_release_policy


def test_non_filing_ready_generation_is_delivered_as_review_draft(monkeypatch):
    monkeypatch.setenv("KORGAN_PRELIMINARY_DELIVERY", "off")
    result = {
        "filing_ready": False,
        "release_status": "preliminary",
        "quality_score": 8.4,
        "quality_issues": ["есть правовая ссылка, не прошедшая source-bound/corpus проверку"],
        "verification_notes": ["FILING_ACTION: указать банковские реквизиты истца перед подачей."],
        "document_base64": "generated-docx",
        "filename": "KORGAN_isk.docx",
    }

    released = apply_release_policy(result, case_id="KOR-TEST")

    assert released["document_base64"] == "generated-docx"
    assert released["filename"] == "KORGAN_isk.docx"
    assert released["filing_ready"] is False
    assert released["release_status"] == "preliminary"
    assert released["preliminary"] is True
    assert "todo_before_filing" in released
    assert released["message"].startswith("Документ готов как предварительный проект")


def test_verified_generation_remains_filing_ready():
    result = {
        "filing_ready": True,
        "release_status": "verified",
        "quality_score": 10.0,
        "quality_issues": [],
        "verification_notes": [],
        "document_base64": "generated-docx",
        "filename": "KORGAN_isk.docx",
    }

    released = apply_release_policy(result, case_id="KOR-TEST")

    assert released is result
    assert released["filing_ready"] is True
    assert released["release_status"] == "verified"
    assert "preliminary" not in released
