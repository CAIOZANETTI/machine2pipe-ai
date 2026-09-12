"""Leitura de comportamento: o que a maquina estava fazendo, instante a instante.

`events.py` diz quando algo aconteceu (entrou no trecho, parou, sumiu o GPS). Este modulo
diz o que a maquina estava fazendo entre um evento e outro, cruzando tres coisas que
sozinhas nao dizem nada: onde ela esta em relacao ao projeto (eixo do tubo, canteiro,
jazida, posto), se o motor esta ligado e quanto ela se deslocou.

A regra e de engenharia, nao de modelo:

- **Frente de servico**: dentro do corredor do eixo, sem transito. E a assinatura do
  assentamento: a maquina fica na mesma estaca por dezenas de minutos com o motor ligando
  e desligando a cada poucos minutos — a equipe posiciona o tubo, o operador religa para
  escavar. Um motor desligado curto nao encerra a frente; um longo, sim.
- **Deslocando**: velocidade ou salto acima do limiar, onde quer que esteja. Motor ligado
  andando rapido nao e escavacao.
- **No canteiro / na jazida / abastecendo**: a menos do raio de uma estrutura de apoio do
  KML. Sao os pontos que Caio marcou justamente para isto.
- **Parada**: motor ligado, sem se mover, fora de qualquer lugar conhecido.
- **Desligada**: motor desligado.

Cada episodio guarda a faixa de estacas em que ocorreu, e as fotos cujo horario cai dentro
dele ficam presas a ele como prova. Uma foto na estaca 114 as 13:01, dentro de uma frente
de servico das 12:57 as 14:40 entre as estacas 114 e 153, e o que transforma "a maquina
esteve ali" em "a maquina estava executando ali". A quantidade continua vindo do
engenheiro: a leitura diz o que aconteceu, nao quantos metros.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import numpy as np
import pandas as pd

from machine2pipe.config import config
from machine2pipe.geo.project_loader import Project
from machine2pipe.geo.stationing import project_point

FRENTE = "frente_de_servico"
DESLOCANDO = "deslocando"
CANTEIRO = "no_canteiro"
JAZIDA = "na_jazida"
ABASTECENDO = "abastecendo"
PARADA = "parada"
DESLIGADA = "desligada"

ROTULOS = {
    FRENTE: "frente de serviço",
    DESLOCANDO: "deslocando",
    CANTEIRO: "no canteiro",
    JAZIDA: "na jazida",
    ABASTECENDO: "abastecendo",
    PARADA: "parada com motor ligado",
    DESLIGADA: "desligada",
}

# Que estado uma estrutura de apoio do KML representa, pelo nome que Caio deu a ela.
APOIO = (("posto", ABASTECENDO), ("canteiro", CANTEIRO), ("jazida", JAZIDA))


@dataclass
class Episode:
    state: str
    start: pd.Timestamp
    end: pd.Timestamp
    points: int
    engine_on_minutes: float = 0.0
    chainage_min_m: float | None = None
    chainage_max_m: float | None = None
    structure: str | None = None
    photo_ids: list[str] = field(default_factory=list)

    @property
    def minutes(self) -> float:
        return round((self.end - self.start).total_seconds() / 60, 1)

    def describe(self) -> str:
        """Uma linha em portugues, do jeito que a pergunta do agente vai cita-la."""
        quando = f"{self.start:%H:%M}–{self.end:%H:%M}"
        duracao = _duracao(self.minutes)
        if self.state == FRENTE and self.chainage_min_m is not None:
            faixa = (
                f"na estaca {self.chainage_min_m:.0f} m"
                if self.chainage_max_m - self.chainage_min_m < 10
                else f"entre as estacas {self.chainage_min_m:.0f} e {self.chainage_max_m:.0f} m"
            )
            prova = f", com {len(self.photo_ids)} foto(s)" if self.photo_ids else ""
            return f"frente de serviço {faixa}, {quando} ({duracao}{prova})"
        onde = f" ({self.structure})" if self.structure else ""
        return f"{ROTULOS.get(self.state, self.state)}{onde}, {quando} ({duracao})"

    def to_dict(self) -> dict[str, Any]:
        return {
            "state": self.state,
            "label": ROTULOS.get(self.state, self.state),
            "start": self.start.isoformat(),
            "end": self.end.isoformat(),
            "minutes": self.minutes,
            "engine_on_minutes": round(self.engine_on_minutes, 1),
            "chainage_min_m": self.chainage_min_m,
            "chainage_max_m": self.chainage_max_m,
            "structure": self.structure,
            "photo_ids": list(self.photo_ids),
            "summary": self.describe(),
        }


def _duracao(minutos: float) -> str:
    horas, resto = divmod(int(round(minutos)), 60)
    if horas and resto:
        return f"{horas}h{resto:02d}"
    if horas:
        return f"{horas}h"
    return f"{resto} min"


def _apoio(project: Project | None, target_crs: str) -> list[tuple[str, str, float, float]]:
    """Estruturas de apoio do KML ja projetadas: (estado, nome, x, y)."""
    saida = []
    for estrutura in (project.structures if project else []):
        chave = estrutura.structure_id.lower()
        estado = next((s for nome, s in APOIO if nome in chave), None)
        if not estado:
            continue  # bueiro e afins ficam no eixo; a frente ja os cobre
        lon, lat = estrutura.coordinate
        ponto = project_point(lat, lon, target_crs)
        saida.append((estado, estrutura.name or estrutura.structure_id, ponto.x, ponto.y))
    return saida


def classify_points(
    matched: pd.DataFrame,
    *,
    project: Project | None = None,
    structure_radius_m: float | None = None,
    transit_speed_kmh: float | None = None,
    transit_jump_m: float | None = None,
) -> pd.DataFrame:
    """Um estado por ponto de telemetria. Devolve `matched` com `state` e `structure`."""
    raio = structure_radius_m if structure_radius_m is not None else config.structure_radius_m
    limite_kmh = transit_speed_kmh if transit_speed_kmh is not None else config.transit_speed_kmh
    salto = transit_jump_m if transit_jump_m is not None else config.transit_jump_m

    rows = _one_row_per_instant(matched)
    if rows.empty:
        rows["state"], rows["structure"] = pd.Series(dtype=str), pd.Series(dtype=object)
        return rows

    # O estado de um ponto vale ate o ponto seguinte. `movement_m` e o deslocamento que
    # *chegou* ao ponto seguinte, entao o transito pertence a este intervalo, nao ao proximo:
    # um salto de 331 m registrado as 12:57 aconteceu entre 12:47 e 12:57.
    segundos = (rows.timestamp.shift(-1) - rows.timestamp).dt.total_seconds()
    movimento = rows.movement_m.shift(-1).fillna(0.0)
    kmh = (movimento / segundos.replace(0, np.nan) * 3.6).fillna(0.0)
    transito = (kmh > limite_kmh) | (movimento >= salto)

    estrutura = pd.Series([None] * len(rows), dtype=object)
    estado_apoio = pd.Series([None] * len(rows), dtype=object)
    for estado, nome, x, y in _apoio(project, config.target_crs):
        perto = np.hypot(rows.x_m - x, rows.y_m - y) <= raio
        estrutura[perto & estado_apoio.isna()] = nome
        estado_apoio[perto & estado_apoio.isna()] = estado

    # Dentro do corredor com motor ligado e frente. Com motor desligado e "desligada" por
    # enquanto: `_absorb_short_stops` devolve a frente os desligamentos curtos, e so os
    # longos (almoco, fim de turno) encerram o episodio.
    ligado = rows.engine_on.astype(bool)
    estado = pd.Series([PARADA] * len(rows), dtype=object)
    estado[~ligado] = DESLIGADA
    estado[rows.inside_corridor.astype(bool) & ligado] = FRENTE
    apoio = estado_apoio.notna()
    estado[apoio] = estado_apoio[apoio]
    estado[transito] = DESLOCANDO
    estrutura[transito] = None

    rows["state"] = estado
    rows["structure"] = estrutura
    return rows


def _one_row_per_instant(matched: pd.DataFrame) -> pd.DataFrame:
    """A telemetria e de eventos: chave ligada, arranque, paragem chegam no mesmo segundo.

    Um estado por instante: a posicao e o motor sao os do ultimo evento do segundo, e o
    deslocamento e a soma, porque cada evento registra o que andou desde o anterior.
    """
    rows = matched.sort_values("timestamp").reset_index(drop=True)
    if rows.empty:
        return rows.copy()
    movimento = rows.groupby("timestamp", sort=True).movement_m.sum()
    ultimos = rows.groupby("timestamp", sort=True).tail(1).set_index("timestamp")
    ultimos["movement_m"] = movimento
    return ultimos.reset_index()


def _episodes(rows: pd.DataFrame) -> list[Episode]:
    """Agrupa pontos consecutivos do mesmo estado. Cada ponto dura ate o proximo."""
    episodios: list[Episode] = []
    proximo = rows.timestamp.shift(-1).fillna(rows.timestamp)
    for indice, row in rows.iterrows():
        fim = proximo.iloc[indice]
        ligado = (fim - row.timestamp).total_seconds() / 60 if row.engine_on else 0.0
        estaca = float(row.chainage_m) if row.state == FRENTE and pd.notna(row.chainage_m) else None
        atual = episodios[-1] if episodios else None
        if atual and atual.state == row.state and atual.structure == row.structure:
            atual.end = fim
            atual.points += 1
            atual.engine_on_minutes += ligado
            if estaca is not None:
                atual.chainage_min_m = min(atual.chainage_min_m, estaca) if atual.chainage_min_m is not None else estaca
                atual.chainage_max_m = max(atual.chainage_max_m, estaca) if atual.chainage_max_m is not None else estaca
            continue
        episodios.append(
            Episode(
                state=row.state, start=row.timestamp, end=fim, points=1, engine_on_minutes=ligado,
                chainage_min_m=estaca, chainage_max_m=estaca, structure=row.structure,
            )
        )
    return episodios


def _absorb_short_stops(episodios: list[Episode], short_stop_minutes: float) -> list[Episode]:
    """Motor desligado curto entre duas frentes e parte da frente, nao uma parada.

    A telemetria mostra a maquina na mesma estaca desligando e religando a cada 2 ou 3
    minutos: e a equipe posicionando o tubo. Cortar a frente a cada religada daria vinte
    episodios de tres minutos e nenhuma leitura util.
    """
    if len(episodios) < 3:
        return episodios
    resultado: list[Episode] = [episodios[0]]
    for indice in range(1, len(episodios)):
        atual = episodios[indice]
        anterior = resultado[-1]
        proximo = episodios[indice + 1] if indice + 1 < len(episodios) else None
        curto = atual.state in {DESLIGADA, PARADA} and atual.minutes <= short_stop_minutes
        if curto and anterior.state == FRENTE and proximo and proximo.state == FRENTE:
            anterior.end = atual.end
            anterior.points += atual.points
            continue
        if atual.state == anterior.state and atual.structure == anterior.structure:
            anterior.end = atual.end
            anterior.points += atual.points
            anterior.engine_on_minutes += atual.engine_on_minutes
            if atual.chainage_min_m is not None:
                anterior.chainage_min_m = min(anterior.chainage_min_m or atual.chainage_min_m, atual.chainage_min_m)
                anterior.chainage_max_m = max(anterior.chainage_max_m or atual.chainage_max_m, atual.chainage_max_m)
            continue
        resultado.append(atual)
    return resultado


def episodes(
    matched: pd.DataFrame,
    *,
    project: Project | None = None,
    short_stop_minutes: float | None = None,
    **thresholds: float,
) -> list[Episode]:
    """A jornada como sequencia de episodios. Deterministica: mesma entrada, mesma saida."""
    rows = classify_points(matched, project=project, **thresholds)
    if rows.empty:
        return []
    limite = short_stop_minutes if short_stop_minutes is not None else config.short_stop_minutes
    return _absorb_short_stops(_episodes(rows), limite)


def attach_photos(episodios: list[Episode], photos: pd.DataFrame) -> list[Episode]:
    """Prende cada foto ao episodio em que foi tirada. A foto vira prova do episodio."""
    if photos is None or photos.empty or "captured_at" not in photos.columns:
        return episodios
    for episodio in episodios:
        episodio.photo_ids = []
    capturas = pd.to_datetime(photos.captured_at, format="ISO8601", utc=True)
    for photo_id, momento in zip(photos.photo_id, capturas):
        for episodio in episodios:
            if episodio.start.tz_convert("UTC") <= momento <= episodio.end.tz_convert("UTC"):
                episodio.photo_ids.append(str(photo_id))
                break
    return episodios


def until(episodios: list[Episode], moment: pd.Timestamp) -> list[Episode]:
    """Os episodios ja vividos ate o instante simulado, com o ultimo cortado nele."""
    recorte: list[Episode] = []
    for episodio in episodios:
        if episodio.start > moment:
            break
        copia = Episode(**{**episodio.__dict__, "photo_ids": list(episodio.photo_ids)})
        copia.end = min(episodio.end, moment)
        recorte.append(copia)
    return recorte


def summary(episodios: list[Episode]) -> dict[str, Any]:
    """Horas por estado e as frentes de servico do dia, prontas para o painel e o agente."""
    minutos: dict[str, float] = {}
    for episodio in episodios:
        minutos[episodio.state] = minutos.get(episodio.state, 0.0) + episodio.minutes
    frentes = [e for e in episodios if e.state == FRENTE]
    return {
        "hours": {estado: round(m / 60, 2) for estado, m in minutos.items()},
        "front_hours": round(minutos.get(FRENTE, 0.0) / 60, 2),
        "fronts": [e.to_dict() for e in frentes],
        "episodes": [e.to_dict() for e in episodios],
    }


def narrative(episodios: list[Episode]) -> str:
    """As frentes de servico em uma frase, para a pergunta do agente."""
    frentes = [e for e in episodios if e.state == FRENTE and e.minutes >= 5]
    if not frentes:
        return "nenhuma frente de serviço identificada até agora"
    partes = [e.describe() for e in frentes]
    total = sum(e.minutes for e in frentes)
    return f"{_duracao(total)} em frente de serviço: " + "; ".join(partes)
