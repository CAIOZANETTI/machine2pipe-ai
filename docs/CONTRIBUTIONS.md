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
| 2026-09-12 | Caio + Claude | P2 — Weather and photo evidence | `pending` | weather.py, scripts/seed_photos.py, api.py, web/index.html | Open-Meteo archive as day context with explicit limits and graceful failure; the album's real photos matched to segment and chainage by capture time against telemetry, with photo GPS as a cross-check (20-53 m agreement on 28/06); photo markers and image serving on the panel; 39 tests |
| 2026-09-12 | Caio + Claude | P0 — Deploy diagnostics | `pending` | start.sh, api.py | The worker is supervised and restarted instead of dying silently behind a green deployment; /health reports whether each secret reached the container, without ever revealing a value, and whether /data is writable |
| 2026-09-12 | Caio + Claude | Documentation alignment | `pending` | README.md, AGENTS.md | README brought in line with the shipped system (FastAPI panel, single service, repository layout, build plan status) and a Verified against the real data section added with the measured audit results |
| 2026-09-12 | Caio + Claude | Agent work queue | `pending` | storage.py, api.py, docs/TASK_SPLIT.md | Pending-event queue for the agent loop, cleared by recording an agent action so a restarted replay never repeats a question; deployment diagnosed from /health (no variable reached the container); Open-Meteo confirms 0.0 mm of rain on the demo day, which rules out the rain phrasing |
| 2026-09-12 | Claude | Cross review | `pending` | docs/REVIEWS.md | Reviewed the Codex Telegram and photo ingestion: allowlist fails open on an unset TELEGRAM_CHAT_ID, which is the live state of the deployed bot, and two documents sharing a filename overwrite each other, losing evidence silently |
| 2026-09-12 | Claude | Status report | `pending` | docs/STATUS.md | Chain-level status: six of nine links working on real data, the three missing ones all in the agent layer; blockers ordered, with the deployed interfaces Codex can build against |
| 2026-09-12 | Caio + Codex | P1 — Real project input | `pending` | `data/project/` | Preserved the original Google Earth KML; added its structured DN400 concrete attributes separately; validated one 255.06 m alignment, four reference points, and 208 of 296 telemetry records within the 25 m corridor |

## Attribution rules

- Credit the human source of field data and engineering decisions.
- Credit each AI system only for work it actually produced.
- Record the commit after it exists; do not claim prospective work as completed.
- Caio remains responsible for accepting engineering interpretations and the final project submission.
- API providers and hackathon sponsors are tools or supporters, not software contributors unless they directly contribute work.
