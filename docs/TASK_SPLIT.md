# Task split — Claude and Codex on `main`

Both agents commit directly to `main`. There are no pull requests, so ownership is defined
by **file path**, not by topic. A file has exactly one owner. If you need a change in a file
you do not own, ask its owner instead of editing it.

## Locked decisions

These are settled; do not re-litigate them mid-build.

| Decision | Value | Why |
|---|---|---|
| Package layout | `src/machine2pipe/`, installed via `pyproject.toml` | Already committed, green, and imported by passing tests |
| Dashboard | `web/index.html` served by `src/machine2pipe/api.py` (FastAPI) | Streamlit was dropped: one Railway service serving the page and the API reads the same SQLite the worker writes, so no bridge between two clouds is needed |
| Hosting | One Railway service running dashboard and worker | The persistent volume mounts to a single service |
| Demo day | `2022-06-28` | 296 telemetry points, 11.9 h shift, and 3 field photos with EXIF GPS |
| Metric CRS | `EPSG:31982` (SIRGAS 2000 / UTM 22S) | The works are in Calmon/SC |
| Thresholds | `src/machine2pipe/config.py` | Never inside a prompt |

Root-level `app.py`, `src/telemetry.py` or any parallel module duplicating the package is
out of scope for both agents.

## Ownership

### Claude — platform, data, geospatial, deployment

| File | State |
|---|---|
| `pyproject.toml`, `requirements.txt`, `Dockerfile`, `start.sh`, `railway.toml` | done |
| `src/machine2pipe/config.py` | done |
| `src/machine2pipe/telemetry/adapter_jcb_2022.py`, `loader.py` | done |
| `src/machine2pipe/api.py`, `web/index.html` | done |
| `src/machine2pipe/replay.py` | done |
| `src/machine2pipe/geo/project_loader.py` | KML/KMZ parsing, segment attributes |
| `src/machine2pipe/geo/matching.py` | nearest segment, corridor, distance to axis |
| `src/machine2pipe/geo/stationing.py` | chainage along the alignment |
| `src/machine2pipe/events.py` | done |
| `src/machine2pipe/storage.py` | done |
| `src/machine2pipe/weather.py` | Open-Meteo archive |
| `scripts/make_demo_kml.py` | provisional KML over the real 28/06 route |
| `tests/test_adapter_*.py`, `test_geo_*.py`, `test_events_*.py` | |

### Ownership change — 2026-09-12, approved by Caio

With the submission window at about eleven hours and `agent.py`, `tools.py` and
`vision.py` still absent, Caio moved the agent layer to Claude. The table below keeps the
original split for the record; the files in it are now Claude's, and Codex should not edit
them without saying so here first. Codex keeps `research_exa.py`, which nothing depends on.

### Codex — interaction, AI, integration

| File | Scope |
|---|---|
| `worker.py` / `src/machine2pipe/worker.py` | the loop: replay tick, polling, agent dispatch |
| `src/machine2pipe/telegram_bot.py` | long polling, commands, sending, chat allowlist |
| `src/machine2pipe/photos.py` | receiving, EXIF, storage |
| `src/machine2pipe/vision.py` | visual classification with confidence |
| `src/machine2pipe/agent.py` | decision: ignore, log, notify, ask; prompts; reply parsing |
| `src/machine2pipe/tools.py` | tool definitions exposed to the model |
| `src/machine2pipe/research_exa.py` | optional Exa lookups |
| `tests/test_agent_*.py`, `test_photos_*.py` | |

### Caio

Google Earth KML export, Telegram `/start` and chat id, API keys in Railway Variables,
video, written description, social post, and acceptance of every engineering interpretation.

## Interfaces between the two halves

Agreed before either side codes against them.

### Deterministic event — Claude produces, Codex consumes

```json
{
  "event_id": "evt_2022-06-28_003",
  "event_type": "long_dwell",
  "timestamp": "2022-06-28T14:30:00-03:00",
  "machine_id": "JCB-3CX",
  "segment_id": "TR-04",
  "chainage_m": 182.5,
  "distance_to_axis_m": 3.2,
  "engine_on": true,
  "moving": false,
  "movement_m": 4.0,
  "dwell_minutes": 95,
  "context": {"rain_mm": 3.2, "planned_diameter_mm": 400, "planned_material": "concrete"}
}
```

`event_id` is what makes the loop auditable: the question sent to the engineer, the reply,
and the confirmed quantity all carry it, so any number on the dashboard can be traced back
to the event that caused it. `event_type` tells the agent which situation it is looking at.
`chainage_m` and `dwell_minutes` are what let the agent write "1h35 near chainage 182 m"
without computing anything itself.

### Agent interpretation — Codex produces

```json
{
  "event_id": "evt_2022-06-28_003",
  "evidence_type": "telegram_photo",
  "activity": "pipe_installation_possible",
  "confidence": 0.78,
  "decision": "ask",
  "message": "A foto parece mostrar assentamento no TR-04. Confirma a execução?"
}
```

`decision` is one of `ignore`, `log`, `notify`, `ask`.

### Confirmed progress — Codex calls, Claude persists

The README and the implementation plan disagreed on this record. This is the settled version.

```json
{
  "event_id": "evt_2022-06-28_003",
  "machine_id": "JCB-3CX",
  "segment_id": "TR-04",
  "confirmed_length_m": 32,
  "status": "partially_completed",
  "interruption_reason": "rain",
  "confirmed_by": "telegram:123456789",
  "source": "telegram",
  "confirmed_at": "2022-06-28T17:40:00-03:00"
}
```

`confirmed_by` records the human, never the model. A quantity with no human source is not
written. Codex calls `storage.record_confirmation(...)`; Codex does not write SQL.

### The agent's work queue — Claude provides, Codex consumes

```
GET /api/events/pending   ->  {"simulated_time": ..., "count": n, "events": [...]}
storage.pending_events(until=...)  ->  the same queue, in-process
storage.record_agent_action(event_id=..., decision=..., message=...)  ->  removes it from the queue
```

An event leaves the queue once an agent action references it, so restarting the replay does
not ask the engineer the same question twice. Only events whose timestamp has already been
reached in simulated time appear.

### Other boundaries

- `tools.py` — Codex defines the tool surface the model sees, and each tool calls an existing
  deterministic function. No tool computes geometry or quantities on its own.
- `config.py` — Claude owns it. Need a new setting? Ask; do not edit.

### Note on the demo day's weather

Open-Meteo, queried from the deployed service, reports **0.0 mm of rain on 2022-06-28**, with
temperatures from 7.8 to 19.0 °C. It was a dry, cold winter day. The rain phrasing in the
README's example message therefore cannot be used for this day — the narrative the data
supports is an 11.9 h shift on TR-06 with three photographs and nothing confirmed.

## Commit convention

```text
feat(claude): add telemetry parquet ingestion
feat(codex): add telegram photo handler
review(codex): validate geospatial output contract
review(claude): validate agent database integration
```

## Scope notes

- The demo project ships as a fixed KML in the repository. Upload through Streamlit is
  optional and last: it needs authentication, and a public dashboard that overwrites the
  active project is a liability during judging.
- Historical rain from Open-Meteo Archive is in scope; it is one keyless call and it carries
  the demo narrative. Terrain elevation is out of scope for the MVP — it adds nothing visible.

## Working rules

1. `git pull --rebase origin main` immediately before every push.
2. Never edit a file you do not own.
3. Small, frequent commits — a short collision window is the only real protection here.
4. Run the tests that cover what you touched before pushing.
5. Add a row to `docs/CONTRIBUTIONS.md` in the same commit.
6. Never force-push, reset, or revert the other agent's work.
7. Cross review: each agent reviews the other's work and records the review in
   `docs/REVIEWS.md`, naming what was checked and what was found. An entry stays until its
   owner resolves or rejects it, with a reason.

## Order of work

Neither half blocks the other at the start.

- Codex can build the Telegram bot and the photo/EXIF pipeline immediately — they depend on
  nothing from the geospatial side.
- Claude delivers KML parsing, matching, chainage, events and storage.
- The two halves meet at `events.detect()` feeding the agent, and at
  `storage.record_confirmation()` writing the engineer's reply.
