# -*- coding: utf-8 -*-
"""Testes de regressao do modelo unico (scripts/modelo_p23.py).

  python scripts/teste_modelo_p23.py

Trava o comportamento contra CASOS JA CONFERIDOS A MAO nesta ordem de forca:
  1. sinteticos    — a norma isolada (§20 e §5o), sem depender de coleta
  2. Vila Velha/ES — proj20 com DOIS superprecatorios consumindo metade do orcamento
  3. Paraguacu/SP  — regime especial, banda de cenarios, fila sem superprecatorio
  4. Cariacica/ES  — o caso do parecer Orly (superpreferencia + saldo, 3 justicas)

Os numeros esperados sao os que ja tinham sido validados na conferencia manual e
publicados nos pareceres. Se um deles quebrar, ou a norma mudou (e o esperado
precisa ser reescrito CONSCIENTEMENTE) ou o modelo regrediu.
"""
import importlib.util
import json
import os
import pathlib
import sys

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

# BASE resolvido a partir do proprio arquivo: funciona no Windows e na VM Linux.
# ALFRED_BASE sobrepoe quando o codigo roda de outro lugar.
BASE = os.environ.get("ALFRED_BASE") or str(pathlib.Path(__file__).resolve().parents[1])
spec = importlib.util.spec_from_file_location("m", os.path.join(BASE, "scripts", "modelo_p23.py"))
M = importlib.util.module_from_spec(spec)
spec.loader.exec_module(M)

falhas = []


def check(nome, obtido, esperado, tol=0.01):
    ok = (abs(obtido - esperado) <= tol) if isinstance(esperado, (int, float)) and \
         isinstance(obtido, (int, float)) else (obtido == esperado)
    print(f"  {'ok  ' if ok else 'FALHA'} {nome}: {obtido}" + ("" if ok else f"  (esperado {esperado})"))
    if not ok:
        falhas.append(nome)


# ---------------------------------------------------------------- 1. sinteticos
print("\n[1] regra isolada — sinteticos")

# §20: um precatorio > 15% do total do ano vira superprecatorio e sai da fila
fila = [{"pos": 1, "ano": 2026, "val": 800.0}] + \
       [{"pos": i, "ano": 2026, "val": 100.0} for i in range(2, 12)]
n, v = M.marca_superprecatorios(fila, minimo=0)      # minimo=0 p/ isolar o limiar
check("§20 identifica 1 superprecatorio", n, 1)
check("§20 valor do superprecatorio", v, 800.0)

# MATERIAL_MIN_SP evita classificar valor pequeno como grande vulto
fila2 = [dict(f) for f in fila]
n2, _ = M.marca_superprecatorios(fila2)              # minimo padrao = R$ 1 mi
check("piso de materialidade descarta o falso positivo", n2, 0)

# §5o: precatorio de exercicio futuro nao e' pago antes do seu ano
fila3 = [{"pos": 1, "ano": 2028, "val": 10.0}]
M.proj20(fila3, orcamento=1_000_000, ano_base=2026)
check("§5o respeita o ano-orcamento futuro", fila3[0]["ano_previsto"], 2028)

# escada do §23 — incisos I a IX da EC 136/2025, conferidos no texto do Planalto
# (2026-08-25). Cortes de 10 em 10 a partir de 15%; NOVE faixas, teto 5%.
# A tabela anterior (cortes 24/33/42/51, teto 3,5%) estava errada nos dois eixos.
check("escada 1,0% ate 15% de mora/RCL", M.escada_p23(13.33), 1.0)
check("escada 1,5% acima de 15%", M.escada_p23(16.48), 1.5)
check("escada 1,5% ainda em 25,0% (borda)", M.escada_p23(25.0), 1.5)
check("escada 2,0% logo acima de 25%", M.escada_p23(25.01), 2.0)
check("escada 2,0% em 33,2%", M.escada_p23(33.2), 2.0)
check("escada 2,5% acima de 35%", M.escada_p23(35.96), 2.5)   # Jequie pela RCL do TJBA
check("escada 3,5% acima de 55%", M.escada_p23(60.0), 3.5)
check("escada 4,0% acima de 65%", M.escada_p23(70.0), 4.0)
check("escada 4,5% acima de 75%", M.escada_p23(79.0), 4.5)    # TJPR: Porecatu 78,58%
check("escada 5,0% (teto) acima de 85%", M.escada_p23(92.0), 5.0)

# ---------------------------------------------------------------- fixture ES
# Fila combinada (Vila Velha / Cariacica) CONGELADA em data/fixtures_teste/cortes_es.json,
# recortada do antigo dados_dashboard.json. O dashboard foi aposentado; este fixture guarda
# os casos ja conferidos a mao. A MESMA ordem por data de apresentacao esta no banco
# (alfred_core._merge_por_apresentacao) — verificado identico.
D = json.load(open(os.path.join(BASE, "data", "fixtures_teste", "cortes_es.json"), encoding="utf-8"))


def fila_es(ibge):
    c = D["cortes"][ibge]
    return c, list(c["fila_tjes"])


# ---------------------------------------------------------------- 2. Vila Velha
print("\n[2] Vila Velha/ES — dois superprecatorios (conferido a mao em 10/08/2026)")
c, fila = fila_es("3205200")
orc = c["trib"]["TJES"]["orcamento"]
n, v = M.marca_superprecatorios(fila)
check("n superprecatorios", n, 2)
check("valor em superprecatorios", round(v, 2), 63_147_544.20)
r = M.proj20(fila, orc, 2026)
check("reserva do §20 em 2026", round(r["reservado"][2026], 2), 9_472_131.63)
check("reserva do §20 em 2027", round(r["reservado"][2027], 2), 10_735_082.51)
check("fila normal zera em", r["zera"], 2033)
check("parcelas do §20 terminam em", r["zera_sp"], 2031)
alvo = next(f for f in fila if str(f.get("num", "")).replace("-", "").replace(".", "")
            == "00037628820248080000")
check("precatorio 0003762-88 previsto para", alvo["ano_previsto"], 2027)
check("acumulado normal a frente dele", M.acumulado_ate(fila, alvo), 19_026_690.04)

# ---------------------------------------------------------------- 3. Paraguacu
print("\n[3] Paraguacu Paulista/SP — regime especial, banda ancorada no teto")
# Paraguacu paga ACIMA do teto (R$ 16,65 mi vs teto R$ 4,05 mi). Ate 20/08/2026 o
# modelo punha o OBSERVADO no cenario central -- valido PRE-EC 136 (RE pagavam acima
# do teto p/ cumprir 2029). A EC 136/2025 estendeu o TETO do §23 aos RE (art. 101 §6
# ADCT): o orcamento legal passou a ser o teto para OS DOIS regimes, e o pago virou
# contraponto (ritmo observado), nao a banda. (Bug irmao: no Estado de MG, que paga
# ABAIXO do teto, o card "teto legal" chegava a exibir o valor pago.)
dp = json.load(open(os.path.join(BASE, "output", "parecer_paraguacu_dados.json"), encoding="utf-8"))
cen = M.projecao_cenarios(dp["rcl"], dp["mora"], "Especial", pago_cnj=dp["pago_cnj_2025"])
check("mora/RCL", round(cen["prop_mora"], 2), 16.48)
check("degrau do §23 (independe da fonte)", cen["pct_p23"], 1.5)
check("orcamento legal e' o teto (nao o pago)", cen["fonte"], "teto_p23")
check("teto anual do §23", cen["teto_p23"], 4_046_758.52)
check("cenario conservador (teto x0,8)", cen["conservador"], 3_237_406.82)
check("cenario central (o proprio teto)", cen["central"], 4_046_758.52)
check("cenario otimista (teto x1,2)", cen["otimista"], 4_856_110.22)
a0 = dp["alvos"][0]
# ATENCAO: ate 10/08/2026 estes esperados eram 2.0 e 8.3 anos. Estavam ERRADOS —
# vinham do acumulado BRUTO (R$ 33,71 mi), que contava o precatorio de ordem 177
# (R$ 17,15 mi = 52,5% do exercicio 2023) como se disputasse a fila. Ele e'
# superprecatorio do §20 e sai por fora. Com a regra aplicada o acumulado cai para
# R$ 16,56 mi. Os valores abaixo sao os corretos.
check("acumulado sem §20 ate a 178a ordem", a0["acum"], 16_563_202.96)
check("acumulado bruto (so p/ conferencia)", a0["acum_bruto"], 33_714_954.92)
# PELO TETO (a projecao legal) leva 4,1 anos; NO RITMO PAGO (o que o ente vem
# pagando, acima do teto) leva 1,0 ano -- e' o contraponto do bloco ritmo_observado.
check("anos ate a 178a ordem PELO TETO (central)", M.anos_ate(a0["acum"], cen["central"]), 4.1)
check("anos ate a 178a ordem NO RITMO PAGO", M.anos_ate(a0["acum"], dp["pago_cnj_2025"]), 1.0)

# ---------------------------------------------------------------- 4. Cariacica
print("\n[4] Cariacica/ES — caso do parecer Orly")
do = json.load(open(os.path.join(BASE, "output", "parecer_orly_dados.json"), encoding="utf-8"))
c, fila = fila_es("3201308")
orc = c["trib"]["TJES"]["orcamento"]
M.proj20(fila, orc, 2026)
sup = next(f for f in fila if f.get("mpos") == 22)
sal = next(f for f in fila if f.get("mpos") == 46)
check("fatia preferencial (ordem 22) prevista para", sup["ano_previsto"], 2027)
check("saldo (ordem 46) previsto para", sal["ano_previsto"], 2028)
check("previsoes batem com o parecer publicado",
      [sup["ano_previsto"], sal["ano_previsto"]],
      [do["alvos"][0]["ano_prev"], do["alvos"][1]["ano_prev"]])

# ------------------------------------------- 5. valor oficial x plano do exercicio
# Regressao da armadilha de 2026-08-25: o `valor_anual` do Comite Gestor so' revela o
# TETO quando a mora e' maior que ele (plano capado). Quando o plano vem IGUAL a mora,
# e' o desembolso do exercicio — usa-lo como orcamento perpetuo projetava 2098.
print("\n[5] valor oficial do tribunal x plano do exercicio")
# (a) plano CAPADO pelo teto: mora 10,38 mi > teto 1,50 mi -> vale o valor publicado
b = M.orcamento_anual(150_313_543.75, 10_382_446.65, "Comum",
                      pct_oficial=1.0, valor_oficial=1_435_336.47)
check("plano capado -> usa o valor do tribunal", b["valor"], 1_435_336.47)
check("plano capado -> fonte", b["fonte"], "oficial_valor")
# (b) plano = mora (ente em dia): NAO limita os anos seguintes -> segue no teto
b = M.orcamento_anual(90_779_185.58, 804_061.01, "Comum",
                      pct_oficial=1.0, valor_oficial=804_061.01)
check("plano = mora -> ignora o valor e usa o teto", b["valor"], 907_791.86)
check("plano = mora -> fonte", b["fonte"], "oficial")
# (c) sem valor oficial: comportamento historico intacto
b = M.orcamento_anual(90_779_185.58, 804_061.01, "Comum", pct_oficial=1.0)
check("sem valor oficial -> teto de sempre", b["valor"], 907_791.86)

# ---------------------------------------------------------------- veredito
print("\n" + "=" * 62)
if falhas:
    print(f"{len(falhas)} FALHA(S): " + ", ".join(falhas))
    sys.exit(1)
print("todos os testes passaram")
