# -*- coding: utf-8 -*-
"""Mapa Anual de Precatorios do CNJ -> tabela `mapa_cnj` do data/alfred.db.

  python scripts/db_mapa.py             # (re)carrega a tabela no banco existente
  python scripts/db_mapa.py --resumo    # o que ja esta carregado
  python scripts/db_mapa.py --ibge 3201605

A fonte e' data/cnj_mapa_anual_raw.csv, extraido do painel Qlik pelo
scripts/extrair_cnj_mapa_anual.py. Este modulo so carrega e interpreta.

------------------------------------------------------------------------------
POR QUE UMA TABELA PROPRIA, E NAO COLUNAS EM `municipio`

O grao do Mapa e' (ano_ref, ente, tribunal) — nao municipio. Achatar em
`municipio.pago_total` perde o TRIBUNAL, e e' exatamente essa perda que engana:
Conceicao da Barra/ES (3201605) em 2025 pagou 100% do que devia ao TJES e ao
TRT17 (saldo zero nos dois) e ZERO ao TRF2, onde deve R$ 13,7 mi. Somado num
numero so, o municipio parece "pagar pouco"; aberto por tribunal, ele e' bom
pagador estadual e inadimplente federal — duas conclusoes opostas sobre a mesma
fila. Com `ano_ref` na tabela, o ano-ref 2026 entra ao lado do 2025 (serie
historica) em vez de sobrescrever.

O MAPA NAO E' A FILA. Sao dados de naturezas diferentes e nenhum corrige o outro:

    LUP / lista cronologica          Mapa Anual CNJ
    fila oficial, atualizada         declaracao do tribunal, anual e defasada
    manda em ORDEM e VALOR           manda em PAGAMENTO e COBERTURA
    7 tribunais no Alfred            59 tribunais, 5.151 municipios

Divergir e' o comportamento esperado: no mesmo municipio o Mapa diz saldo TJES
= 0 (posicao de 31/12/2025) e a LUP mostra R$ 1,97 mi de fila (orcamento 2026,
expedida em 2025). Os dois estao certos. Por isso a carga nunca sobrescreve
precatorio nem ente — so acrescenta.

------------------------------------------------------------------------------
O QUE O "SALDO DEVEDOR" DO CNJ SIGNIFICA (verificado, nao suposto)

Testado sobre as 12.234 linhas:
    saldo == anterior - pago            -> erro relativo mediano  4,4%
    saldo == anterior - pago + expedido -> erro relativo mediano 28,9%
A primeira identidade fecha (o residuo de 4,4% e' correcao monetaria). Ou seja:
o SALDO e' o que sobrou do estoque que ja existia; os EXPEDIDOS no ano sao
divida nova, que ainda nao venceu e por isso nao entra nele. Consequencia
pratica — e' o que justifica este modulo:

    pago / anterior  =  quanto do estoque vencido o ente liquidou no ano
    saldo / pago     =  anos para zerar o estoque no ritmo atual

CAVEAT ja conhecido (memoria [[al-tjal-regime-precatorios]]): "pago = 0" NAO e'
sinonimo de calote. Pode ser fila zerada. Por isso classifica() so devolve
'nao_pagou' quando ha saldo remanescente — sem saldo, o codigo e' 'sem_divida'.
"""
import argparse
import csv
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
DB = os.path.join(BASE, "data", "alfred.db")
CSV_RAW = os.path.join(BASE, "data", "cnj_mapa_anual_raw.csv")
# anos anteriores do TJMG (PDFs do proprio tribunal; ver db_build.carrega_historico_tjmg)
HIST_TJMG_CSV = os.path.join(BASE, "data", "mapa_anual_tjmg_historico.csv")

SCHEMA = """
DROP VIEW  IF EXISTS mapa_ente;
DROP TABLE IF EXISTS mapa_cnj;

CREATE TABLE mapa_cnj (
  prec_id          INTEGER PRIMARY KEY,   -- PREC_id do CNJ: unico, rastreia a fonte
  envio_id         INTEGER,
  ano_ref          INTEGER NOT NULL,
  tribunal         TEXT NOT NULL,
  ramo             TEXT,                  -- Estadual | Trabalho | Federal | ...
  uf               TEXT,
  esfera           TEXT,                  -- Municipal | Estadual | Federal
  tipo_entidade    TEXT,                  -- Direta | Indireta
  ibge             TEXT,                  -- so para esfera Municipal
  ente_nome        TEXT,
  cnpj             TEXT,
  regime           TEXT,                  -- Comum | Especial
  vlr_ano_anterior REAL,                  -- estoque na abertura do ano-ref
  vlr_pago         REAL,                  -- pago durante o ano-ref
  vlr_saldo        REAL,                  -- estoque no fechamento (= anterior - pago)
  vlr_expedidos    REAL                   -- precatorios novos do ano (ainda a vencer)
);

CREATE INDEX ix_mapa_ibge ON mapa_cnj(ibge, ano_ref);
CREATE INDEX ix_mapa_trib ON mapa_cnj(tribunal, ano_ref);

-- um ente pode ter varias entidades indiretas no mesmo tribunal (Manaus tem 5 no
-- TRT11): a view agrega por (ano, municipio, tribunal, tipo) para que a consulta
-- do dia-a-dia nao precise repetir esse GROUP BY.
CREATE VIEW mapa_ente AS
SELECT ano_ref, ibge, uf, tribunal, ramo, tipo_entidade,
       COUNT(*)                                        AS n_entidades,
       MAX(CASE WHEN regime='Especial' THEN 1 ELSE 0 END) AS tem_especial,
       SUM(vlr_ano_anterior)                           AS anterior,
       SUM(vlr_pago)                                   AS pago,
       SUM(vlr_saldo)                                  AS saldo,
       SUM(vlr_expedidos)                              AS expedidos
FROM mapa_cnj
WHERE ibge IS NOT NULL
GROUP BY ano_ref, ibge, tribunal, tipo_entidade;
"""

COL = {
    "prec_id": "PREC_id", "envio_id": "PREC_envio_id", "ano_ref": "PREC_DD_num_ano_referencia",
    "uf": "PREC_DD_sig_uf", "tribunal": "PREC_DD_sig_tribunal", "ramo": "PREC_DD_ramo_justica",
    "esfera": "PREC_DD_dsc_esfera_ente_devedor", "tipo": "PREC_DD_dsc_tipo_entidade_devedora",
    "nome": "PREC_DD_nom_entidade_devedora", "nome_sem": "PREC_DD_nom_entidade_devedora_semcnpj",
    "ibge": "PREC_cod_municipio", "regime": "PREC_DD_dsc_regime_pagamento",
    "anterior": "PREC_DD_vlr_montante_ano_anterior", "pago": "PREC_DD_vlr_pago_ano_referencia",
    "saldo": "PREC_DD_vlr_saldo_devedor", "expedidos": "PREC_DD_vlr_montante_expedidos_ano_referencia",
}


def _num(x):
    try:
        return float(str(x or "").strip() or 0)
    except ValueError:
        return 0.0


def _int(x):
    d = re.sub(r"\D", "", str(x or ""))
    return int(d) if d else None


def _tipo(s):
    """'Entidades da Administracao Indireta' -> Indireta; 'Administracao Direta' -> Direta.
    Testar 'Indireta' PRIMEIRO: 'Direta' e' substring de 'Indireta'."""
    t = str(s or "")
    if "ndireta" in t:
        return "Indireta"
    if "ireta" in t:
        return "Direta"
    return None


def _regime(s):
    t = str(s or "").upper()
    return "Especial" if "ESPECIAL" in t else ("Comum" if "COMUM" in t else None)


def _ente(r):
    """nom_entidade_devedora vem como 'CNPJ - NOME'; na adm direta vem ' - ' (vazio).
    Devolve (nome, cnpj) — ambos podem ser None."""
    bruto = str(r.get(COL["nome"]) or "").strip()
    m = re.match(r"^(\d{11,14})\s*-\s*(.*)$", bruto)
    if m:
        return (m.group(2).strip() or None), m.group(1)
    alt = str(r.get(COL["nome_sem"]) or "").strip()
    nome = alt if alt not in ("", "-") else (bruto if bruto not in ("", "-") else None)
    return nome, None


# codigo IBGE de 2 digitos da UF -> usado como PSEUDO-IBGE do governo estadual,
# o mesmo truque de `municipio` (ES=32, MG=31, MA=21). So' vale para as UFs em que
# o Alfred carrega a fila estadual; nas demais o Estado segue sem ibge.
# Mantido em sincronia manual com UF_ESTADO de db_build.py (ficou desatualizado
# quando BA/GO/CE/RN/AL ganharam fila estadual -- ritmo_observado do Estado ficava
# mudo nessas UFs sem ninguem perceber, ate' o caso de Alagoas em 2026-09-30).
UF_PSEUDO_IBGE = {"ES": "32", "MG": "31", "MA": "21", "SP": "35",
                  "GO": "52", "BA": "29", "CE": "23", "RN": "24", "AL": "27",
                  "RJ": "33", "MT": "51", "PB": "25", "PR": "41", "PI": "22", "AP": "16",
                  "RS": "43", "SC": "42", "TO": "17", "RR": "14", "MS": "50", "PA": "15",
                  "AM": "13", "AC": "12", "PE": "26"}


def _ibge(r):
    """PREC_cod_municipio E' o codigo IBGE de 7 digitos (conferido contra
    data/cnj_cidades.csv: 2400307 = Afonso Bezerra). Nao ha tabela de-para a
    manter — mas so vale para esfera Municipal; nas demais vem '-'.

    EXCECAO (2026-08-26): para a esfera ESTADUAL das UFs cuja fila estadual o Alfred
    carrega, devolve o PSEUDO-IBGE de 2 digitos. Sem isso o parecer de precatorio
    estadual ficava sem `ritmo_observado` — o contraponto mais importante da tela —,
    porque o pago do Estado existia no Mapa mas nao se ligava ao ente."""
    d = re.sub(r"\D", "", str(r.get(COL["ibge"]) or ""))
    if len(d) == 7:
        return d
    esfera = (r.get(COL.get("esfera", "")) or "").strip().lower()
    if esfera.startswith("estad"):
        uf = (r.get(COL.get("uf", "")) or "").strip().upper()
        return UF_PSEUDO_IBGE.get(uf)
    return None


def _historico_via_db_build():
    """Carregador dos anos anteriores quando carrega() roda FORA do db_build (python
    scripts/db_mapa.py): reusa db_build.carrega_historico_tjmg, com o indice de
    municipios montado da tabela `municipio` que ja esta no banco (e' a mesma que o
    build gravou). Import tardio porque o db_build importa este modulo.

    O IMPORT acontece aqui, e carrega() chama isto ANTES do DROP: uma dependencia do
    db_build que falte (na VM faltava enriquece_credor_djen.py) derruba a carga com a
    tabela ainda intacta, em vez de deixa-la so' com o ano corrente."""
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "db_build", os.path.join(BASE, "scripts", "db_build.py"))
    b = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(b)

    def carregar(cx):
        muns = {i: {"ibge": i, "nome": n, "uf": u}
                for i, n, u in cx.execute("SELECT ibge, nome, uf FROM municipio")}
        return b.carrega_historico_tjmg(cx, b.indice_ibge(muns))
    return carregar


def carrega(cx, caminho=CSV_RAW, historico=None):
    """(Re)cria mapa_cnj a partir do CSV cru E recarrega os anos anteriores do TJMG.
    Devolve (n_linhas, anos), contando os dois.

    CORRIGIDO em 2026-09-29 (auditoria M5): o DROP do SCHEMA apagava tambem o historico
    do TJMG (2021-2024, que o Qlik do CNJ nao retem), e so' o db_build inteiro o repunha.
    Rodar este modulo sozinho (ex.: na correcao do A1) deixava 12.234 linhas em vez de
    15.396, em silencio. Agora a carga do historico faz parte da carga, e os dois CSVs
    E o carregador do historico sao preparados ANTES do DROP: se faltar um CSV ou uma
    dependencia do db_build, nada e' apagado.

    `historico(cx) -> (n, anos, pulados)`: o db_build passa o proprio carregador (ja tem o
    indice de municipios); chamado de fora, usa _historico_via_db_build."""
    for p, como in ((caminho, "rode scripts/extrair_cnj_mapa_anual.py"),
                    (HIST_TJMG_CSV, "rode scripts/fetch_mapa_tjmg_historico.py --todos")):
        if not os.path.exists(p):
            raise FileNotFoundError(f"CSV do Mapa nao encontrado: {p} — {como} "
                                    f"(mapa_cnj NAO foi alterada)")
    historico = historico or _historico_via_db_build()
    cx.executescript(SCHEMA)
    linhas, anos = [], set()
    for r in csv.DictReader(open(caminho, encoding="utf-8-sig")):
        ano = _int(r.get(COL["ano_ref"]))
        trib = (r.get(COL["tribunal"]) or "").strip()
        if not ano or not trib:
            continue
        nome, cnpj = _ente(r)
        anos.add(ano)
        linhas.append((
            _int(r.get(COL["prec_id"])), _int(r.get(COL["envio_id"])), ano, trib,
            (r.get(COL["ramo"]) or "").strip() or None,
            (r.get(COL["uf"]) or "").strip() or None,
            (r.get(COL["esfera"]) or "").strip() or None,
            _tipo(r.get(COL["tipo"])), _ibge(r), nome, cnpj, _regime(r.get(COL["regime"])),
            _num(r.get(COL["anterior"])), _num(r.get(COL["pago"])),
            _num(r.get(COL["saldo"])), _num(r.get(COL["expedidos"])),
        ))
    cx.executemany(
        "INSERT OR REPLACE INTO mapa_cnj (prec_id,envio_id,ano_ref,tribunal,ramo,uf,esfera,"
        "tipo_entidade,ibge,ente_nome,cnpj,regime,vlr_ano_anterior,vlr_pago,vlr_saldo,"
        "vlr_expedidos) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", linhas)
    n_hist, anos_hist, pulados = historico(cx)
    if pulados:
        print(f"  mapa_cnj (historico TJMG): {pulados} linhas sem ibge (fora do escopo)")
    # Serie dos Mapas Anuais publicados pelos PROPRIOS tribunais (fetch_mapa_tribunal.py).
    # Corrigido em 05/10/2026: o DROP acima apagava essa serie e nada a recarregava -- desde
    # a troca para o db_build, todo rebuild deixava TJBA/TJAL/TJES/TJRJ so' com o ano do CNJ.
    n_trib, anos_trib, _ = carrega_tribunal(cx)
    print(f"  mapa_cnj (Mapas dos tribunais): {n_trib} linhas (anos-ref: {', '.join(map(str, anos_trib))})")
    return len(linhas) + n_hist + n_trib, sorted(anos | set(anos_hist) | set(anos_trib))


# ---------------------------------------------------------------- interpretacao
EPS = 0.005          # centavo: o CNJ publica valores ja arredondados
QUASE_TUDO = 0.90    # >=90% do estoque de abertura liquidado -> 'quitou_quase_tudo'


def classifica(anterior, pago, saldo, expedidos=0.0):
    """O ENTE ESTA PAGANDO? Resposta derivada de um ano-ref, para UM tribunal.

    codigo         significado
    sem_divida     nao devia nada e nada expediu — nao ha o que pagar
    so_expediu     nao devia no inicio do ano; a divida e' nova e ainda nao venceu
    quitou         zerou o estoque de abertura
    pagando        pagou parte; `anos_para_quitar` diz em quanto tempo zera no ritmo
    nao_pagou      tinha estoque vencido e pagou R$ 0 no ano
    """
    a, p, s, e = (_num(x) for x in (anterior, pago, saldo, expedidos))
    # taxa sobre o estoque de ABERTURA (nao sobre anterior+expedidos): o expedido no
    # ano so vence no exercicio seguinte, entao cobra-lo aqui puniria quem nao devia.
    taxa = round(p / a, 4) if a > EPS else None
    anos = round(s / p, 1) if p > EPS and s > EPS else None

    if a <= EPS and s <= EPS and p <= EPS:
        cod, txt = ("so_expediu", "sem estoque vencido; só expediu no ano") if e > EPS else \
                   ("sem_divida", "sem dívida no ano-ref")
    elif s <= EPS and p > EPS:
        cod, txt = "quitou", "quitou o estoque do ano"
    elif p <= EPS and s > EPS:
        cod, txt = "nao_pagou", "não pagou nada no ano"
    elif p > EPS:
        cod = "quitou" if (taxa is not None and taxa >= 1) else "pagando"
        if cod == "pagando" and taxa is not None and taxa >= QUASE_TUDO:
            cod = "quitou_quase_tudo"
        txt = (f"pagou {taxa:.0%} do estoque de abertura" if taxa is not None
               else "pagou sem estoque de abertura declarado")
        if anos:
            txt += f"; zera em ~{str(anos).replace('.', ',')} ano(s) nesse ritmo"
    else:
        cod, txt = "sem_divida", "sem movimento declarado"

    return {"codigo": cod, "texto": txt, "taxa_quitacao": taxa, "anos_para_quitar": anos,
            "anterior": round(a, 2), "pago": round(p, 2), "saldo": round(s, 2),
            "expedidos": round(e, 2)}


def carrega_tribunal(cx, caminho=None):
    """Carrega os Mapas Anuais publicados pelos PROPRIOS tribunais (serie historica).

    Fonte: data/mapa_tribunal_<sigla>.json (scripts/fetch_mapa_tribunal.py).
    Complementa a carga do painel do CNJ, que so traz o exercicio corrente.

    REGRA DE PRECEDENCIA: (tribunal, ano_ref) que JA existe na tabela nao e'
    sobrescrito. O painel do CNJ e' a fonte canonica do ano corrente; o PDF do
    tribunal entra apenas nos anos que faltam. Sem essa regra a mesma linha
    entraria duas vezes e a view `mapa_ente`, que SOMA por grupo, dobraria os
    valores silenciosamente — bug que so apareceria como "o ente pagou o dobro".

    prec_id e' sintetico e negativo aqui, para nunca colidir com o PREC_id do CNJ.
    """
    import glob
    import json
    if not existe(cx):
        cx.executescript(SCHEMA)
    alvos = [caminho] if caminho else sorted(
        glob.glob(os.path.join(BASE, "data", "mapa_tribunal_*.json")))
    ja = {(r[0], r[1]) for r in cx.execute(
        "SELECT DISTINCT tribunal, ano_ref FROM mapa_cnj")}
    prox = (cx.execute("SELECT MIN(prec_id) FROM mapa_cnj").fetchone()[0] or 0)
    prox = min(prox, 0) - 1
    n, pulados, anos = 0, 0, set()
    for fn in alvos:
        d = json.load(open(fn, encoding="utf-8"))
        for x in d.get("linhas") or []:
            chave = (x["tribunal"], x["ano_ref"])
            if chave in ja:
                pulados += 1
                continue
            # linha ESTADUAL sem ibge -> pseudo-IBGE da UF, a mesma regra do _ibge() do CNJ.
            # Sem isso a serie do governo estadual vinda do PDF do tribunal nao se ligava ao
            # ente: o Estado do RJ tinha 2023-2025 no arquivo do TJRJ e o Alfred so via 2025.
            # Linha ESTADUAL vai SEMPRE para o Estado, mesmo com codigo de municipio preenchido:
            # o TJTO grava o codigo de Palmas (1721000) nas linhas do governo estadual, e o
            # pagamento do Estado caia na serie de Palmas.
            ib = x.get("ibge")
            if str(x.get("esfera") or "").strip().lower().startswith(("estad", "distr")):
                ib = UF_PSEUDO_IBGE.get(str(x.get("uf") or "").strip().upper())
            cx.execute(
                "INSERT INTO mapa_cnj (prec_id, envio_id, ano_ref, tribunal, ramo, uf,"
                " esfera, tipo_entidade, ibge, ente_nome, cnpj, regime, vlr_ano_anterior,"
                " vlr_pago, vlr_saldo, vlr_expedidos) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (prox, None, x["ano_ref"], x["tribunal"], "Estadual", x.get("uf"),
                 x.get("esfera"), x.get("tipo_entidade"), ib, x.get("ente_nome"),
                 x.get("cnpj"), x.get("regime"), x.get("vlr_ano_anterior"),
                 x.get("vlr_pago"), x.get("vlr_saldo"), x.get("vlr_expedidos")))
            prox -= 1
            n += 1
            anos.add(x["ano_ref"])
    cx.commit()
    return n, sorted(anos), pulados


def existe(cx):
    return bool(cx.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='mapa_cnj'"
                           ).fetchone())


def ano_mais_recente(cx, ibge=None):
    q = "SELECT MAX(ano_ref) FROM mapa_cnj"
    args = ()
    if ibge:
        q += " WHERE ibge = ?"
        args = (ibge,)
    r = cx.execute(q, args).fetchone()
    return r[0] if r else None


def por_municipio(cx, ibge, ano_ref=None, so_direta=True):
    """Uma linha por TRIBUNAL, ja classificada. Vazio se nao houver dado."""
    if not ibge or not existe(cx):
        return []
    ano = ano_ref or ano_mais_recente(cx, ibge)
    if not ano:
        return []
    q = ("SELECT tribunal, ramo, tipo_entidade, n_entidades, tem_especial, "
         "anterior, pago, saldo, expedidos FROM mapa_ente WHERE ibge = ? AND ano_ref = ?")
    args = [ibge, ano]
    if so_direta:
        q += " AND tipo_entidade = 'Direta'"
    q += " ORDER BY saldo DESC, tribunal"
    out = []
    for r in cx.execute(q, args):
        d = classifica(r["anterior"], r["pago"], r["saldo"], r["expedidos"])
        d.update(tribunal=r["tribunal"], ramo=r["ramo"], tipo_entidade=r["tipo_entidade"],
                 n_entidades=r["n_entidades"], regime="Especial" if r["tem_especial"] else "Comum",
                 ano_ref=ano)
        out.append(d)
    return out


EM_DIA = ("quitou", "quitou_quase_tudo")


def resumo_municipio(cx, ibge, ano_ref=None, so_direta=True):
    """Consolidado do municipio + a leitura por tribunal.

    O consolidado sozinho MENTE por omissao quando o ente e' seletivo, e o caso e'
    comum: Conceicao da Barra quitou TJES e TRT17 e nao pagou o TRF2 — a media
    ponderada da "2% do estoque, zera em 50 anos", que descreve um inadimplente
    generico e nao esse ente. Por isso o texto consolidado nomeia os tribunais
    quando ha divergencia entre eles, e `codigo` vira 'seletivo'.
    """
    linhas = por_municipio(cx, ibge, ano_ref, so_direta)
    if not linhas:
        return None
    tot = classifica(sum(x["anterior"] for x in linhas), sum(x["pago"] for x in linhas),
                     sum(x["saldo"] for x in linhas), sum(x["expedidos"] for x in linhas))
    em_dia = [x["tribunal"] for x in linhas if x["codigo"] in EM_DIA]
    caloteiro = [x["tribunal"] for x in linhas if x["codigo"] == "nao_pagou"]
    if em_dia and caloteiro:
        tot["codigo"] = "seletivo"
        tot["texto"] = (f"paga uns tribunais e outros não — em dia em {', '.join(em_dia)}; "
                        f"R$ 0 pago em {', '.join(caloteiro)}")
    tot.update(ano_ref=linhas[0]["ano_ref"], por_tribunal=linhas,
               tribunais_inadimplentes=caloteiro, tribunais_em_dia=em_dia)
    return tot


def serie_anual(cx, ibge, so_direta=True):
    """Serie historica: um registro por (ano_ref, tribunal) + o total do ano.

    COBERTURA DESIGUAL, e quem consome precisa saber: o painel Qlik do CNJ publica
    apenas o exercicio corrente, entao a maioria dos estados tem UM ano so (2025).
    MG tem 2021-2025 porque veio de outra fonte (o PDF de enquadramento do TJMG,
    carregado por db_build.carrega_historico_tjmg). Devolver uma serie de um ponto
    e' correto — o que seria errado e' a tela sugerir que ha tendencia onde nao ha.
    """
    if not ibge or not existe(cx):
        return []
    q = ("SELECT ano_ref, tribunal, anterior, pago, saldo, expedidos "
         "FROM mapa_ente WHERE ibge = ?")
    if so_direta:
        q += " AND tipo_entidade = 'Direta'"
    q += " ORDER BY ano_ref, tribunal"
    por_ano = {}
    for r in cx.execute(q, (ibge,)):
        a = por_ano.setdefault(r["ano_ref"], {"ano_ref": r["ano_ref"], "por_tribunal": [],
                                              "anterior": 0.0, "pago": 0.0,
                                              "saldo": 0.0, "expedidos": 0.0})
        a["por_tribunal"].append({"tribunal": r["tribunal"], "anterior": r["anterior"],
                                  "pago": r["pago"], "saldo": r["saldo"],
                                  "expedidos": r["expedidos"]})
        for k in ("anterior", "pago", "saldo", "expedidos"):
            a[k] += r[k] or 0.0

    serie = [por_ano[k] for k in sorted(por_ano)]
    # COBERTURA POR ANO — sem isto a serie MENTE por omissao, e o caso e' comum:
    # os anos historicos vem do Mapa do proprio tribunal (so a Justica Estadual),
    # enquanto o ano do CNJ traz TODOS os tribunais. Em Pedro Canario/ES 2023 e
    # 2024 somavam so o TJES (saldo R$ 0 -> "municipio quitado") e 2025 somava
    # TJES+TRF2+TRT17 (saldo R$ 2,75 mi). O ente devia ao TRF2 o tempo todo; o
    # que mudou foi a COBERTURA, nao a divida. Quem le a serie precisa ver isso.
    for a in serie:
        a["tribunais"] = sorted(x["tribunal"] for x in a["por_tribunal"])
    conjuntos = {tuple(a["tribunais"]) for a in serie}
    for a in serie:
        a["cobertura_uniforme"] = len(conjuntos) == 1
    return serie


def pago_no_tribunal(cx, ibge, tribunal, ano_ref=None, so_direta=True):
    """Pago no ano-ref por este municipio NAQUELE tribunal.

    Serve de fonte 'observado' para o orcamento anual (modelo_p23.orcamento_anual).
    O filtro por tribunal e' obrigatorio: somar TJ + TRT + TRF e atribuir o total a
    fila do TJ inflava o orcamento — em Conceicao da Barra, R$ 271 mil em vez dos
    R$ 202 mil efetivamente pagos ao TJES.
    """
    if not ibge or not tribunal or not existe(cx):
        return None
    ano = ano_ref or ano_mais_recente(cx, ibge)
    if not ano:
        return None
    q = ("SELECT COALESCE(SUM(vlr_pago),0) FROM mapa_cnj "
         "WHERE ibge = ? AND ano_ref = ? AND tribunal = ?")
    args = [ibge, ano, tribunal]
    if so_direta:
        q += " AND tipo_entidade = 'Direta'"
    v = cx.execute(q, args).fetchone()[0]
    return round(v, 2) if v else None


# ---------------------------------------------------------------- CLI
def _brl(v):
    return "—" if v is None else "R$ " + f"{v:,.2f}".replace(",", "\x00").replace(".", ",").replace("\x00", ".")


def resumo(cx):
    n, anos = cx.execute("SELECT COUNT(*), COUNT(DISTINCT ano_ref) FROM mapa_cnj").fetchone()
    print(f"\n=== mapa_cnj: {n:,} linhas | {anos} ano(s)-referencia ===")
    for a, t, m, v in cx.execute(
            "SELECT ano_ref, COUNT(DISTINCT tribunal), COUNT(DISTINCT ibge), SUM(vlr_saldo) "
            "FROM mapa_cnj GROUP BY ano_ref ORDER BY ano_ref"):
        print(f"  {a}: {t} tribunais | {m:,} municipios | saldo devedor {_brl(v)}")
    print("\n  situacao dos municipios (administracao direta, todos os tribunais):")
    cont = {}
    for ibge, in cx.execute("SELECT DISTINCT ibge FROM mapa_cnj WHERE ibge IS NOT NULL"):
        r = resumo_municipio(cx, ibge)
        if r:
            cont[r["codigo"]] = cont.get(r["codigo"], 0) + 1
    for k, v in sorted(cont.items(), key=lambda x: -x[1]):
        print(f"    {k:<20} {v:>5}")
    confere_regime(cx)


def confere_regime(cx):
    """municipio.regime x regime declarado no Mapa. Divergir e' legitimo -- MG e'
    sobrescrito pelo Enquadramento EF 2026, mais recente que o envio do CNJ -- mas
    divergencia SILENCIOSA nao e'. Aplica a mesma regra da consolidacao (qualquer
    linha de TJ/adm direta em Especial -> Especial) para nao acusar falso positivo
    em municipio com duas linhas de TJ (ex.: Torres/RS deve ao TJRS e ao TJSC)."""
    q = ("SELECT m.uf, m.regime AS alfred, "
         "MAX(CASE WHEN k.regime='Especial' THEN 1 ELSE 0 END) AS mapa_especial "
         "FROM municipio m JOIN mapa_cnj k ON k.ibge = m.ibge "
         "WHERE k.ramo = 'Estadual' AND k.tipo_entidade = 'Direta' AND k.regime IS NOT NULL "
         "GROUP BY m.ibge, m.uf, m.regime")
    div = {}
    n = 0
    for r in cx.execute(q):
        n += 1
        if r["alfred"] != ("Especial" if r["mapa_especial"] else "Comum"):
            div[r["uf"]] = div.get(r["uf"], 0) + 1
    if not div:
        print(f"\n  regime: {n:,} municipios conferidos, nenhuma divergencia com o Mapa")
        return
    tot = sum(div.values())
    detalhe = ", ".join(f"{uf}={q_}" for uf, q_ in sorted(div.items(), key=lambda x: -x[1]))
    print(f"\n  regime: {tot} de {n:,} divergem de municipio.regime ({detalhe})")
    if set(div) == {"MG"}:
        print("    (esperado: MG vem do TJMG Enquadramento EF 2026, mais recente que o CNJ)")


def mostra_municipio(cx, ibge):
    m = cx.execute("SELECT nome, uf FROM municipio WHERE ibge = ?", (ibge,)).fetchone()
    r = resumo_municipio(cx, ibge)
    if not r:
        print(f"sem dado do Mapa Anual para {ibge}")
        return
    nome = f"{m['nome']}/{m['uf']}" if m else ibge
    print(f"\n{nome} — Mapa Anual CNJ ref. {r['ano_ref']} (administração direta)")
    print(f"  consolidado: {r['texto']}")
    print(f"  {'tribunal':<8} {'estoque abertura':>18} {'pago':>16} {'saldo':>16} {'expediu':>16}  situação")
    for x in r["por_tribunal"]:
        print(f"  {x['tribunal']:<8} {_brl(x['anterior']):>18} {_brl(x['pago']):>16} "
              f"{_brl(x['saldo']):>16} {_brl(x['expedidos']):>16}  {x['texto']}")


def main():
    ap = argparse.ArgumentParser(description="Carga do Mapa Anual do CNJ no banco do Alfred")
    ap.add_argument("--resumo", action="store_true", help="so mostra o que ja esta carregado")
    ap.add_argument("--ibge", help="mostra a leitura de um municipio")
    a = ap.parse_args()
    if not os.path.exists(DB):
        sys.exit(f"banco nao existe: {DB} — rode scripts/db_build.py")
    cx = sqlite3.connect(DB)
    cx.row_factory = sqlite3.Row
    with cx:
        if a.ibge:
            mostra_municipio(cx, re.sub(r"\D", "", a.ibge))
            return
        if not a.resumo:
            n, anos = carrega(cx)
            print(f"carregadas {n:,} linhas (anos-ref: {', '.join(map(str, anos))})")
        resumo(cx)


if __name__ == "__main__":
    main()
