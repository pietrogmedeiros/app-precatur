"""Projeção dos índices futuros a partir do Boletim Focus (BACEN).

Estende as séries de índice ALÉM do último mês publicado, até dezembro do ano
seguinte, usando as expectativas de mercado do BACEN (API Olinda/Expectativas).
A cada rodada do cron, o valor REAL publicado pelo SGS substitui a projeção
(ver `baixar_indices.py`), então a projeção sempre reflete o dado mais recente.

Índices projetados (só os consumidos pela "atualização ao presente"):
- IPCA (SGS 433, trecho EC 136): Focus MENSAL vivo (ExpectativaMercadoMensais).
- IPCA-E (SGS 10764, graça): PROXY do IPCA cheio — o Focus descontinuou o
  IPCA-15 mensal em 2021 (última coleta 2021-02-17). Erro ~0,05-0,1 pp/mês,
  rotulado (`origem='projetado_proxy_ipca'`).
- SELIC (SGS 4390): expectativa ANUAL Focus (Selic fim de período), convertida
  para variação mensal na convenção base 252 (dias úteis reais).

INPC NÃO é projetado (não entra na atualização ao presente — só em regime de
correção histórico data-base→data-cálculo).

Premissas rotuladas (documentadas no `# descricao` do CSV):
- SELIC: usa a expectativa Focus anual (fim de período) flat no ano. A precisão
  intra-ano da SELIC é imaterial no trecho EC 136 porque a taxa mensal é
  `min(IPCA+2%/12, SELIC)` e a SELIC (~1,0-1,2%/mês) quase nunca é o mínimo — o
  cap escolhe IPCA+2%. A SELIC importa como teto (raro) e no pós-vencimento.
- IPCA-E ≈ IPCA cheio (proxy). Não é projeção oficial do IPCA-15.

Tudo em `Decimal` (regra 2). urllib puro, zero dependências.
"""

from __future__ import annotations

import json
import urllib.parse
import urllib.request
from datetime import date, timedelta
from decimal import Decimal

_OLINDA = "https://olinda.bcb.gov.br/olinda/servico/Expectativas/versao/v1/odata"


class FocusIndisponivel(RuntimeError):
    """Falha ao obter dados do Focus — o caller NÃO deve gravar CSV parcial."""


# ───────────────────────── API Olinda (Focus) ─────────────────────────


def _odata(entity: str, params: dict[str, str]) -> list[dict]:
    qs = "&".join(
        f"%24{k}={urllib.parse.quote(v, safe='')}" for k, v in params.items()
    )
    url = f"{_OLINDA}/{entity}?{qs}&%24format=json"
    try:
        with urllib.request.urlopen(url, timeout=60) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except Exception as exc:  # noqa: BLE001
        raise FocusIndisponivel(f"{entity}: {exc}") from exc
    return data.get("value", [])


def data_coleta_mais_recente() -> str:
    """A `Data` da coleta Focus mais recente do IPCA mensal (fixa a rodada —
    garante idempotência e coerência entre IPCA e SELIC)."""
    rows = _odata(
        "ExpectativaMercadoMensais",
        {
            "top": "1",
            "select": "Data",
            "filter": "Indicador eq 'IPCA' and baseCalculo eq 0",
            "orderby": "Data desc",
        },
    )
    if not rows:
        raise FocusIndisponivel("sem coleta de IPCA mensal no Focus")
    return rows[0]["Data"]


def _fetch_ipca_mensal(coleta: str) -> dict[str, Decimal]:
    """{'YYYY-MM': mediana_pct} das expectativas mensais de IPCA da coleta."""
    rows = _odata(
        "ExpectativaMercadoMensais",
        {
            "select": "DataReferencia,Mediana",
            "filter": f"Indicador eq 'IPCA' and baseCalculo eq 0 and Data eq '{coleta}'",
            "orderby": "DataReferencia asc",
        },
    )
    out: dict[str, Decimal] = {}
    for r in rows:
        mm, yyyy = r["DataReferencia"].split("/")  # 'MM/AAAA'
        out[f"{yyyy}-{mm}"] = Decimal(str(r["Mediana"]))
    return out


def _fetch_selic_anual(coleta: str) -> dict[int, Decimal]:
    """{ano: mediana_meta_aa} da expectativa Selic anual (fim de período)."""
    rows = _odata(
        "ExpectativasMercadoAnuais",
        {
            "select": "DataReferencia,Mediana",
            "filter": f"Indicador eq 'Selic' and baseCalculo eq 0 and Data eq '{coleta}'",
            "orderby": "DataReferencia asc",
        },
    )
    out: dict[int, Decimal] = {}
    for r in rows:
        out[int(r["DataReferencia"])] = Decimal(str(r["Mediana"]))
    if not out:
        raise FocusIndisponivel("sem expectativa Selic anual no Focus")
    return out


# ─────────────────── Dias úteis ANBIMA + conversão SELIC ───────────────────


def _pascoa(ano: int) -> date:
    """Domingo de Páscoa (algoritmo de Meeus/Butcher)."""
    a = ano % 19
    b, c = divmod(ano, 100)
    d, e = divmod(b, 4)
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i, k = divmod(c, 4)
    ll = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * ll) // 451
    mes = (h + ll - 7 * m + 114) // 31
    dia = ((h + ll - 7 * m + 114) % 31) + 1
    return date(ano, mes, dia)


def _feriados_nacionais(ano: int) -> set[date]:
    """Feriados nacionais bancários (calendário ANBIMA/252): fixos + móveis."""
    p = _pascoa(ano)
    fer = {
        date(ano, 1, 1),    # Confraternização
        date(ano, 4, 21),   # Tiradentes
        date(ano, 5, 1),    # Trabalho
        date(ano, 9, 7),    # Independência
        date(ano, 10, 12),  # N. Sra. Aparecida
        date(ano, 11, 2),   # Finados
        date(ano, 11, 15),  # Proclamação da República
        date(ano, 12, 25),  # Natal
        p - timedelta(days=48),  # Carnaval (segunda)
        p - timedelta(days=47),  # Carnaval (terça)
        p - timedelta(days=2),   # Sexta-feira Santa
        p + timedelta(days=60),  # Corpus Christi
    }
    if ano >= 2024:  # Consciência Negra — nacional desde a Lei 14.759/2023
        fer.add(date(ano, 11, 20))
    return fer


def dias_uteis(ano: int, mes: int) -> int:
    """Dias úteis (seg–sex, exceto feriados nacionais) do mês."""
    fer = _feriados_nacionais(ano)
    d = date(ano, mes, 1)
    n = 0
    while d.month == mes and d.year == ano:
        if d.weekday() < 5 and d not in fer:
            n += 1
        d += timedelta(days=1)
    return n


def selic_meta_para_mensal_pct(meta_aa: Decimal, ano: int, mes: int) -> Decimal:
    """Meta Selic anual (% a.a.) → variação mensal % na convenção base 252
    (capitalização diária pelos dias úteis do mês, padrão SGS 4390)."""
    D = dias_uteis(ano, mes)
    fator = (Decimal(1) + meta_aa / Decimal(100)) ** (Decimal(D) / Decimal(252))
    return ((fator - Decimal(1)) * Decimal(100)).quantize(Decimal("0.01"))


# ───────────────────────── Montagem da projeção ─────────────────────────


def _iter_meses(inicio: str, fim: str):
    """Itera 'YYYY-MM' de `inicio` a `fim` inclusive."""
    ay, am = map(int, inicio.split("-"))
    by, bm = map(int, fim.split("-"))
    y, m = ay, am
    while (y, m) <= (by, bm):
        yield f"{y:04d}-{m:02d}"
        m += 1
        if m > 12:
            m, y = 1, y + 1


def carregar_projecoes(ate_mes: str) -> dict[str, dict[str, tuple[Decimal, str]]]:
    """Baixa o Focus e monta a projeção mensal contígua de cada índice até
    `ate_mes` (YYYY-MM), a partir de 2025-01 (folga; o merge só usa meses >
    último real). Retorna {indice: {mes: (valor, origem)}}.

    Índices: 'IPCA', 'IPCA-E', 'SELIC'. NÃO projeta INPC.
    Contiguidade garantida (carry-forward de qualquer buraco) — um mês faltante
    no meio degradaria o motor para `cobertura_insuficiente`.
    """
    coleta = data_coleta_mais_recente()
    ipca_focus = _fetch_ipca_mensal(coleta)
    selic_anual = _fetch_selic_anual(coleta)

    inicio = "2025-01"
    meses = list(_iter_meses(inicio, ate_mes))

    # IPCA (433): mediana Focus por mês; carry-forward de buracos.
    ipca: dict[str, tuple[Decimal, str]] = {}
    ultimo_ipca: Decimal | None = None
    for mes in meses:
        if mes in ipca_focus:
            ultimo_ipca = ipca_focus[mes]
            ipca[mes] = (ultimo_ipca, "projetado_focus")
        elif ultimo_ipca is not None:
            ipca[mes] = (ultimo_ipca, "projetado_focus_carry")
    # IPCA-E: proxy do IPCA cheio (mesmos valores, rótulo próprio).
    ipca_e = {m: (v, "projetado_proxy_ipca") for m, (v, _o) in ipca.items()}

    # SELIC (4390): meta anual → mensal base 252; ano sem expectativa carrega
    # a última meta conhecida (carry-forward).
    selic: dict[str, tuple[Decimal, str]] = {}
    ultima_meta: Decimal | None = None
    for mes in meses:
        ano = int(mes[:4])
        the_no = int(mes[5:7])
        meta = selic_anual.get(ano, ultima_meta)
        if meta is None:
            continue
        ultima_meta = meta
        selic[mes] = (
            selic_meta_para_mensal_pct(meta, ano, the_no),
            "projetado_selic_focus",
        )

    return {
        "coleta": coleta,  # type: ignore[dict-item]
        "IPCA": ipca,
        "IPCA-E": ipca_e,
        "SELIC": selic,
    }


if __name__ == "__main__":  # smoke test manual
    hoje = date.today()
    ate = f"{hoje.year + 1}-12"
    proj = carregar_projecoes(ate)
    print("coleta Focus:", proj["coleta"])
    for idx in ("IPCA", "IPCA-E", "SELIC"):
        d = proj[idx]
        ks = sorted(d.keys())
        print(f"{idx:6} {ks[0]}..{ks[-1]} ({len(ks)} meses); amostra:",
              {k: str(d[k][0]) for k in ks[:2] + ks[-2:]})
    print("dias úteis 2027-02:", dias_uteis(2027, 2), "| 2027-05:", dias_uteis(2027, 5))
    print("SELIC 14% a.a. em 2027-01:", selic_meta_para_mensal_pct(Decimal("14"), 2027, 1))
