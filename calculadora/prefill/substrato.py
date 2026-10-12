"""Pipeline v2 — CAMADA 1: substrato de texto (determinístico onde dá).

Princípio (medido nas fases 0e/0f): **ML fornece geometria, nunca caractere.**

  Página NATIVA  → texto real do PDF (impossível alucinar dígito) + estrutura de
                   coluna por clusterização de coordenadas (medido: 96,3% de
                   atribuição vs 0% do get_text puro, 2ms/pág, zero dependência).
  Página ESCANEADA → OCR (DeepSeek-OCR self-hosted tunado, ou Gemini). Aqui não
                   existe texto real; é o único lugar onde um modelo lê dígito.

Saída por página: {texto, nativa, tabela:[[celulas]], valores:[...]}.
A `tabela` é JSON de células (linha × coluna) — NÃO markdown com pipes: markdown
achata rowspan e injeta `|`/`#` que quebram validação de citação por substring.

Sem dependência nova: só PyMuPDF (já é dependência do projeto).
"""
from __future__ import annotations

import re
from itertools import combinations as _combinacoes

import fitz

# ⚠ guarda anti-coeficiente: sem os lookarounds, "184,97" casa dentro de
# "184,97040" (fator de correção tem 6-8 decimais) e polui tudo com não-dinheiro.
VALOR = re.compile(r"(?<![\d.,])\d{1,3}(?:\.\d{3})*,\d{2}(?!\d)")
_RUIDO = re.compile(r"Assinado eletronicamente.*?Juntado em:.*?\w{8}|Fls\.: \d+", re.S)

# ── carimbo eletrônico do PJe (achado no diagnóstico vt/vp/vj/vs, 10-11/09) ──
# Duas variantes, cada uma um rodapé/cabeçalho de assinatura digital — NUNCA
# conteúdo da conta. O problema real: quando a página é SÓ isto, o carimbo
# sozinho passa dos 50 caracteres de `MIN_TEXTO_NATIVO`, a página é marcada
# `nativa`, o OCR nunca roda, e o LLM só vê o carimbo — devolve null
# corretamente (não é alucinação), mas a conta de verdade nunca é lida.
# Medido: 42 páginas de conta (10 casos, todos TJMG) + 24 de ofício + 30 de
# sentença têm essa patologia. Cada linha abaixo é removida INTEIRA — não dá
# para cortar só a palavra-chave, porque o resto da linha (nome, data, hash,
# URL) não tem valor nenhum sem o carimbo por perto.
_CARIMBO_PJE = re.compile(
    r"^\s*Num\.\s*\d+\s*-\s*P[áa]g\.\s*\d+\s*$"              # "Num. 123 - Pág. 4"
    r"|^\s*Assinado eletronicamente por:.*$"                  # variante 1: assinatura
    r"|^\s*https?://\S+\s*$"                                  # variante 1: URL isolada
    r"|^\s*N[úu]mero do documento:\s*\d+\s*$"                 # variante 1: nº do documento
    r"|^\s*Este documento foi gerado pelo usu[áa]rio\b.*$",   # variante 2
    re.I | re.M,
)

# calibrados na fase 0f (varredura de 84 configs: resultado é robusto, não sensível)
GAP_COLUNA = 18.0   # pt de vão horizontal que separa duas colunas
TOL_LINHA = 3.0     # pt de tolerância vertical p/ mesma linha
MIN_TEXTO_NATIVO = 50   # chars úteis abaixo disso = página escaneada


def texto_util(t: str) -> str:
    t = _RUIDO.sub("", t or "")
    return _CARIMBO_PJE.sub("", t)


def eh_nativa(page) -> bool:
    """Página tem camada de texto real? (senão é escaneada → precisa de OCR)"""
    return len(texto_util(page.get_text()).strip()) >= MIN_TEXTO_NATIVO


def num(s: str) -> float | None:
    try:
        return float(s.replace(".", "").replace(",", "."))
    except Exception:
        return None


# ── PDF DEITADO são DUAS patologias, e confundi-las custa diagnóstico ───────
# Medido no corpus (77 casos, 53.698 páginas) em 2026-08-06:
#
#   PÁGINA girada  `page.rotation == 90` .......... 7.074 pág (13,17%)
#                  atributo da página; `remove_rotation()` resolve.
#   TEXTO  girado  `page.rotation == 0` e `dir == (0,±1)` .. 1.210 pág (2,25%),
#                  em 42 dos 77 casos. A matriz de DESENHO é que está girada;
#                  `remove_rotation()` é NO-OP e só girar COORDENADA resolve.
#
# ⚠ Medir sem chamar `remove_rotation()` ANTES confunde as duas: página com
# `rotation=90` reporta `dir=(0,-1)` mesmo com texto perfeitamente normal.
#
# Este módulo não tratava NENHUMA das duas. O estrago tem duas faces:
#
#   no TEXTO   a planilha do PJe-Calc emite as células coluna a coluna, então
#              cada valor sai numa linha só, divorciado do rótulo E da coluna,
#              com o cabeçalho fora de ordem — nem por posição dá para
#              reatribuir. É o que ia para o LLM:
#                  Descrição do Bruto Devido ao Reclamante
#                  Juros            ← a ordem real é 'Valor Corrigido|Juros|Total'
#                  Total
#                  Valor Corrigido
#                  DIFERENÇA SALARIAL
#                  0,00
#                  59.088,75
#
#   na TABELA  `clusterizar_tabela` agrupa coluna por x e linha por y — com os
#              eixos trocados. Medido no 2015 p33: 24 posições x distintas com
#              passo EXATO de 12,3pt, que não são 24 colunas e sim as 24 LINHAS
#              (12,3pt é o avanço de linha). E como 12,3 < GAP_COLUNA(18), o
#              corte por vão as ENCADEIA num cluster só: a tabela 24×5 colapsa
#              em 1 coluna e o total fica ilegível.
#
# ⚠ `page.set_rotation()` NÃO resolve (testado nos 4 ângulos): a extração ordena
# pela matriz do texto, e o ângulo da página é atributo de exibição.
#
# ⚠ Só as COORDENADAS giram — rotação rígida, que preserva distância (logo
# `GAP_COLUNA`/`TOL_LINHA`, calibrados em pt, seguem válidos sem retuning). O
# texto de cada palavra é o do PDF, literal: nenhum dígito é reinterpretado.
_EIXOS = {
    (0, -1): lambda x, y: (-y, x),   # glifos sobem  → gira 90° anti-horário
    (0, 1): lambda x, y: (y, -x),    # glifos descem → gira 90° horário
}


def direcao_dominante(page) -> tuple[int, int]:
    """Direção do texto da página, ponderada por CARACTERE.

    Ponderar por caractere — não por número de linhas — impede que um cabeçalho
    horizontal de três linhas curtas decida o eixo de uma tabela girada de 40
    linhas. Página sem texto devolve o eixo normal.
    """
    peso: dict[tuple[int, int], int] = {}
    for bloco in page.get_text("dict")["blocks"]:
        if bloco.get("type") != 0:      # 0 = texto, 1 = imagem
            continue
        for linha in bloco.get("lines", []):
            d = linha.get("dir") or (1, 0)
            k = (round(d[0]), round(d[1]))
            peso[k] = peso.get(k, 0) + sum(
                len(s.get("text") or "") for s in linha.get("spans", [])
            )
    return max(peso.items(), key=lambda kv: kv[1])[0] if peso else (1, 0)


def normalizar_pagina(page) -> tuple[int, int]:
    """Desfaz a rotação de PÁGINA e devolve a direção RESIDUAL do texto.

    ⚠ `remove_rotation()` LEVANTA (`ValueError: bad rect`) em página com widget
    de formulário de rect inválido — visto no corpus. Como isto roda dentro do
    laço de `processar_pdf`, a exceção derrubaria o PDF inteiro por causa de uma
    página. Engolir é seguro porque a desrotação por coordenada é a rede: a
    página segue com `rotation`, reporta `dir=(0,±1)` e cai no mesmo conserto.
    """
    if page.rotation:
        try:
            page.remove_rotation()
        except Exception:
            pass
    return direcao_dominante(page)


def desrotacionar(words: list, direcao: tuple[int, int]) -> list:
    """Gira as coordenadas das palavras para o referencial de LEITURA."""
    f = _EIXOS.get(direcao)
    if f is None:
        return words
    out = []
    for w in words:
        ax, ay = f(w[0], w[1])
        bx, by = f(w[2], w[3])
        # renormaliza o bbox: a rotação troca qual canto é o mínimo
        out.append((min(ax, bx), min(ay, by), max(ax, bx), max(ay, by), *w[4:]))
    return out


def texto_pagina(page, direcao: tuple[int, int] | None = None) -> str:
    """Texto da página em ordem de LEITURA, corrigindo texto girado 90°."""
    if direcao is None:
        direcao = normalizar_pagina(page)
    if direcao not in _EIXOS:
        return page.get_text() or ""
    palavras = desrotacionar(page.get_text("words"), direcao)
    if not palavras:
        return ""
    # tolerância vertical proporcional à altura da fonte: fixá-la em pt quebraria
    # em planilha de corpo 6 (junta linhas) e em título de corpo 20 (separa uma só)
    alturas = sorted(p[3] - p[1] for p in palavras)
    tol = max(2.0, alturas[len(alturas) // 2] * 0.5)
    linhas: list[tuple[float, list]] = []
    for p in sorted(palavras, key=lambda p: ((p[1] + p[3]) / 2, p[0])):
        centro = (p[1] + p[3]) / 2
        if linhas and abs(linhas[-1][0] - centro) <= tol:
            linhas[-1][1].append(p)
        else:
            linhas.append((centro, [p]))
    return "\n".join(
        " ".join(p[4] for p in sorted(ws, key=lambda p: p[0])) for _, ws in linhas
    )


def clusterizar_tabela(page, gap: float = GAP_COLUNA, tol: float = TOL_LINHA,
                       direcao: tuple[int, int] | None = None) -> list[list[str]]:
    """Reconstrói a tabela por GEOMETRIA (pura aritmética sobre coordenadas).

    Numa tabela, valores da mesma COLUNA compartilham x; da mesma LINHA, y.
    Agrupa por vão: ordena os x e corta onde houver espaço > `gap`.
    O texto de cada célula é o do PDF — nada é predito.

    Em página girada os eixos são desrotacionados ANTES de tudo (ver `_EIXOS`
    acima) — senão linha e coluna entram trocadas. `direcao` é opcional só para
    o chamador que já a calculou não pagar duas vezes pelo `get_text("dict")`.
    """
    if direcao is None:
        direcao = normalizar_pagina(page)
    words = page.get_text("words")  # (x0,y0,x1,y1,palavra,bloco,linha,n)
    if direcao in _EIXOS:
        words = desrotacionar(words, direcao)
    numericas = [w for w in words if VALOR.fullmatch(w[4] or "")]
    if len(numericas) < 3:
        return []

    # COLUNAS: 1-D clustering das bordas esquerdas
    xs = sorted(w[0] for w in numericas)
    grupos, atual = [], [xs[0]]
    for x in xs[1:]:
        if x - atual[-1] > gap:
            grupos.append(atual)
            atual = [x]
        else:
            atual.append(x)
    grupos.append(atual)
    centros = [sum(g) / len(g) for g in grupos]

    # LINHAS: agrupa por y-centro. Usa TODAS as palavras (não só números) para o
    # rótulo da linha (data/competência) viajar junto com os valores.
    linhas: dict[float, list] = {}
    for w in words:
        yc = (w[1] + w[3]) / 2
        chave = next((k for k in linhas if abs(k - yc) <= tol), None)
        linhas.setdefault(chave if chave is not None else yc, []).append(w)

    tabela = []
    for _, ws in sorted(linhas.items()):
        if not any(VALOR.fullmatch(w[4] or "") for w in ws):
            continue  # linha sem valor: não é linha de dado da tabela
        row = [""] * (len(centros) + 1)  # col 0 = rótulo (texto à esquerda)
        for w in sorted(ws, key=lambda w: w[0]):
            if VALOR.fullmatch(w[4] or ""):
                ci = min(range(len(centros)), key=lambda i: abs(centros[i] - w[0])) + 1
            else:
                ci = 0
            row[ci] = (row[ci] + " " + w[4]).strip()
        tabela.append(row)
    return tabela


def identidade_colunar(tabela: list[list[str]], tol: float = 0.01) -> dict:
    """ORÁCULO ARITMÉTICO: existe triple de colunas com col_i + col_j ≈ col_k?

    É a verificação que NÃO depende de modelo nenhum — a redundância do próprio
    domínio (Principal + Juros = Total). Devolve a melhor identidade e em quantas
    linhas ela vale. `linhas_ok/linhas` alto = reconstrução coerente.
    """
    mat = []
    for row in tabela:
        vals = [num(c) if VALOR.fullmatch((c or "").strip()) else None for c in row]
        if sum(1 for v in vals if v) >= 3:
            mat.append(vals)
    if not mat:
        return {"identidade": None, "linhas_ok": 0, "linhas": 0, "razao": 0.0}
    ncol = max(len(r) for r in mat)
    votos: dict[tuple, int] = {}
    for r in mat:
        r = r + [None] * (ncol - len(r))
        idx = [i for i in range(ncol) if r[i] is not None]
        # pares (Principal + Juros = Total) E trios (Principal + Juros + Selic =
        # Total) — a conta do Projef costuma ter 3 parcelas; testar só par
        # subestimava (NEUZA p581 dava 2/4 com a identidade de 3 termos presente).
        for n in (2, 3):
            if len(idx) < n + 1:
                continue
            for combo in _combinacoes(idx, n):
                s = sum(r[i] for i in combo)
                for k in idx:
                    if k in combo:
                        continue
                    if abs(r[k] - s) <= max(abs(r[k]), 1e-9) * tol:
                        votos[tuple(combo) + (k,)] = votos.get(tuple(combo) + (k,), 0) + 1
    if not votos:
        return {"identidade": None, "linhas_ok": 0, "linhas": len(mat), "razao": 0.0}
    # desempate: mais linhas cobertas; empate → identidade com MAIS parcelas
    # (3 termos é mais específica/informativa que 2, menos chance de coincidência)
    melhor = max(votos.items(), key=lambda kv: (kv[1], len(kv[0])))
    parcelas, total = list(melhor[0][:-1]), melhor[0][-1]
    return {
        "identidade": {"parcelas": parcelas, "col_total": total},
        "linhas_ok": melhor[1], "linhas": len(mat),
        "razao": melhor[1] / len(mat),
    }


def firewall_cobertura(texto: str, tabela: list[list[str]]) -> dict:
    """Todo valor do texto TEM que aparecer numa célula. Residual = valor SEM
    coluna atribuída → ressalva (nunca aceite silencioso)."""
    todos = set(VALOR.findall(texto or ""))
    em_celula = set()
    for row in tabela:
        for cel in row:
            em_celula.update(VALOR.findall(cel or ""))
    orfaos = todos - em_celula
    return {
        "total": len(todos), "cobertos": len(todos & em_celula),
        "orfaos": sorted(orfaos)[:20],
        "cobertura": (len(todos & em_celula) / len(todos)) if todos else 1.0,
    }


def processar_pdf(pdf_path: str, ocr_fn=None, so_paginas: list[int] | None = None) -> list[dict]:
    """Substrato de todas as páginas (ou só `so_paginas`, 1-indexed).

    `ocr_fn(page)->str` é injetado (DeepSeek-OCR self-hosted ou Gemini) e só é
    chamado em página ESCANEADA — página nativa nunca paga OCR.
    """
    # aceita caminho OU bytes (a UI passa os bytes do upload direto)
    if isinstance(pdf_path, (bytes, bytearray)):
        doc = fitz.open(stream=bytes(pdf_path), filetype="pdf")
    else:
        doc = fitz.open(pdf_path)
    out = []
    for i in range(doc.page_count):
        pg_num = i + 1
        if so_paginas and pg_num not in so_paginas:
            continue
        page = doc[i]
        # UMA vez por página: desfaz rotação de página e mede a direção residual
        # do texto. Passada adiante para o texto e a tabela não recalcularem.
        direcao = normalizar_pagina(page)
        nativa = eh_nativa(page)
        if nativa:
            texto = texto_pagina(page, direcao)
            tabela = clusterizar_tabela(page, direcao=direcao)
        else:
            texto = ocr_fn(page) if ocr_fn else ""
            tabela = []  # escaneada: estrutura vem do próprio OCR (markdown do VLM)
        out.append({
            "pagina": pg_num, "nativa": nativa, "texto": texto, "tabela": tabela,
            "valores": VALOR.findall(texto or ""),
            "oraculo": identidade_colunar(tabela) if tabela else None,
            "cobertura": firewall_cobertura(texto, tabela) if tabela else None,
        })
    doc.close()
    return out
