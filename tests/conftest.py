import pytest
from fastapi.testclient import TestClient

import dashboard


@pytest.fixture
def dashboard_client(monkeypatch):
    token = "test-dashboard-token"
    monkeypatch.setattr(dashboard, "_DASH_TOKEN", token)
    return TestClient(dashboard.app, headers={"Authorization": f"Bearer {token}"})
