"""API do painel: serve a pagina e o estado do replay, lendo o mesmo SQLite do worker.

Um servico so no Railway: a API e o worker compartilham `/data`, entao o painel mostra
exatamente o que a conversa no Telegram gravou, sem ponte entre nuvens diferentes.
"""
from __future__ import annotations

import os
import re
import time
from functools import lru_cache
from pathlib import Path

import pandas as pd
import requests
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, JSONResponse

from machine2pipe import events, llm, replay, storage, weather
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


@lru_cache(maxsize=1)
def _weather():
    """Chuva do dia. Contexto para o agente, nunca prova de parada."""
    _, matched, _ = _day()
    return weather.fetch(
        config.replay_date,
        float(matched.latitude.mean()),
        float(matched.longitude.mean()),
        timezone=config.timezone,
    )


@app.on_event("startup")
def _warm() -> None:
    _day()


@app.get("/health")
def health() -> dict[str, object]:
    """Healthcheck do Railway e diagnostico de configuracao.

    Diz se cada segredo chegou ao container sem jamais revelar o valor: a causa mais
    comum de um bot mudo e a variavel nao ter sido aplicada ao deploy.
    """
    photos = storage.photos_frame()
    events_recorded = storage.events_frame()
    esperadas = [
        "TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID", "DATABASE_PATH", "PHOTO_STORAGE_PATH",
        "OPENAI_API_KEY", "OPENROUTER_API_KEY", "LLM_MODEL", "EXA_API_KEY",
    ]
    return {
        "status": "ok",
        "replay_date": config.replay_date,
        # Qual servico, ambiente e commit estao realmente servindo. Variavel cadastrada
        # noutro servico, ou alteracao que ficou em staging, aparece como ausencia aqui.
        "deployment": {
            "service": os.getenv("RAILWAY_SERVICE_NAME"),
            "environment": os.getenv("RAILWAY_ENVIRONMENT_NAME"),
            "commit": (os.getenv("RAILWAY_GIT_COMMIT_SHA") or "")[:7] or None,
            "branch": os.getenv("RAILWAY_GIT_BRANCH"),
        },
        # TELEGRAM_CHAT_ID e o numero do chat, nao o nome do bot. Um valor nao numerico
        # derruba o worker ao montar a allowlist, e o sintoma so aparece nos logs.
        "telegram_allowlist_valid": all(
            parte.strip().lstrip("-").isdigit()
            for parte in config.telegram_chat_id.split(",")
            if parte.strip()
        ),
        "variables_present": [nome for nome in esperadas if os.getenv(nome)],
        "variables_missing": [nome for nome in esperadas if not os.getenv(nome)],
        "telegram_token_configured": bool(config.telegram_bot_token),
        "telegram_allowlist_configured": bool(config.telegram_chat_id),
        "model_key_configured": bool(os.getenv("OPENAI_API_KEY") or os.getenv("OPENROUTER_API_KEY")),
        "llm_provider": config.llm_provider,
        "llm_model": config.llm_model,
        "project_kml": config.project_kml_path.name,
        # O elo do agente e o unico que nao da para ver pelo mapa: estes dois numeros
        # dizem se ele decidiu alguma coisa e se alguma quantidade ganhou dono.
        "agent_actions": int(len(storage.agent_actions_frame())),
        "confirmations": int(len(storage.confirmations_frame())),
        "exa_key_configured": bool(config.exa_api_key),
        "database_path": str(config.database_path),
        "database_writable": os.access(Path(config.database_path).parent, os.W_OK),
        "events_recorded": int(len(events_recorded)),
        "photos_loaded": int(len(photos)),
    }


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


@app.get("/api/telegram/check")
def telegram_check() -> JSONResponse:
    """Pergunta ao proprio Telegram por que o bot esta mudo, sem revelar o token.

    Separa as tres causas que de fora sao identicas: token recusado, webhook registrado
    (que faz o long polling nunca receber nada) e worker que nem chegou a consultar.
    `getMe` e `getWebhookInfo` sao leituras e nao consomem atualizacao nenhuma.
    """
    if not config.telegram_bot_token:
        return JSONResponse({"token_present": False,
                             "diagnosis": "TELEGRAM_BOT_TOKEN ausente no container"})

    bruto = config.telegram_bot_token
    token = bruto.strip()
    # A parte antes dos dois-pontos e o id publico do bot, nao um segredo. Descrever
    # formato e comprimento distingue "valor novo nao aplicado" de "valor novo errado"
    # sem colocar o token na resposta.
    forma = re.match(r"^(\d{6,12}):[A-Za-z0-9_-]{30,}$", token)
    resultado: dict[str, object] = {
        "token_present": True,
        "token_shape_valid": bool(forma),
        "token_bot_id": forma.group(1) if forma else None,
        "token_length": len(token),
        "token_had_surrounding_whitespace": bruto != token,
    }
    if not forma:
        aspas = len(token) > 1 and token[0] == token[-1] and token[0] in "\"'`"
        resultado["token_looks_quoted"] = aspas
        resultado["unexpected_characters"] = sorted(
            {c for c in token if not (c.isalnum() or c in ":_-")}
        )
        resultado["diagnosis"] = (
            "o valor esta entre aspas: grave sem aspas no Railway"
            if aspas
            else "o valor nao tem a forma de um token: esperado numero, dois-pontos e "
                 f"35 caracteres, e chegaram {len(token)} caracteres"
        )
        return JSONResponse(resultado)

    base = f"https://api.telegram.org/bot{token}"
    try:
        me = requests.get(f"{base}/getMe", timeout=15).json()
        resultado["token_accepted"] = bool(me.get("ok"))
        if me.get("ok"):
            resultado["bot_username"] = me["result"].get("username")
        else:
            resultado["telegram_error"] = me.get("description")
            resultado["diagnosis"] = "o Telegram recusou o token: provavelmente revogado ou copiado pela metade"
            return JSONResponse(resultado)

        hook = requests.get(f"{base}/getWebhookInfo", timeout=15).json()
        info = hook.get("result") or {}
        url = info.get("url") or ""
        resultado["webhook_url"] = url or None
        resultado["pending_updates"] = info.get("pending_update_count")
        resultado["last_error"] = info.get("last_error_message")
        resultado["diagnosis"] = (
            "ha um webhook registrado: enquanto ele existir o long polling nunca recebe nada"
            if url
            else "token valido e sem webhook; se o bot segue mudo o worker nao esta consultando"
        )
    except requests.RequestException as erro:
        resultado["diagnosis"] = f"nao foi possivel falar com a API do Telegram: {erro}"
    return JSONResponse(resultado)


@app.get("/api/agent/check")
def agent_check() -> JSONResponse:
    """Pergunta ao modelo se ele responde, sem revelar a chave.

    O bot mudo tinha tres causas identicas de fora; o agente mudo tem as mesmas. Uma
    chamada minima separa "sem chave" de "chave recusada", de "sem credito" e de "modelo
    responde, mas o loop nao esta rodando".
    """
    resultado: dict[str, object] = {
        "provider": config.llm_provider,
        "model": config.llm_model,
        "key_present": llm.available(),
    }
    if not llm.available():
        resultado["diagnosis"] = (
            "nenhuma chave no container: defina OPENROUTER_API_KEY (ou OPENAI_API_KEY). "
            "O agente segue decidindo por regra deterministica ate la."
        )
        return JSONResponse(resultado)

    inicio = time.monotonic()
    try:
        eco = llm.structured(
            [{"role": "user", "content": "Responda exatamente {\"ok\": true}."}],
            schema={
                "type": "object",
                "properties": {"ok": {"type": "boolean"}},
                "required": ["ok"],
                "additionalProperties": False,
            },
            schema_name="verificacao",
            max_tokens=20,
        )
    except llm.LLMUnavailable as erro:
        resultado["model_answers"] = False
        resultado["diagnosis"] = str(erro)
        return JSONResponse(resultado)

    resultado["model_answers"] = bool(eco.get("ok"))
    resultado["latency_ms"] = int((time.monotonic() - inicio) * 1000)
    resultado["diagnosis"] = (
        "modelo respondendo; se nao ha pergunta no Telegram, o replay esta parado ou "
        "nenhum evento foi alcancado ainda"
    )
    return JSONResponse(resultado)


@app.get("/api/photo/{photo_id}")
def photo(photo_id: str) -> FileResponse:
    frame = storage.photos_frame()
    linha = frame[frame.photo_id == photo_id] if not frame.empty else frame
    if linha.empty or not linha.iloc[0].file_path:
        raise HTTPException(404, f"foto desconhecida: {photo_id}")
    caminho = Path(linha.iloc[0].file_path)
    if not caminho.exists():
        raise HTTPException(404, f"arquivo ausente: {caminho.name}")
    return FileResponse(caminho, media_type="image/jpeg")


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
    if not photos.empty:
        capturadas = pd.to_datetime(photos.captured_at, format="ISO8601", utc=True)
        photos = photos[capturadas <= now.tz_convert("UTC")]
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
            "weather": _weather().to_dict() if _weather().available else None,
            "photos": photos.to_dict("records") if not photos.empty else [],
        }
    )


@app.get("/api/events/pending")
def pending() -> JSONResponse:
    """Eventos ja ocorridos no tempo simulado e ainda nao tratados pelo agente.

    E a fila que o worker consome: o agente le daqui, decide, e registra a acao, o que
    tira o evento da fila. Reiniciar o replay nao gera pergunta repetida.
    """
    _, matched, _ = _day()
    now = replay.simulated_now(matched.timestamp.iloc[0], matched.timestamp.iloc[-1])
    frame = storage.pending_events(until=now.isoformat())
    return JSONResponse({"simulated_time": now.isoformat(), "count": int(len(frame)),
                         "events": frame.to_dict("records")})


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
