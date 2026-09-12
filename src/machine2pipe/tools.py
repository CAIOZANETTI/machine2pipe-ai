"""Ferramentas deterministicas que o agente pode consultar antes de decidir.

Toda quantidade de engenharia vive aqui, em Python, e nenhuma e recalculada pelo modelo.
O agente pergunta "quanto ja foi confirmado no trecho?" e recebe o numero que o banco tem;
ele nao soma, nao estima e nao converte. Essa e a fronteira do `AGENTS.md` posta em codigo.

Cada chamada e registrada e volta junto com a decisao, entao `agent_actions.tool_calls`
guarda o que o agente consultou para decidir o que decidiu. Um numero no painel pode ser
seguido de volta ate o evento, a pergunta, a resposta e as consultas que a motivaram.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Callable

from machine2pipe import storage, weather
from machine2pipe.config import config
from machine2pipe.geo.project_loader import Project

log = logging.getLogger(__name__)

REGISTRY: dict[str, Callable[..., dict[str, Any]]] = {}


def tool(name: str) -> Callable:
    def register(function: Callable[..., dict[str, Any]]) -> Callable:
        REGISTRY[name] = function
        return function

    return register


@dataclass
class ToolLog:
    """Registro de auditoria das consultas feitas para uma decisao."""

    calls: list[dict[str, Any]] = field(default_factory=list)

    def run(self, name: str, **kwargs: Any) -> dict[str, Any]:
        function = REGISTRY.get(name)
        if not function:
            raise KeyError(f"ferramenta desconhecida: {name}")
        try:
            result = function(**kwargs)
        except Exception as erro:  # a decisao segue sem a consulta, mas o log guarda a falha
            log.warning("ferramenta %s falhou: %s", name, erro)
            result = {"error": str(erro)}
        self.calls.append({"tool": name, "arguments": kwargs, "result": result})
        return result


@tool("segment_status")
def segment_status(*, segment_id: str | None, project: Project | None = None) -> dict[str, Any]:
    """Projetado, confirmado e restante de um trecho. Os tres numeros vem do banco."""
    if not segment_id:
        return {"segment_id": None, "note": "evento fora do corredor do projeto"}

    planejado: float | None = None
    atributos: dict[str, Any] = {}
    segmento = project.segment(segment_id) if project else None
    if segmento:
        atributos = dict(segmento.attributes)
        valor = atributos.get("planned_length_m")
        planejado = float(valor) if valor is not None else None

    progresso = storage.confirmed_progress()
    confirmado = 0.0
    confirmacoes = 0
    if not progresso.empty:
        linha = progresso[progresso.segment_id == segment_id]
        if not linha.empty:
            confirmado = float(linha.iloc[0].confirmed_length_m or 0)
            confirmacoes = int(linha.iloc[0].confirmations)

    return {
        "segment_id": segment_id,
        "planned_length_m": planejado,
        "diameter_mm": atributos.get("diameter_mm"),
        "material": atributos.get("material"),
        "confirmed_length_m": round(confirmado, 1),
        "confirmations": confirmacoes,
        "remaining_m": round(planejado - confirmado, 1) if planejado is not None else None,
    }


@tool("weather_context")
def weather_context(*, latitude: float, longitude: float, day: str | None = None) -> dict[str, Any]:
    """Chuva do dia historico. Contexto para uma parada, nunca prova de parada."""
    dia = weather.fetch(day or config.replay_date, latitude, longitude, timezone=config.timezone)
    if not dia.available:
        return {"available": False, "note": dia.note}
    return {"available": True, "rained": dia.rained(), **dia.to_dict()}


@tool("photo_evidence")
def photo_evidence(*, segment_id: str | None = None, limit: int = 3) -> dict[str, Any]:
    """Fotos ja arquivadas, opcionalmente do trecho do evento."""
    frame = storage.photos_frame()
    if frame.empty:
        return {"count": 0, "photos": []}
    if segment_id:
        frame = frame[frame.segment_id == segment_id]
    colunas = ["photo_id", "captured_at", "segment_id", "chainage_m", "visual_class", "confidence"]
    recorte = frame.tail(limit)[[c for c in colunas if c in frame.columns]]
    return {"count": int(len(frame)), "photos": recorte.to_dict("records")}


@tool("confirmation_history")
def confirmation_history(*, limit: int = 5) -> dict[str, Any]:
    """O que o engenheiro ja confirmou hoje. Evita perguntar duas vezes a mesma coisa."""
    frame = storage.confirmations_frame()
    if frame.empty:
        return {"count": 0, "confirmations": []}
    colunas = ["segment_id", "confirmed_length_m", "status", "interruption_reason", "confirmed_at"]
    return {
        "count": int(len(frame)),
        "confirmations": frame.tail(limit)[
            [c for c in colunas if c in frame.columns]
        ].to_dict("records"),
    }


def briefing(
    event: dict[str, Any],
    *,
    project: Project | None = None,
    location: tuple[float, float] | None = None,
) -> tuple[dict[str, Any], ToolLog]:
    """Reune o que o agente precisa saber sobre um evento, e o log de como soube.

    A coleta e deterministica de proposito: o modelo decide o que fazer com os numeros,
    nao quais numeros existem. Isso mantem o custo previsivel e o comportamento repetivel
    entre duas execucoes do mesmo replay.
    """
    registro = ToolLog()
    dados: dict[str, Any] = {
        "trecho": registro.run("segment_status", segment_id=event.get("segment_id"), project=project),
        "confirmado_hoje": registro.run("confirmation_history"),
        "fotos": registro.run("photo_evidence", segment_id=event.get("segment_id")),
    }
    # O evento nao carrega coordenada: quem chama sabe onde a maquina estava e informa.
    if location:
        dados["clima"] = registro.run(
            "weather_context", latitude=location[0], longitude=location[1]
        )
    return dados, registro
