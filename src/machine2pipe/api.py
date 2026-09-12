"""API do painel: serve a pagina e o estado do replay, lendo o mesmo SQLite do worker.

Um servico so no Railway: a API e o worker compartilham `/data`, entao o painel mostra
exatamente o que a conversa no Telegram gravou, sem ponte entre nuvens diferentes.
"""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path

import pandas as pd
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, JSONResponse

from machine2pipe import events, replay, storage
from machine2pipe.config import config
from machine2pipe.geo import project_loader
from machine2pipe.geo.matching import SegmentMatcher
from machine2pipe.telemetry import loader

WEB = Path(__file__).resolve().parents[2] / "web"

app = FastAPI(title="Machine2Pipe AI", docs_url="/api/docs")


@lru_cache(maxsize=1)
def _day():
    """Projeto, telemetria casada e eventos do dia. Deterministico, entao vale cache."""
    project = project_loader.load(config.project_kml_path, config.segments_csv_path)
    matcher = SegmentMatcher(project, config.target_crs, config.corridor_m)
    matched = matcher.match_frame(loader.load_day(config.replay_date))
    detected = events.detect(
        matched,
        machine_id=config.machine_id,
        long_dwell_minutes=config.long_dwell_minutes,
        dwell_movement_m=config.dwell_movement_m,
        gps_gap_minutes=config.gps_gap_minutes,
        outside_project_minutes=config.outside_project_minutes,
        project=project,
    )
    storage.initialize()
    storage.record_events(detected)
    return project, matched, detected


@app.on_event("startup")
def _warm() -> None:
    _day()


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "replay_date": config.replay_date}


@app.get("/")
def index() -> FileResponse:
    return FileResponse(WEB / "index.html")


def _segments_payload(project) -> list[dict]:
    return [
        {
            "segment_id": segment.segment_id,
            "name": segment.attributes.get("name", segment.name),
            "coordinates": [[lat, lon] for lon, lat in segment.coordinates],
            "planned_length_m": float(segment.attributes.get("planned_length_m") or 0),
            "diameter_mm": segment.attributes.get("diameter_mm"),
            "material": segment.attributes.get("material"),
        }
        for segment in project.segments
    ]


@app.get("/api/state")
def state() -> JSONResponse:
    project, matched, detected = _day()
    day_start, day_end = matched.timestamp.iloc[0], matched.timestamp.iloc[-1]
    now = replay.simulated_now(day_start, day_end)

    elapsed = matched[matched.timestamp <= now]
    current = elapsed.iloc[-1] if len(elapsed) else matched.iloc[0]
    engine_on = elapsed[elapsed.engine_on] if len(elapsed) else elapsed

    confirmed = storage.confirmed_progress()
    confirmed_by_segment = (
        dict(zip(confirmed.segment_id, confirmed.confirmed_length_m)) if not confirmed.empty else {}
    )

    photos = storage.photos_frame()
    clock = replay.load()

    return JSONResponse(
        {
            "replay": {
                "status": clock.status,
                "speed": clock.speed,
                "date": config.replay_date,
                "simulated_time": now.isoformat(),
                "day_start": day_start.isoformat(),
                "day_end": day_end.isoformat(),
                "progress": round(
                    (now - day_start).total_seconds() / max(1, (day_end - day_start).total_seconds()), 4
                ),
            },
            "machine": {
                "machine_id": config.machine_id,
                "latitude": float(current.latitude),
                "longitude": float(current.longitude),
                "engine_on": bool(current.engine_on),
                "segment_id": current.segment_id if current.inside_corridor else None,
                "chainage_m": float(current.chainage_m) if current.inside_corridor else None,
                "distance_to_axis_m": float(current.distance_to_axis_m)
                if current.distance_to_axis_m is not None
                else None,
                "event_type": current.event_type,
                "shift_hours": round(
                    (engine_on.timestamp.max() - engine_on.timestamp.min()).total_seconds() / 3600, 1
                )
                if len(engine_on) > 1
                else 0.0,
                "distance_km": round(float(elapsed.movement_m.sum()) / 1000, 2) if len(elapsed) else 0.0,
                "points": int(len(elapsed)),
            },
            "track": [[float(r.latitude), float(r.longitude)] for r in elapsed.itertuples()],
            "corridor_m": config.corridor_m,
            "segments": [
                {
                    **segment,
                    "confirmed_length_m": float(confirmed_by_segment.get(segment["segment_id"], 0.0)),
                }
                for segment in _segments_payload(project)
            ],
            "events": [
                event.to_dict() for event in detected if pd.Timestamp(event.timestamp) <= now
            ],
            "photos": photos.to_dict("records") if not photos.empty else [],
        }
    )


@app.post("/api/replay/{action}")
def control(action: str, speed: float | None = None) -> dict:
    actions = {"start": replay.start, "pause": replay.pause, "reset": replay.reset}
    if action == "speed":
        if speed is None:
            raise HTTPException(400, "informe speed")
        return {"replay": replay.set_speed(speed).__dict__}
    if action not in actions:
        raise HTTPException(404, f"acao desconhecida: {action}")
    return {"replay": actions[action]().__dict__}


@app.post("/api/replay/jump/{event_id}")
def jump(event_id: str) -> dict:
    """Leva o relogio ate um evento. E o que torna a gravacao do video repetivel."""
    _, matched, detected = _day()
    event = next((e for e in detected if e.event_id == event_id), None)
    if not event:
        raise HTTPException(404, f"evento desconhecido: {event_id}")
    return {"replay": replay.jump_to(pd.Timestamp(event.timestamp), matched.timestamp.iloc[0]).__dict__}
