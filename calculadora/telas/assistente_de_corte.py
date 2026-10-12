"""Assistente de corte (M1) — fluxo interno passo a passo.

Substitui o trabalho manual de caçar e recortar as peças de um processo:

  1 · Subir     → 1 PDF do processo completo.
  2 · Cortar    → o radar SUGERE as faixas (conta homologada, ofício); o advogado
                  confirma/ajusta/rotula. (o radar sugere, quem decide é o humano.)
  3 · Extrair   → a máquina lê cada corte (tipo já conhecido): valores + prova
                  aritmética + citação + honorários por regex.
  4 · Calcular  → abre a calculadora já pré-preenchida (o advogado revisa e calcula).

Determinístico até o corte (custo zero); o LLM só roda na extração dos cortes
CONFIRMADOS. Beta: sobe a árvore só quando o time validar. Precisa da env
`OPENROUTER_API_KEY` (ou `DEEPSEEK_API_KEY`) para a etapa de extração.
"""
from __future__ import annotations

import os

import streamlit as st

from ponte import url_calculadora
from prefill import rejeitados as _rej




from prefill.pipeline import (
    TIPO_CONTA,
    TIPO_OFICIO,
    TIPOS,
    analisar,
    extrair_cortes,
)

st.title("✂️ Assistente de corte")
st.caption(
    "Suba o processo, confirme onde estão a **conta homologada** e o **ofício**, e a máquina "
    "extrai os valores e abre a calculadora pré-preenchida. O radar **sugere** — quem decide "
    "o corte é você."
)


def _reset_analise() -> None:
    for k in ("asst_meta", "asst_paginas", "asst_resultado", "asst_cortes",
              "asst_prev", "asst_prev_sel", "asst_ver_cit", "asst_baixar"):
        st.session_state.pop(k, None)


def _bump_editor() -> None:
    """Aposenta a versão atual do data_editor (o Streamlit faz GC do estado do
    widget não-renderizado). Chamado quando a SEMENTE do editor muda (nova
    análise ou confirmação) — senão os deltas da edição anterior se re-aplicariam
    sobre a nova semente e DUPLICARIAM linhas adicionadas."""
    st.session_state["asst_editor_v"] = st.session_state.get("asst_editor_v", 0) + 1


# ───────────────────────── 1 · Subir ─────────────────────────
st.subheader("1 · Subir o processo")
# a chave do uploader é versionada p/ o "Recomeçar" conseguir DESCARREGAR o PDF
# antigo (senão um novo "Analisar" re-rodaria no arquivo velho ainda carregado).
_upn = st.session_state.get("asst_upload_n", 0)
_up = st.file_uploader("PDF do processo completo", type=["pdf"], key=f"asst_pdf_{_upn}")
if _up is not None and st.button("Analisar e sugerir cortes", type="primary", key="asst_analisar"):
    _bytes = _up.getvalue()
    with st.spinner("Lendo o processo e localizando conta e ofício (sem custo de IA)…"):
        try:
            _an = analisar(pdf_bytes=_bytes)
        except Exception as _e:  # noqa: BLE001 — leitura de PDF não pode derrubar a UI
            _an = None
            st.error(f"Não consegui analisar o PDF: {type(_e).__name__}: {str(_e)[:200]}")
    if _an is not None:
        _reset_analise()
        _bump_editor()  # editor fresco p/ as novas sugestões (sem deltas do processo anterior)
        st.session_state["asst_pdf_bytes"] = _bytes
        st.session_state["asst_pdf_nome"] = _up.name
        st.session_state["asst_paginas"] = _an.pop("paginas")
        st.session_state["asst_meta"] = _an
        st.rerun()

_meta = st.session_state.get("asst_meta")
_pdf_bytes = st.session_state.get("asst_pdf_bytes")

# ───────────────────────── 2 · Cortar ─────────────────────────
if _meta:
    _h = _meta.get("homologacao")
    _homol_txt = (
        f"homologação na pág {_h['pagina']}"
        + (f" (Evento {_h['evento']})" if _h.get("evento") else "")
        if _h else "homologação não localizada"
    )
    st.subheader("2 · Confirme os cortes")
    st.caption(
        f"**{_meta['n_paginas']}** páginas · **{_meta['escaneadas']}** escaneadas · {_homol_txt}. "
        "Ajuste as faixas abaixo, rotule cada uma e remova o que não for usar."
    )
    if _meta["escaneadas"]:
        st.warning(
            f"⚠️ {_meta['escaneadas']} página(s) escaneada(s) não foram lidas por OCR neste "
            "ambiente — o radar pode não tê-las sugerido. Confira se as faixas cobrem a conta certa."
        )

    # semente = o último corte CONFIRMADO (durável, sobrevive ao switch_page e ao
    # GC do widget) se houver; senão as sugestões do radar. Sem isso, ao voltar da
    # calculadora o editor reverteria às sugestões e um novo "Confirmar" extrairia
    # a faixa ERRADA em silêncio.
    _seed = (
        st.session_state.get("asst_cortes")
        or st.session_state["asst_meta"]["cortes_sugeridos"]
        or [{"tipo": TIPO_CONTA, "pagina_inicio": 1, "pagina_fim": 1}]
    )
    _cortes = st.data_editor(
        _seed,
        key=f"asst_editor_{st.session_state.get('asst_editor_v', 0)}",
        num_rows="dynamic",
        width="stretch",
        column_config={
            "tipo": st.column_config.SelectboxColumn(
                "Tipo da peça", options=TIPOS, required=True, width="medium"),
            "pagina_inicio": st.column_config.NumberColumn(
                "Pág. inicial", min_value=1, max_value=_meta["n_paginas"], step=1, required=True),
            "pagina_fim": st.column_config.NumberColumn(
                "Pág. final", min_value=1, max_value=_meta["n_paginas"], step=1, required=True),
        },
    )

    # faixas válidas (linhas completas, dentro do documento)
    _validos = [
        c for c in _cortes
        if c.get("pagina_inicio") and c.get("pagina_fim") and c.get("tipo")
    ]

    # preview de borda: renderiza só as páginas de início/fim de UMA faixa escolhida
    if _validos and _pdf_bytes and st.checkbox("👁️ Ver páginas de borda (conferir o corte)", key="asst_prev"):
        from prefill.viewer import render_pagina
        # rotula por IDENTIDADE (não por índice posicional): se a lista encolher, o
        # Streamlit reseta p/ um rótulo VÁLIDO e a legenda casa com o preview.
        _rotulos = [f"{i}. {c['tipo']} · pp{int(c['pagina_inicio'])}-{int(c['pagina_fim'])}"
                    for i, c in enumerate(_validos)]
        _escolha = st.selectbox("Qual faixa conferir?", _rotulos, key="asst_prev_sel")
        _c = _validos[_rotulos.index(_escolha)] if _escolha in _rotulos else _validos[0]
        _a, _b = int(_c["pagina_inicio"]), int(_c["pagina_fim"])
        _col1, _col2 = st.columns(2)
        for _col, _pg, _lbl in ((_col1, _a, "início"), (_col2, _b, "fim")):
            with _col:
                _png = render_pagina(_pdf_bytes, _pg)
                if _png:
                    st.image(_png, caption=f"pág {_pg} ({_lbl})", width="stretch")

    _tem_conta = any(c["tipo"] == TIPO_CONTA for c in _validos)
    if not _tem_conta:
        st.info("Marque ao menos uma faixa como **Conta homologada** para extrair.")

    if st.button("Confirmar cortes e extrair", type="primary", disabled=not _tem_conta,
                 key="asst_extrair"):
        # persiste o corte confirmado ANTES de extrair (fonte durável do seed) e
        # aposenta o editor (assa os deltas na semente, sem duplicar linhas).
        st.session_state["asst_cortes"] = _validos
        _bump_editor()
        with st.spinner("Extraindo os valores dos cortes (conta + ofício)…"):
            try:
                _res = extrair_cortes(
                    st.session_state["asst_paginas"], _validos, homol=_meta.get("homologacao"))
            except Exception as _e:  # noqa: BLE001 — rede/LLM instável não derruba a UI
                _res = {"ok": False, "erro": f"{type(_e).__name__}: {str(_e)[:200]}"}
        st.session_state["asst_resultado"] = _res
        st.rerun()

# ───────────────────────── 3 · Extrair / revisar ─────────────────────────
_res = st.session_state.get("asst_resultado")
if _res is not None:
    st.subheader("3 · Revise os valores")
    if not _res.get("ok"):
        st.error(f"Não consegui extrair: {_res.get('erro')}")
    else:
        _p = _res["prova"]
        _sel = {
            True: "✅ a conta fecha (Principal + Juros + Selic = Total)",
            False: f"⚠️ NÃO fecha (dif {_p.get('dif_pct')}%) — confira os valores",
            None: "prova não aplicável (principal/total ausentes)",
        }[_p.get("ok")]
        _of = f" · ofício {_res['oficio_ref']}" if _res.get("oficio_ref") else ""
        st.caption(f"Conta **{_res['conta_ref']}**{_of} · {_sel} · custo ${_res['custo']}")

        if _res.get("multi_conta"):
            st.warning("Você marcou **mais de uma** conta homologada. A calculadora usa "
                       "**um crédito por vez** — extraí a primeira. Reordene/remova se for outra.")
        if _res.get("multi_oficio"):
            st.info("Mais de um ofício marcado — usei o primeiro para os honorários/modalidade.")

        for _k, _d in _res["campos"].items():
            _c = _d.get("citacao") or {}
            _pg = _c.get("pagina")
            st.markdown(f"• **{_k}** = `{_d['valor']}`" + (f"  — pág {_pg}" if _pg else ""))

        for _cf in (_res.get("conflitos") or []):
            st.error(f"⚠️ **{_cf['campo']}**: a IA leu `{_cf['llm']}`, o regex leu "
                     f"`{_cf['regex']}` (pág {_cf['pagina']}) — confira qual está certo.")

        # valores RECUSADOS (não existem na conta) — mesmo aviso da pré-análise
        _usados = _rej.mostrar(st, _res.get("rejeitados"), "asst")

        st.warning("Valores por IA + regex — **confira cada um contra o PDF antes de calcular.**")

        # visualizador: páginas citadas com o valor destacado
        if _pdf_bytes and _res.get("citacoes") and st.checkbox(
                "📄 Ver as páginas citadas (com o valor destacado)", key="asst_ver_cit"):
            from prefill.viewer import render_paginas
            _dest = {int(k): v for k, v in _res["citacoes"].items()}
            for _img in render_paginas(_pdf_bytes, _dest):
                st.image(_img["png"],
                         caption=f"pág {_img['pagina']} — {_img['n_marcas']} valor(es) destacado(s)",
                         width="stretch")

        # ───────── 4 · Calcular / baixar cortes ─────────
        st.subheader("4 · Calcular")
        st.caption("Abra a calculadora já pré-preenchida. Confira PSS/IR (selecione o modo "
                   "'Valor no ofício' para aplicá-los) e clique em Calcular.")
        # LINK, não troca de aba: a calculadora é outra APLICAÇÃO (outro
        # processo, outra porta) — é o que impede um erro aqui de derrubar o
        # cálculo do time. Os valores viajam na query string, que é o
        # mecanismo que a calculadora já consome.
        st.link_button("🧮 Abrir na calculadora com estes valores",
                       url_calculadora(_rej.aplicar(_res["query"], _res.get("rejeitados"), _usados)),
                       type="primary",
                       use_container_width=True)

        # baixar os cortes físicos (peças fatiadas) — úteis para arquivo / Bitrix (M2)
        # só as peças MARCADAS PARA USO (conta/ofício) — 'Outro / não usar' não vira corte.
        _cortes = [c for c in (st.session_state.get("asst_cortes") or [])
                   if c.get("tipo") in (TIPO_CONTA, TIPO_OFICIO)]
        if _pdf_bytes and _cortes and st.checkbox("✂️ Baixar as peças recortadas (PDF)", key="asst_baixar"):
            from prefill.cortar import cortar_pdf
            for _j, _peca in enumerate(cortar_pdf(_pdf_bytes, _cortes, _meta["n_paginas"])):
                st.download_button(
                    f"⬇️ {_peca['nome']}  ({_peca['n_paginas']} pág)",
                    data=_peca["pdf_bytes"], file_name=_peca["nome"], mime="application/pdf",
                    key=f"asst_dl_{_j}")

st.divider()
if st.button("↺ Recomeçar (novo processo)", key="asst_reset"):
    _reset_analise()
    st.session_state.pop("asst_pdf_bytes", None)
    st.session_state.pop("asst_pdf_nome", None)
    st.session_state["asst_upload_n"] = _upn + 1  # descarrega o PDF do uploader
    st.rerun()
