from korgan.document_category_router import preferred_document_category


def test_route_isolation_staging_marker_2() -> None:
    assert preferred_document_category("Подготовь досудебную претензию") == "pretrial"
    assert preferred_document_category("Подготовь отзыв на иск") == "response"
    assert preferred_document_category("Подготовь исковое заявление") == "claim"
