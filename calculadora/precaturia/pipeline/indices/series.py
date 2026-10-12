"""Loader das séries de índices versionadas em `data/indices/*.csv`.

Cache em memória após primeira leitura. Cada série vira um
`dict[str, Decimal]` onde a chave é `YYYY-MM` e o valor é a variação
percentual mensal (em pontos, ex.: 0.5 = 0.5%).

Os índices canônicos sem CSV (TR, IGP-M, IGP-DI, TJLP) ficam fora de
`INDICES_SUPORTADOS` — o caller deve checar antes de chamar
`load_serie` ou tratar a exceção `IndiceNaoSuportado`.
"""

from __future__ import annotations

import csv
from decimal import Decimal
from pathlib import Path
from threading import Lock


_DATA_DIR = Path(__file__).resolve().parent.parent.parent / "data" / "indices"


# Mapping canônico → nome do arquivo (sem extensão).
# - `IPCA-E` → `ipca_e.csv` (BACEN 10764 / IPCA-15, o "IPCA-E" do Manual de
#   Cálculos da JF): correção do pré-precatório e do período de graça.
# - `IPCA` → `ipca.csv` (BACEN 433 / IPCA cheio): usado SÓ no trecho EC 136/2025,
#   que constitucionalmente pede "IPCA" (não IPCA-E). Diferem ~0,05-0,1 pp/mês.
_ARQUIVO_POR_INDICE: dict[str, str] = {
    "IPCA-E": "ipca_e",
    "IPCA": "ipca",
    "SELIC": "selic",
    "INPC": "inpc",
    # Correção histórica (Res. 303 art. 21-A / Tema 905) — sem projeção Focus.
    "TR": "tr",          # SGS 7811 (fase precatório 2009-2015 + poupança)
    "IGP-DI": "igp_di",  # SGS 190 (previdenciário pré-abr/2006)
}

INDICES_SUPORTADOS: frozenset[str] = frozenset(_ARQUIVO_POR_INDICE.keys())


# Cache (escopo de processo).
_CACHE: dict[str, dict[str, Decimal]] = {}
_LOCK = Lock()


def _ler_csv(path: Path) -> dict[str, Decimal]:
    out: dict[str, Decimal] = {}
    with open(path, "r", encoding="utf-8") as f:
        reader = csv.reader(f)
        for row in reader:
            if not row:
                continue
            if row[0].startswith("#"):
                continue
            if row[0] == "mes":
                continue
            mes = row[0]
            try:
                valor = Decimal(row[1])
            except Exception:
                continue
            out[mes] = valor
    return out


def load_serie(indice: str) -> dict[str, Decimal]:
    """Carrega a série de um índice canônico. Cache em memória.

    Levanta `KeyError` se o índice não é suportado (não tem CSV).
    """
    if indice not in _ARQUIVO_POR_INDICE:
        raise KeyError(
            f"índice {indice!r} não está em INDICES_SUPORTADOS "
            f"({sorted(INDICES_SUPORTADOS)})"
        )
    with _LOCK:
        if indice in _CACHE:
            return _CACHE[indice]
        path = _DATA_DIR / f"{_ARQUIVO_POR_INDICE[indice]}.csv"
        if not path.exists():
            raise FileNotFoundError(
                f"CSV de índice ausente: {path}. Rode scripts/baixar_indices.py."
            )
        _CACHE[indice] = _ler_csv(path)
        return _CACHE[indice]


def cobertura(indice: str) -> tuple[str, str]:
    """Devolve (primeiro_mes, ultimo_mes) cobertos pela série."""
    serie = load_serie(indice)
    meses = sorted(serie.keys())
    return meses[0], meses[-1]


def ultimo_mes_real(indice: str) -> str | None:
    """Último mês YYYY-MM com dado REAL publicado (origem='real' na 3ª coluna).

    Meses posteriores são PROJEÇÃO Focus (ver `scripts/baixar_indices.py`). Usado
    pela UI para avisar quando a atualização ancora em meses projetados. Lê o
    arquivo em disco (não usa o cache de valores) — leve, chamado só no render.

    Fallbacks: comentário `# ultimo_real`; e, em CSV legado de 2 colunas (sem
    `origem`), o último mês (tudo é real). None se o índice não tem CSV.
    """
    if indice not in _ARQUIVO_POR_INDICE:
        return None
    path = _DATA_DIR / f"{_ARQUIVO_POR_INDICE[indice]}.csv"
    if not path.exists():
        return None
    ultimo_real: str | None = None
    comentario: str | None = None
    ultimo_qualquer: str | None = None
    with open(path, "r", encoding="utf-8") as f:
        for row in csv.reader(f):
            if not row:
                continue
            c0 = row[0].strip()
            if c0.startswith("#"):
                if c0 == "# ultimo_real" and len(row) > 1:
                    comentario = row[1].strip()
                continue
            if row[0] == "mes":
                continue
            ultimo_qualquer = row[0]
            origem = row[2].strip() if len(row) > 2 else "real"
            if origem == "real" and (ultimo_real is None or row[0] > ultimo_real):
                ultimo_real = row[0]
    return ultimo_real or comentario or ultimo_qualquer
