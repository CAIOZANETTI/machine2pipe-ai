# Machine2Pipe AI — Implementation Plan

This file is the execution backlog for humans and coding agents.

## Product decision

The MVP runs on the web. GitHub stores the source; Railway runs Streamlit and the always-on worker; a persistent volume stores SQLite, the active KML/KMZ, and field photos.

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
