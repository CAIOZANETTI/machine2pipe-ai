# Task split — Claude and Codex on `main`

Both agents commit directly to `main`. There are no pull requests, so ownership is defined
by **file path**, not by topic. A file has exactly one owner. If you need a change in a file
you do not own, ask its owner instead of editing it.

## Locked decisions

These are settled; do not re-litigate them mid-build.

| Decision | Value | Why |
|---|---|---|
| Package layout | `src/machine2pipe/`, installed via `pyproject.toml` | Already committed, green, and imported by passing tests |
| Dashboard entrypoint | `app/streamlit_app.py` | Referenced by `start.sh` and `railway.toml` |
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
| `app/streamlit_app.py` | first version done |
| `src/machine2pipe/geo/project_loader.py` | KML/KMZ parsing, segment attributes |
| `src/machine2pipe/geo/matching.py` | nearest segment, corridor, distance to axis |
| `src/machine2pipe/geo/stationing.py` | chainage along the alignment |
| `src/machine2pipe/events.py` | deterministic event rules |
| `src/machine2pipe/storage.py` | SQLite schema, reads and writes |
| `src/machine2pipe/replay.py` | telemetry replay engine |
| `src/machine2pipe/weather.py` | Open-Meteo archive |
| `scripts/make_demo_kml.py` | provisional KML over the real 28/06 route |
| `tests/test_adapter_*.py`, `test_geo_*.py`, `test_events_*.py` | |

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

- `events.detect(window) -> list[Event]` — Claude produces; Codex consumes. An `Event` carries
  `event_id`, `event_type`, `timestamp`, `machine_id`, `segment_id`, `chainage_m`,
  `distance_to_axis_m`, `engine_on`, `dwell_minutes`, `movement_m`, and `context`.
- `storage` — Claude owns the schema and the write functions for telemetry, events and photo
  evidence. Codex calls `storage.record_confirmation(...)` to persist an engineer reply;
  Codex does not write SQL.
- `tools.py` — Codex defines the tool surface the model sees, and each tool calls an existing
  deterministic function. No tool computes geometry or quantities on its own.
- `config.py` — Claude owns it. Need a new setting? Ask; do not edit.

## Working rules

1. `git pull --rebase origin main` immediately before every push.
2. Never edit a file you do not own.
3. Small, frequent commits — a short collision window is the only real protection here.
4. Run the tests that cover what you touched before pushing.
5. Add a row to `docs/CONTRIBUTIONS.md` in the same commit.
6. Never force-push, reset, or revert the other agent's work.
7. Cross review: each agent reviews the other's commits and leaves the review as a comment on
   the commit on GitHub, naming what was checked and what was found.

## Order of work

Neither half blocks the other at the start.

- Codex can build the Telegram bot and the photo/EXIF pipeline immediately — they depend on
  nothing from the geospatial side.
- Claude delivers KML parsing, matching, chainage, events and storage.
- The two halves meet at `events.detect()` feeding the agent, and at
  `storage.record_confirmation()` writing the engineer's reply.
