from fastapi import HTTPException
from fastapi.testclient import TestClient
import pytest

import dashboard


def test_production_app_and_assets_use_the_same_dashboard_auth(dashboard_client, tmp_path, monkeypatch):
    dist = tmp_path / "dist"
    assets = dist / "assets"
    assets.mkdir(parents=True)
    (dist / "index.html").write_text('<div id="root"></div><script src="/app/assets/app.js"></script>', encoding="utf-8")
    (assets / "app.js").write_text("window.productionApp = true", encoding="utf-8")
    monkeypatch.setattr(dashboard, "WEB_DIST", dist)

    page = dashboard_client.get("/app/")
    asset = dashboard_client.get("/app/assets/app.js")
    demo = dashboard_client.get("/app/demo/")

    assert page.status_code == 200
    assert 'id="root"' in page.text
    assert page.headers["cache-control"] == "no-store"
    assert asset.status_code == 200
    assert asset.text == "window.productionApp = true"
    assert asset.headers["cache-control"] == "public, max-age=31536000, immutable"
    assert demo.status_code == 200
    assert demo.text == page.text


def test_react_routes_fail_closed_without_dashboard_auth(monkeypatch, tmp_path):
    monkeypatch.setattr(dashboard, "_DASH_TOKEN", "expected-token")
    monkeypatch.setattr(dashboard, "WEB_DIST", tmp_path)
    client = TestClient(dashboard.app)

    assert client.get("/app/").status_code == 401
    assert client.get("/app/assets/app.js").status_code == 401


def test_missing_build_returns_a_setup_message(dashboard_client, tmp_path, monkeypatch):
    monkeypatch.setattr(dashboard, "WEB_DIST", tmp_path)

    response = dashboard_client.get("/app/")

    assert response.status_code == 503
    assert "bun run build" in response.text


def test_asset_route_rejects_paths_outside_the_build_directory(tmp_path, monkeypatch):
    dist = tmp_path / "dist"
    dist.mkdir()
    (tmp_path / "secret.txt").write_text("private", encoding="utf-8")
    monkeypatch.setattr(dashboard, "WEB_DIST", dist)

    with pytest.raises(HTTPException) as error:
        dashboard.react_asset("../../secret.txt")

    assert error.value.status_code == 404


def test_legacy_dashboard_links_to_the_integrated_app():
    assert 'href="/app/"' in dashboard.HTML
    assert 'واجهة الإنتاج الفعلية' in dashboard.HTML
