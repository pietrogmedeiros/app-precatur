# -*- coding: utf-8 -*-
"""RASTREIO: o que responder quando o numero NAO esta na fila do Alfred.

Motivacao (28/08/2026). "Nao encontrado" e' a resposta menos util possivel, porque
esconde tres situacoes muito diferentes — e duas delas apareceram na mesma semana:

  #3373 Renata Pena x Municipio do Rio ... nao existe precatorio: a acao ainda esta
        em conhecimento, com sentenca de procedencia em parte e SEM transito.
  #3527 Sandra Pereira x Belem ........... o oficio requisitorio foi expedido e
        remetido, mas o precatorio ainda NAO foi autuado — nao esta em lista nenhuma.
  (terceiro caso) ........................ e' precatorio mesmo, mas de um ente/coleta
        que o Alfred ainda nao tem.

Sem distinguir, o time descarta lead bom e persegue lead que ainda nao existe. O
DataJud (base publica do CNJ, sem chave privada) responde os tres em uma consulta.

    python scripts/rastreia.py 3010180-45.2025.8.19.0001
    python scripts/rastreia.py 0872074-51.2025.8.14.0301

LIMITES DA FONTE (nao sao bugs deste modulo):
  - o DataJud publica METADADOS e movimentacao, NAO as partes (LGPD) nem valores;
  - a cobertura de 2o grau e' irregular: numero de PRECATORIO (final .0000) costuma
    dar zero hit — por isso o rastreio de um precatorio ausente cai no processo de
    ORIGEM, que e' de 1o grau e esta na base;
  - nao ha' STF (sem indice publico).

Usado por api.py quando /busca devolve zero para um numero CNJ de 20 digitos.
"""
from __future__ import annotations

import json
import os
import re
import sys
import urllib.error
import urllib.request

from dotenv import load_dotenv

BASE = os.environ.get("ALFRED_BASE") or os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
load_dotenv(os.path.join(BASE, ".env"))

TIMEOUT = 12
# APIKey PUBLICA do DataJud, divulgada pelo proprio CNJ na documentacao da API.
CHAVE = os.getenv("DATAJUD_APIKEY")
URL = "https://api-publica.datajud.cnj.jus.br/api_publica_%s/_search"

TR_UF = {"01": "ac", "02": "al", "03": "ap", "04": "am", "05": "ba", "06": "ce",
         "07": "df", "08": "es", "09": "go", "10": "ma", "11": "mt", "12": "ms",
         "13": "mg", "14": "pa", "15": "pb", "16": "pr", "17": "pe", "18": "pi",
         "19": "rj", "20": "rn", "21": "rs", "22": "ro", "23": "rr", "24": "sc",
         "25": "se", "26": "sp", "27": "to"}
TJM = {"13": "tjmmg", "21": "tjmrs", "26": "tjmsp"}

# Movimentos que contam a HISTORIA do credito. A tabela do CNJ tem centenas; estes
# sao os que mudam o estagio.
#
# CUIDADO com 'Expedição de documento' (codigo 60): e' generico e aparece dezenas de
# vezes em qualquer processo (certidao, intimacao, "outros documentos"). Usa-lo como
# sinal de requisitorio dava falso positivo em 100% dos casos testados — no processo
# do card #3373 ele aparece ANTES ate' da sentenca. O que distingue e' o
# `complementosTabelados`: so' conta quando o complemento diz 'Ofício'.
MARCOS = ("Distribuição", "Procedência", "Procedência em Parte", "Improcedência",
          "Trânsito em julgado", "Baixa Definitiva", "Definitivo",
          "Homologação", "Extinção da execução", "Cumprimento de sentença",
          "Arquivamento", "Suspensão", "Conversão em RPV", "Pagamento",
          "Expedição de precatório", "Requisição de pequeno valor")
# Classes (codigo do CNJ) que ja' pressupoem TITULO EXECUTIVO FORMADO. E' o sinal
# mais confiavel do estagio — mais do que procurar "Trânsito em julgado" na
# movimentacao, que costuma estar no processo de CONHECIMENTO e nao no cumprimento
# (foi o que fez o card #3527 ser diagnosticado errado na primeira versao).
CLASSES_EXECUCAO = {156: "Cumprimento de sentença", 229: "Execução de título judicial"}
CLASSE_PRECATORIO = 12078


def so_digitos(s):
    return re.sub(r"\D", "", str(s or ""))


def indice(numero):
    """Numero CNJ -> indice do DataJud. None quando nao ha' base publica."""
    d = so_digitos(numero)
    if len(d) != 20:
        return None
    j, tr = d[13], d[14:16]
    if j == "8":
        return "tjdft" if tr == "07" else ("tj" + TR_UF[tr] if tr in TR_UF else None)
    if j == "5":
        return "tst" if tr == "00" else "trt" + str(int(tr))
    if j == "4":
        return "trf" + str(int(tr))
    if j == "6":
        return "tse" if tr == "00" else ("tre-" + TR_UF[tr] if tr in TR_UF else None)
    if j == "3":
        return "stj"
    if j == "7":
        return "stm"
    if j == "9":
        return TJM.get(tr)
    return None                                    # j == "1": STF, sem indice publico


def _consulta(sigla, numero):
    corpo = json.dumps({"query": {"match": {"numeroProcesso": numero}}, "size": 3}).encode()
    req = urllib.request.Request(URL % sigla, data=corpo,
                                 headers={"Authorization": "APIKey " + CHAVE,
                                          "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
        return json.loads(r.read().decode("utf-8"))


def _dbr(iso):
    return "%s/%s/%s" % (iso[8:10], iso[5:7], iso[0:4]) if iso and len(iso) >= 10 else "—"


def _oficio_expedido(movs):
    """Data do ultimo 'Expedição de documento' cujo COMPLEMENTO diz 'Ofício'.

    E' o melhor indicio de requisitorio que o DataJud oferece — e continua sendo um
    INDICIO, nao prova: 'Ofício' tambem cobre oficio a banco, a orgao, etc. Por isso
    o diagnostico fala em "indício de requisitório", nunca em "requisitório expedido".
    """
    achado = None
    for m in movs:
        if m.get("codigo") != 60:
            continue
        comp = " ".join((c.get("nome") or "") for c in (m.get("complementosTabelados") or []))
        if "ofício" in comp.lower() or "oficio" in comp.lower():
            achado = (m.get("dataHora") or "")[:10]
    return achado


def _diagnostico(grau, classe_cod, classe_nome, nomes, movs, numero_e_precatorio):
    """Traduz classe + movimentacao no ESTAGIO do credito.

    A classe manda mais que a movimentacao: um 'Cumprimento de sentença' ja' pressupoe
    titulo formado, mesmo que o 'Trânsito em julgado' esteja registrado no processo de
    conhecimento (numero diferente) e nao neste. Foi exatamente esse o erro da primeira
    versao, que classificou o card #3527 como "ainda em conhecimento".
    """
    n = set(nomes)
    classe_l = (classe_nome or "").lower()
    transitou = "Trânsito em julgado" in n
    execucao = classe_cod in CLASSES_EXECUCAO or "cumprimento" in classe_l or "execução" in classe_l
    oficio = _oficio_expedido(movs)
    sentenca = next((x for x in ("Procedência em Parte", "Procedência", "Improcedência")
                     if x in n), None)

    if numero_e_precatorio or classe_cod == CLASSE_PRECATORIO:
        return ("precatorio_fora_da_base",
                "Este número É de precatório e o processo existe no DataJud — mas ele não está "
                "na fila que o Alfred coletou. Pode ser ente ainda não coberto, precatório "
                "autuado depois da última coleta, ou lista do tribunal desatualizada. "
                "Confirme no portal do tribunal.", oficio, sentenca)
    if execucao and oficio:
        return ("requisitado_nao_autuado",
                "Processo em fase de execução/cumprimento de sentença — título já formado — e "
                "com ofício expedido em %s. É o retrato da janela entre a requisição e a "
                "publicação: o crédito existe, o precatório ainda não foi autuado em lista "
                "nenhuma. Peça cópia do ofício requisitório e da conta homologada, e reconsulte "
                "o portal do tribunal em 30–60 dias. (O DataJud não distingue ofício "
                "requisitório de outros ofícios — confirme no processo.)" % _dbr(oficio),
                oficio, sentenca)
    if execucao:
        return ("em_cumprimento",
                "Processo em fase de execução/cumprimento de sentença: o título já está "
                "formado, mas não há sinal de ofício expedido. O crédito tende a virar "
                "precatório; ainda não virou.", oficio, sentenca)
    if transitou:
        return ("transitado",
                "Há trânsito em julgado registrado, mas o processo não aparece em fase de "
                "cumprimento de sentença. Falta o cumprimento para que a requisição saia.",
                oficio, sentenca)
    if grau == "G1" or "conhecimento" in classe_l or "procedimento comum" in classe_l:
        extra = (" A sentença registrada é de %s, e ainda cabe recurso." % sentenca.lower()
                 if sentenca else "")
        return ("em_conhecimento",
                "Ainda em ação de conhecimento, SEM trânsito em julgado.%s Não há crédito certo, "
                "líquido e exigível — antecipar aqui é comprar expectativa de direito, risco "
                "(e preço) de outra natureza que a cessão de um precatório expedido." % extra,
                oficio, sentenca)
    return ("indefinido",
            "Processo localizado no DataJud, mas a movimentação não permite dizer o estágio "
            "com segurança. Ler os marcos abaixo.", oficio, sentenca)


def rastrear(numero):
    """{achou, tribunal, classe, orgao, grau, ajuizamento, marcos, diagnostico...}.

    Nunca levanta excecao por causa da rede: devolve `erro` preenchido. Esta funcao
    e' chamada de dentro de uma requisicao HTTP — derrubar a busca porque o DataJud
    piscou seria pior do que nao responder.
    """
    d = so_digitos(numero)
    out = {"numero": numero, "numero_normalizado": d, "achou": False,
           "fonte": "DataJud/CNJ (base pública)", "erro": None}
    if len(d) != 20:
        out["erro"] = "número fora do padrão CNJ (20 dígitos)"
        return out
    sigla = indice(d)
    if not sigla:
        out["erro"] = "sem base pública no DataJud para este segmento de justiça"
        return out
    out["indice"] = sigla
    try:
        r = _consulta(sigla, d)
    except urllib.error.HTTPError as e:
        out["erro"] = "DataJud respondeu HTTP %s" % e.code
        return out
    except Exception as e:                                              # noqa: BLE001
        out["erro"] = "DataJud indisponível (%s)" % type(e).__name__
        return out

    hits = (r.get("hits") or {}).get("hits") or []
    if not hits:
        out["diagnostico"] = "sem_registro"
        out["explicacao"] = ("O número não está na fila do Alfred nem aparece no DataJud do "
                             "%s. Número de PRECATÓRIO costuma mesmo dar zero (a base pública "
                             "cobre mal o 2º grau) — tente o número do processo de ORIGEM."
                             % sigla.upper())
        return out

    # Quando ha' mais de um hit (conhecimento + recurso), o de 1o grau conta a fase
    # atual do credito; o de 2o grau costuma estar baixado.
    fontes = [h.get("_source") or {} for h in hits]
    src = next((f for f in fontes if f.get("grau") == "G1"), fontes[0])
    movs = sorted(src.get("movimentos") or [], key=lambda m: m.get("dataHora") or "")
    nomes = [m.get("nome") for m in movs]
    marcos = []
    for m in movs:
        comp = " ".join((c.get("nome") or "") for c in (m.get("complementosTabelados") or []))
        oficio = m.get("codigo") == 60 and "fício" in comp
        if m.get("nome") in MARCOS or oficio:
            marcos.append({"data": (m.get("dataHora") or "")[:10],
                           "nome": m.get("nome") + (" (%s)" % comp if oficio and comp else "")})
    cls = src.get("classe") or {}
    codigo, texto, oficio_em, sentenca = _diagnostico(
        src.get("grau"), cls.get("codigo"), cls.get("nome"), nomes, movs,
        d[13] == "8" and d[16:] == "0000")
    out.update({
        "achou": True, "tribunal": sigla.upper(),
        "classe": (src.get("classe") or {}).get("nome"),
        "orgao": (src.get("orgaoJulgador") or {}).get("nome"),
        "grau": src.get("grau"),
        "ajuizamento": (src.get("dataAjuizamento") or "")[:8] or None,
        "assuntos": [a.get("nome") for a in (src.get("assuntos") or [])][:3],
        "n_movimentos": len(movs),
        "ultimo_movimento": ({"data": (movs[-1].get("dataHora") or "")[:10],
                              "nome": movs[-1].get("nome")} if movs else None),
        "marcos": marcos[-12:],
        "diagnostico": codigo, "explicacao": texto,
        "oficio_expedido_em": oficio_em, "sentenca": sentenca,
        "outros_processos": len(fontes) - 1,
    })
    return out


def _br(iso8):
    return "%s/%s/%s" % (iso8[6:8], iso8[4:6], iso8[0:4]) if iso8 and len(iso8) >= 8 else "—"


def main():
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    sys.stdout.reconfigure(encoding="utf-8")
    r = rastrear(sys.argv[1])
    print("=" * 74)
    print("RASTREIO", r["numero"])
    print("=" * 74)
    if r.get("erro"):
        print("erro:", r["erro"])
        return
    if not r["achou"]:
        print(r["explicacao"])
        return
    print("tribunal .......", r["tribunal"], "| grau", r["grau"])
    print("classe .........", r["classe"])
    print("órgão ..........", r["orgao"])
    print("ajuizamento ....", _br(r["ajuizamento"]))
    print("assuntos .......", ", ".join(r["assuntos"] or []) or "—")
    print("movimentos .....", r["n_movimentos"], "| último:",
          (r["ultimo_movimento"] or {}).get("data"), (r["ultimo_movimento"] or {}).get("nome"))
    print("\nMARCOS")
    for m in r["marcos"]:
        print("   %s  %s" % (m["data"], m["nome"]))
    print("\nDIAGNÓSTICO [%s]" % r["diagnostico"])
    print("  " + r["explicacao"])


if __name__ == "__main__":
    main()
