# Machine2Pipe AI

**Turning real machine telemetry into explainable pipeline progress.**

Machine2Pipe AI is a field agent for linear construction projects. It combines a georeferenced pipe project with real equipment telemetry, deterministic engineering calculations, terrain elevation, and weather context. When something relevant happens, the agent reaches the field engineer through Telegram, where project communication already happens.

> **Hackathon status:** active prototype for **Agents, Everywhere** by AI Tinkerers. This repository was created for the hackathon. The historical telemetry and reusable engineering components are documented under [Prior work](#prior-work).

## Why this project exists

In 2022, a JCB 3CX backhoe loader generated telemetry while working on pavement and drainage activities. The original analysis could answer where the machine was, when the engine was on, how far it moved, and what its operating routine looked like.

That was useful, but incomplete. Telemetry alone does not know:

- what the project required at that location;
- which pipe segment was planned;
- whether the machine was near the correct work front;
- whether rain could explain a stoppage;
- whether presence represents real production;
- when an engineer should be asked for confirmation.

The original 2022 project already listed weather, activity type, productivity, lessons learned, best practices, and AI-assisted decisions as future steps. Machine2Pipe AI is the continuation of that idea with today's agent capabilities.

## Core idea

The system compares two georeferenced realities:

1. **Planned work** — pipe alignments, structures, quantities, and dates from KML/KMZ.
2. **Observed activity** — timestamped GPS and engine events from a real Parquet telemetry dataset.

Python calculates what can be proven. The AI agent interprets those results, decides whether action is needed, and communicates with the engineer.

**The telemetry shows where the machine was. The project shows what should have been built. The agent connects both realities.**

## What the prototype will demonstrate

- Upload or load a KML/KMZ pipe project.
- Load and normalize the real 2022 JCB telemetry from Parquet.
- Replay historical records as a simulated live operation.
- Match each valid GPS point to the nearest project segment.
- Calculate distance to alignment, chainage, dwell time, movement, and engine state.
- Add terrain elevation and historical weather context.
- Detect deterministic operational events and anomalies.
- Let an OpenAI-powered agent decide whether to ignore, log, notify, or ask.
- Send proactive Telegram messages to the field engineer.
- Convert the engineer's natural-language reply into structured progress data.
- Display the project, machine path, events, and confirmed progress in Streamlit.

## End-to-end workflow

~~~mermaid
flowchart TD
    A["KML/KMZ project"] --> C["Deterministic Python engine"]
    B["Parquet telemetry"] --> C
    W["Elevation and weather APIs"] --> C
    C --> D["Structured field event"]
    D --> E["OpenAI agent"]
    E --> F["Telegram engineer"]
    F --> E
    E --> G["JSONL/CSV progress log"]
    G --> H["Streamlit dashboard"]
~~~

## Engineering and AI boundaries

Machine2Pipe AI intentionally separates deterministic engineering from probabilistic interpretation.

### Python is responsible for

- coordinate validation and normalization;
- CRS transformation and metric distances;
- nearest-segment matching;
- chainage and position along the alignment;
- engine-on and engine-off state reconstruction;
- movement, dwell time, and time-window calculations;
- terrain elevation and weather retrieval;
- rule-based event detection;
- structured records, totals, and progress calculations.

### The AI agent is responsible for

- interpreting a structured event in project context;
- selecting an action: ignore, log, notify, or ask;
- explaining the event in concise field language;
- asking the engineer for missing information;
- extracting quantities and causes from natural-language replies;
- calling approved Python tools to record confirmed information;
- producing shift or daily summaries.

### The AI agent must not

- calculate engineering distances or quantities itself;
- infer installed pipe length only from machine presence;
- present DEM elevation as survey-grade altimetry;
- treat estimated weather as an on-site measurement;
- overwrite confirmed progress without an auditable record;
- send operational commands to equipment.

## Human confirmation is part of the product

Machine presence is evidence of activity, not proof of completed work.

Example deterministic event:

~~~json
{
  "event_id": "evt_2022-04-18_001",
  "machine_id": "JCB-3CX",
  "timestamp": "2022-04-18T14:30:00-03:00",
  "segment_id": "TR-04",
  "planned_service": "Excavation for DN400 drainage pipe",
  "distance_to_alignment_m": 4.8,
  "dwell_minutes": 95,
  "engine_on": true,
  "rain_mm": 12.0,
  "rule": "activity_requires_confirmation"
}
~~~

Possible Telegram message:

> JCB-3CX has remained on segment TR-04 for 1h35. Excavation for DN400 pipe is planned here, and estimated rainfall was 12 mm. Was work completed or interrupted?

Engineer reply:

> We completed 32 meters and stopped because of rain.

Agent tool payload:

~~~json
{
  "segment_id": "TR-04",
  "confirmed_length_m": 32,
  "status": "partially_completed",
  "interruption_reason": "rain",
  "source": "engineer_confirmation"
}
~~~

## Input data

### 1. Machine telemetry

The prototype uses a real JCB 3CX dataset from 2022, stored as Parquet. The adapter will map the historical columns to a small canonical schema.

| Canonical field | Historical source | Required | Description |
|---|---|---:|---|
| `timestamp` | `data_hora` | Yes | Event date and time |
| `latitude` | `lat` or parsed map URL | Yes | WGS84 latitude |
| `longitude` | `lon` or parsed map URL | Yes | WGS84 longitude |
| `event_type` | `atividade` | Yes | Raw equipment event |
| `engine_on` | `motor_ligado` or reconstructed | Yes | Engine state |
| `distance_from_previous_m` | `raio_m` or recalculated | No | Movement between valid points |
| `machine_id` | configuration | No | Equipment identifier |

Raw telemetry remains immutable. Normalized and enriched records are written to a separate output directory.

### 2. Pipe project

The project is supplied as KML or KMZ and may contain lines for pipes and points for structures such as manholes, catch basins, pumping stations, or other assets.

Recommended `ExtendedData` fields for each line segment:

| Field | Example | Purpose |
|---|---|---|
| `segment_id` | `TR-04` | Stable identifier |
| `name` | `Rua A - Rua B` | Human-readable location |
| `service_type` | `drainage_pipe` | Planned activity |
| `diameter_mm` | `400` | Nominal pipe diameter |
| `material` | `concrete` | Pipe material |
| `planned_start` | `2022-04-18` | Planned start date |
| `planned_end` | `2022-04-19` | Planned finish date |
| `planned_length_m` | `300` | Scope quantity |

If attributes are missing, geometry can still be displayed, but the agent will have less project context.

### 3. Elevation and weather

- **Elevation:** Open-Meteo Elevation API with OpenTopoData fallback.
- **Historical weather:** Open-Meteo Archive API using the telemetry coordinates and timestamp.

Elevation and weather are contextual data. They are not a substitute for site surveying or a local rain gauge.

## Deterministic event rules for the MVP

| Rule | Initial condition | Agent behavior |
|---|---|---|
| `entered_segment` | Machine enters the configured corridor | Log context |
| `left_segment` | Machine leaves the corridor | Log duration and movement |
| `outside_project` | Engine on beyond the corridor threshold | Notify or ask |
| `long_dwell` | Engine on with little movement for a configured period | Ask for activity or stoppage |
| `unexpected_segment` | Segment conflicts with the planned date | Notify engineer |
| `gps_gap` | No valid GPS record within the expected interval | Log data-quality alert |
| `rain_context` | Rain overlaps a stoppage or low-activity period | Add context; do not claim causation |
| `progress_unconfirmed` | Relevant activity ends without a field record | Ask for confirmation |

Thresholds will live in configuration, not inside prompts.

## Agent tools

The agent will receive a small set of explicit Python tools:

| Tool | Responsibility |
|---|---|
| `get_machine_status` | Return current deterministic state |
| `get_segment_context` | Return project scope and schedule for a segment |
| `get_weather_context` | Return weather for a location and time |
| `list_recent_events` | Return recent structured events |
| `record_occurrence` | Append an auditable field occurrence |
| `confirm_progress` | Record engineer-confirmed quantities |
| `build_daily_summary` | Produce deterministic daily metrics for explanation |

The model receives structured events rather than the complete Parquet dataset. This keeps prompts small, costs controlled, and calculations reproducible.

## Telegram experience

The Telegram bot is both proactive and conversational.

Planned commands:

| Command | Result |
|---|---|
| `/status` | Current machine, segment, engine state, and last event |
| `/segment` | Planned scope for the active segment |
| `/progress` | Confirmed progress by segment |
| `/summary` | Shift or daily summary |
| `/help` | Available commands and limitations |

During the hackathon, the bot can run locally using long polling. A public webhook and hosted worker are not required for the first demo.

## Replay mode

The source telemetry is historical, but the agent experience will be live.

The replay worker will:

1. sort records by timestamp;
2. advance through the dataset using a configurable speed factor;
3. preserve time intervals and engine transitions;
4. enrich each time window with project and environmental context;
5. emit only meaningful events to the agent;
6. update the dashboard and Telegram as the simulated day progresses.

Replay speed will be configured through `REPLAY_SPEED`, allowing several construction days to be demonstrated in minutes.

## Proposed technology stack

| Layer | Technology |
|---|---|
| Language | Python 3.11+ |
| Data | pandas, PyArrow |
| Geometry | Shapely, PyProj |
| KML/KMZ | lxml or fastkml, zipfile |
| Agent | OpenAI API / OpenAI Agents SDK |
| Messaging | Telegram Bot API, python-telegram-bot |
| Weather/elevation | Open-Meteo, OpenTopoData fallback |
| Interface | Streamlit, Plotly or PyDeck |
| Validation | Pydantic |
| Tests | pytest |
| Prototype persistence | JSONL and CSV |

## Proposed repository structure

~~~text
machine2pipe-ai/
├── app/
│   └── streamlit_app.py
├── src/
│   └── machine2pipe/
│       ├── agent.py
│       ├── config.py
│       ├── events.py
│       ├── replay.py
│       ├── telegram_bot.py
│       ├── tools.py
│       ├── weather.py
│       ├── geo/
│       │   ├── matching.py
│       │   ├── project_loader.py
│       │   └── stationing.py
│       └── telemetry/
│           ├── adapter_jcb_2022.py
│           └── loader.py
├── data/
│   ├── sample/
│   └── output/
├── tests/
├── .env.example
├── .gitignore
├── requirements.txt
├── worker.py
└── README.md
~~~

Real or sensitive files should not be committed unless they are explicitly approved for public release. The public demo should use an authorized sample or anonymized subset.

## Local setup (planned)

~~~bash
git clone https://github.com/CAIOZANETTI/machine2pipe-ai.git
cd machine2pipe-ai

python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

cp .env.example .env
~~~

Windows activation:

~~~powershell
.venv\Scripts\activate
~~~

Environment variables:

~~~dotenv
OPENAI_API_KEY=
TELEGRAM_BOT_TOKEN=
TELEGRAM_CHAT_ID=
REPLAY_SPEED=600
PROJECT_CORRIDOR_M=15
LONG_DWELL_MINUTES=45
~~~

Never commit `.env`, API keys, bot tokens, or private project files.

Planned processes:

~~~bash
# Dashboard
streamlit run app/streamlit_app.py

# Telemetry replay + agent + Telegram long polling
python worker.py
~~~

## MVP build order

- [ ] Create project structure, dependencies, configuration, and tests.
- [ ] Audit and document the real Parquet schema.
- [ ] Build the JCB 2022 telemetry adapter.
- [ ] Add KML and KMZ project loading.
- [ ] Create or validate a demo pipe alignment in the telemetry area.
- [ ] Implement metric CRS selection and point-to-segment matching.
- [ ] Implement engine state, dwell time, and event rules.
- [ ] Add elevation and historical weather enrichment.
- [ ] Implement replay mode and deterministic event output.
- [ ] Build the Streamlit map and event timeline.
- [ ] Create the Telegram bot and basic commands.
- [ ] Add the OpenAI agent with explicit Python tools.
- [ ] Parse engineer replies into confirmed progress records.
- [ ] Add guardrails, logging, and automated tests.
- [ ] Record the two-minute demo and document results.

## MVP definition of done

The hackathon prototype is complete when one reproducible scenario demonstrates that:

1. real telemetry is replayed;
2. the machine is matched to a pipe segment;
3. Python emits a structured event;
4. the agent chooses to contact the engineer;
5. Telegram receives a contextual message;
6. the engineer replies in natural language;
7. the agent calls a tool to record confirmed progress;
8. Streamlit displays the updated result with provenance.

## Prior work

Machine2Pipe AI is a new agent and integration created for the hackathon. It builds on prior public engineering work:

- [gps_maquina](https://github.com/CAIOZANETTI/gps_maquina) — real 2022 JCB 3CX telemetry, GPS normalization, engine events, movement analysis, and Streamlit reports.
- [kml_saneamento](https://github.com/CAIOZANETTI/kml_saneamento) — sanitation KML parsing for linear networks, point assets, project attributes, mapping, elevation, and QA/QC.
- [kml-earthworks](https://github.com/CAIOZANETTI/kml-earthworks) — KML alignment parsing, chainage, terrain elevation, engineering profiles, and deterministic calculations.
- [kml_poligono](https://github.com/CAIOZANETTI/kml_poligono) — KML polygons, DEM elevation, geospatial calculations, and earthworks visualization.

None of those repositories contains the Machine2Pipe AI agent, the Telegram workflow, or the project-to-telemetry integration described here.

## Known limitations

- GPS proximity cannot prove that pipe was installed.
- A backhoe can perform several activities in the same location.
- Historical weather APIs estimate conditions and may differ from the job site.
- Public DEM elevation is not appropriate for final pipe invert or grade control.
- Engine events do not directly measure excavation cycles or bucket production.
- The first adapter is specific to the historical JCB dataset.
- The prototype supports decision assistance, not autonomous equipment control.

## Future directions

- Multiple machines and equipment types.
- Planned-versus-actual schedule integration.
- Operator, fuel, maintenance, and site diary data.
- Statistical anomaly detection alongside deterministic rules.
- Productivity forecasts with uncertainty ranges.
- Voice notes and photo evidence through Telegram.
- Support for MQTT or OEM telematics feeds.
- Survey-grade surfaces and as-built verification.

## Author and team

Built by [Caio Zanetti](https://github.com/CAIOZANETTI), civil engineer and Python developer, as the solo team **Ctrl+Alt+Construct**.

Created for the **Agents, Everywhere** global hackathon by AI Tinkerers.
