from korgan.document_category_router import preferred_document_category


def test_route_isolation_branch_marker() -> None:
    assert preferred_document_category("Подготовь ответ на претензию") == "pretrial_response"
