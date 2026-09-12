"""Cliente unico do modelo de linguagem e visao.

Um so lugar fala com o provedor. OpenRouter e OpenAI expoem a mesma rota
`/chat/completions`, entao trocar de provedor e trocar `LLM_PROVIDER`, nunca codigo.

Duas regras que este modulo impoe ao resto do sistema:

1. **Saida estruturada ou nada.** Toda chamada declara um JSON Schema. Texto livre do
   modelo nao vira registro no banco; o que nao encaixa no esquema e descartado com log.
2. **Indisponibilidade e um estado esperado.** Sem chave, sem credito ou com a API fora,
   `LLMUnavailable` sobe e quem chamou decide o fallback deterministico. A demonstracao
   precisa rodar mesmo com o modelo mudo.
"""
from __future__ import annotations

import base64
import json
import logging
import re
from pathlib import Path
from typing import Any

import requests

from machine2pipe.config import config

log = logging.getLogger(__name__)

ENDPOINTS = {
    "openrouter": "https://openrouter.ai/api/v1/chat/completions",
    "openai": "https://api.openai.com/v1/chat/completions",
}
TIMEOUT = 60


class LLMUnavailable(RuntimeError):
    """O modelo nao pode ser consultado agora. Quem chamou segue no deterministico."""


def api_key() -> str:
    if config.llm_provider == "openai":
        return config.openai_api_key
    return config.openrouter_api_key or config.openai_api_key


def available() -> bool:
    return bool(api_key())


def image_part(path: Path, *, media_type: str = "image/jpeg") -> dict[str, Any]:
    """Anexa a imagem em base64. Nao ha URL publica para as fotos de campo."""
    encoded = base64.b64encode(Path(path).read_bytes()).decode()
    return {"type": "image_url", "image_url": {"url": f"data:{media_type};base64,{encoded}"}}


def text_part(text: str) -> dict[str, Any]:
    return {"type": "text", "text": text}


def _extract_json(content: str) -> dict[str, Any]:
    """Aceita tanto JSON puro quanto JSON dentro de cerca de codigo."""
    content = content.strip()
    if content.startswith("```"):
        content = re.sub(r"^```[a-zA-Z]*\n|\n```$", "", content).strip()
    try:
        return json.loads(content)
    except json.JSONDecodeError:
        abre, fecha = content.find("{"), content.rfind("}")
        if abre >= 0 and fecha > abre:
            try:
                return json.loads(content[abre : fecha + 1])
            except json.JSONDecodeError:
                pass
    raise LLMUnavailable(f"resposta do modelo nao e JSON: {content[:200]!r}")


def structured(
    messages: list[dict[str, Any]],
    *,
    schema: dict[str, Any],
    schema_name: str,
    max_tokens: int = 700,
    temperature: float = 0.0,
) -> dict[str, Any]:
    """Faz a chamada e devolve o objeto ja validado contra o esquema pedido."""
    chave = api_key()
    if not chave:
        raise LLMUnavailable(
            "nenhuma chave de modelo no container: defina OPENROUTER_API_KEY ou OPENAI_API_KEY"
        )

    cabecalhos = {"Authorization": f"Bearer {chave}", "Content-Type": "application/json"}
    if config.llm_provider == "openrouter":
        # Identifica o app no ranking do OpenRouter; nenhum dado de campo vai nisso.
        cabecalhos["X-Title"] = "Machine2Pipe AI"
        cabecalhos["HTTP-Referer"] = "https://github.com/CAIOZANETTI/machine2pipe-ai"

    corpo = {
        "model": config.llm_model,
        "messages": messages,
        "max_tokens": max_tokens,
        "temperature": temperature,
        "response_format": {
            "type": "json_schema",
            "json_schema": {"name": schema_name, "strict": True, "schema": schema},
        },
    }
    endpoint = ENDPOINTS.get(config.llm_provider, ENDPOINTS["openrouter"])

    try:
        resposta = requests.post(endpoint, headers=cabecalhos, json=corpo, timeout=TIMEOUT)
    except requests.RequestException as erro:
        raise LLMUnavailable(f"falha de rede ao chamar o modelo: {erro}") from erro

    if resposta.status_code != 200:
        # 401 chave errada, 402 credito esgotado, 429 limite. Todos levam ao mesmo lugar:
        # o deterministico assume e a mensagem fica no log para o operador.
        raise LLMUnavailable(
            f"modelo recusou a chamada ({resposta.status_code}): {resposta.text[:200]}"
        )

    payload = resposta.json()
    escolhas = payload.get("choices") or []
    if not escolhas:
        raise LLMUnavailable(f"resposta sem conteudo: {payload.get('error') or payload}")
    return _extract_json(escolhas[0]["message"]["content"] or "")
