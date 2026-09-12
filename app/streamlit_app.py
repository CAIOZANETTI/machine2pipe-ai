"""Painel publico: mapa do projeto, trilha da maquina, eventos e progresso confirmado."""
from __future__ import annotations

import pandas as pd
import plotly.express as px
import streamlit as st

from machine2pipe.config import config
from machine2pipe.telemetry import loader

st.set_page_config(page_title="Machine2Pipe AI", page_icon="🚜", layout="wide")


@st.cache_data(show_spinner="Carregando telemetria real...")
def carregar_dia(dia: str) -> pd.DataFrame:
    return loader.load_day(dia)


st.title("🚜 Machine2Pipe AI")
st.caption(
    "Telemetria real de uma JCB 3CX em obra de drenagem — Calmon/SC, 2022. "
    "O Python calcula a evidencia; o agente interpreta e pede confirmacao no Telegram."
)

with st.sidebar:
    st.header("Controle da simulação")
    dia = st.text_input("Dia do replay", value=config.replay_date)
    st.metric("Velocidade", f"{config.replay_speed:g}×")
    st.caption(f"Máquina: {config.machine_id}")
    st.caption(f"CRS métrico: {config.target_crs}")
    st.caption(f"Corredor do projeto: {config.corridor_m:g} m")

try:
    df = carregar_dia(dia)
except Exception as exc:  # a origem e externa: a falha precisa aparecer, nao sumir
    st.error(f"Não foi possível carregar a telemetria: {exc}")
    st.stop()

if df.empty:
    st.warning(f"Sem telemetria para {dia}.")
    st.stop()

ligado = df[df.engine_on]
jornada = (
    (ligado.timestamp.max() - ligado.timestamp.min()).total_seconds() / 3600
    if len(ligado) > 1
    else 0.0
)

c1, c2, c3, c4 = st.columns(4)
c1.metric("Pontos de telemetria", len(df))
c2.metric("Jornada com motor ligado", f"{jornada:.1f} h")
c3.metric("Deslocamento no dia", f"{df.movement_m.sum() / 1000:.2f} km")
c4.metric("Pontos sem GPS válido", int((~df.gps_valid).sum()))

st.subheader("Trilha da máquina")
fig = px.scatter_map(
    df,
    lat="latitude",
    lon="longitude",
    color="engine_on",
    hover_data={"timestamp": True, "event_type": True, "movement_m": True},
    zoom=14,
    height=520,
    color_discrete_map={True: "#e8590c", False: "#868e96"},
    labels={"engine_on": "Motor ligado"},
)
fig.update_layout(map_style="open-street-map", margin=dict(l=0, r=0, t=0, b=0))
st.plotly_chart(fig, use_container_width=True)

st.subheader("Atividades declaradas pelo rastreador")
st.dataframe(
    df.event_type.value_counts().rename_axis("atividade").reset_index(name="ocorrências"),
    hide_index=True,
    use_container_width=True,
)

st.info(
    "Próximas etapas: projeto em KML, casamento com o trecho, eventos determinísticos, "
    "agente no Telegram e progresso confirmado.",
    icon="🚧",
)
