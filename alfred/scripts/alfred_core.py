# -*- coding: utf-8 -*-
"""Nucleo de consulta do Alfred: busca + contexto + parecer estruturado.

Existe para que a CLI (db_busca.py) e a API (api.py) compartilhem EXATAMENTE a
mesma logica. A fase 2 acabou de eliminar a duplicacao do modelo de calculo;
recria-la na camada de consulta seria repetir o erro.

Camadas:
    modelo_p23.py   a norma (§20, §23, §5o)  — nao sabe o que e' banco
    db_mapa.py      Mapa Anual do CNJ: o ente pagou? (ano passado, tabela `mapa_cnj`)
    db_nacp.py      Nucleo de Precatorios: quanto deve pagar ESTE ano e esta em dia?
    alfred_core.py  consulta + montagem do parecer (aqui)
    db_busca.py     apresentacao em terminal
    api.py          apresentacao em HTTP

LGPD: mascara_cpf() e' aplicada por padrao em tudo que sai daqui. O CPF completo
so aparece com completo=True, que a API concede apenas ao papel 'completo'.
Nenhuma funcao deste modulo escreve CPF em log.
"""
import csv
import glob
import importlib.util
import math
import os
import pathlib
import re
import sqlite3
import unicodedata
from datetime import date as _date

# BASE resolvido a partir do proprio arquivo: funciona no Windows e na VM Linux.
# ALFRED_BASE sobrepoe quando o codigo roda de outro lugar.
BASE = os.environ.get("ALFRED_BASE") or str(pathlib.Path(__file__).resolve().parents[1])
DB = os.path.join(BASE, "data", "alfred.db")
EXERCICIO = 2026

_spec = importlib.util.spec_from_file_location("modelo_p23", os.path.join(BASE, "scripts", "modelo_p23.py"))
M = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(M)

_spec = importlib.util.spec_from_file_location("db_mapa", os.path.join(BASE, "scripts", "db_mapa.py"))
MAPA = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(MAPA)

_spec = importlib.util.spec_from_file_location("db_nacp", os.path.join(BASE, "scripts", "db_nacp.py"))
NACP = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(NACP)

_spec = importlib.util.spec_from_file_location("credor_norm", os.path.join(BASE, "scripts", "credor_norm.py"))
CN = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(CN)

# Tribunais que NAO publicam o nome do credor na lista cronologica. Consequencia
# pratica: nesses, busca por nome ou CPF nunca acha nada — so' por numero. O
# conjunto tem de bater com a realidade da base (SELECT tribunal, COUNT(credor)),
# senao a UI devolve "nada encontrado" sem dizer por que.
SEM_CREDOR = {"TJRJ", "TJPE", "TJSP", "TJMA", "TJCE", "TJPA", "TRF2", "TRF5", "TRT17", "TRT3"}
# TJPE: a view publica traz saldo zerado em 100% dos registros (caveat do coletor)
SEM_VALOR = {"TJPE"}
# TJMG: o EPD nao publica numero de processo (so uma sequencia interna: "1","2"...)
# nem o nome inteiro do credor (sai em iniciais, "M.O.S."). Logo, precatorio de MG
# NAO e' localizavel por numero nem por nome — so navegando pela fila do ente.
SEM_NUMERO = {"TJMG"}


def conecta(db=DB):
    if not os.path.exists(db):
        raise FileNotFoundError(f"banco nao existe: {db} — rode scripts/db_build.py")
    cx = sqlite3.connect(db)
    cx.row_factory = sqlite3.Row
    cx.create_function("SEM_ACENTO", 1, _sem_acento, deterministic=True)
    return cx


def mascara_cpf(cpf, completo=False):
    """'00000000000' -> '000.***.***-00'. Padrao do sistema e' mascarado."""
    if not cpf:
        return None
    d = re.sub(r"\D", "", cpf)
    if completo:
        if len(d) == 11:
            return f"{d[:3]}.{d[3:6]}.{d[6:9]}-{d[9:]}"
        if len(d) == 14:
            return f"{d[:2]}.{d[2:5]}.{d[5:8]}/{d[8:12]}-{d[12:]}"
        return d
    if len(d) == 11:
        return f"{d[:3]}.***.***-{d[9:]}"
    return (d[:2] + "." + "*" * 6 + "/" + d[-6:]) if len(d) == 14 else "***"


# CPF escrito DENTRO do nome do credor: algumas listas (ex.: Estado da BA) publicam
# "FULANO CPF ..." no campo do nome. Mascara so' na SAIDA, com a mesma mascara do
# cpf_cnpj; banco, credor_norm e credor_fts nao mudam (a busca continua igual).
# Formato de CPF (com pontos e hifen, ou 11 digitos isolados), valido ou nao; os
# lookarounds nao deixam pegar pedaco de numero maior (CNJ, valor em R$, data).
_CPF_NO_TEXTO = re.compile(r"(?<![\d.,])(?:\d{3}\.\d{3}\.\d{3}-\d{2}|\d{11})(?!\d|[.,]\d)")


def mascara_cpf_no_texto(texto):
    """'FULANO CPF 00000000000' -> 'FULANO CPF 000.***.***-00'. Para o campo credor."""
    if not texto:
        return texto
    return _CPF_NO_TEXTO.sub(lambda m: mascara_cpf(m.group(0)), texto)


def brl(v):
    """1234.5 -> 'R$ 1.234,50'. Fica aqui (e nao so na CLI) porque os textos de
    aviso montados neste modulo saem prontos para a tela e para o HTTP."""
    if v is None:
        return "—"
    return "R$ " + f"{v:,.2f}".replace(",", "\x00").replace(".", ",").replace("\x00", ".")


def fmt_cnj(d):
    """20 digitos -> 0002014-69.2020.8.26.0417. O banco guarda so digitos (para a
    busca casar), mas quem le precisa do numero formatado."""
    if not d:
        return None
    d = re.sub(r"\D", "", d)
    if len(d) != 20:
        return d
    return f"{d[:7]}-{d[7:9]}.{d[9:13]}.{d[13]}.{d[14:16]}.{d[16:]}"


# Justica Estadual: codigo do tribunal (posicoes 15-16 do numero CNJ) -> sigla/UF.
# Serve para explicar "nada encontrado": quase sempre e' tribunal fora da cobertura,
# nao precatorio inexistente. Sem isso o usuario conclui que o sistema esta quebrado.
TJ_POR_CODIGO = {
    "01": "TJAC/Acre", "02": "TJAL/Alagoas", "03": "TJAP/Amapá", "04": "TJAM/Amazonas",
    "05": "TJBA/Bahia", "06": "TJCE/Ceará", "07": "TJDFT/Distrito Federal",
    "08": "TJES/Espírito Santo", "09": "TJGO/Goiás", "10": "TJMA/Maranhão",
    "11": "TJMT/Mato Grosso", "12": "TJMS/Mato Grosso do Sul", "13": "TJMG/Minas Gerais",
    "14": "TJPA/Pará", "15": "TJPB/Paraíba", "16": "TJPR/Paraná", "17": "TJPE/Pernambuco",
    "18": "TJPI/Piauí", "19": "TJRJ/Rio de Janeiro", "20": "TJRN/Rio Grande do Norte",
    "21": "TJRS/Rio Grande do Sul", "22": "TJRO/Rondônia", "23": "TJRR/Roraima",
    "24": "TJSC/Santa Catarina", "25": "TJSE/Sergipe", "26": "TJSP/São Paulo",
    "27": "TJTO/Tocantins",
}
SEGMENTO = {"1": "Supremo Tribunal Federal", "2": "Conselho Nacional de Justiça",
            "3": "Superior Tribunal de Justiça", "4": "Justiça Federal",
            "5": "Justiça do Trabalho", "6": "Justiça Eleitoral", "7": "Justiça Militar da União",
            "8": "Justiça Estadual", "9": "Justiça Militar Estadual"}


def cobertura(cx):
    """Tribunais que existem no banco hoje."""
    return sorted(r[0] for r in cx.execute("SELECT DISTINCT tribunal FROM precatorio"))


def explica_vazio(cx, termo):
    """Por que a busca nao achou nada. Devolve texto ou None."""
    d = re.sub(r"\D", "", termo or "")
    tribs = cobertura(cx)
    if len(d) != 20:
        if 11 <= len(d) <= 14:
            return ("CPF/CNPJ não encontrado. Só a fila do TJAL publica CPF — nos demais "
                    "tribunais a busca por CPF não alcança nada, mesmo que o precatório exista.")
        if len(d) >= 15:
            return "Número incompleto: o padrão CNJ tem 20 dígitos."
        if not d and (termo or "").strip():
            # Busca por NOME que nao achou nada. Sem esta explicacao o time procura
            # um credor de CE/PA/RJ, recebe silencio e conclui que o precatorio nao
            # existe — quando na verdade aquele tribunal nao publica o nome de ninguem.
            com, sem = [], []
            for t, n in cx.execute("SELECT tribunal, COUNT(credor) FROM precatorio "
                                   "GROUP BY tribunal ORDER BY tribunal"):
                (com if n else sem).append(t)
            if sem:
                return ("Credor não encontrado. Só publicam o nome do credor: "
                        f"{', '.join(com)}. Nestes a busca por nome não alcança nada, "
                        f"mesmo que o precatório exista: {', '.join(sem)} — aí só pelo "
                        "número do precatório ou do processo de origem.")
        return None
    seg, cod = d[13], d[14:16]
    if seg == "8":
        nome = TJ_POR_CODIGO.get(cod, f"tribunal estadual de código {cod}")
        sigla = nome.split("/")[0]
        if sigla in SEM_NUMERO:     # MG: casa pelo Eproc, nao pelo numero da fila
            return ("Minas Gerais está na base. Busque pelo número do PRECATÓRIO (o CNJ que "
                    "começa com 2 ou 8 e termina em .8.13.0000) ou pelo número do processo de "
                    "origem — a sequência curta do painel do TJMG (\"19\", \"106\") não é "
                    "pesquisável, e o credor sai abreviado em iniciais.")
        if sigla in tribs:
            return (f"Este número é do {nome}, que está na base — mas o precatório não foi "
                    f"localizado. Pode ser processo de origem sem precatório expedido, ente "
                    f"ainda não coletado, ou precatório posterior à última coleta.")
        return (f"Este número é do {nome}, que ainda NÃO está na base do Alfred. "
                f"Hoje temos: {', '.join(tribs)}.")
    return (f"Este número é da {SEGMENTO.get(seg, 'justiça de segmento ' + seg)}. "
            f"O Alfred cobre hoje apenas tribunais estaduais: {', '.join(tribs)}.")


def _criterio(cx, termo, ordem="valor"):
    """(where, params, order_by, criterio) do termo -- UMA definicao para busca(),
    conta() e busca_pagina(), p/ pagina e total nunca divergirem. Aceita nº de
    precatorio, nº de origem, CPF ou nome. ORDER BY vem de whitelist, nunca do
    usuario -- sem injecao -- e sempre termina em `id`: sem desempate, itens com o
    mesmo valor (ou nome) saiam em ordem arbitraria e o LIMIT/OFFSET podia repetir
    um item em duas paginas e pular outro."""
    # NULLS LAST no alfabetico: credor pode ser nulo (TJRJ/PE/GO nao publicam nome).
    alfa = "credor IS NULL, credor COLLATE NOCASE" if ordem == "nome" else None
    d = re.sub(r"\D", "", termo or "")
    if len(d) >= 15:
        # numero_eproc = CNJ do precatorio (TJMG). E o numero que o comercial recebe,
        # entao vem primeiro na clausula. numero_origem = processo de conhecimento.
        return ("numero_eproc = ? OR numero = ? OR numero_origem = ?", [d, d, d],
                (alfa or "tribunal, ordem") + ", id", "numero_processo")
    if 11 <= len(d) <= 14:
        return "cpf_cnpj = ?", [d], (alfa or "ordem") + ", id", "cpf_cnpj"
    frag, params = _where_credor(cx, termo)
    return frag, params, (alfa or "valor DESC") + ", id", "credor"


def busca(cx, termo, limite=50, offset=0, ordem="valor"):
    """Devolve (linhas, criterio) de UMA pagina. `offset` pagina (LIMIT/OFFSET).
    `ordem`: 'valor' (padrao, maior primeiro) ou 'nome' (alfabetico do credor, nulos
    por ultimo). Criterio em _criterio()."""
    w, params, ob, criterio = _criterio(cx, termo, ordem)
    rs = cx.execute(f"SELECT * FROM precatorio_atual WHERE {w} ORDER BY {ob} LIMIT ? OFFSET ?",
                    params + [limite, offset]).fetchall()
    return rs, criterio


def conta(cx, termo):
    """Total de precatorios que casam o termo (sem LIMIT), no MESMO criterio da busca()
    -- p/ a UI paginar (quantas paginas) e avisar quando ha mais."""
    w, params, _, _ = _criterio(cx, termo)
    return cx.execute(f"SELECT COUNT(*) FROM precatorio_atual WHERE {w}", params).fetchone()[0]


def busca_pagina(cx, termo, limite=50, offset=0, ordem="valor"):
    """busca() + conta() numa passada so': (linhas, criterio, total). O total vem de
    COUNT(*) OVER(), calculado sobre TODAS as linhas que casam antes do LIMIT. Pagina
    alem da ultima volta sem linhas -- e sem total --, dai' o conta() so' nesse caso."""
    w, params, ob, criterio = _criterio(cx, termo, ordem)
    rs = cx.execute(f"SELECT *, COUNT(*) OVER() AS _total FROM precatorio_atual WHERE {w} "
                    f"ORDER BY {ob} LIMIT ? OFFSET ?", params + [limite, offset]).fetchall()
    if rs:
        return rs, criterio, rs[0]["_total"]
    return rs, criterio, (0 if offset == 0 else conta(cx, termo))


# SQLite LIKE so' faz case-fold de ASCII: 'Á' (maiusculo) nao bate com 'á' (minusculo)
# do jeito que o SQLite compara por padrao. Como os nomes vem em Title Case ("José
# Silva", nao "JOSÉ SILVA"), termo.upper() de antes quebrava TODA busca por nome com
# acento -- "sátiro" virava "SÁTIRO" e nunca casava com o "Sátiro" gravado. Corrigido
# tirando o acento dos DOIS lados (termo e coluna) antes de comparar.
def _sem_acento(s):
    """'José Sátiro' -> 'JOSE SATIRO'. Usado no termo de busca (lado Python). E' a
    mesma funcao que gravou credor_norm no build (credor_norm.normaliza)."""
    return CN.normaliza(s)


def _sem_acento_sql(coluna):
    """Mesma normalizacao de _sem_acento(), do lado do banco. SQLite nao tem funcao de
    acento nativa; a 1a tentativa encadeou REPLACE por par acentuado/nu (48 pares =
    48 niveis de aninhamento) e funcionou no SQLite 3.49 local mas estourou
    'parser stack overflow' no SQLite 3.45 da VPS (stack do parser menor). Trocado
    por funcao SQL registrada em conecta() (SEM_ACENTO), que chama _sem_acento() --
    1 nivel de aninhamento, mesma logica dos dois lados por construcao. Hoje so' serve
    a banco anterior ao credor_norm (ver _where_credor)."""
    return f"SEM_ACENTO({coluna})"


def _where_credor(cx, termo):
    """WHERE por nome MULTI-PALAVRA: cada palavra e' um filtro "contem" separado,
    combinados por AND (ordem nao importa). Assim 'nilza calatrone' (ou 'calatrone
    nilza') acha o registro exato mesmo com 136 'nilza' na base -- antes, um LIKE unico
    so casava a string inteira e adjacente, e a lista (ordenada por valor) cortava os
    menores. Acento e' ignorado dos dois lados (ver _sem_acento).

    Palavra com 3+ letras vai para o FTS5 trigram (credor_fts): "contem" por indice.
    As outras ficam como LIKE em credor_norm, aplicado so' sobre o que o FTS ja filtrou:
    as de menos de 3 letras (nao formam trigrama) e as com % ou _, que no LIKE sempre
    foram curinga e no FTS seriam literais. Banco sem credor_fts (anterior a
    2026-09-29) cai no caminho antigo: SEM_ACENTO(credor) LIKE, linha a linha."""
    palavras = [w for w in re.split(r"\s+", _sem_acento(termo).strip()) if w]
    if not palavras:
        return "0", []
    if not CN.existe(cx):
        col = _sem_acento_sql("credor")
        return " AND ".join(f"{col} LIKE ?" for _ in palavras), [f"%{w}%" for w in palavras]
    fts = [w for w in palavras if len(w) >= 3 and "%" not in w and "_" not in w]
    like = [w for w in palavras if not (len(w) >= 3 and "%" not in w and "_" not in w)]
    partes, params = [], []
    if fts:
        # cada palavra vira uma frase entre aspas (aspas internas dobradas): dentro da
        # frase nada e' sintaxe do FTS -- AND/OR/NEAR/*/( digitados sao so' texto
        partes.append(f"id IN (SELECT rowid FROM {CN.FTS} WHERE {CN.FTS} MATCH ?)")
        params.append(" AND ".join('"' + w.replace('"', '""') + '"' for w in fts))
    for w in like:
        partes.append("credor_norm LIKE ?")
        params.append(f"%{w}%")
    return " AND ".join(partes), params


def conta_credor(cx, termo):
    """Quantos precatorios casam o nome (total, sem o LIMIT) -- p/ a UI avisar 'mostrando
    X de N; refine com o sobrenome'."""
    frag, params = _where_credor(cx, termo)
    return cx.execute(f"SELECT COUNT(*) FROM precatorio_atual WHERE {frag}", params).fetchone()[0]


def _pago_cnj(cx, ibge, tribunal):
    """Pago no ano-ref pela administracao DIRETA, NAQUELE tribunal (tabela mapa_cnj).

    Duas correcoes sobre a versao anterior, que varria o CSV cru a cada consulta:
      1. FILTRA POR TRIBUNAL. Antes somava TJ + TRT + TRF e entregava o total como
         orcamento da fila do TJ. Em Conceicao da Barra isso dava R$ 271 mil onde o
         pago ao TJES foi R$ 202 mil — a fila de um tribunal nao e' paga com o que
         o ente pagou a outro.
      2. Le do banco, nao do CSV: eram 12.234 linhas relidas por precatorio exibido.
    Cai para o CSV so em banco antigo, sem a tabela (carga: scripts/db_mapa.py).
    """
    if not ibge:
        return None
    if MAPA.existe(cx):
        return MAPA.pago_no_tribunal(cx, ibge, tribunal)
    p = os.path.join(BASE, "data", "cnj_mapa_anual_raw.csv")
    if not os.path.exists(p):
        return None
    v = 0.0
    for x in csv.DictReader(open(p, encoding="utf-8-sig")):
        if x.get("PREC_cod_municipio") != ibge or x.get("PREC_DD_sig_tribunal") != tribunal:
            continue
        tipo = (x.get("PREC_DD_dsc_tipo_entidade_devedora") or "").upper()
        if "DIRETA" in tipo and "INDIRETA" not in tipo:
            v += float(x.get("PREC_DD_vlr_pago_ano_referencia") or 0)
    return v or None


def quitacao_por_natureza(cx, ente_id, tribunal):
    """Taxa de quitacao por natureza (Alimentar x Comum) na ultima coorte JA
    VENCIDA — o achado do parecer do card #3373 (Rio, 2026-08-27): a fila so' faz
    sentido quebrada por natureza. Na coorte de 2025 do Municipio do Rio (a ultima
    ja vencida), 98,0% dos alimentares estavam quitados contra 2,5% dos comuns —
    um numero agregado de fila (so' "38% quitado") esconderia exatamente o que
    decide se um credito especifico sai no prazo ou fica represado.

    So' o TJRJ tem essa base hoje (ver carrega_natureza_tjrj em db_build.py — os
    demais coletores descartam os itens ja quitados na propria coleta). Devolve
    None quando nao ha dado — o chamador trata como "nao disponivel", nunca como
    "quitacao zero".
    """
    if not ente_id:
        return None
    row = cx.execute(
        "SELECT MAX(ano_orcamento) FROM fila_natureza_stats "
        "WHERE ente_id=? AND tribunal=? AND ano_orcamento<?",
        (ente_id, tribunal, EXERCICIO)).fetchone()
    ano = row[0] if row else None
    if ano is None:
        return None
    por_nat = {}
    for nat, itens, quit_, vab in cx.execute(
            "SELECT natureza, itens, quitados, valor_aberto FROM fila_natureza_stats "
            "WHERE ente_id=? AND tribunal=? AND ano_orcamento=? AND itens>0",
            (ente_id, tribunal, ano)):
        por_nat[nat] = {"itens": itens, "quitados": quit_,
                        "quitado_pct": round(100 * quit_ / itens, 1),
                        "valor_aberto": round(vab or 0.0, 2)}
    if len(por_nat) < 2:
        return None                       # so' informa quando ha' o que comparar
    return {"ano_coorte": ano, "por_natureza": por_nat}


def _pago_cnj_medio(cx, ibge, tribunal, ano_ref=None):
    """Pago (admin direta) ao `tribunal` no EXERCICIO ANTERIOR (2025), e a serie.

    Ate 2026-08-20 isto era MEDIA dos ultimos 5 anos (para suavizar volatilidade --
    Varginha/MG: R$1,78mi em 2024 vs R$84mil em 2025 fazia o ritmo de 1 ano so
    projetar 2062, a media 2032). Revertido a pedido do usuario (2026-08-31): o
    ritmo real passa a refletir especificamente o exercicio anterior (2025) -- o
    MESMO ano-base que o resto do modelo ja usa (mora em 1o/jan, RCL do exercicio
    financeiro anterior no §23) -- em vez de uma media multi-ano que dilui esse
    ano de referencia. Mantem o nome da funcao (chamada em 1 lugar) e a assinatura
    (valor, serie) para nao quebrar UI/PDF, que ja tratam serie de 1 item como
    'ultimo ano medido' (ver ritmoN/ritmo_n em ui.html/parecer_pdf.py)."""
    ano_ref = ano_ref or (EXERCICIO - 1)
    if not ibge or not MAPA.existe(cx):
        return None, []
    row = cx.execute(
        "SELECT SUM(vlr_pago) v FROM mapa_cnj WHERE ibge=? AND tribunal=? "
        "AND tipo_entidade='Direta' AND ano_ref=?",
        (ibge, tribunal, ano_ref)).fetchone()
    if row is None or row["v"] is None:
        return None, []
    valor = round(float(row["v"]), 2)
    return valor, [(ano_ref, valor)]


def _rateio_tribunal(cx, ibge, tribunal):
    """Fracao do teto do §23 que cabe a UMA justica.

    O teto (1% da RCL) e' o orcamento do ENTE para precatorios em TODAS as justicas
    (estadual, trabalhista, federal). A fila do parecer e' de UMA delas, e so o
    pagamento a ela faz ESSA fila andar. Aplicar o teto inteiro a uma fila superestima
    (ex.: Acajutiba/BA paga TJBA e TRT5; pelo teto cheio a fila do TJBA "anda" com
    dinheiro que na verdade vai pro TRT5). O dashboard antigo repartia o teto por
    justica (calc_corte: proporcional ao estoque); isso se perdeu na migracao p/ o
    banco e e' o que esta funcao restaura.

    PREFERE FILAS REAIS: quando o banco tem a fila itemizada de >=2 justicas do ente,
    reparte pelo VALOR ELEGIVEL (orcamento <= exercicio = a mora/estoque vencido) de
    cada uma -- o metodo do dashboard antigo, validado no ES (Cariacica: TJES 82,4%,
    identico ao antigo, contra 91,2% que o Mapa dava). So CAI para o Mapa Anual do CNJ
    (agregado, peso = abertura + expedidos) como aproximacao PROVISORIA onde faltam as
    filas das outras justicas (ex.: BA/MG, sem TRT/TRF coletados ainda). `fonte`=
    'filas'|'mapa'. fracao=1.0 quando o ente so aparece num tribunal ou nao ha dado."""
    if not ibge:
        return {"fracao": 1.0, "por_tribunal": None, "fonte": None}

    def _monta(pesos, fonte):
        total = sum(pesos.values())
        if total <= 0 or len(pesos) <= 1 or pesos.get(tribunal, 0.0) <= 0:
            return None
        return {"fracao": round(pesos[tribunal] / total, 4), "fonte": fonte,
                "por_tribunal": [{"tribunal": t, "estoque": round(v, 2), "pct": round(100 * v / total, 1)}
                                 for t, v in sorted(pesos.items(), key=lambda kv: -kv[1])]}

    # (1) FILAS REAIS no banco -- valor elegivel (orcamento <= exercicio) por tribunal
    reais = {}
    for r in cx.execute("SELECT tribunal, SUM(valor) v FROM precatorio_atual "
                        "WHERE ibge=? AND valor IS NOT NULL AND ano_orcamento<=? GROUP BY tribunal",
                        (ibge, EXERCICIO)):
        if r["v"] and r["v"] > 0:
            reais[r["tribunal"]] = float(r["v"])
    por_fila = _monta(reais, "filas")
    if por_fila:
        return por_fila

    # (2) FALLBACK PROVISORIO: Mapa Anual do CNJ (agregado). Peso = SALDO DEVEDOR de fim
    # de ano -- aproxima o estoque DEVIDO (o que o §23 paga) e casa bem com a fila real:
    # Varginha TJMG saldo R$2,73mi ~ elegivel real R$2,50mi (o abertura+expedidos dava
    # R$5,69mi, 2x inflado, porque e' fluxo do ano, nao estoque pendente). So cai p/
    # abertura+expedidos quando TODOS os saldos vierem 0 (ente quitado no ano-ref).
    if not MAPA.existe(cx):
        return {"fracao": 1.0, "por_tribunal": None, "fonte": None}
    pt = (MAPA.resumo_municipio(cx, ibge) or {}).get("por_tribunal") or []
    por_saldo, por_fluxo = {}, {}
    for x in pt:
        t = x["tribunal"]
        por_saldo[t] = por_saldo.get(t, 0.0) + float(x.get("saldo") or 0)
        por_fluxo[t] = por_fluxo.get(t, 0.0) + float(x.get("anterior") or 0) + float(x.get("expedidos") or 0)
    pesos = {t: v for t, v in por_saldo.items() if v > 0} or {t: v for t, v in por_fluxo.items() if v > 0}
    return _monta(pesos, "mapa") or {"fracao": 1.0, "por_tribunal": None, "fonte": None}


# Tribunais cuja `ordem` e' UMA sequencia para o grupo de entes (devedor + autarquias), nao uma
# numeracao por ente. Nesses, reintercalar por data desfaz a ordem oficial (TJGO, Estado: 99,9%
# dos itens mudavam de posicao, deslocamento medio de ~750 posicoes). Medido em 09/10/2026 a
# partir do banco: o mesmo formato aparece tambem no TJPB, TJMA, TJPR, TJMT e em parte do TJSP
# e do TJRS -- entram aqui um a um, depois de validar. TJMG, TJRJ, TJES, TJPE e TJSC numeram por ente.
TRIBUNAIS_ORDEM_UNICA = {"TJGO"}


def ordem_e_sequencia_unica(fila):
    """True quando a `ordem` publicada e' uma unica sequencia para todos os entes da fila:
    sem repeticao relevante (<= 2% dos itens) e densidade (itens / maior ordem) de ate' 1,05.
    Numeracao por ente (TJMG: Estado e IPSEMG ambos comecam em 1) da densidade >> 1."""
    ords = [it["ordem"] for it in fila if it.get("ordem") is not None]
    if len(ords) < 2:
        return False
    dup = len(ords) - len(set(ords))
    return len(ords) / max(ords) <= 1.05 and dup <= 0.02 * len(ords)


def _merge_por_apresentacao(fila, ordem_unica=False):
    """Fila combinada do municipio (prefeitura + autarquias): cada ENTE preserva a ordem
    OFICIAL da fonte (que ja embute preferencia de alimentares/superpref) e os entes sao
    INTERCALADOS pela DATA DE APRESENTACAO do proximo item de cada um — a data so intercala,
    nunca reordena dentro do ente. Sem a data (TJMG), cai para a ordem. Escreve `mpos`
    (posicao na fila combinada), que o modelo_p23._ordem consome.

    ordem_unica=True: a ordem oficial ja' e' a fila combinada (TJGO) — so' ordena por ela
    (empate: data de apresentacao, depois ente)."""
    if ordem_unica:
        out = sorted(fila, key=lambda x: (x["ordem"] if x["ordem"] is not None else 10**9,
                                          x.get("apres") or "9999", str(x.get("ente_id"))))
        for i, it in enumerate(out, 1):
            it["mpos"] = i
        return out
    grupos = {}
    for it in fila:
        grupos.setdefault(it.get("ente_id"), []).append(it)
    for g in grupos.values():
        g.sort(key=lambda x: x["ordem"] if x["ordem"] is not None else 10**9)
    ptr = {e: 0 for e in grupos}
    out = []
    while True:
        vivos = [e for e in grupos if ptr[e] < len(grupos[e])]
        if not vivos:
            break
        e = min(vivos, key=lambda e: ((grupos[e][ptr[e]].get("apres") or "9999"), str(e)))
        it = grupos[e][ptr[e]]
        ptr[e] += 1
        it["mpos"] = len(out) + 1
        out.append(it)
    return out


_ENQ_MG = None


def enquadramento_mg(ibge):
    """Mora e faixa OFICIAIS do TJMG (Enquadramento EF2026, ref. dez/2025), por IBGE.

    Existe porque a mora inferida da lista publicada e' quase sempre MENOR que a
    oficial: em 99 dos 532 municipios de MG com fila, a fila de hoje nao tem nenhum
    precatorio vencido (mora = 0) enquanto o enquadramento aponta mora > 0 -- o
    vencido saiu da lista por suspensao, cancelamento ou acordo, sem pagamento.
    Mostrar so o numero calculado faz o parecer dizer "R$ 0,00 em mora" para um
    ente que nao paga ha anos. Ver db_nacp.plano() para a fonte equivalente na BA.
    """
    global _ENQ_MG
    if _ENQ_MG is None:
        _ENQ_MG = {}
        p = os.path.join(BASE, "data", "enquadramento_definitivo.csv")
        if os.path.exists(p):
            for row in csv.DictReader(open(p, encoding="utf-8-sig")):
                k = (row.get("codigo_ibge") or "").strip()
                if not k:
                    continue
                def _f(c):
                    v = (row.get(c) or "").strip()
                    try:
                        return float(v)
                    except ValueError:
                        return None
                _ENQ_MG[k] = {"mora": _f("divida_mora_tribunais"),
                              "pct": _f("percentual_p23_pct"),
                              "prop_mora": _f("proporcao_mora_rcl_pct"),
                              "inciso": (row.get("inciso_p23") or "").strip() or None,
                              # quem publicou / qual documento / de quando: as tres
                              # coisas separadas, para a tela poder dizer a frase inteira
                              "fonte": "TJMG (Tribunal de Justiça de Minas Gerais)",
                              "documento": ("Entes Federados de MG — EF 2026 — CF art. 100 §23: "
                                            "proporção das dívidas para fins de rateio do depósito"),
                              "referencia": "31/12/2025"}
    return _ENQ_MG.get(str(ibge or "").strip())


_REPASSE = None


def fracao_repasse_fila(ibge, tribunal):
    """Fracao do orcamento TEORICO do §23 (RCL x percentual) que de fato chega na
    ordem cronologica. Default 1.0 (100%) para todo ente sem entrada no CSV.

    Existe porque o teto do §23 e' um limite de DEPOSITO, nao de PAGAMENTO A CREDOR:
    alguns entes reservam parte do repasse para outro canal antes de chegar na fila
    (o caso medido e' Belem/PA, onde o Plano de Pagamento 2026 do TJPA diz
    explicitamente que os repasses vao 50% para a conta de acordos e 50% para a
    ordem cronologica). Sem este ajuste, o motor generico projetava Belem para
    2027 (dividindo pelo orcamento TEORICO inteiro) contra 2030 da conta manual
    (que usou so' a metade que chega na fila).

    So' revela isso o documento oficial do tribunal (plano/ato de rateio) — nao ha'
    como derivar da fila. `data/repasse_fila_pct.csv`, um ente por linha; acrescentar
    UF/ente = achar o plano dele e por uma linha, sem tocar em codigo.
    """
    global _REPASSE
    if _REPASSE is None:
        _REPASSE = {}
        arq = os.path.join(BASE, "data", "repasse_fila_pct.csv")
        if os.path.exists(arq):
            for row in csv.DictReader(open(arq, encoding="utf-8-sig")):
                k = (str(row.get("codigo_ibge") or "").strip(), (row.get("tribunal") or "").strip())
                _REPASSE[k] = row
    row = _REPASSE.get((str(ibge or "").strip(), tribunal))
    if not row or not row.get("pct_fila"):
        return 1.0, None
    return float(row["pct_fila"]) / 100, row


_EDITAIS = None


def edital_acordo(ibge):
    """Edital de acordo direto do ente (art. 102 do ADCT), se houver.

    E o PRIMEIRO filtro do time comercial: onde ha edital, o credor pode receber a
    vista do proprio municipio mediante desagio, e a nossa proposta concorre com esse
    preco publico. So o regime especial pode ter (em MG, 25 dos 104 entes especiais
    tem; dos 749 do regime geral, um).

    NACIONAL desde 28/08/2026: le TODOS os `data/editais_acordo_*.csv`, um por UF —
    `_mg` (gerado por scripts/carrega_editais_mg.py a partir dos PDFs da CEPREC/TJMG),
    `_pa` e `_ba`. Antes lia so' o de MG, e por isso dizia "nao tem edital" para
    Belem/PA, que mantem canal permanente com 40% de desagio: erro que jogava fora
    justamente o numero que a proposta comercial precisa bater. Acrescentar UF =
    largar mais um CSV na pasta, sem tocar no codigo.

    Quando o mesmo ente tem varios editais, vence o ABERTO; nao havendo, o de
    inscricao mais recente — um edital de 2023 nao descreve a alternativa de hoje.

    Devolve tambem `aberto`: um edital com inscricao encerrada nao e mais alternativa
    para quem nao se inscreveu — tratar os dois como a mesma coisa faria o time
    descartar credor que hoje nao tem para onde ir. E `desagio_confirmado`: ha' ente
    (os da BA) em que so' a EXISTENCIA do canal esta verificada, nao o percentual;
    apresentar um desagio nao conferido como preco de referencia seria pior do que
    nao ter nenhum.
    """
    global _EDITAIS
    if _EDITAIS is None:
        _EDITAIS = {}
        hoje_ = _date.today().isoformat()

        def _rank(row):
            """Aberto primeiro; depois inscricao mais recente."""
            fecha = (row.get("inscricao_fecha") or "")[:10]
            ab = bool(fecha) and fecha >= hoje_ and row.get("situacao") != "prejudicado"
            return (1 if ab else 0, (row.get("inscricao_abre") or "")[:10],
                    (row.get("consultado_em") or "")[:10])

        for arq in sorted(glob.glob(os.path.join(BASE, "data", "editais_acordo_*.csv"))):
            for row in csv.DictReader(open(arq, encoding="utf-8-sig")):
                k = str(row.get("codigo_ibge") or "").strip()
                if not k:
                    continue
                if k not in _EDITAIS or _rank(row) > _rank(_EDITAIS[k]):
                    _EDITAIS[k] = row
    e = _EDITAIS.get(str(ibge or "").strip())
    if not e:
        return None

    def _f(c):
        try:
            return float(e.get(c) or 0) or None
        except ValueError:
            return None

    hoje = _date.today().isoformat()
    fecha = (e.get("inscricao_fecha") or "")[:10]
    prejudicado = e.get("situacao") == "prejudicado"
    aberto = bool(fecha) and fecha >= hoje and not prejudicado
    return {
        "tem": True, "aberto": aberto, "prejudicado": prejudicado,
        "edital": e.get("edital"), "municipio": e.get("municipio"),
        "situacao": e.get("situacao"), "observacao": e.get("observacao") or None,
        "desagio_min_pct": _f("desagio_min_pct"), "desagio_max_pct": _f("desagio_max_pct"),
        "desagio_confirmado": _f("desagio_min_pct") is not None or _f("desagio_max_pct") is not None,
        "valor_certame": _f("valor_certame"),
        "inscricao_abre": e.get("inscricao_abre") or None, "inscricao_fecha": fecha or None,
        "ano_venc_limite": e.get("ano_venc_limite") or None,
        "validade_pagamento": e.get("validade_pagamento") or None,
        "url": e.get("url") or None, "fonte": e.get("fonte"),
        "consultado_em": e.get("consultado_em"),
    }


def fora_da_fila(cx, r):
    """Precatorios do mesmo ente/tribunal que NAO disputam o orcamento.

    Suspenso ou sem ordem cronologica sai da fila e, por tabela, sai da conta de
    mora -- e e' justamente onde costuma estar o passivo antigo. Sem esta linha o
    parecer mostra um estoque menor do que o real sem dizer que filtrou nada.
    """
    if r["ibge"]:
        q = ("SELECT p.valor v, p.ano_orcamento ano, p.situacao s, p.suspenso susp "
             "FROM precatorio_atual p JOIN ente e ON e.id = p.ente_id "
             "WHERE e.ibge = ? AND p.tribunal = ? AND (p.ordem IS NULL OR p.suspenso = 1)")
        rows = list(cx.execute(q, (r["ibge"], r["tribunal"])))
    else:
        q = ("SELECT valor v, ano_orcamento ano, situacao s, suspenso susp "
             "FROM precatorio_atual WHERE ente_id = ? AND (ordem IS NULL OR suspenso = 1)")
        rows = list(cx.execute(q, (r["ente_id"],)))
    if not rows:
        return None
    valor = sum((x["v"] or 0.0) for x in rows)
    vencidos = [x for x in rows if (x["ano"] or 9999) < EXERCICIO]
    motivos = sorted({(x["s"] or ("suspenso" if x["susp"] else "sem ordem")) for x in rows})
    return {"n": len(rows), "valor": round(valor, 2),
            "n_vencidos": len(vencidos),
            "valor_vencido": round(sum((x["v"] or 0.0) for x in vencidos), 2),
            "motivos": motivos}


def contexto(cx, r, todos_itens=False):
    """Roda o modelo unico sobre a fila do MUNICIPIO (prefeitura + autarquias).

    todos_itens=True (pagina 'Saude do ente'): devolve a fila INTEIRA em fila_itens (sem a
    janela de 30 em volta do buscado) e, em cada item, tambem o ano no ritmo real.

    E' a RCL municipal que banca o §23, entao a fila que disputa o orcamento e' a
    consolidada — nao a do ente isolado. Cai para o ente so em orgao sem municipio
    (estadual/federal). A ordem da fila combinada e' cronologica por DATA DE APRESENTACAO
    (ver _merge_por_apresentacao), nao a ordem-por-ente empilhada.
    """
    if r["ibge"]:
        fila = [dict(x) for x in cx.execute(
            "SELECT p.id, p.ente_id, p.ordem, p.valor AS val, p.ano_orcamento AS ano, p.numero, "
            "p.data_apresentacao AS apres, p.situacao AS situacao, p.natureza AS natureza "
            "FROM precatorio_atual p JOIN ente e ON e.id = p.ente_id "
            "WHERE e.ibge = ? AND p.tribunal = ? AND p.ordem IS NOT NULL",
            (r["ibge"], r["tribunal"]))]
    else:
        fila = [dict(x) for x in cx.execute(
            "SELECT id, ente_id, ordem, valor AS val, ano_orcamento AS ano, numero, "
            "data_apresentacao AS apres, situacao AS situacao, natureza AS natureza "
            "FROM precatorio_atual WHERE ente_id = ? AND ordem IS NOT NULL", (r["ente_id"],))]
    if not fila:
        return None
    fila = _merge_por_apresentacao(
        fila, ordem_unica=(r["tribunal"] in TRIBUNAIS_ORDEM_UNICA and ordem_e_sequencia_unica(fila)))

    mora, n_mora, estoque, n_tot = M.mora_da_fila(fila, EXERCICIO)

    # Mora e faixa OFICIAIS (Comite Gestor, apuradas em 1o/jan) tem precedencia
    # sobre as inferidas da fila: a lista publicada pode nao conter todo o estoque
    # vencido, e o degrau do §23 e' decisao homologada, nao estimativa nossa.
    mora_oficial = pct_oficial = valor_oficial = None
    fonte_oficial = doc_oficial = ref_oficial = None
    if r["ibge"] and NACP.existe(cx):
        _p = NACP.plano(cx, r["ibge"])
        if _p:
            mora_oficial = _p.get("mora_1jan")
            pct_oficial = _p.get("pct_aplicado")
            # VALOR em reais publicado pelo tribunal: prevalece sobre RCL x % (o
            # tribunal calcula sobre a RCL DELE). Ver orcamento_anual em modelo_p23.
            valor_oficial = _p.get("valor_anual")
            fonte_oficial = "Comitê Gestor de Contas Especiais do tribunal"
            doc_oficial = "Plano Anual de pagamento do exercício (PA de fiscalização)"
            ref_oficial = "1º de janeiro"
    if mora_oficial is None and r["ibge"]:
        _e = enquadramento_mg(r["ibge"])
        if _e and _e.get("mora") is not None:
            mora_oficial, pct_oficial = _e["mora"], _e["pct"]
            fonte_oficial = _e["fonte"]
            doc_oficial = _e["documento"]
            ref_oficial = _e["referencia"]
    base_mora = mora_oficial if mora_oficial is not None else mora

    # Fila sem valor nao produz projecao: o acumulado seria zero e o parecer diria
    # "recebe no exercicio base" para qualquer posicao. Ver SEM_VALOR (TJPE).
    n_zerados = sum(1 for f in fila if not f.get("val"))
    prop_zerados = n_zerados / len(fila) if fila else 0.0
    sem_valor_confiavel = (not r["valor"]) or prop_zerados > 0.20
    out_motivo = None
    if sem_valor_confiavel:
        out_motivo = ("credito sem valor publicado" if not r["valor"]
                      else "fila com %.0f%% dos itens sem valor" % (prop_zerados * 100))

    cen = (M.projecao_cenarios(r["rcl"], base_mora, r["regime"] or "Comum",
                               pago_cnj=_pago_cnj(cx, r["ibge"], r["tribunal"]),
                               pct_oficial=pct_oficial, valor_oficial=valor_oficial)
           if (r["rcl"] or valor_oficial) and not sem_valor_confiavel else None)
    # RATEIO §23: o teto e' do ENTE p/ TODAS as justicas; esta fila e' de uma so.
    # A fracao (por estoque, Mapa CNJ) e' o quanto do teto cabe a esta justica.
    rateio = _rateio_tribunal(cx, r["ibge"], r["tribunal"])
    # E dentro do que cabe a esta justica, uma fracao do repasse pode ir para outro
    # canal (acordo) antes de chegar na ordem cronologica — ver fracao_repasse_fila.
    frac_repasse, repasse_info = fracao_repasse_fila(r["ibge"], r["tribunal"])
    frac = rateio["fracao"] * frac_repasse
    # por ID: o numero repete dentro do ente nas parcelas de precatorio parcelado,
    # e casar por numero devolvia sempre a primeira parcela — ano e posicao errados.
    alvo = next((f for f in fila if f.get("id") == r["id"]), None)
    if alvo is None:
        alvo = next((f for f in fila if f["numero"] == r["numero"]), None)
    out = {"n_total": n_tot, "estoque": estoque, "mora": mora, "n_mora": n_mora,
           "prop_mora": round(100 * mora / r["rcl"], 2) if r["rcl"] else None,
           "mora_oficial": mora_oficial, "pct_oficial": pct_oficial,
           "mora_oficial_fonte": fonte_oficial, "mora_oficial_documento": doc_oficial,
           "mora_oficial_ref": ref_oficial,
           "mora_oficial_sobre_rcl_pct": (round(100 * mora_oficial / r["rcl"], 2)
                                          if mora_oficial is not None and r["rcl"] else None),
           "base_mora_usada": "oficial" if mora_oficial is not None else "fila publicada",
           "fora_da_fila": fora_da_fila(cx, r),
           "cenarios": cen, "rateio": rateio, "sem_projecao_motivo": out_motivo,
           "prop_fila_sem_valor": round(prop_zerados, 3),
           "repasse_fila": ({"pct": round(frac_repasse * 100, 1),
                             "fonte": repasse_info.get("fonte"),
                             "observacao": repasse_info.get("observacao")}
                            if repasse_info else None),
           # frac COMBINADA (rateio entre justicas x repasse_fila): e' o que proj20
           # de fato usa para converter o teto do ente no orcamento desta fila. O
           # parecer() reusa este valor pronto — recompute-lo so' de rateio.fracao
           # (sem a fracao de repasse) mostraria orcamento maior do que o ano
           # projetado realmente supoe, os dois numeros do parecer se contradizendo.
           "frac_orcamento": frac,
           "quitacao_por_natureza": quitacao_por_natureza(cx, r["ente_id"], r["tribunal"]),
           "acumulado": None, "acumulado_bruto": None, "acumulado_a_financiar": None,
           "valor_provisionado": round(sum((f.get("val") or 0.0) for f in fila
                                           if M.provisionado(f)), 2),
           "n_superprecatorios": 0, "ano_previsto": None, "zera": None, "anos": {}}
    if cen and alvo:
        prev = {}
        for k in ("conservador", "central", "otimista"):
            proj = M.proj20(fila, cen[k] * frac, EXERCICIO, regime=r["regime"])   # frac: parcela do teto desta justica
            prev[k] = alvo.get("ano_previsto")
            if k == "central":
                out["n_superprecatorios"] = proj["n_sp"]
                out["zera"] = proj["zera"]
                # A reserva do §20 explica datas que a divisao simples nao explica:
                # em Ipatinga os 3 superprecatorios reservam MAIS que o orcamento
                # anual inteiro ate 2031, e a fila cronologica so volta a andar em
                # 2032. Sem esta linha o parecer mostra o ano sem mostrar a causa.
                res = proj.get("reservado") or {}
                out["reserva_p20"] = {str(a): round(v, 2) for a, v in sorted(res.items())}
                out["valor_superprecatorios"] = round(
                    sum(_val_sp for _val_sp in
                        (f.get("val") or 0.0 for f in fila if f.get("sp"))), 2)
                # Fila item a item, com acumulado corrido e o ano_previsto do cenario
                # central (JA escritos pelo proj20 acima) — alimenta a tabela "fila de
                # precatorios" do parecer, com o item buscado marcado. Acumulado em UMA
                # passada (nao chamar acumulado_ate por item: O(n^2) em file de 15 mil+
                # itens, caso de pseudo-municipios como o Estado de MG).
                JANELA = 30
                ordenada = M.ordena(fila)
                acc = 0.0
                itens_fila = []
                idx_alvo = None
                for i, f in enumerate(ordenada):
                    sp_f = bool(f.get("sp"))
                    if not sp_f:
                        acc += (f.get("val") or 0.0)
                    if f is alvo:
                        idx_alvo = i
                    itens_fila.append({
                        "posicao": i + 1, "id": f.get("id"), "numero": f.get("numero"),
                        "data_apresentacao": f.get("apres"), "ano_orcamento": f.get("ano"),
                        "natureza": f.get("natureza"), "situacao": f.get("situacao"),
                        "valor": round(f.get("val") or 0.0, 2),
                        "ano_previsto": f.get("ano_previsto"),
                        "acumulado": None if sp_f else round(acc, 2),
                        "superprecatorio": sp_f, "provisionado": bool(f.get("provisionado")),
                        "e_buscado": f is alvo,
                    })
                if idx_alvo is not None and len(itens_fila) > (2 * JANELA + 1) and not todos_itens:
                    ini = max(0, idx_alvo - JANELA)
                    fim = min(len(itens_fila), idx_alvo + JANELA + 1)
                    out["fila_itens"] = itens_fila[ini:fim]
                    out["fila_itens_janela"] = {"inicio": ini + 1, "fim": fim,
                                                "total": len(itens_fila), "truncada": True}
                else:
                    out["fila_itens"] = itens_fila
                    out["fila_itens_janela"] = {"inicio": 1, "fim": len(itens_fila),
                                                "total": len(itens_fila), "truncada": False}
        acum = M.acumulado_ate(fila, alvo)
        # o que falta FINANCIAR (exclui itens ja provisionados) — e' o numero que
        # bate com ano_previsto, que o proj20 corrigido ja calcula sem eles.
        # Ver SITUACOES_PROVISIONADO em modelo_p23: hoje so o TJCE publica esse dado.
        acum_financiar = M.acumulado_ate(fila, alvo, excluir_provisionado=True)

        # CENARIO DO RITMO OBSERVADO — o que o ente PAGOU de fato, nao o teto.
        # Existe porque a projecao principal assume que o devedor gasta o limite
        # legal todo ano, e quase nenhum gasta: Pedro Canario/ES tem teto de
        # R$ 1,29 mi e pagou R$ 396 mil ao TJES em 2025 (31%). Pelo teto o
        # precatorio sai em 2028; pelo ritmo real, em 2031. Quem le so o numero
        # grande decide com 3 anos de otimismo. O ritmo e' o do PROPRIO tribunal
        # da fila — pagamento feito ao TRF2 nao anda a fila do TJES.
        # Exercicio anterior (2025) especificamente, nao mais media de anos — ver
        # docstring de _pago_cnj_medio para o porque da reversao.
        pago_bruto, serie_pago = _pago_cnj_medio(cx, r["ibge"], r["tribunal"]) if r["ibge"] else (None, [])
        # O 'pago' do Mapa CNJ e' o que o tribunal desembolsou no ano PARA TODOS OS
        # CANAIS (cronologica + acordo, quando o ente tem um) — nao so' a fila. Sem
        # este ajuste o "ritmo observado" ficava MAIS RAPIDO que "o limite da lei ja
        # ratado para a fila" (paradoxo visto em Belem: ritmo 2030 x limite 2034,
        # quando o teto e' o MAXIMO que pode ir a QUALQUER credor daquele tribunal).
        # Mesma fracao_repasse_fila do cenario do teto; sem doc especifico do
        # ritmo, e' a melhor estimativa disponivel — nao uma medicao direta.
        pago = pago_bruto * frac_repasse if pago_bruto else pago_bruto
        if acum is not None and pago and pago > 0:
            # MESMO motor do cenario do teto, so trocando o orcamento pelo que o ente
            # paga de fato. A divisao simples que havia aqui ignorava a reserva do §20
            # e o piso do §5o, e errava para o lado otimista em ente com
            # superprecatorio (Passos: dizia 2028 onde a conta honesta da ~2039).
            M.proj20(fila, pago, EXERCICIO, regime=r["regime"])
            ano_ritmo = alvo.get("ano_previsto")
            ritmo_por_id = {f.get("id"): f.get("ano_previsto") for f in fila} if todos_itens else None
            out["ritmo_observado"] = {
                "pago_no_ano": pago,                       # MEDIA dos anos disponiveis
                "pago_no_ano_bruto": pago_bruto if frac_repasse < 1.0 else None,
                "anos_media": len(serie_pago),
                "serie_pago": serie_pago,
                "pago_ultimo": serie_pago[0][1] if serie_pago else None,
                "anos": (ano_ritmo - EXERCICIO) if ano_ritmo else None,
                "ano_previsto": ano_ritmo,
                "pct_do_teto": (round(100 * pago / cen["teto_p23"], 1)
                                if cen.get("teto_p23") else None)}
            # proj20 escreve ano_previsto na fila; devolver o cenario central para
            # nao deixar o item marcado com o ritmo para quem ler depois
            M.proj20(fila, cen["central"] * frac, EXERCICIO, regime=r["regime"])
            if ritmo_por_id is not None:
                for it in out.get("fila_itens") or []:
                    it["ano_ritmo"] = ritmo_por_id.get(it["id"])
        elif acum is not None:
            out["ritmo_observado"] = {"pago_no_ano": pago or 0.0, "anos": None,
                                      "ano_previsto": None, "pct_do_teto": 0.0}

        out["e_superprecatorio"] = bool(alvo.get("sp"))
        out["alvo_provisionado"] = bool(alvo.get("provisionado"))
        # "anos" e' a divisao simples acumulado/orcamento (atalho de leitura, sem
        # rodar a fila inteira); tem de usar a MESMA base que ano_previsto (o
        # proj20 corrigido ja tira o provisionado do caminho), senao as duas contas
        # do parecer se contradizem.
        acum_p_anos = acum_financiar if acum_financiar is not None else acum
        out.update(acumulado=acum,
                   acumulado_bruto=M.acumulado_ate(fila, alvo, so_normal=False),
                   acumulado_a_financiar=acum_financiar,
                   ano_previsto=prev["central"], ano_previsto_por_cenario=prev,
                   anos={k: M.anos_ate(acum_p_anos, cen[k] * frac) for k in prev})
    return out


def _bloco_plano(cx, r, avisos):
    """Plano anual do §23 homologado pelo Comite Gestor + conformidade do ente.

    ATENCAO — DOIS NUMEROS QUE PARECEM O MESMO E NAO SAO. Confundi-los ja produziu
    analise errada, entao ficam em campos separados e com nomes diferentes:

      teto_p23      = RCL x pct        -> LIMITE anual de pagamento. E' o que
                                          drena a FILA nos anos seguintes. Fica em
                                          'projecao'. (Lauro de Freitas: R$ 11,17 mi)
      valor_anual   = plano do Comite  -> o que o ente tem de desembolsar ESTE ano
                                          para zerar a mora que ja venceu. NAO e' a
                                          velocidade da fila. (mesmo ente: R$ 53,7 mil)

    O plano e' pequeno quando a mora e' pequena — o ente esta em dia, nao parado.
    Usar valor_anual para drenar a fila projetaria seculos; usar teto_p23 como
    "quanto ele vai pagar este ano" superestima em ~200x. Cada um no seu lugar.

    Tambem devolve a MORA OFICIAL (apurada em 1o/jan pelo tribunal), que e' mais
    confiavel que a mora inferida da fila: a lista publicada pode nao conter todo
    o estoque vencido (ver gap expedicao-vs-publicacao).
    """
    if not r["ibge"] or not NACP.existe(cx):
        return None
    p = NACP.plano(cx, r["ibge"])
    conf = NACP.conformidade(cx, r["ibge"])
    if not p and not conf:
        return None

    if conf and conf["codigo"] == "bloqueio":
        avisos.append(
            f"O tribunal bloqueou valores do ente via SISBAJUD em {conf['em']} "
            f"(PA {conf['pa']}): o pagamento do plano anual estava atrasado e teve de "
            f"ser forçado judicialmente.")
    elif conf and conf["codigo"] == "regular":
        avisos.append(
            f"O Núcleo de Precatórios certificou em {conf['em']} que o ente está REGULAR "
            f"com o Plano de Pagamento — a fila está andando por força do plano homologado.")
    elif conf and conf["codigo"] == "irregular":
        avisos.append(f"O Núcleo de Precatórios certificou em {conf['em']} que o ente está "
                      f"IRREGULAR com o Plano de Pagamento.")

    if p and p.get("mora_1jan") is not None:
        avisos.append(
            f"Mora oficial apurada pelo Comitê Gestor em 1º/jan/{p['ano']}: "
            f"{_brl(p['mora_1jan'])}. É essa a base do §23 — não o “saldo devedor” do "
            f"Mapa do CNJ, que inclui dívida ainda dentro do prazo.")
    return {"plano": p, "conformidade": conf}


def _brl(v):
    if v is None:
        return "—"
    return "R$ " + f"{v:,.2f}".replace(",", "\x00").replace(".", ",").replace("\x00", ".")


def _e_estado(r):
    """Devedor e' um Estado (pseudo-ibge de 2 digitos), nao um municipio."""
    try:
        return len(str(r["ibge"] or "")) == 2
    except (KeyError, IndexError):
        return False


def _bloco_pagamento(cx, r, avisos):
    """O ente esta pagando? (Mapa Anual do CNJ, por tribunal.)

    A fila diz QUANTO se deve e em que ordem; ela nao diz se o devedor honra a fila.
    Este bloco e' a outra metade: pago/estoque no ano-ref, aberto por tribunal.

    RECONCILIACAO — os dois dados divergem POR CONSTRUCAO e nenhum corrige o outro:
    o saldo do Mapa e' a posicao de 31/12 do ano-ref, a fila e' a lista do exercicio
    seguinte. "Saldo zero no Mapa + fila cheia na LUP" nao e' erro: e' um ente em dia
    cuja fila e' toda nova. Sem dizer isso, quem le conclui que uma das fontes esta
    quebrada.
    """
    if not r["ibge"]:
        return None
    res = MAPA.resumo_municipio(cx, r["ibge"])
    if not res:
        return None

    deste = next((x for x in res["por_tribunal"] if x["tribunal"] == r["tribunal"]), None)
    if deste:
        if deste["codigo"] == "nao_pagou":
            avisos.append(
                f"O Mapa Anual do CNJ (ref. {deste['ano_ref']}) registra R$ 0 pago ao "
                f"{r['tribunal']} {'neste Estado' if _e_estado(r) else 'neste município'}, com saldo devedor remanescente: o ente "
                f"não honrou a fila deste tribunal no último ano medido.")
        elif deste["codigo"] in ("quitou", "quitou_quase_tudo") and (r["ano_orcamento"] or 0) >= EXERCICIO:
            avisos.append(
                f"O ente quitou o estoque do {r['tribunal']} em {deste['ano_ref']} "
                f"(saldo zero no Mapa do CNJ). A fila atual é dívida NOVA, ainda não "
                f"vencida — não há mora, e a projeção pelo teto do §23 é o piso pessimista.")
    outros = [x for x in res["por_tribunal"]
              if x["tribunal"] != r["tribunal"] and x["codigo"] == "nao_pagou"]
    if outros:
        pior = max(outros, key=lambda x: x["saldo"])
        avisos.append(
            f"Inadimplência em outro tribunal: {pior['tribunal']} com saldo de "
            f"{brl(pior['saldo'])} e R$ 0 pago em {pior['ano_ref']}. Disputa o mesmo "
            f"caixa {'do Estado' if _e_estado(r) else 'do município'}.")
    return res


TRF2_FEDERAL_CD = "UNIAO_ORCAMENTO_FEDERAL"   # mesmo valor do db_build


def _devedor_do_exercicio(cx, r):
    """Devedores que pagam a fila INTEIRA no exercicio do orcamento, sem §23 nem RCL.
    Devolve o texto do aviso ou None. Tres casos (04/10/2026, aprovados pelo usuario):
      - fila FEDERAL do TRF2 (cd UNIAO_ORCAMENTO_FEDERAL): a proposta 2026 inteira (23.264
        itens) consta paga em 03/2026 na lista do TRF2 baixada em 28/09/2026;
      - INSS na Justica ESTADUAL: acoes de acidente de trabalho sao da Justica Estadual
        (CF art. 109, I) e o precatorio e' requisitado pelo TJ (ex.: Decreto Judiciario
        TJPR 520/2020, art. 1o §1o), pago pelo orcamento federal. CNJ Mapa Anual 2025:
        regime Comum em todos os TJs, saldo ~0 (TJBA: devia R$ 42,0 mi, pagou R$ 37,9 mi);
      - EMBASA: estatal NAO dependente (LOA-BA 2026, Lei 15.072, art. 8o: Orcamento de
        Investimento), fora da RCL do Estado; regime Comum no CNJ Mapa Anual 2025."""
    if not r["ente_id"]:
        return None
    e = cx.execute("SELECT cd_externo, nome FROM ente WHERE id=?", (r["ente_id"],)).fetchone()
    if not e:
        return None
    n = unicodedata.normalize("NFKD", str(e[1] or "")).encode("ascii", "ignore").decode().upper()
    if r["tribunal"] == "TRF2" and e[0] == TRF2_FEDERAL_CD:
        return ("Devedor federal (fila orçamentária do TRF2): não há teto do §23. A União paga a "
                "proposta orçamentária inteira no exercício — a proposta 2026 do TRF2 saiu toda em 03/2026.")
    if r["tribunal"].startswith("TJ") and ("SEGURO SOCIAL" in n or "SEGURIDADE SOCIAL" in n
                                          or re.search(r"INSS", n)):
        return ("INSS na Justiça Estadual (ação de acidente de trabalho, CF art. 109, I): o precatório é "
                "pago pelo orçamento federal, sem teto do §23. No Mapa Anual do CNJ de 2025 o INSS está "
                "no regime comum em todos os TJs e quitou o que devia no ano.")
    if "EMBASA" in n or "BAIANA DE AGUAS" in n:
        return ("EMBASA: empresa estatal não dependente (LOA-BA 2026, art. 8º), fora da RCL do Estado "
                "da Bahia. Está no regime comum (CNJ, Mapa Anual 2025): paga o precatório no exercício "
                "do orçamento, sem teto do §23.")
    return None


def _projecao_exercicio(cx, r):
    """Projecao dos devedores de _devedor_do_exercicio: ano previsto = ano do orcamento (ou o
    exercicio corrente, se o orcamento ja' passou e o precatorio segue pendente). Sem banda nem
    ritmo: nao ha teto a modelar."""
    aviso = _devedor_do_exercicio(cx, r)
    if not aviso or not r["ano_orcamento"]:
        return None
    zera = cx.execute("SELECT MAX(ano_orcamento) FROM precatorio_atual WHERE ente_id=?",
                      (r["ente_id"],)).fetchone()[0]
    orc = int(r["ano_orcamento"])
    ano = max(orc, EXERCICIO)
    aviso += f" Previsão: exercício {ano}."
    if orc < EXERCICIO:
        aviso += (f" ATENÇÃO: o orçamento era {orc} e o precatório segue pendente — atraso fora do "
                  f"padrão deste devedor; conferir nos autos.")
    return {"ano_previsto": ano, "ano_por_cenario": {"conservador": ano, "central": ano, "otimista": ano},
            "fila_zera_em": max(zera or ano, EXERCICIO), "exercicio_base": EXERCICIO, "orcamento_anual": None,
            "fonte_orcamento": "pago_no_exercicio", "pct_p23": None, "teto_p23": None, "rateio": None,
            "repasse_fila": None, "banda": None, "anos_de_orcamento": None, "ritmo_observado": None,
            "_aviso": aviso}


def parecer(cx, r, completo=False, todos_itens=False):
    """Parecer estruturado de UM precatorio: identificacao, fila, projecao e avisos.
    todos_itens: ver contexto() (so' a pagina do ente usa)."""
    c = contexto(cx, r, todos_itens=todos_itens)
    avisos = []
    if r["tribunal"] in SEM_CREDOR:
        avisos.append(f"O {r['tribunal']} não publica o nome do credor na lista cronológica — "
                      f"apenas o do advogado, quando há.")
    if r["tribunal"] in SEM_NUMERO:
        avisos.append("O painel do TJMG não publica número de processo (apenas uma sequência "
                      "interna) e abrevia o credor em iniciais — por isso este precatório não "
                      "é localizável por número nem por nome completo.")
    if c and c.get("sem_projecao_motivo"):
        avisos.insert(0, "PROJEÇÃO NÃO EMITIDA: " + c["sem_projecao_motivo"]
                      + ". Sem o valor da fila não há como estimar quando o dinheiro sai — "
                        "qualquer data aqui seria inventada.")
    if r["tribunal"] in SEM_VALOR:
        avisos.append(f"O {r['tribunal']} publica saldo zerado nesta consulta; "
                      f"o valor não é confiável.")
    if not r["rcl"]:
        avisos.append("Sem Receita Corrente Líquida para este município — projeção indisponível.")
    if c and c.get("n_superprecatorios"):
        n = c["n_superprecatorios"]
        avisos.append(f"Há {n} superprecatório{'s' if n > 1 else ''} no município (art. 100 §20): "
                      f"{'eles disputam' if n > 1 else 'ele disputa'} a ordem cronológica "
                      f"normalmente até chegar a vez {'de cada um' if n > 1 else 'dele'} — só a "
                      f"partir daí o pagamento muda de parcela única para 15% à vista + 5 parcelas "
                      f"anuais de 17%, com prioridade sobre quem vem depois. Por isso o valor que "
                      f"explica a previsão é o da fila normal, não a soma bruta.")
    if c and c.get("e_superprecatorio"):
        avisos.append("Este é um superprecatório (art. 100 §20, grande vulto): disputa a ordem "
                      "cronológica normalmente até chegar a sua vez — só então o pagamento muda de "
                      "parcela única para 15% à vista naquele ano + 5 parcelas anuais de 17%, com "
                      "prioridade sobre quem vem depois dele na fila. Por isso não há um "
                      "“acumulado à frente” simples: o que importa é a posição na fila até a vez "
                      "dele chegar, não mais a soma de valores.")
    if r["regime"] == "Especial":
        avisos.append("Regime especial: o ritmo de pagamento observado é anterior à EC 136/2025. "
                      "Os cenários cobrem a hipótese de o teto do §23 passar a limitá-lo.")
        avisos.append("Regime especial não tem o parcelamento do §20: precatório de grande vulto "
                      "segue na fila como qualquer outro, até ser pago por completo.")
    if c and c.get("valor_provisionado"):
        avisos.append(f"{_brl(c['valor_provisionado'])} da fila deste ente já estão com caixa "
                      f"reservado (situação “Provisionamento Total”) — não disputam orçamento "
                      f"futuro; a previsão já desconta isso.")
    if c and c.get("repasse_fila"):
        rf = c["repasse_fila"]
        avisos.append(f"Apenas {rf['pct']:.0f}% do orçamento teórico do art. 100 §23 chega à "
                      f"ordem cronológica deste ente — o restante vai para outro canal "
                      f"(ver fonte). A previsão já usa a fração menor.")
    qn = c.get("quitacao_por_natureza") if c else None
    if qn:
        pn = qn["por_natureza"]
        maior = max(pn.values(), key=lambda x: x["quitado_pct"])
        menor = min(pn.values(), key=lambda x: x["quitado_pct"])
        if maior["quitado_pct"] - menor["quitado_pct"] >= 30:
            nat_maior = next(k for k, v in pn.items() if v is maior)
            nat_menor = next(k for k, v in pn.items() if v is menor)
            avisos.append(
                f"A fila deste ente anda de forma muito diferente por natureza: na coorte de "
                f"{qn['ano_coorte']} (a última já vencida), {nat_maior.lower()} tinha "
                f"{maior['quitado_pct']:.0f}% quitado contra {menor['quitado_pct']:.0f}% de "
                f"{nat_menor.lower()}. Um número agregado de fila esconde essa diferença — "
                f"o que importa é a natureza deste precatório específico "
                f"({(r['natureza'] or '?').lower()}).")
    plano = _bloco_plano(cx, r, avisos)
    pag = _bloco_pagamento(cx, r, avisos)

    out = {
        "precatorio": {
            "numero": r["numero_fmt"], "numero_normalizado": r["numero"],
            "numero_origem": fmt_cnj(r["numero_origem"]), "tribunal": r["tribunal"],
            "natureza": r["natureza"], "ano_orcamento": r["ano_orcamento"],
            "valor": r["valor"], "situacao": r["situacao"],
            "superpreferencia": r["superpreferencia"], "suspenso": bool(r["suspenso"]),
            "coletado_em": r["coletado_em"],
            # o numero que o comercial reconhece: o CNJ do precatorio
            "numero_eproc": r["numero_eproc"] if "numero_eproc" in r.keys() else None,
            "numero_eproc_fmt": fmt_cnj(r["numero_eproc"]) if "numero_eproc" in r.keys() else None,
        },
        "credor": {"nome": mascara_cpf_no_texto(r["credor"]), "cpf_cnpj": mascara_cpf(r["cpf_cnpj"], completo),
                   "cpf_mascarado": not completo, "advogado": r["advogado"],
                   "fonte_nome": (r["credor_fonte"] if "credor_fonte" in r.keys() else None)},
        "devedor": {"ente": r["ente_nome"], "ibge": r["ibge"], "municipio": r["municipio"],
                    "uf": r["uf"], "regime": r["regime"], "rcl": r["rcl"]},
        # primeiro filtro do comercial; None = ente sem edital publicado
        "edital_acordo": edital_acordo(r["ibge"]),
        "avisos": avisos,
    }
    if plano:
        p, conf = plano["plano"], plano["conformidade"]
        out["plano_exercicio"] = {
            "fonte": "Comitê Gestor de Contas Especiais (art. 100 §23, EC 136/2025)",
            "ano": p["ano"] if p else None,
            "mora_oficial_1jan": p["mora_1jan"] if p else None,
            "pct_aplicado": p["pct_aplicado"] if p else None,
            # NAO confundir com projecao.teto_p23 — ver docstring de _bloco_plano
            "valor_do_plano_no_ano": p["valor_anual"] if p else None,
            "rateio_por_justica": ({"TJ": p["rateio_tj"], "TRT": p["rateio_trt"],
                                    "TRF": p["rateio_trf"]} if p else None),
            "pa_fiscalizacao": (p["fonte_pa"] if p else None) or (conf["pa"] if conf else None),
            "publicado_em": p["fonte_data"] if p else None,
            "conformidade": None if not conf else {
                "situacao": conf["codigo"], "resumo": conf["texto"], "em": conf["em"],
                "bloqueios_sisbajud_na_janela": conf["n_bloqueios_12m"]},
        }
    if pag:
        # Fica FORA de 'fila' e de 'projecao' de proposito: outra fonte, outro grao,
        # outra data-base. Quem consome sabe de onde veio cada numero.
        out["pagamento"] = {
            "fonte": f"CNJ Mapa Anual ref. {pag['ano_ref']}", "ano_ref": pag["ano_ref"],
            "escopo": "administração direta do " + ("Estado" if _e_estado(r) else "município"),
            "situacao": pag["codigo"], "resumo": pag["texto"],
            "estoque_abertura": pag["anterior"], "pago_no_ano": pag["pago"],
            "saldo_fim_ano": pag["saldo"], "expedidos_no_ano": pag["expedidos"],
            "taxa_quitacao": pag["taxa_quitacao"], "anos_para_quitar": pag["anos_para_quitar"],
            "tribunais_em_dia": pag["tribunais_em_dia"],
            "tribunais_inadimplentes": pag["tribunais_inadimplentes"],
            "por_tribunal": pag["por_tribunal"],
            # Serie ano a ano (pago/expedido). Cobertura desigual de proposito:
            # so MG tem varios anos; nos demais estados o CNJ publica so o corrente.
            "historico_anual": MAPA.serie_anual(cx, r["ibge"]),
        }
    fed = _projecao_exercicio(cx, r)
    if fed:
        # os tres casos estao no regime COMUM no CNJ Mapa Anual 2025 (ver _devedor_do_exercicio);
        # sem isso a UI/PDF diziam "regime nao identificado -- confirme o regime"
        out["devedor"]["regime"] = out["devedor"]["regime"] or "Comum"
        out["avisos"] = [a for a in out["avisos"] if "Receita Corrente Líquida" not in a]
        out["avisos"].insert(0, fed.pop("_aviso"))
        out["projecao"] = fed
    if not c:
        return out
    # Terceira leitura de "ja venceu": o saldo do Mapa Anual do CNJ PARA ESTE TRIBUNAL
    # especificamente (pag.por_tribunal ja' calculado acima em _bloco_pagamento — nao
    # gera query nova). E' esperado ficar PROXIMO do numero oficial do tribunal (os
    # dois sao fotos de fechamento de ano, so' que apuradas por instituicoes
    # diferentes: TJMG apura o proprio Enquadramento, o CNJ compila o Mapa que TODOS
    # os tribunais declaram) — nao e' o mesmo calculo do zero, e' um segundo
    # observador medindo a mesma coisa. Ver [[painel-raiox-fiscal-rcl-dcl]] — o
    # Mapa Anual tem lacunas de qualidade conhecidas em alguns tribunais (saldo=0
    # suspeito quando anterior-pago nao fecha em zero); por isso este numero
    # acompanha os outros dois, nunca os substitui.
    mapa_cnj_deste = None
    if pag:
        _dt = next((x for x in (pag.get("por_tribunal") or []) if x["tribunal"] == r["tribunal"]), None)
        if _dt is not None:
            mapa_cnj_deste = {
                "saldo": _dt["saldo"], "ano_ref": _dt.get("ano_ref"),
                "sobre_rcl_pct": (round(100 * _dt["saldo"] / r["rcl"], 2)
                                  if r["rcl"] and _dt["saldo"] is not None else None)}

    out["fila"] = {"ordem": r["ordem"], "n_total": c["n_total"],
                   "e_superprecatorio": c.get("e_superprecatorio", False),
                   "acumulado_sem_p20": c["acumulado"], "acumulado_bruto": c["acumulado_bruto"],
                   "n_superprecatorios": c["n_superprecatorios"],
                   "estoque_municipio": c["estoque"], "estoque_em_mora": c["mora"],
                   "n_em_mora": c["n_mora"], "mora_sobre_rcl_pct": c["prop_mora"],
                   # os tres numeros convivem de proposito: o calculado sai da lista
                   # de hoje, o oficial e' a foto homologada pelo tribunal, o do Mapa
                   # CNJ e' a mesma foto vista pelo compilador nacional. Divergir e'
                   # informacao — nao existe pra escolher um e descartar os outros.
                   "estoque_em_mora_oficial": c.get("mora_oficial"),
                   "mora_oficial_fonte": c.get("mora_oficial_fonte"),
                   "mora_oficial_documento": c.get("mora_oficial_documento"),
                   "mora_oficial_ref": c.get("mora_oficial_ref"),
                   "mora_oficial_sobre_rcl_pct": c.get("mora_oficial_sobre_rcl_pct"),
                   "estoque_em_mora_mapa_cnj": mapa_cnj_deste,
                   "base_mora_usada": c.get("base_mora_usada"),
                   "fora_da_fila": c.get("fora_da_fila"),
                   "reserva_p20": c.get("reserva_p20"),
                   "valor_superprecatorios": c.get("valor_superprecatorios"),
                   # itens com caixa ja reservado (TJCE) — nao contam no "falta
                   # financiar" nem disputam orcamento futuro. Ver aviso correspondente.
                   "provisionado": {"valor": c.get("valor_provisionado"),
                                    "alvo_provisionado": c.get("alvo_provisionado", False),
                                    "acumulado_a_financiar": c.get("acumulado_a_financiar")},
                   "quitacao_por_natureza": c.get("quitacao_por_natureza"),
                   # fila item a item (janela em torno do buscado) p/ a tabela da UI —
                   # ver contexto(): so existe quando ha cenario e o item foi achado na fila.
                   "itens": c.get("fila_itens"), "itens_janela": c.get("fila_itens_janela")}
    cen = c["cenarios"]
    if cen:
        rateio = c.get("rateio") or {"fracao": 1.0}
        # combinada: rateio entre justicas x fracao do repasse que chega na fila
        # (ver contexto()). NAO recomputar so' de rateio.fracao — os dois numeros
        # do parecer (orcamento mostrado x ano projetado) se contradiriam.
        frac = c.get("frac_orcamento", rateio.get("fracao", 1.0))
        out["projecao"] = {
            "ano_previsto": c["ano_previsto"],
            "ano_por_cenario": c.get("ano_previsto_por_cenario"),
            "fila_zera_em": c["zera"], "exercicio_base": EXERCICIO,
            # orcamento_anual e banda = a PARCELA desta justica (teto x fracao do rateio);
            # teto_p23 = o limite CHEIO do ente (todas as justicas). Quando fracao=1 (ente
            # de uma justica so), orcamento_anual == teto e rateio vem None: nada muda.
            "orcamento_anual": round(cen["central"] * frac, 2), "fonte_orcamento": cen["fonte"],
            "pct_p23": cen["pct_p23"], "teto_p23": cen["teto_p23"],
            "rateio": rateio if rateio.get("fracao", 1.0) < 1.0 else None,
            # parte do orcamento teorico que NAO chega na fila (vai p/ acordo etc.)
            "repasse_fila": c.get("repasse_fila"),
            "banda": {k: round(cen[k] * frac, 2) for k in ("conservador", "central", "otimista")},
            "anos_de_orcamento": c["anos"],
            # o mesmo calculo, mas com o que o ente pagou de fato (ver contexto)
            "ritmo_observado": c.get("ritmo_observado"),
        }
    return out


# ===================================================================== SAUDE DO ENTE
# Pagina "Saude do ente" (aba "Ente devedor" da UI, 07/10/2026). O devedor e' o ENTE INTEIRO:
# municipio/Estado com todos os orgaos (pool por ibge) em todos os tribunais. Orgao sem
# municipio (Uniao/federais, INSS nos TJs, estatais) vira uma pagina propria, pela chave
# "e<ente_id>". Nada de dado de credor aqui: so' agregados.

def _chave_devedor(s):
    return re.sub(r"\s+", " ", unicodedata.normalize("NFKD", str(s or "")).encode(
        "ascii", "ignore").decode().upper()).strip()


def devedores(cx):
    """Todos os devedores com fila: chave, nome, uf, tipo, regime, n_orgaos, n, valor, tribunais."""
    out = []
    for r in cx.execute(
            "SELECT e.ibge, m.nome, m.uf, m.regime, COUNT(DISTINCT e.id) n_orgaos, COUNT(p.id) n, "
            "COALESCE(SUM(p.valor), 0) v, GROUP_CONCAT(DISTINCT p.tribunal) tribs "
            "FROM precatorio_atual p JOIN ente e ON e.id = p.ente_id JOIN municipio m ON m.ibge = e.ibge "
            "WHERE p.ordem IS NOT NULL GROUP BY e.ibge"):
        out.append({"chave": r["ibge"], "nome": r["nome"], "uf": r["uf"],
                    "tipo": "estado" if len(r["ibge"]) == 2 else "municipio", "regime": r["regime"],
                    "n_orgaos": r["n_orgaos"], "n": r["n"], "valor": round(r["v"], 2),
                    "tribunais": sorted((r["tribs"] or "").split(","))})
    for r in cx.execute(
            "SELECT e.id, e.nome, e.tribunal, COUNT(p.id) n, COALESCE(SUM(p.valor), 0) v "
            "FROM ente e JOIN precatorio_atual p ON p.ente_id = e.id "
            "WHERE e.ibge IS NULL AND p.ordem IS NOT NULL GROUP BY e.id"):
        out.append({"chave": "e%d" % r["id"], "nome": r["nome"], "uf": None, "tipo": "orgao",
                    "regime": None, "n_orgaos": 1, "n": r["n"], "valor": round(r["v"], 2),
                    "tribunais": [r["tribunal"]]})
    for d in out:
        d["_busca"] = _chave_devedor("%s %s" % (d["nome"], d["uf"] or ""))
    out.sort(key=lambda d: -d["n"])
    return out


def busca_devedor(lista, termo, limite=20):
    """Todas as palavras do termo, sem acento, em qualquer ordem. Estado e nome que comeca
    com o termo vem primeiro; depois por tamanho da fila."""
    t = [w for w in _chave_devedor(termo).split() if len(w) >= 2]
    if not t:
        return []
    achados = [d for d in lista if all(w in d["_busca"] for w in t)]
    achados.sort(key=lambda d: (d["tipo"] != "estado", not d["_busca"].startswith(t[0]), -d["n"]))
    return [{k: v for k, v in d.items() if k != "_busca"} for d in achados[:limite]]


def _where_chave(chave):
    if chave.startswith("e") and chave[1:].isdigit():
        return "e.id = ?", [int(chave[1:])], None
    if chave.isdigit():
        return "e.ibge = ?", [chave], chave
    return None, None, None


def _curva(itens):
    """Ano previsto (lei e ritmo real) de quem esta a 0/25/50/75/100% da fila."""
    if not itens:
        return None
    out = []
    for q in (0.0, 0.25, 0.5, 0.75, 1.0):
        it = itens[min(len(itens) - 1, int(q * (len(itens) - 1)))]
        out.append({"q": q, "posicao": it["posicao"], "ano_lei": it.get("ano_previsto"),
                    "ano_ritmo": it.get("ano_ritmo")})
    return out


def saude_ente(cx, chave):
    """Dados da pagina 'Saude do ente'. None se a chave nao tem fila."""
    where, params, ibge = _where_chave(str(chave))
    if not where:
        return None
    m = cx.execute("SELECT * FROM municipio WHERE ibge = ?", (ibge,)).fetchone() if ibge else None
    orgaos = [dict(x) for x in cx.execute(
        "SELECT e.id, e.nome, e.tribunal, e.tipo, COUNT(p.id) n, COALESCE(SUM(p.valor), 0) valor "
        "FROM ente e JOIN precatorio_atual p ON p.ente_id = e.id WHERE " + where +
        " AND p.ordem IS NOT NULL GROUP BY e.id ORDER BY valor DESC", params)]
    if not orgaos:
        return None
    por_trib = [dict(x) for x in cx.execute(
        "SELECT p.tribunal, COUNT(*) n, COALESCE(SUM(p.valor), 0) valor, "
        "COALESCE(SUM(CASE WHEN p.ano_orcamento < ? THEN p.valor END), 0) vencido, "
        "SUM(p.valor IS NULL OR p.valor = 0) sem_valor, MAX(p.coletado_em) coleta "
        "FROM precatorio_atual p JOIN ente e ON e.id = p.ente_id "
        "WHERE " + where + " AND p.ordem IS NOT NULL GROUP BY p.tribunal ORDER BY n DESC",
        [EXERCICIO] + params)]
    por_ano = [dict(x) for x in cx.execute(
        "SELECT p.ano_orcamento ano, COUNT(*) n, COALESCE(SUM(p.valor), 0) valor "
        "FROM precatorio_atual p JOIN ente e ON e.id = p.ente_id "
        "WHERE " + where + " AND p.ordem IS NOT NULL AND p.ano_orcamento IS NOT NULL "
        "GROUP BY 1 ORDER BY 1", params)]

    # Uma projecao por tribunal com fila, com o MESMO motor do parecer: ancora = ultimo item
    # (com valor) do maior orgao naquele tribunal. O parecer devolve a fila inteira, ja
    # combinada entre os orgaos, com o ano de cada item (lei e ritmo real).
    projecoes, pag, edital, plano, avisos = [], None, None, None, []
    for t in por_trib:
        e = cx.execute(
            "SELECT p.ente_id FROM precatorio_atual p JOIN ente e ON e.id = p.ente_id "
            "WHERE " + where + " AND p.tribunal = ? AND p.ordem IS NOT NULL "
            "GROUP BY p.ente_id ORDER BY COUNT(*) DESC LIMIT 1", params + [t["tribunal"]]).fetchone()
        r = cx.execute("SELECT * FROM precatorio_atual WHERE ente_id = ? AND ordem IS NOT NULL "
                       "ORDER BY valor > 0 DESC, ordem DESC LIMIT 1", (e[0],)).fetchone() if e else None
        if r is None:
            continue
        p = parecer(cx, r, todos_itens=True)
        pj = p.get("projecao") or {}
        f = p.get("fila") or {}
        itens = f.get("itens") or []
        ritmos = [it.get("ano_ritmo") for it in itens if it.get("ano_ritmo")]
        rt = pj.get("ritmo_observado") or {}
        projecoes.append({
            "tribunal": t["tribunal"], "n_fila": f.get("n_total"),
            "fila_zera_lei": pj.get("fila_zera_em"), "fila_zera_ritmo": max(ritmos) if ritmos else None,
            "fonte_orcamento": pj.get("fonte_orcamento"), "orcamento_anual": pj.get("orcamento_anual"),
            "pct_p23": pj.get("pct_p23"), "teto_p23": pj.get("teto_p23"), "rateio": pj.get("rateio"),
            "pago_no_ano": rt.get("pago_no_ano"), "pct_do_teto": rt.get("pct_do_teto"),
            "mora_fila": f.get("estoque_em_mora"), "mora_oficial": f.get("estoque_em_mora_oficial"),
            "mora_oficial_fonte": f.get("mora_oficial_fonte"), "base_mora": f.get("base_mora_usada"),
            "n_superprecatorios": f.get("n_superprecatorios"),
            "valor_superprecatorios": f.get("valor_superprecatorios"),
            "provisionado": (f.get("provisionado") or {}).get("valor"),
            "prop_sem_valor": round(t["sem_valor"] / t["n"], 3) if t["n"] else None,
            "curva": _curva(itens),
        })
        if pag is None:
            pag, edital, plano = p.get("pagamento"), p.get("edital_acordo"), p.get("plano_exercicio")
        for a in p.get("avisos") or []:
            # aviso sobre o PRECATORIO ancora nao serve para o ente
            if (a.startswith(("Este é", "Este precatório", "Este número"))
                    or "este precatório" in a.lower() or a.startswith("PROJEÇÃO NÃO EMITIDA")
                    or a in avisos):
                continue
            avisos.append(a)
    tribs_com_fila = {t["tribunal"] for t in por_trib}
    sem_fila = [x for x in ((pag or {}).get("por_tribunal") or [])
                if x.get("tribunal") not in tribs_com_fila and (x.get("saldo") or x.get("anterior"))]
    if ibge:
        tipo = "estado" if len(ibge) == 2 else "municipio"
    else:
        tipo = "orgao"
    return {
        "chave": str(chave), "ibge": ibge,
        "nome": m["nome"] if m else orgaos[0]["nome"], "uf": m["uf"] if m else None,
        "tipo": tipo, "regime": m["regime"] if m else None, "rcl": m["rcl"] if m else None,
        "ano_rcl": m["ano_rcl"] if m else None, "fonte_rcl": m["fonte_rcl"] if m else None,
        "exercicio": EXERCICIO,
        "orgaos": [{"id": o["id"], "nome": o["nome"], "tribunal": o["tribunal"], "tipo": o["tipo"], "n": o["n"],
                    "valor": round(o["valor"], 2)} for o in orgaos],
        "por_tribunal": [dict(t, valor=round(t["valor"], 2), vencido=round(t["vencido"], 2))
                         for t in por_trib],
        "por_ano": [dict(a, valor=round(a["valor"], 2)) for a in por_ano],
        "projecoes": projecoes,
        "serie_anual": MAPA.serie_anual(cx, ibge) if ibge and MAPA.existe(cx) else [],
        "pagamento": pag, "edital_acordo": edital, "plano_exercicio": plano,
        "tribunais_sem_fila": sem_fila, "avisos": avisos,
    }
