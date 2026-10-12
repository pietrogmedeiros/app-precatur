# -*- coding: utf-8 -*-
"""RCL dos ESTADOS (governo estadual) no SICONFI, p/ dar orcamento §23 a' fila
estadual do Alfred. Mesmo endpoint/anexo do fetch_rcl_estados.py, mas o id_ente
e' o codigo IBGE de 2 digitos da UF (ES=32, MG=31). Grava data/rcl_uf_siconfi.csv.

Uso:  python scripts/fetch_rcl_uf.py            # ES e MG (default)
      python scripts/fetch_rcl_uf.py 32 31 35   # UFs especificas (codigo IBGE)
"""
import csv, json, os, pathlib, sys, time, unicodedata, urllib.parse, urllib.request

BASE = os.environ.get("ALFRED_BASE") or str(pathlib.Path(__file__).resolve().parents[1])
OUT = os.path.join(BASE, "data", "rcl_uf_siconfi.csv")
API = "https://apidatalake.tesouro.gov.br/ords/siconfi/tt/rreo"
ANOS = [2025, 2024]
# codigo IBGE de 2 digitos -> (nome, sigla). So os que o Alfred cobre por ora.
UFS = {"32": ("Estado do Espírito Santo", "ES"), "31": ("Estado de Minas Gerais", "MG"),
       "21": ("Estado do Maranhão", "MA")}


def norm(s):
    return unicodedata.normalize("NFKD", str(s)).encode("ascii", "ignore").decode().upper()


def get(url, tries=4):
    last = None
    for a in range(tries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=60) as r:
                return json.loads(r.read().decode("utf-8"))
        except Exception as e:  # noqa
            last = e; time.sleep(0.5 * (a + 1))
    raise RuntimeError(last)


def rcl(idente):
    for ano in ANOS:
        for tipo in ["RREO", "RREO Simplificado"]:
            q = urllib.parse.urlencode({"an_exercicio": ano, "nr_periodo": 6,
                "co_tipo_demonstrativo": tipo, "no_anexo": "RREO-Anexo 03", "id_ente": idente})
            for it in get(API + "?" + q).get("items", []):
                if norm(it.get("conta", "")).startswith("RECEITA CORRENTE LIQUIDA (III)") \
                        and "ULTIMOS 12 MESES" in norm(it.get("coluna", "")):
                    return ano, float(it.get("valor") or 0.0)
    return None, None


def main():
    alvos = sys.argv[1:] or list(UFS)
    # INCREMENTAL: le o que ja esta no CSV antes de escrever. Sem isso, rodar o
    # script para UMA uf apagava as demais (aconteceu ao acrescentar o MA: ES e MG
    # sumiram do arquivo).
    linhas = []
    if os.path.exists(OUT):
        with open(OUT, encoding="utf-8-sig") as f:
            linhas = [r for r in csv.DictReader(f) if r.get("codigo_ibge") not in alvos]
    for cod in alvos:
        nome, sigla = UFS.get(cod, (f"UF {cod}", "?"))
        ano, v = rcl(cod)
        print(f"{sigla} (id_ente={cod}): RCL {ano} = R$ {v:,.2f}" if v else f"{sigla}: nao achou")
        if v:
            linhas.append({"codigo_ibge": cod, "nome": nome, "uf": sigla,
                           "regime": "Especial", "rcl": f"{v:.2f}", "ano_rcl": ano})
    if linhas:
        with open(OUT, "w", encoding="utf-8-sig", newline="") as f:
            w = csv.DictWriter(f, fieldnames=["codigo_ibge", "nome", "uf", "regime", "rcl", "ano_rcl"])
            w.writeheader()
            w.writerows(sorted(linhas, key=lambda r: r["codigo_ibge"]))
        print("SALVO:", OUT)


if __name__ == "__main__":
    main()
