# -*- coding: utf-8 -*-
"""RCL de TODOS os municipios do Brasil via SICONFI (Tesouro Nacional).

Escala nacional do molde fetch_rcl_estados.py: RREO Anexo 03, linha
'RECEITA CORRENTE LIQUIDA (III)', coluna 'TOTAL (ULTIMOS 12 MESES)'.

Viabilidade medida em 2026-08-25 (piloto 32 municipios, todas as UFs):
  - 1,6 s/municipio sequencial; 4 threads sem 429 -> ~30-40 min p/ o pais;
  - ~1/3 dos municipios pequenos entrega 'RREO Simplificado' (2a tentativa);
  - DF nao e' municipio: consultar id_ente=53 (ente estadual);
  - nao-declarantes cronicos (~0,5%): fallback 2024/2023 e, no fim, fica vazio.

Resumavel: relê o proprio CSV de saida e pula quem ja tem RCL valida.
    python scripts/fetch_rcl_brasil.py
Saida: data/rcl_brasil_siconfi.csv (codigo_ibge, municipio, uf, ano_rcl, tipo_rreo, rcl)
"""
import csv
import io
import json
import os
import unicodedata
import sys
import threading
import time
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed

sys.stdout.reconfigure(encoding="utf-8")

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FONTE = os.path.join(BASE, "data", "regimes_brasil_municipios.csv")
OUT = os.path.join(BASE, "data", "rcl_brasil_siconfi.csv")
API = "https://apidatalake.tesouro.gov.br/ords/siconfi/tt/rreo"
ANOS = [2025, 2024, 2023]
TIPOS = ["RREO", "RREO Simplificado"]
WORKERS = 4
CAMPOS = ["codigo_ibge", "municipio", "uf", "ano_rcl", "tipo_rreo", "rcl",
          "deducao_fundeb", "rcl_p23"]

_lock = threading.Lock()


def sem_acento(s):
    """'DEDUÇÃO ... FORMAÇÃO DO FUNDEB' -> 'DEDUCAO ... FORMACAO DO FUNDEB'.
    Sem isso o filtro do FUNDEB nunca casa (a conta vem acentuada da API)."""
    return unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode().upper()


def get_json(url, tries=4):
    last = None
    for a in range(tries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=60) as r:
                return json.loads(r.read().decode("utf-8"))
        except Exception as e:                                    # noqa: BLE001
            last = e
            time.sleep(0.8 * (a + 1))
    raise RuntimeError(f"falhou: {last}")


def rcl_do_ente(ibge):
    """(ano, tipo, rcl, fundeb) ou (None, None, None, None). DF -> ente estadual 53.

    `fundeb` = linha 'Dedução de Receita para Formação do FUNDEB' do Anexo 03.
    Por que capturar: a RCL que os TRIBUNAIS usam para o art. 100 §23 nao e' a
    RCL(III) do RREO — e' a RCL do **art. 100 §18 / art. 101 §1º ADCT**, cuja lista
    de deducoes e' EXAUSTIVA e NAO inclui o FUNDEB. Na pratica os tribunais
    ESTORNAM a deducao do FUNDEB. Verificado contra o Enquadramento oficial do TJMG
    (EF2026, 40 municipios): `RCL(III) + FUNDEB` reproduz a RCL do tribunal com
    mediana +0,00% e 33/40 batendo abaixo de 1%, enquanto a RCL(III) pura erra
    -10,8%. Guardamos os dois: `rcl` (RREO/LRF) e `rcl_p23` (base de precatorios).
    """
    id_ente = "53" if ibge == "5300108" else ibge
    for ano in ANOS:
        for tipo in TIPOS:
            q = urllib.parse.urlencode({
                "an_exercicio": ano, "nr_periodo": 6, "co_tipo_demonstrativo": tipo,
                "no_anexo": "RREO-Anexo 03", "id_ente": id_ente})
            d = get_json(API + "?" + q)
            rcl = fundeb = None
            for it in d.get("items", []):
                conta = sem_acento(it.get("conta") or "")
                col = sem_acento(it.get("coluna") or "")
                if "ULTIMOS 12 MESES" not in col:
                    continue
                v = float(it.get("valor") or 0.0)
                if rcl is None and conta.startswith("RECEITA CORRENTE L") \
                        and "AJUSTADA" not in conta and v > 0:
                    rcl = v
                elif fundeb is None and "FORMACAO DO FUNDEB" in conta and v > 0:
                    fundeb = v
            if rcl:
                return ano, tipo, rcl, fundeb
    return None, None, None, None


def main():
    muns = list(csv.DictReader(io.open(FONTE, encoding="utf-8-sig")))
    cache = {}
    if os.path.exists(OUT):
        for r in csv.DictReader(io.open(OUT, encoding="utf-8-sig")):
            if r.get("rcl") not in ("", "None", None):
                cache[r["codigo_ibge"]] = r
    pendentes = [m for m in muns if m["codigo_ibge"] not in cache]
    print(f"municipios: {len(muns)} | ja validos: {len(cache)} | a buscar: {len(pendentes)}",
          flush=True)

    feitos = dict(cache)
    t0 = time.time()
    ok = [0]
    falha = []

    def um(m):
        ano, tipo, v, fdb = rcl_do_ente(m["codigo_ibge"])
        return m, ano, tipo, v, fdb

    def grava():
        with io.open(OUT, "w", encoding="utf-8-sig", newline="") as fh:
            w = csv.DictWriter(fh, fieldnames=CAMPOS)
            w.writeheader()
            for m in muns:                       # ordem canonica do arquivo-fonte
                r = feitos.get(m["codigo_ibge"])
                if r:
                    w.writerow({k: r.get(k, "") for k in CAMPOS})

    with ThreadPoolExecutor(max_workers=WORKERS) as ex:
        futs = {ex.submit(um, m): m for m in pendentes}
        for i, f in enumerate(as_completed(futs), 1):
            try:
                m, ano, tipo, v, fdb = f.result()
            except Exception as e:                                # noqa: BLE001
                m = futs[f]
                falha.append((m, str(e)[:60]))
                continue
            if v:
                with _lock:
                    feitos[m["codigo_ibge"]] = {
                        "codigo_ibge": m["codigo_ibge"], "municipio": m["municipio"],
                        "uf": m["uf"], "ano_rcl": ano, "tipo_rreo": tipo, "rcl": v,
                        "deducao_fundeb": fdb if fdb else "",
                        # base do §23: o §18 nao lista o FUNDEB entre as deducoes
                        "rcl_p23": round(v + fdb, 2) if fdb else v}
                    ok[0] += 1
            else:
                falha.append((m, "sem RCL 2023-2025 no SICONFI"))
            if i % 100 == 0:
                dt = time.time() - t0
                rest = dt / i * (len(pendentes) - i)
                print(f"  {i}/{len(pendentes)}  ok={ok[0]}  falhas={len(falha)}  "
                      f"{dt/60:.0f} min corridos, ~{rest/60:.0f} min restantes", flush=True)
                with _lock:
                    grava()                      # checkpoint resumavel

    grava()
    print(f"\ngravado: {OUT}  ({len(feitos)}/{len(muns)} com RCL)")
    if falha:
        print(f"\nSEM RCL ({len(falha)}):")
        for m, e in sorted(falha, key=lambda x: (x[0]['uf'], x[0]['municipio'])):
            print(f"  {m['codigo_ibge']} {m['municipio']}/{m['uf']}: {e}")


if __name__ == "__main__":
    main()
