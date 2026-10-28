"""PJe — o processo se descreve sozinho. Nível 0: ZERO LLM, ZERO OCR.

O PDF exportado do PJe traz duas coisas que o radar ignorava:

  ÍNDICE   as primeiras páginas listam cada documento: Id, data, título e tipo
           ("4609108021  15/07/2021  Laudo Pericial  Laudo Pericial").
  CARIMBO  toda página nativa leva "Num. <Id> - Pág. N" na assinatura digital.

Juntos, dizem a que DOCUMENTO cada página pertence e o que ele é. Daí sai, sem
modelo nenhum:

  conta homologada  o documento que as DECISÕES citam por Id ao lado de
                    "laudo/cálculo/perito" (votação) e que contém o VALOR que o
                    dispositivo manda pagar (âncora, que também aponta a PÁGINA
                    operativa dentro do documento);
  ofício            o formulário da Res. 303/CNJ, lido por RÓTULO de item
                    ("4.15. Valor Bruto:"), com a versão mais recente de cada nº;
  alertas           reconciliação ofício × conta × dispositivo.

Medido no caso #3481 (TJMG, 223 págs., 05/10/2026): o radar devolvia 24 faixas,
marcava o próprio índice como "ofício" e não achava a homologação (a sentença
não diz "homologo", diz "conforme apontado pelo Perito"). Aqui: 212/223 páginas
mapeadas; o laudo (Id 4609108021) recebe 12 votos e o valor do dispositivo
(268.989,79) aparece só na pág 127 dele — a pág 126 tem DUAS contas (04/2020 e
07/2021) e a primeira linha "Total" é a antiga.

⚠ O ofício também erra, e é o que mais importa para a pré-análise: no #3481 o
cartório pôs principal = bruto = 244.536,17 (o principal da conta é 119.475,68)
e data-base 28/12/2012 (a decisão manda corrigir até 15/07/2021). Por isso os
valores do formulário viram ALERTA, nunca campo silencioso.

Fora do PJe (eproc, ESAJ) não há carimbo: `analisar` devolve None e o pipeline
segue com o radar.
"""
from __future__ import annotations

import re
from collections import Counter, defaultdict

import fitz

from .deterministico import centavos, paginas_com_valor
from .substrato import VALOR, texto_util

_ID = r"\d{9,11}"
_RE_CARIMBO = re.compile(rf"Num\.\s*({_ID})\s*-\s*P[áa]g\.\s*(\d+)")
_RE_DATA = re.compile(r"\b(\d{2})/(\d{2})/(\d{4})\b")
_RE_CNJ = re.compile(r"\b\d{7}-\d{2}\.\d{4}\.\d\.\d{2}\.\d{4}\b")

# o índice nunca passa disto; páginas além são conteúdo
MAX_PAGINAS_INDICE = 10
# a coluna "Tipo" começa ~60pt à esquerda do rótulo do cabeçalho (medido no
# TJMG: cabeçalho em x=473, palavras do tipo a partir de x=415; título até ~395)
RECUO_COLUNA_TIPO = 60.0

_RE_DECISAO = re.compile(r"senten[çc]a|decis[ãa]o|despacho|ac[óo]rd[ãa]o", re.I)
_RE_CONTA_TITULO = re.compile(
    r"laudo|c[áa]lculo|planilha|conta de liquida|demonstrativo|contadoria|parecer cont|"
    r"estudo t[ée]cnico", re.I)
# Título que CONTÉM "cálculo" mas é a peça de uma parte, não a conta: no
# levantamento de 28/10/2026, "Impugnação ao Cumprimento de Sentença" (17 casos),
# "Impugnação aos cálculos de liquidação" e "Execução / Cumprimento de Sentença"
# (13). Não ganham o ponto do título; se uma decisão os citar, os votos valem.
_RE_TITULO_NAO_CONTA = re.compile(
    r"impugna|manifesta|peti[çc]|intima|cumprimento de senten|embargos|recurso|agravo", re.I)
# Decisão citando o documento da conta: "laudo pericial de Id. 4609108021",
# "ff. 06/07 do id. 4609108021". A palavra-chave tem de vir ANTES do Id, perto.
_RE_CITA_CONTA = re.compile(
    rf"(laudo|c[áa]lculo|conta|perit\w*|planilha|contadoria)[^.;]{{0,80}}?"
    rf"\bid\.?\s*(?:n[º°.]?\s*)?({_ID})", re.I)
_RE_DISPOSITIVO = re.compile(
    r"DISPOSITIVO|(?:Do|Ante o|Diante do|Pelo) exposto|Isto posto|Posto isso", re.I)
_RE_ATE_DATA = re.compile(r"at[ée]\s+(?:a data de\s+)?(\d{2}/\d{2}/\d{4})", re.I)
_RE_OFICIO_FORM = re.compile(
    r"OF[ÍI]CIO\s+PRECAT[ÓO]RIO|REQUISI[ÇC][ÃA]O\s+(?:PARA|DE)\s+PAGAMENTO|"
    r"REQUISI[ÇC][ÃA]O\s+DE\s+PEQUENO\s+VALOR|TIPO\s+DE\s+REQUISI[ÇC][ÃA]O|"
    r"RESOLU[ÇC][ÃA]O\s+N?[º°.]?\s*303/2019", re.I)
# item do formulário: "4.15. Valor Bruto:" — sempre no início da linha
_RE_ITEM = re.compile(r"(?m)^[ \t]*(\d{1,2}(?:\.\d{1,2}){1,3})\.?[ \t]+")

# rótulos de corte (mesmo vocabulário do `pipeline`; repetido para não criar
# import circular — `pipeline` importa este módulo)
_TIPO_CONTA = "Conta homologada"
_TIPO_OFICIO = "Ofício requisitório"


def _abrir(fonte) -> fitz.Document:
    if isinstance(fonte, fitz.Document):
        return fonte
    if isinstance(fonte, (bytes, bytearray)):
        return fitz.open(stream=bytes(fonte), filetype="pdf")
    return fitz.open(fonte)


def _iso(data_br: str | None) -> str | None:
    m = _RE_DATA.search(data_br or "")
    return f"{m.group(3)}-{m.group(2)}-{m.group(1)}" if m else None


def _data_br(iso: str | None) -> str:
    return "/".join(reversed(iso.split("-"))) if iso else "?"


def _br(cents: int) -> str:
    inteiro, c = divmod(abs(cents), 100)
    return ("-" if cents < 0 else "") + f"{inteiro:,}".replace(",", ".") + f",{c:02d}"


# ── 1 · índice ───────────────────────────────────────────────────────────
def _linhas(page) -> list[list[tuple]]:
    """Palavras agrupadas por linha (y), cada linha ordenada por x."""
    grupos: dict[int, list] = defaultdict(list)
    for w in page.get_text("words"):
        grupos[round(w[1] / 3)].append(w)
    return [sorted(grupos[k], key=lambda w: w[0]) for k in sorted(grupos)]


def ler_indice(doc: fitz.Document) -> dict[str, dict]:
    """{id: {data, titulo, tipo, ordem}} a partir da tabela "Documentos".

    Lê por GEOMETRIA: no texto corrido o PyMuPDF emite a coluna de Ids inteira
    e só depois os títulos, e a associação se perde. Título que quebra linha
    (ex.: "Contrato celebrado entre a Cedente e o / Município") continua na
    linha seguinte, sem Id — é anexado ao documento anterior, na coluna certa.
    """
    indice: dict[str, dict] = {}
    corte_tipo = None
    for i in range(min(MAX_PAGINAS_INDICE, doc.page_count)):
        page = doc[i]
        if i > 0 and _RE_CARIMBO.search(page.get_text()):
            break  # acabou o índice, começou o processo
        atual = None
        for ws in _linhas(page):
            palavras = [w[4] for w in ws]
            if "Tipo" in palavras and any(p.startswith("Id") for p in palavras):
                corte_tipo = ws[palavras.index("Tipo")][0] - RECUO_COLUNA_TIPO
                continue
            if (len(ws) >= 3 and re.fullmatch(_ID, palavras[0])
                    and _RE_DATA.fullmatch(palavras[1]) and re.fullmatch(r"\d\d:\d\d", palavras[2])):
                atual = palavras[0]
                indice[atual] = {"data": _iso(palavras[1]), "titulo": "", "tipo": "",
                                 "ordem": len(indice)}
                resto = ws[3:]
            elif atual and ws and ws[0][0] > 150:  # continuação: só nas colunas de texto
                resto = ws
            else:
                atual = None
                continue
            for w in resto:
                campo = "tipo" if corte_tipo is not None and w[0] >= corte_tipo else "titulo"
                indice[atual][campo] = (indice[atual][campo] + " " + w[4]).strip()
    return indice


# ── 2 · carimbo: página → documento ──────────────────────────────────────
def mapear_paginas(textos: list[str]) -> list[str | None]:
    """Id do documento de cada página (índice 0 = pág 1), ou None.

    Página sem carimbo (escaneada: o carimbo também vira imagem) herda o Id
    só quando as DUAS vizinhas são do mesmo documento — no meio de um
    documento não há dúvida; na borda, chutar o vizinho erraria a metade.
    """
    ids = []
    for t in textos:
        m = _RE_CARIMBO.search(t or "")
        ids.append(m.group(1) if m else None)
    for i in range(1, len(ids) - 1):
        if ids[i] is None and ids[i - 1] and ids[i - 1] == ids[i + 1]:
            ids[i] = ids[i - 1]
    return ids


def _faixas(ids: list[str | None]) -> dict[str, tuple[int, int]]:
    """{id: (primeira, última)} em páginas 1-based."""
    out: dict[str, tuple[int, int]] = {}
    for i, d in enumerate(ids, start=1):
        if d:
            a, _ = out.get(d, (i, i))
            out[d] = (a, i)
    return out


# ── 3 · decisões: dispositivo e citações ─────────────────────────────────
def _dispositivo(texto: str) -> str:
    """Do ÚLTIMO marcador de dispositivo até o fim. Sem marcador, nada — os
    valores da fundamentação incluem os que a decisão REJEITA."""
    ms = list(_RE_DISPOSITIVO.finditer(texto))
    return texto[ms[-1].start():] if ms else ""


def _decisoes(docs: dict, textos_doc: dict) -> list[dict]:
    """Decisões com valor no dispositivo, da mais RECENTE para a mais antiga
    (embargos corrigem a sentença: no #3481, de "até 13/10/2020" para "até
    15/07/2021")."""
    out = []
    for d, info in docs.items():
        if not _RE_DECISAO.search(f"{info['titulo']} {info['tipo']}"):
            continue
        if re.search(r"intima[çc]|certid", info["tipo"], re.I):
            continue  # a cópia da decisão que vai na intimação repete o original
        disp = _dispositivo(re.sub(r"\s+", " ", textos_doc[d]))
        valores = list(dict.fromkeys(VALOR.findall(disp)))
        if valores:
            out.append({"id": d, "titulo": info["titulo"], "data": info["data"],
                        "pagina_inicio": info["pagina_inicio"], "pagina_fim": info["pagina_fim"],
                        "valores": valores,
                        "datas": [_iso(x) for x in _RE_ATE_DATA.findall(disp)]})
    out.sort(key=lambda x: (x["data"] or "", x["pagina_inicio"]), reverse=True)
    return out


def _titulo_de_conta(info: dict) -> bool:
    rotulo = f"{info['titulo']} {info['tipo']}"
    return bool(_RE_CONTA_TITULO.search(rotulo)) and not _RE_TITULO_NAO_CONTA.search(rotulo)


def _achar_conta(docs: dict, textos_doc: dict, decisoes: list[dict],
                 paginas: list[dict], oficios_ids: set[str]) -> dict | None:
    """Documento da conta homologada: votos das decisões + âncora de valor.

    A âncora só vale para quem já é candidato (título de conta OU citado por
    decisão): a petição do advogado TRANSCREVE o valor da condenação (#3481,
    pág 172) e, sem esse filtro, ganharia da própria conta.
    """
    votos: Counter = Counter()
    for d, info in docs.items():
        if not _RE_DECISAO.search(f"{info['titulo']} {info['tipo']}"):
            continue
        for m in _RE_CITA_CONTA.finditer(re.sub(r"\s+", " ", textos_doc[d])):
            if m.group(2) in docs and m.group(2) != d:
                votos[m.group(2)] += 1
    decisao_ids = {d for d, i in docs.items() if _RE_DECISAO.search(f"{i['titulo']} {i['tipo']}")}
    candidatos = {d for d in docs
                  if d not in decisao_ids and d not in oficios_ids
                  and (votos[d] or _titulo_de_conta(docs[d]))}
    if not candidatos:
        return None

    melhor = None
    for d in candidatos:
        a, b = docs[d]["pagina_inicio"], docs[d]["pagina_fim"]
        do_doc = [p for p in paginas if a <= p["pagina"] <= b]
        ancora = None
        for dec in decisoes:  # decisão mais recente primeiro
            for v in dec["valores"]:
                pgs = paginas_com_valor(v, do_doc)
                if pgs:
                    ancora = {"valor": v, "pagina": pgs[-1], "decisao": dec["id"]}
                    break
            if ancora:
                break
        titulo_conta = _titulo_de_conta(docs[d])
        score = votos[d] + (5 if ancora else 0) + (1 if titulo_conta else 0)
        chave = (score, docs[d]["pagina_inicio"])  # empate: o mais recente
        if melhor is None or chave > melhor[0]:
            melhor = (chave, d, ancora)
    (score, _), d, ancora = melhor
    if score < 2 and not ancora:
        return None  # só o título de "planilha" não basta para afirmar homologação
    return {"id": d, "titulo": docs[d]["titulo"], "data": docs[d]["data"],
            "pagina_inicio": docs[d]["pagina_inicio"], "pagina_fim": docs[d]["pagina_fim"],
            "votos": votos[d], "ancora": ancora}


# ── 4 · ofício (formulário da Res. 303/CNJ) ──────────────────────────────
def _itens(texto: str) -> list[tuple[str, str]]:
    """[(numero, corpo)] — o corpo vai até o próximo item. Cortar no item
    seguinte é o que impede um campo VAZIO ("4.20. ... R$" em branco) de
    roubar o valor do campo de baixo."""
    ms = list(_RE_ITEM.finditer(texto))
    return [(m.group(1), texto[m.end(): ms[k + 1].start() if k + 1 < len(ms) else len(texto)])
            for k, m in enumerate(ms)]


def _valor_do_item(itens, rotulo: re.Pattern, extrator: re.Pattern = VALOR) -> str | None:
    for _, corpo in itens:
        cab = corpo.split(":", 1)
        if not rotulo.search(cab[0]):
            continue
        m = extrator.search(cab[1] if len(cab) > 1 else corpo)
        if m:
            return m.group(0)
    return None


def _texto_do_item(itens, rotulo: re.Pattern) -> str | None:
    for _, corpo in itens:
        cab = corpo.split(":", 1)
        if len(cab) == 2 and rotulo.search(cab[0]):
            for linha in cab[1].splitlines():
                linha = linha.strip()
                if linha and not linha.startswith("("):
                    return linha
    return None


def _marcados(page) -> set[str]:
    """Opções assinaladas com "X" — a palavra logo à DIREITA do X, na mesma
    linha. No texto corrido o X vira uma linha solta e a associação depende da
    ordem de emissão; por geometria ela é inequívoca."""
    ws = page.get_text("words")
    out = set()
    for x in ws:
        if x[4] not in ("X", "x"):
            continue
        yc = (x[1] + x[3]) / 2
        direita = [w for w in ws if w is not x and abs((w[1] + w[3]) / 2 - yc) <= 4
                   and 0 <= w[0] - x[2] <= 45]
        if direita:
            out.add(min(direita, key=lambda w: w[0])[4])
    return out


_ROT = {
    "valor_bruto": re.compile(r"valor bruto", re.I),
    "valor_principal": re.compile(r"principal corrigido", re.I),
    "valor_juros": re.compile(r"valor (?:correspondente )?dos juros morat", re.I),
    "valor_juros_compensatorios": re.compile(r"valor dos juros compensat", re.I),
    "valor_despesas": re.compile(r"despesas antecipadas", re.I),
    "valor_total_requisitado": re.compile(r"total requisitado", re.I),
}
_CAMPOS_VALOR_OFICIO = tuple(_ROT)


def ler_oficio(doc: fitz.Document, a: int, b: int) -> dict | None:
    """Campos do formulário-ofício nas páginas [a, b] (1-based), ou None se
    não for um formulário de requisição."""
    pages = [doc[i - 1] for i in range(a, b + 1)]
    texto = "\n".join(texto_util(p.get_text()) for p in pages)
    if not _RE_OFICIO_FORM.search(texto):
        return None
    itens = _itens(texto)
    campos: dict = {k: _valor_do_item(itens, r) for k, r in _ROT.items()}
    campos["data_base"] = _iso(_valor_do_item(itens, re.compile(r"data-base", re.I), _RE_DATA))
    campos["ente_devedor"] = _texto_do_item(itens, re.compile(r"ente devedor", re.I))
    campos["beneficiario"] = _texto_do_item(
        itens, re.compile(r"nome do benefici[áa]rio\s+(?:principal|dos honor)", re.I))
    campos["numero_processo"] = _valor_do_item(itens, re.compile(r"numera[çc][ãa]o [úu]nica", re.I), _RE_CNJ)
    m = re.search(r"N[º°]\s*(\d{3,10})\s*/\s*(\d{4})", texto[:1500])
    campos["numero_oficio"] = f"{m.group(1)}/{m.group(2)}" if m else None
    cab = texto[:1500].upper()
    campos["modalidade"] = "rpv" if "PEQUENO VALOR" in cab else "precatorio"
    marc = set().union(*(_marcados(p) for p in pages))
    campos["natureza_credito"] = ("alimentar" if any(w.startswith("Alimentar") for w in marc)
                                  else "comum" if "Comum" in marc else None)
    if not any(campos[k] for k in ("valor_bruto", "valor_principal", "valor_total_requisitado")):
        # Certidão de aprovação, intimação e juntada CITAM "ofício precatório"
        # (#3481 págs 214, 222, 223); o formulário em branco do cartório também
        # não serve. Sem nenhum valor, não é o ofício que a pré-análise lê.
        return None
    beneficiario_tipo = ("honorarios_sucumbenciais" if "SUCUMB" in cab
                         else "honorarios_contratuais" if "CONTRATUA" in cab.split("REQUISI")[0]
                         else "principal")
    preenchidos = sum(1 for v in campos.values() if v not in (None, ""))
    return {"pagina_inicio": a, "pagina_fim": b, "beneficiario_tipo": beneficiario_tipo,
            "campos": campos, "preenchidos": preenchidos}


def _ultima_versao(oficios: list[dict]) -> list[dict]:
    """Um ofício por (beneficiário, nº): o mais preenchido, e no empate o mais
    recente. O SEI junta o MESMO formulário várias vezes — em branco pelo
    cartório, preenchido pelo advogado, final (#3481: págs 202, 206, 210)."""
    grupos: dict = {}
    for o in oficios:
        k = (o["beneficiario_tipo"], o["campos"].get("numero_oficio"))
        atual = grupos.get(k)
        if atual is None or (o["preenchidos"], o["pagina_inicio"]) >= (atual["preenchidos"], atual["pagina_inicio"]):
            grupos[k] = o
    return sorted(grupos.values(), key=lambda o: o["pagina_inicio"])


# ── 5 · reconciliação ────────────────────────────────────────────────────
def _alertas(conta: dict | None, oficios: list[dict], decisoes: list[dict],
             paginas: list[dict]) -> list[dict]:
    alertas = []
    do_conta = ([p for p in paginas if conta["pagina_inicio"] <= p["pagina"] <= conta["pagina_fim"]]
                if conta else [])
    principal = next((o for o in oficios if o["beneficiario_tipo"] == "principal"), None)
    decisao = decisoes[0] if decisoes else None

    for o in oficios:
        c = {k: centavos(o["campos"].get(k)) for k in _CAMPOS_VALOR_OFICIO}
        bruto, princ, juros = c["valor_bruto"], c["valor_principal"], c["valor_juros"]
        if bruto and princ is not None:
            soma = princ + (juros or 0) + (c["valor_juros_compensatorios"] or 0) + (c["valor_despesas"] or 0)
            if abs(soma - bruto) > max(100, bruto // 1000):
                al = {"tipo": "oficio_aritmetica", "paginas": [o["pagina_inicio"], o["pagina_fim"]],
                      "mensagem": (f"Ofício (págs {o['pagina_inicio']}–{o['pagina_fim']}) não fecha: "
                                   f"principal {_br(princ)} + juros {_br(juros or 0)} = {_br(soma)}, "
                                   f"mas o bruto é {_br(bruto)}.")}
                if juros and princ == bruto:
                    sug = bruto - juros
                    onde = paginas_com_valor(_br(sug), do_conta)
                    al["sugestao"] = {"valor_principal": _br(sug), "paginas_conta": onde}
                    al["mensagem"] += (f" Parece que o principal foi preenchido com o bruto; "
                                       f"bruto − juros = {_br(sug)}"
                                       + (f", que ESTÁ na conta (pág {', '.join(map(str, onde))})." if onde else "."))
                alertas.append(al)
        if do_conta and o is principal:
            for k in ("valor_bruto", "valor_juros"):
                v = o["campos"].get(k)
                if v and centavos(v) and not paginas_com_valor(v, do_conta):
                    alertas.append({"tipo": "oficio_fora_da_conta", "paginas": [o["pagina_inicio"]],
                                    "mensagem": f"{k} do ofício ({v}) não aparece na conta homologada "
                                                f"(págs {conta['pagina_inicio']}–{conta['pagina_fim']})."})
        db = o["campos"].get("data_base")
        if db and decisao and decisao["datas"] and db not in decisao["datas"]:
            alertas.append({"tipo": "oficio_data_base", "paginas": [o["pagina_inicio"], decisao["pagina_inicio"]],
                            "mensagem": (f"Data-base do ofício ({_data_br(db)}) difere da data a que a decisão "
                                         f"(pág {decisao['pagina_inicio']}) manda corrigir "
                                         f"({_data_br(decisao['datas'][-1])}).")})

    # O valor da decisão costuma SOMAR a sucumbência, que vira outro precatório
    # (do advogado). É o "+9,09%" medido no corpus: 10% de honorários sobre o
    # crédito = 9,09% do total. O crédito do credor é o bruto do ofício PRINCIPAL.
    if decisao and principal and centavos(principal["campos"].get("valor_bruto")):
        brutos = sum(centavos(o["campos"].get("valor_bruto")) or 0 for o in oficios)
        alvo = centavos(decisao["valores"][0])
        if len(oficios) > 1 and alvo and abs(brutos - alvo) <= 100:
            alertas.append({"tipo": "sucumbencia_separada", "paginas": [decisao["pagina_inicio"]],
                            "mensagem": (f"O valor da decisão ({decisao['valores'][0]}) = soma dos ofícios "
                                         f"(credor + honorários sucumbenciais). O crédito do credor é "
                                         f"{principal['campos']['valor_bruto']}, não o total da decisão.")})
    return alertas


# ── entrada ──────────────────────────────────────────────────────────────
def analisar(fonte, paginas: list[dict] | None = None) -> dict | None:
    """Segmenta um processo do PJe e localiza conta homologada e ofícios.

    `paginas` = substrato já calculado (reusa o texto, inclusive o de OCR, em
    vez de reler o PDF). Devolve None quando o PDF não tem carimbo do PJe.
    """
    doc = _abrir(fonte)
    try:
        # ⚠ o carimbo sai SEMPRE do PDF, nunca do substrato: em página escaneada
        # o carimbo continua nativo, mas sozinho fica abaixo de MIN_TEXTO_NATIVO
        # e o substrato zera o texto (sem OCR). No #3481 isso apagava 55 páginas.
        crus = [doc[i].get_text() for i in range(doc.page_count)]
        if paginas is None:
            paginas = [{"pagina": i, "texto": t, "tabela": []} for i, t in enumerate(crus, start=1)]
        textos = [(p.get("texto") or "") or c for p, c in zip(paginas, crus)]
        ids = mapear_paginas(crus)
        if not any(ids):
            return None
        indice = ler_indice(doc)
        docs = {}
        for d, (a, b) in _faixas(ids).items():
            info = indice.get(d, {})
            docs[d] = {"id": d, "data": info.get("data"), "titulo": info.get("titulo", ""),
                       "tipo": info.get("tipo", ""), "pagina_inicio": a, "pagina_fim": b}
        textos_doc = {d: "\n".join(textos[i["pagina_inicio"] - 1: i["pagina_fim"]]) for d, i in docs.items()}

        brutos = []
        for d, i in docs.items():
            o = ler_oficio(doc, i["pagina_inicio"], i["pagina_fim"])
            if o:
                o["id"], o["data"] = d, i["data"]
                brutos.append(o)
        oficios = _ultima_versao(brutos)
        decisoes = _decisoes(docs, textos_doc)
        conta = _achar_conta(docs, textos_doc, decisoes, paginas, {o["id"] for o in brutos})
        alertas = _alertas(conta, oficios, decisoes, paginas)

        cortes = []
        if conta:
            cortes.append({"tipo": _TIPO_CONTA, "pagina_inicio": conta["pagina_inicio"],
                           "pagina_fim": conta["pagina_fim"], "origem": "pje",
                           "motivo": f"Id {conta['id']}: citado {conta['votos']}× por decisões"
                                     + (f"; valor da decisão {conta['ancora']['valor']} na pág "
                                        f"{conta['ancora']['pagina']}" if conta["ancora"] else "")})
        # ofício do CREDOR primeiro: `extrair_cortes` usa o 1º corte de ofício
        for o in sorted(oficios, key=lambda o: o["beneficiario_tipo"] != "principal"):
            cortes.append({"tipo": _TIPO_OFICIO, "pagina_inicio": o["pagina_inicio"],
                           "pagina_fim": o["pagina_fim"], "origem": "pje",
                           "motivo": f"formulário-ofício nº {o['campos'].get('numero_oficio') or '?'} "
                                     f"({o['beneficiario_tipo'].replace('_', ' ')})"})
        return {
            "n_paginas": len(ids),
            "paginas_mapeadas": sum(1 for d in ids if d),
            "documentos": sorted(docs.values(), key=lambda x: x["pagina_inicio"]),
            "conta": conta,
            "decisao": decisoes[0] if decisoes else None,
            "oficios": oficios,
            "alertas": alertas,
            "cortes": cortes,
        }
    finally:
        if not isinstance(fonte, fitz.Document):
            doc.close()


def pista_conta(pje: dict | None, conta_ref: tuple[int, int]) -> str | None:
    """Frase para o prompt do extrator quando a âncora cai DENTRO da faixa
    que ele vai ler. Diz qual conta é a operativa — a página pode ter várias
    (#3481 pág 126: a de 04/2020 vem antes da de 07/2021)."""
    anc = ((pje or {}).get("conta") or {}).get("ancora")
    if not anc or not (conta_ref[0] <= anc["pagina"] <= conta_ref[1]):
        return None
    dec = (pje or {}).get("decisao") or {}
    ate = f", corrigido até {_data_br(dec['datas'][-1])}" if dec.get("datas") else ""
    return (f"A decisão manda pagar R$ {anc['valor']}{ate}; esse valor está na PÁGINA {anc['pagina']}. "
            f"A conta operativa é a que leva a esse valor — ignore versões anteriores da conta "
            f"na mesma faixa. Se o valor da decisão incluir honorários sucumbenciais, o "
            f"valor_total é o crédito do credor SEM eles.")


def campos_oficio(pje: dict | None, oficio_ref: tuple[int, int] | None) -> dict:
    """Campos do formulário (formato `{campo: {valor, citacao, fonte}}`) para o
    ofício que está DENTRO de `oficio_ref` — rede de segurança do extrator, no
    mesmo molde de `deterministico.numero_cnj`. Só os campos de identificação:
    os VALORES do ofício viajam como alerta (ver docstring do módulo)."""
    if not pje or not oficio_ref:
        return {}
    o = next((o for o in pje.get("oficios") or []
              if oficio_ref[0] <= o["pagina_inicio"] and o["pagina_fim"] <= oficio_ref[1]), None)
    if not o:
        return {}
    out = {}
    for campo in ("numero_oficio", "ente_devedor", "beneficiario", "modalidade"):
        v = o["campos"].get(campo)
        if v:
            out[campo] = {"valor": v, "citacao": {"pagina": o["pagina_inicio"], "trecho": str(v)},
                          "fonte": "pje"}
    return out
