"""Relogio do replay: transforma tempo real em tempo simulado do dia historico.

O estado fica num JSON ao lado do banco, porque dois processos precisam dele: a API
serve os controles e o worker le para saber onde esta na jornada.

A velocidade padrao e 60x, nao 600x. A 600x uma parada de 45 minutos dispara em 4,5
segundos e o engenheiro nao consegue responder no Telegram antes de a janela fechar.
"""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta
from pathlib import Path

import pandas as pd

from machine2pipe.config import config

STOPPED, RUNNING, PAUSED = "stopped", "running", "paused"


def state_path() -> Path:
    return Path(config.database_path).with_name("replay_state.json")


@dataclass
class ReplayState:
    status: str = STOPPED
    speed: float = 60.0
    elapsed_seconds: float = 0.0
    resumed_at: str | None = None  # instante real do ultimo start, ISO

    def simulated_elapsed(self) -> float:
        seconds = self.elapsed_seconds
        if self.status == RUNNING and self.resumed_at:
            real = (datetime.now().astimezone() - datetime.fromisoformat(self.resumed_at)).total_seconds()
            seconds += max(0.0, real) * self.speed
        return seconds


def load() -> ReplayState:
    path = state_path()
    if not path.exists():
        return ReplayState(speed=config.replay_speed)
    try:
        return ReplayState(**json.loads(path.read_text()))
    except (json.JSONDecodeError, TypeError):
        return ReplayState(speed=config.replay_speed)


def save(state: ReplayState) -> ReplayState:
    path = state_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(asdict(state), indent=2))
    return state


def start() -> ReplayState:
    state = load()
    if state.status != RUNNING:
        state.status = RUNNING
        state.resumed_at = datetime.now().astimezone().isoformat()
    return save(state)


def pause() -> ReplayState:
    state = load()
    if state.status == RUNNING:
        state.elapsed_seconds = state.simulated_elapsed()
        state.status = PAUSED
        state.resumed_at = None
    return save(state)


def reset() -> ReplayState:
    return save(ReplayState(speed=config.replay_speed))


def set_speed(speed: float) -> ReplayState:
    state = pause() if load().status == RUNNING else load()
    state.speed = max(1.0, float(speed))
    return save(state)


def jump_to(target: pd.Timestamp, day_start: pd.Timestamp) -> ReplayState:
    """Leva o relogio direto a um instante do dia. Usado para gravar a demonstracao."""
    state = load()
    state.elapsed_seconds = max(0.0, (target - day_start).total_seconds())
    state.status = PAUSED
    state.resumed_at = None
    return save(state)


def simulated_now(day_start: pd.Timestamp, day_end: pd.Timestamp) -> pd.Timestamp:
    state = load()
    if state.status == STOPPED:
        return day_start
    moment = day_start + timedelta(seconds=state.simulated_elapsed())
    return min(moment, day_end)
