# Boolin Analyst

A research-first sports analysis API and dashboard built as a separate layer above the Boolin data pipeline.

## Purpose

This project turns normalized sports data into an analyst workflow:

- Game Research Cards
- Opening/current/closing market tracking
- Market vs model comparison
- Market change timelines
- Research flags
- Data freshness and provenance
- Scenario analysis
- Analyst notes
- Postgame review/grading
- Daily research board

It is intentionally separate from the production `boolin` repository so the research experience can evolve without destabilizing ingestion.

## Run locally

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload
```

Open:

- Dashboard: http://127.0.0.1:8000/
- Swagger UI: http://127.0.0.1:8000/docs
- ReDoc: http://127.0.0.1:8000/redoc
- OpenAPI JSON: http://127.0.0.1:8000/openapi.json

The checked-in contract is `openapi.yaml`.

## Data contract

Set `BOOLIN_GAMES_PATH` to point the analyst service at a normalized Boolin games JSON file. If unset, the demo data at `data/latest/games.json` is used.

Set `ANALYST_DB_PATH` to choose where analyst notes and postgame reviews are stored. SQLite is used by default.

## Research principles

The API keeps confirmed, projected, and derived information separate. It computes research flags dynamically so stale demo metadata cannot hide unresolved conditions.

A change detected in market history is not treated as causally explained unless the source data actually establishes the cause.

Missing data is represented as missing/unknown rather than silently filled.

## Next integration step

The intended production path is:

`boolin` data pipeline → normalized JSON snapshots → Boolin Analyst API → dashboard / other clients.

Do not couple the research layer directly to bookmaker scraping or model-specific assumptions that belong in the upstream data layer.
