# Boolin Analyst

A research-first sports analysis API built on top of the Boolin data layer.

## What this repo does

Boolin Analyst turns normalized sports data into an analyst workflow:

- Game Research Cards
- Market open/current/close tracking
- Model vs market comparison
- Change timelines
- Research flags
- Data freshness/provenance
- Scenario analysis
- Analyst notes
- Postgame review/grading
- Daily research board

This project is intentionally separate from the production `boolin` data pipeline.

## Architecture

```
Boolin data / normalized snapshots
              |
              v
        Analyst Store
              |
              v
       Research Engine
              |
              v
          FastAPI
              |
              +--> OpenAPI / Swagger
              +--> research board
              +--> game research cards
              +--> analyst notebook
```

## Run locally

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload
```

Open:

- http://127.0.0.1:8000/docs
- http://127.0.0.1:8000/openapi.json

Run tests:

```bash
pytest -q
```

## Data contract

The service consumes generic normalized game snapshots. The production Boolin repository can later feed this layer through an adapter instead of duplicating sports-source logic.

Environment:

```
ANALYST_DB_PATH=data/analyst.db
BOOLIN_SNAPSHOT_DIR=data/snapshots
```

## Design principles

1. Never silently treat partial data as complete.
2. Keep confirmed, projected, and derived values separate.
3. Never invent causality for a detected market/model change.
4. Historical market snapshots are append-only from the analyst layer's perspective.
5. Research flags explain why they fired.
6. A lean/pass/watch conclusion is allowed; the system does not force a bet.
