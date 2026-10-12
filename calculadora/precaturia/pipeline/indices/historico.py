"""Correção monetária histórica — tabela de coeficientes OFICIAL do CJF.

Análogo de `aplicar.fator_periodo`, mas para datas-base ANTIGAS (1964→2000) que
não têm série SGS em %. Fonte: `data/historico/cjf_tcm_geral.csv` — a Tabela de
Correção Monetária do **SICOM/CJF** (Manual de Cálculos da JF; cadeia
ORTN→OTN→IPC→BTN→IPC→INPC→UFIR→IPCA-E do art. 21-A da Res. CNJ 303/2019, com os
expurgos oficiais dos Planos). Baixada por `scripts/baixar_tabela_cjf.py`.

SUPERSEDE a tabela regional `fatores_trf1_1964_2019.csv` (TRF1/SJRO), que batia o
CJF de 1991 em diante mas DIVERGIA no pré-1991 (fator ~3,017× em 1964-1988) por
tratar os expurgos Verão/1989 e Collor/1990 de outro modo. Validado contra o CJF
(a autoridade): igual ao centavo de 1991+; ver docs/regimes_historicos.md §6.

## Como funciona (telescoping reform-safe)

`coef(M)` é o fator ABSOLUTO que traz o valor do mês M à referência da tabela. A
correção de A→B é a razão:

    fator = coef[mês(A)] / coef[mês(B)]

Isso **telescopa exatamente** o produto das variações mensais e é SEGURO cruzando
reformas monetárias — as redenominações (Cruzeiro Novo /1000 em 1967, Cruzado,
Cruzado Novo, Real /2750 em 1994, …) e os expurgos já estão embutidos nos
coeficientes; a razão entre dois meses quaisquer os incorpora sem tratamento
especial.

⚠ **Série LAGGED (defasagem de 1 mês)**: `coef[M-1]/coef[M] == 1 + IPCA-E_SGS[M-1]`
(convenção de precatório: aplica o índice do mês anterior). A série SGS
(`aplicar.fator_periodo`) é UNLAGGED. Por isso o motor usa esta tabela SÓ até
2000-12 e emenda a SGS IPCA-E de 2001-01 em diante — casos recentes seguem 100%
SGS (já validado vs LBZ/Projef). Costurar as duas no meio de 2001+ reintroduz a
defasagem.

Cobertura: 1964-10 → 2025-12, CONTÍGUA (a tabela do CJF não tem o buraco de
2001-01 da antiga TRF1).
"""

from __future__ import annotations

import csv
from datetime import date
from decimal import Decimal
from pathlib import Path
from threading import Lock


_CSV = (
    Path(__file__).resolve().parent.parent.parent
    / "data" / "historico" / "cjf_tcm_geral.csv"
)

# {'YYYY-MM': coef}. Cache de processo.
_COEF: dict[str, Decimal] | None = None
_LOCK = Lock()

# Cadeia de índices por competência (rótulos p/ display) — do rodapé da TCM/CJF.
# (inicio_incl, fim_incl, label). Expurgos: IPC-IBGE em jan-fev/1989 (Verão) e
# mar/1990-fev/1991 (Collor).
_CADEIA: list[tuple[str, str, str]] = [
    ("1964-10", "1986-02", "ORTN"),
    ("1986-03", "1988-12", "OTN"),
    ("1989-01", "1989-02", "IPC-IBGE"),   # Plano Verão
    ("1989-03", "1990-02", "BTN"),
    ("1990-03", "1991-02", "IPC-IBGE"),   # Plano Collor
    ("1991-03", "1991-11", "INPC"),
    ("1991-12", "1991-12", "IPCA-especial"),
    ("1992-01", "2000-12", "UFIR"),
    ("2001-01", "2025-12", "IPCA-E"),
]


class HistoricoForaDeCobertura(Exception):
    """Mês pedido fora da tabela de coeficientes pré-2001 (ou no buraco 2001-01)."""

    def __init__(self, motivo: str, detalhes: dict | None = None):
        super().__init__(motivo)
        self.motivo = motivo
        self.detalhes = detalhes or {}


def _load() -> dict[str, Decimal]:
    global _COEF
    with _LOCK:
        if _COEF is not None:
            return _COEF
        if not _CSV.exists():
            raise FileNotFoundError(
                f"tabela de correção CJF ausente: {_CSV}. "
                "Rode scripts/baixar_tabela_cjf.py."
            )
        coef: dict[str, Decimal] = {}
        with open(_CSV, "r", encoding="utf-8") as f:
            for row in csv.reader(f):
                if not row or row[0].startswith("#") or row[0] == "mes":
                    continue
                try:
                    coef[row[0]] = Decimal(row[1])
                except Exception:
                    continue
        _COEF = coef
        return coef


def coef(mes: str) -> Decimal:
    """Coeficiente absoluto do mês 'YYYY-MM'. Levanta se fora de cobertura."""
    c = _load().get(mes)
    if c is None:
        raise HistoricoForaDeCobertura(
            f"mês {mes} fora da tabela CJF (1964-10..2025-12)",
            {"mes": mes},
        )
    return c


def indice_label(mes: str) -> str:
    """Rótulo do índice vigente no mês (cadeia oficial do Manual JF)."""
    for ini, fim, label in _CADEIA:
        if ini <= mes <= fim:
            return label
    return ""


def cobertura_historico() -> tuple[str, str]:
    meses = sorted(_load().keys())
    return meses[0], meses[-1]


def _mes(d: date) -> str:
    return f"{d.year:04d}-{d.month:02d}"


def fator_historico(de_excl: date, ate_incl: date) -> Decimal:
    """Fator de correção histórico entre `de_excl` (mês excluído) e `ate_incl`
    (mês incluído) — convenção do Manual JF, idêntica a `aplicar.fator_periodo`.

    `fator = coef[mês(de_excl)] / coef[mês(ate_incl)]` (telescoping reform-safe).
    Retorna `Decimal("1")` se ambos caem no mesmo mês. Levanta
    `HistoricoForaDeCobertura` se qualquer um dos meses-extremo estiver fora da
    tabela (1964-10..2025-12).
    """
    return coef(_mes(de_excl)) / coef(_mes(ate_incl))
