"""O agente: decide o que fazer com um evento e le a resposta do engenheiro.

Duas funcoes, uma fronteira. `decide` escolhe entre ignorar, registrar, avisar e perguntar,
e escreve a mensagem. `read_reply` transforma a resposta em portugues num registro
estruturado. Nenhuma das duas calcula quantidade: a primeira so pergunta, a segunda so
extrai o que a pessoa escreveu.

O guarda-costas central esta em `read_reply`: um comprimento so e aceito se os digitos
estiverem no texto do engenheiro. Se o modelo devolver 32 m e ninguem tiver escrito 32, o
numero e descartado e a confirmacao fica sem quantidade. Uma quantidade inventada entraria
no painel como fato e nao ha como desfazer isso depois.

Sem chave de modelo tudo continua funcionando em regra deterministica: a demonstracao nao
pode depender de credito de API.
"""
from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from typing import Any

from machine2pipe import events as event_rules
from machine2pipe import llm
from machine2pipe.config import config
from machine2pipe.storage import VALID_STATUS

log = logging.getLogger(__name__)

IGNORE, LOG, NOTIFY, ASK = "ignore", "log", "notify", "ask"
DECISIONS = [IGNORE, LOG, NOTIFY, ASK]

# Que decisao cada tipo de evento merece quando o modelo nao esta disponivel. E tambem o
# piso: o modelo pode subir de `log` para `ask`, mas nao pode silenciar o que a regra
# deterministica considera digno de pergunta.
FALLBACK = {
    event_rules.PROGRESS_UNCONFIRMED: ASK,
    event_rules.LONG_DWELL: ASK,
    event_rules.UNEXPECTED_SEGMENT: NOTIFY,
    event_rules.OUTSIDE_PROJECT: NOTIFY,
    event_rules.GPS_GAP: LOG,
    event_rules.ENTERED_SEGMENT: LOG,
    event_rules.LEFT_SEGMENT: LOG,
}

DECISION_SCHEMA = {
    "type": "object",
    "properties": {
        "decision": {"type": "string", "enum": DECISIONS},
        "message": {
            "type": "string",
            "description": "Mensagem em portugues para o engenheiro. Vazia se decision for ignore ou log.",
        },
        "confidence": {"type": "number", "minimum": 0, "maximum": 1},
        "rationale": {"type": "string", "description": "Uma frase: por que essa decisao."},
    },
    "required": ["decision", "message", "confidence", "rationale"],
    "additionalProperties": False,
}

REPLY_SCHEMA = {
    "type": "object",
    "properties": {
        "confirmed_length_m": {
            "type": ["number", "null"],
            "description": "So se a pessoa escreveu o numero. Nunca estime.",
        },
        "status": {"type": "string", "enum": sorted(VALID_STATUS) + ["unclear"]},
        "interruption_reason": {"type": ["string", "null"]},
        "acknowledgement": {"type": "string", "description": "Resposta curta em portugues."},
    },
    "required": ["confirmed_length_m", "status", "interruption_reason", "acknowledgement"],
    "additionalProperties": False,
}

DECISION_PROMPT = """Voce e o agente de campo do Machine2Pipe AI, acompanhando uma obra de
drenagem: assentamento de tubo de concreto DN400. A telemetria real da retroescavadeira ja
foi processada em Python e produziu o evento abaixo. Os numeros do evento e do briefing sao
definitivos: nao recalcule, nao arredonde e nao invente nenhum.

Escolha uma decisao:
- ignore: irrelevante para o registro da obra.
- log: registra e segue, sem incomodar ninguem.
- notify: o engenheiro precisa saber, mas nao ha nada a responder.
- ask: so o engenheiro pode fechar a informacao que falta.

Use ask quando houver avanco de servico sem quantidade confirmada, ou uma parada longa sem
motivo conhecido. O campo context.activity e a leitura de comportamento feita pelo Python
(frentes de servico com faixa de estacas, horas, fotos como evidencia): cite-a na pergunta,
porque e o que mostra ao engenheiro que voce sabe o que a maquina fez. Nao pergunte o que a telemetria ja respondeu. Uma pergunta por evento, em
portugues do Brasil, curta, citando trecho e estaca, e pedindo exatamente um dado: metros
executados ou motivo da interrupcao. Trate o engenheiro como colega, sem formalidade vazia."""

REPLY_PROMPT = """Extraia da resposta do engenheiro apenas o que ele escreveu. Regras:
- confirmed_length_m so existe se a pessoa escreveu o numero. Caso contrario, null.
- "terminei o trecho" nao e um numero: status completed, confirmed_length_m null.
- status unclear quando a resposta nao permitir concluir nada.
- interruption_reason so se houver motivo declarado (chuva, quebra, falta de material).
- acknowledgement: uma frase curta confirmando o que foi registrado, em portugues."""


@dataclass(frozen=True)
class Decision:
    decision: str
    message: str
    confidence: float | None
    rationale: str
    tool_calls: list[dict[str, Any]] = field(default_factory=list)

    @property
    def speaks(self) -> bool:
        """A decisao produz mensagem no Telegram?"""
        return self.decision in {NOTIFY, ASK} and bool(self.message)

    @property
    def expects_reply(self) -> bool:
        return self.decision == ASK


@dataclass(frozen=True)
class ReplyReading:
    confirmed_length_m: float | None
    status: str
    interruption_reason: str | None
    acknowledgement: str
    from_model: bool

    @property
    def conclusive(self) -> bool:
        return self.status in VALID_STATUS


def _quantity(value: Any) -> float | None:
    """Numero utilizavel numa frase, ou nada. NaN nao e numero para o engenheiro."""
    try:
        numero = float(value)
    except (TypeError, ValueError):
        return None
    return None if numero != numero else numero  # NaN e o unico valor diferente de si


def _short(event: dict[str, Any]) -> str:
    """O evento em uma linha legivel, do jeito que a pergunta vai cita-lo."""
    momento = str(event.get("timestamp", ""))[11:16]
    trecho = event.get("segment_id") or "fora do corredor"
    estaca = _quantity(event.get("chainage_m"))
    local = f"{trecho}, estaca {estaca:.0f} m" if estaca is not None else trecho
    return f"{event.get('event_type')} as {momento} em {local}"


def default_message(event: dict[str, Any], decision: str) -> str:
    """Mensagem deterministica, usada sem modelo e como rede se o modelo devolver vazio."""
    momento = str(event.get("timestamp", ""))[11:16]
    trecho = event.get("segment_id") or "trecho nao identificado"
    estaca = _quantity(event.get("chainage_m"))
    onde = f"{trecho} (estaca {estaca:.0f} m)" if estaca is not None else trecho
    tipo = event.get("event_type")
    parada = _quantity(event.get("dwell_minutes")) or 0.0

    if decision == ASK and tipo == event_rules.PROGRESS_UNCONFIRMED:
        leitura = (event.get("context") or {}).get("activity")
        if leitura and not leitura.startswith("nenhuma"):
            return (
                f"Leitura da telemetria em {trecho}: {leitura}. Nada foi confirmado ate agora. "
                "Quantos metros de tubo foram assentados?"
            )
        return (
            f"A maquina trabalhou em {onde} e nada foi confirmado ate agora. "
            "Quantos metros de tubo foram assentados nesse trecho?"
        )
    if decision == ASK and tipo == event_rules.LONG_DWELL:
        return (
            f"Parada de {parada:.0f} min com motor ligado em {onde}. "
            "Foi execucao de servico ou interrupcao? Se foi interrupcao, qual o motivo?"
        )
    if decision == ASK:
        return f"Evento {tipo} em {onde} as {momento}. Pode confirmar o que aconteceu?"
    if tipo == event_rules.OUTSIDE_PROJECT:
        # O evento pode nascer com a parada ainda em zero; citar "ha 0 min" soaria errado.
        desde = f"ha {parada:.0f} min" if parada >= 1 else f"desde as {momento}"
        return (
            f"A maquina saiu do corredor de {config.corridor_m:.0f} m do projeto {desde}. "
            "Sem impacto no registro por enquanto."
        )
    if tipo == event_rules.UNEXPECTED_SEGMENT:
        return f"Atividade registrada em {onde}, que nao estava previsto para hoje."
    return f"{_short(event)}."


def decide(
    event: dict[str, Any],
    *,
    briefing: dict[str, Any] | None = None,
    tool_calls: list[dict[str, Any]] | None = None,
) -> Decision:
    """Decide o que fazer com um evento ja detectado pelo motor deterministico."""
    piso = FALLBACK.get(str(event.get("event_type")), LOG)
    registro = list(tool_calls or [])

    if not llm.available():
        return Decision(
            decision=piso,
            message=default_message(event, piso) if piso in {NOTIFY, ASK} else "",
            confidence=None,
            rationale="regra deterministica: nenhum modelo configurado",
            tool_calls=registro,
        )

    conteudo = (
        f"{DECISION_PROMPT}\n\nEvento:\n{json.dumps(event, ensure_ascii=False, default=str)}"
        f"\n\nBriefing deterministico:\n{json.dumps(briefing or {}, ensure_ascii=False, default=str)}"
    )
    try:
        dados = llm.structured(
            [{"role": "user", "content": conteudo}],
            schema=DECISION_SCHEMA,
            schema_name="decisao_do_agente",
            max_tokens=400,
        )
    except llm.LLMUnavailable as erro:
        log.warning("decisao pelo modelo indisponivel (%s); usando regra deterministica", erro)
        return Decision(
            decision=piso,
            message=default_message(event, piso) if piso in {NOTIFY, ASK} else "",
            confidence=None,
            rationale=f"regra deterministica: {erro}",
            tool_calls=registro,
        )

    escolha = str(dados.get("decision", "")).strip()
    if escolha not in DECISIONS:
        escolha = piso
    # O modelo pode elevar o cuidado, nunca reduzi-lo abaixo da regra: se o motor achou que
    # o evento merece pergunta, silencia-lo perderia a unica chance de confirmar o servico.
    if DECISIONS.index(escolha) < DECISIONS.index(piso):
        log.info("decisao do modelo (%s) abaixo do piso (%s); mantendo o piso", escolha, piso)
        escolha = piso

    mensagem = str(dados.get("message", "")).strip()
    if escolha in {NOTIFY, ASK} and not mensagem:
        mensagem = default_message(event, escolha)
    try:
        confianca = max(0.0, min(1.0, float(dados.get("confidence", 0))))
    except (TypeError, ValueError):
        confianca = None

    return Decision(
        decision=escolha,
        message=mensagem if escolha in {NOTIFY, ASK} else "",
        confidence=confianca,
        rationale=str(dados.get("rationale", "")).strip(),
        tool_calls=registro,
    )


NUMBER = re.compile(r"(\d+(?:[.,]\d+)?)\s*(?:m\b|metros?\b)", re.IGNORECASE)
BARE_NUMBER = re.compile(r"\b(\d+(?:[.,]\d+)?)\b")
REASONS = {
    "chuva": "chuva",
    "chove": "chuva",
    "quebr": "quebra de equipamento",
    "pane": "quebra de equipamento",
    "manuten": "manutencao",
    "material": "falta de material",
    "combust": "falta de combustivel",
    "almoc": "intervalo",
    "espera": "espera",
}


def _stated_length(text: str) -> float | None:
    """O comprimento que a pessoa escreveu, se escreveu. Preferimos o numero com unidade."""
    achado = NUMBER.search(text) or BARE_NUMBER.search(text)
    if not achado:
        return None
    try:
        return float(achado.group(1).replace(",", "."))
    except ValueError:
        return None


def _digits_in_text(value: float, text: str) -> bool:
    """O numero aceito precisa estar escrito na mensagem, em metros ou solto."""
    inteiro = f"{value:.0f}"
    decimal = f"{value:.2f}".rstrip("0").rstrip(".")
    limpo = text.replace(",", ".")
    return any(forma and forma in limpo for forma in (inteiro, decimal))


def _rule_reading(text: str) -> ReplyReading:
    """Leitura deterministica da resposta. Tambem e a rede de seguranca do modelo."""
    baixo = text.lower()
    comprimento = _stated_length(text)
    motivo = next((rotulo for chave, rotulo in REASONS.items() if chave in baixo), None)

    if motivo or any(p in baixo for p in ("parad", "interromp", "nao trabalh", "não trabalh")):
        status = "interrupted"
    elif any(p in baixo for p in ("conclu", "termin", "finaliz", "acab")):
        status = "completed"
    elif comprimento is not None:
        status = "partially_completed"
    elif any(p in baixo for p in ("nao comec", "não comec", "nao inici", "não inici")):
        status = "not_started"
    else:
        status = "unclear"

    if status == "unclear":
        reconhecimento = "Nao consegui extrair a informacao. Pode responder com os metros executados ou o motivo da parada?"
    elif comprimento is not None:
        reconhecimento = f"Registrado: {comprimento:g} m, status {status}."
    else:
        reconhecimento = f"Registrado: status {status}, sem quantidade informada."

    return ReplyReading(
        confirmed_length_m=comprimento,
        status=status,
        interruption_reason=motivo,
        acknowledgement=reconhecimento,
        from_model=False,
    )


def read_reply(text: str, *, question: str | None = None) -> ReplyReading:
    """Le a resposta do engenheiro. O numero aceito e sempre o que ele escreveu."""
    texto = (text or "").strip()
    if not texto:
        return _rule_reading("")
    if not llm.available():
        return _rule_reading(texto)

    conteudo = REPLY_PROMPT
    if question:
        conteudo += f"\n\nPergunta enviada:\n{question}"
    conteudo += f"\n\nResposta do engenheiro:\n{texto}"

    try:
        dados = llm.structured(
            [{"role": "user", "content": conteudo}],
            schema=REPLY_SCHEMA,
            schema_name="leitura_da_resposta",
            max_tokens=300,
        )
    except llm.LLMUnavailable as erro:
        log.warning("leitura da resposta pelo modelo indisponivel: %s", erro)
        return _rule_reading(texto)

    status = str(dados.get("status", "unclear"))
    if status not in VALID_STATUS and status != "unclear":
        status = "unclear"

    comprimento = dados.get("confirmed_length_m")
    try:
        comprimento = float(comprimento) if comprimento is not None else None
    except (TypeError, ValueError):
        comprimento = None
    # A guarda que importa: quantidade sem origem no texto da pessoa nao entra no banco.
    if comprimento is not None and not _digits_in_text(comprimento, texto):
        log.warning("comprimento %s nao aparece na resposta; descartado", comprimento)
        comprimento = None
    if comprimento is not None and comprimento < 0:
        comprimento = None

    reconhecimento = str(dados.get("acknowledgement", "")).strip()
    return ReplyReading(
        confirmed_length_m=comprimento,
        status=status,
        interruption_reason=(dados.get("interruption_reason") or None),
        acknowledgement=reconhecimento or _rule_reading(texto).acknowledgement,
        from_model=True,
    )
