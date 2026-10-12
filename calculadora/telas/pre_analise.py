"""Pré-análise — o jurídico anexa as peças JÁ RECORTADAS.

  1 · Anexar   → cálculo homologado (a CONTA) + ofício requisitório, cada um no
                 seu campo. Não há processo completo, então não há radar nem
                 juiz: cada peça É o corte.
  2 · Revisar  → valores extraídos, cada um com o TRECHO de onde saiu, mais a
                 prova aritmética. Aqui é onde o advogado corrige.
  3 · Calcular → abre a calculadora pré-preenchida (o advogado calcula e gera o
                 memorial).

Por que o passo 2 não é opcional (medido em 47 casos reais, 05/08/2026):
`valor_total` NÃO é um conceito só. A prova P+J+S=T fecha em 36% das contas —
e quando não fecha, quase sempre a extração está certa e o total é que é outra
coisa: "TOTAL GERAL" que soma a verba do advogado, "Líquido Devido ao
Reclamante" já sem PSS/IR, "Total Devido pelo Reclamado" com encargos. Em 24
dos 29 casos que não fecharam o total vinha MAIOR que as parcelas, mediana
+9,09% — que é quanto a oferta subiria usando o número cru. Por isso esta tela
mostra o TRECHO de cada citação: é ele que denuncia qual conceito foi capturado.

Beta, atrás de `PREFILL_ENABLED=1`. Precisa de `OPENROUTER_API_KEY` (ou
`DEEPSEEK_API_KEY`) para a extração.
"""
from __future__ import annotations

import os

import streamlit as st

import bitrix as _crm
import hub as _hub
from ponte import url_calculadora
from prefill import rejeitados as _rej




from prefill.pipeline import (
    TIPO_CONTA,
    TIPO_OFICIO,
    TIPO_SENTENCA,
    extrair_pecas,
)

st.title("📥 Pré-análise")
st.caption(
    "Informe o card, anexe as peças já recortadas, e a máquina lê os valores e abre a "
    "calculadora preenchida — **você confere e ajusta antes de calcular.**"
)

_ESTADO = ("pre_res", "pre_conta_bytes", "pre_oficio_bytes", "pre_sent_bytes",
           "pre_ver_cit", "pre_card", "pre_caso", "pre_retomado")


def _juntar_pdfs(pdfs: list[bytes]) -> bytes:
    """Vários PDFs num só (para o hub, que guarda um documento por tipo)."""
    if len(pdfs) == 1:
        return pdfs[0]
    import fitz  # noqa: PLC0415 — só carrega quando há mais de uma peça
    saida = fitz.open()
    for b in pdfs:
        with fitz.open(stream=b, filetype="pdf") as d:
            saida.insert_pdf(d)
    dados = saida.tobytes()
    saida.close()
    return dados


def _reset() -> None:
    for k in _ESTADO:
        st.session_state.pop(k, None)


# ───────────────────────── 1 · Card ─────────────────────────
# Pedir o card ANTES de extrair não é burocracia: é o que traz os dois campos
# que o processo não tem (honorário contratual e nº do precatório) e o que dá
# um lugar para o caso morar — sem isso, fechar o navegador perde tudo,
# inclusive os PDFs que o advogado subiu.
st.subheader("1 · Card do CRM")
if not _crm.habilitado():
    st.info("Sem CRM configurado neste ambiente — siga direto para os anexos.")
else:
    # O advogado não decora número de negócio. Ele tem o NOME do cliente, o CPF,
    # ou o card aberto no navegador — a tela aceita qualquer um dos três.
    # LINK DIRETO: `?card=2273` abre a tela já no card certo. É o que permite o
    # advogado sair da tarefa (ou do card) e cair aqui sem digitar nada — sem
    # esse degrau, qualquer link vira "abra a ferramenta e procure de novo".
    _card_url = (st.query_params.get("card") or "").strip()
    if _card_url and "pre_deal" not in st.session_state:
        st.session_state["pre_deal"] = _card_url

    _cc1, _cc2 = st.columns([3, 1])
    _busca = _cc1.text_input("Cliente, CPF ou link do card", key="pre_deal",
                             placeholder="ex.: Maria Simulada · 123.456.789-00 · "
                                         "ou cole o link do card")
    _ok = _cc2.button("Abrir caso", key="pre_abrir_caso", use_container_width=True)
    _id_direto = _crm.resolver_id(_busca)

    # Sem ID direto, procura no CRM e deixa o advogado escolher pelo NOME —
    # a memória da equipe é "#ID Nome", nunca o número sozinho.
    _escolhido = _id_direto
    if not _id_direto and len((_busca or "").strip()) >= 3:
        try:
            _achados = _crm.buscar_cards(_busca)
        except Exception as _e:  # noqa: BLE001
            _achados = []
            st.error(f"Busca falhou: {type(_e).__name__}")
        if not _achados:
            st.caption("Nenhum card encontrado no funil "
                       f"{_crm.categoria_permitida()} com esse nome/CPF.")
        else:
            _rotulos = [f"#{c['id']} {c['titulo']}" for c in _achados]
            _sel = st.selectbox(f"{len(_achados)} card(s) encontrado(s) — escolha:",
                                _rotulos, key="pre_escolha")
            _escolhido = _achados[_rotulos.index(_sel)]["id"] if _sel in _rotulos else None

    # veio por link e ainda não abriu: abre sozinho, senão o advogado teria de
    # clicar num botão só para confirmar o que o link já disse
    _auto = bool(_card_url) and _id_direto and not st.session_state.get("pre_card")
    if _ok or _auto:
        if not _escolhido:
            st.error("Informe o cliente, o CPF ou o link do card.")
        else:
            try:
                _card = _crm.resumo_do_card(int(_escolhido))
            except Exception as _e:  # noqa: BLE001
                st.error(f"{type(_e).__name__}: {_e}")
            else:
                st.session_state["pre_card"] = _card
                if _hub.habilitado():
                    try:
                        st.session_state["pre_caso"] = _hub.abrir_caso(
                            _card["id"], _card["titulo"] or f"card {_card['id']}",
                            _card["url"])
                    except Exception as _e:  # noqa: BLE001 — hub fora não impede analisar
                        st.session_state["pre_caso"] = None
                        st.warning(f"Caso não foi aberto no hub ({type(_e).__name__}). "
                                   "A análise segue, mas nada fica guardado.")
                st.rerun()

_card = st.session_state.get("pre_card")
if _card:
    st.markdown(f"**#{_card['id']} {_card['titulo']}** · funil {_card['funil']} · "
                f"etapa `{_card['etapa']}` · [abrir no CRM]({_card['url']})")
    if _card["funil"] != str(_crm.categoria_permitida()):
        st.warning(f"⚠️ Este card está no funil {_card['funil']}. Este ambiente só "
                   f"ESCREVE no funil {_crm.categoria_permitida()} — dá para analisar, "
                   "mas o envio ao card vai ser recusado.")
    _do_card = []
    if _card["honorarios_contratuais_pct"]:
        _do_card.append(f"honorários contratuais **{_card['honorarios_contratuais_pct']}%**")
    if _card["numero_precatorio"]:
        _do_card.append(f"nº do precatório **{_card['numero_precatorio']}**")
    st.caption(("Do card: " + " · ".join(_do_card)) if _do_card else
               "O card não traz honorários contratuais nem nº do precatório — "
               "se os documentos também não trouxerem, o valor final será o BRUTO.")
    # O hub é ARMÁRIO, não tela: o advogado nunca sai daqui. Guardar serve para
    # RETOMAR — fechar o navegador no meio não pode custar subir tudo de novo.
    _caso = st.session_state.get("pre_caso")
    if _caso:
        try:
            _guardados = _hub.documentos_do_caso(_caso["id"])
        except Exception:  # noqa: BLE001 — hub fora não trava a tela
            _guardados = []
        if _guardados and not st.session_state.get("pre_conta_bytes"):
            st.info("📁 Este card já tem uma pré-análise guardada: "
                    + ", ".join(f"**{d['peca']}** ({d['nome']})" for d in _guardados))
            if st.button("Retomar de onde parei", key="pre_retomar",
                         use_container_width=True):
                _sents = []
                with st.spinner("Trazendo os PDFs guardados…"):
                    for _d in _guardados:
                        _b = _hub.baixar_documento(_caso["id"], _d["id"])
                        if _d["peca"] == "conta":
                            st.session_state["pre_conta_bytes"] = _b
                        elif _d["peca"] == "oficio":
                            st.session_state["pre_oficio_bytes"] = _b
                        else:
                            _sents.append(_b)
                st.session_state["pre_sent_bytes"] = _sents
                st.session_state["pre_retomado"] = [d["nome"] for d in _guardados]
                st.rerun()
        elif _guardados:
            st.caption(f"Guardado no caso `{_caso['id'][:8]}`: "
                       + ", ".join(d["peca"] for d in _guardados))

# ───────────────────────── 2 · Anexar ─────────────────────────
st.subheader("2 · Anexar as peças")
_n = st.session_state.get("pre_upload_n", 0)
_c1, _c2 = st.columns(2)
_up_conta = _c1.file_uploader("Cálculo homologado (a CONTA)", type=["pdf"], key=f"pre_conta_{_n}")
_up_oficio = _c2.file_uploader("Ofício requisitório (opcional)", type=["pdf"], key=f"pre_oficio_{_n}")
_up_sent = st.file_uploader(
    "Sentença / acórdão (opcional — pode anexar mais de um)", type=["pdf"],
    accept_multiple_files=True, key=f"pre_sent_{_n}")

st.caption(
    "A **conta** é obrigatória: é dela que saem os valores. O **ofício** entra com "
    "honorários, modalidade, ente devedor e data de apresentação. A **sentença/acórdão** "
    "serve a uma coisa só: dizer a **natureza do crédito** quando a conta não diz — e só "
    "é lida nesse caso."
)

# Upload novo vence; na falta dele, vale o que já está na sessão — que pode ter
# vindo de um upload anterior ou do "Retomar". Sem isso, retomar traria os PDFs
# de volta e o botão continuaria desabilitado, porque o uploader está vazio.
_cb_atual = _up_conta.getvalue() if _up_conta is not None else st.session_state.get("pre_conta_bytes")
_ob_atual = _up_oficio.getvalue() if _up_oficio is not None else st.session_state.get("pre_oficio_bytes")
_sb_atual = ([f.getvalue() for f in _up_sent] if _up_sent
             else (st.session_state.get("pre_sent_bytes") or []))

if st.session_state.get("pre_retomado"):
    st.success("✅ Retomado: " + ", ".join(st.session_state["pre_retomado"])
               + " — não precisa anexar de novo (só se quiser trocar alguma peça).")

if st.button("Extrair valores", type="primary", disabled=_cb_atual is None, key="pre_extrair"):
    _cb, _ob, _sb = _cb_atual, _ob_atual, _sb_atual
    with st.spinner("Lendo as peças e extraindo os valores…"):
        try:
            _r = extrair_pecas(conta=_cb, oficio=_ob, sentencas=_sb)
        except Exception as _e:  # noqa: BLE001 — rede/LLM instável não derruba a UI
            _r = {"ok": False, "erro": type(_e).__name__, "detalhe": str(_e)[:200]}
    # COMPLETAR pelo card o que os documentos não trouxeram. Precedência fixa:
    # documento > card. O documento é a fonte primária; o card é o que o humano
    # digitou, e serve de rede — nunca por cima do que foi lido dos autos.
    _card_atual = st.session_state.get("pre_card")
    _r["do_card"] = []
    if _r.get("ok") and _card_atual:
        _q = _r["query"]
        if not _q.get("hc") and _card_atual["honorarios_contratuais_pct"]:
            _q["hc"] = _card_atual["honorarios_contratuais_pct"]
            _r["do_card"].append(f"honorários contratuais {_q['hc']}% (do card)")
        if not _q.get("numero_precatorio") and _card_atual["numero_precatorio"]:
            _q["numero_precatorio"] = _card_atual["numero_precatorio"]
            _r["do_card"].append(f"nº do precatório {_q['numero_precatorio']} (do card)")
            if _q.get("ref"):
                _q["ref"] = f"{_q['ref']} — {_q['numero_precatorio']}"

    # GUARDAR no hub: o caso passa a existir depois do navegador fechar.
    #
    # ⚠ Abre o caso AQUI se ainda não existe. Com as apps separadas, os PDFs não
    # atravessam para a calculadora pela sessão — o caso é o único transporte.
    # Depender de o advogado ter clicado em "Abrir caso" antes fez o card do
    # teste receber o valor e o memorial, mas NENHUM corte.
    _caso_atual = st.session_state.get("pre_caso")
    _card_atual = st.session_state.get("pre_card")
    if not _caso_atual and _card_atual and _hub.habilitado():
        try:
            _caso_atual = _hub.abrir_caso(_card_atual["id"],
                                          _card_atual["titulo"] or f"card {_card_atual['id']}",
                                          _card_atual["url"])
            st.session_state["pre_caso"] = _caso_atual
        except Exception:  # noqa: BLE001 — hub fora não impede analisar
            _caso_atual = None
    _r["guardados"] = []
    if _caso_atual and _hub.habilitado():
        _pecas_hub = [("conta", "calculo_homologado.pdf", _cb)]
        if _ob:
            _pecas_hub.append(("oficio", "oficio.pdf", _ob))
        if _sb:
            # O hub guarda UM documento avulso por tipo. Mandar só a primeira
            # perderia as outras no "Retomar" — e foi o que aconteceu no teste:
            # o card recebeu uma sentença em vez de três. Juntar num PDF só
            # preserva TODAS as páginas; ao card, quando a sessão está viva, elas
            # vão separadas (o campo de anexo lá é múltiplo).
            _pecas_hub.append(("sentenca", "sentencas.pdf", _juntar_pdfs(_sb)))
        for _peca, _nome, _dados in _pecas_hub:
            try:
                _hub.guardar_documento(_caso_atual["id"], _peca, _nome, _dados)
                _r["guardados"].append(_peca)
            except Exception as _e:  # noqa: BLE001 — hub fora não perde a análise
                _r.setdefault("falha_hub", []).append(f"{_peca}: {type(_e).__name__}")

    st.session_state["pre_res"] = _r
    st.session_state["pre_conta_bytes"] = _cb
    st.session_state["pre_oficio_bytes"] = _ob
    st.session_state["pre_sent_bytes"] = _sb
    st.rerun()

# ───────────────────────── 2 · Revisar ─────────────────────────
_res = st.session_state.get("pre_res")
if _res is not None:
    st.divider()
    st.subheader("3 · Revise os valores")

    if not _res.get("ok"):
        _erro = _res.get("erro")
        if _erro == "conta_escaneada":
            from prefill import ocr as _ocr_mod
            _motivo = ("o OCR está DESLIGADO ou indisponível neste ambiente"
                       if not _ocr_mod.disponivel()
                       else "nem o OCR conseguiu extrair texto desta imagem")
            st.error(
                f"**A conta é uma imagem** ({_res.get('chars', 0)} caracteres "
                f"extraíveis) e {_motivo}. Cerca de 1 em cada 5 contas é assim.\n\n"
                "Saídas: anexar uma versão com texto (o mesmo processo às vezes tem "
                "as duas), ou digitar os valores direto na calculadora."
            )
        elif _erro == "sem_conta":
            st.error("Anexe o **cálculo homologado** — o ofício sozinho não traz os valores.")
        else:
            st.error(f"Não consegui extrair: {_erro} — {_res.get('detalhe') or ''}")
    else:
        _campos = _res["campos"]
        _p = _res["prova"]

        # ── a prova, com a conta na tela ──────────────────────────────────
        # Não basta dizer "não fecha": o advogado precisa ver a diferença E as
        # duas causas prováveis, que são as que a medição encontrou.
        def _f(k):
            v = (_campos.get(k) or {}).get("valor")
            return v if v not in (None, "") else "—"

        if _p.get("ok") is True:
            st.success(f"✅ A conta fecha: {_f('valor_principal')} + {_f('valor_juros')} + "
                       f"{_f('valor_selic')} = **{_f('valor_total')}**")
        elif _p.get("ok") is False:
            _soma, _tot = _p.get("soma"), _p.get("total")
            _sobra = (_tot or 0) - (_soma or 0)
            st.warning(
                f"⚠️ **A conta não fecha por {_p.get('dif_pct')}%** — confira antes de calcular.\n\n"
                f"- parcelas: {_f('valor_principal')} + {_f('valor_juros')} + {_f('valor_selic')} "
                f"= **{_soma:,.2f}**\n"
                f"- total lido: **{_tot:,.2f}**\n"
                f"- diferença: **{_sobra:+,.2f}**"
            )
            if _sobra > 0:
                st.caption(
                    "Total MAIOR que as parcelas — normalmente o total inclui a **verba do "
                    "advogado** (sucumbenciais) ou encargos do réu. Se for isso, o valor do "
                    "credor é a soma das parcelas, não o total."
                )
            else:
                st.caption(
                    "Total MENOR que as parcelas — normalmente o total lido é o **líquido** "
                    "(já sem PSS/IR) e as parcelas são o bruto."
                )
        else:
            st.info("Prova não aplicável (principal ou total ausentes).")

        # ── campos, cada um com o TRECHO ──────────────────────────────────
        st.markdown("**Valores extraídos** — o trecho mostra de onde cada número saiu:")
        for _k, _d in _campos.items():
            _cit = _d.get("citacao") or {}
            _pg, _tr = _cit.get("pagina"), (_cit.get("trecho") or "").strip()
            _peca = (_res.get("mapa_paginas") or {}).get(str(_pg), {})
            _onde = f"{_peca.get('peca', '?')}, pág {_peca.get('pagina', _pg)}" if _pg else ""
            _destaque = "**" if _k == "valor_total" else ""
            st.markdown(f"• {_destaque}{_k}{_destaque} = `{_d['valor']}`"
                        + (f"  \n  ↳ _{_tr}_  ({_onde})" if _tr else
                           (f"  \n  ↳ {_onde}" if _onde else "")))

        for _cf in (_res.get("conflitos") or []):
            st.error(f"⚠️ **{_cf['campo']}**: a IA leu `{_cf['llm']}`, o regex leu "
                     f"`{_cf['regex']}` (pág {_cf['pagina']}) — confira qual está certo.")

        # valores RECUSADOS (não existem na conta): aviso + "usar mesmo assim".
        # Nunca silencioso — um campo que some sem explicação só troca a caçada
        # do advogado por outra.
        _usados = _rej.mostrar(st, _res.get("rejeitados"), "pre")

        for _dc in (_res.get("do_card") or []):
            st.info(f"📇 Completado pelo card: **{_dc}** — os documentos não traziam.")
        if _res.get("guardados"):
            st.caption("💾 Guardado no hub: " + ", ".join(_res["guardados"])
                       + " — o caso pode ser reaberto depois.")
        for _fh in (_res.get("falha_hub") or []):
            st.caption(f"⚠️ Não guardou no hub — {_fh}")
        st.caption(f"Extraído por IA + regex · custo US$ {_res['custo']}")

        # ── visualizador: cada citação renderizada NA SUA peça ────────────
        if _res.get("citacoes") and st.checkbox(
                "📄 Ver as páginas citadas (com o valor destacado)", key="pre_ver_cit"):
            from prefill.viewer import render_paginas
            _mapa = _res.get("mapa_paginas") or {}
            _sbs = st.session_state.get("pre_sent_bytes") or []
            _pdfs = {TIPO_CONTA: st.session_state.get("pre_conta_bytes"),
                     TIPO_OFICIO: st.session_state.get("pre_oficio_bytes")}
            # mesmos rótulos que o `extrair_pecas` gerou (numerados se for > 1)
            for _i, _sb1 in enumerate(_sbs):
                _pdfs[TIPO_SENTENCA if len(_sbs) == 1 else f"{TIPO_SENTENCA} {_i + 1}"] = _sb1
            # a citação vem no espaço CONCATENADO; o mapa traduz de volta para
            # (peça, página local) — senão a pág 5 do concatenado renderizaria a
            # pág 5 da conta, que pode nem existir.
            _por_peca: dict[str, dict[int, list[str]]] = {}
            for _pg_str, _termos in _res["citacoes"].items():
                _m = _mapa.get(_pg_str)
                if _m:
                    _por_peca.setdefault(_m["peca"], {})[_m["pagina"]] = _termos
            for _peca_nome, _dest in _por_peca.items():
                _pdf = _pdfs.get(_peca_nome)
                if not _pdf:
                    continue
                for _img in render_paginas(_pdf, _dest):
                    st.image(_img["png"],
                             caption=f"{_peca_nome} — pág {_img['pagina']} · "
                                     f"{_img['n_marcas']} valor(es) destacado(s)",
                             width="stretch")

        # ───────────────────── 3 · Calcular ─────────────────────
        st.divider()
        st.subheader("4 · Calcular")
        st.caption("Abre a calculadora com estes valores. Lá você ajusta o que precisar, "
                   "confere PSS/IR e clica em Calcular para gerar o memorial.")
        # LINK, não troca de aba: a calculadora é outra APLICAÇÃO (outro
        # processo, outra porta) — é o que impede um erro aqui de derrubar o
        # cálculo do time. Os valores viajam na query string, que é o
        # mecanismo que a calculadora já consome.
        # o link carrega o CASO: é por ele que a calculadora acha os PDFs. Sem
        # isso ela procuraria pelo número do card digitado LÁ — e mandar para um
        # card diferente do analisado (teste, correção) perdia os anexos.
        _q_link = _rej.aplicar(_res["query"], _res.get("rejeitados"), _usados)
        if st.session_state.get("pre_caso"):
            _q_link["caso"] = st.session_state["pre_caso"]["id"]
        if st.session_state.get("pre_card"):
            _q_link["card"] = str(st.session_state["pre_card"]["id"])
        if not st.session_state.get("pre_caso"):
            st.warning("⚠️ Sem caso aberto no hub: os PDFs **não** vão junto para o "
                       "card. Informe o card no passo 1 e extraia de novo.")
        st.link_button("🧮 Abrir na calculadora com estes valores",
                       url_calculadora(_q_link), type="primary",
                       use_container_width=True)

st.divider()
if st.button("↺ Recomeçar (outro caso)", key="pre_reset"):
    _reset()
    st.session_state["pre_upload_n"] = _n + 1  # descarrega os PDFs dos uploaders
    st.rerun()
