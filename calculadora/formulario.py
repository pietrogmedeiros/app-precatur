"""Formulário da calculadora → `EntradaCalculadora`, sem Streamlit.

Esta é a camada que garante a **paridade com o app original**: o `Calculadora.py`
do Streamlit lê widgets e monta a entrada; aqui lemos um dicionário com os MESMOS
campos (as chaves são as dos widgets: `vt`, `vp`, `pss_modo`…) e montamos a MESMA
entrada, com as MESMAS validações e as MESMAS mensagens de erro.

Por que não importar do `Calculadora.py`: lá a leitura e a regra estão no meio do
desenho da tela (`st.text_input` devolve o texto e a regra roda na sequência).
Separar permite rodar sem Streamlit — e deixa a regra testável contra a tela
antiga, que continua no repositório como referência.

Regra de ouro ao mexer aqui: **nenhum número é calculado neste arquivo**. Tudo que
é conta mora no motor (`precaturia.pipeline`); isto aqui só lê texto, valida e
repassa.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal

import numeros
from precaturia.pipeline.calculadora import EntradaCalculadora

# ── rótulos (os mesmos textos da tela Streamlit, para o memorial não mudar) ──
PSS_MODOS = {"nao": "Não descontar", "valor": "Valor no ofício (R$)",
             "aliquota": "Por alíquota (%)"}
IR_MODOS = {"nao": "Não descontar", "valor": "Valor no ofício (R$)",
            "estimar": "Estimar por natureza"}

REGIME_OPCOES = {
    "simples-ipca-e": "Simples — IPCA-E",
    "simples-inpc": "Simples — INPC",
    "composto-ec113": "Composto pós-EC 113 (IPCA-E → SELIC)",
}
NATUREZAS_HISTORICAS = ("comum", "servidor", "previdenciario", "tributario",
                        "desapropriacao", "assistencial")
NATUREZAS_TRIBUTARIAS = ("remuneratorio", "previdenciario", "indenizatorio", "misto")
ENTES = [
    "União", "INSS", "Estado do Espírito Santo", "Estado do Rio de Janeiro",
    "Estado de Minas Gerais", "Estado da Bahia", "Estado de Goiás",
    "Estado de Mato Grosso", "Estado de São Paulo", "Estado de Alagoas",
    "IPAJM — Instituto de Previdência dos Servidores do ES",
    "Rio Previdência (RJ)", "Alagoas Previdência",
]


class ErroDeFormulario(Exception):
    """Erros de preenchimento — viram 422 com a lista para a tela."""

    def __init__(self, erros: list[str]):
        super().__init__("; ".join(erros))
        self.erros = erros


def _texto(bruto: dict, chave: str) -> str:
    v = bruto.get(chave)
    return "" if v is None else str(v)


def _data(bruto: dict, chave: str) -> date | None:
    v = (bruto.get(chave) or "").strip() if isinstance(bruto.get(chave), str) else bruto.get(chave)
    if not v:
        return None
    if isinstance(v, date):
        return v
    try:
        return date.fromisoformat(str(v)[:10])
    except ValueError:
        raise ErroDeFormulario([f"Data inválida em '{chave}': {v!r} (use AAAA-MM-DD)."])


def _dec(texto: str, erros: list[str], rotulo: str) -> Decimal | None:
    """Dinheiro digitado. Espelha `parse_dec` da tela: inválido vira aviso e
    None — o cálculo segue sem o campo, como no Streamlit."""
    try:
        return numeros.parse_decimal_br(texto)
    except ValueError:
        erros.append(f"{rotulo}: valor inválido '{(texto or '').strip()}'. "
                     "Use vírgula para centavos (ex.: 1.234,56).")
        return None


def _ler_declarado(texto: str, rotulo: str, outros: str) -> tuple[Decimal | None, str | None]:
    """Cópia fiel de `_ler_declarado` do `Calculadora.py` (PSS/IR declarados):
    vazio ou inválido BLOQUEIA — não vira estimativa silenciosa."""
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
    """Cópia fiel de `_ler_percentual`: ponto é decimal, intervalo 0–100,
    vazio não é erro."""
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


def build_regime(preset: str | None) -> list[dict] | None:
    """Presets de regime (só no modo originário) — idêntico ao da tela."""
    rotulo = REGIME_OPCOES.get(preset or "", preset or "")
    if rotulo.startswith("Simples"):
        indice = "IPCA-E" if "IPCA-E" in rotulo else "INPC"
        return [{"indice": indice, "inicio_tipo": "data_base", "inicio_data": None,
                 "fim_tipo": "data_calculo", "fim_data": None}]
    if rotulo.startswith("Composto"):
        return [
            {"indice": "IPCA-E", "inicio_tipo": "data_base", "inicio_data": None,
             "fim_tipo": "data", "fim_data": "2021-12-09"},
            {"indice": "SELIC", "inicio_tipo": "data", "inicio_data": "2021-12-09",
             "fim_tipo": "data_calculo", "fim_data": None},
        ]
    return None


@dataclass
class Formulario:
    """O formulário já lido — entrada do motor + o que o memorial precisa."""

    entrada: EntradaCalculadora
    eh_conta: bool
    avisos: list[str] = field(default_factory=list)
    # rótulos para o memorial (o PDF mostra o MODO escolhido, não só o número)
    pss_modo_label: str = ""
    ir_modo_label: str = ""
    preset_label: str | None = None
    natureza_hist: str | None = None
    ente_devedor: str | None = None
    ano_orcamentario: str | None = None
    referencia: str = ""
    observacao: str = ""
    honorarios_sucumbenciais_pct: Decimal | None = None
    meses: int = 0
    aliquota_pss: Decimal | None = None
    # valores crus, para as iniciais da trilha do memorial
    valor_total: Decimal | None = None
    valor_principal: Decimal | None = None
    valor_juros: Decimal | None = None
    valor_selic: Decimal | None = None
    valor_originario: Decimal | None = None
    data_alvo: date | None = None


def ler(bruto: dict) -> Formulario:
    """Dicionário do formulário → `Formulario`. Levanta `ErroDeFormulario`.

    A ordem e o conteúdo das validações seguem o `Calculadora.py` (bloco
    `if submitted`), para a tela nova recusar exatamente o que a antiga recusa.
    """
    erros: list[str] = []
    avisos: list[str] = []

    eh_conta = (bruto.get("modo") or "oficio") != "originario"

    # ── 1 · Valores do crédito ────────────────────────────────────────────
    if eh_conta:
        valor_total = _dec(_texto(bruto, "vt"), avisos, "Valor Total Requisitado")
        valor_principal = _dec(_texto(bruto, "vp"), avisos, "Principal Corrigido")
        valor_juros = _dec(_texto(bruto, "vj"), avisos, "Juros")
        valor_selic = _dec(_texto(bruto, "vs"), avisos, "SELIC")
        valor_originario = None
    else:
        valor_originario = _dec(_texto(bruto, "vo"), avisos, "Valor originário")
        valor_total = valor_principal = valor_juros = valor_selic = None

    data_base = _data(bruto, "data_base") if not eh_conta else None
    data_calculo = _data(bruto, "data_calculo")

    # ── 2 · Regime (só no modo originário) ────────────────────────────────
    natureza_hist = None
    assist_idx = None
    preset = None
    if not eh_conta:
        nh = (bruto.get("nat_hist") or "").strip() or None
        natureza_hist = nh if nh in NATUREZAS_HISTORICAS else None
        if natureza_hist == "assistencial":
            assist_idx = bruto.get("assist_idx") or "IPCA-E"
            if assist_idx not in ("IPCA-E", "INPC"):
                assist_idx = "IPCA-E"
        if natureza_hist is None:
            preset = (bruto.get("regime") or "simples-ipca-e").lower()
            if preset not in REGIME_OPCOES:
                preset = "simples-ipca-e"
    else:
        preset = None

    # ── 3 · Natureza e tributação ─────────────────────────────────────────
    nat = (bruto.get("natureza") or "").strip() or None
    natureza = nat if nat in NATUREZAS_TRIBUTARIAS else None

    pss_modo = (bruto.get("pss_modo") or "nao").lower()
    if pss_modo not in PSS_MODOS:
        pss_modo = "nao"
    valor_pss: Decimal | None = None
    estimar_pss = False
    aliq_pss: Decimal | None = None
    if pss_modo == "nao":
        valor_pss = Decimal("0")  # explícito: congela em 0
    elif pss_modo == "valor":
        valor_pss, erro = _ler_declarado(_texto(bruto, "pss"), "PSS",
                                         "Não descontar ou Por alíquota (%)")
        if erro:
            erros.append(erro)
    else:
        estimar_pss = True
        # Sem default aqui: na tela o campo NASCE com 14, mas quem o apaga
        # recebe um erro — e não um 14 silencioso. O default é da tela.
        aliq_pss, erro = _ler_percentual(_texto(bruto, "apss"), "Alíquota do PSS")
        if erro:
            erros.append(erro)
        elif aliq_pss is None:
            erros.append("Alíquota do PSS: informe a alíquota (maior que 0) ou "
                         "escolha outro modo (Não descontar ou Valor no ofício (R$))")
        elif aliq_pss == 0:
            erros.append("Alíquota do PSS: Informe uma alíquota maior que 0 "
                         "ou escolha Não descontar.")

    ir_modo = (bruto.get("ir_modo") or "nao").lower()
    if ir_modo not in IR_MODOS:
        ir_modo = "nao"
    valor_ir: Decimal | None = None
    estimar_ir = False
    if ir_modo == "nao":
        valor_ir = Decimal("0")  # explícito: evita IR com meses=1 inflado
    elif ir_modo == "valor":
        valor_ir, erro = _ler_declarado(_texto(bruto, "ir"), "IR",
                                        "Não descontar ou Estimar por natureza")
        if erro:
            erros.append(erro)
    else:
        estimar_ir = True

    try:
        meses = int(bruto.get("meses") or 0)
    except (TypeError, ValueError):
        meses = 0
        avisos.append("Número de meses (RRA) ilegível — tratado como não informado.")
    if meses < 0:
        meses = 0

    # ── 4 · Honorários ────────────────────────────────────────────────────
    hon_con, erro = _ler_percentual(_texto(bruto, "hc"), "Honorários Contratuais (%)")
    if erro:
        erros.append(erro)
    hon_suc, erro = _ler_percentual(_texto(bruto, "hs"), "Honorários de Sucumbência (%)")
    if erro:
        erros.append(erro)

    # ── 5 · Precatório e período de graça ─────────────────────────────────
    modalidade = (bruto.get("modalidade") or "").strip() or None
    if modalidade not in ("precatorio", "rpv"):
        modalidade = None
    data_apres = _data(bruto, "data_apres")
    superpref_valor = _dec(_texto(bruto, "sp_val"), avisos, "Superpreferência paga")
    superpref_data = _data(bruto, "sp_data")

    ente_sel = (bruto.get("ente") or "").strip()
    ente_custom = (bruto.get("ente_outro") or "").strip()
    if ente_sel == "outro":
        ente_devedor = ente_custom or None
    else:
        ente_devedor = ente_sel or None
    ano_orcamentario = (bruto.get("ano_orc") or "").strip() or None

    data_expedicao = _data(bruto, "data_expedicao")

    esfera_sel = (bruto.get("esfera") or "auto").lower()
    if esfera_sel == "federal":
        esfera = "federal"
    elif esfera_sel in ("estadual", "municipal"):
        esfera = "estadual"
    else:  # Auto: deduz pelo ente, igual à tela
        _ente_l = (ente_devedor or "").lower()
        esfera = "federal" if any(k in _ente_l for k in ("união", "uniao", "inss", "federal")) else "estadual"

    # ── 6 · Atualização ao presente ───────────────────────────────────────
    data_alvo = _data(bruto, "data_alvo")

    # ── validações finais (mesma ordem da tela) ───────────────────────────
    if data_calculo is None:
        erros.append(f"{'Data-base' if eh_conta else 'Data do cálculo'} é obrigatória.")
    if not eh_conta and data_base is None:
        erros.append("No modo originário, a data-base é obrigatória.")
    if data_base and data_calculo and data_calculo < data_base:
        erros.append("Data do cálculo deve ser ≥ data-base.")
    if not eh_conta and valor_originario is None:
        erros.append("No modo originário, o valor originário é obrigatório.")
    if erros:
        raise ErroDeFormulario(erros)

    entrada = EntradaCalculadora(
        valor_total=valor_total,
        valor_bruto_reclamante=None,
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
        meses_competencia=meses if meses >= 1 else None,
        # Sucumbencial NÃO entra no motor: não sai do líquido do credor.
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

    return Formulario(
        entrada=entrada,
        eh_conta=eh_conta,
        avisos=avisos,
        pss_modo_label=PSS_MODOS[pss_modo],
        ir_modo_label=IR_MODOS[ir_modo],
        preset_label=REGIME_OPCOES.get(preset or "") if preset else None,
        natureza_hist=natureza_hist,
        ente_devedor=ente_devedor,
        ano_orcamentario=ano_orcamentario,
        referencia=(bruto.get("ref") or "").strip(),
        observacao=(bruto.get("obs") or "").strip(),
        honorarios_sucumbenciais_pct=hon_suc,
        meses=meses,
        aliquota_pss=aliq_pss,
        valor_total=valor_total,
        valor_principal=valor_principal,
        valor_juros=valor_juros,
        valor_selic=valor_selic,
        valor_originario=valor_originario,
        data_alvo=data_alvo,
    )
