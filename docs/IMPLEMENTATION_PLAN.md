# Machine2Pipe AI — Implementation Plan

This file is the execution backlog for humans and coding agents.

## Product decision

The MVP runs on the web. GitHub stores the source; Railway runs Streamlit and the always-on worker; a persistent volume stores SQLite, the active KML/KMZ, and field photos.

## Delivery strategy

### Release targets

| Release | Goal | Success signal |
|---|---|---|
| Hackathon MVP | Prove one complete real-data workflow | Telemetry + KMZ + photo + Telegram confirmation |
| Company pilot | Run with one active project and real users | Daily use with auditable records |
| V2 platform | Support multiple projects, machines, and OEM feeds | Second equipment adapter without changing the core |

### Scope priority

**Must have**

- public Streamlit dashboard;
- real JCB Parquet replay;
- exported KML/KMZ project;
- deterministic machine-to-segment matching;
- Telegram photo reception;
- one vision classification;
- one agent question and engineer confirmation;
- persistent auditable result.

**Should have**

- historical rain and elevation context;
- daily summary;
- Exa technical-research tool;
- comparison with the historical field record.

**Not in the hackathon MVP**

- multiple OEM integrations;
- automatic installed-length measurement;
- survey-grade depth measurement;
- full authentication and enterprise permissions;
- autonomous machine control.

### Parallel workstreams

| Workstream | Owner | Files/area | Dependency |
|---|---|---|---|
| Platform and deployment | Agent A | Docker, Railway, config, storage | None |
| Data and geospatial | Agent A | Parquet, KMZ, matching, events | Project file |
| Telegram and photos | Agent B | Bot, EXIF, image storage | Storage contract |
| Vision and agent | Agent B | Model, tools, Exa, prompts | Event contracts |
| Engineering validation | Caio | KMZ, thresholds, historical records | Working outputs |
| Integration and demo | Shared | Replay, dashboard, end-to-end test | All must-have items |

Agents must follow `AGENTS.md` and avoid editing the same module concurrently.

### Integration gates

| Gate | Required result |
|---|---|
| G0 — Online | Streamlit URL and worker are running |
| G1 — Data | Parquet and KMZ load with validated schemas |
| G2 — Geometry | Machine is matched to a segment and chainage |
| G3 — Evidence | Telegram photo is stored and matched |
| G4 — Agent | Model asks for missing field confirmation |
| G5 — Proof | Reply updates SQLite and dashboard |
| G6 — Demo | Historical run completes reproducibly |

Do not start the next gate if the previous gate cannot be demonstrated.

### Suggested 24-hour build window

| Time | Target |
|---|---|
| Hours 0–3 | G0: repository scaffold and Railway deployment |
| Hours 3–7 | G1: Parquet and KMZ ingestion |
| Hours 7–11 | G2: map, distance, segment, and chainage |
| Hours 11–15 | G3: Telegram and photo metadata |
| Hours 15–19 | G4: vision model, agent tools, and Exa |
| Hours 19–22 | G5: persistence and dashboard update |
| Hours 22–24 | G6: tests, fallback demo, README, and video |

If time becomes constrained, remove should-have items before touching the complete evidence-to-confirmation loop.

## Definition of the MVP

A judge can:

1. open the public dashboard;
2. upload or select the demonstration KML/KMZ;
3. start a replay of the real 2022 JCB telemetry;
4. observe the machine matched to a project segment;
5. send a historical field photo to Telegram;
6. see the photo matched by time and location;
7. receive an agent question;
8. reply with executed quantity or interruption reason;
9. see the confirmed record on the dashboard.

## Inputs

| Input | Source | MVP handling |
|---|---|---|
| Telemetry | `gps_maquina/data/silver_jcb_relatorio_2022.parquet` | URL/download adapter |
| Pipe project | Google Earth KML/KMZ | Streamlit upload |
| Photos | Telegram | Store original file and metadata |
| Engineer reply | Telegram text | Validate and persist |
| Weather/elevation | External APIs | Cache structured response |
| Technical research | Exa API | Call only when explicitly useful |

## Outputs

| Output | Destination |
|---|---|
| Current machine and segment | Streamlit + Telegram |
| Structured operational event | SQLite |
| Photo evidence record | SQLite + dashboard |
| Question requiring confirmation | Telegram |
| Confirmed progress | SQLite + dashboard |
| Daily summary | Telegram + dashboard |
| Technical research with sources | Telegram/dashboard |

## Data contracts

### Telemetry point

```json
{
  "machine_id": "JCB-3CX",
  "timestamp": "2022-06-28T13:01:00-03:00",
  "latitude": -26.5988,
  "longitude": -51.1008,
  "engine_on": true,
  "event_type": "raw_event"
}
```

### Photo evidence

```json
{
  "photo_id": "20220628_130132",
  "captured_at": "2022-06-28T13:01:32-03:00",
  "latitude": -26.5988,
  "longitude": -51.1008,
  "segment_id": "TR-04",
  "chainage_m": 182.5,
  "distance_to_segment_m": 4.2,
  "telemetry_delta_seconds": 32,
  "visual_class": "pipe_installation",
  "confidence": 0.86,
  "requires_confirmation": true
}
```

### Confirmed progress

```json
{
  "event_id": "evt_001",
  "segment_id": "TR-04",
  "confirmed_length_m": 18,
  "status": "partially_completed",
  "interruption_reason": null,
  "confirmed_by": "telegram_user_id",
  "confirmed_at": "2022-06-28T17:40:00-03:00"
}
```

## Execution backlog

### P0 — Foundation

- [ ] Scaffold Python package and tests.
- [ ] Add `requirements.txt`, `.env.example`, and `.gitignore`.
- [ ] Add Dockerfile and Railway start configuration.
- [ ] Create SQLite schema and migrations/initialization.
- [ ] Add health/status logging.
- [ ] Deploy empty dashboard and worker.

**Acceptance:** public Streamlit URL loads and worker remains active.

### P1 — Data ingestion

- [ ] Inspect the real Parquet schema.
- [ ] Implement JCB 2022 adapter.
- [ ] Export and validate the Google Earth project as KMZ.
- [ ] Parse LineStrings, Points, and ExtendedData.
- [ ] Plot project and telemetry on the same map.

**Acceptance:** one telemetry point is displayed and matched to a visible project geometry.

### P2 — Engineering engine

- [ ] Select metric CRS.
- [ ] Implement nearest-segment matching.
- [ ] Implement chainage.
- [ ] Reconstruct engine/movement windows.
- [ ] Add configurable event rules.
- [ ] Add weather and elevation enrichment.
- [ ] Persist deterministic events.

**Acceptance:** repeated runs produce the same events.

### P3 — Telegram and photos

- [ ] Create bot with BotFather.
- [ ] Implement long polling in `worker.py`.
- [ ] Receive text, location, photo, and document messages.
- [ ] Store the highest-quality original available.
- [ ] Extract EXIF timestamp and GPS.
- [ ] Request location when GPS is absent.
- [ ] Match photo to project and telemetry.
- [ ] Show evidence in Streamlit.

**Acceptance:** a Telegram photo appears on the correct segment with provenance.

### P4 — AI agent

- [ ] Connect one vision/language model.
- [ ] Define structured vision output.
- [ ] Define agent actions: ignore, log, notify, ask.
- [ ] Expose approved deterministic Python tools.
- [ ] Parse engineer replies.
- [ ] Record human-confirmed progress.
- [ ] Add Exa Agent/Search as an optional research tool.
- [ ] Add prompt and tool-call audit logs.

**Acceptance:** the agent asks a relevant question and records the validated reply without inventing quantity.

### P5 — Historical validation and demo

- [ ] Replay selected construction days.
- [ ] Load the historical photos.
- [ ] Keep the original field records as evaluation ground truth.
- [ ] Compare reconstructed events against ground truth.
- [ ] Report segment match rate, photo match rate, false alerts, and confirmations required.
- [ ] Prepare a two-minute reproducible demo.

**Acceptance:** the demo completes the full evidence-to-confirmation loop.

### P6 — V2 company platform

This phase begins only after the hackathon MVP is validated.

- [ ] Define a vendor-neutral telemetry adapter interface.
- [ ] Add a machine registry with equipment class and manufacturer.
- [ ] Support multiple concurrent machines and projects.
- [ ] Add adapters for JCB, Caterpillar, Komatsu, and generic GPS/CSV/API feeds.
- [ ] Replace SQLite/local photos with PostgreSQL and object storage.
- [ ] Add authentication, roles, and project-level permissions.
- [ ] Add live ingestion through APIs, webhooks, or scheduled connectors.
- [ ] Configure operational rules by equipment class.
- [ ] Add audit history and management reports.
- [ ] Run a pilot with one active company project.

**Acceptance:** at least two different equipment sources use the same canonical event pipeline without changing the engineering engine.

## Immediate next actions

1. Caio exports the Google Earth project as KML/KMZ and makes the historical field record available as evaluation ground truth.
2. Agent A implements P0 and publishes the first Railway URL.
3. Agent A audits the real Parquet and freezes the canonical telemetry schema.
4. Agent B starts Telegram only after the storage and event contracts exist.
5. Both agents integrate at G3; no parallel redesign of shared schemas.

## Non-negotiable guardrails

- GPS proximity is evidence of activity, not proof of installed quantity.
- A photo classification is probabilistic and must include confidence.
- Depth is not reported as measured without a valid scale/reference.
- Original inputs remain immutable.
- Every confirmed quantity records its human source.
- API keys and Telegram tokens never enter Git.
- Exa credits do not pay for the vision/language model.

## Current external assets

- Telemetry: https://github.com/CAIOZANETTI/gps_maquina
- Machine2Pipe repository: https://github.com/CAIOZANETTI/machine2pipe-ai
- Photo album: https://photos.app.goo.gl/Bw5BuCvfpGf4eskXA
- Google Earth project: https://earth.google.com/earth/d/1AxktfRe0YqqKtn-7T0XMgNEnYQQTGYa8?usp=sharing
- KML references:
  - https://github.com/CAIOZANETTI/kml_saneamento
  - https://github.com/CAIOZANETTI/kml-earthworks
