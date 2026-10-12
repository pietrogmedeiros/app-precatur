# -*- coding: utf-8 -*-
"""Confere a RCL nacional recem-coletada (data/rcl_brasil_siconfi.csv).

Tres checagens, nesta ordem de importancia:
  1. COBERTURA — quantos dos 5.571 tem RCL, quem ficou de fora e por UF.
  2. CRUZAMENTO com as coletas anteriores por UF (mesma fonte, datas diferentes):
     divergencia grande = coleta velha ou exercicio diferente, nao erro novo.
  3. CRUZAMENTO com a RCL do TJMG (enquadramento §23 EF2026), que e' outra base:
     ja se sabia que o TJMG vem MAIOR; aqui se mede em quanto, no pais inteiro de MG.
  + sanidade: RCL por habitante fora de faixa plausivel vira alerta (nao erro fatal).

    python scripts/valida_rcl_brasil.py
"""
import csv
import glob
import io
import os
import statistics
import sys
from collections import Counter, defaultdict

sys.stdout.reconfigure(encoding="utf-8")
BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
D = os.path.join(BASE, "data")


def le(p, chave="codigo_ibge"):
    if not os.path.exists(p):
        return {}
    return {r[chave]: r for r in csv.DictReader(io.open(p, encoding="utf-8-sig"))}


muns = le(os.path.join(D, "regimes_brasil_municipios.csv"))
nac = le(os.path.join(D, "rcl_brasil_siconfi.csv"))

print("=" * 78)
print("  1. COBERTURA")
print("=" * 78)
print(f"  municipios (CNJ): {len(muns)}")
print(f"  com RCL nacional: {len(nac)}  ({100 * len(nac) / len(muns):.2f}%)")
faltam = [m for k, m in muns.items() if k not in nac]
print(f"  sem RCL .........: {len(faltam)}")
if faltam:
    for m in sorted(faltam, key=lambda x: (x["uf"], x["municipio"])):
        print(f"     {m['codigo_ibge']} {m['municipio']}/{m['uf']}")

anos = Counter(r["ano_rcl"] for r in nac.values())
tipos = Counter(r["tipo_rreo"] for r in nac.values())
print(f"\n  exercicio usado: {dict(sorted(anos.items(), reverse=True))}")
print(f"  tipo de RREO ..: {dict(tipos)}")
print("  (exercicio < 2025 = o municipio nao entregou o RREO de 2025 ainda)")

poruf = defaultdict(lambda: [0, 0])
for k, m in muns.items():
    poruf[m["uf"]][0] += 1
    if k in nac:
        poruf[m["uf"]][1] += 1
incompletas = {u: v for u, v in poruf.items() if v[0] != v[1]}
print(f"\n  UFs 100% cobertas: {len(poruf) - len(incompletas)} de {len(poruf)}")
for u, (t, c) in sorted(incompletas.items()):
    print(f"     {u}: {c}/{t}")

print("\n" + "=" * 78)
print("  2. CRUZAMENTO com as coletas por UF (mesma fonte SICONFI, data anterior)")
print("=" * 78)
for f in sorted(glob.glob(os.path.join(D, "rcl_*_siconfi.csv"))):
    nome = os.path.basename(f)
    if nome in ("rcl_brasil_siconfi.csv", "rcl_uf_siconfi.csv"):
        continue
    velho = le(f)
    difs, iguais, so_velho = [], 0, 0
    for k, r in velho.items():
        if not r.get("rcl") or k not in nac:
            so_velho += 1
            continue
        a, b = float(r["rcl"]), float(nac[k]["rcl"])
        if abs(a - b) < 0.01:
            iguais += 1
        else:
            difs.append((abs(b - a) / a * 100, k, r.get("municipio", "?"),
                         r.get("ano_rcl"), nac[k]["ano_rcl"], a, b))
    if not velho:
        continue
    print(f"\n  {nome}: {len(velho)} registros · idênticos {iguais} · "
          f"divergentes {len(difs)} · fora do nacional {so_velho}")
    if difs:
        difs.sort(reverse=True)
        med = statistics.median(d[0] for d in difs)
        print(f"     divergencia mediana {med:.1f}% — top 3:")
        for p, k, nm, av, an, a, b in difs[:3]:
            print(f"       {nm[:22]:22s} {av}->{an}  {a:>16,.0f} -> {b:>16,.0f}  ({p:+.1f}%)")

print("\n" + "=" * 78)
print("  3. CRUZAMENTO com a RCL do TJMG (enquadramento §23 EF2026) — base DIFERENTE")
print("=" * 78)
enq = le(os.path.join(D, "enquadramento_definitivo.csv"))
difs = []
for k, r in enq.items():
    if not r.get("rcl") or k not in nac:
        continue
    a, b = float(r["rcl"]), float(nac[k]["rcl"])
    if a > 0:
        difs.append(((b - a) / a * 100, r.get("ente", "?"), a, b))
if difs:
    ds = sorted(d[0] for d in difs)
    print(f"  {len(difs)} municipios de MG com as duas fontes")
    print(f"  SICONFI vs TJMG: mediana {statistics.median(ds):+.1f}% · "
          f"p10 {ds[len(ds)//10]:+.1f}% · p90 {ds[9*len(ds)//10]:+.1f}%")
    print("  (negativo = SICONFI menor que TJMG, como ja observado na amostra de 5)")
    print("  Precedencia no banco: o TJMG so entra onde o SICONFI nao tem — "
          "e agora tem quase tudo.")

print("\n" + "=" * 78)
print("  4. SANIDADE")
print("=" * 78)
vals = sorted((float(r["rcl"]), r["municipio"], r["uf"]) for r in nac.values())
print(f"  menor RCL: {vals[0][0]:>18,.2f}  {vals[0][1]}/{vals[0][2]}")
print(f"  maior RCL: {vals[-1][0]:>18,.2f}  {vals[-1][1]}/{vals[-1][2]}")
print(f"  mediana ..: {statistics.median(v[0] for v in vals):>18,.2f}")
print(f"  soma .....: {sum(v[0] for v in vals):>18,.2f}")
baixos = [v for v in vals if v[0] < 5e6]
if baixos:
    print(f"\n  ALERTA — RCL < R$ 5 mi ({len(baixos)}): valor implausivel p/ municipio, conferir")
    for v in baixos[:10]:
        print(f"     {v[1]}/{v[2]}: {v[0]:,.2f}")
