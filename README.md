# Plant-Level Productivity & Ops Dashboard — backend

FastAPI + SQLAlchemy + Postgres. Two layers:

- **CRUD API** (`/api/v1/plants`, `/machines`, `/machine-runs`, `/time-logs`, …) —
  one router per entity, for whatever writes into the system.
- **Dashboard API** (`/api/v1/dashboard/…`) — one read call per dashboard screen,
  composing those entities into the three levels the frontend renders.

## Running it

```bash
python -m venv .venv
.venv/Scripts/pip install -r requirements.txt     # Linux/macOS: .venv/bin/pip
cp .env.example .env

docker compose up -d                              # Postgres on :5432
.venv/Scripts/python -m alembic upgrade head
.venv/Scripts/python -m scripts.seed_demo --days 60 --reset
.venv/Scripts/python -m uvicorn app.main:app --reload --port 8000
```

Interactive docs at `/docs`. Tests:

```bash
createdb plant_ops_dashboard_test   # or: docker exec plant_ops_db \
                                    #   psql -U plantops -d postgres \
                                    #   -c "CREATE DATABASE plant_ops_dashboard_test"
.venv/Scripts/python -m pytest
```

Set `CORS_ORIGINS` for wherever the dashboard is served from (comma-separated;
defaults to the Vite dev server).

## Demo data

`scripts/seed_demo.py` simulates a plant rather than hand-writing rows, so every
derived number — yield, U×R×Q, the Paretos, parameter drift — comes out of the
same arithmetic a real plant would produce. It models the things that make the
dashboard worth looking at:

- Paper waste around 12%, split across the stages that cause it.
- Boarding as the pacemaker: its stops starve printing, printing's stops starve
  bundling, written as genuinely overlapping time logs — which is what lets
  Level 3 name a starvation event's upstream cause.
- Monsoon months running measurably worse on moisture, warp and yield, so the
  season-adjusted bands have something to prove themselves against.
- Roll temperature drifting out of band on some shifts, so the drift alert has
  something real to catch.

**The seed generates up to the current clock time**, which is what gives the
status line a machine genuinely mid-run. Re-run it if the demo has been sitting
for more than about twenty minutes, or the status line will correctly report a
stale feed as grey.

## The dashboard endpoints

| Endpoint | Screen |
|---|---|
| `GET /dashboard/plants/{id}/overview?range=` | Level 1 — status line, four rollups, flight path, waterfall, alerts |
| `GET /dashboard/plants/{id}/trends?days=` | 30-day lines with target bands |
| `GET /dashboard/plants/{id}/stages/{stage}?range=` | Level 2 — context row, KPI cards, two charts, stage alerts |
| `GET /dashboard/plants/{id}/stages/{stage}/specifics?range=` | Level 3 — hour rows, causes + event log, parameters |
| `GET /dashboard/plants/{id}/alerts?level=` | live alerts, ranked by ₹ impact |
| `POST /dashboard/plants/{id}/alerts/acknowledge` | take ownership of a drift alert |
| `GET /dashboard/plants/{id}/reason-picker` | reason-code catalog for classifying a stop |

`range` is `today` / `week` / `month` / `custom` (with `date_from` and
`date_to`). Every endpoint accepts `as_of` to pin "now", which is how the tests
assert against a known instant.

## Where the logic lives

```
app/services/dashboard/
  ranges.py    the time selector: window resolution and the comparison rule
  bands.py     targets, red lines, RAG verdicts, monsoon bands
  facts.py     every day-grained aggregate over the fact tables
  status.py    live machine state (the one thing that ignores the selector)
  plant.py     Level 1
  stage.py     Level 2
  specifics.py Level 3
  alerts.py    the alert engine
```

Nothing in `facts.py` reads `DailyPlantRollup`. Totals and trends are recomputed
from facts, so a number never depends on whether a rollup job has run, and the
same figure at Level 1 and Level 2 is the same query rather than two definitions
that drift apart.

## Decisions that are easy to undo by accident

- **Plant productivity is corrugator-only.** Boarding is the pacemaker and sets
  the plant's ceiling; averaging U×R×Q across machines produces a number nobody
  owns.
- **A shift in progress is measured against elapsed minutes, not the full
  roster.** Utilisation an hour into a shift would otherwise divide one hour of
  running by eight hours of roster and read red every morning. Both sides are
  clamped — an open interval is truncated at `as_of` too, or utilisation can
  exceed 100%.
- **One job carries two throughput standards.** `Order.standard_speed` is the
  corrugator's, in m/min; `Order.printing_standard_sheets_per_hr` is the
  printer's. Dividing sheets-per-hour by a metres-per-minute figure produced
  efficiencies in the thousands.
- **Cumulative targets scale with the range.** A per-day rupee target judged
  against a month-to-date total paints every month red by the 2nd. Rates and
  percentages do not scale. See `CUMULATIVE_METRICS` in `bands.py`.
- **Alerts are never stored.** They are derived on every read, which is what
  makes "auto-clear when the condition clears" true by construction. Only the
  *acknowledgement* is persisted, matched to a live condition by a deterministic
  `alert_key`.
- **Alert thresholds are constants, not settings** (`down > 15 min`, drift
  escalation at 60 min, a pattern at 3 occurrences). The spec calls for alerting
  never to be a matter of opinion.
- **Alerts are ranked by money, so the money has to be roughly right.** A
  stopped pacemaker is priced per minute at the plant rate; an unstaged order is
  an exposure, capped. Get these wrong and stale paperwork pushes a stopped
  machine off the panel.
- **Grey is not red.** A stale feed produces `no_data`, never `down`.

## Configuration beyond the database

The spec's cost-of-waste formula needs prices, and there is no commercial table
in the data model, so rates are configuration rather than invented data — see
`app/core/config.py` for paper, starch, power, planned-waste percentage, genset
rating, and the alert pricing rates.

Master data required before a real go-live: machine standards by job type,
parameter control bands (with monsoon variants), targets and red lines per KPI,
and the reason-code taxonomy. The seed script sets plausible values for all of
these against one plant.
