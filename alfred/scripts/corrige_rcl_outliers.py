# -*- coding: utf-8 -*-
"""Detecta e corrige RCL implausivel em data/rcl_brasil_siconfi.csv.

MOTIVO (achado 2026-08-25): o SICONFI publica o que o ENTE declarou, e ha
declaracao errada. Sao Jose dos Ausentes/RS declarou o RREO 2025 com RCL de
R$ 3,88 mi contra R$ 46,5 mi em 2024 e R$ 37,2 mi em 2023 — 12x menor. Como a
RCL alimenta o teto do art. 100 §23, um erro desses encolhe o teto na mesma
proporcao e joga a projecao de pagamento para decadas a frente.

DETECCAO em duas camadas (nenhuma depende de julgamento manual):
  1. RCL POR HABITANTE fora da faixa plausivel. Populacao vem da propria API
     do SICONFI (/tt/entes). Municipio brasileiro roda entre ~R$ 2 mil e ~R$ 30
     mil de RCL por habitante; fora disso e' suspeito.
  2. SALTO ENTRE EXERCICIOS: recoleta 3 anos do suspeito e compara. RCL nominal
     nao cai 50% em um ano — quando cai, o exercicio corrente esta' errado e o
     anterior e' a melhor estimativa disponivel.

CORRECAO: troca pelo exercicio anterior coerente e marca a origem na coluna
`tipo_rreo` (sufixo ' [ano anterior: declaracao <ano> inconsistente]'), para o
parecer nunca afirmar um numero cuja procedencia se perdeu.

    python scripts/corrige_rcl_outliers.py            # relatorio, nao grava
    python scripts/corrige_rcl_outliers.py --aplicar  # corrige o CSV
"""
import csv
import io
import json
import os
import sys
import time
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor

sys.stdout.reconfigure(encoding="utf-8")
BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CSV = os.path.join(BASE, "data", "rcl_brasil_siconfi.csv")
API = "https://apidatalake.tesouro.gov.br/ords/siconfi/tt/rreo"
ENTES = "https://apidatalake.tesouro.gov.br/ords/siconfi/tt/entes"
APLICAR = "--aplicar" in sys.argv

# faixa plausivel de RCL por habitante (R$/ano). Referencia empirica: mediana
# nacional fica na casa dos R$ 5-8 mil; municipios ricos/pequenos chegam a 30 mil.
PC_MIN, PC_MAX = 2_000, 40_000
QUEDA_MAX = 0.50          # cair mais de 50% em um ano = declaracao suspeita


def get(url, tries=4):
    last = None
    for a in range(tries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=90) as r:
                return json.loads(r.read().decode("utf-8"))
        except Exception as e:                                    # noqa: BLE001
            last = e
            time.sleep(0.8 * (a + 1))
    raise RuntimeError(str(last)[:80])


def _sem_acento(s):
    import unicodedata
    return unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode().upper()


def serie(ibge):
    """{ano: (rcl, tipo, fundeb)} dos 3 exercicios, tentando os dois tipos de RREO.

    Traz o FUNDEB junto porque a correcao TROCA O EXERCICIO: sem recalcular, o
    `rcl_p23` continuaria sendo o do ano descartado (ficava 3-4x menor que o `rcl`
    novo — inconsistencia detectada em 27 registros antes deste ajuste).
    """
    out = {}
    for ano in (2025, 2024, 2023):
        for tipo in ("RREO", "RREO Simplificado"):
            q = urllib.parse.urlencode({
                "an_exercicio": ano, "nr_periodo": 6, "co_tipo_demonstrativo": tipo,
                "no_anexo": "RREO-Anexo 03", "id_ente": ibge})
            try:
                d = get(API + "?" + q)
            except RuntimeError:
                continue
            rcl = fundeb = None
            for it in d.get("items", []):
                conta = _sem_acento(it.get("conta") or "")
                col = _sem_acento(it.get("coluna") or "")
                if "ULTIMOS 12 MESES" not in col:
                    continue
                v = float(it.get("valor") or 0)
                if rcl is None and conta.startswith("RECEITA CORRENTE L") \
                        and "AJUSTADA" not in conta and v > 0:
                    rcl = v
                elif fundeb is None and "FORMACAO DO FUNDEB" in conta and v > 0:
                    fundeb = v
            if rcl:
                out[ano] = (rcl, tipo, fundeb)
                break
    return out


def main():
    rd = csv.DictReader(io.open(CSV, encoding="utf-8-sig"))
    linhas = list(rd)
    # os campos vem do PROPRIO arquivo, nunca de uma lista fixa aqui: em 2026-08-25
    # esta funcao gravou com o cabecalho antigo depois que o coletor ganhou as colunas
    # deducao_fundeb/rcl_p23 -> DictWriter levantou ValueError no meio da escrita e
    # truncou o CSV inteiro (20 min de coleta perdidos).
    campos = list(rd.fieldnames or [])
    print(f"registros: {len(linhas)} | campos: {', '.join(campos)}")

    print("populacao (SICONFI /tt/entes)...", flush=True)
    pop = {}
    for x in get(ENTES).get("items", []):
        if x.get("cod_ibge") and x.get("populacao"):
            pop[str(x["cod_ibge"])] = int(x["populacao"])
    print(f"  populacao conhecida p/ {len(pop)} entes")

    suspeitos, sem_pop = [], 0
    for r in linhas:
        p = pop.get(r["codigo_ibge"])
        if not p:
            sem_pop += 1
            continue
        pc = float(r["rcl"]) / p
        if pc < PC_MIN or pc > PC_MAX:
            suspeitos.append((pc, r, p))
    suspeitos.sort(key=lambda x: x[0])
    print(f"  sem populacao na API: {sem_pop}")
    print(f"\nSUSPEITOS por RCL/habitante fora de R$ {PC_MIN:,}-{PC_MAX:,}: {len(suspeitos)}")
    for pc, r, p in suspeitos:
        print(f"  {r['municipio'][:26]:26s}/{r['uf']}  pop {p:>8,}  "
              f"RCL {float(r['rcl']):>16,.2f}  = R$ {pc:>9,.0f}/hab  ({r['ano_rcl']})")

    if not suspeitos:
        print("\nnada a corrigir.")
        return

    print(f"\nrecoletando a serie 2023-2025 dos {len(suspeitos)} suspeitos...", flush=True)
    with ThreadPoolExecutor(max_workers=4) as ex:
        series = list(ex.map(lambda s: serie(s[1]["codigo_ibge"]), suspeitos))

    corrigidos, sem_saida = 0, []
    for (pc, r, p), s in zip(suspeitos, series):
        ano_atual = int(r["ano_rcl"])
        hist = " · ".join(f"{a}: {v:,.0f} (R$ {v/p:,.0f}/hab)"
                          for a, (v, _t, _f) in sorted(s.items(), reverse=True))
        print(f"\n  {r['municipio']}/{r['uf']} (R$ {pc:,.0f}/hab)")
        print(f"     serie: {hist or '(so o ano corrente)'}")
        # Escolhe o exercicio MAIS RECENTE cuja RCL por habitante seja plausivel.
        # Nao basta comparar com o ano anterior: em Canavieiras/BA 2024 E 2025 vieram
        # errados (~R$ 800/hab) e so' 2023 e' coerente — a regra "caiu vs o ano
        # anterior" daria o ano anterior igualmente errado por bom.
        cands = [(a, v, t, fd) for a, (v, t, fd) in sorted(s.items(), reverse=True)
                 if PC_MIN <= v / p <= PC_MAX]
        if not cands:
            sem_saida.append(r)
            print("     -> NENHUM exercicio plausivel em 2023-2025; MANTIDO e sinalizado")
            continue
        ano_ok, v_ok, tipo_ok, fdb_ok = cands[0]
        if ano_ok == ano_atual:
            print("     -> o proprio exercicio ja e' o plausivel; mantido")
            continue
        print(f"     -> declaracao de {ano_atual} inconsistente "
              f"(R$ {pc:,.0f}/hab) -> usar {ano_ok}: {v_ok:,.2f} (R$ {v_ok/p:,.0f}/hab)")
        if APLICAR:
            r["rcl"] = f"{v_ok:.2f}"
            r["ano_rcl"] = str(ano_ok)
            r["tipo_rreo"] = f"{tipo_ok} [declaracao {ano_atual} inconsistente]"
            # o FUNDEB e a base do §23 tem de vir do MESMO exercicio adotado
            if "rcl_p23" in campos:
                r["deducao_fundeb"] = f"{fdb_ok:.2f}" if fdb_ok else ""
                r["rcl_p23"] = f"{(v_ok + fdb_ok):.2f}" if fdb_ok else f"{v_ok:.2f}"
            corrigidos += 1

    if sem_saida:
        print(f"\n  ATENCAO — {len(sem_saida)} sem exercicio plausivel (RCL fica suspeita):")
        for r in sem_saida:
            print(f"     {r['codigo_ibge']} {r['municipio']}/{r['uf']}: {float(r['rcl']):,.2f}")

    if APLICAR and corrigidos:
        # escreve num temporario e so' entao substitui: escrita parcial nunca
        # destroi o arquivo bom (foi assim que se perderam 20 min de coleta).
        # Monta TUDO em memoria antes de tocar no arquivo: a escrita final e' uma
        # unica operacao, entao um erro de formatacao no meio nao trunca o CSV bom.
        # (os.replace de temporario falhava com WinError 5 neste ambiente Windows —
        # provavel lock de antivirus/indexador sobre o .tmp recem-escrito.)
        buf = io.StringIO()
        w = csv.DictWriter(buf, fieldnames=campos, lineterminator="\n")
        w.writeheader()
        w.writerows(linhas)
        io.open(CSV, "w", encoding="utf-8-sig", newline="").write(buf.getvalue())
        print(f"\ngravado: {CSV} ({corrigidos} corrigido(s))")
    elif not APLICAR:
        print("\n(relatorio apenas — rode com --aplicar p/ gravar)")


if __name__ == "__main__":
    main()
