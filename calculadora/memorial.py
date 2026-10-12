"""Memorial de cálculo em PDF (xhtml2pdf) — bundle standalone.

Gera um documento imprimível a partir do resultado de `calcular_dict`. Tema
CLARO (branco / petróleo) apropriado para papel. Python puro (xhtml2pdf +
reportlab) — roda no Render free. Nada é armazenado; o PDF é montado em memória
e baixado direto pelo navegador do advogado.

A seção "Memorial de cálculo" mostra a evolução passo-a-passo dos três
componentes (principal sem juros, juros, SELIC/correção) período a período, no
formato "valor × índice = valor". A trilha é FIEL ao modelo ENCADEADO do motor
(cada fase multiplica principal e juros pelo fator seguinte; a SELIC já
acumulada fica CONGELADA — carregada nominalmente) e é reconstituída a partir
dos componentes — com checagem de sanidade contra o total do motor.
"""
from __future__ import annotations

import base64
from datetime import date
from decimal import ROUND_HALF_UP, Decimal
from functools import lru_cache
from io import BytesIO
from pathlib import Path

from xhtml2pdf import pisa

_Q = Decimal("0.01")

# IR sobre os honorários SUCUMBENCIAIS, na seção "Honorários do advogado".
# Faixa máxima da tabela: o sucumbencial é renda do advogado e cai no teto na
# prática (confirmado com o Matheus em 25/08/2026). Só ele leva este desconto —
# os contratuais saem no bruto, e a nota embaixo do total diz isso.
# Não é o IR-RRA do crédito, que é outro cálculo (por meses de competência) e
# vive no motor; este aqui é linha de exibição e não toca líquido nenhum.
IR_SUCUMBENCIAIS_PCT = Decimal("27.5")
_ASSETS = Path(__file__).resolve().parent / "assets"


@lru_cache(maxsize=4)
def _asset_uri(nome: str) -> str:
    """Data URI base64 de uma imagem da marca em `assets/` (cabeçalho/rodapé,
    mesmos do resumo do sistema). String vazia se não encontrar."""
    try:
        dados = (_ASSETS / nome).read_bytes()
        b64 = base64.b64encode(dados).decode("ascii")
        return f"data:image/png;base64,{b64}"
    except Exception:
        return ""


def _brl(v) -> str:
    if v is None or v == "":
        return "—"
    d = Decimal(str(v))
    neg = d < 0
    d = abs(d).quantize(_Q)
    intp, dec = f"{d:.2f}".split(".")
    intp = f"{int(intp):,}".replace(",", ".")
    return f"{'-' if neg else ''}R$ {intp},{dec}"


def _q(v: Decimal) -> Decimal:
    return v.quantize(_Q, rounding=ROUND_HALF_UP)


def _data(s) -> str:
    if not s:
        return "—"
    try:
        return date.fromisoformat(str(s)[:10]).strftime("%d/%m/%Y")
    except Exception:
        return str(s)


def _fator_str(f) -> str:
    """Fator com 6 casas (ex.: 1,048196)."""
    try:
        return f"{Decimal(str(f)):.6f}".replace(".", ",")
    except Exception:
        return str(f)


def _pct(f) -> str:
    """Fator → variação percentual (ex.: 1,0985 → 9,85%)."""
    try:
        v = (Decimal(str(f)) - Decimal("1")) * Decimal("100")
        return f"{v:.4f}".rstrip("0").rstrip(".").replace(".", ",") + "%"
    except Exception:
        return "—"


def _pct_frac(tx) -> str:
    """Fração → percentual (ex.: 0.0761 → 7,61%)."""
    try:
        v = Decimal(str(tx)) * Decimal("100")
        return f"{v:.4f}".rstrip("0").rstrip(".").replace(".", ",") + "%"
    except Exception:
        return "—"


def _pct_num(v) -> str:
    """Número percentual ('14', '27.5') → '14%' / '27,5%'."""
    try:
        d = Decimal(str(v))
        s = f"{d:.4f}".rstrip("0").rstrip(".")
        return s.replace(".", ",") + "%"
    except Exception:
        return f"{v}%"


def _regime_curto(regime: str) -> str:
    r = (regime or "").lower()
    if "graça" in r or "graca" in r:
        return "IPCA-E — período de graça"
    if "ec 136" in r:
        return "IPCA + 2% a.a. (EC 136, teto SELIC)"
    if "ec 113" in r or "selic" in r:
        return "SELIC (EC 113)"
    return regime


def _e_graca(regime: str) -> bool:
    r = (regime or "").lower()
    return "graça" in r or "graca" in r


_CSS = """
@page {
  size: A4 portrait;
  margin: 1.2cm 1.4cm 3cm 1.4cm;
  @frame footer_frame {
    -pdf-frame-content: rodape;
    -pdf-frame-border: 0;
    left: 1.4cm; width: 18.2cm;
    bottom: 0.6cm; height: 2.3cm;
  }
}
#rodape img { width: 18.2cm; }
body { font-family: Helvetica; color: #1a2529; font-size: 9pt; line-height: 1.28; }
.brand { color: #34474D; font-weight: bold; letter-spacing: 3px; font-size: 15pt; }
.gerado { color: #8a999e; font-size: 8pt; }
.ref { color: #34474D; font-size: 9.5pt; font-weight: bold; }
h1 { font-size: 10.5pt; color: #34474D; border-bottom: 1.5px solid #34474D;
     padding-bottom: 2px; margin: 10px 0 4px; }
table { width: 100%; border-collapse: collapse; }
/* grade horizontal de entrada */
.hgrid td { border: 0.5px solid #d5dcde; padding: 4px 6px; vertical-align: top; }
.hgrid .ck { color: #7a8a8f; font-size: 7.5pt; }
.hgrid .cv { color: #1a2529; font-size: 9.5pt; font-weight: bold; }
.outros { color: #34474D; font-size: 9pt; margin: 6px 0 2px; }
.outros b { color: #56666b; font-weight: normal; }
/* fases do memorial */
.fase-h { color: #34474D; font-weight: bold; font-size: 9pt; margin: 6px 0 1px; }
.fase-h .per { color: #7a8a8f; font-weight: normal; font-size: 8pt; }
.calc td { padding: 1.5px 5px; border-bottom: 0.5px solid #eef1f2; }
.calc .lbl { color: #56666b; width: 34%; }
.calc .op { text-align: right; width: 40%; }
.calc .res { text-align: right; font-weight: bold; width: 26%; }
.nota { color: #8a999e; font-size: 7.5pt; font-style: italic; margin-bottom: 1px; }
.sintese { background: #eef2f3; padding: 5px 8px; margin: 6px 0 2px; font-size: 9.5pt; }
/* cascata do resultado */
.wf td { padding: 4px 5px; border-bottom: 0.5px solid #d5dcde; }
.wf .k { color: #56666b; }
.wf .num { text-align: right; }
.wf .final td { border-top: 1.5px solid #34474D; border-bottom: none; padding-top: 8px;
                font-weight: bold; color: #34474D; }
.wf .final .lbl { font-size: 12pt; text-transform: uppercase; letter-spacing: 0.5px; }
.wf .final .num { font-size: 15pt; }
.caveat { background: #fbf3e9; padding: 6px 8px;
          margin: 8px 0; font-size: 8.5pt; color: #6a5432; }
.foot { color: #8a999e; font-size: 7.5pt; margin-top: 16px;
        border-top: 0.5px solid #d5dcde; padding-top: 5px; }
"""


def _hgrid(items: list[tuple[str, str]]) -> str:
    cels = "".join(
        f'<td><div class="ck">{l}</div><div class="cv">{v}</div></td>'
        for l, v in items if v not in (None, "", "—")
    )
    return f'<table class="hgrid"><tr>{cels}</tr></table>' if cels else ""


def _trilha_html(cen: dict, iniciais: dict | None) -> str:
    """Reconstitui a evolução período a período (modelo ENCADEADO) no formato
    'valor × índice = valor': cada fase multiplica o principal E os juros pelo
    fator do componente. A linha de SELIC já acumulada da conta recebe correção
    (graça / EC 136), não SELIC nova. Cai para vazio (→ fallback) se não
    reconciliar com o total do motor (ex.: os 2% da EC 136 vão para a linha de
    juros e não aparecem no fator do principal)."""
    if not iniciais or iniciais.get("principal") is None:
        return ""
    at = cen.get("atualizacao") or {}
    comps = at.get("componentes") or []
    if not comps:
        return ""

    P = Decimal(str(iniciais["principal"]))
    J = Decimal(str(iniciais.get("juros") or "0"))
    S = Decimal(str(iniciais.get("selic") or "0"))

    # Superpreferência: `n_componentes_pre` marca quantos componentes (fases)
    # pertencem à perna 1 (data_calculo → pagamento) na lista concatenada —
    # o `fim` de fase NÃO serve de marcador (a varredura mês a mês fecha
    # segmentos em fronteira de mês, não no dia exato do pagamento).
    superpref = cen.get("superpreferencia_detalhe")
    n_pre_sp = superpref.get("n_componentes_pre") if superpref else None
    data_pagto_sp = superpref.get("data_pagamento") if superpref else None

    def _bloco_abatimento_sp() -> str:
        linhas_sp = [(
            "Principal sem juros",
            f'{_brl(superpref["principal_pre"])} − {_brl(superpref["principal_abatido"])}',
            f'= {_brl(superpref["principal_pos"])}',
        )]
        if Decimal(superpref["juros_pre"]) > 0 or Decimal(superpref["juros_abatido"]) > 0:
            linhas_sp.append((
                "Juros de mora",
                f'{_brl(superpref["juros_pre"])} − {_brl(superpref["juros_abatido"])}',
                f'= {_brl(superpref["juros_pos"])}',
            ))
        if Decimal(superpref["selic_pre"]) > 0 or Decimal(superpref["selic_abatido"]) > 0:
            linhas_sp.append((
                "SELIC / correção acumulada",
                f'{_brl(superpref["selic_pre"])} − {_brl(superpref["selic_abatido"])}',
                f'= {_brl(superpref["selic_pos"])}',
            ))
        corpo_sp = "".join(
            f'<tr><td class="lbl">{l}</td><td class="op">{o}</td>'
            f'<td class="res">{r}</td></tr>' for l, o, r in linhas_sp
        )
        return (
            f'<div class="fase-h">Superpreferência — abatimento '
            f'<span class="per">· {_data(data_pagto_sp)} '
            f'(−{_brl(superpref["valor_abatido"])})</span></div>'
            f'<table class="calc">{corpo_sp}</table>'
        )

    # Sem bloco "Ponto de partida": os valores iniciais já constam da seção 1
    # (Dados de entrada) e reaparecem como operando esquerdo da 1ª fase — repeti-los
    # aqui era redundante. A trilha começa direto na primeira correção.
    blocos = []
    if superpref and n_pre_sp == 0:
        # Pagamento no MESMO dia da data do cálculo — perna 1 é uma janela
        # vazia (nenhuma fase própria); o abatimento abre a trilha.
        blocos.append(_bloco_abatimento_sp())
        P = Decimal(superpref["principal_pos"])
        J = Decimal(superpref["juros_pos"])
    for i, c in enumerate(comps, start=1):
        fator = Decimal(str(c.get("fator")))
        regime_raw = c.get("regime", "")
        regime = _regime_curto(regime_raw)
        per = f'{_data(c.get("inicio"))} → {_data(c.get("fim"))}'
        fator_j = Decimal(str(c.get("fator_juros") or fator))
        # Juros NOVOS da fase (poupança do art. 22 / 2% a.a. da EC 136) —
        # expostos pelo motor. A fase decompõe estilo gabarito: correção do
        # saldo de juros + parcela nova (com % e base), fechando ao centavo.
        jn = Decimal(str(c.get("juros_novos") or "0"))
        tx = Decimal(str(c.get("taxa_juros_novos") or "0"))
        rotulo_jn = (
            "Juros de mora 2% a.a. (EC 136)"
            if "ec 136" in regime_raw.lower()
            else "Juros da poupança (art. 1º-F Lei 9.494)"
        )
        linhas = [(
            "Principal sem juros",
            f"{_brl(P)} × {_fator_str(fator)}",
            f"= {_brl(_q(P * fator))}",
        )]
        P = P * fator  # precisão plena interna (evita drift; só arredonda no display)
        if J > 0 and jn > 0:
            # Correção sobre o saldo de juros + parcela NOVA da fase, com o
            # destino explícito (soma na própria linha de juros).
            jc = _q(J * fator)
            jfim = _q(J * fator_j)
            linhas.append((
                "Juros de mora (correção)",
                f"{_brl(J)} × {_fator_str(fator)}",
                f"= {_brl(jc)}",
            ))
            linhas.append((
                f"(+) {rotulo_jn}",
                f"{_pct_frac(tx)} sobre o principal corrigido, mês a mês",
                f"+ {_brl(jfim - jc)}",
            ))
            linhas.append((
                "Juros de mora ao fim da fase",
                f"{_brl(jc)} + {_brl(jfim - jc)}",
                f"= {_brl(jfim)}",
            ))
            J = J * fator_j
        elif J > 0:
            linhas.append((
                "Juros de mora",
                f"{_brl(J)} × {_fator_str(fator_j)}",
                f"= {_brl(_q(J * fator_j))}",
            ))
            J = J * fator_j
        elif jn > 0:
            # A linha de juros NASCE nesta fase (conta sem juros de mora).
            linhas.append((
                rotulo_jn,
                f"{_pct_frac(tx)} sobre o principal corrigido, mês a mês",
                f"= {_brl(jn)}",
            ))
            J = jn
        # A linha de SELIC já acumulada fica CONGELADA — carregada nominalmente
        # (não recebe correção), igual ao motor. Só principal e juros crescem.
        corpo = "".join(
            f'<tr><td class="lbl">{l}</td><td class="op">{o}</td>'
            f'<td class="res">{r}</td></tr>' for l, o, r in linhas
        )
        blocos.append(
            f'<div class="fase-h">{i}ª fase — {regime} '
            f'<span class="per">· {per}</span></div>'
            f'<table class="calc">{corpo}</table>'
        )

        # Fase do abatimento: pagamento BRUTO retirado proporcionalmente de
        # principal/juros/SELIC na data em que ocorreu (ver
        # `cenarios.construir_cenarios`). Mostra o valor de CADA componente
        # antes e depois — igual ao pedido do advogado, no mesmo formato das
        # outras fases. Resincroniza P/J com os valores autoritativos do
        # motor (em vez de só multiplicar localmente) para a perna 2 seguir
        # sem arrastar deriva de arredondamento.
        if superpref and i == n_pre_sp:
            blocos.append(_bloco_abatimento_sp())
            P = Decimal(superpref["principal_pos"])
            J = Decimal(superpref["juros_pos"])

    # Valores finais AUTORITATIVOS do motor. A trilha ilustra o CAMINHO do
    # principal fase a fase; a síntese usa os componentes do motor pra FECHAR
    # sempre — inclusive quando os 2% da EC 136 geram juros a partir de uma linha
    # de juros inicial = 0 (aí o fator_juros por fase é 1 e a reconstrução, por si
    # só, não captaria esse juros).
    def _mot(campo: str, fallback: Decimal) -> Decimal:
        v = cen.get(campo)
        return Decimal(str(v)) if v is not None else fallback

    P_fim = _mot("principal_corrigido_atualizado", P)
    J_fim = _mot("juros_moratorios_atualizado", J)
    S_fim = _mot("selic_acumulada_atualizada", S)
    soma_componentes = _q(P_fim + J_fim + S_fim)
    motor = cen.get("valor_total_atualizado")
    if motor is not None and abs(soma_componentes - Decimal(str(motor))) > Decimal("0.05"):
        # componentes não somam o total exibido (conta com "outros") → fallback
        return ""
    total = _q(Decimal(str(motor))) if motor is not None else soma_componentes
    partes = [f"{_brl(P_fim)} (principal)"]
    if J_fim > 0:
        partes.append(f"{_brl(J_fim)} (juros)")
    if S_fim > 0:
        partes.append(f"{_brl(S_fim)} (SELIC/correção)")
    sintese = (
        f'<div class="sintese"><b>Valor atualizado ao presente</b> = '
        f'{" + ".join(partes)} = <b>{_brl(total)}</b></div>'
    )
    return "".join(blocos) + sintese


def _fallback_atualizacao_html(cen: dict) -> str:
    """Versão simples da atualização (tabela de componentes + baldes finais),
    usada se a trilha detalhada não puder reconciliar com o motor — assim a
    seção 2 nunca some."""
    at = cen.get("atualizacao") or {}
    comps = at.get("componentes") or []
    if not comps:
        return ""
    rows = "".join(
        f'<tr><td class="lbl">{_data(c.get("inicio"))} → {_data(c.get("fim"))}</td>'
        f'<td class="op">{_regime_curto(c.get("regime", ""))}</td>'
        f'<td class="res">{_pct(c.get("fator"))}</td></tr>'
        for c in comps
    )
    tab = (
        '<table class="calc"><tr><td class="lbl"><b>Período</b></td>'
        '<td class="op"><b>Regime</b></td><td class="res"><b>Correção</b></td></tr>'
        f"{rows}</table>"
    )
    brk = [
        ("Principal atualizado", cen.get("principal_corrigido_atualizado")),
        ("Juros atualizados", cen.get("juros_moratorios_atualizado")),
        ("SELIC / correção acumulada", cen.get("selic_acumulada_atualizada")),
    ]
    tot = cen.get("valor_total_atualizado")
    # Só detalha os baldes quando eles somam o total (conta detalhada em
    # principal/juros/SELIC). Se o total ≠ soma dos componentes, o restante é
    # escalado à parte e os baldes enganariam — omite-os (fica a tabela de período).
    _soma_brk = sum((Decimal(str(v)) for _, v in brk if v is not None), Decimal("0"))
    _brk_ok = tot is not None and abs(_soma_brk - Decimal(str(tot))) <= Decimal("1")
    brows = "".join(
        f'<tr><td class="lbl">{k}</td><td class="op"></td><td class="res">{_brl(v)}</td></tr>'
        for k, v in brk if v is not None and str(v) not in ("0", "0.00")
    ) if _brk_ok else ""
    sint = (
        f'<div class="sintese"><b>Valor atualizado ao presente</b> = '
        f"<b>{_brl(tot)}</b></div>" if tot is not None else ""
    )
    return tab + (f'<table class="calc">{brows}</table>' if brows else "") + sint


def _descontos_html(cen: dict) -> str:
    """Memória de cálculo dos descontos ESTIMADOS (estilo gabarito): PSS com a
    base visível × alíquota; IR-RRA com o caminho completo (base → deduções →
    ÷ meses → faixa da tabela → valor). Só aparece quando o motor expôs
    `pss_detalhe`/`ir_detalhe` (estimativas); valor declarado pelo advogado não
    tem memória (o número é dele). As contas exibidas FECHAM ao centavo com a
    cascata do resultado — mesmos valores do motor, nada recalculado aqui."""
    pss_d = cen.get("pss_detalhe")
    ir_d = cen.get("ir_detalhe")
    if not pss_d and not ir_d:
        return ""

    def _tabela(linhas: list[tuple[str, str, str]]) -> str:
        corpo = "".join(
            f'<tr><td class="lbl">{l}</td><td class="op">{o}</td>'
            f'<td class="res">{r}</td></tr>' for l, o, r in linhas
        )
        return f'<table class="calc">{corpo}</table>'

    blocos = []
    if pss_d:
        linhas = [(
            "Principal atualizado (sem juros de mora)",
            "",
            _brl(pss_d.get("principal_atualizado")),
        )]
        selic = Decimal(str(pss_d.get("selic_atualizada") or "0"))
        if selic > 0:
            linhas.append(("(+) SELIC acumulada da conta", "", f"+ {_brl(selic)}"))
        contr = pss_d.get("contratuais_pct")
        if contr not in (None, "", "0"):
            linhas.append((
                "(×) parte do credor após o destaque contratual",
                f"100% − {_pct_num(contr)}",
                "",
            ))
        linhas.append(("Base do PSS", "", f"= {_brl(pss_d.get('base'))}"))
        linhas.append((
            "PSS / contribuição previdenciária",
            f"{_brl(pss_d.get('base'))} × {_pct_num(pss_d.get('aliquota_pct'))}",
            f"= <b>{_brl(pss_d.get('valor'))}</b>",
        ))
        blocos.append(
            '<div class="fase-h">PSS — contribuição previdenciária (estimado)</div>'
            + _tabela(linhas)
        )

    if ir_d:
        meses = ir_d.get("meses_competencia")
        linhas = [(
            "Base de cálculo (principal atualizado, sem juros de mora)",
            "",
            _brl(ir_d.get("base_total")),
        )]
        pss_ded = Decimal(str(ir_d.get("pss_deduzido") or "0"))
        if pss_ded > 0:
            linhas.append((
                "(−) PSS deduzido (art. 12-A §4º Lei 7.713/88)",
                "",
                f"− {_brl(pss_ded)}",
            ))
        hon_ded = Decimal(str(ir_d.get("honorarios_deduzido") or "0"))
        if hon_ded > 0:
            linhas.append((
                "(−) Honorários deduzidos (IN RFB 1500/2014 art. 8º/36)",
                "",
                f"− {_brl(hon_ded)}",
            ))
        linhas.append((
            "Base após deduções",
            "",
            f"= {_brl(ir_d.get('base_apos_deducoes'))}",
        ))
        linhas.append((
            "Base mensal (RRA)",
            f"{_brl(ir_d.get('base_apos_deducoes'))} ÷ {meses} meses",
            f"= {_brl(ir_d.get('base_mensal'))}",
        ))
        linhas.append((
            "Faixa da tabela progressiva mensal (IRPF)",
            f"alíquota {_pct_num(ir_d.get('aliquota_efetiva_pct'))} — parcela a "
            f"deduzir {_brl(ir_d.get('parcela_dedutivel'))}/mês",
            "",
        ))
        linhas.append((
            "IR-RRA (art. 12-A Lei 7.713/88)",
            f"({_brl(ir_d.get('base_mensal'))} × "
            f"{_pct_num(ir_d.get('aliquota_efetiva_pct'))} − "
            f"{_brl(ir_d.get('parcela_dedutivel'))}) × {meses} meses",
            f"= <b>{_brl(ir_d.get('valor_ir'))}</b>",
        ))
        blocos.append(
            '<div class="fase-h">IR-RRA — rendimentos recebidos acumuladamente '
            "(estimado)</div>" + _tabela(linhas)
        )

    return "".join(blocos)


def _cascata_html(cen: dict) -> str:
    linhas = []
    superpref_val = cen.get("valor_superpreferencia")
    superpref_data = cen.get("data_pagamento_superpreferencia")
    if superpref_val is not None:
        linhas.append((
            f"Valor corrigido até a superpreferência ({_data(superpref_data)})",
            _brl(cen.get("valor_corrigido_pre_superpreferencia")), "",
        ))
        linhas.append((
            f"(−) Superpreferência paga em {_data(superpref_data)}",
            _brl(superpref_val), "",
        ))
    linhas.append(("Valor total atualizado", _brl(cen.get("valor_total_atualizado")), ""))
    pss = cen.get("valor_pss")
    linhas.append(("(−) PSS / contribuição previdenciária",
                   "a apurar" if pss is None else _brl(pss), ""))
    ir = cen.get("valor_ir")
    linhas.append(("(−) IR-RRA", "a apurar" if ir is None else _brl(ir), ""))
    hcon = cen.get("valor_honorarios_contratuais")
    if hcon is not None:
        pct = cen.get("honorarios_contratuais_pct")
        rot = f"(−) Honorários contratuais ({pct}%)" if pct else "(−) Honorários contratuais"
        linhas.append((rot, _brl(hcon), ""))
    hsuc = cen.get("valor_honorarios_sucumbenciais")
    if hsuc is not None:
        pct = cen.get("honorarios_sucumbenciais_pct")
        rot = f"(−) Honorários sucumbenciais ({pct}%)" if pct else "(−) Honorários sucumbenciais"
        linhas.append((rot, _brl(hsuc), ""))
    rows = "".join(
        f'<tr><td class="k">{rot}</td><td class="num">{val}</td></tr>'
        for rot, val, _ in linhas
    )
    rows += (
        '<tr class="final"><td class="lbl">Valor líquido atualizado</td>'
        f'<td class="num">{_brl(cen.get("valor_liquido_atualizado"))}</td></tr>'
    )
    return f'<table class="wf">{rows}</table>'


def _honorarios_html(cen: dict, sucumb_pct=None, sucumb_valor=None) -> str:
    """Crédito do ADVOGADO, separado do crédito do credor.

    Existe para o comercial: advogado que quer ceder a própria parte precisa ver
    quanto ela vale, e até aqui os honorários só apareciam como linha `(−)` no
    meio da cascata — que responde "quanto sobra para o credor", não "quanto é do
    advogado".

    As duas linhas NÃO têm o mesmo estatuto, e a tabela diz isso em cada uma:

      contratuais   — o motor calcula (`pct × valor total atualizado`) e JÁ
                      deduziu no resultado acima. Número do cálculo.
      sucumbenciais — a calculadora nunca os deduziu de propósito (são crédito
                      do advogado, não desconto do credor), então o motor não
                      os calcula: o valor aqui é o percentual informado aplicado
                      sobre o mesmo total atualizado, para ordem de grandeza.
                      NÃO altera o líquido de ninguém.

    Vazio quando não há nem um nem outro — precatório sem honorários destacados
    não ganha seção em branco.
    """
    hcon = cen.get("valor_honorarios_contratuais")
    if hcon is None and sucumb_valor is None:
        return ""

    linhas = []
    if hcon is not None:
        pct = cen.get("honorarios_contratuais_pct")
        rot = "Honorários contratuais"
        if pct:
            rot += f" ({_pct_num(pct)})"
        linhas.append((rot, _brl(hcon), "já deduzidos do líquido acima"))

    suc_liquido = None
    if sucumb_valor is not None:
        rot = "Honorários sucumbenciais"
        if sucumb_pct:
            rot += f" ({_pct_num(sucumb_pct)})"
        linhas.append((rot, _brl(sucumb_valor),
                       "sobre o valor bruto atualizado — não deduzidos do líquido"))
        ir_suc = _q(Decimal(str(sucumb_valor)) * IR_SUCUMBENCIAIS_PCT / Decimal("100"))
        suc_liquido = _q(Decimal(str(sucumb_valor)) - ir_suc)
        linhas.append((f"(−) IR sobre os sucumbenciais ({_pct_num(IR_SUCUMBENCIAIS_PCT)})",
                       _brl(ir_suc), "faixa máxima da tabela do IR"))
        linhas.append(("Sucumbenciais líquidos", _brl(suc_liquido), ""))

    rows = "".join(
        f'<tr><td class="k">{rot}'
        + (f'<br/><span class="nota">{nota}</span>' if nota else "")
        + f'</td><td class="num">{val}</td></tr>'
        for rot, val, nota in linhas
    )
    nota_total = ""
    if hcon is not None and suc_liquido is not None:
        total = _q(Decimal(str(hcon)) + suc_liquido)
        rows += ('<tr class="final"><td class="lbl">Total do advogado</td>'
                 f'<td class="num">{_brl(total)}</td></tr>')
        # O total soma contratuais BRUTOS com sucumbenciais LÍQUIDOS — é
        # assimétrico de propósito (só o sucumbencial leva o IR, conferido com o
        # jurídico em 25/08/2026). Dizer isso embaixo do número evita que alguém
        # o leia como "o que o advogado recebe depois de todo imposto".
        nota_total = ('<div class="nota">Contratuais no bruto + sucumbenciais já '
                      "líquidos de IR.</div>")
    return f'<table class="wf">{rows}</table>{nota_total}'


def _cenarios_honorarios_html(linhas: list[dict] | None) -> str:
    """Tabela PROVISÓRIA "líquido por % de honorário contratual".

    Existe porque o contrato de honorários costuma chegar DEPOIS da pré-análise
    e o comercial precisava pedir recálculo ao jurídico a cada percentual novo
    (descontar por fora é errado: o % muda a base de PSS/IR — caso #2405). Cada
    linha vem do motor completo (`cenarios_honorarios_contratuais`); aqui só se
    renderiza. Vazia com menos de 2 linhas — tabela de uma linha não é cenário.
    """
    if not linhas or len(linhas) < 2:
        return ""
    rows = ""
    for ln in linhas:
        pct = Decimal(str(ln["pct"]))
        rot = "Sem honorário contratual" if pct == 0 else f"Contratuais de {_pct_num(pct)}"
        marca = ' <span class="nota">← este cálculo</span>' if ln.get("atual") else ""
        rows += (f'<tr><td class="k">{rot}{marca}</td>'
                 f'<td class="num">{_brl(ln["liquido"])}</td></tr>')
    ressalva = (
        '<div class="nota">Tabela provisória, para negociação enquanto o contrato de '
        "honorários não chega: cada linha é o cálculo completo refeito pelo motor com o "
        "percentual indicado (o percentual altera a base de PSS/IR — não é regra de três "
        "sobre o líquido). Não vale se o ofício tiver destaque de honorários (item 2.19) "
        "ou se o contrato tiver percentual escalonado ou base diferente do valor "
        "atualizado — nesses casos, refazer o cálculo com o contrato em mãos.</div>"
    )
    return f'<table class="wf">{rows}</table>{ressalva}'


def gerar_memorial_pdf(
    valores: list[tuple[str, str]],
    datas: list[tuple[str, str]],
    outros: list[tuple[str, str]],
    iniciais: dict | None,
    res: dict,
    gerado_em: date,
    referencia: str = "",
    aviso_projecao: str | None = None,
    observacao_advogado: str | None = None,
    sucumbenciais_pct=None,
    sucumbenciais_valor=None,
    cenarios_honorarios: list[dict] | None = None,
) -> bytes:
    """Monta o memorial em HTML e converte para PDF (bytes)."""
    cen = res.get("cenario_homologado") or {}

    outros_html = ""
    outros_itens = [f"<b>{l}:</b> {v}" for l, v in outros if v not in (None, "", "—")]
    if outros_itens:
        outros_html = '<div class="outros">' + " &nbsp;·&nbsp; ".join(outros_itens) + "</div>"

    ref_html = f'<div class="ref">{referencia}</div>' if referencia else ""

    trilha = _trilha_html(cen, iniciais) or _fallback_atualizacao_html(cen)

    caveats = ""
    if aviso_projecao:
        caveats += f'<div class="caveat">⚠ {aviso_projecao}</div>'
    ressalva = (cen.get("atualizacao") or {}).get("ressalva_adi")
    if ressalva:
        caveats += f'<div class="caveat">⚖ {ressalva}</div>'
    # (Havia aqui um aviso laranja "sucumbenciais: apenas informativo — não
    # descontados deste cálculo". Saiu em 25/08/2026: a seção "Honorários do
    # advogado" passou a mostrar o valor, com a ressalva na própria linha, e o
    # aviso virava contradição aparente — falava em "não descontado" logo abaixo
    # de uma tabela que desconta o IR. Um lugar só para o assunto.)
    obs = [o for o in (cen.get("observacoes") or []) if "onorár" not in o]
    if obs:
        caveats += '<div class="caveat">' + "<br/>".join(f"• {o}" for o in obs) + "</div>"
    # Observação livre do advogado — escapada (texto do usuário) e com quebras de
    # linha preservadas. Vai por último, no fim do PDF.
    if observacao_advogado:
        _obs = (
            observacao_advogado.replace("&", "&amp;")
            .replace("<", "&lt;").replace(">", "&gt;").replace("\n", "<br/>")
        )
        caveats += f'<div class="caveat"><b>Observações:</b> {_obs}</div>'

    # Seções numeradas dinamicamente: 1·Dados → [2·Memorial] → [PSS e IR] →
    # Resultado. A seção de descontos só existe quando o motor expôs a memória
    # (PSS/IR estimados).
    descontos = _descontos_html(cen)
    _num = 1
    memorial_sec = ""
    if trilha:
        _num += 1
        memorial_sec = f"<h1>{_num} · Memorial de cálculo</h1>{trilha}"
    descontos_sec = ""
    if descontos:
        _num += 1
        descontos_sec = (
            f"<h1>{_num} · PSS e IR — memória de cálculo</h1>{descontos}"
        )
    _num += 1
    titulo_resultado = f"{_num} · Resultado"
    # Crédito do advogado — sai DEPOIS do resultado de propósito: primeiro
    # "quanto sobra para o credor", que é a resposta do memorial, e só então
    # "quanto é do advogado", que é a pergunta do comercial.
    honorarios = _honorarios_html(cen, sucumbenciais_pct, sucumbenciais_valor)
    honorarios_sec = ""
    if honorarios:
        _num += 1
        honorarios_sec = f"<h1>{_num} · Honorários do advogado</h1>{honorarios}"
    # Cenários por % contratual — por último: é anexo de negociação (provisório),
    # não parte do cálculo aprovado.
    cenarios_hc = _cenarios_honorarios_html(cenarios_honorarios)
    cenarios_hc_sec = ""
    if cenarios_hc:
        _num += 1
        cenarios_hc_sec = (f"<h1>{_num} · Cenários por honorário contratual "
                           f"(provisório)</h1>{cenarios_hc}")

    _logo = _asset_uri("cabecalho.png")
    cabecalho = (
        f'<img src="{_logo}" style="height:40px" alt="Precatur"/>' if _logo
        else '<div class="brand">PRECATUR<span style="color:#34474D">-IA</span></div>'
    )
    # Rodapé: imagem institucional da marca (assets/rodape.png), fixada no fim da
    # página — o mesmo rodapé original do sistema. Telefone e endereço foram
    # atualizados direto na imagem (Segoe UI, mesmo estilo); CNPJ, régua, site e
    # ícones intactos. Sem disclaimer (já consta no topo, em `.gerado`).
    _rodape = _asset_uri("rodape.png")
    rodape_html = (
        f'<div id="rodape"><img src="{_rodape}" alt="Precatur — contato"/></div>'
        if _rodape else '<div id="rodape"></div>'
    )

    html = f"""<!DOCTYPE html><html><head><meta charset="utf-8"/>
<style>{_CSS}</style></head><body>
{cabecalho}
{ref_html}
<div class="gerado">Documento gerado em {gerado_em.strftime('%d/%m/%Y')} — apoio à
análise jurídica; conferir antes de uso.</div>

<h1>1 · Dados de entrada</h1>
{_hgrid(valores)}
{_hgrid(datas)}
{outros_html}

{memorial_sec}

{descontos_sec}

<h1>{titulo_resultado}</h1>
{_cascata_html(cen)}

{honorarios_sec}

{cenarios_hc_sec}

{caveats}

{rodape_html}
</body></html>"""

    buf = BytesIO()
    pisa.CreatePDF(src=html, dest=buf, encoding="utf-8")
    return buf.getvalue()
