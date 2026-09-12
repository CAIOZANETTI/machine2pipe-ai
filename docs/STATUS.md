# Status — 2026-09-12 15:10 BRT

Submission closes **2026-09-13 03:00 BRT** (12/09 23:00 PDT). About **11h50** remain.

`main` at `52174c9`. 41 tests passing. Deployed and serving at
`https://machine2pipe-ai-production.up.railway.app`.

## The chain, link by link

The definition of done in `README.md` is one chain. Six of its nine links work on real data.

| # | Link | State | Owner |
|---|---|---|---|
| 1 | Real Parquet → canonical telemetry | **done** — 78,365 rows, schema audited | Claude |
| 2 | KML → segments with attributes | **done** — 7 provisional segments; the real export is pending | Claude / Caio |
| 3 | Photo → segment and chainage | **done** — 6 album photos matched by capture time | Claude |
| 4 | Deterministic event | **done** — 29 on the demo day, reproducible | Claude |
| 5 | Agent decision (ignore/log/notify/ask) | **missing** | Codex |
| 6 | Question sent in Telegram | **partly** — the bot can send; nothing composes a question | Codex |
| 7 | Engineer's reply parsed into a record | **missing** | Codex |
| 8 | Confirmed progress persisted | **done** — `record_confirmation` refuses a quantity with no human source | Claude |
| 9 | Panel updates | **done** — planned against confirmed, per segment | Claude |

So the deterministic half is complete and the agent half is not. In scoring terms that
matters more than the count suggests: links 5 to 7 are what makes this an agent rather than
a dashboard, and they are the hackathon's theme.

## Roughly where we are

| Phase | Complete | What is left |
|---|---|---|
| P0 Foundation | 100% | — |
| P1 Data ingestion | 100% | the real KML from Google Earth (Caio) |
| P2 Engineering engine | 100% | — |
| P3 Telegram and photos | ~70% | vision classification; the bot's own photo→segment call |
| P4 AI agent | ~5% | everything: decision, prompts, tools, reply parsing, Exa |
| P5 Demo | ~20% | video, written description, social post |

Overall: about **70% of the code**, with the remaining 30% concentrated in one place.

## Blocking, in order

1. **Railway variables never reached the container.** `/health` reports
   `telegram_token_configured: false` and `database_path: /app/data/machine2pipe.db`
   instead of `/data`. The three variables are saved in the dashboard but not applied to
   the active deployment, so the bot cannot poll and the database is wiped on every
   deploy. **Caio: redeploy, and mount the volume at `/data`.**
2. **No model key.** `/health` reports `model_key_configured: false`. The agent cannot
   run without `OPENAI_API_KEY` or `OPENROUTER_API_KEY`. **Caio.**
3. **`agent.py` and `tools.py` do not exist.** This is the critical path. **Codex.**
4. **The real KML.** The provisional alignment works; swapping the file is instant.
   **Caio.**

## What Codex can rely on, already deployed

```
GET  /api/events/pending            queue of events already reached in simulated time
                                    and not yet handled by the agent
GET  /api/state                     replay clock, machine, segments, events, photos, weather
POST /api/replay/start|pause|reset
POST /api/replay/jump/{event_id}    jump the clock straight to an event
GET  /health                        which secrets reached the container

storage.pending_events(until=...)          the same queue, in-process
storage.record_agent_action(...)           clears the event from the queue
storage.record_confirmation(...)           the only way a quantity is persisted
storage.confirmed_progress()               totals per segment, for the panel
events.detect(...)                         deterministic rules, pure function
weather.fetch(day, lat, lon)               rain context with its limits declared
```

The event contract is in `docs/TASK_SPLIT.md`. Nothing in the agent layer needs to compute
geometry, distance, chainage or totals — all of it already exists and is tested.

## Facts that constrain the demo

- **It did not rain on 2022-06-28.** Open-Meteo, queried from the deployed service, gives
  0.0 mm and 7.8 to 19.0 °C. The rain phrasing in the README example cannot be used for
  this day. The narrative the data supports: an 11.9 h shift, three photographs at 12:59,
  13:01 and 15:27, DN400 concrete planned, and nothing confirmed.
- **The strongest trigger is `progress_unconfirmed`**, which fires four times on the real
  day, one per segment worked. `long_dwell` does not fire: the longest engine-on stay
  within 20 m is 25 minutes, and within 50 m it is 45. Whether a trench work station
  spans 50 m is an engineering call for Caio, not a number to tune until an event appears.
- **Photos are matched by time, not by GPS**, because Telegram strips EXIF from images sent
  as photos. Where GPS survives it agrees with the machine to within 20 to 53 m.

## Two open review findings

In `docs/REVIEWS.md`, both on the Codex side: the chat allowlist fails open when
`TELEGRAM_CHAT_ID` is unset, which is the live state of the deployed bot; and two documents
sharing a filename overwrite each other in `PhotoStore`.
