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
- Independent second-opinion control layer
- Mutual audit of the primary and independent layers

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

## Market matching rules

A market quote is only compared with the model, or with another quote, when the event, market, **side**, period and
line series all match (`app/matching.py`).

- **Perspective.** `model.perspective` says which team `win_probability` and `projected_spread` are FROM (a team code,
  `home` or `away`). If it is missing or invalid, moneyline/spread comparisons are skipped with a warning instead of
  guessing a side. `projected_spread` must use the same sign convention as market spread lines for that team (BUF +3.5 = 3.5).
- **No-vig fair probability.** Per bookmaker, both sides must be quoted within 15 minutes of each other; the margin is
  then removed proportionally and the books are averaged. Books with a missing side, stale pair or ambiguous snapshots
  are excluded with a stated reason. If no book has a complete pair, the response falls back to the raw implied
  probability and labels it `raw_implied_vig_included`.
- **Movement** is calculated per bookmaker + market + side + period + line series (`independent.movement_records`), with
  statuses `STABLE`, `LINE_ONLY_MOVE`, `PRICE_ONLY_MOVE`, `LINE_AND_PRICE_MOVE`, `INSUFFICIENT_HISTORY`, `UNKNOWN`. Steam and
  reverse-line-movement signals are not computed (they need betting-percentage data).
- **Alternate lines** must carry a `line_id` (the main line is `null`). Two different lines for the same series at the same
  timestamp without a `line_id` are flagged `MARKET_AMBIGUOUS_SNAPSHOTS` and excluded from the fair price.

## Research principles

The API keeps confirmed, projected, and derived information separate. The independent layer does not call the primary research engine; it acts as a market-first control model designed to expose overconfidence and data-quality problems. It computes research flags dynamically so stale demo metadata cannot hide unresolved conditions.

A change detected in market history is not treated as causally explained unless the source data actually establishes the cause.

Missing data is represented as missing/unknown rather than silently filled.

## Next integration step

The intended production path is:

`boolin` data pipeline → normalized JSON snapshots → Boolin Analyst API → dashboard / other clients.

Do not couple the research layer directly to bookmaker scraping or model-specific assumptions that belong in the upstream data layer.


## Dashboard launch URL

Run the API from the repository root:

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python -m uvicorn app.main:app --reload
```

Then open:

**http://127.0.0.1:8000/**

Swagger: **http://127.0.0.1:8000/docs**

On Windows PowerShell, use `.\\.venv\\Scripts\\python.exe -m uvicorn app.main:app --reload`.
