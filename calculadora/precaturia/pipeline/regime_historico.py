"""Regime builder da FASE DE CONDENAÇÃO por natureza (Temas 810 STF / 905 STJ).

Dada a natureza do crédito + data-base + data final (inscrição/expedição ou
cálculo), deriva o regime a aplicar: uma lista de **períodos de correção**
(multiplicativa) e uma lista de **janelas de juros** (simples, aditiva) — a
separação estrutural que o motor histórico exige (docs/regimes_historicos.md §7
item 2). Função PURA (sem DB, sem IA), testável isoladamente.

Transcreve a matriz §2 do doc (verificada em fontes primárias). Convenção do
Manual de Cálculos da JF: mês inicial EXCLUÍDO, mês final INCLUÍDO (idêntica a
`indices.fator_periodo` / `juros_historicos.soma_juros`), de modo que os períodos
telescopam sem gap/overlap.

Fontes de correção por período:
- competências **< 2001-01**: ``HISTORICO`` (tabela de coeficientes TRF1,
  `indices.historico.fator_historico`) — exceto previdenciário (IGP-DI, SGS 190,
  desde 2000-01).
- competências **≥ 2001-01**: série SGS (`indices.fator_periodo`): IPCA-E / INPC /
  IGP-DI, ou ``SELIC`` (exclusiva — embute correção + juros; janela de juros = zero).

⚠ Escolhas do §5 do doc (conflitos em aberto) são PARÂMETROS, nunca decididas em
silêncio: `inpc_prev_inicio` (default 2006-04), e a natureza ``assistencial``
(BPC/LOAS) EXIGE `assistencial_indice` explícito ('INPC'|'IPCA-E').

NÃO aplica o regime a um valor (isso é do motor de aplicação, que resolve a
convenção de SELIC-exclusiva composta×simples e a base dos juros — questões de
modelagem sob validação). Aqui só se PRODUZ o regime.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from decimal import ROUND_HALF_UP, Decimal

from precaturia.pipeline import juros_historicos as jh
from precaturia.pipeline.indices import (
    fator_historico,
    fator_periodo,
    load_serie,
)


# ── Naturezas suportadas ─────────────────────────────────────────────────────
NAT_COMUM = "comum"
NAT_SERVIDOR = "servidor"
NAT_PREVIDENCIARIO = "previdenciario"
NAT_TRIBUTARIO = "tributario"
NAT_DESAPROPRIACAO = "desapropriacao"
NAT_ASSISTENCIAL = "assistencial"

NATUREZAS = frozenset({
    NAT_COMUM, NAT_SERVIDOR, NAT_PREVIDENCIARIO,
    NAT_TRIBUTARIO, NAT_DESAPROPRIACAO, NAT_ASSISTENCIAL,
})

# Fontes de correção (rótulo `correcao` dos pontos de regime).
CORR_HISTORICO = "HISTORICO"     # tabela TRF1 pré-2001
CORR_SELIC = "SELIC"             # SELIC exclusiva (embute juros → janela juros zero)

# Marcos temporais (competência 'YYYY-MM') — ver §3 do doc.
_SEAM_SGS = "2001-01"            # costura HISTORICO → SGS (IPCA-E unlagged)
_IGP_DI_COBERTURA = "2000-01"    # SGS 190 começa em 2000
_SELIC_TRIBUTARIO = "1996-01"    # art. 39 §4º Lei 9.250/95 (Tema 145 STJ)
_SELIC_COMUM = "2003-01"         # art. 406 CC/2002 (Tema 905)
_TEMA_810_POUPANCA = "2009-07"   # Lei 11.960/2009 (jul/2009)
_SELIC_COMUM_FIM = "2009-07"     # IPCA-E retroage a 30/06/2009 → jul/2009
_SERVIDOR_0_5 = "2001-08"        # MP 2.180-35 de 24/08/2001 (Tema 905 3.1.1(b))
_EC_113 = "2021-12"              # SELIC única (09/12/2021)
_INPC_PREV_DEFAULT = "2006-04"   # art. 41-A Lei 8.213/91 (§5 conflito → param)


class RegimeHistoricoError(Exception):
    pass


@dataclass
class PeriodoCorrecao:
    fonte: str                # 'HISTORICO' | 'SGS'
    indice: str               # 'IPCA-E'|'INPC'|'IGP-DI'|'SELIC'|'HISTORICO'
    inicio_excl: date         # mês excluído (convenção MCJF)
    fim_incl: date            # mês incluído
    rotulo: str = ""


@dataclass
class JanelaJuros:
    modo: str                 # juros_historicos.MODO_*
    taxa: Decimal | None      # fração (a.m. p/ mensal_fixo; a.a. p/ anual_fixo)
    inicio_excl: date
    fim_incl: date
    rotulo: str = ""


@dataclass
class RegimeHistorico:
    natureza: str
    data_base: date
    data_final: date
    correcao: list[PeriodoCorrecao] = field(default_factory=list)
    juros: list[JanelaJuros] = field(default_factory=list)
    avisos: list[str] = field(default_factory=list)


# ── Pontos de regime por natureza ────────────────────────────────────────────
# Cada ponto = (competência_início 'YYYY-MM', correcao, juros_modo, juros_taxa).
# Ativo da sua competência até o próximo ponto. '' = mais antigo (pré tudo).
_MENSAL = jh.MODO_MENSAL_FIXO
_ANUAL = jh.MODO_ANUAL_FIXO
_POUP = jh.MODO_POUPANCA
_ZERO = jh.MODO_ZERO


def _pontos(natureza: str, inpc_prev_inicio: str, assistencial_indice: str | None):
    d05, d1 = Decimal("0.005"), Decimal("0.01")
    if natureza == NAT_COMUM:
        return [
            ("", CORR_HISTORICO, _MENSAL, d05),           # CC/1916 art. 1.062
            (_SEAM_SGS, "IPCA-E", _MENSAL, d05),
            (_SELIC_COMUM, CORR_SELIC, _ZERO, None),      # art. 406 CC/2002
            (_SELIC_COMUM_FIM, "IPCA-E", _POUP, None),    # Tema 810
            (_EC_113, CORR_SELIC, _ZERO, None),           # EC 113
        ]
    if natureza == NAT_SERVIDOR:
        return [
            ("", CORR_HISTORICO, _MENSAL, d1),            # alimentar 1% (DL 2.322/87)
            (_SEAM_SGS, "IPCA-E", _MENSAL, d1),
            (_SERVIDOR_0_5, "IPCA-E", _MENSAL, d05),      # MP 2.180-35 (lex specialis)
            (_TEMA_810_POUPANCA, "IPCA-E", _POUP, None),
            (_EC_113, CORR_SELIC, _ZERO, None),
        ]
    if natureza == NAT_PREVIDENCIARIO:
        return [
            ("", CORR_HISTORICO, _MENSAL, d1),            # pré-2000: IGP-DI indisponível
            (_IGP_DI_COBERTURA, "IGP-DI", _MENSAL, d1),   # Lei 9.711/98; Súm. 204 (1%)
            (inpc_prev_inicio, "INPC", _MENSAL, d1),      # art. 41-A Lei 8.213/91
            (_TEMA_810_POUPANCA, "INPC", _POUP, None),
            (_EC_113, CORR_SELIC, _ZERO, None),
        ]
    if natureza == NAT_TRIBUTARIO:
        return [
            ("", CORR_HISTORICO, _MENSAL, d1),            # pré-1996: suporte limitado
            (_SELIC_TRIBUTARIO, CORR_SELIC, _ZERO, None), # SELIC exclusiva (Tema 145)
        ]
    if natureza == NAT_DESAPROPRIACAO:
        return [
            ("", CORR_HISTORICO, _ANUAL, Decimal("0.06")),  # moratórios 6% a.a.
            (_SEAM_SGS, "IPCA-E", _ANUAL, Decimal("0.06")), # correção plena (Súm. 561)
        ]
    if natureza == NAT_ASSISTENCIAL:
        idx = assistencial_indice
        return [
            ("", CORR_HISTORICO, _MENSAL, d1),
            (_IGP_DI_COBERTURA if idx == "INPC" else _SEAM_SGS, idx, _MENSAL, d1),
            (_TEMA_810_POUPANCA, idx, _POUP, None),
            (_EC_113, CORR_SELIC, _ZERO, None),
        ]
    raise RegimeHistoricoError(f"natureza desconhecida: {natureza!r} (use {sorted(NATUREZAS)})")


# ── Helpers de mês ───────────────────────────────────────────────────────────
def _ym(d: date) -> str:
    return f"{d.year:04d}-{d.month:02d}"


def _ultimo_dia_mes(ano: int, mes: int) -> date:
    if mes == 12:
        return date(ano, 12, 31)
    return date.fromordinal(date(ano, mes + 1, 1).toordinal() - 1)


def _competencias(data_base: date, data_final: date) -> list[str]:
    """Competências corrigidas: mês seguinte à data-base até o mês da data final
    (convenção MCJF — base excluída, final incluído)."""
    y, m = data_base.year, data_base.month
    m += 1
    if m > 12:
        m, y = 1, y + 1
    out: list[str] = []
    fy, fm = data_final.year, data_final.month
    while (y, m) <= (fy, fm):
        out.append(f"{y:04d}-{m:02d}")
        m += 1
        if m > 12:
            m, y = 1, y + 1
    return out


def _ativo_em(pontos: list, comp: str):
    """(correcao, juros_modo, juros_taxa) vigente na competência `comp`."""
    escolhido = pontos[0]
    for ponto in pontos:
        if ponto[0] <= comp:
            escolhido = ponto
        else:
            break
    return escolhido[1], escolhido[2], escolhido[3]


def construir_regime(
    natureza: str,
    data_base: date,
    data_final: date,
    *,
    inpc_prev_inicio: str = _INPC_PREV_DEFAULT,
    assistencial_indice: str | None = None,
) -> RegimeHistorico:
    """Constrói o regime da fase de condenação (correção + juros) por natureza.

    `natureza='assistencial'` (BPC/LOAS) EXIGE `assistencial_indice` ∈
    {'INPC','IPCA-E'} — o doc §5 manda expor a escolha, não decidir sozinho.
    """
    if natureza not in NATUREZAS:
        raise RegimeHistoricoError(
            f"natureza desconhecida: {natureza!r} (use {sorted(NATUREZAS)})"
        )
    if natureza == NAT_ASSISTENCIAL and assistencial_indice not in {"INPC", "IPCA-E"}:
        raise RegimeHistoricoError(
            "natureza 'assistencial' (BPC/LOAS) exige assistencial_indice "
            "'INPC' ou 'IPCA-E' (conflito em aberto §5 — decisão do advogado)."
        )

    regime = RegimeHistorico(natureza=natureza, data_base=data_base, data_final=data_final)
    comps = _competencias(data_base, data_final)
    if not comps:
        return regime  # data_final ≤ data_base: nada a corrigir

    pontos = _pontos(natureza, inpc_prev_inicio, assistencial_indice)

    # Estado mês a mês (à prova de off-by-one nas fronteiras), depois coalesce.
    estados = [(comp, *_ativo_em(pontos, comp)) for comp in comps]

    # ── Períodos de CORREÇÃO: coalesce por (correcao) ──
    # inicio_excl telescopa: base para o 1º; fim do anterior para os demais.
    inicio_excl = data_base
    i = 0
    n = len(estados)
    while i < n:
        comp_i, corr_i, _jm, _jt = estados[i]
        j = i
        while j + 1 < n and estados[j + 1][1] == corr_i:
            j += 1
        fim_comp = estados[j][0]
        fy, fm = int(fim_comp[:4]), int(fim_comp[5:7])
        fim_incl = _ultimo_dia_mes(fy, fm)
        if corr_i == CORR_HISTORICO:
            fonte, indice = "HISTORICO", "HISTORICO"
        elif corr_i == CORR_SELIC:
            fonte, indice = "SGS", "SELIC"
        else:
            fonte, indice = "SGS", corr_i
        regime.correcao.append(PeriodoCorrecao(
            fonte=fonte, indice=indice, inicio_excl=inicio_excl, fim_incl=fim_incl,
            rotulo=f"{indice} ({comp_i}→{fim_comp})",
        ))
        inicio_excl = fim_incl
        i = j + 1

    # ── Janelas de JUROS: coalesce por (modo, taxa) ──
    inicio_excl = data_base
    i = 0
    while i < n:
        comp_i, _corr, modo_i, taxa_i = estados[i]
        j = i
        while j + 1 < n and estados[j + 1][2] == modo_i and estados[j + 1][3] == taxa_i:
            j += 1
        fim_comp = estados[j][0]
        fy, fm = int(fim_comp[:4]), int(fim_comp[5:7])
        fim_incl = _ultimo_dia_mes(fy, fm)
        regime.juros.append(JanelaJuros(
            modo=modo_i, taxa=taxa_i, inicio_excl=inicio_excl, fim_incl=fim_incl,
            rotulo=f"{modo_i}{'' if taxa_i is None else f' {taxa_i}'} ({comp_i}→{fim_comp})",
        ))
        inicio_excl = fim_incl
        i = j + 1

    # ── Avisos (limitações conhecidas) ──
    primeira = comps[0]
    if natureza == NAT_PREVIDENCIARIO and primeira < _IGP_DI_COBERTURA:
        regime.avisos.append(
            "previdenciário pré-2000: IGP-DI (SGS 190) não cobre — correção via "
            "tabela histórica (IPCA-E/JF) como proxy; revisar."
        )
    if natureza == NAT_TRIBUTARIO and primeira < _SELIC_TRIBUTARIO:
        regime.avisos.append(
            "tributário pré-1996: SELIC exclusiva ainda não vigia — suporte "
            "limitado (correção histórica + 1% a.m. como proxy); revisar."
        )
    if natureza == NAT_DESAPROPRIACAO:
        regime.avisos.append(
            "desapropriação: modelados só os juros MORATÓRIOS (6% a.a.); juros "
            "COMPENSATÓRIOS (6%→12%→6% a.a., Súm. 618 STF) exigem regime manual."
        )
    if any(p.indice == "SELIC" for p in regime.correcao):
        regime.avisos.append(
            "contém janela de SELIC exclusiva (condenação): SELIC simples "
            "dentro da fase (1+Σ), embute correção+juros (Tema 145/905)."
        )
    return regime


# ── Motor de aplicação (correção multiplicativa + juros aditivo simples) ──────
@dataclass
class ComponenteCorrecao:
    indice: str
    inicio_excl: date
    fim_incl: date
    fator: Decimal


@dataclass
class ComponenteJuros:
    modo: str
    inicio_excl: date
    fim_incl: date
    percentual: Decimal      # Σ taxas da janela (fração)
    valor: Decimal           # percentual × principal_corrigido (VC final)


@dataclass
class ResultadoRegime:
    valor_originario: Decimal
    principal_corrigido: Decimal
    juros: Decimal
    total: Decimal
    fator_correcao: Decimal
    percentual_juros: Decimal
    componentes_correcao: list[ComponenteCorrecao] = field(default_factory=list)
    componentes_juros: list[ComponenteJuros] = field(default_factory=list)
    avisos: list[str] = field(default_factory=list)


def _fator_selic_simples(inicio_excl: date, fim_incl: date) -> Decimal:
    """SELIC exclusiva da CONDENAÇÃO = SIMPLES dentro da fase: ``1 + Σ selic_m``
    (SGS 4390, % a.m.). NÃO compõe ∏(1+i) — isso seria SELIC-sobre-SELIC
    (armadilha; a sistemática judicial/Projef soma; ver verdict A da verificação
    adversarial). Entre fases o encadeamento continua multiplicativo (telescopa).
    """
    serie = load_serie("SELIC")
    total = Decimal("0")
    for mes in jh._iter_meses(inicio_excl, fim_incl):
        taxa = serie.get(mes)
        if taxa is None:
            from precaturia.pipeline.indices import IndiceNaoSuportado
            raise IndiceNaoSuportado(
                f"mês {mes} fora da cobertura da SELIC (4390)", {"mes": mes}
            )
        total += taxa / Decimal("100")
    return Decimal("1") + total


def aplicar_regime_historico(
    valor_originario: Decimal, regime: RegimeHistorico
) -> ResultadoRegime:
    """Aplica o regime da condenação a um valor: correção MULTIPLICATIVA encadeada
    (telescopa entre fases) + juros SIMPLES ADITIVOS sobre o principal corrigido
    ao FINAL (Opção 1 do MCJF — ver verdicts A e B da verificação adversarial).

    - Correção: cada período multiplica o principal corrente. SELIC exclusiva usa
      `_fator_selic_simples` (embute juros → a janela de juros correspondente é
      'zero', sem dupla contagem); HISTORICO usa a tabela TRF1; SGS usa a série.
    - Juros: ``J = principal_corrigido × Σ(percentuais das janelas)`` — o mesmo VC
      final para todas as janelas (não itera mês a mês sobre base corrente).
    """
    principal = valor_originario
    comps_corr: list[ComponenteCorrecao] = []
    for p in regime.correcao:
        if p.indice == "SELIC":
            f = _fator_selic_simples(p.inicio_excl, p.fim_incl)
        elif p.fonte == "HISTORICO":
            f = fator_historico(p.inicio_excl, p.fim_incl)
        else:
            f = fator_periodo(p.indice, p.inicio_excl, p.fim_incl)
        principal *= f
        comps_corr.append(ComponenteCorrecao(p.indice, p.inicio_excl, p.fim_incl, f))

    principal_corrigido = principal.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    fator_correcao = (
        principal / valor_originario if valor_originario else Decimal("1")
    )

    perc_total = Decimal("0")
    comps_juros: list[ComponenteJuros] = []
    for j in regime.juros:
        perc = jh.soma_juros(j.modo, j.inicio_excl, j.fim_incl, j.taxa)
        if perc == 0:
            continue  # janela SELIC/graça — sem juros aditivo
        valor_j = (principal * perc).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        comps_juros.append(ComponenteJuros(j.modo, j.inicio_excl, j.fim_incl, perc, valor_j))
        perc_total += perc

    juros = (principal * perc_total).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    total = (principal_corrigido + juros).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

    return ResultadoRegime(
        valor_originario=valor_originario,
        principal_corrigido=principal_corrigido,
        juros=juros,
        total=total,
        fator_correcao=fator_correcao,
        percentual_juros=perc_total,
        componentes_correcao=comps_corr,
        componentes_juros=comps_juros,
        avisos=list(regime.avisos),
    )
