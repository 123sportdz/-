import dashboard


def test_audit_page_builds_dynamic_rows_with_text_nodes():
    html = dashboard.api_audit_page().body.decode("utf-8")

    assert "textContent" in html
    assert "replaceChildren" in html
    assert "rows.innerHTML" not in html
