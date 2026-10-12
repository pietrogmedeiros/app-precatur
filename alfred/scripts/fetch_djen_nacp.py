# -*- coding: utf-8 -*-
"""Coleta os atos do Nucleo de Precatorios (NACP) no DJEN e extrai os dados que
faltavam no Alfred para responder "o ente esta pagando?" sem garimpo manual:

  1. TABELA §23 do Comite Gestor de Contas Especiais (EC 136/2025)
     -> mora oficial em 1o/jan, % aplicado, valor anual do plano e rateio por
        tribunal, de TODOS os entes do estado. Um unico despacho traz a tabela
        inteira, republicada no PA de Fiscalizacao de cada municipio.
  2. CERTIDAO DE REGULARIDADE  -> o ente esta em dia com o Plano de Pagamento?
  3. PROTOCOLO DE VALOR BLOQUEADO -> houve bloqueio SISBAJUD (sinal de calote).

Descoberta que viabiliza tudo (2026-08-19): o DJEN aceita `orgaoId` como filtro.
`orgaoId=94109` = Presidencia/Nucleo de Precatorios do TJBA. Sem isso a varredura
era inviavel (o filtro `nomeOrgao` e' silenciosamente IGNORADO pela API e devolve
o diario inteiro, e `numeroProcesso` exige saber o PA de cada municipio antes).

Uso:
  python scripts/fetch_djen_nacp.py --uf BA --de 2026-01-01 --ate 2026-12-31
  python scripts/fetch_djen_nacp.py --uf BA --meses 12

Saida: data/djen_nacp_<UF>.json  (consumido por db_build.py)
"""
import argparse
import html
import json
import os
import pathlib
import re
import sys
import time
import unicodedata
import urllib.parse
import urllib.request
from datetime import date, timedelta

sys.stdout.reconfigure(encoding="utf-8")
BASE = os.environ.get("ALFRED_BASE") or str(pathlib.Path(__file__).resolve().parents[1])
DJEN = "https://comunicaapi.pje.jus.br/api/v1/comunicacao"
UA = "Mozilla/5.0 (alfred-nacp)"

# orgaoId do Nucleo/Setor de Precatorios por tribunal. Para descobrir o de um
# tribunal novo: pegue UMA publicacao conhecida do nucleo (por numeroProcesso do
# PA de Fiscalizacao) e leia o campo `idOrgao` do item devolvido.
ORGAOS = {
    "BA": {"tribunal": "TJBA", "orgao_id": 94109, "nome": "Presidência - Núcleo de Precatórios"},
}

# A tabela vem achatada numa linha so: "DEVEDOR R$ x,xx 1,00% R$ y,yy 100,00% 0,00% 0,00%".
# O nome do ente e' greedy-safe porque ancoramos no "R$" seguinte.
RX_LINHA = re.compile(
    r"([A-ZÀ-Ú][A-ZÀ-Ú0-9\s\-\.\/']*?)\s+"
    r"R\$\s*([\d.]+,\d{2})\s+"          # total devido (mora em 1o/jan)
    r"([\d,]+)%\s+"                     # % aplicado (faixa do §23)
    r"R\$\s*([\d.]+,\d{2})\s+"          # valor anual do plano
    r"([\d,]+)%\s+([\d,]+)%\s+([\d,]+)%"  # rateio TJ / TRT / TRF
)
# Cabecalho da tabela: some no fim do 1o match e vira prefixo do 1o devedor.
RX_CABECALHO = re.compile(r"^(?:DEVEDOR|TOTAL DEVIDO|%?\s*APLICADO|VALOR ANUAL|%\s*TJ\w*|%\s*TRT|%\s*TRF)\s+", re.I)

RX_ANO_PLANO = re.compile(r"Plano de Pagamento de (\d{4})", re.I)
RX_ANO_TABELA = re.compile(r"reuni[ãa]o realizada em \d{2}/\d{2}/(\d{4})", re.I)
RX_ORCAMENTO = re.compile(r"RELA[ÇC][ÃA]O DE PRECAT[ÓO]RIOS\s*[-–—]?\s*OR[ÇC]AMENTO\s+(\d{4})", re.I)


def norm(s):
    """Maiusculas sem acento — chave de casamento nome<->IBGE."""
    s = unicodedata.normalize("NFKD", str(s or "")).encode("ascii", "ignore").decode()
    return re.sub(r"\s+", " ", s).upper().strip()


def limpa(txt):
    """HTML do DJEN -> texto plano numa linha (a tabela ja vem achatada)."""
    t = re.sub(r"<[^>]+>", " ", html.unescape(txt or ""))
    return re.sub(r"\s+", " ", t).strip()


def moeda(s):
    return float(s.replace(".", "").replace(",", "."))


def pct(s):
    return float(s.replace(",", "."))


def get(url, tentativas=4):
    ultimo = None
    for i in range(tentativas):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA})
            with urllib.request.urlopen(req, timeout=90) as r:
                return json.loads(r.read().decode("utf-8"))
        except Exception as e:  # noqa: BLE001
            ultimo = e
            time.sleep(1.5 * (i + 1))
    raise RuntimeError(f"DJEN falhou: {ultimo}")


TETO_DJEN = 10000  # a API satura o `count` em 10.000 e para de paginar alem disso


def _conta(orgao_id, de, ate):
    """So o `count` da janela — 1 requisicao barata.

    Existe para NAO paginar uma janela que vai saturar: sem esta sonda, descobrir
    que um intervalo estourou custava 50 requisicoes (as 10.000 linhas inteiras)
    antes de decidir dividir. Com 3 niveis de recursao isso sozinho estourava o
    tempo de execucao.
    """
    q = urllib.parse.urlencode({
        "orgaoId": orgao_id, "dataDisponibilizacaoInicio": de,
        "dataDisponibilizacaoFim": ate, "itensPorPagina": 1, "pagina": 1})
    return get(f"{DJEN}?{q}").get("count") or 0


def _fatia(orgao_id, de, ate, por_pagina=200):
    """Pagina UMA janela que ja se sabe caber abaixo do teto."""
    itens, pagina = [], 1
    while True:
        q = urllib.parse.urlencode({
            "orgaoId": orgao_id, "dataDisponibilizacaoInicio": de,
            "dataDisponibilizacaoFim": ate, "itensPorPagina": por_pagina, "pagina": pagina})
        d = get(f"{DJEN}?{q}")
        lote = d.get("items") or []
        if not lote:
            break
        itens.extend(lote)
        if len(lote) < por_pagina or len(itens) >= (d.get("count") or 0):
            break
        pagina += 1
        time.sleep(0.25)
    return itens


def varre(orgao_id, de, ate, por_pagina=200, _nivel=0):
    """Todas as publicacoes do orgao no periodo, com fatiamento adaptativo.

    A API do DJEN satura em 10.000 resultados por consulta e simplesmente para —
    sem erro. Numa janela de 8 meses do NACP/TJBA isso cortou JANEIRO inteiro, que
    e' justamente onde sai o despacho anual do Comite Gestor com a tabela §23.
    Por isso: se a janela saturar, parte no meio e desce recursivamente ate caber.
    """
    ini, fim = date.fromisoformat(de), date.fromisoformat(ate)
    ident = "  " * _nivel
    total = _conta(orgao_id, de, ate)
    if total < TETO_DJEN or ini >= fim:
        itens = _fatia(orgao_id, de, ate, por_pagina)
        print(f"    {ident}{de}..{ate}: {len(itens)}", flush=True)
        return itens
    meio = ini + (fim - ini) // 2
    print(f"    {ident}{de}..{ate}: satura ({total}) — dividindo", flush=True)
    esq = varre(orgao_id, de, meio.isoformat(), por_pagina, _nivel + 1)
    dir_ = varre(orgao_id, (meio + timedelta(days=1)).isoformat(), ate, por_pagina, _nivel + 1)
    vistos, saida = set(), []
    for it in esq + dir_:            # janelas adjacentes nao se sobrepoem, mas garante
        if it.get("id") in vistos:
            continue
        vistos.add(it.get("id"))
        saida.append(it)
    return saida


def ente_do_item(it, texto):
    """Nome do ente devedor: preferir o polo passivo do proprio PA."""
    for d in (it.get("destinatarios") or []):
        nome = (d.get("nome") or "").strip()
        if norm(nome).startswith(("MUNICIPIO", "ESTADO", "CAMARA", "PREFEITURA")):
            return nome
    m = re.search(r"REQUERIDO:\s*([A-ZÀ-Ú][^:]{3,80}?)\s+(?:Advogado|REQUERENTE|$)", texto)
    return m.group(1).strip() if m else None


def parse_tabela(texto):
    """Extrai a tabela §23 inteira. Devolve [] se o texto nao for o despacho."""
    if "% APLICADO" not in texto.upper():
        return []
    linhas = []
    for m in RX_LINHA.finditer(texto):
        nome = RX_CABECALHO.sub("", re.sub(r"\s+", " ", m.group(1)).strip())
        # sobra de cabecalho pode deixar so a sigla do ultimo campo colada
        nome = re.sub(r"^(?:TRF|TRT|TJ\w{0,2})\s+(?=[A-ZÀ-Ú])", "", nome).strip()
        if len(nome) < 3:
            continue
        linhas.append({
            "devedor": nome,
            "mora_1jan": moeda(m.group(2)),
            "pct_aplicado": pct(m.group(3)),
            "valor_anual": moeda(m.group(4)),
            "rateio": {"TJ": pct(m.group(5)), "TRT": pct(m.group(6)), "TRF": pct(m.group(7))},
        })
    return linhas


def classifica(texto):
    """Que tipo de ato e' esta publicacao do NACP."""
    up = texto.upper()
    if "% APLICADO" in up and "COMIT" in up:
        return "tabela_p23"
    if "SITUAÇÃO REGULAR" in up or "SITUACAO REGULAR" in up:
        return "certidao_regular"
    if "IRREGULAR" in up and "CERTIFICO" in up:
        return "certidao_irregular"
    if "VALOR BLOQUEADO" in up:
        return "bloqueio_sisbajud"
    if RX_ORCAMENTO.search(texto):
        return "relacao_orcamento"
    return None


def mapa_ibge(uf):
    """nome normalizado -> codigo IBGE, a partir do arquivo do IBGE ja no repo."""
    fn = os.path.join(BASE, "data", f"ibge_{uf.lower()}_municipios.json")
    if not os.path.exists(fn):
        print(f"  (!) sem {fn} — entes ficarao sem IBGE")
        return {}
    dados = json.load(open(fn, encoding="utf-8"))
    return {norm(m["nome"]): str(m["id"]) for m in dados}


def casa_ibge(nome, mapa):
    """Casa 'MUNICIPIO DE X' / 'X' com o IBGE. Devolve None p/ autarquia/empresa."""
    n = norm(nome)
    n = re.sub(r"^(MUNICIPIO|PREFEITURA(?: MUNICIPAL)?)\s+(DE\s+|DO\s+|DA\s+)?", "", n).strip()
    return mapa.get(n)


SOBREPOSICAO_DIAS = 10   # ver docstring de janela_incremental


def extrai(pas, mapa):
    """Publicacoes do PA -> (tabela §23 por ano, lista de atos)."""
    tabela, atos = {}, []
    for it in pas:
        texto = limpa(it.get("texto"))
        tipo = classifica(texto)
        if not tipo:
            continue
        pub = {"tipo": tipo, "data": it.get("data_disponibilizacao"),
               "pa": it.get("numeroprocessocommascara"), "id_djen": it.get("id")}

        if tipo == "tabela_p23":
            # O MESMO despacho e' republicado no PA de cada municipio, MAS existem
            # variantes curtas que citam o Comite/o "% APLICADO" sem reproduzir a
            # tabela. Ficar com a PRIMEIRA que aparece gravava justamente uma dessas
            # (0 entes). Por isso: parseia todas e fica a que tiver MAIS entes.
            ano = int(m.group(1)) if (m := RX_ANO_TABELA.search(texto)) else None
            chave = str(ano or pub["data"][:4])
            linhas = parse_tabela(texto)
            anterior = tabela.get(chave)
            if anterior and len(anterior["entes"]) >= len(linhas):
                continue
            for ln in linhas:
                ln["ibge"] = casa_ibge(ln["devedor"], mapa)
            tabela[chave] = {"ano": ano, "fonte": pub, "entes": linhas}
            continue

        ente = ente_do_item(it, texto)
        pub["ente"] = ente
        pub["ibge"] = casa_ibge(ente, mapa) if ente else None
        if tipo in ("certidao_regular", "certidao_irregular"):
            pub["situacao"] = "IRREGULAR" if tipo.endswith("irregular") else "REGULAR"
            pub["ano_plano"] = int(m.group(1)) if (m := RX_ANO_PLANO.search(texto)) else None
        if tipo == "relacao_orcamento":
            pub["ano_orcamento"] = int(m.group(1)) if (m := RX_ORCAMENTO.search(texto)) else None
        atos.append(pub)
    return tabela, atos


def funde(antigo, tabela_nova, atos_novos):
    """Junta o que ja estava no JSON com o que a varredura desta rodada trouxe.

    Duas regras, e as duas existem por um motivo concreto:

    1. ATOS deduplicam por `id_djen` — o id da publicacao no DJEN. E' chave
       natural e estavel, entao reprocessar um periodo ja coletado nao duplica
       nada (e a tabela `nacp_ato` tem o mesmo id como PRIMARY KEY).

    2. A TABELA §23 do ano anterior e' PRESERVADA. Ela sai UMA VEZ por ano, em
       janeiro. Uma coleta incremental de 10 dias em agosto nao a encontra — se
       o merge simplesmente substituisse, a rotina APAGARIA o plano de todos os
       entes do estado na primeira execucao. Dentro do mesmo ano, fica a versao
       com MAIS entes (mesmo criterio da extracao).
    """
    tabela = dict((antigo.get("tabela_p23") or {}))
    for chave, bloco in tabela_nova.items():
        atual = tabela.get(chave)
        if atual and len(atual.get("entes") or []) >= len(bloco.get("entes") or []):
            continue
        tabela[chave] = bloco

    por_id = {a["id_djen"]: a for a in (antigo.get("atos") or []) if a.get("id_djen")}
    novos = 0
    for a in atos_novos:
        if a.get("id_djen") is None:
            continue
        if a["id_djen"] not in por_id:
            novos += 1
        por_id[a["id_djen"]] = a
    atos = sorted(por_id.values(), key=lambda x: (x.get("data") or "", x["id_djen"]))
    return tabela, atos, novos


def janela_incremental(antigo, hoje):
    """De onde retomar. Volta SOBREPOSICAO_DIAS antes da ultima coleta.

    O DJEN publica com atraso: um ato do dia 5 pode aparecer no dia 12. Retomar
    exatamente onde parou perde essas publicacoes atrasadas para sempre, porque
    a janela seguinte ja comeca depois delas. A sobreposicao custa pouco (a
    dedup por id_djen absorve o reprocessamento) e fecha esse buraco.
    """
    ate_ant = (antigo.get("janela") or {}).get("ate")
    if not ate_ant:
        return None
    inicio = date.fromisoformat(ate_ant) - timedelta(days=SOBREPOSICAO_DIAS)
    return min(inicio, hoje).isoformat()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--uf", default="BA")
    ap.add_argument("--de")
    ap.add_argument("--ate")
    ap.add_argument("--meses", type=int, default=12,
                    help="janela retroativa na primeira coleta (sem --de/--ate)")
    ap.add_argument("--incremental", action="store_true",
                    help="retoma da ultima coleta (com sobreposicao) e funde no JSON existente")
    ap.add_argument("--cache", action="store_true",
                    help="salva/reusa o bruto da varredura (p/ reparsear sem refetch)")
    a = ap.parse_args()

    uf = a.uf.upper()
    if uf not in ORGAOS:
        sys.exit(f"UF {uf} sem orgaoId mapeado. Ver dicionario ORGAOS no topo.")
    cfg = ORGAOS[uf]
    fn = os.path.join(BASE, "data", f"djen_nacp_{uf.lower()}.json")
    antigo = json.load(open(fn, encoding="utf-8")) if os.path.exists(fn) else {}

    hoje = date.today()
    ate = a.ate or hoje.isoformat()
    if a.de:
        de = a.de
    elif a.incremental and (retomada := janela_incremental(antigo, hoje)):
        de = retomada
        print(f"  (incremental) ultima coleta ate {antigo['janela']['ate']}; "
              f"retomando de {de} (sobreposicao de {SOBREPOSICAO_DIAS} dias)")
    else:
        de = (hoje - timedelta(days=31 * a.meses)).isoformat()

    print(f"NACP {cfg['tribunal']} (orgaoId={cfg['orgao_id']})  {de} -> {ate}")
    # Cache do BRUTO: a varredura completa leva ~15 min (35 mil publicacoes para
    # usar ~1.700). Sem isto, cada ajuste de regex custava outra varredura.
    cache = os.path.join(BASE, "data", f".cache_djen_nacp_{uf.lower()}_{de}_{ate}.json")
    if a.cache and os.path.exists(cache):
        itens = json.load(open(cache, encoding="utf-8"))
        print(f"  (cache) {len(itens)} publicacoes de {cache}")
    else:
        itens = varre(cfg["orgao_id"], de, ate)
        if a.cache:
            json.dump(itens, open(cache, "w", encoding="utf-8"), ensure_ascii=False)
    print(f"  publicacoes no periodo: {len(itens)}")

    pas = [i for i in itens if i.get("nomeClasse") == "PROCESSO ADMINISTRATIVO"]
    print(f"  PROCESSO ADMINISTRATIVO (PA de Fiscalizacao): {len(pas)}")

    tabela_nova, atos_novos = extrai(pas, mapa_ibge(uf))
    tabela, atos, n_novos = funde(antigo if a.incremental else {}, tabela_nova, atos_novos)

    from collections import Counter
    print(f"  atos nesta rodada: {dict(Counter(x['tipo'] for x in atos_novos))}")
    if a.incremental:
        print(f"  atos INEDITOS: {n_novos} | acervo total: {len(atos)}")
    for chave, bloco in sorted(tabela.items()):
        print(f"  tabela §23 {chave}: {len(bloco['entes'])} entes "
              f"({sum(1 for x in bloco['entes'] if x['ibge'])} com IBGE)")

    # a janela gravada e' a COBERTURA acumulada, nao a desta rodada — e' dela que
    # a proxima execucao incremental parte
    de_ant = (antigo.get("janela") or {}).get("de") if a.incremental else None
    saida = {"uf": uf, "tribunal": cfg["tribunal"], "orgao_id": cfg["orgao_id"],
             "janela": {"de": min(de, de_ant) if de_ant else de, "ate": ate},
             "coletado_em": hoje.isoformat(),
             "tabela_p23": tabela, "atos": atos}
    json.dump(saida, open(fn, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(f"OK -> {fn}")


if __name__ == "__main__":
    main()
