"""Juros de mora SIMPLES por janela — fase de condenação (Temas 810 STF / 905 STJ).

Componente ESTRUTURAL do motor histórico (docs/regimes_historicos.md §7 item 2):
os juros de mora são **simples** (não compõem — Súmula 121 STF veda juros sobre
juros) e ADITIVOS, somados como Σ de taxas mensais e aplicados pelo motor sobre o
principal já corrigido. Ficam SEPARADOS da correção monetária multiplicativa
(IPCA-E/INPC/… em `pipeline.indices`).

Este módulo NÃO aplica juros a um valor — ele só computa o **percentual acumulado**
(fração decimal) de uma janela, por modo. Quem multiplica pela base é o regime
builder / motor.

Modos de juros (§2 do doc):

- ``mensal_fixo`` — taxa a.m. constante. 0,5% a.m. (comum, CC/1916 art. 1.062, até
  2002) · 1% a.m. (alimentar/previdenciário — DL 2.322/87, Súmula 204 STJ).
- ``anual_fixo``  — taxa a.a. dividida por 12. Desapropriação: 6% a.m.… (moratórios
  art. 15-B DL 3.365/41) · 6%→12% a.a. (compensatórios, Súmula 618 STF / ADI 2.332).
- ``poupanca``    — art. 1º-F Lei 9.494/97 red. Lei 11.960/2009. Da competência
  **jul/2009** a **abr/2012**: 0,5% a.m. Desde **mai/2012** (MP 567 → Lei 12.703):
  ``min(0,5% a.m.; 70% × meta_Selic_anual / 12)``. A META Selic vem da SGS 432
  (``meta_selic.csv``) — taxa ANUAL, NÃO a série de rentabilidade da poupança
  (25/195/196 embutem a TR — armadilha A1 do doc). A TR do art. 1º-F entra como
  correção à parte (série ``TR``), nunca aqui.
- ``zero``        — sem juros (período de graça SV 17 / Tema 1037 / Tema 1.335; e
  janela SELIC/EC 113, onde a SELIC já embute os juros).

Convenção temporal = Manual de Cálculos da JF (idêntica a `pipeline.indices`): o
mês da data inicial é **excluído** (juros começam no mês seguinte ao termo inicial)
e o mês final é **incluído**. O termo inicial dos juros (citação, exercício
seguinte na desapropriação, etc.) é responsabilidade do caller — este módulo só
conta os meses da janela recebida.

Testável por aritmética pura (taxas fixas) e contra a SGS 432 (poupança); sem
depender de gabarito de tribunal (docs/regimes_historicos.md §7 "Validação").
"""

from __future__ import annotations

import csv
from datetime import date
from decimal import Decimal
from pathlib import Path
from threading import Lock


# ── Modos ────────────────────────────────────────────────────────────────────
MODO_MENSAL_FIXO = "mensal_fixo"
MODO_ANUAL_FIXO = "anual_fixo"
MODO_POUPANCA = "poupanca"
MODO_ZERO = "zero"

MODOS = frozenset({MODO_MENSAL_FIXO, MODO_ANUAL_FIXO, MODO_POUPANCA, MODO_ZERO})

# ── Poupança (art. 1º-F red. Lei 11.960/2009) ────────────────────────────────
POUPANCA_TETO_AM = Decimal("0.005")          # 0,5% a.m.
POUPANCA_FATOR_META = Decimal("0.7")         # 70% da meta Selic
# Início do regime da poupança no art. 1º-F (Lei 11.960, competência jul/2009).
POUPANCA_INICIO = "2009-07"
# Nova regra (piso da meta) por competência mensal — MP 567 de 04/05/2012 → Lei
# 12.703. Convenção mensal do MCJF: mai/2012 (ver §5 do doc).
POUPANCA_NOVA_REGRA = "2012-05"


class JurosForaDeCobertura(Exception):
    """Mês da janela de poupança fora da cobertura da série meta Selic (432)."""

    def __init__(self, motivo: str, detalhes: dict | None = None):
        super().__init__(motivo)
        self.motivo = motivo
        self.detalhes = detalhes or {}


# ── Loader da meta Selic (SGS 432) ───────────────────────────────────────────
# Fica FORA de `indices.INDICES_SUPORTADOS` de propósito: 432 é taxa ANUAL de
# evento (Copom), não um índice de correção mensal. `meta_selic.csv` guarda a
# meta vigente no 1º dia de cada mês (início do período de rendimento).
_META_CSV = (
    Path(__file__).resolve().parent.parent / "data" / "indices" / "meta_selic.csv"
)
_META_CACHE: dict[str, Decimal] | None = None
_META_LOCK = Lock()


def _load_meta_selic() -> dict[str, Decimal]:
    global _META_CACHE
    with _META_LOCK:
        if _META_CACHE is not None:
            return _META_CACHE
        if not _META_CSV.exists():
            raise FileNotFoundError(
                f"série meta Selic ausente: {_META_CSV}. "
                "Rode scripts/baixar_indices.py (baixar_meta_selic)."
            )
        out: dict[str, Decimal] = {}
        with open(_META_CSV, "r", encoding="utf-8") as f:
            for row in csv.reader(f):
                if not row or row[0].startswith("#") or row[0] == "mes":
                    continue
                try:
                    out[row[0]] = Decimal(row[1])
                except Exception:
                    continue
        _META_CACHE = out
        return out


def meta_selic_anual(mes: str) -> Decimal:
    """Meta Selic (% a.a.) vigente no 1º dia de `mes` ('YYYY-MM')."""
    serie = _load_meta_selic()
    valor = serie.get(mes)
    if valor is None:
        raise JurosForaDeCobertura(
            f"mês {mes} fora da cobertura da meta Selic (SGS 432)",
            {"mes": mes},
        )
    return valor


def taxa_poupanca_mensal(mes: str) -> Decimal:
    """Taxa de juros da poupança do mês `mes` ('YYYY-MM'), fração decimal a.m.

    Só a REMUNERAÇÃO do art. 1º-F (a TR é correção à parte). jul/2009→abr/2012:
    0,5%. Desde mai/2012: ``min(0,5%; 70% × meta/12)``. Levanta ValueError se
    `mes` é anterior a jul/2009 (fora do regime da poupança).
    """
    if mes < POUPANCA_INICIO:
        raise ValueError(
            f"poupança (art. 1º-F) só vale a partir de {POUPANCA_INICIO}; "
            f"pedido para {mes}. Antes de jul/2009 use taxa fixa (0,5%/1% a.m.)."
        )
    if mes < POUPANCA_NOVA_REGRA:
        return POUPANCA_TETO_AM
    meta = meta_selic_anual(mes)  # % a.a.
    setenta_pct_am = POUPANCA_FATOR_META * meta / Decimal("100") / Decimal("12")
    return min(POUPANCA_TETO_AM, setenta_pct_am)


# ── Iteração de meses (convenção MCJF: início excl., fim incl.) ───────────────
def _prox_mes(d: date) -> date:
    return date(d.year + 1, 1, 1) if d.month == 12 else date(d.year, d.month + 1, 1)


def _iter_meses(inicio_excl: date, fim_incl: date):
    """Meses 'YYYY-MM' entre `inicio_excl` (mês excluído) e `fim_incl` (incluído)."""
    cursor = _prox_mes(date(inicio_excl.year, inicio_excl.month, 1))
    fim = date(fim_incl.year, fim_incl.month, 1)
    while cursor <= fim:
        yield f"{cursor.year:04d}-{cursor.month:02d}"
        cursor = _prox_mes(cursor)


def taxa_mensal(
    modo: str,
    mes: str,
    taxa: Decimal | None = None,
) -> Decimal:
    """Taxa de juros SIMPLES do mês `mes`, fração decimal a.m. (ex.: 0.005).

    - ``mensal_fixo``: devolve `taxa` (fração a.m.; obrigatória).
    - ``anual_fixo``:  devolve `taxa / 12` (fração a.a.; obrigatória).
    - ``poupanca``:    fórmula do art. 1º-F (ignora `taxa`).
    - ``zero``:        0.
    """
    if modo == MODO_ZERO:
        return Decimal("0")
    if modo == MODO_POUPANCA:
        return taxa_poupanca_mensal(mes)
    if modo == MODO_MENSAL_FIXO:
        if taxa is None:
            raise ValueError("modo 'mensal_fixo' exige `taxa` (fração a.m.).")
        return taxa
    if modo == MODO_ANUAL_FIXO:
        if taxa is None:
            raise ValueError("modo 'anual_fixo' exige `taxa` (fração a.a.).")
        return taxa / Decimal("12")
    raise ValueError(f"modo de juros desconhecido: {modo!r} (use {sorted(MODOS)})")


def soma_juros(
    modo: str,
    inicio_excl: date,
    fim_incl: date,
    taxa: Decimal | None = None,
) -> Decimal:
    """Percentual de juros SIMPLES acumulado na janela (fração decimal).

    Σ das taxas mensais entre `inicio_excl` (mês excluído) e `fim_incl` (mês
    incluído). O caller multiplica pela base (principal corrigido). Devolve
    `Decimal("0")` se a janela não cobre nenhum mês completo ou se `modo` é
    'zero'.

    Para a poupança, os meses devem estar na cobertura da meta Selic (432) —
    senão levanta `JurosForaDeCobertura`.
    """
    if modo not in MODOS:
        raise ValueError(f"modo de juros desconhecido: {modo!r} (use {sorted(MODOS)})")
    if modo == MODO_ZERO:
        return Decimal("0")
    total = Decimal("0")
    for mes in _iter_meses(inicio_excl, fim_incl):
        total += taxa_mensal(modo, mes, taxa)
    return total
