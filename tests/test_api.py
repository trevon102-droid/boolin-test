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
    assert response.json()[0]["research_score"] > 0


def test_research_card_builds_dynamic_flags_and_freshness():
    response = client.get("/games/NFL-2026-BUF-KC/research")
    assert response.status_code == 200
    payload = response.json()
    assert "market_vs_model" in payload
    assert "market_summary" in payload
    assert "freshness" in payload
    assert any(flag["code"] == "SMALL_SAMPLE" for flag in payload["flags"])
    assert any(flag["code"] == "AVAILABILITY_UNRESOLVED" for flag in payload["flags"])


def test_market_summary_and_changes():
    summary = client.get("/games/NFL-2026-BUF-KC/market-summary")
    changes = client.get("/games/NFL-2026-BUF-KC/changes")
    assert summary.status_code == 200
    assert changes.status_code == 200
    assert any(item["market"] == "spread" for item in summary.json())
    assert any(change["category"] == "market" for change in changes.json())


def test_research_endpoints():
    for suffix in ("compare", "freshness", "flags", "scenarios"):
        response = client.get(f"/games/NFL-2026-BUF-KC/{suffix}")
        assert response.status_code == 200


def test_notes_and_reviews():
    note = {
        "thesis": "Buffalo can stay inside the number if the run game travels.",
        "supporting_evidence": ["Lower projected total."],
        "contradicting_evidence": ["WR1 is unresolved."],
        "unknowns": ["Final availability."],
        "decision": "watch",
        "entry_trigger": "Wait for confirmation.",
    }
    response = client.post("/games/NFL-2026-BUF-KC/notes", json=note)
    assert response.status_code == 201
    assert response.json()["thesis"] == note["thesis"]

    review = {
        "thesis_grade": "B",
        "market_read_grade": "A-",
        "injury_grade": "B+",
        "what_was_right": ["Market moved toward Buffalo."],
        "what_was_wrong": ["Availability timing."],
        "actual_result": "Pending",
        "lessons": ["Track confirmations closer to kickoff."],
    }
    response = client.post("/games/NFL-2026-BUF-KC/reviews", json=review)
    assert response.status_code == 201
    assert response.json()["actual_result"] == "Pending"


def test_dashboard_and_openapi():
    dashboard = client.get("/dashboard")
    assert dashboard.status_code == 200
    assert "Boolin Analyst" in dashboard.text

    response = client.get("/openapi.json")
    assert response.status_code == 200
    spec = response.json()
    for path in (
        "/research-board",
        "/games/{game_id}/research",
        "/games/{game_id}/market-summary",
        "/games/{game_id}/changes",
        "/games/{game_id}/freshness",
        "/games/{game_id}/flags",
        "/games/{game_id}/scenarios",
    ):
        assert path in spec["paths"]
