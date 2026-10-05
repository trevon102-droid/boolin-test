from fastapi.testclient import TestClient

from app.main import app


client = TestClient(app)


def test_health():
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_research_board():
    response = client.get("/research-board")
    assert response.status_code == 200
    assert response.json()[0]["game_id"] == "NFL-2026-BUF-KC"


def test_research_card():
    response = client.get("/games/NFL-2026-BUF-KC/research")
    assert response.status_code == 200
    payload = response.json()
    assert "market_vs_model" in payload
    assert "unknowns" in payload


def test_openapi():
    response = client.get("/openapi.json")
    assert response.status_code == 200
    spec = response.json()
    assert "/research-board" in spec["paths"]
    assert "/games/{game_id}/research" in spec["paths"]
