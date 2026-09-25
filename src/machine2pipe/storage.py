"""Persistencia SQLite dos eventos, evidencias fotograficas e progresso confirmado.

WAL e obrigatorio: o worker escreve enquanto o painel le, e sem ele o Streamlit
encontraria `database is locked` no meio da demonstracao.

Nenhuma quantidade e gravada sem uma fonte humana. `record_confirmation` exige
`confirmed_by`, e esse campo guarda a pessoa, nunca o modelo.
"""
from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable, Iterator

import pandas as pd

from machine2pipe.config import config
from machine2pipe.events import Event

SCHEMA = """
CREATE TABLE IF NOT EXISTS events (
    event_id            TEXT PRIMARY KEY,
    event_type          TEXT NOT NULL,
    timestamp           TEXT NOT NULL,
    machine_id          TEXT NOT NULL,
    segment_id          TEXT,
    chainage_m          REAL,
    distance_to_axis_m  REAL,
    engine_on           INTEGER NOT NULL,
    moving              INTEGER NOT NULL,
    movement_m          REAL NOT NULL,
    dwell_minutes       REAL NOT NULL,
    context             TEXT NOT NULL DEFAULT '{}'
);

CREATE TABLE IF NOT EXISTS photo_evidence (
    photo_id                TEXT PRIMARY KEY,
    captured_at             TEXT,
    received_at             TEXT NOT NULL,
    latitude                REAL,
    longitude               REAL,
    segment_id              TEXT,
    chainage_m              REAL,
    distance_to_segment_m   REAL,
    telemetry_delta_seconds REAL,
    visual_class            TEXT,
    confidence              REAL,
    requires_confirmation   INTEGER NOT NULL DEFAULT 1,
    source                  TEXT NOT NULL DEFAULT 'telegram',
    file_path               TEXT
);

CREATE TABLE IF NOT EXISTS confirmations (
    confirmation_id     INTEGER PRIMARY KEY AUTOINCREMENT,
    event_id            TEXT,
    machine_id          TEXT NOT NULL,
    segment_id          TEXT NOT NULL,
    confirmed_length_m  REAL,
    status              TEXT NOT NULL,
    interruption_reason TEXT,
    confirmed_by        TEXT NOT NULL,
    source              TEXT NOT NULL DEFAULT 'telegram',
    confirmed_at        TEXT NOT NULL,
    raw_message         TEXT
);

CREATE TABLE IF NOT EXISTS agent_actions (
    action_id   INTEGER PRIMARY KEY AUTOINCREMENT,
    event_id    TEXT,
    decision    TEXT NOT NULL,
    confidence  REAL,
    message     TEXT,
    tool_calls  TEXT NOT NULL DEFAULT '[]',
    created_at  TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_events_segment ON events(segment_id);
CREATE INDEX IF NOT EXISTS idx_confirmations_segment ON confirmations(segment_id);
"""

VALID_STATUS = {"completed", "partially_completed", "not_started", "interrupted"}


class StorageError(ValueError):
    """Tentativa de gravar um registro que quebraria a auditoria."""


@contextmanager
def connect(database_path: Path | None = None) -> Iterator[sqlite3.Connection]:
    path = Path(database_path or config.database_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(path, timeout=30)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA journal_mode=WAL")
    connection.execute("PRAGMA busy_timeout=30000")
    try:
        yield connection
        connection.commit()
    finally:
        connection.close()


# Colunas acrescentadas depois do primeiro deploy. O banco vive num volume e nao e recriado,
# entao cada uma e adicionada se faltar; `ALTER TABLE ... ADD COLUMN` e idempotente assim.
MIGRATIONS = [
    ("photo_evidence", "visual_summary", "TEXT"),
]


def initialize(database_path: Path | None = None) -> None:
    with connect(database_path) as connection:
        connection.executescript(SCHEMA)
        for table, column, kind in MIGRATIONS:
            existentes = {row[1] for row in connection.execute(f"PRAGMA table_info({table})")}
            if column not in existentes:
                connection.execute(f"ALTER TABLE {table} ADD COLUMN {column} {kind}")


def record_events(events: Iterable[Event], database_path: Path | None = None) -> int:
    """Grava eventos de forma idempotente: reexecutar o replay nao duplica nada."""
    rows = [
        (
            e.event_id, e.event_type, e.timestamp.isoformat(), e.machine_id, e.segment_id,
            e.chainage_m, e.distance_to_axis_m, int(e.engine_on), int(e.moving),
            e.movement_m, e.dwell_minutes, json.dumps(e.context, default=str),
        )
        for e in events
    ]
    if not rows:
        return 0
    with connect(database_path) as connection:
        before = connection.execute("SELECT COUNT(*) FROM events").fetchone()[0]
        connection.executemany(
            "INSERT OR IGNORE INTO events VALUES (?,?,?,?,?,?,?,?,?,?,?,?)", rows
        )
        return connection.execute("SELECT COUNT(*) FROM events").fetchone()[0] - before


def record_photo(photo: dict[str, Any], database_path: Path | None = None) -> None:
    columns = [
        "photo_id", "captured_at", "received_at", "latitude", "longitude", "segment_id",
        "chainage_m", "distance_to_segment_m", "telemetry_delta_seconds", "visual_class",
        "confidence", "requires_confirmation", "source", "file_path", "visual_summary",
    ]
    if not photo.get("photo_id"):
        raise StorageError("photo_id e obrigatorio")
    photo.setdefault("received_at", datetime.now().isoformat())
    values = [photo.get(column) for column in columns]
    with connect(database_path) as connection:
        connection.execute(
            f"INSERT OR REPLACE INTO photo_evidence ({','.join(columns)}) "
            f"VALUES ({','.join('?' * len(columns))})",
            values,
        )


def update_photo_reading(
    photo_id: str,
    *,
    visual_class: str | None,
    confidence: float | None,
    visual_summary: str | None,
    database_path: Path | None = None,
) -> None:
    """Grava a leitura visual de uma foto ja arquivada. A geometria da foto nao muda."""
    with connect(database_path) as connection:
        connection.execute(
            "UPDATE photo_evidence SET visual_class = ?, confidence = ?, visual_summary = ?"
            " WHERE photo_id = ?",
            (visual_class, confidence, visual_summary, photo_id),
        )


def delete_photo(photo_id: str, database_path: Path | None = None) -> str | None:
    """Retira uma foto da evidencia e devolve o caminho do arquivo, ou None se nao existia.

    Existe para a foto errada que chegou pelo Telegram: sem ela, a unica saida era zerar a
    conversa inteira. Uma foto do album volta no proximo deploy, porque a carga e refeita.
    """
    with connect(database_path) as connection:
        row = connection.execute(
            "SELECT file_path FROM photo_evidence WHERE photo_id = ?", (photo_id,)
        ).fetchone()
        if row is None:
            return None
        connection.execute("DELETE FROM photo_evidence WHERE photo_id = ?", (photo_id,))
    return row["file_path"] or ""


def record_confirmation(
    *,
    segment_id: str,
    status: str,
    confirmed_by: str,
    machine_id: str | None = None,
    event_id: str | None = None,
    confirmed_length_m: float | None = None,
    interruption_reason: str | None = None,
    source: str = "telegram",
    confirmed_at: datetime | str | None = None,
    raw_message: str | None = None,
    database_path: Path | None = None,
) -> None:
    """Grava uma quantidade confirmada por uma pessoa.

    Chamada pelo lado do agente. Sem `confirmed_by` nao ha registro: uma quantidade sem
    fonte humana nao entra no banco, porque o painel nao poderia defende-la depois.
    """
    if not confirmed_by:
        raise StorageError("confirmed_by e obrigatorio: nenhuma quantidade sem fonte humana")
    if status not in VALID_STATUS:
        raise StorageError(f"status invalido: {status!r}; esperado um de {sorted(VALID_STATUS)}")
    if confirmed_length_m is not None and confirmed_length_m < 0:
        raise StorageError("confirmed_length_m nao pode ser negativo")

    moment = confirmed_at or datetime.now()
    with connect(database_path) as connection:
        connection.execute(
            "INSERT INTO confirmations (event_id, machine_id, segment_id, confirmed_length_m,"
            " status, interruption_reason, confirmed_by, source, confirmed_at, raw_message)"
            " VALUES (?,?,?,?,?,?,?,?,?,?)",
            (
                event_id, machine_id or config.machine_id, segment_id, confirmed_length_m,
                status, interruption_reason, confirmed_by, source,
                moment.isoformat() if isinstance(moment, datetime) else str(moment),
                raw_message,
            ),
        )


def record_agent_action(
    *,
    decision: str,
    event_id: str | None = None,
    confidence: float | None = None,
    message: str | None = None,
    tool_calls: list[dict] | None = None,
    database_path: Path | None = None,
) -> None:
    """Registra a decisao do agente e as ferramentas que ele chamou, para auditoria."""
    with connect(database_path) as connection:
        connection.execute(
            "INSERT INTO agent_actions (event_id, decision, confidence, message, tool_calls,"
            " created_at) VALUES (?,?,?,?,?,?)",
            (event_id, decision, confidence, message,
             json.dumps(tool_calls or [], default=str), datetime.now().isoformat()),
        )


def _frame(query: str, parameters: tuple = (), database_path: Path | None = None) -> pd.DataFrame:
    with connect(database_path) as connection:
        return pd.DataFrame([dict(row) for row in connection.execute(query, parameters)])


def events_frame(database_path: Path | None = None) -> pd.DataFrame:
    return _frame("SELECT * FROM events ORDER BY timestamp", database_path=database_path)


def photos_frame(database_path: Path | None = None) -> pd.DataFrame:
    return _frame("SELECT * FROM photo_evidence ORDER BY captured_at", database_path=database_path)


def agent_actions_frame(database_path: Path | None = None) -> pd.DataFrame:
    return _frame("SELECT * FROM agent_actions ORDER BY action_id", database_path=database_path)


def confirmations_frame(database_path: Path | None = None) -> pd.DataFrame:
    return _frame("SELECT * FROM confirmations ORDER BY confirmed_at", database_path=database_path)


def confirmed_progress(database_path: Path | None = None) -> pd.DataFrame:
    """Total confirmado por trecho, com o numero de confirmacoes que o sustenta."""
    return _frame(
        "SELECT segment_id, SUM(COALESCE(confirmed_length_m, 0)) AS confirmed_length_m,"
        " COUNT(*) AS confirmations, MAX(confirmed_at) AS last_confirmed_at"
        " FROM confirmations GROUP BY segment_id ORDER BY segment_id",
        database_path=database_path,
    )


def pending_events(
    until: str | None = None, database_path: Path | None = None
) -> pd.DataFrame:
    """Eventos que o agente ainda nao tratou, em ordem cronologica.

    Um evento e considerado tratado quando existe uma acao do agente para ele. E assim
    que o loop evita perguntar duas vezes a mesma coisa quando o replay e reiniciado.
    """
    query = (
        "SELECT e.* FROM events e"
        " LEFT JOIN agent_actions a ON a.event_id = e.event_id"
        " WHERE a.action_id IS NULL"
    )
    parameters: tuple = ()
    if until:
        query += " AND e.timestamp <= ?"
        parameters = (until,)
    return _frame(query + " ORDER BY e.timestamp", parameters, database_path)


def open_question(database_path: Path | None = None) -> dict[str, Any] | None:
    """A ultima pergunta feita pelo agente que ainda nao recebeu confirmacao.

    O worker reinicia — deploy, queda, `supervise_worker` — e o engenheiro nao tem por que
    saber disso. Sem esta consulta a resposta que chega depois do reinicio ficaria orfa e a
    confirmacao perderia o `event_id` que a torna auditavel.
    """
    with connect(database_path) as connection:
        row = connection.execute(
            "SELECT a.event_id, a.message, e.segment_id, e.event_type FROM agent_actions a"
            " LEFT JOIN events e ON e.event_id = a.event_id"
            " WHERE a.decision = 'ask'"
            "   AND NOT EXISTS (SELECT 1 FROM confirmations c WHERE c.event_id = a.event_id)"
            " ORDER BY a.action_id DESC LIMIT 1"
        ).fetchone()
    return dict(row) if row else None


def reset_demo(database_path: Path | None = None) -> dict[str, int]:
    """Apaga o que a conversa produziu, para a demonstracao poder ser gravada de novo.

    `pending_events` foi desenhada para nao repetir pergunta quando o replay reinicia; a
    consequencia e que o segundo ensaio do video nao tem pergunta nenhuma. Esta e a unica
    porta que limpa decisoes, confirmacoes e fotos vindas do Telegram. Os eventos ficam:
    sao deterministicos e voltariam identicos. As fotos do album ficam: sao dado historico.
    """
    with connect(database_path) as connection:
        contagem = {
            "agent_actions": connection.execute("DELETE FROM agent_actions").rowcount,
            "confirmations": connection.execute("DELETE FROM confirmations").rowcount,
            "telegram_photos": connection.execute(
                "DELETE FROM photo_evidence WHERE source LIKE 'telegram%'"
            ).rowcount,
        }
    return contagem


def handled_event_ids(database_path: Path | None = None) -> set[str]:
    frame = _frame("SELECT DISTINCT event_id FROM agent_actions WHERE event_id IS NOT NULL",
                   database_path=database_path)
    return set(frame.event_id) if not frame.empty else set()


def confirmed_segment_ids(database_path: Path | None = None) -> set[str]:
    frame = confirmations_frame(database_path)
    return set(frame.segment_id) if not frame.empty else set()
