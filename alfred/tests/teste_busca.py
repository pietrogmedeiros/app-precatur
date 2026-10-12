# -*- coding: utf-8 -*-
"""Testes de regressao da busca por nome (credor_norm + FTS5 trigram).

  python scripts/teste_busca.py

Rodar depois de mexer em alfred_core.py (busca/conta/busca_pagina/_where_credor),
db_build.py (schema/carga), credor_norm.py ou nos enriquece_credor*.py.

O criterio de "certo" e' um ORACULO: a definicao direta da busca -- credor nao nulo
e, para cada palavra do termo, SEM_ACENTO(credor) LIKE '%palavra%' --, calculada por
varredura. O caminho rapido (FTS + LIKE em credor_norm) tem que devolver exatamente
o mesmo conjunto, com total, paginacao e ordem coerentes. Em tres camadas:
  1. banco sintetico em memoria (SCHEMA real do db_build): semantica, termos curtos,
     caracteres especiais, borda de pagina com empate, credor nulo e o caminho antigo
     (banco sem credor_fts) -- nao depende de nenhum dado coletado
  2. controle negativo: os enriquece() REAIS (Callix e DJEN) sobre o banco sintetico,
     com e sem a sincronizacao -- sem ela o nome novo nao pode ser achavel
  3. banco real (data/alfred.db): invariantes de sincronia + termos conferidos
     contra o oraculo (os 8 da investigacao de 2026-09-29 + bordas)
"""
import glob
import importlib.util
import os
import pathlib
import re
import sqlite3
import sys

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

BASE = os.environ.get("ALFRED_BASE") or str(pathlib.Path(__file__).resolve().parents[1])


def _carrega(nome, arquivo):
    spec = importlib.util.spec_from_file_location(nome, os.path.join(BASE, "scripts", arquivo))
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


core = _carrega("alfred_core", "alfred_core.py")
B = _carrega("db_build", "db_build.py")
CN = core.CN
LIM = 50

falhas = []


def check(nome, obtido, esperado):
    ok = obtido == esperado
    print(f"  {'ok  ' if ok else 'FALHA'} {nome}: {obtido}" + ("" if ok else f"  (esperado {esperado})"))
    if not ok:
        falhas.append(nome)


def oraculo(cx, termo):
    """Ids que DEVEM casar: credor nao nulo e cada palavra contida, sem acento."""
    ws = [w for w in re.split(r"\s+", core._sem_acento(termo).strip()) if w]
    if not ws:
        return set()
    w = " AND ".join("SEM_ACENTO(credor) LIKE ?" for _ in ws)
    return {r[0] for r in cx.execute(f"SELECT id FROM precatorio_atual WHERE credor IS NOT NULL AND {w}",
                                     [f"%{x}%" for x in ws])}


def ids_do_criterio(cx, termo):
    w, p, _, _ = core._criterio(cx, termo)
    return {r[0] for r in cx.execute(f"SELECT id FROM precatorio_atual WHERE {w}", p)}


def todas_paginas(cx, termo, ordem="valor", lim=LIM):
    """Percorre busca_pagina() ate' a primeira pagina vazia. Devolve (ids em ordem,
    totais vistos em cada pagina, inclusive a vazia)."""
    ids, totais, k = [], [], 0
    while True:
        rs, _, tot = core.busca_pagina(cx, termo, lim, k * lim, ordem)
        totais.append(tot)
        if not rs:
            return ids, totais
        ids += [r["id"] for r in rs]
        k += 1


def banco_sintetico(linhas):
    """Banco em memoria com o SCHEMA real do build. linhas: dicts com credor, valor e,
    opcionalmente, tribunal/numero/numero_eproc. Sincroniza credor_norm/FTS como a carga."""
    cx = sqlite3.connect(":memory:")
    cx.row_factory = sqlite3.Row
    cx.create_function("SEM_ACENTO", 1, core._sem_acento, deterministic=True)
    cx.executescript(B.SCHEMA)
    cx.execute("INSERT INTO coleta (id,tribunal,arquivo,coletado_em,carregado_em,n_registros) "
               "VALUES (1,'TJXX','sintetico.json','2026-01-01','2026-01-01',0)")
    B.materializa_coleta_atual(cx)
    cx.executemany(
        "INSERT INTO precatorio (coleta_id,tribunal,ordem,credor,valor,numero,numero_eproc) "
        "VALUES (1,?,?,?,?,?,?)",
        [(l.get("tribunal", "TJXX"), i + 1, l.get("credor"), l.get("valor", 1.0),
          l.get("numero"), l.get("numero_eproc")) for i, l in enumerate(linhas)])
    CN.sincroniza(cx)
    return cx


# ---------------------------------------------------------------- 1. sintetico
print("\n[1] banco sintetico — semantica da busca")
LINHAS = ([{"credor": "José Sátiro da Silva", "valor": 300.0},
           {"credor": "MARIA DA SILVA", "valor": 200.0},
           {"credor": "Silvana Souza", "valor": 150.0},        # 'silva' tem que achar SILVANA
           {"credor": 'Ana O"Brien', "valor": 120.0},           # aspas dentro do nome
           {"credor": "Pedro D'Ávila", "valor": 110.0},         # apostrofo + acento
           {"credor": "Jo Li", "valor": 90.0},                  # palavras < 3 letras
           {"credor": "Nilza Calatrone", "valor": 80.0},
           {"credor": None}, {"credor": None}, {"credor": None}]  # TJRJ/PE/GO: sem nome
          + [{"credor": "Fulano Borda", "valor": 10.0} for _ in range(LIM + 1)])  # 51 empatados
cx = banco_sintetico(LINHAS)
N_COM_NOME = sum(1 for l in LINHAS if l["credor"])

ESPERADO = {"silva": 3, "sátiro": 1, "maria silva": 1, "nilza calatrone": 1,
            "jo li": 1,                     # so' palavras curtas (sem trigrama)
            'o"brien': 1, "d'avila": 1,     # aspas / apostrofo
            "sil_a": 3,                     # '_' continua curinga do LIKE
            "silva OR santos": 0,           # OR digitado e' texto, nao operador do FTS
            "(silva)": 0, "silva*": 0,      # parenteses / asterisco idem
            "xyzqwkj": 0,                   # sem resultado
            "%": N_COM_NOME,                # so' '%': todo credor COM nome, nunca os nulos
            "fulano borda": LIM + 1}
for termo, n in ESPERADO.items():
    got = ids_do_criterio(cx, termo)
    check(f"{termo!r}: conjunto = oraculo", got == oraculo(cx, termo), True)
    rs, _, tot = core.busca_pagina(cx, termo)
    check(f"{termo!r}: total", (tot, core.conta(cx, termo)), (n, n))

# borda de pagina: 51 itens com o MESMO valor -> sem o desempate por id, o
# LIMIT/OFFSET podia repetir um na pagina 2 e pular outro
for ordem in ("valor", "nome"):
    ids, totais = todas_paginas(cx, "fulano borda", ordem)
    check(f"borda ({ordem}): 51 itens, nenhum repetido", (len(ids), len(set(ids))), (LIM + 1, LIM + 1))
    check(f"borda ({ordem}): empate sai em ordem de id", ids == sorted(ids), True)
    check(f"borda ({ordem}): total em cada pagina (a 3a vazia usa conta())", totais, [LIM + 1] * 3)
rs1, _ = core.busca(cx, "fulano borda", LIM, 0)
rp1, _, _ = core.busca_pagina(cx, "fulano borda", LIM, 0)
check("busca() e busca_pagina() devolvem a mesma pagina", [r["id"] for r in rs1], [r["id"] for r in rp1])
check("ordem por valor: maior primeiro", [r["credor"] for r in core.busca(cx, "silva")[0]],
      ["José Sátiro da Silva", "MARIA DA SILVA", "Silvana Souza"])

# duas sincronizacoes na MESMA transacao (ex.: os dois enriquecimentos sem commit entre
# eles). Regressao: registrar funcao SQL com escrita pendente no FTS5 falhava.
try:
    CN.sincroniza(cx, [1, 2])
    CN.sincroniza(cx, [3])
    check("duas sincronizacoes seguidas sem commit", "ok", "ok")
except sqlite3.OperationalError as e:
    check("duas sincronizacoes seguidas sem commit", str(e), "ok")
check("... e a busca continua igual ao oraculo", ids_do_criterio(cx, "silva") == oraculo(cx, "silva"), True)

# banco anterior ao credor_fts: cai no caminho antigo (SEM_ACENTO linha a linha), com o
# mesmo resultado -- o codigo novo pode chegar 'a VM antes do banco novo
cx.execute("DROP TABLE credor_fts")
check("sem credor_fts -> caminho antigo", CN.existe(cx), False)
for termo, n in ESPERADO.items():
    if termo == "%":
        continue      # caminho antigo: SEM_ACENTO(NULL) = '' casa '%' -> inclui os nulos (comportamento de sempre)
    check(f"caminho antigo {termo!r}: conjunto = oraculo", ids_do_criterio(cx, termo) == oraculo(cx, termo), True)
check("caminho antigo '%': inclui os sem nome (como antes)", core.conta(cx, "%"), len(LINHAS))
cx.close()

# ---------------------------------------------------- 2. controle negativo (enriquece)
print("\n[2] enriquecimentos reais: sem sincronizacao o nome novo nao e' achavel")


def controle(rotulo, E, linha, termo):
    for sync in (False, True):
        cx = banco_sintetico([linha])
        original = E.CN.sincroniza
        if not sync:
            E.CN.sincroniza = lambda cx, ids=None: 0          # = comentar a linha no script
        try:
            E.enriquece(cx)
        finally:
            E.CN.sincroniza = original
        achou = core.conta(cx, termo) == 1
        check(f"{rotulo} {'COM' if sync else 'SEM'} sincronizacao -> acha {termo!r}", achou, sync)
        cx.close()


def palavras_longas(nome):
    return [w for w in re.split(r"[\s;]+", nome) if len(w) >= 4]


# Pula (sem falhar) onde o enriquecimento nao roda: sem os arquivos de origem ou sem
# pandas p/ ler o xlsx do Callix -- caso da VM, que so' serve a API e recebe o banco
# ja enriquecido. O mesmo criterio do enriquece(), que tambem so' roda com os arquivos.
E = _carrega("enriquece_credor", "enriquece_credor.py")
if not glob.glob(os.path.join(E.DIR, "*.xlsx")):
    print(f"  pulado (Callix): sem arquivos em {E.DIR}")
else:
    try:
        por_eproc, _ = E._carrega_nomes()
    except ImportError as e:
        print(f"  pulado (Callix): {e}")
    else:
        for ep, (nome, _) in por_eproc.items():        # um nome real do Callix + a mascara do TJMG
            ws, ini = palavras_longas(nome), E._iniciais(nome)
            mascara = ".".join(ini) + "."
            if len(ws) >= 2 and len(ini) >= 2 and E._e_mascara(mascara) and E._alvo_iniciais(mascara) == ini:
                controle("Callix", E, {"credor": mascara, "tribunal": "TJMG", "numero_eproc": ep},
                         f"{ws[0]} {ws[-1]}".lower())
                break
        else:
            check("Callix: achou nome p/ o teste", False, True)

ED = _carrega("enriquece_credor_djen", "enriquece_credor_djen.py")
if not glob.glob(os.path.join(ED.DIR, "*.jsonl")):
    print(f"  pulado (DJEN): sem arquivos em {ED.DIR}")
else:
    for numero, (credor, _) in ED._carrega_cache().items():   # um nome real do DJEN, credor nulo na fila
        ws = palavras_longas(credor)
        if len(ws) >= 2:
            controle("DJEN", ED, {"credor": None, "numero": numero}, f"{ws[0]} {ws[-1]}".lower())
            break
    else:
        check("DJEN: achou nome p/ o teste", False, True)

# ---------------------------------------------------------------- 3. banco real
print("\n[3] banco real (data/alfred.db)")
if not os.path.exists(core.DB):
    print(f"  pulado: {core.DB} nao existe (rode scripts/db_build.py)")
else:
    cx = core.conecta()
    if not CN.existe(cx):
        check("banco com credor_fts (rode scripts/db_build.py)", False, True)
    else:
        q = lambda s: cx.execute(s).fetchone()[0]
        n_credor = q("SELECT COUNT(*) FROM precatorio WHERE credor IS NOT NULL")
        check("credor_norm preenchido onde ha credor",
              q("SELECT COUNT(*) FROM precatorio WHERE credor_norm IS NOT NULL"), n_credor)
        check("credor_norm = normaliza(credor)",
              q("SELECT COUNT(*) FROM precatorio WHERE credor IS NOT NULL "
                "AND credor_norm IS NOT SEM_ACENTO(credor)"), 0)
        check("credor_fts: uma linha por credor", q("SELECT COUNT(*) FROM credor_fts"), n_credor)
        check("credor_fts: mesmo texto de credor_norm",
              q("SELECT COUNT(*) FROM credor_fts f JOIN precatorio p ON p.id = f.rowid "
                "WHERE f.credor_norm IS NOT p.credor_norm"), 0)
        for termo in ["maria silva", "silva", "sátiro", "nilza calatrone", "jose", "de souza", "ana",
                      "joão da silva",                              # os 8 da investigacao
                      "jo", 'o"brien', "d'avila", "sil_a", "xyzqwkj"]:  # curto, especiais, vazio
            esperado = oraculo(cx, termo)
            rs, _, tot = core.busca_pagina(cx, termo)
            # valor DESC do SQLite poe NULL por ultimo; empate desfeito por id
            chaves = [(r["valor"] is None, -(r["valor"] or 0), r["id"]) for r in rs]
            check(f"{termo!r}: conjunto = oraculo, total = conta()",
                  (ids_do_criterio(cx, termo) == esperado, tot, core.conta(cx, termo)),
                  (True, len(esperado), len(esperado)))
            check(f"{termo!r}: 1a pagina em (valor DESC, id)", chaves == sorted(chaves), True)
    cx.close()

# ---------------------------------------------------------------- veredito
print("\n" + "=" * 62)
if falhas:
    print(f"{len(falhas)} FALHA(S): " + ", ".join(falhas))
    sys.exit(1)
print("todos os testes passaram")
