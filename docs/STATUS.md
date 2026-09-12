# Status — 2026-09-12 16:15 BRT

Submission closes **2026-09-13 03:00 BRT** (12/09 23:00 PDT). About **10h45** remain.

`main` at `ba64dc4`. 86 tests passing. Deployed at
`https://machine2pipe-ai-production.up.railway.app`.

## The chain, link by link

The definition of done in `README.md` is one chain. All nine links now exist in code; three
of them have never run in production, because the variables they need are not in the
container yet.

| # | Link | State | Evidence |
|---|---|---|---|
| 1 | Real Parquet → canonical telemetry | **done** | 78,365 rows, schema audited |
| 2 | KML → segments with attributes | **done** | the real Google Earth export is now the default: one 255.06 m DN400 alignment, four reference points |
| 3 | Photo → segment and chainage | **done** | `ingest.py`; a Telegram photo is now recorded and matched, not only the seeded album |
| 4 | Deterministic event | **done** | 18 on the demo day with the real KML, reproducible |
| 5 | Agent decision (ignore/log/notify/ask) | **code done, unproven live** | `agent.py`, floor rule + model |
| 6 | Question sent in Telegram | **code done, unproven live** | `worker.FieldAgent.handle_event` |
| 7 | Engineer's reply parsed into a record | **code done, unproven live** | `agent.read_reply`, quantity only if the digits are in the reply |
| 8 | Confirmed progress persisted | **done** | `record_confirmation` refuses a quantity with no human source |
| 9 | Panel updates | **done** | planned against confirmed, per segment |

Links 5 to 7 run end to end in `tests/test_ingest_worker.py` and in a local smoke run over
the real day: event `evt_2022-06-28_018` (`progress_unconfirmed`) produced the question
*"A maquina trabalhou em tubo_concreto_40 e nada foi confirmado ate agora. Quantos metros
de tubo foram assentados nesse trecho?"*, and the reply *"assentamos 42 m de tubo hoje"*
became 42 m confirmed against 255 m planned, signed `telegram:<id>` and tied to that
`event_id`. What has not happened yet is the same run against the deployed service.

## Roughly where we are

| Phase | Complete | What is left |
|---|---|---|
| P0 Foundation | 100% | — |
| P1 Data ingestion | 100% | — |
| P2 Engineering engine | 100% | — |
| P3 Telegram and photos | 100% | — |
| P4 AI agent | ~85% | Exa research tool; audit log shown on the panel |
| P5 Demo | ~20% | the live run, the video, the written description, the social post |

## Tested against production (`ca91548`), 2026-09-12 ~17:30 BRT

| Part | Result |
|---|---|
| Deploy | `/health` at `ca91548`, real KML, 18 events, 6 album photos in the database |
| Telemetry + replay | jump to `evt_013` → 14:37 on site, machine at chainage 126.5 m, engine on, 175 points, 7.5 h shift, 13 events reached |
| Behaviour reading | 3h29 at the front so far; the 12:57–14:10 front at 114–153 m carries both photographs |
| Photos | two visible at 14:37 (12:59 and 13:01, chainage 114 m); `/api/photo/<id>` serves JPEG, ~3 MB each |
| Telegram token | accepted, no webhook, bot answers `/start` and `/whoami` |
| Telegram evidence and agent question | **not testable**: `TELEGRAM_CHAT_ID` missing, so evidence is refused and the agent has nowhere to ask |
| Model | **not testable**: `OPENROUTER_API_KEY` missing; `/api/agent/check` says so |
| Exa | not used anywhere: no key, no module, no call |

## Blocking, in order

1. **Three variables are not in the container.** `/health` reports `TELEGRAM_CHAT_ID`,
   `OPENROUTER_API_KEY` and `LLM_MODEL` missing. Without the first, the bot now refuses to
   record evidence — deliberately, and it says so in the chat — and the agent has no chat
   to ask questions in. Without the second, every decision falls back to the deterministic
   rule: the loop still works, but nothing in it is AI. **Caio:**

   ```text
   TELEGRAM_CHAT_ID=7161087185
   OPENROUTER_API_KEY=<chave do OpenRouter, US$ 5 em creditos>
   LLM_MODEL=google/gemini-2.5-flash
   ```

2. **The live run has not been done.** After the redeploy: `/api/agent/check` must answer
   `model_answers: true`, then `POST /api/replay/start`, then the question must arrive in
   Telegram and the reply must show up on the panel. Until that sequence runs once, links
   5 to 7 are code, not a demonstration.
3. **The video, the description and the social post.** **Caio.**

## What the deployed service answers

```
GET  /health                        which secrets reached the container, and now also
                                    the model in use, the project file and how many
                                    agent decisions and confirmations exist
GET  /api/agent/check               asks the model whether it answers, without revealing
                                    the key: separates no key, refused key, no credit and
                                    a loop that simply is not running
GET  /api/telegram/check            the same for the bot: token, webhook, pending updates
GET  /api/events/pending            the agent's queue
GET  /api/state                     replay clock, machine, segments, events, photos, weather
POST /api/replay/start|pause|reset
POST /api/replay/jump/{event_id}
```

## Driving the demo without waiting

At 60× the morning takes seven real minutes before anything happens, and a presentation
cannot wait. The panel now offers the day's moments as shortcuts: a strip under the
progress bar with every event that speaks (⏳ ⚠ ◌) and every photo (📷), each a click
away; every event in the timeline and every photo in the gallery is clickable too, and
the clock lands on that instant with the machine where it was. ⏭ jumps to the next event,
⏩ to the end of the day, and the speed selector offers 60×, 180× and 600×. Under the hood
it is `POST /api/replay/seek?at=<instant>`.

The agent is no longer invisible on the panel: the conversation card says which model is
behind it and what it does and does not do, and every photo without a reading has a
**🔎 Ler com o modelo** button that runs the vision reading live (`POST
/api/photo/{id}/read`) and shows class, confidence and one sentence — the way to test the
AI in front of an audience.

## The reading Caio asked for

The KML support points now drive a deterministic behaviour reading (`activity.py`): each
instant is front of work, transit, at the yard, at the borrow pit, refuelling, stopped or
off, from position in the project, engine state and displacement. The signature of pipe
laying is unmistakable in the real telemetry: the machine holds the same chainage for
an hour with the engine cycling every two or three minutes while the crew positions the
pipe. On 2022-06-28 that reads as **5h06 at the front** (68–96 m in the morning, 114–164 m
in the afternoon), 3h03 at the yard, 53 min at the borrow pit, 2h10 in transit; the fuel
station was never closer than 213 m. The 12:59 and 13:01 photographs fall inside the
12:57–14:10 front at chainage 114–153, which is what turns "the machine was there" into
"the machine was executing there". The quantity still comes from the engineer.

## Facts that constrain the demo

- **It did not rain on 2022-06-28.** Open-Meteo gives 0.0 mm and 7.8 to 19.0 °C. The rain
  phrasing in the README example cannot be used for this day. The narrative the data
  supports: an 11.9 h shift on a 255 m DN400 alignment, three photographs at 12:59, 13:01
  and 15:27, and nothing confirmed until the engineer answers.
- **`progress_unconfirmed` is the trigger that carries the demo.** With the real KML it
  fires once, at the end of the working day, which is exactly the question worth asking.
  `long_dwell` does not fire: the longest engine-on stay within 20 m is 25 minutes.
- **Photos are matched by time, not by GPS**, because Telegram strips EXIF from images sent
  as photos. A photo taken today has no 2022 telemetry to match, so it is anchored to the
  replay clock and `received_at` keeps the real instant.
- **The model never produces a quantity.** It may only extract digits the engineer wrote.
  A number that is not in the reply text is discarded, and the confirmation is recorded
  without a quantity rather than with an invented one.
