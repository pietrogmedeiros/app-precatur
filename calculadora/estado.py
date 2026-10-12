"""Mantém o formulário vivo quando o advogado troca de aba.

O Streamlit faz GC do estado dos widgets que NÃO foram renderizados na execução
anterior. Num app de uma página só isso é invisível; com abas, sair da
calculadora apaga o formulário inteiro — medido com AppTest: `vt` sai do
`session_state` na aba vizinha e volta VAZIO, levando junto o resultado.

Reatribuir a chave a cada execução mantém o valor vivo. Roda em TODAS as
páginas e ANTES de qualquer widget: o descarte acontece na página que não
renderiza o widget, e `session_state` só aceita escrita antes de o widget ser
criado.

⚠ LISTA EXPLÍCITA, não varredura. Reatribuir tudo estoura em `file_uploader`
(`Values for the widget with key '_prefill_pdf' cannot be set using
st.session_state`) — e o erro não aparece na atribuição, e sim depois, quando o
uploader é criado. Chave nova no formulário precisa ser adicionada aqui.
"""
from __future__ import annotations

import streamlit as st

# campos de TEXTO do formulário da calculadora (os que o advogado digita)
CAMPOS = (
    "vt", "vp", "vj", "vs", "vo", "vbr",   # valores do crédito
    "pss", "ir",                           # PSS / IR (não `apss`: tem
                                           # `value=` e reatribuir só gera aviso)
    "hc", "hs",                            # honorários
    "sp_val",                              # superpreferência (valor)
    "ente_outro", "ref", "obs",            # metadados do memorial
    "bx_deal", "bx_num_oficio", "bx_num_precatorio",   # dados do card
    "pre_deal",                            # busca do card na pré-análise
)


def manter() -> None:
    for chave in CAMPOS:
        if chave in st.session_state:
            try:
                st.session_state[chave] = st.session_state[chave]
            except Exception:  # noqa: BLE001 — widget já instanciado nesta execução
                pass
