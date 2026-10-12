"""Baixa IPCA-E / IPCA / SELIC / INPC do BACEN SGS e ANEXA a projeção Focus
(meses futuros até dez do ano seguinte) — gera os CSVs em `precaturia/data/indices/`.

Fluxo (idempotente):
1. Baixa o histórico REAL do SGS (mesmos códigos de sempre).
2. Dropa o mês CORRENTE parcial da SELIC (a 4390 acumula intra-mês → o mês
   ainda aberto vem com valor incompleto, ex.: 0,05 no dia 1º).
3. Anexa a projeção Focus (IPCA/IPCA-E/SELIC) para os meses APÓS o último real,
   até dez do ano seguinte. O REAL sempre vence (a projeção só preenche buracos
   futuros). INPC não é projetado.
4. Grava CSV com 3 colunas `mes,variacao_pct,origem` + comentários
   `# ultimo_real` e `# projetado_ate`. O loader (`series.py`) ignora a 3ª
   coluna e os comentários — o valor entra no cálculo normalmente.

Rodar: `python scripts/baixar_indices.py`. Sem dependências (urllib puro).
Se o Focus estiver fora do ar, ABORTA sem sobrescrever os CSVs (não grava
projeção pela metade). Roda mensalmente via GitHub Action.
"""

from __future__ import annotations

import csv
import json
import sys
import urllib.request
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import projecao_focus  # noqa: E402

BACEN_BASE = "https://api.bcb.gov.br/dados/serie/bcdata.sgs.{codigo}/dados"
DATA_INICIAL = "01/01/2000"

# nome do arquivo, código(s) SGS, se projeta via Focus, e a chave da projeção.
SERIES = [
    {"nome": "ipca_e", "codigos": [7478, 10764], "proj": "IPCA-E",
     "descricao": "IPCA-15 (% a.m.) — 'IPCA-E' do Manual JF (pré-precatório/graça); splice 7478+10764. Meses futuros = PROJEÇÃO (proxy IPCA cheio Focus, IPCA-15 mensal descontinuado no Focus)"},
    {"nome": "ipca", "codigo": 433, "proj": "IPCA",
     "descricao": "IPCA cheio (% a.m.) — trecho EC 136/2025. Meses futuros = PROJEÇÃO Focus (mediana ExpectativaMercadoMensais)"},
    {"nome": "selic", "codigo": 4390, "proj": "SELIC",
     "descricao": "SELIC acumulada no mês (% a.m.). Mês corrente parcial descartado. Meses futuros = PROJEÇÃO (Selic meta anual Focus → base 252; premissa: cap EC 136 escolhe IPCA+2% em ~todo mês projetado)"},
    {"nome": "inpc", "codigo": 188, "proj": None,
     "descricao": "INPC (% a.m.) — IBGE. NÃO projetado (não entra na atualização ao presente)."},
    {"nome": "tr", "codigo": 7811, "proj": None,
     "descricao": "TR mensal (% a.m.) — Res. 303 art. 21-A inc. XI (fase precatório 10/12/2009→25/03/2015) e componente da correção da poupança. SGS 7811 (1º dia do mês; a 226 é diária). NÃO projetado."},
    {"nome": "igp_di", "codigo": 190, "proj": None,
     "descricao": "IGP-DI (% a.m.) — FGV. Correção previdenciária pré-abr/2006 (fase condenação, Tema 905). NÃO projetado."},
]

OUT_DIR = Path(__file__).resolve().parent.parent / "precaturia" / "data" / "indices"

# Meta Selic (SGS 432) — taxa ANUAL (% a.a.) definida pelo Copom, publicada
# DIARIAMENTE (forward-fill entre reuniões). NÃO é índice de correção (fica FORA
# de `series.INDICES_SUPORTADOS`): serve só à fórmula da poupança em
# `juros_historicos.py` (art. 1º-F Lei 11.960/2009, red. Lei 12.703/2012). Guardada
# como série MENSAL = meta vigente no 1º dia do mês (início do período de
# rendimento da poupança). NÃO projetada (regime poupança acaba na EC 113/2021).
META_SELIC_CODIGO = 432


def _get_sgs(codigo: int, di: str, df: str, tentativas: int = 3) -> list[dict]:
    url = (
        f"{BACEN_BASE.format(codigo=codigo)}"
        f"?formato=json&dataInicial={di}&dataFinal={df}"
    )
    print(f"  GET SGS {codigo} [{di}..{df}]")
    req = urllib.request.Request(url, headers={"Accept": "application/json"})
    ultimo_erro: Exception | None = None
    for _t in range(tentativas):
        try:
            with urllib.request.urlopen(req, timeout=60) as resp:
                corpo = resp.read().decode("utf-8").strip()
            if not corpo:
                raise RuntimeError("corpo vazio")
            return json.loads(corpo)
        except Exception as e:  # 406/HTML/vazio esporádico do SGS
            ultimo_erro = e
            import time
            time.sleep(2)
    raise RuntimeError(f"SGS {codigo} [{di}..{df}] falhou após {tentativas}x: {ultimo_erro!r}")


def baixar_serie(codigo: int) -> list[dict]:
    data_final = datetime.utcnow().strftime("%d/%m/%Y")
    return _get_sgs(codigo, DATA_INICIAL, data_final)


def baixar_serie_diaria(codigo: int, ano_inicial: int = 2000) -> list[dict]:
    """Séries DIÁRIAS do SGS (ex.: 432) — a API limita a janela a ~10 anos por
    requisição (janelas maiores devolvem HTTP 406). Fatia em blocos de 9 anos e
    concatena."""
    hoje = date.today()
    linhas: list[dict] = []
    ini = ano_inicial
    while ini <= hoje.year:
        fim = min(ini + 3, hoje.year)  # janelas de 4 anos (SGS diário é flaky em >~5a)
        di = f"01/01/{ini}"
        df = f"31/12/{fim}" if fim < hoje.year else hoje.strftime("%d/%m/%Y")
        linhas.extend(_get_sgs(codigo, di, df))
        ini = fim + 1
    return linhas


def _mes_iso(data_br: str) -> str:  # 'DD/MM/AAAA' -> 'AAAA-MM'
    dd, mm, yyyy = data_br.split("/")
    return f"{yyyy}-{mm}"


def baixar_real(serie: dict) -> dict[str, str]:
    """{'YYYY-MM': valor_str} do SGS. Splice por prioridade quando há `codigos`."""
    reais: dict[str, str] = {}
    codigos = serie.get("codigos") or [serie["codigo"]]
    for codigo in codigos:  # primeiro vence (splice)
        for row in baixar_serie(codigo):
            reais.setdefault(_mes_iso(row["data"]), row["valor"])
    return reais


def baixar_meta_selic() -> Path:
    """Gera `meta_selic.csv`: meta Selic (% a.a.) vigente no 1º dia de cada mês.

    Independente da projeção Focus (histórico real). A 432 vem DIÁRIA em % a.a.;
    colapsamos para o valor do dia 01 de cada mês (início do período de
    rendimento da poupança). Colunas: `mes, meta_anual_pct, origem`.
    """
    print(f"Série meta_selic (SGS {META_SELIC_CODIGO})...")
    por_mes: dict[str, str] = {}
    for row in baixar_serie_diaria(META_SELIC_CODIGO):
        dd, _mm, _yyyy = row["data"].split("/")
        if dd == "01":  # meta vigente no 1º dia do mês
            por_mes[_mes_iso(row["data"])] = row["valor"]
    if not por_mes:
        raise RuntimeError("SGS 432 não retornou nenhum dia-01 — abortando.")
    ultimo_real = max(por_mes)
    linhas = sorted(por_mes.items())
    out = OUT_DIR / "meta_selic.csv"
    with open(out, "w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(["# fonte", f"BACEN SGS {META_SELIC_CODIGO}"])
        w.writerow(["# descricao",
                    "Meta Selic definida pelo Copom (% a.a.) — valor vigente no 1º "
                    "dia do mês. Taxa ANUAL, fora de INDICES_SUPORTADOS (não é "
                    "correção); usada só na fórmula da poupança (juros_historicos). "
                    "NÃO projetada."])
        w.writerow(["# baixado_em", datetime.utcnow().strftime("%Y-%m-%d")])
        w.writerow(["# cobertura", f"{linhas[0][0]} a {linhas[-1][0]}"])
        w.writerow(["# ultimo_real", ultimo_real])
        w.writerow(["mes", "meta_anual_pct", "origem"])
        for mes, valor in linhas:
            w.writerow([mes, valor, "real"])
    print(f"  -> {out} ({len(linhas)} meses; real até {ultimo_real})")
    return out


def salvar_csv(nome: str, fonte: str, descricao: str,
               linhas: list[tuple[str, str, str]], ultimo_real: str,
               projetado_ate: str | None) -> Path:
    out = OUT_DIR / f"{nome}.csv"
    linhas = sorted(linhas, key=lambda t: t[0])
    with open(out, "w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(["# fonte", fonte])
        w.writerow(["# descricao", descricao])
        w.writerow(["# baixado_em", datetime.utcnow().strftime("%Y-%m-%d")])
        w.writerow(["# cobertura", f"{linhas[0][0]} a {linhas[-1][0]}"])
        w.writerow(["# ultimo_real", ultimo_real])
        if projetado_ate:
            w.writerow(["# projetado_ate", projetado_ate])
        w.writerow(["mes", "variacao_pct", "origem"])
        for mes, valor, origem in linhas:
            w.writerow([mes, valor, origem])
    return out


def main() -> int:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    hoje = date.today()
    ate = f"{hoje.year + 1}-12"
    ym_atual = f"{hoje.year:04d}-{hoje.month:02d}"

    # Meta Selic (poupança) — histórico real, independente do Focus. Fetch antes
    # do Focus para não depender dele (não é projetada).
    baixar_meta_selic()

    # Projeção Focus (uma coleta só p/ todos — coerência do cap EC 136).
    # Se o Focus falhar, aborta ANTES de tocar em qualquer CSV.
    print("Baixando projeção Focus (BACEN Expectativas)...")
    proj = projecao_focus.carregar_projecoes(ate)
    coleta = proj["coleta"]
    print(f"  coleta Focus: {coleta}")

    for s in SERIES:
        nome = s["nome"]
        print(f"Série {nome}...")
        reais = baixar_real(s)

        # SELIC: descartar o mês corrente (ainda aberto → valor parcial).
        if nome == "selic":
            reais = {m: v for m, v in reais.items() if m < ym_atual}

        ultimo_real = max(reais)
        linhas = [(m, v, "real") for m, v in reais.items()]

        projetado_ate: str | None = None
        chave = s["proj"]
        if chave:
            futuros = proj[chave]  # {mes: (Decimal, origem)}
            ultimo = None
            for mes in projecao_focus._iter_meses(_prox_mes(ultimo_real), ate):
                if mes in reais:
                    continue  # real vence
                if mes in futuros:
                    valor, origem = futuros[mes]
                    ultimo = (valor, origem)
                elif ultimo is not None:
                    valor, _o = ultimo
                    origem = ultimo[1] + "_carry"
                else:
                    continue
                linhas.append((mes, str(valor), origem))
            projetado_ate = ate

        fonte = ("BACEN SGS " + "+".join(str(c) for c in (s.get("codigos") or [s["codigo"]]))
                 + (f" + Focus {coleta}" if chave else ""))
        out = salvar_csv(nome, fonte, s["descricao"], linhas, ultimo_real, projetado_ate)
        proj_txt = f", projecao ate {ate}" if chave else ""
        print(f"  -> {out} ({len(linhas)} meses; real até {ultimo_real}{proj_txt})")

    print("OK.")
    return 0


def _prox_mes(mes_iso: str) -> str:
    y, m = map(int, mes_iso.split("-"))
    m += 1
    if m > 12:
        m, y = 1, y + 1
    return f"{y:04d}-{m:02d}"


if __name__ == "__main__":
    raise SystemExit(main())
