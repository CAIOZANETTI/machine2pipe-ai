"""Regras deterministicas de evento.

Nenhuma regra aqui usa modelo de linguagem. O agente recebe o que este modulo produz e
decide o que fazer; ele nao recalcula nada. Todos os limiares vem de `config.py`.

Cada regra dispara uma vez por episodio, nao por ponto de telemetria: uma parada longa
gera um evento, nao noventa. Sem isso, um replay acelerado viraria uma rajada de
mensagens no Telegram.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Iterator

import pandas as pd

from machine2pipe.geo.project_loader import Project

ENTERED_SEGMENT = "entered_segment"
LEFT_SEGMENT = "left_segment"
OUTSIDE_PROJECT = "outside_project"
LONG_DWELL = "long_dwell"
UNEXPECTED_SEGMENT = "unexpected_segment"
GPS_GAP = "gps_gap"
PROGRESS_UNCONFIRMED = "progress_unconfirmed"


@dataclass(frozen=True)
class Event:
    event_id: str
    event_type: str
    timestamp: datetime
    machine_id: str
    segment_id: str | None
    chainage_m: float | None
    distance_to_axis_m: float | None
    engine_on: bool
    moving: bool
    movement_m: float
    dwell_minutes: float
    context: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "event_id": self.event_id,
            "event_type": self.event_type,
            "timestamp": self.timestamp.isoformat(),
            "machine_id": self.machine_id,
            "segment_id": self.segment_id,
            "chainage_m": self.chainage_m,
            "distance_to_axis_m": self.distance_to_axis_m,
            "engine_on": self.engine_on,
            "moving": self.moving,
            "movement_m": self.movement_m,
            "dwell_minutes": self.dwell_minutes,
            "context": self.context,
        }


class _Numbering:
    def __init__(self, date: str):
        self.date = date
        self.count = 0

    def next(self) -> str:
        self.count += 1
        return f"evt_{self.date}_{self.count:03d}"


def _segment_context(project: Project | None, segment_id: str | None) -> dict[str, Any]:
    if not project or not segment_id:
        return {}
    segment = project.segment(segment_id)
    if not segment:
        return {}
    keep = ("service_type", "diameter_mm", "material", "planned_length_m", "planned_start", "planned_end")
    return {f"planned_{k}" if not k.startswith("planned") else k: segment.attributes[k]
            for k in keep if k in segment.attributes}


def _distance(a, b) -> float:
    """Distancia em metros entre dois pontos ja projetados no CRS metrico."""
    return float(((a.x_m - b.x_m) ** 2 + (a.y_m - b.y_m) ** 2) ** 0.5)


def _minutes(start: pd.Timestamp, end: pd.Timestamp) -> float:
    return round((end - start).total_seconds() / 60, 1)


def detect(
    matched: pd.DataFrame,
    *,
    machine_id: str,
    long_dwell_minutes: float,
    dwell_movement_m: float,
    gps_gap_minutes: float,
    outside_project_minutes: float,
    project: Project | None = None,
    confirmed_segments: set[str] | None = None,
) -> list[Event]:
    """Percorre a telemetria ja casada com o projeto e devolve os eventos do periodo.

    `matched` precisa das colunas de `SegmentMatcher.match_frame`.
    """
    if matched.empty:
        return []

    rows = matched.sort_values("timestamp").reset_index(drop=True)
    numbering = _Numbering(str(rows.timestamp.iloc[0].date()))
    confirmed = confirmed_segments or set()
    events: list[Event] = []

    def emit(row, event_type: str, *, dwell: float = 0.0, extra: dict | None = None) -> None:
        segment_id = row.segment_id if row.inside_corridor else None
        context = _segment_context(project, segment_id)
        context.update(extra or {})
        events.append(
            Event(
                event_id=numbering.next(),
                event_type=event_type,
                timestamp=row.timestamp.to_pydatetime(),
                machine_id=machine_id,
                segment_id=segment_id,
                chainage_m=row.chainage_m if row.inside_corridor else None,
                distance_to_axis_m=row.distance_to_axis_m,
                engine_on=bool(row.engine_on),
                moving=bool(row.movement_m > dwell_movement_m),
                movement_m=float(row.movement_m),
                dwell_minutes=dwell,
                context=context,
            )
        )

    active_segment: str | None = None
    anchor = None
    dwell_start: pd.Timestamp | None = None
    dwell_reported = False
    outside_start: pd.Timestamp | None = None
    outside_reported = False
    previous = None
    flagged_unexpected: set[str] = set()
    visited: dict[str, pd.Timestamp] = {}

    for row in rows.itertuples():
        current = row.segment_id if row.inside_corridor else None

        if previous is not None and _minutes(previous.timestamp, row.timestamp) > gps_gap_minutes:
            emit(row, GPS_GAP, extra={"gap_minutes": _minutes(previous.timestamp, row.timestamp)})

        if current != active_segment:
            if active_segment is not None and previous is not None:
                emit(previous, LEFT_SEGMENT)
            if current is not None:
                emit(row, ENTERED_SEGMENT)
            active_segment = current

        if current is not None:
            visited.setdefault(current, row.timestamp)
            if current not in flagged_unexpected and _off_schedule(project, current, row.timestamp):
                flagged_unexpected.add(current)
                emit(row, UNEXPECTED_SEGMENT, extra={"scheduled": False})

        # Parada longa: motor ligado e a maquina permanecendo dentro de um raio.
        # Medir deslocamento entre pontos consecutivos nao serve: uma retro escavando fica
        # no lugar enquanto o GPS oscila dezenas de metros a cada leitura.
        if row.engine_on:
            if anchor is None or _distance(anchor, row) > dwell_movement_m:
                anchor, dwell_start, dwell_reported = row, row.timestamp, False
            elapsed = _minutes(dwell_start, row.timestamp)
            if not dwell_reported and elapsed >= long_dwell_minutes:
                emit(row, LONG_DWELL, dwell=elapsed,
                     extra={"radius_m": dwell_movement_m, "since": dwell_start.isoformat()})
                dwell_reported = True
        else:
            anchor, dwell_start, dwell_reported = None, None, False

        # Motor ligado fora do corredor por tempo relevante.
        if row.engine_on and not row.inside_corridor:
            outside_start = outside_start or row.timestamp
            if not outside_reported and _minutes(outside_start, row.timestamp) >= outside_project_minutes:
                emit(row, OUTSIDE_PROJECT, extra={"minutes_outside": _minutes(outside_start, row.timestamp)})
                outside_reported = True
        else:
            outside_start, outside_reported = None, False

        previous = row

    last = rows.iloc[-1]
    for segment_id, first_seen in visited.items():
        if segment_id in confirmed:
            continue
        events.append(
            Event(
                event_id=numbering.next(),
                event_type=PROGRESS_UNCONFIRMED,
                timestamp=last.timestamp.to_pydatetime(),
                machine_id=machine_id,
                segment_id=segment_id,
                chainage_m=None,
                distance_to_axis_m=None,
                engine_on=bool(last.engine_on),
                moving=False,
                movement_m=0.0,
                dwell_minutes=_minutes(first_seen, last.timestamp),
                context=_segment_context(project, segment_id),
            )
        )
    return events


def _off_schedule(project: Project | None, segment_id: str, timestamp: pd.Timestamp) -> bool:
    """Verdadeiro quando a maquina esta num trecho fora da janela planejada."""
    if not project:
        return False
    segment = project.segment(segment_id)
    if not segment:
        return False
    start, end = segment.attributes.get("planned_start"), segment.attributes.get("planned_end")
    if not start or not end:
        return False
    day = timestamp.date()
    return not (pd.Timestamp(str(start)).date() <= day <= pd.Timestamp(str(end)).date())


def by_type(events: list[Event]) -> Iterator[tuple[str, list[Event]]]:
    types = sorted({e.event_type for e in events})
    for event_type in types:
        yield event_type, [e for e in events if e.event_type == event_type]
