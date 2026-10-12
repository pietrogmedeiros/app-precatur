"""Pré-análise — aplicação SEPARADA da calculadora.

Por que dois apps e não duas abas do mesmo:

  RITMO      a calculadora é estável e usada todo dia; esta tela vai mudar
             muito nas próximas semanas. Juntas, cada ajuste aqui reiniciava o
             serviço e derrubava a sessão de quem estava calculando.
  RAIO       aqui se abrem PDFs de centenas de páginas (e, em breve, OCR). Um
             pico de memória ou um erro não tratado mataria o processo que
             serve a calculadora. Separados, o pior caso é esta tela cair.

O que continua compartilhado é o CÓDIGO (mesmo repositório: `prefill`, `auth`,
`estado`, `bitrix`, `hub`) — o que se separa é o PROCESSO.

A ponte com a calculadora é um LINK com os valores na query string, que é o
mecanismo que ela já consome. `CALCULADORA_URL` aponta para lá; sem ela, cai em
"/" (mesmo host), que é como o Caddy publica a calculadora.
"""
from __future__ import annotations

import os

import streamlit as st

from auth import mostrar_usuario, require_password
from estado import manter as _manter_estado

st.set_page_config(page_title="Precatur — Pré-análise", page_icon="📥", layout="centered")
require_password()
mostrar_usuario()
_manter_estado()

# Trava de beta mantida: publicar o código não expõe a ferramenta ao time antes
# da hora. Vive na ENTRADA, então vale para as duas telas de uma vez.
if os.environ.get("PREFILL_ENABLED") != "1":
    st.title("📥 Pré-análise")
    st.info("Ferramenta em beta, desligada neste ambiente (`PREFILL_ENABLED`).")
    st.stop()

_paginas = [
    st.Page("telas/pre_analise.py", title="Pré-análise", icon="📥", default=True),
    st.Page("telas/assistente_de_corte.py", title="Assistente de corte", icon="✂️"),
]
st.navigation(_paginas).run()
