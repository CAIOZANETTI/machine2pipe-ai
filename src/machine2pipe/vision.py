"""Classificacao visual da foto de campo, com confianca declarada.

O que o modelo pode dizer: o que aparece na imagem e com que certeza. O que ele nao pode:
quanto foi executado, qual a profundidade da vala ou qual o diametro real do tubo. Presenca
nao e quantidade, e uma imagem sem escala nao mede nada. Por isso o esquema so tem classe,
confianca e descricao — nao ha campo onde uma quantidade caberia.

A classe entra no banco como evidencia, nunca como prova: `requires_confirmation` continua
1 para toda foto, e so a resposta do engenheiro fecha quantidade.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path

from machine2pipe import llm

log = logging.getLogger(__name__)

CLASSES = [
    "pipe_installation",   # tubo sendo assentado ou ja assentado na vala
    "trench_open",         # vala aberta, sem tubo visivel
    "trench_backfill",     # reaterro ou compactacao
    "material_on_site",    # tubos, brita ou material estocado
    "machine_operating",   # maquina trabalhando, servico nao identificavel
    "site_context",        # foto do local sem servico identificavel
    "unrelated",           # nao e foto de obra
]

SCHEMA = {
    "type": "object",
    "properties": {
        "visual_class": {"type": "string", "enum": CLASSES},
        "confidence": {"type": "number", "minimum": 0, "maximum": 1},
        "summary": {"type": "string", "description": "Uma frase em portugues do que se ve."},
        "pipe_visible": {"type": "boolean"},
    },
    "required": ["visual_class", "confidence", "summary", "pipe_visible"],
    "additionalProperties": False,
}

PROMPT = (
    "Voce analisa fotos de uma obra de drenagem: assentamento de tubo de concreto DN400 "
    "em vala. Classifique a imagem em uma das classes e de sua confianca honesta. "
    "Nunca estime comprimento executado, profundidade ou diametro: a imagem nao tem escala "
    "e essas quantidades vem da telemetria ou do engenheiro. Se a foto nao permitir "
    "identificar o servico, use site_context ou unrelated com confianca baixa."
)


@dataclass(frozen=True)
class VisualReading:
    visual_class: str | None
    confidence: float | None
    summary: str
    pipe_visible: bool = False

    @property
    def classified(self) -> bool:
        return self.visual_class is not None

    def describe(self) -> str:
        if not self.classified:
            return self.summary
        return f"{self.summary} ({self.visual_class}, confianca {self.confidence:.0%})"


UNREAD = VisualReading(
    visual_class=None,
    confidence=None,
    summary="Foto arquivada sem leitura visual: o modelo nao esta disponivel.",
)


def classify(path: Path, *, context: str = "") -> VisualReading:
    """Le a foto. Se o modelo nao responder, devolve `UNREAD` em vez de levantar.

    A evidencia ja esta salva e casada com o trecho antes desta chamada; a leitura visual
    e um enriquecimento, e perde-la nao pode derrubar a ingestao.
    """
    if not llm.available():
        return UNREAD

    partes = [llm.text_part(PROMPT)]
    if context:
        partes.append(llm.text_part(f"Contexto da telemetria: {context}"))
    partes.append(llm.image_part(Path(path)))

    try:
        dados = llm.structured(
            [{"role": "user", "content": partes}],
            schema=SCHEMA,
            schema_name="leitura_visual",
            max_tokens=300,
        )
    except llm.LLMUnavailable as erro:
        log.warning("leitura visual indisponivel: %s", erro)
        return UNREAD
    except Exception:
        log.exception("falha inesperada na leitura visual")
        return UNREAD

    classe = str(dados.get("visual_class", ""))
    if classe not in CLASSES:
        log.warning("classe visual fora do contrato: %r", classe)
        return UNREAD
    try:
        confianca = max(0.0, min(1.0, float(dados.get("confidence", 0))))
    except (TypeError, ValueError):
        confianca = 0.0
    return VisualReading(
        visual_class=classe,
        confidence=confianca,
        summary=str(dados.get("summary", "")).strip() or "Sem descricao.",
        pipe_visible=bool(dados.get("pipe_visible")),
    )
