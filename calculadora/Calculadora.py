"""Calculadora manual de precatórios — bundle standalone (Streamlit no Render).

Contém APENAS o motor determinístico (`precaturia.pipeline`) + os índices
públicos do BACEN. **Zero dado de cliente** — o advogado digita os números.
Reusa o mesmo `calcular_dict` do sistema → números idênticos (paridade).
"""

from __future__ import annotations

import os
import re
import sys
import unicodedata
from datetime import date
from decimal import Decimal, InvalidOperation

import streamlit as st

# O pacote `precaturia` está ao lado deste arquivo (raiz do repo do bundle).
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from precaturia.pipeline import calculadora  # noqa: E402
from precaturia.pipeline.calculadora import EntradaCalculadora  # noqa: E402
from precaturia.pipeline.indices import series as _series  # noqa: E402
import memorial  # noqa: E402
import numeros  # noqa: E402 — leitura de número digitado (puro, testável)
# A trava de acesso vive em `auth.py` — uma cópia só, para as duas aplicações.
# Havia uma inline aqui, espelhando a de lá; com o login individual as duas
# passariam a ter regra de autenticação, e duas regras que precisam ser iguais
# acabam diferentes.
from auth import mostrar_usuario, require_password, usuario_atual  # noqa: E402
from versao import sha_do_deploy  # noqa: E402 — motor_versao do snapshot (Fase 2)


def _meses_projetados(res: dict) -> tuple[str, str] | None:
    """Se a data-alvo do cálculo passou do último mês REAL de algum índice da
    atualização, devolve (mes_alvo, ultimo_real_min) para o aviso. Senão None."""
    at = (res.get("cenario_homologado") or {}).get("atualizacao") or {}
    data_alvo = at.get("data_alvo")
    if not data_alvo:
        return None
    mes_alvo = str(data_alvo)[:7]
    reais = [r for r in (_series.ultimo_mes_real(i) for i in ("SELIC", "IPCA", "IPCA-E")) if r]
    if not reais:
        return None
    min_real = min(reais)
    return (mes_alvo, min_real) if mes_alvo > min_real else None

st.set_page_config(page_title="Precatur — Calculadora", page_icon="⚖️", layout="centered")

from estado import manter as _manter_estado  # noqa: E402
# leve (só json): lido no envio ao ledger mesmo com PREFILL_ENABLED desligado
from prefill import rejeitados as _rej  # noqa: E402

_manter_estado()


# ───────────────────────── marca (petróleo/creme) ─────────────────────────
st.markdown(
    """
    <style>
      @import url('https://fonts.googleapis.com/css2?family=Roboto:wght@400;500;700&display=swap');
      html, body, [class*="css"] { font-family: 'Roboto', sans-serif; }
      .marca { display:flex; align-items:baseline; gap:.15rem; margin-bottom:.25rem; }
      .marca .w { font-weight:700; letter-spacing:.22em; text-transform:uppercase; font-size:1.4rem; color:#f2ece6; }
      .marca .ia { font-weight:700; letter-spacing:.22em; text-transform:uppercase; font-size:1.4rem; color:#fceadc; }
      .marca .sub { margin-left:.6rem; font-size:.7rem; letter-spacing:.2em; text-transform:uppercase; color:#9fb0b3; }
      .oferta { background:#213139; border:1px solid #384f59; border-radius:12px; padding:1rem 1.25rem; }
      .oferta .lbl { font-size:.75rem; letter-spacing:.12em; text-transform:uppercase; color:#9fb0b3; }
      .oferta .val { font-size:2rem; font-weight:700; color:#fceadc; }
      /* cascata (waterfall) do líquido */
      .wf { width:100%; border-collapse:collapse; margin:.4rem 0 .2rem; }
      .wf td { padding:.4rem .3rem; border-bottom:1px solid #2a3a42; }
      .wf td.v { text-align:right; font-variant-numeric:tabular-nums; white-space:nowrap; }
      .wf tr.top td { font-weight:600; color:#e8eef0; }
      .wf tr.sub td { color:#9fb0b3; font-size:.92rem; }
      .wf tr.final td { border-top:2px solid #4a6470; border-bottom:none; padding-top:.6rem;
                         font-weight:700; color:#fceadc; }
      .wf tr.final td.lbl2 { font-size:1rem; letter-spacing:.04em; text-transform:uppercase; }
      .wf tr.final td.v { font-size:1.7rem; }
      /* tabela de correção por período */
      .comp { width:100%; border-collapse:collapse; margin:.2rem 0; font-size:.92rem; }
      .comp th { text-align:left; color:#9fb0b3; font-weight:500;
                 border-bottom:1px solid #384f59; padding:.35rem .45rem; }
      .comp td { padding:.35rem .45rem; border-bottom:1px solid #22303733; }
      .comp td.n { text-align:right; font-variant-numeric:tabular-nums; white-space:nowrap; }
      .brk { display:flex; gap:1.2rem; flex-wrap:wrap; margin:.5rem 0 .2rem; }
      .brk .cell .k { font-size:.7rem; letter-spacing:.1em; text-transform:uppercase; color:#9fb0b3; }
      .brk .cell .n { font-size:1rem; font-weight:600; color:#e8eef0; font-variant-numeric:tabular-nums; }
    </style>
    <div class="marca"><span class="w">Precatur<span class="ia">-IA</span></span>
      <span class="sub">Calculadora de precatórios</span></div>
    """,
    unsafe_allow_html=True,
)

require_password()
mostrar_usuario()

# ───────────────────────────── helpers ─────────────────────────────


def parse_dec(s: str) -> Decimal | None:
    """Número digitado → Decimal. Vazio → None; inválido → aviso + None.

    As regras (BR, americano, ponto de milhar, NaN/Infinity/"1e3" inválidos)
    vivem em `numeros.parse_decimal_br`, que é testado sozinho. Os campos de
    PSS/IR no modo "Valor da conta" NÃO passam por aqui: vazio ou inválido lá
    bloqueia o cálculo (`_ler_declarado`), não vira aviso.
    """
    try:
        return numeros.parse_decimal_br(s)
    except ValueError:
        st.warning(f"Valor inválido: '{(s or '').strip()}'. "
                   "Use vírgula para centavos (ex.: 1.234,56).")
        return None


def _ler_declarado(texto: str, rotulo: str, outros: str) -> tuple[Decimal | None, str | None]:
    """Campo de PSS/IR no modo "Valor da conta": (valor, None) ou (None, erro).

    Aqui vazio e inválido NÃO são "sem valor": o motor estimaria sozinho (14% de
    PSS e IR-RRA, com 1 mês se os meses ficassem em 0) enquanto o memorial
    rotula o modo como "Valor da conta". O advogado escolheu digitar o número —
    se ele não veio legível, o cálculo não roda até vir ou até ele trocar de
    modo. O zero digitado ("0", "0,00") é resposta válida: conta sem desconto.
    """
    try:
        valor = numeros.parse_decimal_br(texto)
    except ValueError as exc:
        return None, (f"{rotulo}: valor inválido '{(texto or '').strip()}' ({exc}). "
                      "Use vírgula para centavos (ex.: 1.234,56) ou escolha outro "
                      f"modo ({outros}).")
    if valor is None:
        return None, (f"{rotulo}: modo 'Valor no ofício' sem valor. Informe o valor "
                      f"do {rotulo} ou escolha outro modo ({outros}).")
    if valor < 0:
        return None, (f"{rotulo}: valor negativo ('{texto.strip()}') não é válido — "
                      f"informe o valor do {rotulo} sem sinal ou escolha outro modo "
                      f"({outros}).")
    return valor, None


def _ler_percentual(texto: str, rotulo: str) -> tuple[Decimal | None, str | None]:
    """Campo de PERCENTUAL: (valor, None), (None, None) se vazio ou (None, erro).

    Ponto é sempre decimal ("12.500" → 12,5; em R$ seria milhar) e o intervalo é
    0–100: "150", "-1", "NaN" e texto ilegível bloqueiam o cálculo, no mesmo
    padrão do PSS/IR. VAZIO devolve (None, None) — não é erro aqui: contratuais
    vazio = sem desconto, sucumbenciais vazio = sem linha no memorial. A
    alíquota do PSS é a exceção, e quem a trata é o chamador (vazio bloqueia
    no modo "Por alíquota").
    """
    try:
        valor = numeros.parse_decimal_br(texto, milhar=False)
    except ValueError as exc:
        return None, (f"{rotulo}: valor inválido '{(texto or '').strip()}' ({exc}). "
                      "Informe um percentual de 0 a 100 (ex.: 12,5).")
    if valor is None:
        return None, None
    if valor < 0 or valor > 100:
        return None, (f"{rotulo}: '{texto.strip()}' está fora de 0 a 100. "
                      "Informe um percentual (ex.: 12,5).")
    return valor, None


def fmt_brl(s) -> str:
    if s is None:
        return "—"
    d = Decimal(str(s))
    neg = d < 0
    d = abs(d).quantize(Decimal("0.01"))
    intp, dec = f"{d:.2f}".split(".")
    intp = f"{int(intp):,}".replace(",", ".")
    return f"{'-' if neg else ''}R$ {intp},{dec}"


def fmt_data(s) -> str:
    try:
        return date.fromisoformat(str(s)[:10]).strftime("%d/%m/%Y")
    except Exception:
        return str(s or "—")


def nome_arquivo(ref: str) -> str:
    """Nome do PDF a partir da referência do caso, saneado para filesystem.
    Vazio → 'memorial_calculo.pdf'."""
    base = (ref or "").strip()
    if not base:
        return "memorial_calculo.pdf"
    # remove acentos (compatibilidade cross-OS) e caracteres proibidos em nome.
    base = unicodedata.normalize("NFKD", base).encode("ascii", "ignore").decode("ascii")
    base = re.sub(r'[\\/:*?"<>|]+', " ", base)
    base = re.sub(r"\s+", " ", base).strip()[:100].rstrip(" .-")
    return f"{base or 'memorial_calculo'}.pdf"


def fmt_pct_fator(f) -> str:
    """Fator (ex.: 1.0985) → variação percentual BR (ex.: +9,85%)."""
    try:
        v = (Decimal(str(f)) - Decimal("1")) * Decimal("100")
        return f"{v:+.2f}%".replace(".", ",")
    except Exception:
        return "—"


def regime_curto(regime: str) -> str:
    r = (regime or "").lower()
    if "graça" in r or "graca" in r:
        return "IPCA-E — período de graça (SELIC parada)"
    if "ec 136" in r:
        return "IPCA + 2% a.a. (EC 136, teto SELIC)"
    if "ec 113" in r or "selic" in r:
        return "SELIC (EC 113)"
    return regime


def money(label: str, key: str, help: str | None = None) -> Decimal | None:
    return parse_dec(st.text_input(label, key=key, help=help, placeholder="0,00"))


def build_regime(preset: str) -> list[dict] | None:
    """Presets de regime (só no modo originário)."""
    if preset.startswith("Simples"):
        indice = "IPCA-E" if "IPCA-E" in preset else "INPC"
        return [{
            "indice": indice, "inicio_tipo": "data_base", "inicio_data": None,
            "fim_tipo": "data_calculo", "fim_data": None,
        }]
    if preset.startswith("Composto"):
        return [
            {"indice": "IPCA-E", "inicio_tipo": "data_base", "inicio_data": None,
             "fim_tipo": "data", "fim_data": "2021-12-09"},
            {"indice": "SELIC", "inicio_tipo": "data", "inicio_data": "2021-12-09",
             "fim_tipo": "data_calculo", "fim_data": None},
        ]
    return None


# Hoisted do formulário: o "reabrir para editar" (`?snapshot=`) precisa destas
# listas ANTES de o formulário existir na execução (o handler roda no topo).
_REGIME_OPCOES = [
    "Simples — IPCA-E", "Simples — INPC",
    "Composto pós-EC 113 (IPCA-E → SELIC)",
]
# `_qp_index` não serve para o regime: os dois "Simples" têm o MESMO prefixo
# antes do " — ". Slug explícito por opção resolve sem ambiguidade.
_REGIME_SLUG_IDX = {"simples-ipca-e": 0, "simples-inpc": 1, "composto-ec113": 2}
_ENTE_OPCOES = [
    "(não informar)",
    "União",
    "INSS",
    "Estado do Espírito Santo",
    "Estado do Rio de Janeiro",
    "Estado de Minas Gerais",
    "Estado da Bahia",
    "Estado de Goiás",
    "Estado de Mato Grosso",
    "Estado de São Paulo",
    "Estado de Alagoas",
    "IPAJM — Instituto de Previdência dos Servidores do ES",
    "Rio Previdência (RJ)",
    "Alagoas Previdência",
    "Outro (digitar abaixo)",
]
_ANO_OPCOES = ["(não informar)"] + [str(a) for a in range(2020, 2041)]

# (chave do widget, query param) dos campos de TEXTO semeáveis — fonte única:
# a semeadura do prefill e a limpeza do "reabrir" usam a MESMA lista, senão um
# campo novo entra numa e esquece da outra. Chaves com `value=` no widget
# (`apss`, `meses`) ficam de fora: essas leem o param direto no `value=`.
_SEED_PARES = [
    ("vt", "vt"), ("vp", "vp"), ("vj", "vj"), ("vs", "vs"),
    ("vo", "vo"), ("sp_val", "sp_val"),
    ("pss", "valor_pss"), ("ir", "valor_ir"),
    ("hc", "hc"), ("hs", "hs"), ("ref", "ref"), ("obs", "obs"),
    ("ente_outro", "ente_outro"),
    ("bx_num_oficio", "numero_oficio"), ("bx_num_precatorio", "numero_precatorio"),
    ("bx_deal", "card"),
]


# Params que a tela lê com `parse_dec` — os que o snapshot semeia como número.
_PARAMS_NUMERICOS = ("vt", "vp", "vo", "vj", "vs", "sp_val", "hc", "hs",
                     "valor_pss", "valor_ir", "apss")


def _params_do_snapshot(snap: dict) -> dict[str, str]:
    """`entrada` congelada → o vocabulário de query params do formulário.

    É deliberadamente o MESMO canal do prefill: o snapshot não ganha um
    segundo mecanismo de semeadura, ganha params — e a URL resultante segue
    compartilhável. Regime fora dos presets fica sem param (o seletor abre no
    default) — caso hoje teórico: este formulário só produz presets, então
    toda entrada gravada por ele casa com um.
    """
    e = snap.get("entrada") or {}
    p: dict[str, str] = {}

    def poe(param: str, chave: str):
        v = e.get(chave)
        if v not in (None, ""):
            p[param] = str(v)

    poe("vt", "valor_total")
    poe("vp", "valor_principal_corrigido")
    poe("vo", "valor_originario")
    # juros/SELIC zerados são o default do dataclass, não digitação — omitir
    for param, chave in (("vj", "valor_juros"), ("vs", "valor_selic")):
        v = e.get(chave)
        if v not in (None, "") and Decimal(str(v)) != 0:
            p[param] = str(v)
    for param, chave in (("data_base", "data_base"), ("data_calculo", "data_calculo"),
                         ("data_alvo", "data_alvo"), ("data_apres", "data_apresentacao"),
                         ("data_expedicao", "data_expedicao"),
                         ("sp_data", "data_pagamento_superpreferencia")):
        poe(param, chave)
    poe("sp_val", "valor_superpreferencia")
    poe("natureza", "natureza_tributaria")

    # PSS/IR: o modo do radio é derivado do que a entrada DIZ, com o zero
    # explícito voltando como "Não descontar" (0 congela; None estimaria).
    v_pss = e.get("valor_pss")
    if e.get("estimar_pss"):
        p["pss_modo"] = "aliquota"
        if e.get("aliquota_pss_pct") is not None:
            p["apss"] = str(e["aliquota_pss_pct"])
    elif v_pss is not None:
        if Decimal(str(v_pss)) == 0:
            p["pss_modo"] = "nao"
        else:
            p["pss_modo"] = "valor"
            p["valor_pss"] = str(v_pss)
    v_ir = e.get("valor_ir")
    if e.get("estimar_ir"):
        p["ir_modo"] = "estimar"
    elif v_ir is not None:
        if Decimal(str(v_ir)) == 0:
            p["ir_modo"] = "nao"
        else:
            p["ir_modo"] = "valor"
            p["valor_ir"] = str(v_ir)
    if e.get("meses_competencia"):
        p["meses"] = str(e["meses_competencia"])

    poe("hc", "honorarios_contratuais_pct")
    poe("hs", "honorarios_sucumbenciais_pct")
    poe("modalidade", "modalidade")
    poe("esfera", "esfera")

    if e.get("valor_originario") is not None:
        p["modo"] = "originario"
        poe("nat_hist", "natureza")
        poe("assist_idx", "assistencial_indice")
        regime = e.get("regime")
        if regime:
            for slug, idx in _REGIME_SLUG_IDX.items():
                if build_regime(_REGIME_OPCOES[idx]) == regime:
                    p["regime"] = slug
                    break

    tela = e.get("_tela") or {}
    if tela.get("referencia"):
        p["ref"] = str(tela["referencia"])
    if tela.get("observacao"):
        p["obs"] = str(tela["observacao"])
    ente = tela.get("ente_devedor")
    if ente:
        if ente in _ENTE_OPCOES:
            p["ente"] = ente
        else:
            p["ente"] = "Outro (digitar abaixo)"
            p["ente_outro"] = str(ente)
    if tela.get("ano_orcamentario"):
        p["ano_orc"] = str(tela["ano_orcamentario"])

    # identificação: o caso e o card viajam junto — o envio e as peças
    # dependem deles (mesma razão do `?caso=` da pré-análise)
    if snap.get("case_id"):
        p["caso"] = str(snap["case_id"])
    if snap.get("deal_id"):
        p["card"] = str(snap["deal_id"])
    # `str(Decimal("987.650"))` seria lido como milhar (987650): nos campos numéricos
    # a única forma ambígua ganha vírgula. As demais ficam como estão.
    for _k in _PARAMS_NUMERICOS:
        if _k in p:
            p[_k] = numeros.para_semente(p[_k])
    return p


# ── Anexar processo (BETA, atrás de flag) ──────────────────────────────
# Pré-preenche a conta HOMOLOGADA a partir do PDF do processo. ADITIVO e
# REVERSÍVEL: só aparece com PREFILL_ENABLED=1; com a flag off, este bloco é
# inerte e o `prefill/` nem é importado (deps pymupdf/numpy/httpx só quando on).
# O advogado revisa cada campo (com a citação) antes de calcular.
if os.environ.get("PREFILL_ENABLED") == "1":
    with st.expander("📎 Anexar processo (beta) — pré-preenche a partir do PDF", expanded=False):
        _up = st.file_uploader("PDF do processo completo", type=["pdf"], key="_prefill_pdf")
        if _up is not None and st.button("Localizar e extrair (conta homologada + ofício)", key="_prefill_go"):
            with st.spinner("Lendo o processo, localizando a conta homologada e o ofício, extraindo os valores…"):
                from prefill.pipeline import preencher  # import lazy (só com a flag on)
                _bytes = _up.getvalue()
                try:
                    _res = preencher(pdf_bytes=_bytes)
                except Exception as _e:  # rede/LLM instável não pode derrubar a UI
                    _res = {"ok": False, "erro": f"{type(_e).__name__}: {str(_e)[:200]}"}
            if not _res.get("ok"):
                st.error(f"Não consegui pré-preencher: {_res.get('erro')}")
            else:
                st.session_state["_prefill_result"] = _res
                st.session_state["_prefill_pdf_bytes"] = _bytes
                # a calculadora já consome esses params; `rej` leva os recusados ao ledger
                st.query_params.update(_rej.aplicar(_res["query"], _res.get("rejeitados")))
                st.session_state.pop("_prefill_done", None)  # re-semeia os campos
                st.rerun()
        _pr = st.session_state.get("_prefill_result")
        if _pr and _pr.get("ok"):
            _p = _pr["prova"]
            _sel = {True: "✅ a conta fecha (Principal+Juros+Selic=Total)",
                    False: f"⚠️ NÃO fecha (dif {_p.get('dif_pct')}%) — confira os valores",
                    None: "prova não aplicável"}[_p.get("ok")]
            _of = f" · ofício {_pr['oficio_ref']}" if _pr.get("oficio_ref") else ""
            st.caption(f"Conta **{_pr['conta_ref']}**{_of} · {_sel} · custo ${_pr['custo']}")
            for _k, _d in _pr["campos"].items():
                _c = _d.get("citacao") or {}
                st.caption(f"• **{_k}** = `{_d['valor']}` — pág {_c.get('pagina')}")
            for _cf in (_pr.get("conflitos") or []):
                st.error(f"⚠️ **{_cf['campo']}**: a IA leu `{_cf['llm']}`, o regex leu "
                         f"`{_cf['regex']}` (pág {_cf['pagina']}) — confira qual está certo.")
            # valores RECUSADOS (não existem na conta). Aqui o formulário é a
            # própria tela: "usar mesmo assim" devolve o valor ao campo UMA vez
            # (na transição) — depois é do advogado, e rerun não sobrescreve.
            _usados_pr = _rej.mostrar(st, _pr.get("rejeitados"), "_prefill")
            for _r in (_pr.get("rejeitados") or []):
                _flag = f"_rej_aplicado_{_r['param']}"
                if _r["param"] in _usados_pr and not st.session_state.get(_flag):
                    st.session_state[_flag] = True
                    st.session_state[_r["param"]] = str(_r["valor"])
                    st.query_params.update(_rej.aplicar({}, _pr.get("rejeitados"), _usados_pr)
                                           | {_r["param"]: str(_r["valor"])})
            st.warning("Valores por IA + regex — **confira cada um contra o PDF antes de calcular.** "
                       "Campos com `(pág N)` você confere no visualizador abaixo.")
            # Visualizador: renderiza as páginas CITADAS com o valor DESTACADO, para
            # o advogado conferir sem sair da calculadora.
            _pdfb = st.session_state.get("_prefill_pdf_bytes")
            if _pdfb and _pr.get("citacoes") and st.checkbox(
                    "📄 Ver as páginas citadas (com o valor destacado)", key="_prefill_ver"):
                from prefill.viewer import render_paginas
                _dest = {int(k): v for k, v in _pr["citacoes"].items()}
                for _img in render_paginas(_pdfb, _dest):
                    st.image(_img["png"],
                             caption=f"pág {_img['pagina']} — {_img['n_marcas']} valor(es) destacado(s)",
                             use_container_width=True)

# ── Pré-preenchimento via URL ──────────────────────────────────────────
# O botão "Abrir na calculadora" do sistema PrecaturIA abre este app com os
# valores do ofício principal na query string. Semeia os inputs de TEXTO com
# key ANTES de eles serem criados (Streamlit adota o session_state); datas e
# seletores derivam seus defaults de `_qp_*` abaixo. Só na 1ª renderização da
# sessão — não sobrescreve o que o advogado editar depois.
#
# ⚠ `st.switch_page` LIMPA a query string (medido com AppTest em 1.58). As telas
# internas de pré-preenchimento, que navegam para cá por switch_page, entregam
# os valores por `_prefill_params` no session_state — a URL é reposta aqui, e
# todo o resto do arquivo continua lendo `st.query_params` como antes (o link
# volta a ser compartilhável). Chamada externa por URL não muda em nada.
_entregue = st.session_state.pop("_prefill_params", None)
if _entregue:
    st.query_params.update(_entregue)

# ── Reabrir um cálculo enviado (Fase 2): `?snapshot=<id>` ──────────────
# A ENTRADA congelada vira query params (o MESMO canal do prefill — uma
# expansão por id, e a URL segue compartilhável); o RESULTADO congelado vai
# para o painel do topo. Recalcular usa os índices de HOJE: a diferença entre
# os dois números é índice/motor novo, e o painel existe para mostrá-la.
_snap_qp = (st.query_params.get("snapshot") or "").strip() or None
if _snap_qp and st.session_state.get("_snap_expandido") != _snap_qp:
    st.session_state["_snap_expandido"] = _snap_qp
    _snap = None
    try:
        import hub as _hub_snap  # noqa: PLC0415 — lazy, igual ao bloco do envio
        if _hub_snap.habilitado():
            _snap = _hub_snap.snapshot(_snap_qp)
        else:
            st.error("`?snapshot=` precisa de HUB_URL no ambiente — o cálculo "
                     "congelado mora no hub.")
    except Exception as _e_snap:  # noqa: BLE001 — rede/hub não derruba a tela
        st.error(f"Não consegui abrir o snapshot: {type(_e_snap).__name__}: {_e_snap}")
    if _snap:
        st.session_state["_snap_aberto"] = _snap
        st.session_state.pop("_snap_memorial", None)
        try:
            if _snap.get("memorial_pdf_hash"):
                st.session_state["_snap_memorial"] = (
                    _hub_snap.memorial_do_snapshot(_snap_qp))
        except Exception:  # noqa: BLE001 — memorial é prova, não pré-requisito
            pass
        # limpa os campos de texto ANTES de semear: reabrir um snapshot que
        # não preencheu `vt` não pode herdar o `vt` da sessão anterior.
        for _k, _ in _SEED_PARES:
            if _k in st.session_state:
                try:
                    st.session_state[_k] = ""
                except Exception:  # noqa: BLE001 — widget já instanciado
                    pass
        st.query_params.update(_params_do_snapshot(_snap))
        st.session_state.pop("_prefill_done", None)   # re-semeia os campos
        st.rerun()

_qp = st.query_params
# "o pré-preenchimento rodou nesta sessão" — durável, diferente de `_prefilled`,
# que só é verdadeiro na renderização em que a semeadura acontece. Alimenta os
# avisos de campo que a extração NÃO conseguiu preencher.
# só params de VALOR contam como "o pré-preenchimento rodou" — `?card=2273`,
# que é o link direto da tela de pré-análise, não é preenchimento de nada.
_PARAMS_DE_VALOR = {
    "vt", "vp", "vj", "vs", "valor_pss", "valor_ir", "hc", "hs", "natureza",
    "modalidade", "data_calculo", "ente", "data_apres"}
_prefill_rodou = (any(k in _qp for k in _PARAMS_DE_VALOR)
                  or bool(st.session_state.get("_prefill_done")))


def _qp_get(name: str) -> str | None:
    v = _qp.get(name)
    return v or None


def _meses_da_url() -> tuple[int, str | None]:
    """`?meses=` → (n, None) ou (0, aviso). Inteiro não negativo ou nada.

    O widget é um `st.number_input` de inteiros: "12.5", "12.500" ou "abc"
    estouravam ValueError no `int()` e derrubavam a tela inteira. Valor inválido
    cai em 0 (o IR estimado fica "a apurar", que é o seguro) e a tela avisa.
    """
    raw = _qp_get("meses")
    if not raw:
        return 0, None
    try:
        n = int(raw.strip())
        if n < 0:
            raise ValueError(raw)
    except ValueError:
        return 0, (f"Nº de meses inválido na URL ('{raw}') — usando 0. "
                   "Digite os meses do RRA no campo abaixo.")
    return n, None


def _qp_date(name: str) -> date | None:
    raw = _qp_get(name)
    if not raw:
        return None
    try:
        return date.fromisoformat(raw)
    except ValueError:
        return None


def _qp_index(name: str, opcoes: list[str], default: int = 0) -> int:
    """Índice da opção cujo prefixo bate com o param (ex.: 'precatorio')."""
    raw = _qp_get(name)
    if not raw:
        return default
    for i, o in enumerate(opcoes):
        if o.split(" — ")[0].strip().lower() == raw.strip().lower():
            return i
    return default


_prefilled = bool(_qp) and not st.session_state.get("_prefill_done")
if _prefilled:
    # Chaves de texto SEM `value=` no widget — só essas podem ser semeadas via
    # session_state (`apss`/`meses` têm value= e leem o param direto lá). A
    # lista é `_SEED_PARES` (fonte única com a limpeza do `?snapshot=`); os
    # porquês históricos de cada par — ente_outro para o seletor "Outro",
    # bx_* como ex-passageiros invisíveis da URL — estão anotados nela.
    for _key, _param in _SEED_PARES:
        # ⚠ NÃO condicionar a `_key not in st.session_state`: a chave do widget
        # nasce na PRIMEIRA renderização da calculadora e sobrevive à navegação,
        # então a guarda pulava o preenchimento em toda sessão que tivesse aberto
        # a calculadora antes de ir à tela de pré-análise — que é o caminho
        # normal. Quem garante "só uma vez" é `_prefill_done`, logo abaixo.
        _val = _qp_get(_param)
        if _val is not None:
            st.session_state[_key] = _val
    st.session_state["_prefill_done"] = True
    # O aviso é sobre VALOR extraído do ofício. Uma URL que só traz `?card=` ou
    # `?caso=` semeia identificação, não conta nenhuma — anunciar "campos
    # pré-preenchidos" ali mandaria o advogado conferir uma extração que não
    # houve. Mesmo critério que `_prefill_rodou` usa para os avisos de campo.
    # reabertura de snapshot também chega por params, mas não é extração de
    # ofício — o aviso certo é o do painel congelado, não este.
    if _prefill_rodou and not _qp_get("snapshot"):
        st.info(
            "📥 Campos pré-preenchidos pelo PrecaturIA a partir do ofício. "
            "**Confira cada valor** antes de calcular — especialmente PSS/IR "
            "(selecione o modo 'Valor no ofício' para aplicá-los)."
        )

# ── Fase 2: painel do snapshot congelado + histórico do caso ────────────

_snap_aberto = st.session_state.get("_snap_aberto")
if _snap_aberto and _qp_get("snapshot"):
    with st.container(border=True):
        _quem = _snap_aberto.get("autor") or "sem autoria (senha do time)"
        st.markdown(
            f"🧊 **Cálculo congelado** — enviado em "
            f"{fmt_data(_snap_aberto.get('criado_em'))} por **{_quem}**"
            + (f" · card #{_snap_aberto.get('deal_id')}" if _snap_aberto.get("deal_id") else ""))
        st.markdown(f"Valor enviado: **{_snap_aberto.get('valor_card') or fmt_brl(_snap_aberto.get('valor_liquido'))}**")
        _mv = _snap_aberto.get("motor_versao")
        _mv_hoje = sha_do_deploy()
        _umr = _snap_aberto.get("ultimo_mes_real") or {}
        st.caption(
            f"motor do envio: `{_mv or 'desconhecido'}`"
            + (" (o mesmo de hoje)" if _mv and _mv == _mv_hoje
               else f" · motor de hoje: `{_mv_hoje or 'desconhecido'}`")
            + (" · índices reais até " + ", ".join(
                f"{k} {v}" for k, v in sorted(_umr.items())) if _umr else ""))
        if st.session_state.get("_snap_memorial"):
            st.download_button(
                "📄 Memorial deste envio (PDF congelado)",
                data=st.session_state["_snap_memorial"],
                file_name=f"memorial_snapshot_{_qp_get('snapshot')}.pdf",
                mime="application/pdf")
        st.caption(
            "Os campos abaixo foram semeados deste snapshot. **Calcular** roda "
            "com os índices de HOJE — divergência do valor congelado é índice/"
            "motor novo, não erro; a comparação aparece junto do resultado.")

# O histórico (snapshots + journal) mora no hub; sem HUB_URL o painel nem
# aparece. Carregar é ação explícita — a tela não faz HTTP a cada rerun.
if os.environ.get("HUB_URL"):
    try:
        import hub as _hub_pan  # noqa: PLC0415 — lazy, igual ao bloco do envio
    except Exception:  # noqa: BLE001 — dependência ausente não derruba a tela
        _hub_pan = None
    _caso_pan = (_qp_get("caso") or "").strip() or None
    _card_pan = ((_qp_get("card") or "").strip()
                 or str(st.session_state.get("bx_deal") or "").strip() or None)
    if _hub_pan is not None and (_caso_pan or _card_pan):
        with st.expander("📚 Cálculos enviados deste caso (snapshots e journal)"):
            if st.button("🔄 Carregar histórico do caso", key="_f2_carregar"):
                try:
                    _cid_pan = (_caso_pan
                                or ((_hub_pan.caso_do_card(_card_pan) or {}).get("id")))
                    if not _cid_pan:
                        st.session_state.pop("_f2_hist", None)
                        st.info("Este card ainda não tem caso no hub — o histórico "
                                "nasce no primeiro envio feito por aqui.")
                    else:
                        st.session_state["_f2_hist"] = {
                            "caso": _cid_pan,
                            "snapshots": _hub_pan.snapshots_do_caso(_cid_pan),
                            "journal": _hub_pan.journal_do_caso(_cid_pan),
                        }
                except Exception as _e_pan:  # noqa: BLE001
                    st.error(f"{type(_e_pan).__name__}: {_e_pan}")
            _hist = st.session_state.get("_f2_hist")
            if _hist:
                if not _hist["snapshots"]:
                    st.caption("Nenhum cálculo enviado ainda.")
                for _s in _hist["snapshots"]:
                    _c1, _c2 = st.columns([4, 1])
                    _c1.markdown(
                        f"**{fmt_data(_s.get('criado_em'))}** · "
                        f"{_s.get('autor') or 'sem autoria'} · "
                        f"{_s.get('valor_card') or fmt_brl(_s.get('valor_liquido'))}"
                        + (" · 📄" if _s.get("tem_memorial") else ""))
                    if _c2.button("↩ Reabrir", key=f"_f2_abrir_{_s['id']}"):
                        st.query_params["snapshot"] = _s["id"]
                        st.session_state.pop("_snap_expandido", None)
                        st.session_state.pop("_snap_aberto", None)
                        st.rerun()

                if _hist["journal"]:
                    st.markdown("**Journal do valor do card** (mais novo primeiro)")
                _ICONE = {"aplicado": "✅", "falhou": "❌", "pendente": "⏳"}
                for _j in _hist["journal"]:
                    st.caption(
                        f"{_ICONE.get(_j['status'], '·')} "
                        f"{fmt_data(_j.get('criado_em'))} · **{_j['tipo']}** · "
                        f"{_j.get('valor_antes') or '(vazio)'} → {_j['valor_depois'] or '(vazio)'}"
                        f" · {_j.get('autor') or 'sem autoria'}"
                        + (f" · motivo: {_j['motivo']}" if _j.get("motivo") else "")
                        + (f" · erro: {_j['erro']}" if _j.get("erro") else ""))

                # ── reversão: desfaz a ÚLTIMA escrita aplicada ────────────
                _ultima = next((_j for _j in _hist["journal"]
                                if _j["status"] == "aplicado"), None)
                if _ultima:
                    st.markdown("**↩ Reverter a última escrita aplicada**")
                    st.caption(
                        f"Desfaz: {_ultima['tipo']} de {fmt_data(_ultima.get('criado_em'))} "
                        f"— o card volta a **{_ultima.get('valor_antes') or '(vazio)'}**. "
                        "Reversão é linha NOVA no journal, nada é apagado.")
                    st.text_input("Motivo da reversão (obrigatório)",
                                  key="_f2_rev_motivo",
                                  placeholder="ex.: sobrescrita foi engano — valor anterior era o homologado")
                    st.checkbox("Reverter mesmo que o card tenha mudado depois "
                                "desta escrita", key="_f2_rev_confirma")
                    if st.button("Reverter no card", key="_f2_rev_go"):
                        _mot_rev = (st.session_state.get("_f2_rev_motivo") or "").strip()
                        if not _mot_rev:
                            st.error("Sem motivo não há reversão — mesma regra da sobrescrita.")
                        else:
                            try:
                                import bitrix as _bx_rev  # noqa: PLC0415
                                if not _bx_rev.habilitado():
                                    raise RuntimeError("BITRIX_WEBHOOK ausente — "
                                                       "não há como escrever no card")
                                _deal_rev = int(_ultima["deal_id"])
                                # o que o card mostra AGORA — evidência do journal
                                _agora = (_bx_rev.carregar_deal(_deal_rev)
                                          .get(_bx_rev.CAMPO_VALOR) or "")
                                _jr_rev = _hub_pan.journal_registrar(
                                    _hist["caso"], deal_id=str(_deal_rev),
                                    tipo="reversao",
                                    valor_antes=str(_agora),
                                    valor_depois=_ultima.get("valor_antes") or "",
                                    motivo=_mot_rev, reverte_id=_ultima["id"],
                                    autor=usuario_atual(),
                                    confirmar_divergencia=bool(
                                        st.session_state.get("_f2_rev_confirma")))
                            except _hub_pan.DivergenciaCard as _dv:
                                st.warning(
                                    f"⚠ O card mudou depois dessa escrita: agora está "
                                    f"**{_dv.detail.get('card_agora') or '(vazio)'}**, a entrada "
                                    f"esperava **{_dv.detail.get('esperado') or '(vazio)'}**. "
                                    "Nada foi escrito. Marque a caixa acima para "
                                    "reverter por cima mesmo assim.")
                            except Exception as _e_rev:  # noqa: BLE001 — journal-primeiro: sem trilha, não escreve
                                st.error(f"Reversão BLOQUEADA (nada foi escrito no "
                                         f"card): {type(_e_rev).__name__}: {_e_rev}")
                            else:
                                try:
                                    _bx_rev.sobrescrever_valor(
                                        _deal_rev, _ultima.get("valor_antes") or "")
                                except Exception as _e_rev:  # noqa: BLE001
                                    try:
                                        _hub_pan.journal_concluir(
                                            _jr_rev["id"], "falhou",
                                            erro=f"{type(_e_rev).__name__}: {_e_rev}"[:300])
                                    except Exception:  # noqa: BLE001
                                        pass
                                    st.error(f"O CRM recusou a escrita: {_e_rev} — "
                                             "a tentativa ficou registrada como "
                                             "'falhou' no journal.")
                                else:
                                    try:
                                        _hub_pan.journal_concluir(_jr_rev["id"], "aplicado")
                                    except Exception:  # noqa: BLE001
                                        st.caption("⚠ card revertido; a conclusão do "
                                                   "journal não gravou — a entrada fica "
                                                   "'pendente' e aparece nas pendências.")
                                    st.session_state.pop("_f2_hist", None)
                                    st.success("Reversão aplicada no card e registrada "
                                               "no journal. Recarregue o histórico para ver.")

# ───────────────────────────── formulário ─────────────────────────────

modo = st.radio(
    "Ponto de partida", ["Modo ofício (valores homologados)", "Modo originário (liquidar do zero)"],
    # `?snapshot=` de um caso originário reabre no modo certo; fora isso, conta.
    index=1 if _qp_get("modo") == "originario" else 0,
    horizontal=True,
    help="Ofício: todos os ofícios trazem valores já liquidados/homologados. "
         "Originário: começa do valor de origem + regime.",
)
eh_conta = modo.startswith("Modo ofício")

# A seção "Regime de correção" só existe no modo originário; a numeração
# acompanha o que está na tela (ofício: 1–5; originário: 1–6).
_sec = iter(range(1, 10))

with st.form("calc"):
    st.subheader(f"{next(_sec)} · Valores do crédito")
    if eh_conta:
        c1, c2 = st.columns(2)
        with c1:
            valor_total = money("Valor Total Requisitado (R$)", "vt", "Valor homologado do crédito do credor (já sem cota patronal).")
            valor_principal = money("Principal Corrigido (R$)", "vp", "Base do PSS, do IR e da atualização.")
        with c2:
            valor_juros = money("Juros (moratórios) (R$)", "vj", "Linha de juros do ofício, se destacada.")
            valor_selic = money("SELIC (R$)", "vs", "Se o ofício já traz a SELIC num campo próprio.")
        valor_bruto_recl = None
        valor_originario = None
    else:
        c1, c2 = st.columns(2)
        with c1:
            valor_originario = money("Valor originário (R$)", "vo", "Valor de origem, antes de qualquer correção.")
        with c2:
            st.caption("O regime da seção 2 corrige o originário até a data do cálculo.")
        valor_total = None
        valor_principal = None
        valor_bruto_recl = None
        valor_juros = None
        valor_selic = None

    if eh_conta:
        data_base = None
        data_calculo = st.date_input(
            "Data-base", value=_qp_date("data_calculo"), format="DD/MM/YYYY",
            min_value=date(2000, 1, 1),
            help="Data-base do ofício: data em que os valores acima estão expressos. "
                 "A atualização parte daqui.",
        )
    else:
        c3, c4 = st.columns(2)
        data_base = c3.date_input("Data-base", value=_qp_date("data_base"), format="DD/MM/YYYY",
                                  min_value=date(1964, 10, 1),
                                  help="Marco inicial da correção. Motor histórico (por natureza) cobre desde out/1964; índices SGS desde jan/2000.")
        data_calculo = c4.date_input("Data do cálculo", value=_qp_date("data_calculo"), format="DD/MM/YYYY",
                                     min_value=date(1964, 10, 1),
                                     help="Até quando corrigir o originário (≥ data-base).")

    natureza_hist = None
    assist_idx = None
    preset = None
    if not eh_conta:
        st.subheader(f"{next(_sec)} · Regime de correção")
        _NAT_HIST = [
            "(usar índice SGS abaixo)",
            "comum — condenatória geral",
            "servidor — remuneratório",
            "previdenciario — benefício",
            "tributario — repetição de indébito",
            "desapropriacao — moratórios 6% a.a.",
            "assistencial — BPC/LOAS",
        ]
        nh = st.selectbox(
            "Correção por natureza (motor histórico — cobre desde 1964)",
            _NAT_HIST,
            index=_qp_index("nat_hist", _NAT_HIST),
            help=(
                "Corrige o originário do ZERO pela fase de condenação (Temas 810/905): "
                "correção pela Tabela oficial do CJF + juros simples por natureza. "
                "Deixe no SGS para o regime simples/composto declarado."
            ),
        )
        natureza_hist = None if nh.startswith("(") else nh.split(" — ")[0]
        if natureza_hist == "assistencial":
            assist_idx = st.selectbox(
                "Índice (BPC/LOAS)", ["IPCA-E", "INPC"],
                index=_qp_index("assist_idx", ["IPCA-E", "INPC"]),
                help="Decisão jurídica (§5): o Tema 810 aponta IPCA-E.",
            )
        if natureza_hist is None:
            preset = st.selectbox(
                "Regime (índice SGS)", _REGIME_OPCOES,
                # slug próprio (`?regime=`): os dois "Simples" empatam no
                # prefixo e `_qp_index` não os distingue.
                index=_REGIME_SLUG_IDX.get((_qp_get("regime") or "").lower(), 0),
                help="Como corrigir o valor originário até a data do cálculo.",
            )
    else:
        preset = "Automático (só atualização ao presente)"

    st.subheader(f"{next(_sec)} · Natureza e tributação (PSS / IR)")
    _NAT_OPCOES = [
        "(não informar)",
        "remuneratorio — salários / vencimentos",
        "previdenciario — aposentadoria / pensão",
        "indenizatorio — dano / verba indenizatória",
        "misto — mistura tributável e não-tributável",
    ]
    natureza_lbl = st.selectbox(
        "Natureza do Crédito",
        _NAT_OPCOES,
        index=_qp_index("natureza", _NAT_OPCOES),
        help=(
            "Define a incidência de PSS e IR. Remuneratório: incide PSS e IR. "
            "Previdenciário: só IR. Indenizatório: nenhum. Misto: fica 'a apurar' "
            "(o advogado segrega a parcela remuneratória). Crédito alimentar de "
            "salários entra como remuneratório."
        ),
    )
    natureza = None if natureza_lbl.startswith("(") else natureza_lbl.split(" — ")[0]

    c5, c6 = st.columns(2)
    with c5:
        st.markdown("**Contribuições (previdência / assistência)**")
        pss_modo = st.radio(
            "Contribuições", ["Não descontar", "Valor no ofício (R$)", "Por alíquota (%)"],
            # `?pss_modo=` explícito (snapshot) vence; senão a heurística de
            # sempre — valor presente na URL abre no modo "Valor no ofício".
            index={"nao": 0, "valor": 1, "aliquota": 2}.get(
                _qp_get("pss_modo") or "", 1 if _qp_get("valor_pss") else 0),
            label_visibility="collapsed",
            help="Escolha a fonte do PSS. Os dois campos abaixo ficam sempre "
                 "visíveis — vale o que corresponde ao modo escolhido.",
        )
        # Campos SEMPRE renderizados (dentro de st.form, campos condicionais não
        # aparecem ao trocar o radio — o form só re-renderiza no submit).
        pss_val_in = st.text_input(
            "↳ Valor das contribuições (R$)", key="pss",
            placeholder="0,00",
        )
        aliq_in = st.text_input(
            # tem `value=`, então lê o param aqui — não entra em `_SEED_PARES`
            "↳ Alíquota (%)",
            value=_qp_get("apss") or "14", key="apss",
            help="Padrão 14%. Informe um valor maior que 0. "
                 "Para não descontar PSS, escolha 'Não descontar'.",
        )
        valor_pss = None
        estimar_pss = False
        aliq_pss = None
        erro_pss = None
        erro_aliq = None
        if pss_modo == "Não descontar":
            valor_pss = Decimal("0")  # explícito: congela em 0 (evita auto-estimativa)
        elif pss_modo == "Valor no ofício (R$)":
            valor_pss, erro_pss = _ler_declarado(
                pss_val_in, "PSS", "Não descontar ou Por alíquota (%)")
        elif pss_modo == "Por alíquota (%)":
            estimar_pss = True
            aliq_pss, erro_aliq = _ler_percentual(aliq_in, "Alíquota do PSS")
            if erro_aliq is None and aliq_pss is None:
                # Vazio (ou só espaços) no modo "Por alíquota": o motor usaria 14%
                # em silêncio. Decisão do time (30/09/2026): bloqueia. O campo
                # nasce com 14, então só erra quem apaga o número.
                erro_aliq = ("Alíquota do PSS: informe a alíquota (maior que 0) ou "
                             "escolha outro modo (Não descontar ou Valor no ofício (R$))")
            elif aliq_pss is not None and aliq_pss == 0:
                # O motor trata alíquota <= 0 como "não informada" e usa 14%
                # (calculadora.py, clamp). Quem digita 0 quer zero, não 14%:
                # o caminho para "sem PSS" é o modo "Não descontar".
                erro_aliq = ("Alíquota do PSS: Informe uma alíquota maior que 0 "
                             "ou escolha Não descontar.")
    with c6:
        st.markdown("**Imposto de Renda a deduzir**")
        ir_modo = st.radio(
            "Imposto de Renda", ["Não descontar", "Valor no ofício (R$)", "Estimar por natureza"],
            index={"nao": 0, "valor": 1, "estimar": 2}.get(
                _qp_get("ir_modo") or "", 1 if _qp_get("valor_ir") else 0),
            label_visibility="collapsed",
            help="Escolha a fonte do IR. Os dois campos abaixo ficam sempre "
                 "visíveis — valem conforme o modo escolhido.",
        )
        # Campos SEMPRE renderizados (mesma razão do PSS — limitação do st.form).
        ir_val_in = st.text_input(
            "↳ Valor do IR (R$)", key="ir",
            placeholder="0,00",
        )
        _meses_ini, _aviso_meses = _meses_da_url()
        if _aviso_meses:
            st.warning(_aviso_meses)
        meses = st.number_input(
            "↳ Número de meses (RRA)", min_value=0,
            value=_meses_ini, step=1,
            help="Dilui a base do IR-RRA. Sem os meses, o IR estimado fica "
                 "'a apurar' em vez de inflar.",
        )
        valor_ir = None
        estimar_ir = False
        erro_ir = None
        if ir_modo == "Não descontar":
            valor_ir = Decimal("0")  # explícito: congela em 0 (evita IR meses=1 inflado)
        elif ir_modo == "Valor no ofício (R$)":
            valor_ir, erro_ir = _ler_declarado(
                ir_val_in, "IR", "Não descontar ou Estimar por natureza")
        elif ir_modo == "Estimar por natureza":
            estimar_ir = True

    st.subheader(f"{next(_sec)} · Honorários")
    c7, c8 = st.columns(2)
    hon_con, erro_hc = _ler_percentual(
        c7.text_input("Honorários Contratuais (%)", key="hc", placeholder="20",
                      help="Descontado no FINAL, sobre o valor atualizado — entra "
                           "no memorial como linha própria, igual PSS e IR."),
        "Honorários Contratuais (%)")
    hon_suc, erro_hs = _ler_percentual(
        c8.text_input("Honorários de Sucumbência (%)", key="hs", placeholder="10",
                      help="NÃO sai do líquido do credor. Vai para o memorial "
                           "na seção 'Honorários do advogado', com o valor "
                           "calculado sobre o bruto atualizado e o IR de 27,5%."),
        "Honorários de Sucumbência (%)")

    # Quando o pré-preenchimento rodou e NÃO trouxe o contratual, diga isso na
    # tela. É o campo mais perigoso do formulário: ele vem do CONTRATO, não do
    # processo (só 20% dos casos medidos o declaram em algum documento), e se
    # ficar vazio em silêncio o "líquido" sai IGUAL ao bruto — 43% de diferença
    # num número que o comercial lê como valor da proposta.
    if _prefill_rodou and not _qp_get("hc") and not _qp_get("snapshot"):
        c7.caption("↳ **não encontrado nos documentos** — vem do contrato com o "
                   "cliente. Sem ele não há desconto e o valor final é o BRUTO.")

    st.subheader(f"{next(_sec)} · Precatório e período de graça")
    c9, c10 = st.columns(2)
    _MODAL_OPCOES = ["(não informar)", "precatorio", "rpv"]
    modalidade = c9.selectbox(
        "Espécie da requisição", _MODAL_OPCOES, index=_qp_index("modalidade", _MODAL_OPCOES)
    )
    modalidade = None if modalidade.startswith("(") else modalidade
    data_apres = c10.date_input("Data de apresentação do ofício ao tribunal", value=_qp_date("data_apres"), format="DD/MM/YYYY",
                                min_value=date(2000, 1, 1),
                                help="Âncora do período de graça (art. 100 §5º CF + SV 17). "
                                     "O corte varia por época: 1º/07 até 2021, 02/04 (2022-2025), 1º/02 (2026+).")

    # Superpreferência (idoso 80+/doença grave/PcD, RCL/EC 114): pagamento
    # BRUTO já recebido antes do restante do crédito. Abatido NA DATA em que
    # ocorreu (corrige até lá, subtrai, segue corrigindo o saldo) — não é
    # subtração no final sobre o valor cheio. Ver `cenarios.construir_cenarios`.
    c9b, c10b = st.columns(2)
    with c9b:
        superpref_valor = money(
            "Superpreferência paga (R$)", "sp_val",
            help="Antecipação já recebida via superpreferência (idoso 80+/doença "
                 "grave/PcD). Valor BRUTO — abatido do saldo corrigido na data do "
                 "pagamento, antes de PSS/IR/honorários incidirem sobre o resto.",
        )
    superpref_data = c10b.date_input(
        "Data do pagamento da superpreferência", value=_qp_date("sp_data"),
        format="DD/MM/YYYY", min_value=date(2000, 1, 1),
        help="Data em que o valor acima foi efetivamente pago ao credor.",
    )

    # Ente devedor + ano orçamentário — metadados do precatório (aparecem no
    # memorial; NÃO alteram o cálculo). Ente com lista dos principais + opção
    # "Outro (digitar)" — o campo de texto fica SEMPRE visível (dentro de
    # st.form o condicional só apareceria no submit; mesma razão do PSS/IR).
    c11, c12 = st.columns(2)
    # `_ENTE_OPCOES`/`_ANO_OPCOES` moraram aqui; foram para os helpers porque
    # `_params_do_snapshot` roda ANTES do formulário e precisa das listas.
    ente_sel = c11.selectbox(
        "Ente/Entidade devedora", _ENTE_OPCOES, index=_qp_index("ente", _ENTE_OPCOES),
        help="Quem paga o precatório. Se não estiver na lista, escolha 'Outro' e digite abaixo.",
    )
    ano_sel = c12.selectbox(
        "Ano orçamentário", _ANO_OPCOES, index=_qp_index("ano_orc", _ANO_OPCOES),
        help="Exercício em que o precatório entra na proposta orçamentária do ente (art. 100 CF).",
    )
    ente_custom = st.text_input(
        "↳ Entidade devedora - preencha se escolheu 'Outro' acima", key="ente_outro",
        placeholder="ex.: Município de Vitória / DER-ES / Autarquia estadual",
    )
    if ente_sel.startswith("Outro"):
        ente_devedor = ente_custom.strip() or None
    elif ente_sel.startswith("("):
        ente_devedor = None
    else:
        ente_devedor = ente_sel
    ano_orcamentario = None if ano_sel.startswith("(") else ano_sel

    # Esfera do ente — define quando entra o regime IPCA+2% da EC 136 (Provimento
    # CNJ 207/2025): federais migram set/2025, estaduais/municipais ago/2025.
    # 'Auto' deduz pelo ente (União/INSS/federal → federal; senão estadual).
    data_expedicao = st.date_input(
        "Data de expedição do ofício",
        value=_qp_date("data_expedicao"), format="DD/MM/YYYY",
        min_value=date(1964, 10, 1),
        help=(
            "Só importa para conta ANTERIOR a dez/2021. Se o precatório foi expedido "
            "até 25/03/2015, a fase precatório usa TR na janela dez/2009–mar/2015 "
            "(art. 21-A XI + §7º da Res. CNJ 303). Vazio = não aplica TR (usa IPCA-E) "
            "— é o regime do que foi expedido após a modulação das ADIs 4357/4425."
        ),
    )

    _ESFERA_OPCOES = ["Auto (deduz pelo ente)", "Estadual / Municipal / DF", "Federal (União / INSS / autarquia federal)"]
    esfera_sel = st.selectbox(
        "Esfera do ente devedor", _ESFERA_OPCOES,
        # `?esfera=` (snapshot) reabre com a escolha EXPLÍCITA — a entrada
        # guarda o resultado da dedução, não o "Auto" que a produziu.
        index={"estadual": 1, "municipal": 1, "federal": 2}.get(
            (_qp_get("esfera") or "").lower(), 0),
        help=(
            "Quem deve o precatório: a **União** (e autarquias federais, como o "
            "INSS) ou um **estado/município/DF**. Muda **uma só coisa** no cálculo: "
            "o mês em que a correção passa a ser o **IPCA + 2% a.a. da EC 136/2025** "
            "— federais só a partir de **set/2025**; estaduais/municipais desde "
            "**ago/2025** (Provimento CNJ 207/2025). Se a atualização (data-alvo) "
            "não alcança ago/2025, este campo **não faz diferença**. 'Auto' deduz "
            "pelo nome do ente (União/INSS/federal → federal; senão estadual)."
        ),
    )
    st.caption(
        f"↳ tratando como **{'federal' if esfera_sel.startswith('Federal') else ('estadual' if esfera_sel.startswith('Estadual') else 'auto')}** "
        "· só influencia o trecho ago–set/2025 em diante (EC 136)."
    )
    if esfera_sel.startswith("Federal"):
        esfera = "federal"
    elif esfera_sel.startswith("Estadual"):
        esfera = "estadual"
    else:  # Auto pelo ente
        _ente_l = (ente_devedor or ente_sel or "").lower()
        esfera = "federal" if any(k in _ente_l for k in ("união", "uniao", "inss", "federal")) else "estadual"

    st.subheader(f"{next(_sec)} · Atualização ao presente")
    data_alvo = st.date_input("Data de atualização", value=_qp_date("data_alvo"), format="DD/MM/YYYY",
                              help="Até quando atualizar (padrão: hoje). Recua se passar da cobertura do BACEN.")
    referencia = st.text_input(
        "Nº do processo / requisição", key="ref",
        placeholder="ex.: Precatório nº ... - Fulano de Tal",
    )
    observacao = st.text_area(
        "Observações Gerais", key="obs",
        placeholder="Anotações do advogado que devem constar no PDF.",
    )

    submitted = st.form_submit_button("Calcular", type="primary", use_container_width=True)

# ───────────────────────────── cálculo ─────────────────────────────

# `submitted` só é True na execução do clique em "Calcular". Qualquer outro
# botão da página (baixar memorial, enviar ao CRM) provoca um rerun em que ele
# volta a False — e o bloco inteiro de resultados sumiria da tela, junto com o
# handler do botão que acabou de ser clicado. Foi o que fez o "Conferir (ensaio)"
# parecer não fazer nada: ele FUNCIONAVA, mas a tela era redesenhada sem ele.
#
# Recalcular no rerun é seguro e barato: widget dentro de `st.form` só atualiza o
# session_state no submit, então os valores lidos aqui são exatamente os do
# último "Calcular" — e `calcular_dict` é determinístico.
if submitted:
    st.session_state["_ja_calculou"] = True

if submitted or st.session_state.get("_ja_calculou"):
    erros = [e for e in (erro_pss, erro_ir, erro_aliq, erro_hc, erro_hs) if e]
    if data_calculo is None:
        erros.append(f"{'Data-base' if eh_conta else 'Data do cálculo'} é obrigatória.")
    if not eh_conta and data_base is None:
        erros.append("No modo originário, a data-base é obrigatória.")
    if data_base and data_calculo and data_calculo < data_base:
        erros.append("Data do cálculo deve ser ≥ data-base.")
    if not eh_conta and valor_originario is None:
        erros.append("No modo originário, o valor originário é obrigatório.")

    if erros:
        for e in erros:
            st.error(e)
        st.stop()

    entrada = EntradaCalculadora(
        valor_total=valor_total,
        valor_bruto_reclamante=valor_bruto_recl,
        valor_principal_corrigido=valor_principal,
        valor_juros=valor_juros if valor_juros is not None else Decimal("0"),
        valor_selic=valor_selic if valor_selic is not None else Decimal("0"),
        valor_originario=valor_originario,
        data_base=data_base,
        data_calculo=data_calculo,
        regime=build_regime(preset) if (not eh_conta and natureza_hist is None) else None,
        natureza=natureza_hist,
        assistencial_indice=assist_idx,
        natureza_tributaria=natureza,
        valor_pss=valor_pss,
        estimar_pss=estimar_pss,
        aliquota_pss_pct=aliq_pss,
        valor_ir=valor_ir,
        estimar_ir=estimar_ir,
        meses_competencia=int(meses) if meses and meses >= 1 else None,
        # Sucumbencial NÃO entra no cálculo da calculadora: não sai do líquido do
        # credor. No motor ele seria descontado — por isso passa None aqui; o
        # valor mostrado no memorial é derivado à parte (_suc_valor).
        honorarios_sucumbenciais_pct=None,
        honorarios_contratuais_pct=hon_con,
        modalidade=modalidade,
        data_apresentacao=data_apres,
        data_expedicao=data_expedicao,
        data_alvo=data_alvo,
        esfera=esfera,
        valor_superpreferencia=superpref_valor,
        data_pagamento_superpreferencia=superpref_data,
    )

    try:
        res = calculadora.calcular_dict(entrada)
    except Exception as exc:  # noqa: BLE001
        st.error(f"Erro no cálculo: {exc}")
        st.stop()

    # PSS/IR DECLARADOS entram nominais (sem correção) e saem do total ATUALIZADO.
    # Se juntos passam desse total, o líquido nasce negativo — quase sempre valor
    # digitado errado (centavos no lugar de reais, campo trocado). Erro visível e
    # nada segue: sem memorial e sem envio ao card. Só o que foi DIGITADO entra
    # na soma; PSS/IR estimados vêm do motor e não passam por esta checagem.
    _declarados = [(rot, v) for rot, modo, v in (
        ("PSS", pss_modo, valor_pss), ("IR", ir_modo, valor_ir))
        if modo == "Valor no ofício (R$)" and v is not None]
    _total_atual = (res.get("cenario_homologado") or {}).get("valor_total_atualizado")
    if _declarados and _total_atual is not None:
        _soma_decl = sum((v for _, v in _declarados), Decimal("0"))
        if _soma_decl > Decimal(str(_total_atual)):
            _det = " + ".join(f"{rot} {fmt_brl(v)}" for rot, v in _declarados)
            if len(_declarados) > 1:
                _det += f" = {fmt_brl(_soma_decl)}"
            st.error(
                f"O valor declarado ({_det}) é maior que o total bruto atualizado "
                f"({fmt_brl(_total_atual)}) — o líquido ficaria negativo. Confira o "
                "que foi digitado; o PSS/IR declarado entra sem correção monetária."
            )
            st.stop()

    # Rede definitiva, em QUALQUER modo: o líquido que o motor devolveu. A soma
    # PSS + IR acima não enxerga o honorário contratual (30% de 150.000 = 45.000:
    # PSS 100.000 + IR 40.000 cabe no total e dá −35.000), nem um percentual
    # digitado de forma absurda. Líquido negativo não vira memorial nem card.
    _cen_liq = res.get("cenario_homologado") or {}
    _liq_res = _cen_liq.get("valor_liquido_atualizado")
    if _liq_res is not None and Decimal(str(_liq_res)) < 0:
        def _comp(v, vazio="R$ 0,00"):
            return fmt_brl(v) if v is not None else vazio
        st.error(
            f"O líquido ficou negativo ({fmt_brl(_liq_res)}): total atualizado "
            f"{_comp(_cen_liq.get('valor_total_atualizado'))} − honorários contratuais "
            f"{_comp(_cen_liq.get('valor_honorarios_contratuais'))} − PSS "
            f"{_comp(_cen_liq.get('valor_pss'), 'a apurar')} − IR "
            f"{_comp(_cen_liq.get('valor_ir'), 'a apurar')}. Confira os valores "
            "digitados (PSS/IR declarados entram sem correção monetária) e o "
            "percentual de honorários."
        )
        st.stop()

    # Memorial da correção do zero (modo originário por natureza).
    _orig = res.get("originario")
    if _orig:
        with st.expander("🧮 Correção do originário (motor histórico — tabela oficial CJF)", expanded=True):
            oc1, oc2, oc3 = st.columns(3)
            oc1.metric("Principal corrigido", fmt_brl(_orig["principal_corrigido"]))
            oc2.metric("Juros de mora", fmt_brl(_orig["juros"]))
            oc3.metric("Total na data do cálculo", fmt_brl(_orig["total"]))
            _linhas = [
                f"correção {c['indice']} · {c['inicio'][:7]}→{c['fim'][:7]} · ×{Decimal(c['fator']):.6f}"
                for c in _orig["componentes_correcao"]
            ] + [
                f"juros {j['modo']} · {j['inicio'][:7]}→{j['fim'][:7]} · {fmt_brl(j['valor'])}"
                for j in _orig["componentes_juros"]
            ]
            st.caption(" · ".join(_linhas))
            for _a in _orig.get("avisos", []):
                st.warning(_a)

    # Dados de entrada estruturados para o memorial.
    _cen = res.get("cenario_homologado") or {}
    _alvo_efetivo = (_cen.get("atualizacao") or {}).get("data_alvo")
    if hon_con and hon_suc:
        _hon = f"contr. {hon_con}% · sucumb. {hon_suc}%"
    elif hon_con:
        _hon = f"contratuais {hon_con}%"
    elif hon_suc:
        _hon = f"sucumbenciais {hon_suc}%"
    else:
        _hon = "—"
    if eh_conta:
        _valores = [
            ("Principal corrigido", fmt_brl(valor_principal)),
            ("Juros de mora", fmt_brl(valor_juros) if valor_juros else "—"),
            ("SELIC acumulada", fmt_brl(valor_selic) if valor_selic else "—"),
            ("Total da conta", fmt_brl(valor_total)),
            ("Honorários", _hon),
        ]
    else:
        _valores = [
            ("Valor originário", fmt_brl(valor_originario)),
            ("Regime", f"{natureza_hist} (motor histórico)" if natureza_hist else preset),
            ("Honorários", _hon),
        ]
    _datas = []
    if data_base:
        _datas.append(("Data-base", fmt_data(data_base)))
    _datas.append(("Data do cálculo", fmt_data(data_calculo)))
    if data_apres:
        _datas.append(("Apresentação ao tribunal", fmt_data(data_apres)))
    _datas.append(("Data-alvo", fmt_data(_alvo_efetivo) if _alvo_efetivo else fmt_data(data_alvo)))
    _outros = []
    if ente_devedor:
        _outros.append(("Ente devedor", ente_devedor))
    if ano_orcamentario:
        _outros.append(("Ano orçamentário", ano_orcamentario))
    if natureza:
        _outros.append(("Natureza", natureza))
    if modalidade:
        _outros.append(("Modalidade", modalidade))
    _outros.append(("PSS", pss_modo + (f" ({aliq_pss}%)" if pss_modo.startswith("Por") and aliq_pss else "")))
    _outros.append(("IR-RRA", ir_modo + (f" ({int(meses)} meses)" if ir_modo.startswith("Estimar") and meses else "")))
    # Iniciais da trilha = valores CHEIOS da conta: o crédito é atualizado
    # inteiro e os honorários contratuais saem no final, como linha da cascata
    # (igual PSS/IR) — não há mais carve antes da atualização.
    _p0 = valor_principal if valor_principal else valor_total
    _iniciais = {
        "principal": _p0,
        "juros": valor_juros or Decimal("0"),
        "selic": valor_selic or Decimal("0"),
    }

    st.divider()

    oferta = res.get("valor_oferta_base")
    pior = res.get("pior_cenario")
    st.markdown(
        f'<div class="oferta"><div class="lbl">Oferta-base sugerida '
        f'(líquido do pior cenário{f" — {pior}" if pior else ""})</div>'
        f'<div class="val">{fmt_brl(oferta)}</div></div>',
        unsafe_allow_html=True,
    )
    if oferta is None:
        st.info("Sem oferta-base: faltam dados suficientes (ex.: valor de face ou data do cálculo).")

    # Snapshot reaberto: os dois números lado a lado. A divergência é
    # esperada (índices andaram, motor pode ter mudado) — o que não pode é
    # ela passar despercebida.
    if st.session_state.get("_snap_aberto") and _qp_get("snapshot"):
        _sa = st.session_state["_snap_aberto"]
        _liq_novo = (res.get("cenario_homologado") or {}).get("valor_liquido_atualizado")
        st.caption(
            f"🧊 Congelado no snapshot ({fmt_data(_sa.get('criado_em'))}): "
            f"**{fmt_brl(_sa.get('valor_liquido'))}** · recalculado agora: "
            f"**{fmt_brl(_liq_novo)}** — divergência aqui é índice/motor novo "
            f"(ver o painel do topo), não erro de conta.")

    # PSS por alíquota mas a natureza não incide → explica em vez de zerar em silêncio.
    if pss_modo == "Por alíquota (%)":
        _pss_res = str((res.get("cenario_homologado") or {}).get("valor_pss"))
        if natureza in ("previdenciario", "indenizatorio") and _pss_res in ("0.00", "0"):
            st.info(
                f"ℹ️ O PSS ficou **R$ 0,00** porque a natureza **'{natureza}'** não recolhe "
                "contribuição previdenciária (só o **remuneratório** incide). Se a conta traz "
                "um valor de PSS, use o modo **'Valor no ofício (R$)'** — aí ele é descontado "
                "independentemente da natureza."
            )
        elif natureza == "misto":
            st.info(
                "ℹ️ O PSS ficou **'a apurar'** porque a natureza **'misto'** exige segregar a "
                "parcela remuneratória (o sistema não decide sozinho). Use **'Valor no ofício "
                "(R$)'** se você tem o valor."
            )
        elif natureza is None:
            st.info(
                "ℹ️ O PSS **não foi estimado** porque a natureza não foi informada. Escolha a "
                "natureza (remuneratório) ou use **'Valor no ofício (R$)'**."
            )

    _proj = _meses_projetados(res)
    if _proj:
        _mes_alvo, _min_real = _proj
        st.warning(
            f"⚠️ Esta atualização usa **projeção do Boletim Focus/BACEN** para os "
            f"meses após {_min_real} (até {_mes_alvo}). Os índices oficiais vão "
            f"até {_min_real}; os meses seguintes são **estimativa de mercado**, "
            f"não índice publicado — confira antes de fechar a oferta."
        )

    # Sucumbencial: NÃO sai do líquido do credor — mas o VALOR é exibido no
    # memorial (seção "Honorários do advogado"), porque o comercial precisa
    # dele: advogado que quer ceder a própria parte pergunta quanto ela vale.
    # Base = valor BRUTO atualizado (confirmado com o Matheus em 25/08/2026), a
    # mesma dos contratuais, então as duas linhas são comparáveis. Nada aqui
    # toca líquido: o motor continua recebendo `honorarios_sucumbenciais_pct
    # =None` (se recebesse o percentual, deduziria do líquido do credor).
    _suc_valor = None
    if hon_suc:
        _base_suc = (res.get("cenario_homologado") or {}).get("valor_total_atualizado")
        if _base_suc is not None:
            _suc_valor = (Decimal(str(_base_suc)) * Decimal(str(hon_suc))
                          / Decimal("100")).quantize(Decimal("0.01"))
        st.caption(
            f"ℹ️ Honorários sucumbenciais de {hon_suc}%: não saem do líquido do "
            f"credor. O valor vai no memorial, na seção 'Honorários do advogado'."
        )

    # Memorial em PDF (montado em memória; nada é armazenado).
    _proj_aviso = None
    if _proj:
        _proj_aviso = (
            f"Atualização usa projeção do Boletim Focus/BACEN para os meses após "
            f"{_proj[1]} (até {_proj[0]}) — estimativa de mercado, não índice publicado."
        )
    # Cenários por % de honorário contratual — anexo PROVISÓRIO do memorial.
    # O contrato de honorários costuma chegar depois da pré-análise; a tabela
    # responde "e se vier X%?" sem desconto por fora (que erra a base de PSS/IR
    # — caso #2405). Cada linha é o motor completo; falhar aqui não pode
    # derrubar o memorial.
    try:
        _cen_hc = calculadora.cenarios_honorarios_contratuais(entrada)
    except Exception:  # noqa: BLE001
        _cen_hc = None
    try:
        _pdf = memorial.gerar_memorial_pdf(
            _valores, _datas, _outros, _iniciais, res, gerado_em=date.today(),
            referencia=referencia or "", aviso_projecao=_proj_aviso,
            observacao_advogado=(observacao or "").strip() or None,
            sucumbenciais_pct=hon_suc, sucumbenciais_valor=_suc_valor,
            cenarios_honorarios=_cen_hc,
        )
        st.download_button(
            "📄 Baixar memorial de cálculo (PDF)", data=_pdf,
            file_name=nome_arquivo(referencia), mime="application/pdf",
            use_container_width=True,
        )
    except Exception as _exc:  # noqa: BLE001
        _pdf = None
        st.caption(f"(Não foi possível gerar o PDF: {_exc})")

    # ── Enviar para o card do CRM ──────────────────────────────────────────
    # Só aparece com BITRIX_WEBHOOK no ambiente. O número que vai para o card é
    # o que está NESTA tela — o advogado já conferiu e ajustou; recalcular do
    # outro lado abriria espaço para divergir do que ele aprovou.
    # Import TARDIO e CONDICIONADO: a calculadora é o que o time usa todo dia, e
    # ela não pode quebrar por causa de um módulo acessório. Sem BITRIX_WEBHOOK
    # no ambiente, `bitrix`/`hub` (que dependem de httpx) nem são carregados.
    _liq = (res.get("cenario_homologado") or {}).get("valor_liquido_atualizado")
    _bx_mod = _hub_mod = None
    if os.environ.get("BITRIX_WEBHOOK") and _liq is not None:
        try:
            import bitrix as _bx_mod  # noqa: PLC0415
            import hub as _hub_mod  # noqa: PLC0415
        except Exception as _e:  # noqa: BLE001 — dependência ausente não derruba o cálculo
            st.caption(f"(Envio ao CRM indisponível: {type(_e).__name__})")

    def _payload_snapshot(deal_id: int, valor_card: str) -> dict:
        """O que congela no hub: a entrada REAL + o res inteiro + procedência.

        `serializar_entrada` serializa o dataclass diretamente (nunca um
        espelho); `_tela` leva o contexto do memorial que não é do motor.
        `ultimo_mes_real` diz até onde os índices eram REAIS neste momento —
        é o que explica a divergência num recálculo futuro.
        """
        return {
            "entrada": _hub_mod.serializar_entrada(entrada, tela={
                "referencia": (referencia or "").strip(),
                "observacao": (observacao or "").strip(),
                "ente_devedor": ente_devedor,
                "ano_orcamentario": ano_orcamentario,
            }),
            "resultado": res,
            "autor": usuario_atual(),
            "deal_id": str(deal_id),
            "valor_liquido": str(_liq),
            "valor_card": valor_card,
            "motor_versao": sha_do_deploy(),
            "ultimo_mes_real": {i: _series.ultimo_mes_real(i)
                                for i in ("SELIC", "IPCA", "IPCA-E")},
        }

    if _bx_mod is not None and _bx_mod.habilitado() and _liq is not None:
        with st.expander("📤 Enviar para o card do CRM",
                         expanded=bool(st.session_state.get("bx_deal"))):
            _deal = st.text_input("Número do card (ID do negócio)", key="bx_deal",
                                  placeholder="ex.: 2387")
            st.caption(
                f"Vai gravar **{fmt_brl(_liq)}** em *Cálculo Atualizado (Valor)*"
                + (", o memorial em PDF" if _pdf else "")
                + ", e as peças do caso (desta sessão ou do que ficou guardado)"
                + f" · só no funil {_bx_mod.categoria_permitida()} · **nunca sobrescreve campo "
                  "já preenchido**."
            )
            _n1, _n2 = st.columns(2)
            _num_oficio = _n1.text_input("Número do ofício", key="bx_num_oficio",
                                         placeholder="057/2025")
            _num_prec = _n2.text_input("Nº do precatório (CNJ)", key="bx_num_precatorio",
                                       placeholder="0000000-00.0000.0.00.0000")
            _c_ens, _c_env = st.columns(2)
            _ensaiar = _c_ens.button("Conferir (ensaio, não grava)", key="bx_ensaio",
                                     use_container_width=True)
            _enviar = _c_env.button("Enviar para o card", key="bx_enviar", type="primary",
                                    use_container_width=True)
            if (_ensaiar or _enviar) and not (_deal or "").strip().isdigit():
                st.error("Informe o número do card.")
            elif _ensaiar or _enviar:
                _snap_id = _jr_id = None   # Fase 2 — preenchidos no caminho do envio
                try:
                    _did = int(_deal.strip())
                    _card = _bx_mod.carregar_deal(_did)
                    # as peças que o advogado subiu na tela de pré-análise
                    _pecas = {}
                    if st.session_state.get("pre_conta_bytes"):
                        _pecas["conta"] = [("calculo_homologado.pdf",
                                            st.session_state["pre_conta_bytes"])]
                    if st.session_state.get("pre_oficio_bytes"):
                        _pecas["oficio"] = [("oficio.pdf",
                                             st.session_state["pre_oficio_bytes"])]
                    _sents = st.session_state.get("pre_sent_bytes") or []
                    if _sents:
                        _pecas["sentenca"] = [(f"sentenca_{i + 1}.pdf", b)
                                              for i, b in enumerate(_sents)]
                    # A sessão do navegador é frágil: reiniciar o servidor, dar
                    # refresh ou expirar a sessão apaga os PDFs — enquanto os
                    # VALORES sobrevivem na URL. O resultado seria um envio
                    # silenciosamente sem anexos. O caso no hub é a fonte
                    # durável; buscar lá torna o envio independente da aba.
                    # ⚠ Com a calculadora e a pré-análise em PROCESSOS separados, a
                    # sessão daqui nunca tem os PDFs: eles ficam na sessão de lá.
                    # O caso guardado deixou de ser plano B — é o único caminho.
                    _fonte_pecas = "desta sessão"
                    if not _pecas and _hub_mod is not None and _hub_mod.habilitado():
                        # O caso vem no LINK (`?caso=`), não do número digitado
                        # aqui: enviar para um card diferente do analisado — um
                        # de teste, uma correção — perderia os anexos em
                        # silêncio. O card só é consultado quando não há link.
                        _caso_id = (_qp_get("caso") or "").strip()
                        _caso_do_card = ({"id": _caso_id} if _caso_id
                                         else _hub_mod.caso_do_card(_did))
                        if _caso_do_card:
                            for _d in _hub_mod.documentos_do_caso(_caso_do_card["id"]):
                                _pecas.setdefault(_d["peca"], []).append(
                                    (_d["nome"], _hub_mod.baixar_documento(
                                        _caso_do_card["id"], _d["id"])))
                            if _pecas:
                                _fonte_pecas = ("do caso vindo da pré-análise" if _caso_id
                                                else "do caso guardado no hub")
                    _campos, _pulados = _bx_mod.montar(
                        _card, valor_liquido=_liq, hon_contratuais=hon_con,
                        atualizado_para=_alvo_efetivo or data_alvo or date.today(),
                        numero_precatorio=(_num_prec or "").strip() or None,
                        numero_oficio=(_num_oficio or "").strip() or None,
                        # a natureza é a do SELETOR, não a do param: o advogado
                        # pode tê-la corrigido na tela, e é a dele que vale
                        natureza=natureza,
                        memorial_pdf=_pdf, pecas=_pecas)
                    _linhas = [
                        f"Valor final atualizado: {fmt_brl(_liq)}",
                        # a data que o MOTOR usou, não a que o campo mostra: o
                        # "Data-alvo" fica vazio por padrão (o motor assume hoje)
                        # e formatar None com `:%d/%m/%Y` estourava um TypeError.
                        f"Atualizado até {fmt_data(_alvo_efetivo or data_alvo)}"
                        + (f" · {_proj_aviso}" if _proj_aviso else " · índice publicado"),
                        f"Honorários contratuais: {hon_con}%" if hon_con
                        else "Honorários contratuais: NÃO informados — valor acima é BRUTO",
                        f"Referência: {referencia or '—'}",
                    ]
                    # ── Fase 2: snapshot + journal, journal-PRIMEIRO ────────
                    # No ENVIO os dois são best-effort (a calculadora funciona
                    # sem hub — a mesma regra do ledger); o que não se negocia
                    # é a ORDEM: a intenção entra no journal antes de o card
                    # ser tocado, e a conclusão vem depois. Sobrescrita e
                    # reversão, ao contrário, BLOQUEIAM sem trilha.
                    _cid_f2 = None
                    if _enviar and _hub_mod is not None and _hub_mod.habilitado():
                        try:
                            _cid_f2 = ((_qp_get("caso") or "").strip()
                                       or ((_hub_mod.caso_do_card(_did) or {}).get("id")))
                            if _cid_f2:
                                _snap_id = _hub_mod.gravar_snapshot(
                                    _cid_f2,
                                    _payload_snapshot(
                                        _did,
                                        _campos.get(_bx_mod.CAMPO_VALOR)
                                        or _bx_mod.brl_atualizado(
                                            Decimal(str(_liq)),
                                            _alvo_efetivo or data_alvo or date.today())),
                                    memorial_pdf=_pdf)["id"]
                        except Exception as _e_f2:  # noqa: BLE001 — snapshot não derruba envio
                            st.caption(f"⚠ snapshot não gravou "
                                       f"({type(_e_f2).__name__}) — o envio segue")
                        # journal só quando o VALOR vai ser escrito: campo já
                        # preenchido no card = `montar` pulou = nada a auditar.
                        if _cid_f2 and _bx_mod.CAMPO_VALOR in _campos:
                            try:
                                _jr_id = _hub_mod.journal_registrar(
                                    _cid_f2, deal_id=str(_did), tipo="envio",
                                    valor_antes=str(_card.get(_bx_mod.CAMPO_VALOR) or ""),
                                    valor_depois=str(_campos[_bx_mod.CAMPO_VALOR]),
                                    snapshot_id=_snap_id,
                                    autor=usuario_atual())["id"]
                            except Exception as _e_f2:  # noqa: BLE001
                                st.caption(f"⚠ journal não registrou "
                                           f"({type(_e_f2).__name__}) — o envio segue")
                    _r = _bx_mod.enviar(_did, _campos, _linhas, aplicar=_enviar,
                                        autor=usuario_atual())
                except Exception as _e:  # noqa: BLE001 — erro de rede/CRM não derruba a tela
                    if _jr_id:
                        # o card recusou DEPOIS da intenção registrada — a
                        # conclusão 'falhou' fecha o par; se ela também se
                        # perder, a entrada fica 'pendente' e aparece nas
                        # pendências (falha ruidosa, por desenho).
                        try:
                            _hub_mod.journal_concluir(
                                _jr_id, "falhou",
                                erro=f"{type(_e).__name__}: {_e}"[:300])
                        except Exception:  # noqa: BLE001
                            pass
                    st.error(f"{type(_e).__name__}: {_e}")
                else:
                    if _jr_id:
                        try:
                            _hub_mod.journal_concluir(
                                _jr_id,
                                "aplicado" if _r.get("aplicado") else "falhou",
                                erro=(None if _r.get("aplicado")
                                      else "envio não aplicou nada"))
                        except Exception:  # noqa: BLE001 — best-effort; 'pendente' aparece nas pendências
                            st.caption("⚠ valor enviado; a conclusão do journal "
                                       "não gravou — a entrada fica 'pendente'.")
                    st.caption(f"Card #{_did} · {_card.get('TITLE')} · "
                               f"etapa {_bx_mod.nome_da_etapa(_card.get('CATEGORY_ID'), _card.get('STAGE_ID'))}")
                    # LEDGER: o par (proposta da máquina, envio do advogado).
                    # A proposta ainda está na URL; a confirmação está nos
                    # widgets. Este é o ÚNICO ponto do fluxo em que os dois
                    # existem juntos — depois daqui a query string some e o
                    # par se perde. Não-fatal por construção: o valor já foi
                    # para o card, e perder o registro é melhor que derrubar
                    # a tela do advogado.
                    if _enviar and _r.get("aplicado") and _hub_mod is not None \
                            and _hub_mod.habilitado():
                        try:
                            _cid_led = ((_qp_get("caso") or "").strip()
                                        or ((_hub_mod.caso_do_card(_did) or {}).get("id")))
                            if _cid_led:
                                _prop = {p: _qp_get(p)
                                         for _k, p in _hub_mod.CAMPOS_LEDGER
                                         if _qp_get(p) is not None}
                                _conf = {p: st.session_state.get(_k)
                                         for _k, p in _hub_mod.CAMPOS_LEDGER
                                         if st.session_state.get(_k) not in (None, "")}
                                # a natureza vem do SELETOR (o advogado pode
                                # tê-la corrigido), igual ao que vai ao card
                                _prop["natureza"] = _qp_get("natureza")
                                _conf["natureza"] = natureza
                                # ⚠ faixa de páginas no processo de ORIGEM não
                                # é conhecida aqui: o hub guarda o PDF já
                                # recortado. O rótulo de slicing fica parcial
                                # até o master subir junto — limitação anotada.
                                _faixas = [{"peca": _p, "document_id": None}
                                           for _p in sorted(_pecas)]
                                # `revisor`: quem está logado nesta sessão. Com
                                # senha ÚNICA compartilhada não havia de onde
                                # tirar autoria e o campo ia None de propósito;
                                # o login individual (`APP_USERS`) é o que
                                # passou a existir para preenchê-lo. Segue None
                                # quando a entrada foi pela senha do time — o
                                # ledger prefere não ter revisor a ter um
                                # revisor inventado.
                                # valores que o prefill RECUSOU (não existiam
                                # na conta): viajam em `rej` e ficam na
                                # observação — sem isso a rejeição sumiria do
                                # ledger e o campo pareceria mera omissão.
                                _hub_mod.registrar_adjudicacao(
                                    _cid_led, _prop, _conf, _faixas,
                                    revisor=usuario_atual(),
                                    observacao=_rej.observacao(
                                        _rej.decodificar(_qp.get("rej"))))
                        except Exception as _e_led:  # noqa: BLE001 — contabilidade nunca derruba
                            st.caption(f"⚠ ledger de adjudicação não gravou "
                                       f"({type(_e_led).__name__}) — o envio ao card está feito")
                    if _r.get("nada_novo"):
                        st.info(f"ℹ️ {_r['detalhe']}")
                    elif _r.get("aplicado"):
                        _titulo = (f"✅ **Card #{_did} COMPLETADO:**"
                                   if _r.get("completou")
                                   else f"✅ **Gravado no card #{_did}:**")
                        st.success(_titulo + "\n\n"
                                   + "\n".join(f"- {d}" for d in _r["descricao"]))
                    else:
                        if _r.get("ja_rodou_antes"):
                            st.caption("↻ este card já recebeu uma pré-análise; enviar de "
                                       "novo COMPLETA os campos ainda vazios e atualiza o "
                                       "comentário de auditoria.")
                        st.info("**Ensaio** — nada foi gravado. Seria escrito:\n\n"
                                + ("\n".join(f"- {d}" for d in _r["descricao"])
                                   or "- (nada)"))
                    if _pecas:
                        st.caption("📎 peças anexadas: "
                                   + ", ".join(f"{k} ({len(v)})" for k, v in _pecas.items())
                                   + f" — {_fonte_pecas}")
                    else:
                        st.warning(
                            "📎 **Nenhuma peça será anexada.** Os PDFs vivem no caso do "
                            "hub, e nenhum foi encontrado para este card — o valor vai "
                            "sozinho, sem os documentos que o sustentam. Confira se a "
                            "pré-análise chegou a abrir o caso.")
                    for _pl in _pulados:
                        st.caption(f"↳ {_pl}")

            # ── Fase 2: sobrescrever o valor do card (caminho auditado) ────
            # O envio normal NUNCA toca campo preenchido (`montar`). Quando o
            # número do card está errado e precisa ser corrigido, o caminho é
            # este: motivo obrigatório, journal-PRIMEIRO, e hub fora do ar =
            # bloqueado. Sem comentário na timeline — a trilha é o journal.
            st.divider()
            st.markdown("**✏️ Sobrescrever o valor do card** — para quando "
                        "*Cálculo Atualizado (Valor)* JÁ está preenchido e "
                        "precisa ser corrigido. Exige motivo e registra no "
                        "journal do hub ANTES de escrever.")
            if _hub_mod is None or not _hub_mod.habilitado():
                st.caption("Indisponível sem HUB_URL: sobrescrita sem trilha de "
                           "auditoria não existe — é o desenho, não uma falha.")
            else:
                if st.button("🔎 Carregar valor atual do card", key="bx_sob_ver"):
                    if not (_deal or "").strip().isdigit():
                        st.error("Informe o número do card.")
                    else:
                        try:
                            _d_sob = _bx_mod.carregar_deal(int(_deal.strip()))
                            st.session_state["_sob_atual"] = {
                                "deal": int(_deal.strip()),
                                "titulo": _d_sob.get("TITLE") or "",
                                "valor": _d_sob.get(_bx_mod.CAMPO_VALOR) or "",
                            }
                        except Exception as _e:  # noqa: BLE001
                            st.error(f"{type(_e).__name__}: {_e}")
                _sob = st.session_state.get("_sob_atual")
                if _sob and str(_sob.get("deal")) == (_deal or "").strip():
                    st.caption(f"Card #{_sob['deal']} · {_sob['titulo']}")
                    st.markdown(f"No card agora: **{_sob['valor'] or '(vazio)'}**")
                    _novo_txt = st.text_input(
                        "Novo valor (R$)", value=str(_liq), key="bx_sob_valor",
                        help="Pré-preenchido com o líquido calculado NESTA tela "
                             "(grava com snapshot atrás). Digitar outro número "
                             "grava como 'valor a mão' — o journal registra a "
                             "ausência de cálculo (snapshot_id vazio).")
                    st.text_input(
                        "Motivo da sobrescrita (obrigatório)", key="bx_sob_motivo",
                        placeholder="ex.: conta retificada pelo juízo em 28/08")
                    if st.button("Sobrescrever valor no card", key="bx_sob_go",
                                 type="primary"):
                        _novo = parse_dec(_novo_txt)
                        _motivo_sob = (st.session_state.get("bx_sob_motivo") or "").strip()
                        if not _motivo_sob:
                            st.error("Sem motivo não há sobrescrita — é o preço "
                                     "do caminho que contorna o 'só campo vazio'.")
                        elif _novo is None:
                            st.error("Novo valor ilegível.")
                        else:
                            _e_o_calculado = _novo == Decimal(str(_liq))
                            _txt_card = (_bx_mod.brl_atualizado(
                                _novo, _alvo_efetivo or data_alvo or date.today())
                                if _e_o_calculado else _bx_mod.brl(_novo))
                            try:
                                _cid_sob = ((_qp_get("caso") or "").strip()
                                            or ((_hub_mod.caso_do_card(_sob["deal"])
                                                 or {}).get("id")))
                                if not _cid_sob:
                                    raise RuntimeError(
                                        "este card não tem caso no hub — sem caso "
                                        "não há journal, e sem journal não há "
                                        "sobrescrita (abra o caso pela pré-análise)")
                                _snap_sob = None
                                if _e_o_calculado:
                                    _snap_sob = _hub_mod.gravar_snapshot(
                                        _cid_sob,
                                        _payload_snapshot(_sob["deal"], _txt_card),
                                        memorial_pdf=_pdf)["id"]
                                # valor_antes LIDO AGORA, não o mostrado acima:
                                # a evidência do journal é o card no instante
                                # da escrita, não a tela de minutos atrás.
                                _antes_sob = (_bx_mod.carregar_deal(_sob["deal"])
                                              .get(_bx_mod.CAMPO_VALOR) or "")
                                _jr_sob = _hub_mod.journal_registrar(
                                    _cid_sob, deal_id=str(_sob["deal"]),
                                    tipo="sobrescrita",
                                    valor_antes=str(_antes_sob),
                                    valor_depois=_txt_card,
                                    motivo=_motivo_sob,
                                    snapshot_id=_snap_sob,
                                    autor=usuario_atual())
                            except Exception as _e:  # noqa: BLE001 — journal-primeiro: sem trilha, não escreve
                                st.error(f"Sobrescrita BLOQUEADA (nada foi escrito "
                                         f"no card): {type(_e).__name__}: {_e}")
                            else:
                                try:
                                    _bx_mod.sobrescrever_valor(_sob["deal"], _txt_card)
                                except Exception as _e:  # noqa: BLE001
                                    try:
                                        _hub_mod.journal_concluir(
                                            _jr_sob["id"], "falhou",
                                            erro=f"{type(_e).__name__}: {_e}"[:300])
                                    except Exception:  # noqa: BLE001
                                        pass
                                    st.error(f"O CRM recusou a escrita: {_e} — a "
                                             "tentativa ficou registrada como "
                                             "'falhou' no journal.")
                                else:
                                    try:
                                        _hub_mod.journal_concluir(_jr_sob["id"],
                                                                  "aplicado")
                                    except Exception:  # noqa: BLE001
                                        st.caption("⚠ valor gravado; a conclusão do "
                                                   "journal não gravou — a entrada "
                                                   "fica 'pendente' e aparece nas "
                                                   "pendências.")
                                    st.session_state.pop("_sob_atual", None)
                                    st.session_state.pop("_f2_hist", None)
                                    st.success(f"Valor sobrescrito no card "
                                               f"#{_sob['deal']}: {_txt_card}")

    def render_cenario(cen: dict, titulo: str):
        if not cen or not cen.get("disponivel"):
            return
        st.markdown(f"### {titulo}")

        # ── Cascata: total atualizado → subtrações → valor final atualizado ──
        linhas = []
        superpref_val = cen.get("valor_superpreferencia")
        superpref_data = cen.get("data_pagamento_superpreferencia")
        if superpref_val is not None:
            linhas.append((
                f"Valor corrigido até a superpreferência ({fmt_data(superpref_data)})",
                cen.get("valor_corrigido_pre_superpreferencia"),
                "top",
            ))
            linhas.append((
                f"(−) Superpreferência paga em {fmt_data(superpref_data)}",
                superpref_val,
                "sub",
            ))
        linhas.append(("Valor total atualizado", cen.get("valor_total_atualizado"), "top"))
        pss = cen.get("valor_pss")
        linhas.append((
            "(−) PSS / contribuição previdenciária",
            "a apurar" if pss is None else pss,
            "sub",
        ))
        ir = cen.get("valor_ir")
        linhas.append((
            "(−) IR-RRA",
            "a apurar" if ir is None else ir,
            "sub",
        ))
        hcon_pct = cen.get("honorarios_contratuais_pct")
        hcon = cen.get("valor_honorarios_contratuais")
        if hcon is not None:
            rot = f"(−) Honorários contratuais ({hcon_pct}%)" if hcon_pct else "(−) Honorários contratuais"
            linhas.append((rot, hcon, "sub"))
        hsuc_pct = cen.get("honorarios_sucumbenciais_pct")
        hsuc = cen.get("valor_honorarios_sucumbenciais")
        if hsuc is not None:
            rot = f"(−) Honorários sucumbenciais ({hsuc_pct}%)" if hsuc_pct else "(−) Honorários sucumbenciais"
            linhas.append((rot, hsuc, "sub"))
        linhas.append(("Valor final atualizado", cen.get("valor_liquido_atualizado"), "final"))

        html = ["<table class='wf'>"]
        for rot, val, cls in linhas:
            v = val if val == "a apurar" else fmt_brl(val)
            if cls == "final":
                html.append(f"<tr class='final'><td class='lbl2'>{rot}</td><td class='v'>{v}</td></tr>")
            else:
                html.append(f"<tr class='{cls}'><td>{rot}</td><td class='v'>{v}</td></tr>")
        html.append("</table>")
        st.markdown("".join(html), unsafe_allow_html=True)

        # ── Como foi atualizado: breakdown + tabela de correção por período ──
        at = cen.get("atualizacao") or {}
        comps = at.get("componentes") or []
        if at.get("data_origem"):
            st.markdown(
                f"<div style='color:#9fb0b3;font-size:.85rem;margin-top:.6rem'>"
                f"Como foi atualizado · de {fmt_data(at.get('data_origem'))} até "
                f"{fmt_data(at.get('data_alvo'))} · fator total "
                f"{fmt_pct_fator(at.get('fator'))}</div>",
                unsafe_allow_html=True,
            )
        # buckets que somam o total atualizado — só exibidos quando REALMENTE
        # somam o total (conta detalhada em principal/juros/SELIC). Quando a conta
        # tem total ≠ principal+juros+SELIC, o restante é escalado à parte e os
        # buckets somariam menos que o total, ficando enganosos: aí some a grade e
        # resta a tabela de correção por período.
        brk = [
            ("Principal atualizado", cen.get("principal_corrigido_atualizado")),
            ("Juros atualizados", cen.get("juros_moratorios_atualizado")),
            ("SELIC / correção acumulada", cen.get("selic_acumulada_atualizada")),
        ]
        _soma_brk = sum((Decimal(str(v)) for _, v in brk if v is not None), Decimal("0"))
        _tot_at = cen.get("valor_total_atualizado")
        _brk_reconcilia = _tot_at is not None and abs(_soma_brk - Decimal(str(_tot_at))) <= Decimal("1")
        cells = "".join(
            f"<div class='cell'><div class='k'>{k}</div><div class='n'>{fmt_brl(v)}</div></div>"
            for k, v in brk if v is not None and str(v) not in ("0", "0.00")
        ) if _brk_reconcilia else ""
        if cells:
            st.markdown(f"<div class='brk'>{cells}</div>", unsafe_allow_html=True)
        if comps:
            # Decomposição estilo gabarito: fases 21-A/EC 136 expõem os juros
            # NOVOS somados na linha de juros (poupança / 2% a.a.) — coluna só
            # aparece quando alguma fase tem o valor.
            def _fmt_juros_fase(c: dict) -> str:
                jn = Decimal(str(c.get("juros_novos") or "0"))
                if jn <= 0:
                    return "—"
                tx = Decimal(str(c.get("taxa_juros_novos") or "0")) * 100
                txs = f"{tx:.4f}".rstrip("0").rstrip(".").replace(".", ",")
                return f"+ {fmt_brl(jn)} ({txs}%)"

            tem_juros_fase = any(
                Decimal(str(c.get("juros_novos") or "0")) > 0 for c in comps
            )
            if tem_juros_fase:
                rows = "".join(
                    f"<tr><td>{fmt_data(c.get('inicio'))} → {fmt_data(c.get('fim'))}</td>"
                    f"<td>{regime_curto(c.get('regime',''))}</td>"
                    f"<td class='n'>{fmt_pct_fator(c.get('fator'))}</td>"
                    f"<td class='n'>{_fmt_juros_fase(c)}</td></tr>"
                    for c in comps
                )
                st.markdown(
                    "<table class='comp'><tr><th>Período</th><th>Índice / regime</th>"
                    "<th style='text-align:right'>Correção</th>"
                    f"<th style='text-align:right'>Juros da fase</th></tr>{rows}</table>",
                    unsafe_allow_html=True,
                )
                st.caption(
                    "“Juros da fase” = poupança (art. 1º-F) ou 2% a.a. (EC 136) somados "
                    "na linha de juros — % é a soma das taxas mensais, aplicadas mês a "
                    "mês sobre o principal corrigido."
                )
            else:
                rows = "".join(
                    f"<tr><td>{fmt_data(c.get('inicio'))} → {fmt_data(c.get('fim'))}</td>"
                    f"<td>{regime_curto(c.get('regime',''))}</td>"
                    f"<td class='n'>{fmt_pct_fator(c.get('fator'))}</td></tr>"
                    for c in comps
                )
                st.markdown(
                    "<table class='comp'><tr><th>Período</th><th>Índice / regime</th>"
                    f"<th style='text-align:right'>Correção</th></tr>{rows}</table>",
                    unsafe_allow_html=True,
                )
        # Memória de cálculo do abatimento da superpreferência — mesmo estilo
        # do expander de PSS/IR abaixo: quanto cada componente tinha antes e
        # depois do pagamento (mesmos números que entram no memorial PDF).
        sp_d = cen.get("superpreferencia_detalhe")
        if sp_d:
            with st.expander("💰 Superpreferência — memória de cálculo", expanded=True):
                st.markdown(
                    f"**Abatido em {fmt_data(sp_d['data_pagamento'])}** — "
                    f"pagamento de {fmt_brl(sp_d['valor_abatido'])}, retirado "
                    "proporcionalmente do saldo corrigido até essa data."
                )
                _l = [
                    f"Principal: {fmt_brl(sp_d['principal_pre'])} − "
                    f"{fmt_brl(sp_d['principal_abatido'])} = "
                    f"**{fmt_brl(sp_d['principal_pos'])}**"
                ]
                if Decimal(sp_d["juros_pre"]) > 0 or Decimal(sp_d["juros_abatido"]) > 0:
                    _l.append(
                        f"Juros de mora: {fmt_brl(sp_d['juros_pre'])} − "
                        f"{fmt_brl(sp_d['juros_abatido'])} = "
                        f"**{fmt_brl(sp_d['juros_pos'])}**"
                    )
                if Decimal(sp_d["selic_pre"]) > 0 or Decimal(sp_d["selic_abatido"]) > 0:
                    _l.append(
                        f"SELIC / correção acumulada: {fmt_brl(sp_d['selic_pre'])} − "
                        f"{fmt_brl(sp_d['selic_abatido'])} = "
                        f"**{fmt_brl(sp_d['selic_pos'])}**"
                    )
                st.markdown("\n".join(f"- {x}" for x in _l))

        # Memória de cálculo dos descontos ESTIMADOS (estilo gabarito) — só
        # quando o motor expôs; valor declarado pelo advogado não tem memória.
        pss_d, ir_d = cen.get("pss_detalhe"), cen.get("ir_detalhe")
        if pss_d or ir_d:
            with st.expander("🧾 PSS e IR — memória de cálculo (estimados)"):
                if pss_d:
                    st.markdown("**PSS / contribuição previdenciária**")
                    _l = [
                        f"Principal atualizado (sem juros de mora): "
                        f"{fmt_brl(pss_d['principal_atualizado'])}"
                    ]
                    if Decimal(str(pss_d.get("selic_atualizada") or "0")) > 0:
                        _l.append(
                            f"(+) SELIC acumulada da conta: {fmt_brl(pss_d['selic_atualizada'])}"
                        )
                    if pss_d.get("contratuais_pct") not in (None, "", "0"):
                        _l.append(
                            "(×) parte do credor após o destaque contratual: "
                            f"100% − {str(pss_d['contratuais_pct']).replace('.', ',')}%"
                        )
                    _l.append(f"Base do PSS: {fmt_brl(pss_d['base'])}")
                    _aliq = str(pss_d["aliquota_pct"]).replace(".", ",")
                    _l.append(
                        f"**PSS = {fmt_brl(pss_d['base'])} × {_aliq}% = "
                        f"{fmt_brl(pss_d['valor'])}**"
                    )
                    st.markdown("\n".join(f"- {x}" for x in _l))
                if ir_d:
                    st.markdown("**IR-RRA (art. 12-A Lei 7.713/88)**")
                    _aliq_ir = str(ir_d["aliquota_efetiva_pct"]).replace(".", ",")
                    _l = [
                        f"Base (principal atualizado, sem juros de mora): "
                        f"{fmt_brl(ir_d['base_total'])}"
                    ]
                    if Decimal(str(ir_d.get("pss_deduzido") or "0")) > 0:
                        _l.append(
                            f"(−) PSS deduzido (art. 12-A §4º): {fmt_brl(ir_d['pss_deduzido'])}"
                        )
                    if Decimal(str(ir_d.get("honorarios_deduzido") or "0")) > 0:
                        _l.append(
                            "(−) Honorários deduzidos (IN RFB 1500/2014): "
                            f"{fmt_brl(ir_d['honorarios_deduzido'])}"
                        )
                    _l.append(f"Base após deduções: {fmt_brl(ir_d['base_apos_deducoes'])}")
                    _l.append(
                        f"Base mensal: {fmt_brl(ir_d['base_apos_deducoes'])} ÷ "
                        f"{ir_d['meses_competencia']} meses = {fmt_brl(ir_d['base_mensal'])}"
                    )
                    _l.append(
                        f"Faixa da tabela mensal: {_aliq_ir}% — parcela a deduzir "
                        f"{fmt_brl(ir_d['parcela_dedutivel'])}/mês"
                    )
                    _l.append(
                        f"**IR = ({fmt_brl(ir_d['base_mensal'])} × {_aliq_ir}% − "
                        f"{fmt_brl(ir_d['parcela_dedutivel'])}) × {ir_d['meses_competencia']} "
                        f"meses = {fmt_brl(ir_d['valor_ir'])}**"
                    )
                    st.markdown("\n".join(f"- {x}" for x in _l))
        if at.get("ressalva_adi"):
            st.caption(f"⚖️ {at['ressalva_adi']}")
        for obs in cen.get("observacoes") or []:
            # Observações de honorários "não descontado" são ruído no modo manual:
            # aqui não há conta/ofício — o advogado é quem informa os honorários.
            # Mesmo filtro que o memorial em PDF já aplica (mantém UI ≡ PDF).
            if "onorár" in obs:
                continue
            st.caption(f"• {obs}")

    render_cenario(res.get("cenario_homologado"), "Cenário homologado")
    sent = res.get("cenario_sentencial")
    if sent and sent.get("disponivel"):
        render_cenario(sent, "Cenário sentencial")

    with st.expander("Ver JSON completo do cálculo"):
        st.json(res)
