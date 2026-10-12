# -*- coding: utf-8 -*-
"""FASE 1 da migracao do Alfred para banco: schema + carga a partir dos JSONs crus.

  python scripts/db_build.py            # (re)cria e carrega data/alfred.db
  python scripts/db_build.py --resumo   # so imprime o que ja esta carregado
  python scripts/db_build.py --saida X  # constroi em X; nao toca data/alfred.db
  python scripts/db_build.py --verifica [--relatorio X.csv]   # so' lista entradas suspeitas

DECISAO DE DESENHO CENTRAL
  A data da coleta faz parte da IDENTIDADE do precatorio, nao e' um campo mutavel:
  a chave e' (coleta_id, tribunal, numero). Rodar o coletor de novo NAO sobrescreve --
  cria uma nova coleta e preserva a anterior. E' isso que permite, mais adiante,
  medir o modelo contra a realidade ("o precatorio que projetei p/ 2027 andou quanto
  na fila em 6 meses?"). A view `precatorio_atual` devolve so a coleta mais recente
  de cada (tribunal, ente), que e' o que o dia-a-dia consulta.

OS JSONs CRUS CONTINUAM SENDO A FONTE DA VERDADE. Este banco e' DERIVADO e pode ser
reconstruido do zero a qualquer momento (por isso --reset apaga sem cerimonia).

NORMALIZACOES QUE O BANCO IMPOE (e que os JSONs nao tinham)
  - numero de processo -> so digitos, em `numero` / `numero_origem` (os originais
    ficam em `numero_fmt`). Sem isso nao ha busca por processo.
  - natureza -> {Alimentar, Comum}. Cada tribunal escrevia de um jeito: 0/1 no TJAL,
    A/C no TJBA e TJES, "Alimentícia" no TJRJ, "ALIMENTARES"/"OUTRAS ESPÉCIES" no TJSP.
  - regime   -> {Comum, Especial}. O dashboard dizia "Geral" onde a base canonica do
    CNJ diz "Comum" -- mesma coisa com dois nomes, que quebrava filtro por string.

COBERTURA: 25 adaptadores (TJES/LUP, TJMG, TJBA, TJRJ, TJAL, TJPE, TJSP, TJMA,
TJCE, TJPA, TJGO, TJAM, TJRR, TJPI, TJPR, TJRS, TJSC, TJTO, TJSE, TJAC, TJMS, TJAP, TJMT,
TJRN e TRT17/TRF2). TJCE, TJPA, TJGO e TJAM vem dos
paineis Power BI publicos (scripts/powerbi_publico.py) -- tem esquema proprio e
por isso nao usam o laco generico de FONTES, que exige a chave "precatorios".
TJRS tambem e' bespoke (nao entra em FONTES): o servidor tem um bug confirmado
que faz `devedor=<id>` diferentes devolverem a MESMA fila, e o laco de carga
precisa desambiguar isso ANTES de gravar (ver comentario dentro de `carrega()`).
Todos os 59 tribunais do CNJ aparecem em `mapa_cnj` (db_mapa.py, no fim desta
build): la o grao e' ente/ano, nao o precatorio.
"""
import argparse
import csv
import glob
import importlib.util
import json
import os
import pathlib
import re
import sqlite3
import sys
import unicodedata
from collections import defaultdict
from datetime import datetime, timezone

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

# BASE resolvido a partir do proprio arquivo: funciona no Windows e na VM Linux.
# ALFRED_BASE sobrepoe quando o codigo roda de outro lugar.
BASE = os.environ.get("ALFRED_BASE") or str(pathlib.Path(__file__).resolve().parents[1])
DB = os.path.join(BASE, "data", "alfred.db")

_spec = importlib.util.spec_from_file_location("db_mapa", os.path.join(BASE, "scripts", "db_mapa.py"))
MAPA = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(MAPA)

_spec = importlib.util.spec_from_file_location("db_nacp", os.path.join(BASE, "scripts", "db_nacp.py"))
NACP = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(NACP)

_spec = importlib.util.spec_from_file_location("credor_norm", os.path.join(BASE, "scripts", "credor_norm.py"))
CN = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(CN)

_spec = importlib.util.spec_from_file_location("enriquece_credor",
                                               os.path.join(BASE, "scripts", "enriquece_credor.py"))
CRED = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(CRED)

_spec = importlib.util.spec_from_file_location("enriquece_credor_djen",
                                               os.path.join(BASE, "scripts", "enriquece_credor_djen.py"))
CRED_DJEN = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(CRED_DJEN)

SCHEMA = """
PRAGMA journal_mode=WAL;

CREATE TABLE coleta (
  id           INTEGER PRIMARY KEY,
  tribunal     TEXT NOT NULL,
  fonte        TEXT,
  arquivo      TEXT,
  coletado_em  TEXT NOT NULL,          -- mtime do JSON cru (ISO)
  carregado_em TEXT NOT NULL,
  n_registros  INTEGER
);

CREATE TABLE municipio (
  ibge       TEXT PRIMARY KEY,
  nome       TEXT NOT NULL,
  uf         TEXT NOT NULL,
  regime     TEXT,                     -- Comum | Especial  (normalizado)
  rcl        REAL,                     -- RCL(III) do RREO/LRF — o que o ente publica
  ano_rcl    INTEGER,
  fonte_rcl  TEXT,
  -- RCL na definicao do art. 100 §18 / art. 101 §1º ADCT, que e' a base do §23:
  -- lista de deducoes EXAUSTIVA, sem o FUNDEB. Calculada como RCL(III) + deducao
  -- do FUNDEB; reproduz a RCL do Enquadramento do TJMG (mediana +0,00%, 33/40
  -- batendo <1% na amostra de 2026-08-25). Guardada AO LADO da `rcl`, nao no lugar:
  -- trocar a base sobe o teto do §23 de quase todo municipio em ~12% e encurta
  -- todas as projecoes — e' decisao de negocio, nao efeito colateral de coleta.
  rcl_p23    REAL,
  fundeb     REAL                      -- deducao do FUNDEB (12 meses), do Anexo 03
);

CREATE TABLE ente (
  id         INTEGER PRIMARY KEY,
  tribunal   TEXT NOT NULL,
  cd_externo TEXT,                     -- id do ente no sistema do tribunal
  nome       TEXT NOT NULL,
  ibge       TEXT REFERENCES municipio(ibge),
  tipo       TEXT,                     -- prefeitura | autarquia | outro
  UNIQUE (tribunal, cd_externo)
);

CREATE TABLE precatorio (
  id               INTEGER PRIMARY KEY,
  coleta_id        INTEGER NOT NULL REFERENCES coleta(id),
  ente_id          INTEGER REFERENCES ente(id),
  tribunal         TEXT NOT NULL,
  numero           TEXT,               -- so digitos
  numero_fmt       TEXT,               -- como veio da fonte
  numero_origem    TEXT,               -- processo de conhecimento/execucao, so digitos
  numero_eproc     TEXT,               -- CNJ do PRECATORIO (TJMG: 'No Eproc 2G'), so digitos
  ordem            INTEGER,             -- ordem OFICIAL dentro do ente (a fila da fonte)
  data_apresentacao TEXT,              -- expedicao/protocolo (ISO ordenavel) p/ intercalar entes
  natureza         TEXT,               -- Alimentar | Comum
  ano_orcamento    INTEGER,
  valor            REAL,
  situacao         TEXT,
  superpreferencia TEXT,
  suspenso         INTEGER DEFAULT 0,
  credor           TEXT,
  credor_norm      TEXT,               -- credor sem acento/maiusculo, p/ busca por nome (scripts/credor_norm.py)
  credor_fonte     TEXT,               -- NULL = lista do tribunal; 'Callix' = nome completo repondo a mascara PF do TJMG
  cpf_cnpj         TEXT,
  advogado         TEXT,
  -- Origem e confianca do documento em cpf_cnpj (LGPD, auditoria A6; ver classifica_cpf
  -- e docs/auditoria/04-lgpd-fase0.md). NULL onde nao ha documento. Nunca alteram cpf_cnpj.
  -- 'verificado' = origem OFICIAL e CONSISTENTE (DV valido, um so' nome no banco, casamento
  -- sem ambiguidade) -- NAO e' confirmacao independente de que o documento e' da pessoa.
  -- 'provavel' + iniciais_fallback NAO equivale a 'provavel' + cnj_precatorio.
  cpf_fonte        TEXT,               -- tjac_painel_qlik | tjal_api_sapre | rpa_rj_planilha_estado_al | callix_planilhas_mg
  cpf_metodo       TEXT,               -- lista_tribunal | planilha_rpa_rj | cnj_precatorio | iniciais_fallback
  cpf_data         TEXT,               -- data (ISO) em que a fonte foi obtida
  cpf_confianca    TEXT CHECK (cpf_confianca IN ('verificado', 'provavel', 'nao_verificado'))
);

CREATE INDEX ix_prec_numero     ON precatorio(numero);
CREATE INDEX ix_prec_origem     ON precatorio(numero_origem);
CREATE INDEX ix_prec_credor     ON precatorio(credor);
CREATE INDEX ix_prec_coleta     ON precatorio(coleta_id);
CREATE INDEX ix_prec_cpf        ON precatorio(cpf_cnpj);
CREATE INDEX ix_prec_eproc      ON precatorio(numero_eproc);
CREATE INDEX ix_prec_ente_ordem ON precatorio(ente_id, ordem);
CREATE INDEX ix_ente_ibge       ON ente(ibge);

-- busca por nome: FTS5 trigram sobre credor_norm (rowid = precatorio.id). Derivado de
-- `credor`, mantido por credor_norm.sincroniza() -- ver o cabecalho daquele modulo.
CREATE VIRTUAL TABLE credor_fts USING fts5(credor_norm, tokenize='trigram');

-- Quitacao por natureza (alimentar x comum), por coorte -- ver carrega_natureza_tjrj().
-- So' TJRJ por enquanto: o unico coletor cujo JSON cru preserva os itens ja quitados
-- (os outros descartam na propria coleta). Informativo: nao alimenta `precatorio`.
CREATE TABLE fila_natureza_stats (
  id            INTEGER PRIMARY KEY,
  ente_id       INTEGER REFERENCES ente(id),
  tribunal      TEXT NOT NULL,
  ano_orcamento INTEGER,
  natureza      TEXT,
  itens         INTEGER,
  quitados      INTEGER,
  valor_aberto  REAL
);
CREATE INDEX ix_fns_ente ON fila_natureza_stats(ente_id, tribunal);

-- ultima coleta de cada (tribunal, arquivo): o "hoje" do sistema. TABELA, preenchida
-- por materializa_coleta_atual() logo depois da carga -- era VIEW com subquery
-- correlacionada sem indice, reexecutada por LINHA de precatorio (/entes levava 147 s
-- local, 416 s na VM; auditoria A3). So' o build escreve em `coleta`, entao
-- materializar uma vez no fim da carga da' o mesmo resultado.
CREATE TABLE coleta_atual (
  id           INTEGER PRIMARY KEY,    -- = coleta.id (o join com precatorio e' por aqui)
  tribunal     TEXT NOT NULL,
  fonte        TEXT,
  arquivo      TEXT,
  coletado_em  TEXT NOT NULL,
  carregado_em TEXT NOT NULL,
  n_registros  INTEGER
);
CREATE UNIQUE INDEX ix_coleta_atual_chave ON coleta_atual(tribunal, arquivo);

CREATE VIEW precatorio_atual AS
SELECT p.*, e.nome AS ente_nome, e.ibge, m.nome AS municipio, m.uf,
       m.regime, m.rcl, c.coletado_em
FROM precatorio p
JOIN coleta_atual c ON c.id = p.coleta_id
LEFT JOIN ente e      ON e.id = p.ente_id
LEFT JOIN municipio m ON m.ibge = e.ibge;
"""


# ------------------------------------------------------------------ utils
def so_digitos(s):
    d = re.sub(r"\D", "", str(s or ""))
    return d or None


def loose(s):
    n = unicodedata.normalize("NFKD", str(s or "")).encode("ascii", "ignore").decode().upper()
    return re.sub(r"\s+", " ", re.sub(r"[^A-Z0-9]", " ", n)).strip()


PREP = {"DE", "DA", "DO", "DAS", "DOS", "E"}


def sem_prep(s):
    return " ".join(w for w in loose(s).split() if w not in PREP)


def money(x):
    if isinstance(x, (int, float)):
        return float(x)
    s = str(x or "").strip()
    if not s or s.lower() in ("none", "null", "-"):
        return 0.0
    try:
        return float(s)
    except ValueError:
        return float(re.sub(r"[^\d,-]", "", s).replace(".", "").replace(",", ".") or 0)


def ano(x):
    d = re.findall(r"\d{4}", str(x or ""))
    return int(d[-1]) if d else None          # "6/2023" -> 2023


def norm_data(x):
    """Data de apresentacao/expedicao -> string ISO ORDENAVEL lexicograficamente,
    preservando a hora quando existe (o desempate entre entes no mesmo dia depende dela).
    Aceita ISO, lista [ano,mes,dia] (TJBA) e 'DD/MM/AAAA[ HH:MM]' (TJPE/TJSP). None se nao casar."""
    if x is None:
        return None
    if isinstance(x, (list, tuple)) and len(x) >= 3:
        try:
            return f"{int(x[0]):04d}-{int(x[1]):02d}-{int(x[2]):02d}"
        except (ValueError, TypeError):
            return None
    s = str(x).strip()
    m = re.match(r"(\d{4})-(\d{2})-(\d{2})[ T]?(\d{2}:\d{2}(?::\d{2})?)?", s)      # ISO
    if m:
        return f"{m.group(1)}-{m.group(2)}-{m.group(3)}" + (f"T{m.group(4)}" if m.group(4) else "")
    m = re.match(r"(\d{2})/(\d{2})/(\d{4})\D*(\d{2}:\d{2}(?::\d{2})?)?", s)         # DD/MM/AAAA
    if m:
        return f"{m.group(3)}-{m.group(2)}-{m.group(1)}" + (f"T{m.group(4)}" if m.group(4) else "")
    return None


def norm_regime(s):
    t = loose(s)
    if "ESPECIAL" in t:
        return "Especial"
    if t in ("COMUM", "GERAL") or "COMUM" in t or "GERAL" in t:
        return "Comum"
    return None


def norm_natureza(s):
    t = loose(s)
    if t in ("0", "A") or "ALIMENT" in t:
        return "Alimentar"
    if t in ("1", "C") or "COMUM" in t or "OUTRAS" in t:
        return "Comum"
    return None


def mtime_iso(path):
    return datetime.fromtimestamp(os.path.getmtime(path), timezone.utc).isoformat(timespec="seconds")


# ------------------------------------------------------------------ municipios
def carrega_municipios(cx):
    """regimes_brasil_municipios.csv (CNJ, canonico) + rcl_<uf>_siconfi.csv.

    MG nao tem rcl_mg_siconfi.csv (nenhum coletor rodou p/ essa UF): cai para a
    RCL do proprio enquadramento_definitivo.csv (TJMG, EF2026, ref. dez/2025) --
    fonte oficial ja usada em municipios_rg_faixas.csv/projecao_pagamento_mg.csv.
    Mantida com rotulo proprio (nao "SICONFI") porque a base difere: no confronto
    amostral com o SICONFI (5 municipios) a RCL do TJMG veio 9%-29% mais alta.
    """
    muns = {}
    p = os.path.join(BASE, "data", "regimes_brasil_municipios.csv")
    for r in csv.DictReader(open(p, encoding="utf-8-sig")):
        muns[r["codigo_ibge"]] = {"ibge": r["codigo_ibge"], "nome": r["municipio"],
                                  "uf": r["uf"], "regime": norm_regime(r["regime"]),
                                  "rcl": None, "ano_rcl": None, "fonte_rcl": None,
                                  "rcl_p23": None, "fundeb": None}
    # rcl_brasil_siconfi.csv (nacional, fetch_rcl_brasil.py) + os rcl_<uf>_siconfi.csv
    # antigos. Mesma fonte e mesma metodologia, coletados em datas diferentes -> a
    # precedencia e' EXPLICITA pelo ano do exercicio (o mais recente vence), e nao a
    # ordem alfabetica do glob, que faria 'brasil' perder p/ 'es'/'pe'/'rj' por acaso.
    for f in sorted(glob.glob(os.path.join(BASE, "data", "rcl_*_siconfi.csv"))):
        for r in csv.DictReader(open(f, encoding="utf-8-sig")):
            m = muns.get(r.get("codigo_ibge"))
            if not m or r.get("rcl") in (None, "", "None"):
                continue
            ano = int(r["ano_rcl"]) if (r.get("ano_rcl") or "").isdigit() else None
            # A base do §23 e' dado COMPLEMENTAR, nao concorrente: preenche sempre que
            # o arquivo a tiver e o municipio ainda estiver sem. Fora deste bloco os
            # 519 municipios de BA/AL ficavam sem `rcl_p23` — os CSVs antigos dessas
            # UFs (sem a coluna) empatam no ano com o nacional e vencem o empate,
            # bloqueando tambem o que nao disputava.
            if r.get("rcl_p23") not in (None, "", "None") and m.get("rcl_p23") is None:
                m["rcl_p23"] = float(r["rcl_p23"])
                if r.get("deducao_fundeb") not in (None, "", "None"):
                    m["fundeb"] = float(r["deducao_fundeb"])
            if m["rcl"] is not None and (ano or 0) <= (m["ano_rcl"] or 0):
                continue
            m["rcl"] = float(r["rcl"])
            m["ano_rcl"] = ano
            m["fonte_rcl"] = "SICONFI/RREO Anexo 03"
    # A RCL do TJMG SOBREPOE o SICONFI em MG -- e' deliberado. O teto do §23 que o
    # municipio de fato deposita e' calculado pelo TRIBUNAL sobre a RCL do proprio
    # Enquadramento; usar outra base produziria um teto que ninguem pratica. As duas
    # bases divergem de verdade: no confronto dos 853 municipios mineiros (2026-08-25)
    # o SICONFI vem MENOR, mediana -10,9%, casos extremos -68% -- deixar o SICONFI
    # ganhar encolheria o teto de 845 deles e alongaria toda projecao de MG.
    # Regra geral: onde existir RCL oficial do tribunal para fins do §23, ela vence.
    p = os.path.join(BASE, "data", "enquadramento_definitivo.csv")
    if os.path.exists(p):
        for r in csv.DictReader(open(p, encoding="utf-8-sig")):
            m = muns.get(r.get("codigo_ibge"))
            if m and r.get("rcl") not in (None, "", "None"):
                m["rcl"] = float(r["rcl"])
                m["ano_rcl"] = 2025
                m["fonte_rcl"] = "TJMG/Enquadramento §23 (EF2026, ref. dez/2025)"
                # a RCL do TJMG JA e' apurada na definicao do §18 (o proprio
                # cabecalho da planilha cita "§§ 18 e 23 do art. 100") -> ela e'
                # simultaneamente a `rcl` que usamos e a base do §23.
                m["rcl_p23"] = float(r["rcl"])
    # ESTADOS como "pseudo-municipio" (chave = codigo IBGE de 2 digitos: ES=32, MG=31).
    # Isso da RCL a fila ESTADUAL (Estado + autarquias estaduais), que antes ficava com
    # ibge=None e sem projecao. A maquina do §23 e' a mesma; resolve_ibge aponta os entes
    # estaduais de ES/MG para esses codigos. Fonte: SICONFI RREO Anexo 03 (fetch_rcl_uf.py).
    p = os.path.join(BASE, "data", "rcl_uf_siconfi.csv")
    if os.path.exists(p):
        for r in csv.DictReader(open(p, encoding="utf-8-sig")):
            muns[r["codigo_ibge"]] = {
                "ibge": r["codigo_ibge"], "nome": r["nome"], "uf": r["uf"],
                "regime": norm_regime(r.get("regime")),
                "rcl": float(r["rcl"]) if r.get("rcl") else None,
                "ano_rcl": int(r["ano_rcl"]) if r.get("ano_rcl", "").isdigit() else None,
                "fonte_rcl": "SICONFI/RREO Anexo 03 (Estado)"}
    cx.executemany(
        "INSERT INTO municipio (ibge,nome,uf,regime,rcl,ano_rcl,fonte_rcl,rcl_p23,fundeb) "
        "VALUES (?,?,?,?,?,?,?,?,?)",
        [(m["ibge"], m["nome"], m["uf"], m["regime"], m["rcl"], m["ano_rcl"], m["fonte_rcl"],
          m.get("rcl_p23"), m.get("fundeb")) for m in muns.values()])
    return muns


def indice_ibge(muns):
    """nome normalizado -> ibge, por UF (p/ casar ente do tribunal com municipio)."""
    ix = {}
    for m in muns.values():
        ix.setdefault(m["uf"], {})[sem_prep(m["nome"])] = m["ibge"]
    return ix


MARCADORES_AUTARQUIA = ("INSTITUTO", "AUTARQUIA", "SERVICO", "SAAE", "DEPARTAMENTO",
                        "FUNDO", "CAMARA", "COMPANHIA", "CIA ", "PREV", "IPREM",
                        "UNIVERSIDADE", "CONSORCIO", "AGENCIA", "CAIXA", "EMPRESA",
                        "FUNDACAO", "HOSPITAL", "SUPERINT", "SUDECAP", "SLU")


# Estados como pseudo-municipio (ver carrega_municipios).
UF_ESTADO = {"ES": "32", "MG": "31", "GO": "52", "BA": "29", "CE": "23", "RN": "24", "SP": "35",
             "AL": "27", "RJ": "33", "MT": "51", "PB": "25", "PR": "41", "PI": "22", "AP": "16",
             "RS": "43", "SC": "42", "TO": "17", "RR": "14", "MS": "50", "PA": "15", "AM": "13",
             "AC": "12", "PE": "26"}

# RJ, MT e PB (03/10/2026): o pool do Estado e' feito por cd_externo da lista do TJ, nome a
# nome (mesma ideia do AL_ESTADUAIS_CD). As listas desses TJs misturam orgaos estaduais,
# municipais, federais e de OUTROS Estados (ex.: no TJPB, 'FUNDO UNICO DE PREVIDENCIA DO
# ESTADO DO RIO DE JANEIRO'), entao nada de regra por palavra. Conferido pelo nome e, no RJ
# e no MT, contra o Mapa Anual do CNJ 2025 (esfera Estadual, adm. indireta, regime Especial).
# Ficam FORA de proposito: CEDAE e CTC (RJ: regime Comum no CNJ), CAGEPA, EMPAER e CEHAP (PB:
# empresas, mesma duvida da EMBASA), INPAS e FUNDEC (RJ: nao confirmados como estaduais).
ESTADUAIS_CD = {
    "RJ": {"1", "65", "4", "3", "20", "351", "6", "17", "224", "76", "116", "191", "5", "208",
           "95", "14", "57", "236", "260", "252", "101", "12", "134", "228", "277", "80", "220",
           "293", "73", "247", "112", "126", "212", "210", "217", "60", "61", "79"},
    "MT": {"51", "148", "77", "82", "80", "79", "197", "230", "81", "50", "83", "47", "48"},
    "PB": {"78", "227", "233", "230", "247", "229", "241", "246", "271", "280", "261", "263",
           "273",
           # EMPAER e CEHAP: estatais DEPENDENTES, no Orcamento Fiscal da LOA-PB 2026 (Lei 14.257,
           # p. 893 e 850). A CAGEPA fica fora: so' no Orcamento de Investimento (p. 520).
           "234", "245"},
    # PR, PI e AP (04/10/2026): nesses TJs as autarquias do Estado NAO aparecem separadas -- o
    # Estado vem como devedor unico. O resto da lista e' municipal, federal (INSS, UFPR, AGU)
    # ou de OUTRO Estado ('ESTADO DE SANTA CATARINA (SC)' na lista do TJPR): fica fora.
    "PR": {"12"},
    "PI": {"41"},
    "AP": {"1"},
    # MG: autarquias/fundacoes do Estado cujo nome nao tem "MG"/"MINAS"/"ESTADUAL" e que a
    # regra por nome (_e_estadual) deixava sem ibge. No TJMG o cd_externo e' o nome normalizado.
    "MG": {"FUNED FUNDACAO EZEQUIEL DIAS", "FUNDACAO CLOVIS SALGADO",
           "IPEM INSTITUTO DE METROLOGIA E QUALIDADE EMG", "IGTEC INSTITUTO DE GEOINFORMACAO E TECNOLOGIA",
           "AGENCIA REGULADORA DE SERV DE ABAST DE AGUA E ESGOTO ARSAE", "IGA INSTITUTO DE GEOCIENCIAS APLICADAS",
           "FUNDACAO TV MINAS CULTURAL E EDUCATIVA TVE MG", "INSTITUTO DE PREVIDENCIA DO LEGISLATIVO DO EST M G",
           # orgaos ESTADUAIS que o casamento por sufixo punha no municipio de mesmo nome
           # (auditoria C2, corrigido em 05/10/2026): Fundacao Joao Pinheiro caia em Joao Pinheiro
           # e a UNIMONTES (universidade estadual) em Montes Claros
           "FUNDACAO JOAO PINHEIRO", "UNIMONTES UNIVERSIDADE ESTADUAL DE MONTES CLAROS"},
    # ES: IPAJM e' a previdencia do ESTADO (o nome homenageia o governador Jeronimo Monteiro) e
    # caia no municipio de Jeronimo Monteiro: R$ 25,9 mi sobre uma fila propria de R$ 1,9 mi.
    # Ja' tinha sido corrigido em jul/2026 no pipeline antigo (fetch_lup_tjes.py) e voltou no
    # db_build. O IPASJM (cd 2669) e' a previdencia MUNICIPAL e continua no municipio.
    "ES": {"1218"},
    # 05/10/2026: os 9 Estados que ainda nao tinham RCL. Lista lida nome a nome na lista de cada TJ;
    # ficam FORA empresas (SANACRE, EMATER/AC, COSAMA, SANESUL, CAER, COMPESA, ATS -- mesma duvida da
    # EMBASA: so' entram se a LOA mostrar que sao dependentes), INSS e orgaos de OUTROS Estados.
    # No TJRS e no TJSC o Estado vem como devedor unico. TJAC/TJAM/TJPA: cd_externo = nome normalizado.
    "RS": {'1'},
    "SC": {'11'},
    "TO": {'5', '21'},
    "RR": {'10', '35', '32', '36', '30', '31', '28', '29', '48'},
    "MS": {'113', '1', '123', '114', '135', '125', '118', '115', '126', '116', '117', '121', '134'},
    "PA": {'GOVERNO DO ESTADO DO PARA', 'IGEPREV', 'HOSPITAL OPHIR LOYOLA', 'CENTRO DE HEMOTERAPIA E HEMATOLOGIA DO PARA HEMOPA', 'DEPARTAMENTO DE TRANSITO DO ESTADO DO PARA', 'UNIVERSIDADE DO ESTADO DO PARA', 'FUNDACAO SANTA CASA DE MISERICORDIA DO PARA', 'JUNTA COMERCIAL DO ESTADO DO PARA JUCEPA', 'FASEPA FUNDACAO DE ATENDIMENTO SOCIOEDUCATIVO DO PARA', 'FUNDACAO CULTURAL DO PARA TANCREDO NEVES', 'CENTRO DE PERICIAS CIENTIFICAS RENATO CHAVES'},
    "AM": {'ESTADO DO AMAZONAS', 'UNIVERSIDADE DO ESTADO DO AMAZONAS UEA', 'FUNDO PREVIDENCIARIO DO ESTADO DO AMAZONAS AMAZONPREV', 'FUNDACAO DE VIGILANCIA EM SAUDE FVS', 'SUPERINTENDENCIA DE HABITACAO SUHAB', 'FUNDACAO CENTRO DE CONTROLE DE ONCOLOGIA DO ESTADO DO AMAZON', 'FUNDACAO HOSPITAL ADRIANO JORGE', 'FUNDACAO DE MEDICINA TROPICAL DOUTOR HEITOR VIEIRA DOURADO F', 'DEPARTAMENTO ESTADUAL DE TRANSITO DO AMAZONAS', 'TRIBUNAL DE JUSTICA DO ESTADO DO AMAZONAS TJAM', 'ASSEMBLEIA LEGISLATIVA DO ESTADO DO AMAZONAS', 'FUNDACAO DE HEMATOLOGIA E HEMOTERAPIA DO AMAZONAS HEMOAM', 'SUPERINTENDENCIA ESTADUAL DE NAVEGACAO PORTOS E HIDROVIAS SN', 'INSTITUTO DE PROTECAO AMBIENTAL DO AMAZONAS IPAAM', 'CENTRO DE EDUCACAO TECNOLOGICA DO AMAZONAS', 'FUNDACAO DE DERMATOLOGIA TROPICAL E VENEREOLOGIA ALFREDO DA '},
    "AC": {'ESTADO DO ACRE', 'INSTITUTO DE PREVIDENCIA DO ESTADO DO ACRE ACREPREVIDENCIA', 'FUNDACAO HOSPITAL ESTADUAL DO ACRE FUNDHACRE', 'INSTITUTO DE ADMINISTRACAO PENITENCIARIA DO ESTADO DO ACRE I', 'INSTITUTO SOCIO EDUCATIVO DO ESTADO DO ACRE ISE', 'FUNDACAO DE DESENVOLVIMENTO DE RECURSOS HUMANOS DA CULTURA E', 'DEPARTAMENTO DE ESTRADAS DE RODAGEM INFRAESTRUTURA HIDROVIAR', 'FUNDACAO DE TECNOLOGIA DO ESTADO DO ACRE FUNTAC', 'SERVICO DE AGUA E ESGOSTO DO ESTADO DO ACRE SANEACRE', 'DEPARTAMENTO ESTADUAL DE TRANSITO DO ESTADO DO ACRE DETRAN A', 'INSTITUTO DE DEFESA AGROPECUARIA E FLORESTAL DO ESTADO DO AC', 'INSTITUTO DE MEIO AMBIENTE DO ACRE IMAC', 'INSTITUTO DE TERRAS DO ACRE ITERACRE', 'INSTITUTO ESTADUAL DE DESENVOLVIMENTO DA EDUCACAO PROFISSION'},
    "PE": {'250', '396', '370', '426', '282'},
}
CD_DO_ESTADO = {"RJ": "1", "MT": "51", "PB": "78", "PR": "12", "PI": "41", "AP": "1",
                "RS": '1', "SC": '11', "TO": '5', "RR": '10', "MS": '113', "PA": 'GOVERNO DO ESTADO DO PARA', "AM": 'ESTADO DO AMAZONAS', "AC": 'ESTADO DO ACRE', "PE": '250'}  # o governo estadual na lista
# autarquias MUNICIPAIS que o casamento por nome nao liga ao municipio-mae
MUNICIPAIS_CD = {("RJ", "81"): "3304557",     # PREVI RIO
                 ("RJ", "268"): "3304557",    # FUNPREVI (Fundo Especial de Previdencia do Rio)
                 # nao sao do Estado do RJ (nao constam na LOA-RJ 2026); CNPJ municipal no CNJ
                 ("RJ", "82"): "3303906",     # INPAS - previdencia de Petropolis
                 ("RJ", "285"): "3301702",    # FUNDEC - fundacao de Duque de Caxias
                 ("PR", "39"): "4106902",     # IPMC (previdencia de Curitiba) -- entrou em 05/10,
                                               # depois que as linhas espelho do TJPR sairam
                 ("PR", "649"): "4106902",    # FAS - Fundacao de Acao Social de Curitiba
                 ("PR", "66"): "4106902",     # IPPUC (planejamento urbano de Curitiba)
                 # PREV SAO JOSE: o casamento por sufixo punha em PINHAIS (4119152), outro municipio
                 ("PR", "576"): "4125506"}    # -> Sao Jose dos Pinhais
# URBS e COHAB (Curitiba) ficam fora de proposito: empresas, mesma duvida da EMBASA.
# IPMC: ficou fora em 04/10 porque 387 dos 820 itens vinham sem valor; eram as linhas espelho
# de superpreferencia do TJPR, que o ad_tjpr pula desde 05/10.
# PREFEITURAS cuja grafia na lista do TJ nao casa com o nome oficial do IBGE
PREFEITURAS_CD = {("TO", "96"): "1712504",    # 'MARIANOPOLIS' = Marianopolis do Tocantins
                  ("AP", "6"): "1600501",     # 'MUNICIPIO DE OIAPOQUE-AP'
                  ("AP", "11"): "1600253",    # 'ITAUBAL DO PIRIRIM' = Itaubal
                  ("AP", "10"): "1600212"}    # 'CUTIAS DO ARAGUARI' = Cutias

# Grafias do TJBA que diferem do cadastro do IBGE. Bertopolis (MG) e Cristinapolis (SE)
# tambem aparecem na lista do TJBA mas sao de OUTRO Estado: ficam sem ibge de proposito.
ALIAS_BA = {"DIAS DAVILA": "DIAS D AVILA", "MARAGOJIPE": "MARAGOGIPE"}


def _e_estadual(n, uf, cd=None):
    """Heuristica p/ 'este ente pertence ao ESTADO' (nao a um municipio).
    Conservadora: prefere ERRAR PARA MENOS (deixar ibge=None => sem projecao) a
    poolar errado uma autarquia municipal de agua/esgoto no Estado."""
    if n.startswith(("SAAE", "SANEAR", "SERVICO", "MUNICIPIO", "CAMARA")):
        return False
    if uf == "ES":
        return "ESTADO DO ESPIRITO SANTO" in n or "DO ESPIRITO SANTO" in n \
            or "CAPIXABA" in n or "ESTADUAL" in n
    if uf == "MG":
        return "MINAS GERAIS" in n or n.endswith(" DE MG") or " DE MG " in n + " " \
            or "ESTADUAL" in n or "MINEIR" in n
    if uf == "BA":
        # "ESTADO DA BAHIA" exato: nao basta achar "BAHIA" (ha municipio 'X-BAHIA' e
        # entes de outros Estados na mesma lista do TJBA -- INSS, UNITINS, DESO...).
        return n == "ESTADO DA BAHIA" or "DO ESTADO DA BAHIA" in n or "ESTADUAL" in n and "BAHIA" in n
    if uf == "CE":
        # exato: a lista do TJCE tem 'ESTADO DE SAO PAULO', 'ESTADO DO PIAUI'... (outros Estados) e
        # institutos de previdencia MUNICIPAIS que nao sao do governo estadual
        return n == "ESTADO DO CEARA" or "DO ESTADO DO CEARA" in n
    if uf == "RN":
        if "RIO DE JANEIRO" in n or " RJ" in n or " SP " in n:   # DETRAN/RJ etc. aparecem na lista do TJRN
            return False
        # a lista do TJRN mistura outros Estados ('CEARA - ESTADO', 'SAO PAULO - ESTADO'),
        # INSS, DETRAN de outras UFs e institutos de previdencia MUNICIPAIS -> so o que e'
        # claramente do governo do RN. IPERN e' o instituto do Estado (os municipais tem nome de cidade).
        return n == "ESTADO DO RIO GRANDE DO NORTE" or "DO ESTADO DO RIO GRANDE DO NORTE" in n             or "RIO GRANDE DO NORTE" in n and "MUNICIPIO" not in n or "FUNDACAO JOSE AUGUSTO" in n             or n.split(" ")[0] in ("IPERN", "UERN", "IDEMA", "DETRAN", "DER", "EMATER", "FJA", "FUNDASE",
                                   "CAERN", "IDIARN", "ITEP", "JUCERN", "CEASA", "DATANORTE", "EMGERN", "FAPERN")
    if uf == "GO":
        # cuidado: dezenas de municipios de GO tem "DE GOIAS" no PROPRIO nome
        # (Palmeiras de Goias, Cachoeira de Goias...) -> nao basta achar "GOIAS"
        # no texto, tem que ser claramente o governo do ESTADO.
        return "ESTADO DE GOIAS" in n or "DO ESTADO DE GOIAS" in n \
            or "ESTADUAL" in n or "GOIASPREV" in n
    if uf == "SP":
        # Conservador de proposito (so 1 ente casa hoje, ver conferencia 2026-09-25):
        # o catalogo de 703 entidades do DEPRE/TJSP so tem "FAZENDA DO ESTADO DE SAO
        # PAULO" como devedora estadual direta -- autarquias estaduais (SPPREV, DER,
        # DAEE, USP/UNESP/UNICAMP etc.) nao aparecem la' e ficam de fora ate' serem
        # mapeadas uma a uma (nao dar match largo por "ESTADUAL" aqui: nomes de
        # consorcio/autarquia municipal usam a palavra tambem, ver MARCADORES_AUTARQUIA).
        return "DO ESTADO DE SAO PAULO" in n and "FAZENDA" in n
    if uf == "AL":
        # por cd_externo (id da entidade no SAPRE/TJAL), nao por nome: os nomes das
        # autarquias (CASAL, DER-AL, UNCISAL...) nao tem um padrao textual comum, e
        # o catalogo tem entes de fora do escopo com nome parecido (INSS, "Fazenda
        # Federal do Estado de Alagoas" = Uniao, nao o Estado; IMPREV Arapiraca =
        # municipal). Lista = ENTIDADES_ESTADUAIS conferida por CNPJ no projeto
        # RPA_RJ (al_sapre_api.py), mesma curadoria usada la' para separar a familia
        # estadual do resto do catalogo SAPRE.
        return cd in AL_ESTADUAIS_CD
    return False


# cd_externo (SAPRE/TJAL) das entidades estaduais diretas + autarquias/fundacoes/
# empresas do Estado de Alagoas -- ver _e_estadual. 28=Estado, demais conferidas
# por CNPJ no RPA_RJ (al_sapre_api.ENTIDADES_ESTADUAIS): CASAL, ALE, ADEAL, DER-AL,
# DETRAN-AL, ITEC, UNCISAL, IMA-AL, ARSAL, Alagoas Previdencia, UNEAL, ITERAL,
# IPASEAL SAUDE. NAO inclui INSS/Fazenda Nacional/Fazenda Federal (Uniao) nem
# IMPREV Arapiraca (municipal).
AL_ESTADUAIS_CD = {"28", "105", "106", "107", "108", "109", "110", "111", "112",
                   "115", "121", "122", "125", "136"}


def resolve_ibge(nome, uf, ix, cd=None):
    """Casa 'MUNICIPIO DE X' / 'PREFEITURA MUNICIPAL DE X' com o IBGE da UF."""
    if uf not in ix:
        return None, "outro"
    # listas curadas por cd_externo valem ANTES do casamento por nome: e' o casamento por
    # sufixo que punha CEHAB-RJ, Fundacao UERJ e FIPERJ no municipio do Rio (auditoria M2)
    if (uf, str(cd)) in MUNICIPAIS_CD:
        return MUNICIPAIS_CD[(uf, str(cd))], "autarquia"
    if (uf, str(cd)) in PREFEITURAS_CD:
        return PREFEITURAS_CD[(uf, str(cd))], "prefeitura"
    if str(cd) in ESTADUAIS_CD.get(uf, ()):
        return UF_ESTADO[uf], "estado" if CD_DO_ESTADO.get(uf) == str(cd) else "autarquia"
    n = loose(nome)
    tipo = "autarquia" if any(k in n for k in MARCADORES_AUTARQUIA) else None
    base = re.sub(r"^(MUNICIPIO|PREFEITURA MUNICIPAL|PREFEITURA)\s+(DE|DO|DA)?\s*", "", n).strip()
    cand = sem_prep(base)
    if uf == "BA" and cand not in ix[uf]:      # Itaguacu DA BAHIA tem "bahia" no nome oficial
        cand = cand.removesuffix(" BAHIA")
        cand = ALIAS_BA.get(cand, cand)
    ibge = ix[uf].get(cand)
    if ibge and tipo is None:
        return ibge, "prefeitura"
    if ibge:
        return ibge, "autarquia"
    if tipo == "autarquia":                       # autarquia com sufixo do municipio
        for chave, cod in ix[uf].items():
            if cand.endswith(" " + chave) or cand == chave:
                return cod, "autarquia"
    if uf in UF_ESTADO and _e_estadual(n, uf, str(cd)):  # Estado + autarquias -> pseudo-municipio
        return UF_ESTADO[uf], "estado" if str(cd) == "28" else "autarquia"
    return None, tipo or "outro"


# ------------------------------------------------------------------ adaptadores
def ad_tjes(d):
    for p in d.get("precatorios", []):
        sp = None
        if p.get("is_prioritario_idade"):
            sp = "Idade"
        elif p.get("is_prioritario_doenca"):
            sp = "Doença Grave"
        yield {"numero_fmt": p.get("cd_precatorio"), "numero": so_digitos(p.get("cd_precatorio")),
               "numero_origem": so_digitos(p.get("nu_acao")), "ordem": p.get("ordem"),
               "data_apresentacao": norm_data(p.get("dt_expedicao")),
               "natureza": norm_natureza(p.get("cd_natureza")),
               "ano_orcamento": ano(p.get("nu_ano_orcamento")), "valor": money(p.get("vl_atualizado")),
               "situacao": None, "superpreferencia": sp, "suspenso": 0,
               "credor": p.get("de_beneficiario"), "cpf_cnpj": None, "advogado": None}


def ad_tjba(d):
    """GOTCHA: `ordemPagamento` do TJBA e' SEMPRE 0 -- a posicao real esta em
    `ordemCronologica`. E sao DUAS filas independentes, cada uma numerada do 1:
    `flprioridade=1` (superpreferencia) e `flnormal=1` (comum). Somar as duas sem
    tratar produz ordens duplicadas e acumulado errado. Aqui a fila de prioridade
    vem primeiro (e' o que a norma manda) e a normal e' deslocada logo apos ela."""
    ps = d.get("precatorios", [])
    n_prio = sum(1 for x in ps if x.get("flprioridade") == 1)
    for p in ps:
        prio = p.get("flprioridade") == 1
        base = p.get("ordemCronologica") or 0
        yield {"numero_fmt": p.get("cdPrecatorio"), "numero": so_digitos(p.get("cdPrecatorio")),
               "numero_origem": None,
               "ordem": base if prio else base + n_prio,
               "data_apresentacao": norm_data(p.get("dtExpedicao") or p.get("dataExp")),
               "natureza": norm_natureza(p.get("cdNatureza")),
               "ano_orcamento": ano(p.get("nuAnoOrcamento")), "valor": money(p.get("valorDevido")),
               "situacao": None,
               "superpreferencia": "Prioridade" if prio else None,
               "suspenso": 0, "credor": p.get("deBeneficiario"), "cpf_cnpj": None, "advogado": None}


def ad_tjrj(d):
    """GOTCHA TRIPLO do TJRJ:
    (1) `OrdemPagamento` vem 0 em 100% dos casos; a posicao esta em `OrdemCronologica`,
        e chega como TEXTO ordinal ("18º").
    (2) essa ordem e' POR ANO-ORCAMENTO, nao global: a ordem 424 aparece 3x, nos
        orcamentos 2014, 2021 e 2025. O campo `NumSeqOrc` prova (202100424 = ano 2021 +
        ordem 424). Aqui a fila e' reordenada por (ano, ordem) e RENUMERADA de 1..N,
        que e' a ordem real de pagamento: exercicio mais antigo primeiro.
    (3) a lista "de ativos" TRAZ OS JA QUITADOS, com `Saldo` = 0 — no Municipio do Rio
        sao 971 de 3.908. O campo `Quitado` e' LIXO (diz "Sim" em 100% das linhas,
        inclusive nas abertas): o unico separador confiavel e' o `Saldo`. Carregar as
        linhas de saldo zero inflava a fila e o estoque do ente.
    O valor certo e' o `Saldo` (o que ainda se deve), NAO o `ValorHistorico` (a face).
    A regra antiga "Saldo vem ~0, usar ValorHistorico" era efeito colateral do
    `ordemPagamento=1` no coletor — corrigido em 2026-08-27, ver scripts/fetch_tjrj.py.
    """
    ps = [p for p in d.get("precatorios", []) if (p.get("Saldo") or 0) > 0.005]

    def _oc(x):
        return int(re.sub(r"\D", "", str(x.get("OrdemCronologica") or "")) or 0)

    for i, x in enumerate(sorted(ps, key=lambda y: (ano(y.get("Orcamento")) or 9999, _oc(y))), 1):
        x["_ordem_efetiva"] = i
    for p in ps:
        yield {"numero_fmt": p.get("NumeroPrecatorio"), "numero": so_digitos(p.get("NumeroPrecatorio")),
               "numero_origem": so_digitos(p.get("NumeroProcOriginario")),
               "ordem": p["_ordem_efetiva"],
               "data_apresentacao": norm_data(p.get("DataProtocolo")),
               "natureza": norm_natureza(p.get("SiglaNatureza")),
               "ano_orcamento": ano(p.get("Orcamento")),
               "valor": money(p.get("Saldo")),
               "situacao": p.get("SituacaoPrecatorio"),
               "superpreferencia": p.get("Prioridade") or None, "suspenso": 0,
               "credor": None, "cpf_cnpj": None, "advogado": None}


def carrega_natureza_tjrj(cx, ente_id, d):
    """Estatistica de QUITACAO POR NATUREZA (alimentar x comum), por coorte.

    Achado do parecer do card #3373 (Renata Pena x Municipio do Rio, 2026-08-27):
    a fila do Rio so' faz sentido quebrada por natureza — a coorte de 2025 (a
    ultima ja vencida) tinha 98,0% dos alimentares quitados contra 2,5% dos comuns.
    Um numero agregado de fila esconde exatamente o que decide se um credito sai
    no prazo ou fica represado.

    Por que so' o TJRJ (por enquanto): `ad_tjrj` (acima) DESCARTA os itens ja
    quitados (Saldo=0) antes de gravar em `precatorio` — correto para a fila viva,
    mas apaga o denominador necessario para calcular quitado_pct. Esta funcao le o
    JSON CRU (`d`, ja' carregado no chamador) ANTES desse filtro, so' para alimentar
    `fila_natureza_stats` — nao interfere em nada do que `precatorio_atual` mostra.
    Outros tribunais (TJCE, TJBA, TJAL) tem natureza mas descartam quitados do
    mesmo jeito nos seus proprios coletores; estender exigiria mudar cada um.
    """
    agg = defaultdict(lambda: [0, 0, 0.0])           # (ano, natureza) -> [itens, quitados, valor_aberto]
    for p in d.get("precatorios", []):
        a = ano(p.get("Orcamento"))
        if a is None:
            continue
        nat = norm_natureza(p.get("SiglaNatureza"))
        if nat is None:
            continue
        saldo = money(p.get("Saldo"))
        linha = agg[(a, nat)]
        linha[0] += 1
        if saldo <= 0.005:
            linha[1] += 1
        else:
            linha[2] += saldo
    cx.executemany(
        "INSERT INTO fila_natureza_stats (ente_id,tribunal,ano_orcamento,natureza,itens,"
        "quitados,valor_aberto) VALUES (?,?,?,?,?,?,?)",
        [(ente_id, "TJRJ", a, nat, itens, quit_, round(vab, 2))
         for (a, nat), (itens, quit_, vab) in agg.items()])


def ad_tjal(d):
    """SUPERPREFERENCIA (05/10/2026): o SAPRE nao marca a parcela do art. 100 §2o, mas ela
    aparece como uma 2a linha do MESMO id no MESMO ano, a de ordem menor (paga antes), com o
    valor do teto (R$ 25.426,65; R$ 24.472,23 no teto anterior) -- 1.998 pares no Estado de AL.
    Nao e' duplicata: as duas somadas batem com o oficio. Aqui so' se MARCA a linha da parcela."""
    NAT = {0: "Alimentar", 1: "Comum"}
    _ord = lambda p: (p.get("ultima_classificacao_orcamentaria") or {}).get("ordemclassificacao")
    grupos = {}
    for p in d.get("precatorios", []):
        grupos.setdefault((p.get("id"), p.get("anoorcamento")), []).append(p)
    parcela = set()
    for g in grupos.values():
        if len(g) == 2 and all(_ord(x) is not None for x in g):
            parcela.add(id(min(g, key=_ord)))
    for p in d.get("precatorios", []):
        uco = p.get("ultima_classificacao_orcamentaria") or {}
        yield {"numero_fmt": p.get("nuprocessosaj"), "numero": so_digitos(p.get("nuprocessosaj")),
               "numero_origem": so_digitos(p.get("numprocessoconhecimento")),
               "ordem": uco.get("ordemclassificacao"),
               "data_apresentacao": norm_data(p.get("datacadastro")),
               "natureza": NAT.get(p.get("naturezaprecatorio")),
               "ano_orcamento": ano(p.get("anoorcamento")), "valor": money(p.get("valorglobal")),
               "situacao": None,
               "superpreferencia": "Parcela superpreferencial" if id(p) in parcela else None,
               "suspenso": 0,
               "credor": p.get("nomerequerente"), "cpf_cnpj": p.get("cpfcnpjrequerente"),
               "advogado": None}


def ad_tjpe(d):
    for p in d.get("precatorios", []):
        yield {"numero_fmt": p.get("numero_cnj"), "numero": so_digitos(p.get("numero_cnj")),
               "numero_origem": None, "ordem": p.get("ordem"),
               "data_apresentacao": norm_data(p.get("recebimento")),
               "natureza": norm_natureza(p.get("natureza")), "ano_orcamento": ano(p.get("orcamento")),
               "valor": money(p.get("saldo_atualizado_num")),   # CAVEAT: 0 em 100% no TJPE
               "situacao": None, "superpreferencia": p.get("superpreferencia") or None,
               "suspenso": 0, "credor": None, "cpf_cnpj": None, "advogado": None}


def ad_tjsp(d):
    """SALDO ZERADO (05/10/2026): o PDF do DEPRE imprime 'Valor atualizado: 0,00' em ~1.400
    pendentes (246 do INSS, todos de 2026) -- provavel credito quitado ainda na lista. Fica no
    banco (a busca acha) mas SAI DA FILA (ordem None) com a nota em `situacao`; sem isso conta
    como item sem valor e pode bloquear a projecao do ente (limite de 20% no alfred_core)."""
    for p in d.get("precatorios", []):
        zerado = p.get("valor") is not None and money(p.get("valor")) == 0
        yield {"numero_fmt": p.get("depre"), "numero": so_digitos(p.get("depre")),
               "numero_origem": so_digitos(p.get("autos")),
               "ordem": None if zerado else p.get("ordem"),
               "data_apresentacao": norm_data(p.get("protocolo")),
               "natureza": norm_natureza(p.get("natureza")),
               "ano_orcamento": ano(p.get("ano_orcamento")),
               "valor": None if zerado else money(p.get("valor")),
               "situacao": ("saldo zerado na fonte (provavel quitado); fora da fila" if zerado else None),
               "superpreferencia": p.get("superpreferencia"),
               "suspenso": 1 if p.get("suspenso") else 0,
               "credor": None, "cpf_cnpj": None, "advogado": p.get("advogado")}


def ad_tjmg(lista):
    """Base RICA do RPA (municipal + estadual), estagiada por scripts/tjmg_stage.py.
    Traz o que o EPD antigo nao tinha: numero_origem (proc. execucao), data de
    apresentacao (Protocolo) e superpreferencia (do CSV, cobertura parcial ~73%)."""
    for p in lista:
        venc = p.get("venc")
        yield {"numero_fmt": p.get("num"), "numero": so_digitos(p.get("num")),
               "numero_origem": p.get("numero_origem"),
               "numero_eproc": p.get("numero_eproc"), "ordem": p.get("ordem"),
               "data_apresentacao": norm_data(p.get("protocolo")),
               "natureza": norm_natureza(p.get("natureza")),
               "ano_orcamento": venc if isinstance(venc, int) and venc < 3000 else None,
               "valor": money(p.get("valor")), "situacao": p.get("situacao") or None,
               "superpreferencia": p.get("superpreferencia"), "suspenso": p.get("suspenso", 0),
               "credor": p.get("credor"), "cpf_cnpj": None, "advogado": None}


# ------------------------------------------------------------------ carga
def ad_tjma(precs):
    """TJMA — Listas de Ordem Cronologica, estagiadas por scripts/tjma_stage.py.

    Dois luxos que a maioria dos tribunais nao da: o valor ja vem ATUALIZADO (nao e'
    face) e a superpreferencia do art. 100 §2o vem MARCADA na propria linha. Em
    compensacao o credor NAO e' publicado -- o art. 12 §3o da Res. CNJ 303/2019 veda
    identificar o beneficiario na lista, e o TJMA cumpre a risca.
    """
    for p in precs:
        yield {"numero_fmt": p.get("numero"), "numero": so_digitos(p.get("numero")),
               "numero_origem": None, "ordem": p.get("ordem"),
               "data_apresentacao": p.get("apresentacao"),
               "natureza": norm_natureza(p.get("natureza")),
               "ano_orcamento": ano(p.get("ano_orcamento")),
               "valor": money(p.get("valor_atualizado")),
               "situacao": None, "superpreferencia": p.get("superpreferencia"),
               "suspenso": 0, "credor": None, "cpf_cnpj": None, "advogado": None}


def ad_trt17(d):
    """GPREC (Justiça do Trabalho, TRT17/ES). A fila e' `listaCronologica`; o valor de
    cada RP e' a soma dos `exequentes.valorTotalBeneficio`; o ano-orcamento e'
    `vencimento`. Sem processo de origem no publico. Carregado p/ o rateio §23 do ES."""
    for it in d.get("listaCronologica", []):
        val = sum(money(e.get("valorTotalBeneficio")) for e in it.get("exequentes", []))
        prio = it.get("pagamentoPrioritario") == "Sim" or any(
            (e.get("prioridadeExequente") or "").strip() for e in it.get("exequentes", []))
        yield {"numero_fmt": it.get("numeroRP"), "numero": so_digitos(it.get("numeroRP")),
               "numero_origem": None, "numero_eproc": so_digitos(it.get("numeroPrecatorioRPV")),
               "ordem": it.get("ordemPagamento"),
               "data_apresentacao": norm_data(it.get("dataOficioProtocolo")),
               "natureza": norm_natureza(it.get("naturezaCredito")),
               "ano_orcamento": ano(it.get("vencimento")), "valor": round(val, 2),
               "situacao": None, "superpreferencia": "Prioridade" if prio else None,
               "suspenso": 0, "credor": None, "cpf_cnpj": None, "advogado": None}


def ad_trf2(fila):
    """TRF2 (Justiça Federal, RJ/ES). Fila ja parseada (pos, num, ano, val, nat, prio)
    em data/trf2_es.json por parse_trf2_es.py."""
    for it in fila:
        yield {"numero_fmt": it.get("num"), "numero": so_digitos(it.get("num")),
               "numero_origem": None, "ordem": it.get("pos"), "data_apresentacao": None,
               "natureza": norm_natureza(it.get("nat")),
               "ano_orcamento": ano(it.get("ano")), "valor": money(it.get("val")),
               "situacao": None, "superpreferencia": "Prioridade" if it.get("prio") else None,
               "suspenso": 0, "credor": None, "cpf_cnpj": None, "advogado": None}


def ad_trf2_rj(fila):
    """TRF2, municipios do RJ (parse_trf2_rj.py, aba Regime_Geral_RJ/Regime_Especial_RJ do .ods
    de pendentes). `od_cron` e' a ordem DENTRO do regime do ente (cada municipio esta em um so'
    regime); `numero_processo` e' o numero do precatorio no TRF2 (.4.02.9333) e `acao_originaria`
    o processo de execucao. `ano_proposta` = ano do orcamento. A lista e' de pendentes."""
    for it in fila:
        yield {"numero_fmt": it.get("numero_processo"), "numero": so_digitos(it.get("numero_processo")),
               "numero_origem": it.get("acao_originaria"), "ordem": it.get("od_cron"),
               "data_apresentacao": None, "natureza": norm_natureza(it.get("natureza")),
               "ano_orcamento": ano(it.get("ano_proposta")), "valor": money(it.get("val")),
               "situacao": f"Regime {it['regime']}" if it.get("regime") else None,
               "superpreferencia": "Prioridade" if it.get("prio") else None,
               "suspenso": 0, "credor": None, "cpf_cnpj": None, "advogado": None}


def _ano_orc_trf5(apres_iso, prc, prazos):
    """Ano do orcamento de um precatorio do TRF5. A ordem cronologica nao traz; o PDF de divida
    consolidada traz o PRAZO CONSTITUCIONAL (31/12/<ano do orcamento>) -> `prazos`. Sem ele (3%),
    vale o corte por data de apresentacao, medido nos proprios dados do TRF5: ate 1o/jul (<=2021),
    ate 2/abr (2022-2025), ate 1o/fev (>=2026) -> orcamento do ano seguinte; depois, o subsequente."""
    if prc in prazos:
        return prazos[prc]
    if not apres_iso:
        return None
    y, mmdd = int(apres_iso[:4]), apres_iso[5:10]
    corte = "07-01" if y <= 2021 else ("04-02" if y <= 2025 else "02-01")
    return y + 1 if mmdd <= corte else y + 2


def ad_trf5(itens, prazos):
    """TRF5 (Justica Federal, NE), ordem cronologica por entidade (scripts/fetch_trf5.py). `ordem`
    e' da entidade; `processo` e' o numero do precatorio no TRF5; `proc_origem` o da execucao.
    Sem credor (LGPD). Lista de pendentes (situacao Andamento/Sobrestado)."""
    for it in itens:
        apres = norm_data(it.get("data_apresentacao"))
        prc = (it.get("prc") or "").replace("PRC", "")
        yield {"numero_fmt": it.get("processo"), "numero": so_digitos(it.get("processo")),
               "numero_origem": it.get("proc_origem"), "ordem": it.get("ordem"),
               "data_apresentacao": apres, "natureza": norm_natureza(it.get("natureza")),
               "ano_orcamento": _ano_orc_trf5(apres, prc, prazos), "valor": money(it.get("valor")),
               "situacao": it.get("prc"), "superpreferencia": "Prioridade" if it.get("superpref") else None,
               "suspenso": 0, "credor": None, "cpf_cnpj": None, "advogado": None}


TRF2_FEDERAL_CD = "UNIAO_ORCAMENTO_FEDERAL"      # cd_externo do ente; alfred_core reconhece por ele


def ad_trf2_federal(path):
    """TRF2, fila FEDERAL ("relatorio_precatorios_orcamentarios.csv", baixado do site do TRF2).
    UMA ordem cronologica continua para todo devedor federal (Uniao, INSS, autarquias): quem
    paga e' o orcamento da Uniao, entao o arquivo nao tem coluna de devedor. CSV em latin-1,
    ';', com ~18 linhas de notas antes do cabecalho 'Nº de Ordem Cronológica'.

    - Linha com 'Data Pagamento' preenchida = ja paga (a proposta 2026 inteira saiu em
      03/2026): fica de fora, como nas demais listas de pendentes.
    - Nota 4 da fonte: alimentar acima de 180 SM aparece 2x -- a 1a limitada (incisos II/III)
      e a 2a com o SALDO (inciso IV). Nao e' dupla contagem; as duas linhas entram.
    - 'Não Alimentares' (inciso V) e' Comum. Atencao: norm_natureza() leria 'ALIMENT' ali.
    - O CPF parcial (3 digitos) NAO e' carregado."""
    linhas = open(path, encoding="latin-1").read().split("\n")
    ini = next(i for i, l in enumerate(linhas) if l.startswith("Nº de Ordem"))
    for row in csv.DictReader(linhas[ini:], delimiter=";"):
        row = {(k or "").strip(): (v or "").strip() for k, v in row.items()}
        if not row.get("Nº de Ordem Cronológica") or row.get("Data Pagamento"):
            continue
        base = row.get("Base legal para enquadramento na ordem cronológica", "")
        inciso = (re.search(r"Inciso\s+([IVX]+)", base) or [None, None])[1]
        yield {"numero_fmt": row["Número do Precatório"], "numero": so_digitos(row["Número do Precatório"]),
               "numero_origem": None, "ordem": int(row["Nº de Ordem Cronológica"]),
               "data_apresentacao": norm_data((row.get("Data de Autuação no TRF2") or "")[:10]),
               "natureza": "Comum" if base.upper().startswith("NÃO ALIMENT") else "Alimentar",
               "ano_orcamento": ano(row.get("Proposta")), "valor": money(row.get("Parcela Devida")),
               "situacao": f"Inciso {inciso} do art. 107-A §8º ADCT" if inciso else None,
               "superpreferencia": "Prioridade (idade/doença/PCD)" if inciso == "II" else None,
               "suspenso": 0, "credor": None, "cpf_cnpj": None, "advogado": None}


# TRT -> UF primaria (p/ resolver o ente do GPREC ao municipio). Os multi-estados
# (8=PA/AP, 10=DF/TO, 11=AM/RR, 14=RO/AC) usam a UF principal; refinar se necessario.
def ad_tjce(d):
    """Painel SAPRE do TJCE (Power BI publico; scripts/fetch_tjce.py).

    1 LINHA = 1 PARCELA/DESDOBRAMENTO, nao 1 precatorio: o superprecatorio do §20
    reaparece em varias coortes (em Maracanau, 6 parcelas de R$ 13,2 mi nas coortes
    2023-2028) e o credor com superpreferencia aparece DUAS vezes na mesma coorte —
    a linha 'Preferencial - Idade' e' a fatia do teto e a 'Orcamentario' e' o saldo
    na fila comum. Dedup por numero subestimaria a fila; as linhas entram todas.

    A `ordem` ja e' global 1..N por ente e ja poe preferencial antes de orcamentario
    dentro da coorte — vai direto, sem renumerar.

    `situacao` percorre Cadastrado -> Provisionamento Parcial -> Provisionamento Total
    -> Com Pagamento Parcial -> Pago (Extinto/Suspenso fora do fluxo). 'Provisionamento
    Total' e' caixa JA RESERVADO e continua na fila (nao e' pagamento); so' 'Pago' e
    'Extinto' saem, senao a fila do ente vem inflada.
    """
    MORTAS = {"pago", "extinto"}
    for p in d.get("itens", []):
        sit = (p.get("situacao") or "").strip()
        if loose(sit).lower() in MORTAS:
            continue
        # 'Preferencial - Doenca' | '- Idade' | '- PCD' | 'Orcamentario'. Sao TRES
        # modalidades e a mais comum e' DOENCA (6.324 no estado contra 1.538 de idade):
        # rotular tudo como "Idade" descreveria errado a maioria das superpreferencias.
        cls = str(p.get("classificacao") or "")
        sup = cls.split("-", 1)[1].strip() if cls.lower().startswith("prefer") else None
        # o painel publica valor original e valor atualizado; o atual manda quando existe
        valor = money(p.get("valor_atual")) or money(p.get("valor_original"))
        yield {"numero_fmt": p.get("processo"), "numero": so_digitos(p.get("processo")),
               "numero_origem": None, "ordem": p.get("ordem"),
               "data_apresentacao": norm_data(p.get("data_cadastro")),
               "natureza": norm_natureza(p.get("natureza")),
               "ano_orcamento": ano(p.get("ano_orcamento")), "valor": valor,
               "situacao": sit or None,
               "superpreferencia": sup,
               "suspenso": 1 if loose(sit).lower() == "suspenso" else 0,
               "credor": None, "cpf_cnpj": None, "advogado": None}


def ad_tjpa(d):
    """Painel da Coordenadoria de Precatorios do TJPA (scripts/fetch_tjpa.py).

    DUAS listas SEPARADAS, cada uma numerada do 1: a cronologica e a de
    superpreferencias — e a superpreferencia NAO aparece na cronologica. Quem carrega
    so' a primeira conclui que nao ha' ninguem na frente por idade. Aqui as duas sao
    fundidas e RENUMERADAS 1..N por (exercicio, superpreferencia primeiro, ordem), que
    e' a ordem real de consumo do caixa.

    A `ordem` da cronologica ja e' global por ente e cresce junto com o exercicio
    (Belem: 1..376 cobrindo 2024..2028), entao a fusao so' insere as superpreferencias
    no inicio do bloco do exercicio delas.

    `NATUREZA` traz o ESTADO grudado no tipo: 'ALIMENTAR', 'COMUM',
    'COMUM - PARCELADO', 'COMUM - SUSPENSO'. norm_natureza() resolve o tipo; o
    'SUSPENSO' vira flag e o 'PARCELADO' fica em `situacao`.
    Superpreferencia so' existe em credito alimentar (art.100 §2o), dai a natureza
    fixa nessas linhas — a tabela do painel nao traz o campo.
    """
    itens = [(p, True) for p in d.get("superpreferencia", [])]
    itens += [(p, False) for p in d.get("cronologica", [])]
    itens.sort(key=lambda t: (ano(t[0].get("exercicio")) or 9999,
                              0 if t[1] else 1, t[0].get("ordem") or 0))
    for i, (p, sup) in enumerate(itens, 1):
        nat_raw = "ALIMENTAR" if sup else (p.get("natureza") or "")
        t = loose(nat_raw)
        yield {"numero_fmt": p.get("processo"), "numero": so_digitos(p.get("processo")),
               "numero_origem": None, "ordem": i,
               "data_apresentacao": norm_data(p.get("autuacao")),
               "natureza": norm_natureza(nat_raw),
               "ano_orcamento": ano(p.get("exercicio")), "valor": money(p.get("valor")),
               "situacao": ("Parcelado" if "PARCELAD" in t else
                            ("Suspenso" if "SUSPENS" in t else None)),
               "superpreferencia": (p.get("modalidade") or "Idade") if sup else None,
               "suspenso": 1 if "SUSPENS" in t else 0,
               "credor": None, "cpf_cnpj": None, "advogado": None}


def ad_tjrr(d):
    """API REST do TJRR (scripts/fetch_tjrr.py). `situacao` vem vazia p/ ativo; valores
    observados: '' (fila normal), 'Pago Parcialmente' (saldo ainda em aberto, continua na
    fila), 'Suspenso' (5 casos). Sem status 'Pago' (quitado) na amostra coletada em
    2026-08-29 -- ao contrario do TJPI, nao ha' item ja liquidado misturado na fila."""
    for p in d.get("precatorios", []):
        sit = (p.get("situacao") or "").strip()
        prio = (p.get("prioridade") or "").strip()
        yield {"numero_fmt": p.get("precatorio"), "numero": so_digitos(p.get("precatorio")),
               "numero_origem": so_digitos(p.get("autos")), "ordem": p.get("ordem"),
               "data_apresentacao": norm_data(p.get("apresentacao")),
               "natureza": norm_natureza(p.get("natureza")),
               "ano_orcamento": ano(p.get("orcamento")), "valor": money(p.get("valorDeferido")),
               "situacao": sit or None, "superpreferencia": prio or None,
               "suspenso": 1 if loose(sit) == "SUSPENSO" else 0,
               "credor": None, "cpf_cnpj": None, "advogado": None}


def ad_tjpi(d):
    """SAPRE do TJPI (scripts/fetch_tjpi.py), tabela HTML sem coluna de status estruturada.

    ACHADO NA REVISAO (2026-08-29): o unico sinal de que um item ja foi PAGO vem embutido
    como texto livre em `observacoes` ('CREDITO PREFERENCIAL: PAGO') -- e NAO e' raro:
    2.887 dos 7.161 precatorios coletados (40%!) tem essa marca, todos de fila 'Ordem'
    normal (nao so' superpreferencia). O coletor nao filtra isso porque a pagina do
    tribunal mistura historico com fila viva. Sem este filtro o banco contaria como
    divida em mora um credito ja quitado -- o mesmo tipo de erro que o TJRJ jah teve
    (ver ad_tjrj) e que ad_tjce evita com o conjunto MORTAS. Os outros dois textos vistos
    ('AGUARDANDO COMPROVANTE', 'PRECATORIO: PENDENCIA/VERIFICACAO DE PAGAMENTO') NAO
    afirmam pagamento concluido -- ficam na fila, guardados em `situacao` p/ quem quiser
    filtrar depois."""
    for p in d.get("precatorios", []):
        obs = (p.get("observacoes") or "").strip()
        if "PAGO" in obs.upper():
            continue
        yield {"numero_fmt": p.get("numero_pje"), "numero": so_digitos(p.get("numero_pje")),
               "numero_origem": None, "ordem": p.get("posicao"),
               "data_apresentacao": norm_data(p.get("data_entrada_oficio")),
               "natureza": norm_natureza(p.get("natureza")),
               "ano_orcamento": ano(p.get("orcamento")), "valor": p.get("valor_num"),
               "situacao": obs or None, "superpreferencia": p.get("superpreferencia_motivo"),
               "suspenso": 0, "credor": None, "cpf_cnpj": None, "advogado": None}


def ad_tjpr(d):
    """Portlet Liferay do TJPR (scripts/fetch_tjpr.py). `Autos do Precatório` vem com os
    digitos do CPF/CNPJ do requerente MASCARADOS ('xxxx', LGPD) -- numero_origem fica
    None de proposito, pra nao gravar um numero incompleto que pareceria uma busca
    valida. `Valor Deferido` e' numero em ~85% das linhas; o resto (prioridade medica
    recem-entrada) ainda nao tem valor deferido publicado.

    LINHA ESPELHO (05/10/2026): as 3.613 linhas sem `Valor Deferido` sao TODAS as de
    idPrecatorio 'c...' (superpreferencia); em 3.611 o mesmo Oficio tem a linha 'p...' com o
    valor. Contar a 'c' como item a parte punha um item sem valor na fila (o IPMC de Curitiba
    tinha 47% da fila assim e travava a projecao). A 'c' com irma e' pulada; sem irma, valor
    vira None (nao 0: zero puxaria a mora para baixo)."""
    _tem_valor = lambda p: money(p.get("Valor Deferido")) > 0
    com_valor = {p.get("Ofício Precatório") for p in d.get("precatorios", [])
                 if str(p.get("idPrecatorio") or "").startswith("p") and _tem_valor(p)}
    for p in d.get("precatorios", []):
        if not _tem_valor(p) and str(p.get("idPrecatorio") or "").startswith("c") \
                and p.get("Ofício Precatório") in com_valor:
            continue
        sit = (p.get("Situação do Precatório") or "").strip()
        prio = (p.get("Prioridade") or "").strip()
        yield {"numero_fmt": p.get("Ofício Precatório"), "numero": so_digitos(p.get("Ofício Precatório")),
               "numero_origem": None, "ordem": p.get("Ordem"),
               "data_apresentacao": norm_data(p.get("Apresentação")),
               "natureza": norm_natureza(p.get("Natureza")),
               "ano_orcamento": ano(p.get("Orçamento")),
               "valor": money(p.get("Valor Deferido")) if _tem_valor(p) else None,
               "situacao": sit or None, "superpreferencia": prio or None,
               "suspenso": 1 if loose(sit) == "SUSPENSO" else 0,
               "credor": None, "cpf_cnpj": None, "advogado": None}


def ad_tjrs(d):
    """Lista Unificada do TJRS via exportacsv.php (scripts/fetch_tjrs.py). `carater` ja'
    vem A/C (bate direto com norm_natureza). Sem situacao/credor no CSV. A escolha de
    QUAIS arquivos chamar esta funcao (dedupe de fila_hash colidido) e' feita no laco
    bespoke em carrega(), nao aqui -- esta funcao so' converte os registros de 1 arquivo."""
    SUP = {"PI": "Idade", "PD": "Doença Grave", "PCD": "PCD"}
    # LINHA ESPELHO (05/10/2026): 15.221 dos 20.268 zeros do TJRS tem o MESMO numeroProcesso
    # com valor em outra linha do ente (tipicamente PI = 0 e N = valor cheio, ou o inverso
    # depois de calculada a parcela preferencial): a zerada e' pulada. Zero sem irma (4.385
    # do orcamento 2028 ainda sem valor publicado + ~660 antigos) vira None, nao 0.
    com_valor = {p.get("numeroProcesso") for p in d.get("precatorios", [])
                 if money(p.get("valorDevido")) > 0}
    for p in d.get("precatorios", []):
        if money(p.get("valorDevido")) <= 0 and p.get("numeroProcesso") in com_valor:
            continue
        prio = (p.get("prioridadeSigla") or "").strip().upper()
        yield {"numero_fmt": p.get("numeroProcesso"), "numero": so_digitos(p.get("numeroProcesso")),
               "numero_origem": None,
               "ordem": p.get("ordem") if isinstance(p.get("ordem"), int) else None,
               "data_apresentacao": norm_data(p.get("dataApresentacao")),
               "natureza": norm_natureza(p.get("carater")),
               "ano_orcamento": ano(p.get("verbaAno")),
               "valor": money(p.get("valorDevido")) or None,
               "situacao": None, "superpreferencia": SUP.get(prio), "suspenso": 0,
               "credor": None, "cpf_cnpj": None, "advogado": None}


def ad_tjgo(d):
    """Painel Power BI (embed AAD, capacidade dedicada) do TJGO (scripts/fetch_tjgo.py).
    O relatorio-fonte ja' se chama 'Pendentes e Preferenciais' -- por isso `situacao`
    (`andamento_calculo`) so' tem status de item AINDA EM ABERTO (AGUARDANDO PAGAMENTO,
    PAGO PARCIALMENTE, ACORDO, PROCESSANDO PAGAMENTO, RESERVADO, SUSPENSO -- confirmado
    na coleta completa de 2026-08-29, sem nenhum 'Pago'/'Extinto' misturado, ao contrario
    do TJPI): nao precisa do filtro tipo MORTAS que o ad_tjce usa. `ordem` (rotulo na UI
    'Ord PG') e' a posicao DENTRO da fila daquela entidade, nao um contador estadual.

    LINHAS REPETIDAS (05/10/2026): o fetch_tjgo pagina ordenando por um campo que se repete
    entre entes, e as paginas se sobrepoem na fronteira -- 28 linhas identicas (mesmo
    processo, ordem e valor). Ficam so' uma vez. (A mesma sobreposicao provavelmente PERDE
    linhas -- faltam 37 ordens em Goiania --, o que so' a recoleta com ordenacao unica resolve.)"""
    vistos = set()
    for p in d.get("itens", []):
        chave = (p.get("processo"), p.get("ordem"), p.get("valor"))
        if chave in vistos:
            continue
        vistos.add(chave)
        sit = (p.get("situacao") or "").strip()
        yield {"numero_fmt": p.get("processo"), "numero": so_digitos(p.get("processo")),
               "numero_origem": None, "ordem": p.get("ordem"),
               "data_apresentacao": norm_data(p.get("formalizacao")),
               "natureza": norm_natureza(p.get("natureza")),
               "ano_orcamento": ano(p.get("ano_orcamento")), "valor": money(p.get("valor")),
               "situacao": sit or None, "superpreferencia": p.get("prioridade") or None,
               "suspenso": 1 if loose(sit) == "SUSPENSO" else 0,
               "credor": None, "cpf_cnpj": None, "advogado": None}


def ad_tjsc(d):
    """Lista Unificada do TJSC, mesmo produto do TJES/LUP (scripts/fetch_tjsc.py).

    `valorDevido` e' o FACE do credito; `valorPagoNumerico` e' o que ja' foi desembolsado
    (soma de vlPagoNormal/Doenca/Idade/PNE/MenorValor/Leilao -- pagamentos parciais por
    superpreferencia ao longo do tempo). MESMA LICAO do TJRJ (ad_tjrj): o que resta em
    mora e' a DIFERENCA, nao o face -- carregar valorDevido puro superestimaria a divida
    de quem ja' recebeu parte. 954 dos 52.459 itens coletados em 2026-08-29 (1,8%) tem
    diferenca <= 0 (quitados) e sao pulados, mesma logica do Saldo=0 do TJRJ.

    A lista de entidades devedoras do TJSC inclui devedores de OUTROS ESTADOS (ex.:
    Estado de Roraima, fundacoes do AM/BA/PA/MT) cujo credito tramitou em SC mesmo assim
    -- confirmado pelo proprio campo `nmTribunal` de cada registro, nao inferido pelo
    nome do ente. Filtra por nmTribunal=='TJSC' por seguranca (caso a API um dia misture
    tribunais na mesma resposta)."""
    for p in d.get("precatorios", []):
        if (p.get("nmTribunal") or "TJSC") != "TJSC":
            continue
        vd = money(p.get("valorDevido"))
        vp = money(p.get("valorPagoNumerico"))
        liq = vd - vp
        if liq <= 0.01:
            continue
        tipo = (p.get("siglaTipo") or "").strip().upper()
        SUP = {"PI": "Idade", "PD": "Doença Grave", "PNE": "PCD"}
        yield {"numero_fmt": p.get("cdPrecatorioFormatado"),
               "numero": so_digitos(p.get("cdPrecatorioFormatado")),
               "numero_origem": so_digitos(p.get("nuAcao")), "ordem": p.get("posicaoOrdem"),
               "data_apresentacao": norm_data(p.get("dtExpedicao")),
               "natureza": norm_natureza(p.get("cdNatureza")),
               "ano_orcamento": ano(p.get("nuAnoOrcamento")), "valor": round(liq, 2),
               "situacao": None, "superpreferencia": SUP.get(tipo), "suspenso": 0,
               "credor": None, "cpf_cnpj": None, "advogado": None}


def ad_tjto(d):
    """Lista Unificada do TJTO/TRT10/TRF1 (sistema GRV, scripts/fetch_tjto.py) -- unifica as
    3 justicas numa fila so' por ente, com CREDOR por extenso (raro entre os tribunais do
    projeto). `Ordem` chega como ordinal texto ("1º"); `ValorAtual` (corrigido) prevalece
    sobre `ValorOriginal`. Sem status de pago/quitado na amostra (2026-08-29): so' Cadastrado,
    Provisionamento Total/Parcial (tratado a parte por SITUACOES_PROVISIONADO em modelo_p23.py)
    e Transferido Juizo Execucao -- nenhum precisa ser filtrado aqui."""
    def _val(s):
        if not s or not isinstance(s, str):
            return None
        n = re.sub(r"[^\d,]", "", s).replace(",", ".")
        try:
            return float(n)
        except ValueError:
            return None

    for p in d.get("precatorios", []):
        m = re.search(r"\d+", str(p.get("Ordem") or ""))
        prio = (p.get("Prioridade") or "").strip()
        yield {"numero_fmt": p.get("Processo"), "numero": so_digitos(p.get("Processo")),
               "numero_origem": so_digitos(p.get("AcaoOriginaria")),
               "ordem": int(m.group(0)) if m else None,
               "data_apresentacao": norm_data(p.get("Apresentacao")),
               "natureza": norm_natureza(p.get("Natureza")),
               "ano_orcamento": ano(p.get("AnoOrcamento")),
               "valor": _val(p.get("ValorAtual")) or _val(p.get("ValorOriginal")) or 0.0,
               "situacao": p.get("Situacao") or None,
               "superpreferencia": None if prio.upper() in ("", "NENHUMA") else prio,
               "suspenso": 0, "credor": p.get("Credor") or None, "cpf_cnpj": None,
               "advogado": None}


def ad_tjse(d):
    """Lista Unificada do TJSE (JSF/PrimeFaces, scripts/fetch_tjse.py). `tipo` distingue fila
    normal ("Cronologia") de superpreferencia ("Antecipacao - Idoso/Doenca Grave/PCD") --
    o prefixo "Antecipacao - " e' tirado, sobra so' o motivo. TEM CREDOR por extenso quando
    o tribunal publica (a maioria vem "-", mascarado)."""
    for p in d.get("precatorios", []):
        tipo = (p.get("tipo") or "").strip()
        sup = None if tipo.lower() == "cronologia" else re.sub(r"^Antecipa[cç][aã]o\s*-\s*", "", tipo)
        yield {"numero_fmt": p.get("numero_unico") or p.get("processo_tjse"),
               "numero": so_digitos(p.get("numero_unico") or p.get("processo_tjse")),
               "numero_origem": None, "ordem": int(p["ordem"]) if p.get("ordem") else None,
               "data_apresentacao": norm_data(p.get("apresentacao")),
               "natureza": norm_natureza(p.get("natureza")),
               "ano_orcamento": ano(p.get("ano_pagamento")), "valor": money(p.get("valor")),
               "situacao": None, "superpreferencia": sup or None, "suspenso": 0,
               "credor": p.get("credor"), "cpf_cnpj": None, "advogado": None}


def ad_tjac(d):
    """Painel Qlik Sense do TJAC (protocolo QIX via WebSocket, scripts/fetch_tjac.py --
    primeiro coletor Qlik do projeto). A fonte ja' vem filtrada pra' "Dados SEAP" (fila
    ativa) -- o coletor separa `_fora_da_fila_ativa.json` (majoritariamente QUITADO) num
    arquivo a parte, que comeca com "_" e por isso o laco generico ja' ignora sozinho.
    Ainda assim, `situacao_precatorio` traz uns poucos CANCELADO (6 em 4.131) misturados
    na fila ativa -- filtrados aqui. `tipo_fila` SUPERPREFERENCIAL/CRONOLOGICA ja' vem
    numa unica sequencia de `ordem` (superpreferencial primeiro), sem precisar renumerar
    como no TJBA. TEM CREDOR e ADVOGADO por extenso, e desde 2026-08-30 tambem o CPF/CNPJ
    cru do beneficiario (`documento_beneficiario` -- decisao do usuario de coletar sem
    custo onde a fonte ja' publica, ao inves de mascarar como os outros adaptadores)."""
    for p in d.get("precatorios", []):
        if (p.get("situacao_precatorio") or "").upper() == "CANCELADO":
            continue
        prio = (p.get("prioridade") or "").strip()
        sup = None
        if (p.get("tipo_fila") or "").upper() == "SUPERPREFERENCIAL":
            sup = prio.replace("_", " ").title() if prio else "Prioridade"
        yield {"numero_fmt": p.get("numero_precatorio"), "numero": so_digitos(p.get("numero_precatorio")),
               "numero_origem": None, "ordem": int(p["ordem"]) if p.get("ordem") else None,
               "data_apresentacao": norm_data(p.get("apresentacao")),
               "natureza": norm_natureza(p.get("tipo_natureza_credito")),
               "ano_orcamento": ano(p.get("ano_exercicio")), "valor": money(p.get("valor")),
               "situacao": p.get("situacao_precatorio"), "superpreferencia": sup, "suspenso": 0,
               "credor": p.get("nome_beneficiario"), "cpf_cnpj": p.get("documento_beneficiario"),
               "advogado": p.get("advogado")}


def ad_tjms(d):
    """SAPRE do TJMS via Playwright (Citrix bot-detection, scripts/fetch_tjms.py). `valor_atual`
    vem 0.0 em 14% das linhas -- e NAO e' so' item quitado/provisionado (519 dos 995 zerados
    estao com situacao 'Cadastrado', normal): parece so' nao populado nesses casos. Usa
    valor_atual quando > 0, senao cai pro valor_inscrito (face). So' 2 status (de 7.028)
    sao claramente quitados -- 'Com pagamento total' e 'Extinto' -- e ficam de fora; o
    resto (Cadastrado, Provisionamento total/parcial, Com pagamento parcial, Suspenso,
    Baixado com saldo, Requisitado o valor) segue em mora."""
    MORTAS = {"com pagamento total", "extinto"}
    for p in d.get("precatorios", []):
        sit = (p.get("situacao") or "").strip()
        if sit.lower() in MORTAS:
            continue
        valor = money(p.get("valor_atual")) or money(p.get("valor_inscrito"))
        # parcela do §20: o TJMS escreve '<CNJ>/2027' (sufixo = ano da parcela). so_digitos
        # colava o ano no numero e a busca pelo CNJ nao achava nenhuma das 5 parcelas.
        num = str(p.get("processo_precatorio") or "")
        m = re.match(r"^(.*)/(\d{4})$", num.strip())
        if m and m.group(2) == str(p.get("ano_orcamento") or "").strip():
            num = m.group(1)
        yield {"numero_fmt": p.get("processo_precatorio"),
               "numero": so_digitos(num),
               "numero_origem": so_digitos((p.get("processo_execucao") or "").split("/")[0]),
               "ordem": p.get("ord"), "data_apresentacao": norm_data(p.get("data_cadastro")),
               "natureza": norm_natureza(p.get("natureza")),
               "ano_orcamento": ano(p.get("ano_orcamento")), "valor": valor,
               "situacao": sit or None, "superpreferencia": None,
               "suspenso": 1 if sit.lower() == "suspenso" else 0,
               "credor": None, "cpf_cnpj": None, "advogado": None}


def ad_tjam(d):
    """Painel Power BI (publish to web) do TJAM (scripts/fetch_tjam.py). `situacao` tem
    DOIS status enormes que precisam sair da fila: 'Cancelado' (39% dos itens coletados
    em 2026-08-30 -- precatorio anulado, nao e' divida) e 'Pago'/'Pago Superpreferencial'
    (9%). 'Procedimento de Bloqueio' (34%!) FICA -- e' o SISBAJUD em andamento pra forcar
    o pagamento, item ainda nao quitado, so' com a cobranca ja' em curso (mesma logica do
    bloqueio mensal de FPM visto no NACP/TJBA). 'Pago - Com Saldo Remanescente' tambem
    fica (tem saldo em aberto apesar do nome). `valor` as vezes chega como STRING (bug de
    decompressao do DSR do Power BI, ~0,75% dos itens) -- money() ja' trata os dois tipos."""
    MORTAS = {"cancelado", "pago", "pago superpreferencial"}
    for p in d.get("itens", []):
        sit = (p.get("situacao") or "").strip()
        if sit.lower() in MORTAS:
            continue
        sup = (p.get("superpreferencia") or "").strip()
        yield {"numero_fmt": p.get("processo"), "numero": so_digitos(p.get("processo")),
               "numero_origem": None, "ordem": p.get("ordem"),
               "data_apresentacao": norm_data(p.get("apresentacao")),
               "natureza": norm_natureza(p.get("natureza")),
               "ano_orcamento": ano(p.get("exercicio")), "valor": money(p.get("valor")),
               "situacao": sit or None,
               "superpreferencia": None if sup.lower() in ("", "nao", "não") else sup,
               "suspenso": 1 if sit.lower() == "suspenso" else 0,
               "credor": None, "cpf_cnpj": None, "advogado": None}


def ad_tjap(d):
    """Sistema ScriptCase do TJAP (scripts/fetch_tjap.py) -- NAO e' Power BI (correcao de
    uma pesquisa anterior que confundiu tribunal). Dado mais limpo que a maioria: ja' vem
    com `valor_a_pagar_num` = saldo remanescente de verdade (nao a face) -- correlacao
    perfeita e testada com `situacao`: valor_a_pagar>0 <=> situacao != 'PAGO' (0 excecoes
    em 24.739 itens). Por isso basta pular valor<=0, sem precisar do texto de `situacao`."""
    for p in d.get("precatorios", []):
        valor = p.get("valor_a_pagar_num")
        if not valor or valor <= 0:
            continue
        prio = (p.get("prioridade") or "").strip()
        # ordem acima de 999 chega como TEXTO com ponto de milhar ("1.000", "12.086"): lida
        # como numero virava 1,0 e 12,086 (auditoria de 02/10/2026, 19.768 linhas fora de ordem)
        ordem = int(so_digitos(p.get("ordem")) or 0) or None
        yield {"numero_fmt": p.get("processo"), "numero": so_digitos(p.get("processo")),
               "numero_origem": None, "ordem": ordem,
               "data_apresentacao": norm_data(p.get("data_autuacao")),
               "natureza": norm_natureza(p.get("natureza")),
               "ano_orcamento": ano(p.get("ano_vencimento")), "valor": valor,
               "situacao": p.get("situacao"),
               "superpreferencia": None if prio.lower() in ("", "nao", "não") else prio,
               "suspenso": 1 if (p.get("situacao") or "").upper() == "SUSPENSO" else 0,
               "credor": None, "cpf_cnpj": None, "advogado": None}


def _chave_nome(s):
    """Nome de orgao so com letras/digitos (sem acento, espaco, pontuacao), p/ comparar o
    devedor da LINHA com o do ARQUIVO quando o PDF quebra ou trunca o nome na celula."""
    return re.sub(r"[^A-Z0-9]", "", unicodedata.normalize("NFKD", str(s or ""))
                  .encode("ascii", "ignore").decode().upper())


def ad_tjmt(d):
    """API anonima oficial do TJMT (`precatorios.tjmt.jus.br` -> `srp-api.tjmt.jus.br`,
    scripts/fetch_tjmt.py). Nenhum dos 10 status vistos na coleta de 2026-08-30 e' "pago
    por completo" (nem 'Em Tramite de Quitacao' -- ainda em processo) -- mas ha' pagamento
    PARCIAL registrado em varios (`valor_pago`>0 em ~7% dos itens), entao o valor certo e'
    a DIFERENCA, nao o requisitado bruto (mesma licao do TJRJ/TJSC).

    DUPLICATA CORRIGIDA em 2026-09-29 (auditoria C2): o PDF de cada autarquia/fundo traz
    TAMBEM a fila inteira do ente-pai (Estado de MT, Cuiaba, Varzea Grande...) -- carregar
    tudo inflava o TJMT de ~R$ 3,19 bi para R$ 16,64 bi e punha o mesmo precatorio em ate
    4 entes. Cada linha tem a coluna `orgao_devedor` (o devedor REAL): so fica a linha cujo
    devedor e' o proprio orgao do arquivo. Comparacao sem espacos/pontuacao porque o
    pdfplumber quebra palavra na celula ("RONDONOPOLI S"). Conferido: cada um dos 16.425
    numeros fica com exatamente 1 dono, nenhum se perde."""
    dono = _chave_nome(d.get("nome"))
    for p in d.get("precatorios", []):
        if _chave_nome(p.get("orgao_devedor")) != dono:
            continue                              # copia da fila de outro orgao
        valor = money(p.get("valor_requisitado")) - money(p.get("valor_pago"))
        if valor <= 0.01:
            continue
        sit = (p.get("situacao") or "").strip()
        prio = (p.get("preferencia") or "").strip()
        yield {"numero_fmt": p.get("protocolo"), "numero": so_digitos(p.get("protocolo")),
               "numero_origem": None, "ordem": p.get("ordem"),
               "data_apresentacao": norm_data(p.get("data_envio")),
               "natureza": norm_natureza(p.get("natureza")),
               "ano_orcamento": ano(p.get("exercicio_pagamento")), "valor": round(valor, 2),
               "situacao": sit or None,
               "superpreferencia": None if prio.lower() in ("", "nao", "não") else prio,
               "suspenso": 1 if sit.lower() == "suspenso" else 0,
               "credor": None, "cpf_cnpj": None, "advogado": None}


def ad_tjrn(d):
    """PDF SIGPRE do TJRN (scripts/fetch_tjrn.py, extraido apos vencer reCAPTCHA Enterprise
    -- coleta parcial em 2026-08-30, 104 de 257 entes, rate-limitada pelo score do captcha;
    reexecutar depois de um cooldown longo pra completar). GOTCHA identico ao TJBA: DUAS
    filas numeradas cada uma do 1 (`lista` = 'cronologica' ou 'prioridade') -- prioridade
    vem primeiro (e' o que a norma manda) e a cronologica e' deslocada apos ela. O PDF SO'
    marca natureza (Alimentar/Comum) nas linhas de `cronologica`; nas de `prioridade` o
    campo `natureza` na verdade guarda o MOTIVO da preferencia (Idade/Deficiencia) -- vai
    pra `superpreferencia`, natureza fica None nessas linhas (a fonte nao informa).

    DUPLICATAS CORRIGIDAS em 2026-09-29 (auditoria C2), em duas camadas:
    1. A lista de prioridade NAO e' outra fila: 9.976 dos 9.996 itens dela estao TAMBEM
       na cronologica do mesmo ente (com o valor da parcela preferencial, menor em ~43%
       dos casos). Carregar as duas contava o credito duas vezes e empurrava a `ordem`
       de toda a cronologica em n_prio (6.889 posicoes no Estado). Agora a prioridade so'
       MARCA o item da cronologica (`superpreferencia` = motivo) e a `ordem` e' a posicao
       publicada na cronologica, sem deslocamento.
    2. As listas do ESTADO e de NATAL sao CONSOLIDADAS (trazem IPERN, UERN, NATALPREV...
       -- a coluna `ente_devedor` diz o dono) e cada autarquia TAMBEM tem a propria lista,
       com a MESMA posicao da fila consolidada. Fica a linha da lista consolidada (e' a
       fila que o tribunal publica e paga) e sai a copia da lista da autarquia. Escolha
       deliberada em vez de "fica com o dono": NATALPREV nao tem IBGE (M2) e, pelo dono,
       as dividas dela sairiam da fila de Natal. 18 numeros tem 2 devedores LEGITIMOS
       (valor e processo administrativo diferentes) e ficam nos dois."""
    arquivo = _chave_nome(d.get("nome"))
    consolidado = _tjrn_consolidado()
    itens = list(d.get("precatorios", []))
    crono = {p.get("processo_pje") for p in itens if p.get("lista") == "cronologica"}
    prio = {p.get("processo_pje"): p.get("natureza") for p in itens if p.get("lista") == "prioridade"}
    for p in itens:
        e_prio = p.get("lista") == "prioridade"
        if e_prio and p.get("processo_pje") in crono:
            continue                              # vira so' marcacao do item cronologico
        dev = _chave_nome(p.get("ente_devedor"))
        if not e_prio and dev and arquivo.startswith(dev) and any(
                o.startswith(dev) or dev.startswith(o)
                for o in consolidado.get(so_digitos(p.get("processo_pje")), ())):
            continue                              # ja' esta' na lista consolidada do ente-pai
        yield {"numero_fmt": p.get("processo_pje"), "numero": so_digitos(p.get("processo_pje")),
               "numero_origem": None, "ordem": p.get("posicao") or 0,
               "data_apresentacao": norm_data(p.get("data_autuacao")),
               "natureza": None if e_prio else norm_natureza(p.get("natureza")),
               "ano_orcamento": ano(p.get("ano_orcamentario")), "valor": money(p.get("valor")),
               "situacao": None,
               "superpreferencia": p.get("natureza") if e_prio else prio.get(p.get("processo_pje")),
               "suspenso": 0, "credor": None, "cpf_cnpj": None, "advogado": None}


_TJRN_CONSOLIDADO = None


def _tjrn_consolidado():
    """{numero: {devedor}} das linhas cronologicas que aparecem na lista de OUTRO ente
    (a lista consolidada do Estado/Natal). Varre os JSONs uma vez; ver ad_tjrn."""
    global _TJRN_CONSOLIDADO
    if _TJRN_CONSOLIDADO is None:
        _TJRN_CONSOLIDADO = defaultdict(set)
        for f in glob.glob(os.path.join(BASE, "data", "tjrn", "*.json")):
            if os.path.basename(f).startswith("_"):
                continue
            try:
                d = json.load(open(f, encoding="utf-8"))
            except Exception:                                        # noqa: BLE001
                continue
            arquivo = _chave_nome(d.get("nome"))
            for p in d.get("precatorios", []):
                dev = _chave_nome(p.get("ente_devedor"))
                if p.get("lista") == "cronologica" and dev and not arquivo.startswith(dev):
                    _TJRN_CONSOLIDADO[so_digitos(p.get("processo_pje"))].add(dev)
    return _TJRN_CONSOLIDADO


def ad_tjpb(d):
    """"Consulta de Precatorios" (Ordem Cronologica) do TJPB, subdominio
    app.tjpb.jus.br (scripts/fetch_tjpb_fila.py) -- API JSON aberta, sem
    captcha/Playwright, achada em 2026-09-17 (o Painel Precatorios Municipais
    institucional em Qlik Sense, ja coletado em fetch_tjpb.py, so tem dado
    AGREGADO; este e' o balde A de verdade). O coletor ja separou a fila por
    `entidadeDevedora.id` real (o parametro de busca `entidadeId` agrupa
    municipio+autarquias na mesma consulta, mesmo bug de grao do TJRJ -- ver
    ad_tjrj) -- aqui cada arquivo e' um so' devedor. `posicao` e' estavel
    entre paginas (testado offset=0 e offset=20, sem overlap/gap). Sem
    situacao/pago explicito no schema -- a amostra testada (500 registros)
    nao trouxe nenhum valorAtual=0, sinal de que o endpoint publico ja so'
    devolve fila ABERTA. Sem credor (LGPD, aviso explicito na pagina).

    VALOR (03/10/2026): em 8.328 de 43.872 itens (4.894 so' no Estado da PB) o `valorAtual`
    vem NULO (nao zero) e o `valorOriginario` vem preenchido. Antes isso virava 0 e
    encolhia a mora e a fila. Agora usa o originario como PISO (sem correcao) e anota em
    `situacao`; a previsao desses entes fica um pouco otimista, nunca a zero."""
    for p in d.get("precatorios", []):
        superpref = p.get("superpreferencia")
        motivo = (p.get("tipoPreferencia") or {}).get("descricao")
        valor, sit = p.get("valorAtual"), None
        if valor is None and p.get("valorOriginario"):
            valor, sit = p.get("valorOriginario"), "valor originário, sem correção (o TJPB não publica o valor atual)"
        yield {"numero_fmt": p.get("numero"), "numero": so_digitos(p.get("numero")),
               "numero_origem": None, "ordem": p.get("posicao"),
               "data_apresentacao": norm_data(p.get("dataAutuacao")),
               "natureza": norm_natureza("A" if p.get("naturezaAlimentar") else "C"),
               "ano_orcamento": ano(p.get("anoOrcamento")), "valor": money(valor),
               "situacao": sit, "superpreferencia": motivo if superpref else None,
               "suspenso": 0, "credor": None, "cpf_cnpj": None, "advogado": None}


TRT_UF = {1: "RJ", 2: "SP", 3: "MG", 4: "RS", 5: "BA", 6: "PE", 7: "CE", 8: "PA",
          9: "PR", 10: "DF", 11: "AM", 12: "SC", 13: "PB", 14: "RO", 15: "SP", 16: "MA",
          17: "ES", 18: "GO", 19: "AL", 20: "SE", 21: "RN", 22: "PI", 23: "MT", 24: "MS"}


def novo_ente(cx, cache, tribunal, cd, nome, uf, ix):
    chave = (tribunal, str(cd))
    if chave in cache:
        return cache[chave]
    ibge, tipo = resolve_ibge(nome, uf, ix, cd)
    cur = cx.execute("INSERT OR IGNORE INTO ente (tribunal,cd_externo,nome,ibge,tipo) VALUES (?,?,?,?,?)",
                     (tribunal, str(cd), nome, ibge, tipo))
    eid = cur.lastrowid or cx.execute(
        "SELECT id FROM ente WHERE tribunal=? AND cd_externo=?", (tribunal, str(cd))).fetchone()[0]
    cache[chave] = eid
    return eid


def quarentena_valor(r):
    """Valor NEGATIVO publicado pela fonte nao e' divida a pagar (ex.: TJSP traz 'valor
    atualizado' negativo em ~920 itens da lista de pendentes). Somado, ele ABATE a mora e
    o acumulado a frente de todo o ente. Vira NULL (o modelo ja' trata NULL como 'sem
    valor') e o numero original fica anotado em `situacao`, para ninguem perder a pista.
    Auditoria 01-codigo.md, M4."""
    v = r.get("valor")
    if isinstance(v, (int, float)) and v < 0:
        nota = "valor negativo na fonte: %.2f" % v
        r["situacao"] = "%s; %s" % (r["situacao"], nota) if r.get("situacao") else nota
        r["valor"] = None
    return r


# Tribunais em que a parcela do §20 vem como uma linha por exercicio, com o MESMO numero
# (conferido na fonte em 05/10/2026: Caucaia/CE, Serra/ES, Campo Grande/MS, Estado de AL).
# NAO vale para TJPB/TJRN (numero repetido = requisicoes diferentes) nem para o TJMG (numero
# curto se repete entre anos).
TRIB_PARCELA_P20 = {"TJCE", "TJES", "TJMS", "TJAL"}


def marca_parcelas_p20(tribunal, regs):
    """Marca em `situacao` 'parcela k/n do §20' quando o MESMO numero aparece em 3+ exercicios
    seguidos com valores parecidos (+-15% da mediana; a ultima parcela pode ser menor). So'
    marca: nao muda valor, ordem nem fila."""
    if tribunal not in TRIB_PARCELA_P20:
        return regs
    grupos = {}
    for r in regs:
        if r.get("numero") and r.get("ano_orcamento"):
            grupos.setdefault(r["numero"], []).append(r)
    for g in grupos.values():
        anos = sorted({r["ano_orcamento"] for r in g})
        if len(g) < 3 or len(anos) != len(g) or anos != list(range(anos[0], anos[0] + len(anos))):
            continue
        vals = sorted(r["valor"] for r in g if r.get("valor"))
        if len(vals) != len(g):
            continue
        med = vals[len(vals) // 2]
        g.sort(key=lambda r: r["ano_orcamento"])
        if any(abs(r["valor"] - med) > 0.15 * med for r in g[:-1]) or g[-1]["valor"] > 1.15 * med:
            continue
        for k, r in enumerate(g, 1):
            nota = "parcela %d/%d do §20 (art. 100)" % (k, len(g))
            r["situacao"] = "%s; %s" % (r["situacao"], nota) if r.get("situacao") else nota
    return regs


def grava(cx, tribunal, arquivo, coletado_em, ente_id, regs):
    regs = marca_parcelas_p20(tribunal, [quarentena_valor(r) for r in regs])
    cur = cx.execute(
        "INSERT INTO coleta (tribunal,fonte,arquivo,coletado_em,carregado_em,n_registros) "
        "VALUES (?,?,?,?,?,?)",
        (tribunal, None, os.path.basename(arquivo), coletado_em,
         datetime.now(timezone.utc).isoformat(timespec="seconds"), len(regs)))
    cid = cur.lastrowid
    cx.executemany(
        "INSERT INTO precatorio (coleta_id,ente_id,tribunal,numero,numero_fmt,numero_origem,"
        "numero_eproc,ordem,"
        "data_apresentacao,natureza,ano_orcamento,valor,situacao,superpreferencia,suspenso,"
        "credor,cpf_cnpj,advogado) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        # .get no numero_eproc: so o TJMG tem esse campo, os outros ad_* nao o produzem
        [(cid, ente_id, tribunal, r["numero"], r["numero_fmt"], r["numero_origem"],
          r.get("numero_eproc"), r["ordem"],
          r.get("data_apresentacao"), r["natureza"], r["ano_orcamento"], r["valor"], r["situacao"],
          r["superpreferencia"], r["suspenso"], r["credor"], r["cpf_cnpj"], r["advogado"]) for r in regs])
    return len(regs)


def materializa_coleta_atual(cx):
    """Preenche a tabela coleta_atual com a coleta mais recente de cada (tribunal, arquivo).
    Mesmo criterio da antiga view: coletado_em DESC, desempate por id DESC. `arquivo`
    NULL fica de fora, como na view (la' `c2.arquivo = c.arquivo` nunca casava NULL);
    aqui o PARTITION BY juntaria os NULLs num grupo so', dai' o filtro explicito."""
    cx.execute("DELETE FROM coleta_atual")
    cx.execute(
        "INSERT INTO coleta_atual (id,tribunal,fonte,arquivo,coletado_em,carregado_em,n_registros) "
        "SELECT id,tribunal,fonte,arquivo,coletado_em,carregado_em,n_registros FROM ("
        "  SELECT c.*, ROW_NUMBER() OVER (PARTITION BY tribunal, arquivo "
        "                                 ORDER BY coletado_em DESC, id DESC) AS rn "
        "  FROM coleta c WHERE arquivo IS NOT NULL) "
        "WHERE rn = 1")
    return cx.execute("SELECT COUNT(*) FROM coleta_atual").fetchone()[0]


FONTES = [
    ("TJES", "data/lup_tjes/*.json", "ES", ad_tjes, "cd_entidade", "nome_lup"),
    ("TJBA", "data/tjba/[0-9]*_*.json", "BA", ad_tjba, "cd_entidade", "nome"),
    ("TJRJ", "data/tjrj/*.json", "RJ", ad_tjrj, "cd_entidade", "nome"),
    ("TJAL", "data/tjal/*.json", "AL", ad_tjal, "cd_entidade", "nome"),
    ("TJPE", "data/tjpe/*.json", "PE", ad_tjpe, "cd_entidade", "nome"),
    ("TJSP", "data/tjsp/[0-9]*_*.json", "SP", ad_tjsp, "cd_entidade", "nome"),
    ("TJRR", "data/tjrr/*.json", "RR", ad_tjrr, "devedor_id", "nome"),
    ("TJPI", "data/tjpi/*.json", "PI", ad_tjpi, "cd_entidade", "nome"),
    ("TJPR", "data/tjpr/*.json", "PR", ad_tjpr, "id_entidade", "nome"),
    ("TJSC", "data/tjsc/*.json", "SC", ad_tjsc, "cd_entidade", "nome"),
    ("TJTO", "data/tjto/*.json", "TO", ad_tjto, "id_entidade", "nome"),
    ("TJSE", "data/tjse/*.json", "SE", ad_tjse, "cd_entidade", "nome"),
    ("TJMS", "data/tjms/*.json", "MS", ad_tjms, "cd_entidade", "nome"),
    ("TJAP", "data/tjap/*.json", "AP", ad_tjap, "id_entidade", "nome"),
    ("TJMT", "data/tjmt/*.json", "MT", ad_tjmt, "id_orgao_devedor", "nome"),
    ("TJRN", "data/tjrn/*.json", "RN", ad_tjrn, "ente_id", "nome"),
    ("TJPB", "data/tjpb_fila/*.json", "PB", ad_tjpb, "id_entidade", "nome"),
]


def _e_cabeca_tjrs(nome):
    n = loose(nome)
    return (n.startswith("MUNICIPIO DE") or n.startswith("MUNICIPIO DO")
            or n.startswith("ESTADO DO RIO GRANDE DO SUL"))


def _tjrs_pular(dtjrs):
    """Regra de colisao de fila_hash do TJRS (ver o comentario em carrega()). Devolve
    (ids a pular, {hash: [ids]}). Funcao propria para o --verifica usar a MESMA regra."""
    grupos_hash = defaultdict(list)
    for eid, (d, _f) in dtjrs.items():
        h = d.get("fila_hash")
        if h and (d.get("total") or 0) > 0:
            grupos_hash[h].append(eid)
    pular_tjrs = set()
    for ids in grupos_hash.values():
        if len(ids) < 2:
            continue
        cabecas = [i for i in ids if _e_cabeca_tjrs(dtjrs[i][0].get("nome"))]
        pular_tjrs.update((set(ids) - set(cabecas)) if len(cabecas) == 1 else set(ids))
    return pular_tjrs, grupos_hash


# --pasta TRIB=DIR (so' com --saida/--verifica): le a pasta crua de um tribunal de FONTES de
# outro lugar, p/ construir um banco de "depois" sem trocar data/ (ex.: o TJSP reprocessado,
# auditoria A8 item A). Vazio = comportamento normal.
PASTAS = {}


def _padrao_fonte(trib, padrao):
    if trib in PASTAS:
        return os.path.join(PASTAS[trib], os.path.basename(padrao))
    return os.path.join(BASE, padrao)


def carrega(cx, muns, ix):
    cache, resumo = {}, {}
    for trib, padrao, uf, adap, kcd, knome in FONTES:
        n_prec = n_ent = 0
        for f in sorted(glob.glob(_padrao_fonte(trib, padrao))):
            if os.path.basename(f).startswith("_"):
                continue
            try:
                d = json.load(open(f, encoding="utf-8"))
            except Exception:
                continue
            if not isinstance(d, dict) or "precatorios" not in d:
                continue                                  # consultas pontuais do TJBA
            eid = novo_ente(cx, cache, trib, d.get(kcd), d.get(knome) or "?", uf, ix)
            regs = list(adap(d))
            if regs:
                n_prec += grava(cx, trib, f, mtime_iso(f), eid, regs)
                n_ent += 1
            if trib == "TJRJ":
                carrega_natureza_tjrj(cx, eid, d)
        resumo[trib] = (n_ent, n_prec)

    # MG: base RICA do RPA (municipal + estadual), estagiada em data/tjmg/precatorios.json
    # por scripts/tjmg_stage.py. SUBSTITUI a antiga fonte data/epd_itens/ (a consulta
    # interativa do site, que NAO servia as capitais -- BH/Contagem/Betim/Ipatinga ficavam
    # de fora). A ordem da fila ja vem calculada pelo stage: (Ano Venc., Alimentar antes de
    # Comum, Numero) -- ver o cabecalho de tjmg_stage.py (corrigido em 29/09/2026). Uma coleta
    # por ente, com `arquivo` sintetico unico (coleta_atual agrupa por arquivo).
    n_prec = n_ent = 0
    fmg = os.path.join(BASE, "data", "tjmg", "precatorios.json")
    if os.path.exists(fmg):
        dmg = json.load(open(fmg, encoding="utf-8"))
        coletado = dmg.get("coletado_em") or mtime_iso(fmg)
        for e in dmg.get("entes", []):
            nome_ente = e.get("ente") or "?"
            slug = loose(nome_ente)[:60]
            eid = novo_ente(cx, cache, "TJMG", slug, nome_ente, e.get("uf", "MG"), ix)
            regs = list(ad_tjmg(e.get("precatorios", [])))
            if regs:
                n_prec += grava(cx, "TJMG", f"tjmg_{slug}.json", coletado, eid, regs)
                n_ent += 1
    resumo["TJMG"] = (n_ent, n_prec)

    # MA: Listas de Ordem Cronologica do TJMA (PDF do hotsite) estagiadas em
    # data/tjma/precatorios.json por scripts/tjma_stage.py. Cobre o ESTADO (direta +
    # autarquias) e SAO LUIS. A 3a lista do tribunal ("INSS e Municipios Diversos")
    # NAO entra: nao identifica o ente devedor em 93% das linhas, e sem ente nao ha
    # fila por municipio. O `ibge` ja vem resolvido do stager ('21' = pseudo-municipio
    # do Estado, 2111300 = Sao Luis).
    n_prec = n_ent = 0
    fma = os.path.join(BASE, "data", "tjma", "precatorios.json")
    if os.path.exists(fma):
        dma = json.load(open(fma, encoding="utf-8"))
        coletado = dma.get("coletado_em") or mtime_iso(fma)
        for e in dma.get("entes", []):
            nome_ente = e.get("ente") or "?"
            slug = loose(nome_ente)[:60]
            eid = novo_ente(cx, cache, "TJMA", slug, nome_ente, e.get("uf", "MA"), ix)
            # o stager ja sabe o IBGE (Estado vs Sao Luis); grava direto no ente
            if e.get("ibge"):
                cx.execute("UPDATE ente SET ibge=? WHERE id=?", (e["ibge"], eid))
            regs = list(ad_tjma(e.get("precatorios", [])))
            if regs:
                n_prec += grava(cx, "TJMA", f"tjma_{slug}.json", coletado, eid, regs)
                n_ent += 1
    resumo["TJMA"] = (n_ent, n_prec)

    # TRTs (Justica do Trabalho) — filas REAIS por ente, para o rateio §23 entre justicas
    # usar dado itemizado em vez do Mapa CNJ. GPREC e' nacional (mesmo formato p/ os 24);
    # cada TRT coletado fica em data/trt<N>/ (scripts/gprec_coletar.py --trt N). O TRT17/ES
    # foi o piloto; a UF vem do mapa abaixo (p/ resolver o ente ao municipio).
    for tdir in sorted(glob.glob(os.path.join(BASE, "data", "trt[0-9]*"))):
        if not os.path.isdir(tdir):
            continue
        m = re.search(r"trt(\d+)$", os.path.basename(tdir))
        if not m:
            continue
        trib = "TRT" + m.group(1)
        uf = TRT_UF.get(int(m.group(1)), "?")
        n_prec = n_ent = 0
        for f in sorted(glob.glob(os.path.join(tdir, "*.json"))):
            if os.path.basename(f).startswith("_"):
                continue
            try:
                d = json.load(open(f, encoding="utf-8"))
            except Exception:
                continue
            if not isinstance(d, dict) or "listaCronologica" not in d:
                continue
            eid = novo_ente(cx, cache, trib, d.get("cnpj") or os.path.basename(f),
                            d.get("nomeDevedor") or d.get("nome") or "?", uf, ix)
            regs = list(ad_trt17(d))
            if regs:
                n_prec += grava(cx, trib, f, mtime_iso(f), eid, regs)
                n_ent += 1
        if n_ent:
            resumo[trib] = (n_ent, n_prec)

    # TRF2: UM arquivo, muitos ibge (parse_trf2_es.py). O ibge e' a CHAVE -> crio o ente
    # ja com o ibge certo (nao dependo do resolve_ibge pelo nome).
    n_prec = n_ent = 0
    # RJ: a chave "ESTADO" (sem ibge) fica de fora -- o Estado do RJ no TRF2 entra pelo pool
    # estadual quando for decidido (ver ESTADUAIS_CD), nao como municipio.
    for arq, adap in (("trf2_es.json", ad_trf2), ("trf2_rj.json", ad_trf2_rj)):
        ftrf2 = os.path.join(BASE, "data", arq)
        if not os.path.exists(ftrf2):
            continue
        coletado = mtime_iso(ftrf2)
        for ib, e in json.load(open(ftrf2, encoding="utf-8")).items():
            if not str(ib).isdigit():
                continue
            chave = ("TRF2", str(ib))
            if chave in cache:
                eid = cache[chave]
            else:
                cur = cx.execute("INSERT OR IGNORE INTO ente (tribunal,cd_externo,nome,ibge,tipo) "
                                 "VALUES (?,?,?,?,?)", ("TRF2", str(ib), e.get("municipio") or e.get("devedor") or "?",
                                                        str(ib), "prefeitura"))
                eid = cur.lastrowid or cx.execute(
                    "SELECT id FROM ente WHERE tribunal=? AND cd_externo=?", ("TRF2", str(ib))).fetchone()[0]
                cache[chave] = eid
            regs = list(adap(e.get("fila", [])))
            if regs:
                n_prec += grava(cx, "TRF2", f"trf2_{ib}.json", coletado, eid, regs)
                n_ent += 1
    # TRF2 federal: fila unica da Uniao e autarquias federais (ad_trf2_federal). Sem ibge:
    # o devedor e' o orcamento federal, nao um municipio/Estado.
    ffed = os.path.join(BASE, "data", "trf2_federal", "relatorio_precatorios_orcamentarios.csv")
    if os.path.exists(ffed):
        cur = cx.execute("INSERT OR IGNORE INTO ente (tribunal,cd_externo,nome,ibge,tipo) VALUES (?,?,?,?,?)",
                         ("TRF2", TRF2_FEDERAL_CD, "UNIÃO FEDERAL E AUTARQUIAS FEDERAIS (orçamento federal - TRF2)",
                          None, "outro"))
        eid = cur.lastrowid or cx.execute(
            "SELECT id FROM ente WHERE tribunal=? AND cd_externo=?", ("TRF2", TRF2_FEDERAL_CD)).fetchone()[0]
        regs = list(ad_trf2_federal(ffed))
        if regs:
            n_prec += grava(cx, "TRF2", "trf2_federal_orcamentarios.csv", mtime_iso(ffed), eid, regs)
            n_ent += 1
    resumo["TRF2"] = (n_ent, n_prec)

    # TRF5 (scripts/fetch_trf5.py): 1 JSON por entidade devedora. So' entra relatorio cujo rodape
    # (total e n de precatorios) CONFERE com o que o parser leu. A UF vem do sufixo do nome
    # ("... - AL" / "... PB"): o PDF de uma UF traz devedores de outras (ESTADO DE SAO PAULO no
    # PDF de AL). Estado e autarquias estaduais ficam sem ibge (sem pool por cd_externo ainda).
    n_prec = n_ent = 0
    d5 = os.path.join(BASE, "data", "trf5")
    fpz = os.path.join(d5, "prazos_prc.json")
    prazos5 = json.load(open(fpz, encoding="utf-8")) if os.path.exists(fpz) else {}
    for f in sorted(glob.glob(os.path.join(d5, "*_*_*.json"))):
        try:
            d = json.load(open(f, encoding="utf-8"))
        except Exception:
            continue
        if not isinstance(d, dict) or d.get("confere") is not True or not d.get("itens")                 or not d.get("entidade"):          # relatorio sem nome de entidade (id 377): nao da' p/ atribuir
            continue
        nome = d["entidade"]
        m = re.search(r"[\s/-]+([A-Z]{2})\s*$", nome.upper())
        uf = m.group(1) if m and m.group(1) in ix else None
        base_nome = nome[:m.start()].strip() if uf else nome
        if uf is None and "MUNICIPIO" in loose(nome):
            # sem sufixo de UF no nome: vale a UF mais frequente nos PRC da entidade
            ufs = [(i.get("prc") or "")[-2:] for i in d["itens"]]
            top = max(set(ufs), key=ufs.count) if ufs else None
            uf = top if top in ix else None
        eid = novo_ente(cx, cache, "TRF5", f"{d['id']}_{d['seq']}", base_nome if uf else nome, uf, ix)
        regs = list(ad_trf5(d["itens"], prazos5))
        if regs:
            n_prec += grava(cx, "TRF5", os.path.basename(f), mtime_iso(f), eid, regs)
            n_ent += 1
    if n_ent:
        resumo["TRF5"] = (n_ent, n_prec)

    # TJCE e TJPA: paineis Power BI publicos (scripts/powerbi_publico.py). Um arquivo
    # por ente, mas com esquema proprio -- nao entram no laco generico de FONTES, que
    # exige a chave "precatorios". Nao ha' codigo de ente no painel: o cd_externo e' o
    # NOME normalizado (estavel dentro do tribunal), como ja se faz no TJMG.
    for trib, pasta, uf, adap, chaves in (
            ("TJCE", "tjce", "CE", ad_tjce, ("itens",)),
            ("TJPA", "tjpa", "PA", ad_tjpa, ("cronologica", "superpreferencia")),
            ("TJGO", "tjgo", "GO", ad_tjgo, ("itens",)),
            ("TJAM", "tjam", "AM", ad_tjam, ("itens",))):
        n_prec = n_ent = 0
        for f in sorted(glob.glob(os.path.join(BASE, "data", pasta, "*.json"))):
            if os.path.basename(f).startswith("_"):
                continue
            try:
                d = json.load(open(f, encoding="utf-8"))
            except Exception:                                          # noqa: BLE001
                continue
            if not isinstance(d, dict) or not any(k in d for k in chaves):
                continue
            nome_ente = d.get("ente") or "?"
            eid = novo_ente(cx, cache, trib, loose(nome_ente)[:60], nome_ente, uf, ix)
            regs = list(adap(d))
            if regs:
                n_prec += grava(cx, trib, f, d.get("coletado_em") or mtime_iso(f), eid, regs)
                n_ent += 1
        if n_ent:
            resumo[trib] = (n_ent, n_prec)

    # TJRS: exportacsv.php do sistema Lista Unificada tem um BUG DO SERVIDOR confirmado na
    # coleta de 2026-08-29 -- varios "devedor=<id>" DIFERENTES e validos (existem no <select>
    # da pagina) devolvem o MESMO CSV byte-a-byte. 33 grupos de colisao, 120 dos 733 entes
    # afetados. O maior grupo (24 entes) e' o Estado do RS + 23 orgaos/autarquias estaduais,
    # todos devolvendo a fila do Estado (R$14,2 bi) -- e o mesmo padrao se repete em miniatura
    # em ~28 outros grupos, sempre "Municipio de X" + as PROPRIAS autarquias/fundacoes/
    # hospitais/institutos de previdencia de X (ex.: Municipio de Sao Leopoldo + o SAAE + a
    # Fundacao Hospital de Sao Leopoldo, todos com a mesma fila de 1.370 itens). Ou seja: o
    # sistema nao tem fila propria pra' esses orgaos subordinados e devolve a do municipio-mae.
    # Carregar cegamente inflaria o total (a mesma divida contada 1x por ente colidido) OU
    # atribuiria divida errada a quem nao a deve. REGRA: dentro de cada grupo de mesmo
    # fila_hash, se EXATAMENTE UM membro e' o orgao "cabeca" (Municipio de X / Estado do Rio
    # Grande do Sul), a fila fica so' com ele -- os demais (subordinados sem fila propria) sao
    # pulados. Sem cabeca unica -- 4 grupos: um trio hospitalar de Pelotas sem o Municipio no
    # grupo, um par nao identificado, um bloco de orgaos FEDERAIS (Uniao/INSS/Ministerio da
    # Agricultura) e um grupo com municipios de 5 estados diferentes sem nenhuma relacao entre
    # si -- o grupo inteiro fica de fora ate' existir uma fonte melhor pra' desambiguar. Entes
    # com fila_hash unico (ou fila vazia) carregam normal. Efeito medido: 638/733 entes,
    # 102.716 precatorios, R$17,20 bi (vs. R$379 bi se somasse cego o arquivo bruto de todo
    # mundo, ou R$17,92 bi se so' deduplicasse por hash sem excluir os 4 grupos ambiguos).
    n_prec = n_ent = 0
    dtjrs = {}
    for f in sorted(glob.glob(os.path.join(BASE, "data", "tjrs", "*.json"))):
        try:
            d = json.load(open(f, encoding="utf-8"))
        except Exception:
            continue
        if isinstance(d, dict) and "precatorios" in d and d.get("id_entidade") is not None:
            dtjrs[d["id_entidade"]] = (d, f)

    pular_tjrs, _ = _tjrs_pular(dtjrs)

    for eid, (d, f) in sorted(dtjrs.items()):
        if eid in pular_tjrs:
            continue
        nome_ente = d.get("nome") or "?"
        eeid = novo_ente(cx, cache, "TJRS", eid, nome_ente, "RS", ix)
        regs = list(ad_tjrs(d))
        if regs:
            n_prec += grava(cx, "TJRS", f, mtime_iso(f), eeid, regs)
            n_ent += 1
    if n_ent:
        resumo["TJRS"] = (n_ent, n_prec)
    if pular_tjrs:
        print(f"  [TJRS] {len(pular_tjrs)} entes pulados por colisao de fila_hash "
              f"sem cabeca unica (ver comentario em carrega())")

    # TJAC: painel Qlik Sense (scripts/fetch_tjac.py). Sem codigo de ente no arquivo (so'
    # nome) -- mesmo padrao do TJMG/TJCE/TJPA: cd_externo = nome normalizado.
    n_prec = n_ent = 0
    for f in sorted(glob.glob(os.path.join(BASE, "data", "tjac", "*.json"))):
        if os.path.basename(f).startswith("_"):
            continue
        try:
            d = json.load(open(f, encoding="utf-8"))
        except Exception:
            continue
        if not isinstance(d, dict) or "precatorios" not in d:
            continue
        nome_ente = d.get("nome_entidade_devedora") or "?"
        eid = novo_ente(cx, cache, "TJAC", loose(nome_ente)[:60], nome_ente, "AC", ix)
        regs = list(ad_tjac(d))
        if regs:
            n_prec += grava(cx, "TJAC", f, mtime_iso(f), eid, regs)
            n_ent += 1
    if n_ent:
        resumo["TJAC"] = (n_ent, n_prec)

    return resumo


HIST_TJMG_CSV = MAPA.HIST_TJMG_CSV     # um so' lugar: db_mapa confere antes do DROP


def carrega_historico_tjmg(cx, ix):
    """Preenche mapa_cnj com os anos que o Qlik do CNJ nao retem (so guarda o
    vigente -- memoria [[cnj-mapa-anual-qlik]]). Fonte: data/mapa_anual_tjmg_historico.csv
    (scripts/fetch_mapa_tjmg_historico.py --todos), os PDFs "Mapa Anual de
    Precatorios por Ente Devedor" que o proprio TJMG publica ano a ano (GEPREC,
    Resolucao CNJ 303/2019 art.85). NAO cobre 2025: aquele ano ja vem do Qlik
    (mesma fonte primaria, com envio_id/cnpj que o PDF nao traz) -- inserir os
    dois duplicaria o ano vigente. So entram entidades que casam com um
    municipio de MG (resolve_ibge): as poucas linhas de outros entes federados
    que aparecem no PDF (Distrito Federal, Estado de Alagoas etc. -- causas
    julgadas em MG contra devedor de outra esfera) ficam de fora, fora do
    escopo de mapa_ente/parecer, que so leem por ibge."""
    if not os.path.exists(HIST_TJMG_CSV):
        raise FileNotFoundError(f"{HIST_TJMG_CSV} nao encontrado — rode "
                                f"scripts/fetch_mapa_tjmg_historico.py --todos")
    linhas, anos, pulados = [], set(), 0
    for i, r in enumerate(csv.DictReader(open(HIST_TJMG_CSV, encoding="utf-8"))):
        ano_ref = int(r["ano_ref"])
        if ano_ref == 2025:
            continue
        ibge, tipo = resolve_ibge(r["ente_federado"], "MG", ix)
        if not ibge:
            pulados += 1
            continue
        anos.add(ano_ref)
        linhas.append((
            -(ano_ref * 100000 + i),           # prec_id sintetico, negativo (nunca colide com o CNJ)
            None, ano_ref, "TJMG", "Estadual", "MG", "Municipal",
            "Indireta" if r["tipo_entidade"] == "I" else "Direta",
            ibge, r["nome_devedora"], None,
            "Comum" if r["regime"] == "Geral" else "Especial",
            money(r["expedidos_ate_ano_anterior"]), money(r["pago_no_ano"]),
            money(r["saldo_apos_pagamento"]), money(r["expedidos_no_ano"]),
        ))
    cx.executemany(
        "INSERT OR REPLACE INTO mapa_cnj (prec_id,envio_id,ano_ref,tribunal,ramo,uf,esfera,"
        "tipo_entidade,ibge,ente_nome,cnpj,regime,vlr_ano_anterior,vlr_pago,vlr_saldo,"
        "vlr_expedidos) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", linhas)
    return len(linhas), sorted(anos), pulados


def resumo(cx):
    print("\n=== conteudo do banco ===")
    for trib, ne, np_, vl in cx.execute(
            "SELECT tribunal, COUNT(DISTINCT ente_id), COUNT(*), COALESCE(SUM(valor),0) "
            "FROM precatorio GROUP BY tribunal ORDER BY COUNT(*) DESC"):
        print(f"  {trib:6s} {ne:>5} entes | {np_:>7,} precatorios | R$ {vl:>18,.2f}")
    tot = cx.execute("SELECT COUNT(*), COALESCE(SUM(valor),0) FROM precatorio").fetchone()
    print(f"  {'TOTAL':6s} {'':>5}       | {tot[0]:>7,} precatorios | R$ {tot[1]:>18,.2f}")
    n_ent, n_ok = cx.execute("SELECT COUNT(*), COUNT(ibge) FROM ente").fetchone()
    print(f"\n  entes casados com IBGE: {n_ok}/{n_ent} ({100*n_ok/max(n_ent,1):.1f}%)")
    print("  municipios: {} | com RCL: {}".format(
        *cx.execute("SELECT COUNT(*), COUNT(rcl) FROM municipio").fetchone()))
    print("  com credor: {:,} | com CPF: {:,} | com processo de origem: {:,}".format(
        *cx.execute("SELECT COUNT(credor), COUNT(cpf_cnpj), COUNT(numero_origem) "
                    "FROM precatorio").fetchone()))


# ------------------------------------------------------------------ origem do CPF
# Etapa 3 da LGPD (auditoria A6, 01/10/2026). Grava, para cada documento em cpf_cnpj,
# DE ONDE ele veio (cpf_fonte), COMO foi ligado ao precatorio (cpf_metodo), QUANDO a
# fonte foi obtida (cpf_data) e QUANTO dá para confiar (cpf_confianca). Aditivo:
# nao altera cpf_cnpj nem credor. Regras aprovadas em 01/10 (docs/auditoria/04-lgpd-fase0.md):
#   nao_verificado: DV invalido; documento com mais de um nome no banco; nome publicado
#       por extenso diferente do nome do Callix; nome comparado so' pelas iniciais com outro
#       credor de mesmas iniciais no processo de origem; fallback em origem com mais de um
#       credor ou com candidatos ambiguos no Callix; origem do Callix nao reproduzida.
#   verificado: lista do proprio tribunal; CNJ do precatorio com nome por extenso identico
#       ao do Callix; planilha do RPA_RJ confirmada pela API SAPRE (mesmo documento e nome).
#       = origem oficial e consistente, NAO confirmacao independente.
#   provavel: o resto (CNJ com nome so' em iniciais; fallback sem risco; RPA_RJ sem confirmacao).
#       iniciais_fallback NUNCA chega a verificado: a chave e' o processo, nao o precatorio.
CPF_COLS = (("cpf_fonte", "TEXT"), ("cpf_metodo", "TEXT"), ("cpf_data", "TEXT"),
            ("cpf_confianca", "TEXT CHECK (cpf_confianca IN ('verificado', 'provavel', 'nao_verificado'))"))

CPF_REVISAO_DDL = """
DROP TABLE IF EXISTS cpf_revisao;
-- Documentos com cpf_confianca = 'nao_verificado' + CPF achado DENTRO do nome do credor,
-- para conferencia manual (inclusive na fonte SAPRE). Documento sempre MASCARADO
-- (XXX.***.***-XX, mesma mascara da API); sem nome. Recriada a cada build.
CREATE TABLE cpf_revisao (
  precatorio_id  INTEGER NOT NULL REFERENCES precatorio(id),
  campo          TEXT NOT NULL,       -- cpf_cnpj | credor (CPF embutido no nome)
  tribunal       TEXT,
  ente_id        INTEGER,
  numero_fmt     TEXT,
  numero_eproc   TEXT,
  tipo_doc       TEXT,                -- CPF | CNPJ
  doc_mascarado  TEXT,
  cpf_fonte      TEXT,
  cpf_metodo     TEXT,
  motivos        TEXT,                -- separados por ';'
  PRIMARY KEY (precatorio_id, campo)
);
"""

_DOC_RE = re.compile(r"(?<![\d.])(\d{3}\.?\d{3}\.?\d{3}-?\d{2})(?![\d.])")


def _so_dig(s):
    return re.sub(r"\D", "", str(s or ""))


def _dv_cpf(d):
    if len(d) != 11 or d == d[0] * 11:
        return False
    v1 = (sum(int(d[i]) * (10 - i) for i in range(9)) * 10 % 11) % 10
    v2 = (sum(int(d[i]) * (11 - i) for i in range(10)) * 10 % 11) % 10
    return v1 == int(d[9]) and v2 == int(d[10])


def _dv_cnpj(d):
    if len(d) != 14 or d == d[0] * 14:
        return False
    def dv(ns, ws):
        r = sum(int(a) * b for a, b in zip(ns, ws)) % 11
        return 0 if r < 2 else 11 - r
    w1 = [5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2]
    return dv(d[:12], w1) == int(d[12]) and dv(d[:13], [6] + w1) == int(d[13])


def _mascara_doc(d):
    """Mesma mascara de alfred_core.mascara_cpf (padrao do sistema)."""
    if len(d) == 11:
        return f"{d[:3]}.***.***-{d[9:]}"
    return (d[:2] + "." + "*" * 6 + "/" + d[-6:]) if len(d) == 14 else "***"


def _nome_cmp(s):
    """Nome para comparar pessoas: sem sufixo '(...)'/'/ ...', sem acento, maiusculo."""
    return re.sub(r"\s+", " ", CRED._norm(CRED._nome_limpo(s))).strip()


def garante_colunas_cpf(cx):
    """Migracao ADITIVA para bancos ja prontos: cria as colunas cpf_* que faltarem.
    A view usa p.*, mas o SQLite congela a lista de colunas da view na criacao (ver
    migra_numero_eproc.py): sem recriar, as colunas novas nao aparecem nela."""
    tem = {r[1] for r in cx.execute("PRAGMA table_info(precatorio)")}
    faltam = [(c, t) for c, t in CPF_COLS if c not in tem]
    for c, t in faltam:
        cx.execute(f"ALTER TABLE precatorio ADD COLUMN {c} {t}")
    if faltam:
        sql = cx.execute("SELECT sql FROM sqlite_master WHERE name='precatorio_atual'").fetchone()
        if sql:
            cx.execute("DROP VIEW precatorio_atual")
            cx.execute(sql[0])
    return [c for c, _ in faltam]


def _data_mtime(caminhos):
    ts = [os.path.getmtime(p) for p in caminhos if os.path.exists(p)]
    return datetime.fromtimestamp(max(ts)).date().isoformat() if ts else None


def classifica_cpf(cx, log=print):
    """Preenche cpf_fonte/cpf_metodo/cpf_data/cpf_confianca e recria cpf_revisao.
    Le cpf_cnpj e credor; NUNCA os altera. Retorna {nivel: n}."""
    from difflib import SequenceMatcher
    garante_colunas_cpf(cx)
    rows = cx.execute("""SELECT p.id, p.tribunal, c.arquivo, c.coletado_em, p.cpf_cnpj, p.credor,
                                p.credor_fonte, p.numero_eproc, p.numero_origem, p.cpf_metodo
                         FROM precatorio p JOIN coleta c ON c.id = p.coleta_id
                         WHERE coalesce(p.cpf_cnpj, '') <> ''""").fetchall()

    # documento -> nomes (banco todo): documento com mais de um nome = nao_verificado
    nomes_doc = defaultdict(set)
    for _, _, _, _, doc, cred, *_ in rows:
        nomes_doc[_so_dig(doc)].add(_nome_cmp(cred))

    def sim_min(nomes):
        ns = sorted(nomes)
        return min(SequenceMatcher(None, a, b).ratio() for i, a in enumerate(ns) for b in ns[i + 1:])
    multi = {d: sim_min(v) for d, v in nomes_doc.items() if len(v) > 1}

    # TJMG / Callix: a mesma lista e a mesma logica de casamento de enriquece_credor
    tem_tjmg = any(r[1] == "TJMG" for r in rows)
    por_eproc, por_orig = CRED._carrega_nomes() if tem_tjmg else ({}, {})
    data_callix = _data_mtime(glob.glob(os.path.join(CRED.DIR, "*.xlsx")))
    amb_orig = set()
    for og, lst in por_orig.items():
        por_ini = defaultdict(set)
        for n, c in lst:
            por_ini[CRED._iniciais(n)].add(c)
        if any(len(s) > 1 for s in por_ini.values()):
            amb_orig.add(og)
    orig_nomes = defaultdict(set)
    orig_ini = defaultdict(lambda: defaultdict(int))
    if tem_tjmg:
        for og, cred in cx.execute("SELECT numero_origem, credor FROM precatorio "
                                   "WHERE tribunal = 'TJMG' AND coalesce(numero_origem, '') <> ''"):
            orig_nomes[_so_dig(og)].add(_nome_cmp(cred))
            orig_ini[_so_dig(og)][CRED._alvo_iniciais(cred)] += 1

    # TJAL: (documento, nome) vistos na API SAPRE direta -> confirma a planilha do RPA_RJ
    api_tjal = {(_so_dig(d), _nome_cmp(c)) for _, t, a, _, d, c, *_ in rows
                if t == "TJAL" and not a.startswith("28_")}
    data_rpa = None
    j = os.path.join(BASE, "data", "tjal", "28_estado_de_alagoas.json")
    if os.path.exists(j):
        m = re.search(r"gerado (\d{4}-\d{2}-\d{2})", json.load(open(j, encoding="utf-8")).get("fonte", ""))
        data_rpa = m.group(1) if m else None

    upd, revisao, cont = [], [], defaultdict(int)
    for pid, trib, arq, coletado, doc, cred, cfonte, eproc, origem, met_gravado in rows:
        d = _so_dig(doc)
        pj = len(d) == 14
        mot = []
        if not (_dv_cnpj(d) if pj else _dv_cpf(d)):
            mot.append("dv_invalido")
        if d in multi:
            mot.append("documento_com_mais_de_um_nome")
            if multi[d] < 0.6:
                mot.append("nomes_de_pessoas_diferentes")
        nivel = None
        if trib == "TJMG":
            fonte, data = "callix_planilhas_mg", data_callix
            alvo = CRED._alvo_iniciais(cred)
            ep = _so_dig(eproc)
            cand, met = None, None
            if ep and ep in por_eproc:                      # chave 1 do enriquece
                cand, met = por_eproc[ep], "cnj_precatorio"
            if cand is None:                                # fallback do enriquece
                for c in por_orig.get(_so_dig(origem), []):
                    if CRED._iniciais(c[0]) == alvo:
                        cand, met = c, "iniciais_fallback"
                        break
            reproduz = (cand is not None and CRED._iniciais(cand[0]) == alvo and cand[1] == d
                        and (met_gravado is None or met_gravado == met))
            if not reproduz:
                mot.append("origem_nao_reproduzida")
                met = met_gravado or met
            mascarado = cfonte == "Callix"                  # a lista do TJMG so' tinha iniciais
            nome_igual = (not mascarado) and cand is not None and _nome_cmp(cred) == _nome_cmp(cand[0])
            if cand is not None and not mascarado and not nome_igual:
                mot.append("nome_publicado_diverge_do_callix")
            homonimo = orig_ini[_so_dig(origem)][alvo] > 1 if origem else False
            if met == "iniciais_fallback":
                if _so_dig(origem) in amb_orig:
                    mot.append("origem_ambigua_no_callix")
                if origem and len(orig_nomes[_so_dig(origem)]) > 1:
                    mot.append("origem_com_mais_de_um_credor")
                if homonimo:
                    mot.append("homonimo_de_iniciais_na_origem")
            elif not nome_igual and homonimo:
                mot.append("homonimo_de_iniciais_na_origem")
            if not mot:
                nivel = "verificado" if met == "cnj_precatorio" and nome_igual else "provavel"
        elif trib == "TJAL" and arq.startswith("28_"):
            fonte, met, data = "rpa_rj_planilha_estado_al", "planilha_rpa_rj", data_rpa or (coletado or "")[:10]
            if not mot:
                nivel = "verificado" if (d, _nome_cmp(cred)) in api_tjal else "provavel"
        elif trib in ("TJAL", "TJAC"):
            fonte = "tjal_api_sapre" if trib == "TJAL" else "tjac_painel_qlik"
            met, data = "lista_tribunal", (coletado or "")[:10]
            if not mot:
                nivel = "verificado"
        else:                                               # origem nova: ninguem mapeou ainda
            fonte, met, data = f"{trib.lower()}_nao_mapeada", None, (coletado or "")[:10]
            mot.append("origem_nao_mapeada")
        nivel = nivel or "nao_verificado"
        cont[nivel] += 1
        upd.append((fonte, met, data, nivel, pid))
        if nivel == "nao_verificado":
            revisao.append((pid, "cpf_cnpj", trib, d, fonte, met, ";".join(mot)))

    cx.executemany("UPDATE precatorio SET cpf_fonte=?, cpf_metodo=?, cpf_data=?, cpf_confianca=? "
                   "WHERE id=?", upd)

    # CPF dentro do NOME do credor (nao esta' em cpf_cnpj): so' registra para revisao
    for pid, trib, cred in cx.execute("SELECT id, tribunal, credor FROM precatorio "
                                      "WHERE credor GLOB '*[0-9][0-9][0-9]*'").fetchall():
        achados = [_so_dig(m.group(1)) for m in _DOC_RE.finditer(cred or "")]
        achados = [x for x in achados if _dv_cpf(x)]
        if achados:
            revisao.append((pid, "credor", trib, achados[0], "nome_do_credor", None,
                            "cpf_no_nome_do_credor" + (f";{len(achados)}_documentos" if len(achados) > 1 else "")))
            cont["cpf_no_nome_do_credor"] += 1

    cx.executescript(CPF_REVISAO_DDL)
    info = {r[0]: r[1:] for r in cx.execute(
        "SELECT id, ente_id, numero_fmt, numero_eproc FROM precatorio WHERE id IN (%s)"
        % ",".join(str(r[0]) for r in revisao))} if revisao else {}
    cx.executemany(
        "INSERT INTO cpf_revisao (precatorio_id, campo, tribunal, ente_id, numero_fmt, numero_eproc, "
        "tipo_doc, doc_mascarado, cpf_fonte, cpf_metodo, motivos) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
        [(pid, campo, trib, *info[pid], "CNPJ" if len(d) == 14 else "CPF", _mascara_doc(d), f, m, mot)
         for pid, campo, trib, d, f, m, mot in revisao])
    log(f"  origem do CPF: {cont['verificado']:,} verificado | {cont['provavel']:,} provavel | "
        f"{cont['nao_verificado']:,} nao_verificado | cpf_revisao: {len(revisao):,} "
        f"(inclui {cont['cpf_no_nome_do_credor']} com CPF no nome do credor)")
    return dict(cont)


# ------------------------------------------------------------------ verificacao (A8)
# --verifica: LE as mesmas entradas que o carrega() le (mesmos globs, mesmos filtros de
# '_') e lista o que parece falha de coleta -- sem criar banco e sem rejeitar nada. E' o
# passo antes de o build passar a recusar entradas (docs/auditoria/05-coletores-fase1.md, C0).
# Nao imprime nem grava campo de credor: so' tribunal, arquivo, nome do ENTE e contagens.

# campo com o total DECLARADO PELA FONTE (independente do que o coletor leu). TJPI fica de
# fora: `qtd_declarada` vem da listagem, que o proprio coletor diz ser defasada.
TOTAL_DECLARADO = {"TJBA": "total_api", "TJRR": "total_api", "TJTO": "total_api",
                   "TJSE": "row_count_api", "TJSP": "blocos_no_pdf", "TJES": "total"}
# coletores sem paginacao com teto fixo: lista exatamente do tamanho do teto = corte provavel
TETO_LISTA = {"TJSC": 50000, "TJES": 10000, "TJAP": 50000}
QUEDA_ENTE = 0.20      # ente que encolhe mais que isso em relacao ao banco atual vira suspeita


def _evidencia_vazio(trib, d):
    """(evidencia, forte) de que uma lista VAZIA e' vazio de verdade, lida so' do arquivo."""
    c = d.get("_coleta") or {}
    if c.get("status") == "vazio_confirmado":
        return f"marcador _coleta: {c.get('evidencia')}", True
    if trib in ("TJBA", "TJRR", "TJTO") and d.get("total_api") == 0:
        return "total_api=0", True
    if trib == "TJPI" and d.get("qtd_declarada") == 0:
        return "qtd_declarada=0 (o coletor confirma o HTTP 500 na pagina padrao)", True
    if trib == "TJES" and d.get("total") == 0:
        return "total da API=0", True
    if trib == "TJSE" and d.get("row_count_api") == 0 and d.get("publicacao"):
        return "rowCount=0 com data de publicacao", True
    if trib == "TJRS" and d.get("fila_hash"):
        return "CSV so' com cabecalho", True
    if trib == "TJAL" and d.get("total") == 0:
        return "total=0 (fraca: o coletor grava `total or 0`)", False
    return None, False


def verifica(relatorio=None, log=print):
    """Lista entradas suspeitas. Nunca altera nada; devolve a lista de dicts."""
    linhas = []

    def nota(trib, arquivo, ente, regra, nivel, detalhe="", **n):
        linhas.append({"tribunal": trib, "arquivo": arquivo, "ente": ente, "regra": regra,
                       "nivel": nivel, "detalhe": detalhe, **n})

    banco = {}
    if os.path.exists(DB):
        c = sqlite3.connect(f"file:{pathlib.Path(DB).as_posix()}?mode=ro&immutable=1", uri=True)
        try:
            banco = {(t, a): n for t, a, n in
                     c.execute("SELECT tribunal, arquivo, n_registros FROM coleta_atual")}
        finally:
            c.close()
    vistos = set()
    origem_data = defaultdict(lambda: defaultdict(int))

    def compara_banco(trib, arquivo, ente, n_carga):
        vistos.add((trib, arquivo))
        n_b = banco.get((trib, arquivo), 0)
        if n_b and not n_carga:
            nota(trib, arquivo, ente, "perderia_fila", "suspeita",
                 f"{n_b} no banco atual -> 0", n_carga=0, n_banco=n_b)
        elif n_b and n_carga < (1 - QUEDA_ENTE) * n_b:
            nota(trib, arquivo, ente, "queda_vs_banco", "suspeita",
                 f"{n_b} -> {n_carga}", n_carga=n_carga, n_banco=n_b)

    def le(f):
        try:
            return json.load(open(f, encoding="utf-8")), None
        except Exception as e:                                       # noqa: BLE001
            return None, type(e).__name__

    def arquivo_lista(trib, f, d, chaves, nome, adap, pular=False):
        """Regras comuns a um arquivo por ente. `chaves` = onde esta' a lista."""
        bn = os.path.basename(f)
        n = sum(len(d.get(k) or []) for k in chaves if isinstance(d.get(k), list))
        try:
            n_carga = 0 if pular else len(list(adap(d)))
        except Exception as e:                                       # noqa: BLE001
            nota(trib, bn, nome, "adaptador_falhou", "suspeita", type(e).__name__)
            n_carga = 0
        origem_data[trib]["campo coletado_em" if d.get("coletado_em") else "mtime do arquivo"] += 1
        decl_k = TOTAL_DECLARADO.get(trib)
        decl = d.get(decl_k) if decl_k else None
        if n == 0:
            if trib == "TJRS" and "fila_hash" in d and d["fila_hash"] is None:
                nota(trib, bn, nome, "resposta_0_bytes", "suspeita",
                     "o servidor devolveu corpo vazio; nao e' lista vazia", n_lista=0)
            elif trib == "TJSE" and not d.get("publicacao"):
                nota(trib, bn, nome, "vazio_sem_publicacao", "suspeita",
                     "a pagina nao tem data de publicacao da lista", n_lista=0)
            else:
                ev, forte = _evidencia_vazio(trib, d)
                if forte:
                    nota(trib, bn, nome, "vazio_confirmado", "info", ev, n_lista=0)
                elif ev:
                    nota(trib, bn, nome, "vazio_evidencia_fraca", "suspeita", ev, n_lista=0)
                else:
                    nota(trib, bn, nome, "vazio_sem_evidencia", "suspeita",
                         "nada no arquivo distingue vazio de falha", n_lista=0)
        if isinstance(decl, (int, float)) and decl != n:
            nota(trib, bn, nome, "declarado_diferente_do_lido", "suspeita",
                 f"{decl_k}={decl} lido={n}", n_lista=n, n_declarado=decl)
        if d.get("paginas_faltando"):
            nota(trib, bn, nome, "paginas_faltando", "suspeita",
                 f"{len(d['paginas_faltando'])} pagina(s)", n_lista=n)
        if TETO_LISTA.get(trib) and n == TETO_LISTA[trib]:
            nota(trib, bn, nome, "lista_no_teto", "suspeita", f"{n} = teto do coletor", n_lista=n)
        compara_banco(trib, bn, nome, n_carga)

    for trib, padrao, _uf, adap, _kcd, knome in FONTES:
        if trib == "TJRS":
            continue
        for f in sorted(glob.glob(_padrao_fonte(trib, padrao))):
            if os.path.basename(f).startswith("_"):
                continue
            d, erro = le(f)
            if erro:
                nota(trib, os.path.basename(f), "?", "nao_faz_parse", "suspeita", erro)
                continue
            if not isinstance(d, dict):
                nota(trib, os.path.basename(f), "?", "nao_e_objeto", "info",
                     "o build ignora (ex.: consulta pontual)")
                continue
            if "precatorios" not in d:
                nota(trib, os.path.basename(f), d.get(knome) or "?", "sem_chave_lista", "suspeita",
                     "sem 'precatorios'; chaves: " + ",".join(sorted(d)[:8]))
                continue
            arquivo_lista(trib, f, d, ("precatorios",), d.get(knome) or "?", adap)

    for trib, pasta, _uf, adap, chaves in (
            ("TJCE", "tjce", "CE", ad_tjce, ("itens",)),
            ("TJPA", "tjpa", "PA", ad_tjpa, ("cronologica", "superpreferencia")),
            ("TJGO", "tjgo", "GO", ad_tjgo, ("itens",)),
            ("TJAM", "tjam", "AM", ad_tjam, ("itens",))):
        for f in sorted(glob.glob(os.path.join(BASE, "data", pasta, "*.json"))):
            if os.path.basename(f).startswith("_"):
                continue
            d, erro = le(f)
            if erro:
                nota(trib, os.path.basename(f), "?", "nao_faz_parse", "suspeita", erro)
                continue
            if not isinstance(d, dict) or not any(k in d for k in chaves):
                nota(trib, os.path.basename(f), "?", "sem_chave_lista", "suspeita")
                continue
            arquivo_lista(trib, f, d, chaves, d.get("ente") or "?", adap)

    # TJRS: mesma regra de colisao do carrega() (_tjrs_pular)
    dtjrs = {}
    for f in sorted(glob.glob(os.path.join(BASE, "data", "tjrs", "*.json"))):
        d, erro = le(f)
        if erro:
            nota("TJRS", os.path.basename(f), "?", "nao_faz_parse", "suspeita", erro)
            continue
        if isinstance(d, dict) and "precatorios" in d and d.get("id_entidade") is not None:
            dtjrs[d["id_entidade"]] = (d, f)
    pular, grupos = _tjrs_pular(dtjrs)
    for eid, (d, f) in sorted(dtjrs.items()):
        arquivo_lista("TJRS", f, d, ("precatorios",), d.get("nome") or "?", ad_tjrs, pular=eid in pular)
    zeros = {eid: loose(d.get("nome")) for eid, (d, _f) in dtjrs.items()
             if not d.get("total") and "fila_hash" in d and d["fila_hash"] is None}
    for ids in grupos.values():
        if len(ids) < 2 or len([i for i in ids if _e_cabeca_tjrs(dtjrs[i][0].get("nome"))]) == 1:
            continue
        d0 = dtjrs[ids[0]][0]
        nota("TJRS", f"grupo:{d0.get('fila_hash', '')[:10]}", d0.get("nome") or "?",
             "colisao_sem_cabeca", "info",
             f"{len(ids)} entes com a mesma fila ({d0.get('total')} precatorios) descartados")
        nomes = " | ".join(loose(dtjrs[i][0].get("nome")) for i in ids)
        for eid, nz in zeros.items():
            m = re.match(r"MUNICIPIO (?:DE|DO|DA) (.+)$", nz)
            if m and re.search(r"\b" + re.escape(m.group(1)) + r"\b", nomes):
                nota("TJRS", os.path.basename(dtjrs[eid][1]), dtjrs[eid][0].get("nome"),
                     "cabeca_provavel_0_bytes", "suspeita",
                     f"o nome aparece num grupo de colisao descartado ({len(ids)} entes, "
                     f"{d0.get('total')} precatorios): a fila do municipio pode estar la'")

    for f in sorted(glob.glob(os.path.join(BASE, "data", "tjac", "*.json"))):
        if os.path.basename(f).startswith("_"):
            continue
        d, erro = le(f)
        if erro or not isinstance(d, dict) or "precatorios" not in d:
            nota("TJAC", os.path.basename(f), "?", "nao_faz_parse" if erro else "sem_chave_lista",
                 "suspeita", erro or "")
            continue
        arquivo_lista("TJAC", f, d, ("precatorios",), d.get("nome_entidade_devedora") or "?", ad_tjac)

    for tdir in sorted(glob.glob(os.path.join(BASE, "data", "trt[0-9]*"))):
        m = re.search(r"trt(\d+)$", os.path.basename(tdir))
        if not os.path.isdir(tdir) or not m:
            continue
        trib = "TRT" + m.group(1)
        for f in sorted(glob.glob(os.path.join(tdir, "*.json"))):
            bn = os.path.basename(f)
            if bn.startswith("_"):
                continue
            d, erro = le(f)
            if erro or not isinstance(d, dict):
                nota(trib, bn, "?", "nao_faz_parse" if erro else "nao_e_objeto", "suspeita", erro or "")
                continue
            nome = d.get("nomeDevedor") or d.get("nome") or "?"
            origem_data[trib]["mtime do arquivo"] += 1
            if "listaCronologica" not in d:
                nota(trib, bn, nome, "sem_chave_lista", "suspeita",
                     "resposta sem listaCronologica: o coletor marcou como feita, o build descarta")
                compara_banco(trib, bn, nome, 0)
                continue
            n = len(d.get("listaCronologica") or [])
            tp = d.get("totalPrecatorio")
            if isinstance(tp, (int, float)) and tp != n:
                nota(trib, bn, nome, "declarado_diferente_do_lido", "suspeita",
                     f"totalPrecatorio={tp} lido={n}", n_lista=n, n_declarado=tp)
            if n == 0:
                nota(trib, bn, nome, "vazio_sem_evidencia", "suspeita", "", n_lista=0)
            compara_banco(trib, bn, nome, len(list(ad_trt17(d))))

    # fontes de arquivo unico (stages): uma "coleta" por ente com arquivo sintetico
    for trib, rel, adap, sigla in (("TJMG", "tjmg/precatorios.json", ad_tjmg, "tjmg"),
                                   ("TJMA", "tjma/precatorios.json", ad_tjma, "tjma")):
        f = os.path.join(BASE, "data", *rel.split("/"))
        if not os.path.exists(f):
            nota(trib, rel, "-", "entrada_ausente", "suspeita", "o build pula o tribunal inteiro")
            continue
        d, erro = le(f)
        if erro:
            nota(trib, rel, "-", "nao_faz_parse", "suspeita", erro)
            continue
        origem_data[trib][f"fixo do stage ({d.get('coletado_em')})" if d.get("coletado_em")
                          else "mtime do arquivo"] += 1
        if not d.get("entes"):
            nota(trib, rel, "-", "sem_entes", "suspeita", "o stage gravou 'entes' vazio")
        for e in d.get("entes", []):
            slug = loose(e.get("ente") or "?")[:60]
            regs = list(adap(e.get("precatorios", [])))
            if not regs:
                nota(trib, f"{sigla}_{slug}.json", e.get("ente") or "?", "vazio_sem_evidencia",
                     "suspeita", "ente sem linhas no stage", n_lista=0)
            compara_banco(trib, f"{sigla}_{slug}.json", e.get("ente") or "?", len(regs))
    for arq, adap in (("trf2_es.json", ad_trf2), ("trf2_rj.json", ad_trf2_rj)):
        ftrf2 = os.path.join(BASE, "data", arq)
        if not os.path.exists(ftrf2):
            continue
        d, erro = le(ftrf2)
        if erro:
            nota("TRF2", arq, "-", "nao_faz_parse", "suspeita", erro)
        else:
            origem_data["TRF2"]["mtime do arquivo"] += 1
            for ib, e in d.items():
                if not str(ib).isdigit():
                    continue
                compara_banco("TRF2", f"trf2_{ib}.json", e.get("municipio") or e.get("devedor") or "?",
                              len(list(adap(e.get("fila", [])))))

    for (t, a), n_b in sorted(banco.items()):
        if (t, a) not in vistos and n_b:
            nota(t, a, "?", "arquivo_sumiu", "suspeita",
                 f"tinha {n_b} no banco atual; o arquivo nao existe mais", n_banco=n_b)

    # entradas auxiliares: a ausencia faz o build pular a tabela inteira em silencio
    p = os.path.join(BASE, "data", "rcl_uf_siconfi.csv")
    if not os.path.exists(p):
        nota("-", "rcl_uf_siconfi.csv", "-", "entrada_ausente", "suspeita",
             "os Estados perdem RCL, regime e projecao")
    else:
        ufs = {r.get("codigo_ibge") for r in csv.DictReader(open(p, encoding="utf-8-sig"))
               if r.get("rcl")}
        for uf, cod in sorted(UF_ESTADO.items()):
            if cod not in ufs:
                nota("-", "rcl_uf_siconfi.csv", f"Estado {uf}", "uf_sem_rcl", "suspeita",
                     f"codigo {cod} sem linha com RCL: o Estado fica sem RCL/regime no banco")
    for rel, efeito in (("cnj_mapa_anual_raw.csv", "o build publica sem mapa_cnj"),
                        ("mapa_anual_tjmg_historico.csv", "o build publica sem mapa_cnj (M5)"),
                        ("enquadramento_definitivo.csv", "MG cai para a RCL do SICONFI"),
                        ("regimes_brasil_municipios.csv", "o build nao roda")):
        if not os.path.exists(os.path.join(BASE, "data", rel)):
            nota("-", rel, "-", "entrada_ausente", "suspeita", efeito)
    for padrao, efeito in (("djen_nacp_*.json", "o build publica sem nacp_*"),
                           ("callix_mg/*.xlsx", "sem enriquecimento do credor do TJMG"),
                           ("djen_nomes/*.jsonl", "sem enriquecimento DJEN")):
        if not glob.glob(os.path.join(BASE, "data", padrao)):
            nota("-", padrao, "-", "entrada_ausente", "suspeita", efeito)

    # ---- saida
    por_regra = defaultdict(lambda: defaultdict(int))
    for r in linhas:
        por_regra[(r["nivel"], r["regra"])][r["tribunal"]] += 1
    log(f"\n== --verifica: {len(linhas)} apontamentos "
        f"({sum(1 for r in linhas if r['nivel'] == 'suspeita')} suspeitas). Nada foi alterado.")
    for (nivel, regra), por_t in sorted(por_regra.items()):
        tot = sum(por_t.values())
        detal = ", ".join(f"{t} {n}" for t, n in sorted(por_t.items(), key=lambda x: -x[1]))
        log(f"  [{nivel:8}] {regra:28} {tot:5}  ({detal})")
    criticas = [r for r in linhas if r["regra"] in
                ("perderia_fila", "queda_vs_banco", "arquivo_sumiu", "cabeca_provavel_0_bytes",
                 "uf_sem_rcl", "entrada_ausente", "nao_faz_parse", "adaptador_falhou",
                 "paginas_faltando", "lista_no_teto")]
    if criticas:
        log("\n  detalhe das regras criticas:")
        for r in criticas[:60]:
            log(f"    {r['tribunal']:6} {r['regra']:24} {str(r['ente'])[:50]:50} {r['detalhe']}")
        if len(criticas) > 60:
            log(f"    ... e mais {len(criticas) - 60} (ver --relatorio)")
    log("\n  origem da data de coleta (M10):")
    for t in sorted(origem_data):
        log(f"    {t:6} " + "; ".join(f"{o}: {n}" for o, n in origem_data[t].items()))
    if relatorio:
        cols = ["tribunal", "arquivo", "ente", "regra", "nivel", "detalhe",
                "n_lista", "n_carga", "n_declarado", "n_banco"]
        with open(relatorio, "w", encoding="utf-8", newline="") as fo:
            w = csv.DictWriter(fo, fieldnames=cols, extrasaction="ignore")
            w.writeheader()
            w.writerows(linhas)
        log(f"\n  lista completa: {relatorio}")
    return linhas


# ------------------------------------------------------------------ publicacao
# Escrita atomica (auditoria A2). O build inteiro acontece em alfred.db.tmp; o
# alfred.db so' e' substituido no fim, por os.replace, depois de o banco novo passar
# nas checagens. Se o build morrer no meio (erro, Ctrl+C, kill), ou se as checagens
# reprovarem, o alfred.db continua exatamente o que era e o .tmp fica para inspecao.
# (Antes: os.remove(DB) no inicio -- durante o build o banco ficava vazio/parcial e,
# se quebrasse, nao sobrava copia boa.)
DB_TMP = DB + ".tmp"
QUEDA_MAX = 0.20       # tribunal que encolhe mais que isso barra a publicacao (sem --forca)


def _apaga_com_satelites(p):
    """O arquivo e os satelites do SQLite: -wal/-shm de outro banco nao podem sobrar
    ao lado de um banco novo com o mesmo nome (seriam aplicados sobre ele)."""
    for s in ("", "-wal", "-shm", "-journal"):
        if os.path.exists(p + s):
            os.remove(p + s)


def _por_tribunal(caminho, somente_leitura):
    uri = f"file:{pathlib.Path(caminho).as_posix()}?mode=ro" if somente_leitura else None
    c = sqlite3.connect(uri, uri=True) if uri else sqlite3.connect(caminho)
    try:
        return dict(c.execute("SELECT tribunal, COUNT(*) FROM precatorio GROUP BY 1"))
    finally:
        c.close()


def publica(tmp, final, forca=False):
    """Checa o banco novo e so' entao o poe no lugar do final. SystemExit = recusado,
    com o `final` intocado."""
    cx = sqlite3.connect(tmp)
    try:
        cx.execute("PRAGMA wal_checkpoint(TRUNCATE)")          # tudo do WAL no arquivo
        ok = cx.execute("PRAGMA quick_check").fetchone()[0]
        novo = dict(cx.execute("SELECT tribunal, COUNT(*) FROM precatorio GROUP BY 1"))
    finally:
        cx.close()                     # sem fechar, o Windows nao deixa renomear
    if ok != "ok":
        raise SystemExit(f"\n!! quick_check do banco novo: {ok}\n   {final} NAO foi tocado; "
                         f"o novo ficou em {tmp} para inspecao")
    if os.path.exists(final):
        velho = _por_tribunal(final, somente_leitura=True)
        caiu = {t: (v, novo.get(t, 0)) for t, v in velho.items()
                if v and novo.get(t, 0) < (1 - QUEDA_MAX) * v}
        if caiu:
            linhas = "\n".join(f"     {t}: {v:,} -> {n:,} ({100 * (n - v) / v:+.0f}%)"
                               for t, (v, n) in sorted(caiu.items()))
            if not forca:
                raise SystemExit(
                    f"\n!! tribunal(is) que cairam mais de {QUEDA_MAX:.0%} em relacao ao banco atual:\n"
                    f"{linhas}\n   Publicacao RECUSADA: {final} NAO foi tocado; o novo ficou em {tmp}.\n"
                    f"   Fonte que sumiu/veio parcial? Se a queda for de proposito: --forca")
            print(f"  (--forca) publicando apesar da queda:\n{linhas}")
        # WAL do banco velho de volta ao arquivo dele e -wal/-shm fora: o novo nao herda
        c = sqlite3.connect(final)
        try:
            c.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        finally:
            c.close()
        for s in ("-wal", "-shm"):
            if os.path.exists(final + s):
                os.remove(final + s)
    try:
        os.replace(tmp, final)         # atomico no mesmo disco
    except PermissionError as e:
        raise SystemExit(f"\n!! nao deu para substituir {final} ({e}).\n   Algum processo esta' com o "
                         f"banco aberto (API local, notebook, teste)? Feche e mova {tmp} -> {final}.")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--resumo", action="store_true", help="so mostra o que ja esta carregado")
    ap.add_argument("--forca", action="store_true",
                    help=f"publica mesmo se algum tribunal cair mais de {QUEDA_MAX:.0%}")
    ap.add_argument("--so-classifica-cpf", metavar="CAMINHO",
                    help="NAO faz build: aplica so' a migracao aditiva da origem do CPF (colunas "
                         "cpf_*, cpf_revisao) num banco ja' pronto, no caminho dado")
    ap.add_argument("--saida", metavar="CAMINHO",
                    help="constroi o banco NESTE caminho (que nao pode existir) e nao toca "
                         "data/alfred.db nem data/alfred.db.tmp")
    ap.add_argument("--verifica", action="store_true",
                    help="NAO faz build: so' le as entradas e lista as suspeitas (nao rejeita nada)")
    ap.add_argument("--relatorio", metavar="CSV", help="com --verifica: grava a lista completa aqui")
    ap.add_argument("--pasta", metavar="TRIB=DIR", action="append", default=[],
                    help="so' com --saida ou --verifica: le os JSONs crus do tribunal TRIB (um de "
                         "FONTES) de DIR em vez de data/<pasta>")
    a = ap.parse_args()
    for item in a.pasta:
        trib, _, pasta = item.partition("=")
        if not (a.saida or a.verifica):
            raise SystemExit("--pasta so' vale com --saida ou --verifica: um build que publica em "
                             "data/alfred.db nunca le dado de fora de data/")
        if trib not in {t for t, *_ in FONTES} or not os.path.isdir(pasta):
            raise SystemExit(f"--pasta invalida: {item} (tribunal de FONTES = pasta existente)")
        PASTAS[trib] = os.path.abspath(pasta)
        print(f"  (--pasta) {trib} lido de {PASTAS[trib]}")
    if a.verifica:
        verifica(a.relatorio)
        return
    final, tmp = DB, DB_TMP
    if a.saida:
        final = os.path.abspath(a.saida)
        if os.path.normcase(final) in {os.path.normcase(os.path.abspath(p)) for p in (DB, DB_TMP)}:
            raise SystemExit(f"--saida nao pode ser o banco de producao: {final}")
        if os.path.exists(final):
            raise SystemExit(f"--saida ja' existe: {final} (apague ou escolha outro caminho)")
        tmp = final + ".tmp"
    if a.so_classifica_cpf:
        alvo = a.so_classifica_cpf
        if not os.path.exists(alvo):
            raise SystemExit(f"banco nao existe: {alvo}")
        cx = sqlite3.connect(alvo)
        try:
            novas = garante_colunas_cpf(cx)
            print(f"  colunas criadas: {', '.join(novas) or 'nenhuma (ja existiam)'}")
            classifica_cpf(cx)
            cx.commit()
            print(f"  quick_check: {cx.execute('PRAGMA quick_check').fetchone()[0]}")
        finally:
            cx.close()
        return
    if a.resumo:
        cx = sqlite3.connect(DB)
        try:
            resumo(cx)
        finally:
            cx.close()
        return
    _apaga_com_satelites(tmp)          # sobra de um build que morreu antes
    cx = sqlite3.connect(tmp)
    try:
        cx.executescript(SCHEMA)
        muns = carrega_municipios(cx)
        ix = indice_ibge(muns)
        r = carrega(cx, muns, ix)
        # antes de qualquer leitura de precatorio_atual (os enriquecimentos abaixo leem)
        n_atual = materializa_coleta_atual(cx)
        # credor_norm + credor_fts da carga inteira; os enriquecimentos abaixo
        # ressincronizam so' os ids em que trocam o credor
        n_norm = CN.sincroniza(cx)
        cx.commit()
        for trib, (ne, np_) in r.items():
            print(f"  {trib}: {ne} entes, {np_:,} precatorios")
        print(f"  coleta_atual: {n_atual:,} coletas | credor_norm/credor_fts: {n_norm:,} precatorios")
        # Mapa Anual do CNJ: comportamento de pagamento por ente/tribunal/ano. Entra
        # como tabela SEPARADA -- nao corrige fila nem regime, so acrescenta (ver
        # db_mapa.py). Ausencia do CSV nao invalida a build. O historico do TJMG
        # (2021-2024) entra DENTRO de MAPA.carrega (M5): este build so' passa o
        # carregador com o indice de municipios que ja montou.
        try:
            n_mapa, anos = MAPA.carrega(cx, MAPA.CSV_RAW,
                                        historico=lambda c: carrega_historico_tjmg(c, ix))
            cx.commit()
            print(f"  mapa_cnj: {n_mapa:,} linhas (anos-ref: {', '.join(map(str, anos))})")
        except FileNotFoundError as e:
            print(f"  mapa_cnj: PULADO — {e}")
        # NACP: plano anual do §23 (Comite Gestor) + conformidade do ente. Tambem
        # tabela separada -- e' a resposta a "quanto deve pagar ESTE ano", que o
        # Mapa (ano-ref anterior) nao da. Ausencia dos JSONs nao invalida a build.
        try:
            n_plano, n_ato = NACP.carrega(cx)
            cx.commit()
            print(f"  nacp: {n_plano:,} linhas de plano §23, {n_ato:,} atos")
        except Exception as e:  # noqa: BLE001
            print(f"  nacp: PULADO — {e}")
        # Enriquecimento do credor do TJMG (repoe nome completo mascarado por LGPD,
        # a partir da lista do Callix). Roda por ULTIMO: depende da fila ja carregada.
        try:
            n_nome, n_cpf, n_rej = CRED.enriquece(cx)
            cx.commit()
            print(f"  credor Callix: {n_nome:,} nomes repostos + {n_cpf:,} CPFs no TJMG | {n_rej} rejeitados")
        except FileNotFoundError as e:
            print(f"  credor Callix: PULADO — {e}")
        # Enriquecimento gratuito via DJEN (nome do credor onde a fila do tribunal nunca
        # trouxe nenhum) -- scripts/fetch_djen_nomes.py roda por fora (pode levar horas/
        # dias), este passo so' aplica o que ja' esta' no cache ate' agora.
        try:
            n_djen_nome, n_djen_adv = CRED_DJEN.enriquece(cx)
            cx.commit()
            print(f"  credor DJEN: {n_djen_nome:,} nomes preenchidos + {n_djen_adv:,} advogados")
        except FileNotFoundError as e:
            print(f"  credor DJEN: PULADO — {e}")
        # origem e confianca de cada documento (LGPD, A6): depois de TODOS os
        # enriquecimentos, porque depende do nome final e do metodo gravado pelo Callix
        classifica_cpf(cx)
        cx.commit()
        # estatisticas p/ o planejador (sqlite_stat1): sem elas ele escolhe indice as cegas
        cx.execute("ANALYZE")
        cx.commit()
        resumo(cx)
    finally:
        cx.close()
    # com --saida o `final` nao existe (checado acima): publica() so' faz o quick_check e o
    # os.replace, sem a comparacao de queda, que so' faz sentido contra o banco de producao
    publica(tmp, final, a.forca)
    print(f"\nOK -> {final}  ({os.path.getsize(final)/1e6:.1f} MB)")


if __name__ == "__main__":
    main()
