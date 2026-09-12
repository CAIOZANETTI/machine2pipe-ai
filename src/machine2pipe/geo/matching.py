"""Casa um ponto de telemetria com o trecho de projeto mais proximo.

Proximidade e evidencia de atividade, nunca prova de tubo assentado. O resultado diz
onde a maquina esta em relacao ao projeto; quanto foi executado so o engenheiro confirma.
"""
from __future__ import annotations

from dataclasses import dataclass

import pandas as pd
from shapely.geometry import LineString

from machine2pipe.geo.project_loader import Project
from machine2pipe.geo.stationing import chainage, offset, project_line, project_point


@dataclass(frozen=True)
class Match:
    segment_id: str | None
    distance_to_axis_m: float | None
    chainage_m: float | None
    inside_corridor: bool

    @property
    def outside_project(self) -> bool:
        return not self.inside_corridor


NO_MATCH = Match(None, None, None, False)


class SegmentMatcher:
    def __init__(self, project: Project, target_crs: str, corridor_m: float):
        self.corridor_m = corridor_m
        self.lines: dict[str, LineString] = {
            segment.segment_id: project_line(segment.coordinates, target_crs)
            for segment in project.segments
        }
        self.target_crs = target_crs

    def match(self, latitude: float, longitude: float) -> Match:
        if not self.lines:
            return NO_MATCH
        point = project_point(latitude, longitude, self.target_crs)
        segment_id, line = min(
            self.lines.items(), key=lambda item: offset(item[1], point)
        )
        distance = offset(line, point)
        return Match(
            segment_id=segment_id,
            distance_to_axis_m=round(distance, 2),
            chainage_m=round(chainage(line, point), 2),
            inside_corridor=distance <= self.corridor_m,
        )

    def match_frame(self, telemetry: pd.DataFrame) -> pd.DataFrame:
        """Anexa trecho, estaca e distancia ao eixo a cada ponto de telemetria."""
        matches = [
            self.match(row.latitude, row.longitude) for row in telemetry.itertuples()
        ]
        enriched = telemetry.copy()
        enriched["segment_id"] = [m.segment_id for m in matches]
        enriched["distance_to_axis_m"] = [m.distance_to_axis_m for m in matches]
        enriched["chainage_m"] = [m.chainage_m for m in matches]
        enriched["inside_corridor"] = [m.inside_corridor for m in matches]
        return enriched

    def segment_length_m(self, segment_id: str) -> float:
        return float(self.lines[segment_id].length)
