# -*- coding: utf-8 -*-
"""Ato Conjunto do Comite Gestor de Contas Especiais do RN -> data/djen_nacp_rn.json.

    python scripts/fetch_ato_conjunto_rn.py            # baixa do DJEN e grava
    python scripts/fetch_ato_conjunto_rn.py --texto f  # reparseia um texto ja baixado

No RN o limite anual de pagamento (art. 100 §23, EC 136/2025) de CADA ente -- Estado e
167 municipios -- sai num unico ato publicado no DJEN pelo processo administrativo
0801288-28.2026.8.20.9500 (Ato Conjunto n. 01/2026, 26/02/2026). Traz: acervo (a base do
§23), RCL usada, % da RCL (faixa), valor a pagar em 2026 e o RATEIO entre TJRN, TRT21 e
TRF1/2/5.

O arquivo sai no MESMO formato do `djen_nacp_ba.json`, entao `db_nacp.carrega` o lê sem
mudar nada e o parecer passa a usar o valor e o rateio oficiais (alfred_core: valor_oficial
e _rateio_tribunal). Antes disto o Alfred usava 1,5% p/ o Estado do RN; o ato diz 2,0%.

Ressalvas do proprio ato: (1) o % foi calculado com a RCL do 5o bimestre de 2025 e sera
atualizado quando cada ente informar a RCL do ano todo; (2) "TOTAL ACERVO" e' a base da
faixa -- tratada aqui como a mora de 1o/jan (mesma coluna do plano da BA).
"""
import argparse
import json
import os
import pathlib
import re
import sys
import unicodedata

import requests

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

BASE = os.environ.get("ALFRED_BASE") or str(pathlib.Path(__file__).resolve().parents[1])
DJEN = "https://comunicaapi.pje.jus.br/api/v1/comunicacao"
PROCESSO = "08012882820268209500"
ANO = 2026
UF_ESTADO_IBGE = "24"          # pseudo-IBGE do Estado do RN no banco (municipio.ibge = '24')

RX_LINHA = re.compile(
    r"([A-ZÀ-Úa-zà-ú][A-Za-zÀ-ú0-9\s\-\.\/'’()]*?)\s+"
    r"R\$\s*([\d.]+,\d{2})\s+"            # TOTAL ACERVO
    r"R\$\s*([\d.]+,\d{2})\s+"            # RCL
    r"([\d,]+)%\s+"                       # divida / RCL
    r"([\d,]+)%\s+"                       # comprometimento (faixa do §23)
    r"R\$\s*([\d.]+,\d{2})\s+"            # valor a pagar no exercicio
    r"([\d,]+)%\s+([\d,]+)%\s+([\d,]+)%\s+([\d,]+)%\s+([\d,]+)%")  # TJRN TRT21 TRF1 TRF2 TRF5
# o cabecalho da tabela sobra colado no nome da 1a linha ("TRF5 Acari")
RX_CAB = re.compile(r"^(?:TRF\d|TRT\d+|TJRN)\s+(?=[A-ZÀ-Ú])")


def norm(s):
    s = unicodedata.normalize("NFKD", str(s or "")).encode("ascii", "ignore").decode()
    return re.sub(r"[^A-Z0-9]+", " ", s.upper()).strip()


def num(s):
    return float(s.replace(".", "").replace(",", "."))


def pct(s):
    return float(s.replace(",", "."))


def baixa_texto():
    r = requests.get(DJEN, params={"numeroProcesso": PROCESSO, "itensPorPagina": 20},
                     headers={"User-Agent": "Mozilla/5.0 (alfred-nacp)"}, timeout=90)
    r.raise_for_status()
    for it in r.json().get("items", []):
        t = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", it.get("texto") or ""))
        if "ATO CONJUNTO" in t.upper() and "Nome da Entidade Devedora" in t:
            return t, it
    sys.exit("publicacao do Ato Conjunto nao encontrada no DJEN")


def mapa_ibge_rn():
    d = json.load(open(os.path.join(BASE, "data", "ibge_br_municipios.json"), encoding="utf-8"))
    return {norm(m["municipio-nome"]): str(m["municipio-id"]) for m in d if m.get("UF-sigla") == "RN"}


# grafias do ato que nao batem com o IBGE
ALIAS = {"ACU": "ASSU", "ARES": "AREZ"}


def acha_ibge(nome, mapa):
    """Casa o nome do ato com o IBGE. O ato escreve 'Campo Grande (Augusto Severo)' e
    'Boa Saúde (Januário Cicco)' (nome antigo entre parenteses); o IBGE guarda so' um deles."""
    cands = [nome]
    m = re.match(r"^(.*?)\s*\((.*?)\)\s*$", nome)
    if m:
        cands += [m.group(1), m.group(2)]
    for c in cands:
        n = norm(c)
        n = ALIAS.get(n, n)
        if n in mapa:
            return mapa[n]
    return None


def parse(texto):
    i = texto.find("Nome da Entidade Devedora")
    linhas = []
    for m in RX_LINHA.finditer(texto[i:]):
        nome = RX_CAB.sub("", m.group(1).strip())
        linhas.append({
            "devedor": nome,
            "mora_1jan": num(m.group(2)),
            "rcl_ato": num(m.group(3)),
            "divida_sobre_rcl_pct": pct(m.group(4)),
            "pct_aplicado": pct(m.group(5)),
            "valor_anual": num(m.group(6)),
            "rateio": {"TJ": pct(m.group(7)), "TRT": pct(m.group(8)),
                       "TRF": round(pct(m.group(9)) + pct(m.group(10)) + pct(m.group(11)), 2)},
        })
    return linhas


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--texto", help="arquivo com o texto ja baixado (pula o DJEN)")
    a = ap.parse_args()
    if a.texto:
        texto, it = open(a.texto, encoding="utf-8").read(), {}
    else:
        texto, it = baixa_texto()
    linhas = parse(texto)
    mapa = mapa_ibge_rn()
    sem = []
    for ln in linhas:
        n = norm(ln["devedor"])
        if n == "ESTADO DO RIO GRANDE DO NORTE":
            ln["ibge"] = UF_ESTADO_IBGE
        else:
            ln["ibge"] = acha_ibge(ln["devedor"], mapa)
            if not ln["ibge"]:
                sem.append(ln["devedor"])
    pub = {"tipo": "ato_conjunto", "data": (it.get("data_disponibilizacao") or "2026-02-26"),
           "pa": it.get("numeroprocessocommascara") or "0801288-28.2026.8.20.9500",
           "id_djen": it.get("id")}
    for ln in linhas:
        ln["fonte"] = pub
    saida = {"uf": "RN", "tribunal": "TJRN", "orgao_id": None,
             "janela": {"de": pub["data"], "ate": pub["data"]},
             "coletado_em": __import__("datetime").date.today().isoformat(),
             "tabela_p23": {str(ANO): {"ano": ANO, "fonte": pub, "entes": linhas}},
             "atos": []}
    fn = os.path.join(BASE, "data", "djen_nacp_rn.json")
    json.dump(saida, open(fn, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(f"{len(linhas)} entes ({sum(1 for x in linhas if x['ibge'])} com IBGE) -> {fn}")
    if sem:
        print("  sem IBGE:", sem)
    est = [x for x in linhas if x["ibge"] == UF_ESTADO_IBGE]
    print("  Estado do RN:", est[0] if est else "NAO ACHADO")


if __name__ == "__main__":
    main()
