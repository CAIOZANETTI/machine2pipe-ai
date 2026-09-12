"""Processo sempre ligado: replay, long polling do Telegram e o loop do agente.

Tres coisas acontecem aqui ao mesmo tempo, e a ordem entre elas e o produto:

1. O motor deterministico ja gravou os eventos do dia no SQLite.
2. O relogio do replay avanca; quando um evento e alcancado, o agente decide o que fazer
   com ele e, se for o caso, pergunta no Telegram.
3. A resposta do engenheiro volta pelo polling, e o que ela afirma vira quantidade
   confirmada — amarrada ao `event_id` da pergunta que a provocou.

Fotos entram pelo mesmo caminho: sao casadas com trecho e estaca pela telemetria, lidas
pelo modelo de visao e gravadas como evidencia. Nenhuma delas fecha quantidade sozinha.
"""
from __future__ import annotations

import json
import logging
import signal
import threading
from typing import Any

import pandas as pd

from machine2pipe import activity, agent, events as event_rules, ingest, replay, storage, tools, vision
from machine2pipe.config import config
from machine2pipe.photos import PhotoStore, StoredPhoto
from machine2pipe.telegram_bot import TelegramBot, parse_chat_allowlist

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s [worker] %(message)s",
)
log = logging.getLogger(__name__)

_stop_event = threading.Event()

# Quantos eventos o agente trata por rodada. Com o teto por tipo de evento em agent.py a
# maioria e escrituracao silenciosa, entao a rodada pode ser maior sem virar rajada no
# Telegram; ao pular o relogio para o fim do dia, 18 eventos levam menos de um minuto.
MAX_POR_RODADA = 4


def _stop(signum, _frame):
    log.info("sinal %s recebido, encerrando", signum)
    _stop_event.set()


def _number(value: Any) -> float | None:
    """NaN do pandas vira None.

    Duas razoes: `json.dumps` escreve `NaN`, que nao e JSON valido e chega torto ao modelo;
    e `f"{nan:.0f}"` escreve "estaca nan m" na pergunta enviada ao engenheiro.
    """
    if value is None:
        return None
    try:
        numero = float(value)
    except (TypeError, ValueError):
        return None
    return None if pd.isna(numero) else numero


def _event_dict(row: Any) -> dict[str, Any]:
    """Linha do SQLite no contrato de evento de `docs/TASK_SPLIT.md`."""
    evento = {
        "event_id": row.event_id,
        "event_type": row.event_type,
        "timestamp": row.timestamp,
        "machine_id": row.machine_id,
        "segment_id": row.segment_id,
        "chainage_m": _number(row.chainage_m),
        "distance_to_axis_m": _number(row.distance_to_axis_m),
        "engine_on": bool(row.engine_on),
        "moving": bool(row.moving),
        "movement_m": _number(row.movement_m),
        "dwell_minutes": _number(row.dwell_minutes),
    }
    try:
        evento["context"] = json.loads(row.context or "{}")
    except (TypeError, json.JSONDecodeError):
        evento["context"] = {}
    return evento


class FieldAgent:
    """O agente de campo: um evento por vez, uma pergunta aberta por vez."""

    def __init__(self, index: ingest.ProjectIndex, bot: TelegramBot | None, chat_id: int | None):
        self.index = index
        self.bot = bot
        self.chat_id = chat_id
        self.lock = threading.Lock()
        self._warned_no_destination = False
        # Sobrevive ao reinicio do worker: a resposta que chegar depois continua com dono.
        self.pending: dict[str, Any] | None = storage.open_question()
        if self.pending:
            log.info("pergunta em aberto recuperada do banco: %s", self.pending.get("event_id"))

    # ---------------------------------------------------------------- eventos

    def simulated_now(self) -> pd.Timestamp:
        inicio, fim = self.index.day_bounds
        return replay.simulated_now(inicio, fim)

    def _machine_at(self, moment: pd.Timestamp) -> tuple[float, float] | None:
        telemetria = self.index.telemetry
        alcancado = telemetria[telemetria.timestamp <= moment]
        if alcancado.empty:
            return None
        ponto = alcancado.iloc[-1]
        return float(ponto.latitude), float(ponto.longitude)

    def tick(self) -> int:
        """Trata os eventos ja alcancados pelo relogio do replay. Devolve quantos."""
        if not self.bot or self.chat_id is None:
            # Sem chat para perguntar, tratar a fila so a esvaziaria: a acao ficaria
            # gravada, o evento sairia da fila e a pergunta que carrega a demonstracao
            # nunca seria feita. Melhor deixar tudo pendente ate a variavel chegar.
            if not self._warned_no_destination:
                log.error("TELEGRAM_CHAT_ID ausente: o agente nao trata a fila ate ter um chat")
                self._warned_no_destination = True
            return 0
        agora = self.simulated_now()
        fila = storage.pending_events(until=agora.isoformat())
        if fila.empty:
            return 0

        tratados = 0
        for row in fila.head(MAX_POR_RODADA).itertuples():
            if _stop_event.is_set():
                break
            self.handle_event(_event_dict(row))
            tratados += 1
        return tratados

    def handle_event(self, evento: dict[str, Any]) -> agent.Decision:
        # O que a maquina fez ate o evento, lido pelo Python. E o que faz a pergunta
        # dizer "trabalhou 3h entre as estacas 114 e 165" em vez de "houve um evento".
        ate_aqui = activity.until(self.index.episodes, pd.Timestamp(evento["timestamp"]))
        activity.attach_photos(ate_aqui, storage.photos_frame())
        evento.setdefault("context", {})["activity"] = activity.narrative(ate_aqui, brief=True)
        briefing, registro = tools.briefing(
            evento,
            project=self.index.project,
            location=self._machine_at(pd.Timestamp(evento["timestamp"])),
            activity_summary=activity.summary(ate_aqui),
        )
        decisao = agent.decide(evento, briefing=briefing, tool_calls=registro.calls)

        # Uma pergunta de cada vez: duas perguntas abertas tornam a resposta ambigua e a
        # confirmacao deixaria de poder apontar para um evento so. A excecao e o avanco sem
        # confirmacao: e a pergunta que a demonstracao — e a obra — existe para fazer, e
        # ela substitui qualquer pergunta menor que esteja esperando resposta.
        if decisao.expects_reply and self.pending and self._supersedes(evento):
            log.info(
                "%s substitui a pergunta em aberto (%s)",
                evento["event_id"],
                self.pending.get("event_id"),
            )
        elif decisao.expects_reply and self.pending:
            log.info(
                "pergunta ja aberta (%s); %s fica registrado sem perguntar",
                self.pending.get("event_id"),
                evento["event_id"],
            )
            decisao = agent.Decision(
                decision=agent.LOG,
                message="",
                confidence=decisao.confidence,
                rationale="pergunta anterior ainda sem resposta",
                tool_calls=decisao.tool_calls,
            )

        # Gravar antes de enviar: se o envio falhar, o evento ja saiu da fila e nao volta
        # como pergunta repetida quando o worker reiniciar.
        storage.record_agent_action(
            event_id=evento["event_id"],
            decision=decisao.decision,
            confidence=decisao.confidence,
            message=decisao.message or decisao.rationale,
            tool_calls=decisao.tool_calls,
        )
        log.info(
            "evento %s (%s) -> %s%s",
            evento["event_id"],
            evento["event_type"],
            decisao.decision,
            f" | {decisao.rationale}" if decisao.rationale else "",
        )

        if decisao.speaks:
            if self.send(decisao.message) and decisao.expects_reply:
                with self.lock:
                    self.pending = {
                        "event_id": evento["event_id"],
                        "event_type": evento.get("event_type"),
                        "message": decisao.message,
                        "segment_id": evento.get("segment_id"),
                    }
        return decisao

    def _supersedes(self, evento: dict[str, Any]) -> bool:
        pendente = self.pending or {}
        return (
            evento.get("event_type") == event_rules.PROGRESS_UNCONFIRMED
            and pendente.get("event_type") != event_rules.PROGRESS_UNCONFIRMED
        )

    # ---------------------------------------------------------------- Telegram

    def send(self, text: str) -> bool:
        if not self.bot or self.chat_id is None:
            log.warning("sem destino no Telegram (TELEGRAM_CHAT_ID ausente): %s", text)
            return False
        try:
            self.bot.send_message(self.chat_id, text)
            return True
        except Exception:
            log.exception("falha ao enviar mensagem no Telegram")
            return False

    def on_photo(self, message: dict[str, Any], photo: StoredPhoto) -> str:
        """Foto recebida: casa com o projeto, le e arquiva como evidencia."""
        colocacao = self.index.place_photo(photo.metadata, simulated_now=self.simulated_now())
        leitura = vision.classify(
            photo.path,
            context=(
                f"Maquina {config.machine_id} em "
                f"{colocacao.segment_id or 'fora do corredor do projeto'}"
                + (f", estaca {colocacao.chainage_m:.0f} m" if colocacao.chainage_m else "")
                + f", as {colocacao.captured_at:%H:%M} de {config.replay_date}."
            ),
        )
        registro = ingest.photo_record(
            colocacao,
            path=photo.path,
            source="telegram",
            visual_class=leitura.visual_class,
            confidence=leitura.confidence,
            visual_summary=leitura.summary if leitura.classified else None,
        )
        storage.record_photo(registro)
        log.info(
            "foto %s arquivada em %s (%s)",
            registro["photo_id"],
            colocacao.segment_id or "fora do corredor",
            leitura.visual_class or "sem leitura visual",
        )

        partes = [colocacao.describe(), leitura.describe()]
        episodio = next(
            (e for e in self.index.episodes if e.start <= colocacao.captured_at <= e.end), None
        )
        if episodio and episodio.state == activity.FRENTE:
            partes.append(f"Ela cai dentro de uma {episodio.describe()}: evidência de execução.")
        elif episodio:
            partes.append(f"Nesse instante a leitura da telemetria era: {episodio.describe()}.")
        if colocacao.anchored_to_replay:
            partes.append("Ancorada no instante do replay: a foto nao tem horario proprio.")
        if not self.pending and colocacao.segment_id:
            partes.append(
                f"Quantos metros de tubo estao assentados em {colocacao.segment_id} ate agora?"
            )
            with self.lock:
                self.pending = {
                    "event_id": None,
                    "message": "quantidade executada apos foto",
                    "segment_id": colocacao.segment_id,
                }
        return " ".join(p for p in partes if p)

    def status(self) -> str:
        """/status: que dia da obra esta em replay, o que a maquina faz e o que ja foi confirmado.

        E a resposta a "que dia e hoje?": o replay reproduz um dia de 2022 como se fosse
        agora, e o engenheiro precisa saber em que ponto dele a conversa esta.
        """
        agora = self.simulated_now()
        relogio = replay.load()
        inicio, fim = self.index.day_bounds
        estado = {replay.RUNNING: "em andamento", replay.PAUSED: "pausado", replay.STOPPED: "parado"}
        linhas = [
            f"Replay do dia {agora:%d/%m/%Y}, {estado.get(relogio.status, relogio.status)} "
            f"a {relogio.speed:g}x: {agora:%H:%M} na obra "
            f"(jornada {inicio:%H:%M}–{fim:%H:%M})."
        ]
        if relogio.status == replay.STOPPED:
            linhas.append("Nada aconteceu ainda: inicie o replay no painel.")
        ate_aqui = activity.until(self.index.episodes, agora)
        if ate_aqui:
            atual = ate_aqui[-1]
            linhas.append(f"Agora: {atual.describe()}.")
            linhas.append(f"Até aqui: {activity.narrative(ate_aqui, brief=True)}.")
        progresso = storage.confirmed_progress()
        for segmento in self.index.project.segments:
            planejado = float(segmento.attributes.get("planned_length_m") or 0)
            confirmado = 0.0
            if not progresso.empty and (progresso.segment_id == segmento.segment_id).any():
                confirmado = float(progresso[progresso.segment_id == segmento.segment_id].iloc[0].confirmed_length_m)
            linhas.append(
                f"{segmento.segment_id}: {confirmado:.0f} m confirmados de {planejado:.0f} m projetados."
            )
        with self.lock:
            pergunta = self.pending
        if pergunta:
            linhas.append(f"Pergunta em aberto: {pergunta.get('message')}")
        else:
            linhas.append("Nenhuma pergunta em aberto.")
        return "\n".join(linhas)

    def context(self) -> dict[str, Any]:
        """O que o agente sabe neste instante, para responder uma mensagem livre."""
        agora = self.simulated_now()
        ate_aqui = activity.until(self.index.episodes, agora)
        activity.attach_photos(ate_aqui, storage.photos_frame())
        resumo = activity.summary(ate_aqui)
        progresso = storage.confirmed_progress()
        confirmado = (
            progresso[["segment_id", "confirmed_length_m", "confirmations"]].to_dict("records")
            if not progresso.empty else []
        )
        with self.lock:
            pergunta = self.pending
        return {
            "dia_do_replay": f"{agora:%d/%m/%Y}",
            "hora_na_obra": f"{agora:%H:%M}",
            "replay": replay.load().status,
            "maquina": config.machine_id,
            "projeto": [
                {"trecho": seg.segment_id, "planejado_m": seg.attributes.get("planned_length_m"),
                 "diametro_mm": seg.attributes.get("diameter_mm"), "material": seg.attributes.get("material")}
                for seg in self.index.project.segments
            ],
            "agora": ate_aqui[-1].describe() if ate_aqui else "nada ainda",
            "horas_por_estado": resumo["hours"],
            "frentes_de_servico": [f["summary"] for f in resumo["fronts"] if f["minutes"] >= 5],
            "fotos_arquivadas": int(len(storage.photos_frame())),
            "confirmado": confirmado,
            "pergunta_em_aberto": (pergunta or {}).get("message"),
        }

    def on_text(self, message: dict[str, Any], text: str) -> str | None:
        """Texto do engenheiro: resposta a pergunta em aberto, ou conversa livre.

        Com pergunta em aberto, o texto e lido primeiro como resposta; so vira quantidade
        se for conclusivo. Sem pergunta, ou quando o texto nao responde a ela, o agente
        conversa a partir do que sabe — e o que sabe e o contexto deterministico, nada mais.
        """
        with self.lock:
            pergunta = self.pending
        if not pergunta:
            return agent.answer(text, context=self.context(), fallback=self.status())

        leitura = agent.read_reply(text, question=pergunta.get("message"))
        if not leitura.conclusive:
            # Nao respondeu a pergunta: pode ser uma pergunta dele. A pergunta continua
            # aberta — uma resposta ambigua nao pode virar registro — e o agente conversa.
            return agent.answer(
                text, context=self.context(),
                fallback=f"{leitura.acknowledgement}\n\nPergunta em aberto: {pergunta.get('message')}",
            )

        trecho = pergunta.get("segment_id")
        if not trecho:
            with self.lock:
                self.pending = None
            return "Registrado, mas sem trecho associado a essa pergunta."

        quem = (message.get("from") or {}).get("id")
        storage.record_confirmation(
            segment_id=trecho,
            status=leitura.status,
            confirmed_by=f"telegram:{quem}" if quem else "telegram:desconhecido",
            event_id=pergunta.get("event_id"),
            confirmed_length_m=leitura.confirmed_length_m,
            interruption_reason=leitura.interruption_reason,
            confirmed_at=self.simulated_now().isoformat(),
            raw_message=text,
        )
        storage.record_agent_action(
            event_id=pergunta.get("event_id"),
            decision="confirmed",
            message=text,
            tool_calls=[{"tool": "record_confirmation", "arguments": {
                "segment_id": trecho,
                "status": leitura.status,
                "confirmed_length_m": leitura.confirmed_length_m,
            }}],
        )
        with self.lock:
            self.pending = None

        estado = tools.segment_status(segment_id=trecho, project=self.index.project)
        resumo = ""
        if estado.get("planned_length_m"):
            resumo = (
                f" Total confirmado em {trecho}: {estado['confirmed_length_m']:.0f} m "
                f"de {estado['planned_length_m']:.0f} m projetados."
            )
        log.info("confirmacao gravada em %s por %s", trecho, quem)
        return f"{leitura.acknowledgement}{resumo}"


def _record_day(index: ingest.ProjectIndex) -> int:
    """Garante que os eventos do dia estao no banco antes de o agente consumir a fila."""
    casada = index.matcher.match_frame(index.telemetry)
    detectados = event_rules.detect(
        casada,
        machine_id=config.machine_id,
        long_dwell_minutes=config.long_dwell_minutes,
        dwell_movement_m=config.dwell_movement_m,
        gps_gap_minutes=config.gps_gap_minutes,
        outside_project_minutes=config.outside_project_minutes,
        project=index.project,
    )
    storage.initialize()
    novos = storage.record_events(detectados)
    log.info("%s eventos no dia, %s novos no banco", len(detectados), novos)
    return len(detectados)


def _destination() -> int | None:
    allowlist = parse_chat_allowlist(config.telegram_chat_id)
    return min(allowlist) if allowlist else None


def main() -> None:
    for sig in (signal.SIGINT, signal.SIGTERM):
        signal.signal(sig, _stop)

    log.info(
        "worker iniciado | maquina=%s | dia de replay=%s | velocidade=%sx | corredor=%sm",
        config.machine_id,
        config.replay_date,
        config.replay_speed,
        config.corridor_m,
    )

    index = ingest.ProjectIndex()
    _record_day(index)
    log.info(
        "projeto %s com %s trecho(s); modelo %s",
        config.project_kml_path.name,
        len(index.project.segments),
        config.llm_model if agent.llm.available() else "AUSENTE (regra deterministica)",
    )

    bot = None
    if config.telegram_bot_token:
        bot = TelegramBot(
            config.telegram_bot_token,
            photo_store=PhotoStore(config.photo_storage_path),
            allowed_chat_ids=parse_chat_allowlist(config.telegram_chat_id),
        )
    else:
        log.warning("TELEGRAM_BOT_TOKEN ausente: long polling desativado nesta execucao")

    campo = FieldAgent(index, bot, _destination())

    if bot:
        polling = threading.Thread(
            target=bot.run,
            args=(_stop_event,),
            kwargs={"on_photo": campo.on_photo, "on_text": campo.on_text, "on_status": campo.status},
            name="telegram",
            daemon=True,
        )
        polling.start()

    while not _stop_event.is_set():
        try:
            campo.tick()
        except Exception:
            log.exception("falha na rodada do agente")
        _stop_event.wait(config.agent_tick_seconds)

    log.info("worker encerrado")


if __name__ == "__main__":
    main()
