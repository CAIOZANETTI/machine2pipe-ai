"""Casa a evidencia recebida no Telegram com o projeto e a telemetria.

O casamento primario e por horario, nao por GPS: a telemetria ja sabe onde a maquina
estava as 13:01, entao a foto se localiza sozinha. Isso importa porque o Telegram remove
EXIF de imagens enviadas como "foto" — so o envio como documento preserva. O GPS da foto,
quando sobrevive, entra como conferencia, nunca como fonte da posicao.

Uma foto tirada hoje nao tem telemetria de 2022 para casar. Nesse caso ela e ancorada no
instante simulado do replay, que e o que a demonstracao significa: a evidencia pertence ao
momento da jornada que esta na tela. `received_at` guarda o relogio real, entao a diferenca
entre o que foi encenado e o que foi vivido continua auditavel.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date as date_type
from functools import lru_cache
from pathlib import Path
from typing import Any

import pandas as pd

from machine2pipe import activity
from machine2pipe.config import config
from machine2pipe.geo import project_loader
from machine2pipe.geo.matching import SegmentMatcher
from machine2pipe.geo.stationing import project_point
from machine2pipe.photos import PhotoMetadata
from machine2pipe.telemetry import loader

log = logging.getLogger(__name__)

# Fora desta janela a foto nao descreve o ponto de telemetria mais proximo.
MAX_DELTA = pd.Timedelta("45min")


@dataclass(frozen=True)
class PhotoPlacement:
    """Onde a foto caiu no projeto, e com que confianca isso foi estabelecido."""

    captured_at: pd.Timestamp
    latitude: float
    longitude: float
    segment_id: str | None
    chainage_m: float | None
    distance_to_segment_m: float | None
    telemetry_delta_seconds: float
    anchored_to_replay: bool
    gps_check_m: float | None

    def describe(self) -> str:
        """Uma linha em portugues dizendo onde a foto caiu. Vai para o Telegram."""
        if not self.segment_id:
            return (
                f"Foto registrada as {self.captured_at:%H:%M}, mas a maquina estava fora do "
                f"corredor de {config.corridor_m:.0f} m do projeto nesse instante."
            )
        onde = f"{self.segment_id}, estaca {self.chainage_m:.0f} m"
        conferencia = (
            f" GPS da foto confere a {self.gps_check_m:.0f} m."
            if self.gps_check_m is not None
            else ""
        )
        return (
            f"Foto situada em {onde} ({self.captured_at:%H:%M}), a "
            f"{self.distance_to_segment_m:.0f} m do eixo.{conferencia}"
        )


class ProjectIndex:
    """Projeto, telemetria do dia e casador, carregados uma vez por processo.

    O worker vive por horas e uma foto pode chegar a qualquer momento; reabrir o Parquet
    a cada mensagem custaria segundos de silencio no Telegram.
    """

    def __init__(self) -> None:
        self.project = project_loader.load(config.project_kml_path, config.segments_csv_path)
        self.matcher = SegmentMatcher(self.project, config.target_crs, config.corridor_m)
        # A telemetria inteira fica em memoria (608 dias, 78 mil linhas): o engenheiro pode
        # perguntar por qualquer dia, e reler o Parquet a cada pergunta custaria segundos.
        self.all_telemetry = loader.load()
        dia = pd.Timestamp(config.replay_date).date()
        self.telemetry = self.all_telemetry[
            self.all_telemetry.timestamp.dt.date == dia
        ].reset_index(drop=True)
        # A leitura de comportamento do dia inteiro; o worker recorta ate o instante.
        self.episodes = activity.episodes(
            self.matcher.match_frame(self.telemetry), project=self.project
        )

    @lru_cache(maxsize=64)
    def read_day(self, day: date_type) -> dict[str, Any]:
        """Le qualquer dia da telemetria com a mesma regra de comportamento do replay.

        E o que responde "o que aconteceu em 29/06?": naquele dia a maquina ligou 188 vezes
        e nunca entrou no corredor — trabalhou fora deste projeto. Sem esta leitura o agente
        so conheceria o dia do replay e teria de dizer "nao sei" ou, pior, inventar.
        """
        pontos = self.all_telemetry[self.all_telemetry.timestamp.dt.date == day]
        if pontos.empty:
            return {"day": day.isoformat(), "telemetry_points": 0,
                    "reading": "sem telemetria nesse dia"}
        casado = self.matcher.match_frame(pontos.reset_index(drop=True))
        episodios = activity.episodes(casado, project=self.project)
        resumo = activity.summary(episodios)
        return {
            "day": day.isoformat(),
            "telemetry_points": int(len(casado)),
            "points_in_corridor": int(casado.inside_corridor.sum()),
            "engine_on_points": int(casado.engine_on.sum()),
            "shift": f"{casado.timestamp.iloc[0]:%H:%M}–{casado.timestamp.iloc[-1]:%H:%M}",
            "hours": resumo["hours"],
            "front_hours": resumo["front_hours"],
            "fronts": [f["summary"] for f in resumo["fronts"] if f["minutes"] >= 5],
            "reading": activity.narrative(episodios, brief=True),
        }

    @property
    def day_bounds(self) -> tuple[pd.Timestamp, pd.Timestamp]:
        return self.telemetry.timestamp.iloc[0], self.telemetry.timestamp.iloc[-1]

    def _localize(self, moment: pd.Timestamp) -> pd.Timestamp:
        return moment.tz_localize(config.timezone) if moment.tzinfo is None else moment

    def place_photo(
        self, metadata: PhotoMetadata, *, simulated_now: pd.Timestamp
    ) -> PhotoPlacement:
        """Situa a foto no projeto pelo horario de captura, ou pelo relogio do replay."""
        anchored = True
        moment = self._localize(pd.Timestamp(simulated_now))
        if metadata.captured_at is not None:
            capturada = self._localize(pd.Timestamp(metadata.captured_at))
            proximidade = (self.telemetry.timestamp - capturada).abs().min()
            if proximidade <= MAX_DELTA:
                moment, anchored = capturada, False

        janela = self.telemetry.iloc[
            (self.telemetry.timestamp - moment).abs().argsort()[:1]
        ]
        ponto = janela.iloc[0]
        delta = (ponto.timestamp - moment).total_seconds()
        casamento = self.matcher.match(float(ponto.latitude), float(ponto.longitude))

        conferencia = None
        if metadata.has_gps:
            da_foto = project_point(metadata.latitude, metadata.longitude, config.target_crs)
            da_maquina = project_point(
                float(ponto.latitude), float(ponto.longitude), config.target_crs
            )
            conferencia = round(da_foto.distance(da_maquina), 1)

        return PhotoPlacement(
            captured_at=moment,
            # A posicao vem da maquina: o GPS da foto confere, nao localiza.
            latitude=float(ponto.latitude),
            longitude=float(ponto.longitude),
            segment_id=casamento.segment_id if casamento.inside_corridor else None,
            chainage_m=casamento.chainage_m if casamento.inside_corridor else None,
            distance_to_segment_m=casamento.distance_to_axis_m,
            telemetry_delta_seconds=float(delta),
            anchored_to_replay=anchored,
            gps_check_m=conferencia,
        )


def photo_record(
    placement: PhotoPlacement,
    *,
    path: Path,
    source: str,
    visual_class: str | None = None,
    confidence: float | None = None,
    visual_summary: str | None = None,
) -> dict:
    """Monta a linha de `photo_evidence` no contrato de `docs/TASK_SPLIT.md`."""
    return {
        "photo_id": f"{source}_{placement.captured_at:%Y%m%d_%H%M%S}",
        "captured_at": placement.captured_at.isoformat(),
        "latitude": placement.latitude,
        "longitude": placement.longitude,
        "segment_id": placement.segment_id,
        "chainage_m": placement.chainage_m,
        "distance_to_segment_m": placement.distance_to_segment_m,
        "telemetry_delta_seconds": placement.telemetry_delta_seconds,
        "visual_class": visual_class,
        "confidence": confidence,
        "visual_summary": visual_summary,
        # Uma classificacao visual e probabilistica: a foto nunca fecha quantidade sozinha.
        "requires_confirmation": 1,
        "source": source,
        "file_path": str(path),
    }
