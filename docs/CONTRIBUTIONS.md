# Contributions

Machine2Pipe AI is led and technically validated by Caio Zanetti, with AI-assisted software development. This log separates product ownership, prior work, and implementation contributions.

## Contributors

| Contributor | Role | Contributions |
|---|---|---|
| Caio Zanetti | Project lead and civil engineer | Product concept, 2022 field experience, real JCB telemetry, Google Earth project, construction photos, engineering rules, historical ground truth, and final technical validation |
| OpenAI Codex | AI coding collaborator | Repository documentation, architecture, implementation backlog, agent coordination rules, technical review, integration support, and future code contributions |
| Anthropic Claude | AI coding collaborator | Platform, data, deployment, geospatial, or other implementation contributions recorded as commits are completed |

## Contribution log

Add one row for each meaningful code or documentation delivery.

| Date | Contributor | Backlog item | Commit | Files/area | Result |
|---|---|---|---|---|---|
| 2026-09-12 | Caio + Codex | Product planning | Documentation commits | README, implementation plan, AGENTS | Defined MVP, web architecture, real-data inputs, photo workflow, agent boundaries, and V2 roadmap |
| 2026-09-12 | Caio + Claude | P0 — Foundation | `9e0baaf` | Package, config, telemetry adapter, dashboard, Docker/Railway, tests | Scaffold with src layout; JCB 2022 adapter validated against the real Parquet (raio_m confirmed as displacement, MAE 0.13 m); demo day pinned to 2022-06-28; Streamlit plotting the real track; single-service deploy config; 5 passing tests |
| 2026-09-12 | Caio + Claude | P2 — Geospatial engine | `pending` | geo/project_loader, geo/matching, geo/stationing, scripts/make_demo_kml | KML/KMZ parser reading ExtendedData, `key: value` descriptions and a CSV fallback, since Google Earth Web exports neither; segment matching with chainage and distance to axis in EPSG:31982; provisional 7-segment alignment derived from the real 28/06 route; 12 passing tests |
| 2026-09-12 | Caio + Claude | P2 — Events and storage | `pending` | events.py, storage.py, app/streamlit_app.py | Deterministic event rules firing once per episode; dwell measured as time within a radius rather than point-to-point movement; SQLite with WAL, idempotent event writes and a confirmation record that refuses any quantity without a human source; 20 passing tests |
| 2026-09-12 | Caio + Codex | Telegram and photo ingestion | this commit | `worker.py`, Telegram client, EXIF pipeline, tests | Added long polling, bot commands, chat allowlist, photo/document download, safe storage, conservative EXIF handling, and six new tests |
| 2026-09-12 | Caio + Claude | P2 — Panel and replay | `pending` | api.py, replay.py, web/index.html, start.sh | Streamlit replaced by a FastAPI service rendering the panel and the API from one Railway service, removing the need to share a database across two clouds; replay clock with start/pause/reset and jump-to-event for recording; validated three-hue palette with light and dark modes; 26 passing tests |

## Attribution rules

- Credit the human source of field data and engineering decisions.
- Credit each AI system only for work it actually produced.
- Record the commit after it exists; do not claim prospective work as completed.
- Caio remains responsible for accepting engineering interpretations and the final project submission.
- API providers and hackathon sponsors are tools or supporters, not software contributors unless they directly contribute work.
