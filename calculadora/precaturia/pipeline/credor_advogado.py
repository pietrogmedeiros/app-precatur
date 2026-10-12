"""Detecção determinística de RPV cujo credor é o ADVOGADO (não o exequente).

Safety-net da regra 8 (CLAUDE.md): em casos multi-ofício, a etapa 5 (LLM) às
vezes classifica `beneficiario_tipo='exequente'` com confiança 1.0 para um
requisitório que, na verdade, é a RPV de honorários do ADVOGADO — caso CASO
(RPV 16/2026 em favor de CASO, o procurador). Isso fere a regra 8: a
sucumbência/honorário do advogado entraria no agregado "recebível pelo
exequente".

**Sinal determinístico (alta precisão, in-document):** no formato de RPV do
PJe estadual (TJMG/TJES) cada requisitório lista::

    Credores da RPV:
    Nome:   <CREDOR>
    ...
    Dados do procurador do credor:
    Nome:   <PROCURADOR (advogado, com OAB)>

Quando o **credor de uma RPV é o procurador (advogado) nomeado em OUTRA RPV do
mesmo caso**, essa RPV é o requisitório de honorários do advogado → não é
crédito do exequente. É o caso CASO: pp247 tem credor=CASO, que é o
procurador da pp246.

**Por que é seguro (não regride):** o sinal só dispara nesse formato específico
de RPV estadual. Requisitórios do exequente que apenas *mencionam* honorários no
corpo (despacho de expedição eproc — CASO pp405; homologação TJMG — CASO
pp45) NÃO têm os campos `Credores da RPV`/`procurador do credor` parseáveis, então
não disparam (validado nos 4 casos-âncora). Diferente de heurística por marcador
de texto ("sucumbência"/"honorários"), que daria falso-positivo nesses.
"""

import re
import unicodedata
from decimal import Decimal


# `Credores da RPV: ... Nome: <CREDOR>` e `procurador do credor: ... Nome: <PROC>`.
# O nome vem após "Nome:" separado por tab/espaço, na mesma linha lógica, até a
# próxima tabulação/quebra (o campo seguinte — CPF/OAB — vem após \t ou \n).
_CREDOR_RPV_RE = re.compile(
    r"Credor(?:es)?\s+da\s+RPV\s*:\s*Nome\s*:\s*([^\n\t]+)", re.IGNORECASE
)
_PROCURADOR_RE = re.compile(
    r"procurador\s+do\s+credor\s*:\s*Nome\s*:\s*([^\n\t]+)", re.IGNORECASE
)
# Placeholder do PJe quando o campo não foi preenchido.
_NAO_CADASTRADO_RE = re.compile(
    r"(N[ÃA]O|INFORMA[ÇC][ÃA]O).*CADASTRAD|^-{2,}", re.IGNORECASE
)

# Formato FEDERAL (TRF/PJe-1G): "Requerente / Credor :  NOME" e
# "Advogado / OAB:  NOME  CÓDIGO". Sem o cabeçalho "Credores da RPV / Nome:".
# `(?<!do\s)` evita casar "procurador DO CREDOR:" (form estadual); `[ \t]*` (não
# `\s*`) impede cruzar a quebra de linha e capturar o "Nome:" da linha seguinte.
_CREDOR_FEDERAL_RE = re.compile(
    r"(?:Requerente\s*/\s*)?(?<!do\s)Credor\s*:[ \t]*([^\n]+)", re.IGNORECASE
)
# Marcador de SOCIEDADE DE ADVOCACIA no nome do credor — quando a própria RPV é
# em favor da banca (honorários), o credor é "X ADVOCACIA"/"SOCIEDADE ... DE
# ADVOGADOS" (caso CASO: "CASO"). Sinal forte de honorários.
_SOCIEDADE_ADVOCACIA_RE = re.compile(
    r"\bADVOCACIA\b|SOCIEDADE\s+(?:INDIVIDUAL\s+)?DE\s+ADVOGAD"
    r"|ESCRIT[ÓO]RIO\s+DE\s+ADVOC",
    re.IGNORECASE,
)
# Sinal (3), in-document: o PRÓPRIO cabeçalho do requisitório federal declara que
# ELE é a RPV/precatório de honorários SUCUMBENCIAIS do advogado. Aplicados sobre
# texto SEM acento (`_sem_acentos`), tolerando o ruído de OCR ("Naureza"). Exigem
# o RÓTULO de campo do formulário — nunca o termo solto — para não falsar despacho
# que só MENCIONA honorários no corpo (CASO/CASO). Restritos a SUCUMBENCIAIS
# (do advogado por art. 23 Lei 8.906); honorário CONTRATUAL pode ser do exequente,
# então fica fora. Caso CASO cb27c844 (credor = advogado pessoa física, que
# os sinais 1/2 não pegam).
_TIPO_REQ_HONORARIOS_RE = re.compile(
    r"Tipo\s+de\s+Requisicao\s*:?[ \t]{0,4}Hon(?:\.|orarios?)?\s*Sucumben",
    re.IGNORECASE,
)
_NATUREZA_HONORARIOS_RE = re.compile(
    r"Nat?ureza\s+da\s+Obrigacao[^\n]{0,40}?"
    r"(?:08\.01\.14\.91|Honorarios?\s+Advocaticios[^\n]{0,20}?Sucumbenc)",
    re.IGNORECASE,
)
# Sinal (4), in-document — formulário de expedição de precatório do PJe estadual
# (TJES/TJBA): o ofício é o requisitório de HONORÁRIOS do ADVOGADO quando (a) o
# cabeçalho declara "FORMULÁRIO DE HONORÁRIOS SUCUMBENCIAIS", ou (b) o campo de
# BENEFICIÁRIO é "ADVOGADO(A) CREDOR(A)" (em vez de "PARTE CREDORA"). Caso CASO:
# Ofício 2846 (honorários do advogado Juraci) tem ambos; o Ofício 2845 da viúva tem
# "5. PARTE CREDORA (BENEFICIÁRIO)" e o advogado num campo "6. ADVOGADO(A)" separado
# — logo NÃO dispara. Aplicados sobre texto sem acento (`_sem_acentos`).
_FORMULARIO_HON_SUCUMB_RE = re.compile(
    r"FORMULARIO\s+DE\s+HONORARIOS\s+SUCUMBENC", re.IGNORECASE
)
_ADVOGADO_CREDOR_BENEF_RE = re.compile(
    r"ADVOGAD[OA]\s*\(?\s*A?\s*\)?\s*CREDOR", re.IGNORECASE
)
# Número da requisição no cabeçalho do requisitório (identidade do precatório/RPV):
# TRF1 "Precatório (297-2025 ...)" / "Requisição de Pequeno Valor (298-2025 ...)";
# estadual "RPV 15/2026" / "Precatório nº 15/2026".
_NUM_REQUISICAO_RE = re.compile(
    r"(?:Precat[óo]rio|Requisi[çc][ãa]o\s+de\s+Pequeno\s+Valor|RPV)\s*"
    r"(?:n?[º°]?\.?\s*|\(\s*)(\d{1,4}[-/]\d{4})",
    re.IGNORECASE,
)


# Documento-RESUMO de requisição (NÃO um crédito próprio): "Certidão de
# Conferência de Ofício de Requisição", "Demonstrativo de Cálculo/Requisição",
# "Prévia de Cálculo/Ofício Requisitório". Casa sobre texto SEM acento. NÃO casa
# "conta de liquidação" (essa é a conta da etapa 8, tipo='calculo'). Sinal usado
# pela 4ª passada de dedup (F3) para colapsar a conferência contra suas parcelas.
_CONFERENCIA_RE = re.compile(
    r"certid[ãa]o\s+de\s+confer[êe]ncia"
    r"|confer[êe]ncia\s+de\s+(?:of[íi]cio|valores|requisi)"
    # "demonstrativo/prévia DE CÁLCULO" sozinho é genérico (aparece em ofício
    # legítimo) — exige contexto de REQUISIÇÃO/conferência para não dar FP no gate 1.
    r"|demonstrativo\s+de\s+(?:requisi|confer)"
    r"|pr[ée]via\s+de\s+(?:requisi|of[íi]cio)",
    re.IGNORECASE,
)


def _sem_acentos(s: str) -> str:
    """Remove diacríticos preservando quebras de linha e caixa — para casar
    rótulos de campo do requisitório sobre texto com ruído de OCR/acentuação."""
    s = unicodedata.normalize("NFKD", s or "")
    return "".join(c for c in s if not unicodedata.combining(c))


def e_certidao_conferencia(texto: str) -> bool:
    """`True` se o texto do ofício é uma CERTIDÃO DE CONFERÊNCIA / demonstrativo /
    prévia de requisição — documento-resumo cujo valor de face costuma ser a SOMA
    das parcelas (precatório fracionado). Sinal textual (1 de 2 gates) do dedup F3;
    a absorção só ocorre quando a face também bate com a soma das parcelas."""
    return bool(_CONFERENCIA_RE.search(_sem_acentos(texto or "")))


def _normalizar_nome(s: str) -> str:
    """Minúsculas→MAIÚSCULAS, sem acento, espaços colapsados, pontuação de fim.

    Remove o sufixo "E OUTRO(A)/E OUTROS" (litisconsórcio) para não poluir o
    nome do credor exibido nem a comparação credor×procurador.
    """
    s = unicodedata.normalize("NFKD", s or "")
    s = "".join(c for c in s if not unicodedata.combining(c))
    s = re.sub(r"\s+", " ", s).strip().upper().rstrip(".,;:")
    return re.sub(r"\s+E\s+OUTRO(?:S|\(A\)|\(S\))?\.?$", "", s).strip()


# Conectivos/tokens curtos ignorados na comparação de nomes ("DE OLIVEIRA E
# SILVA" → {OLIVEIRA, SILVA}). Evita que preposições contem como sobrenome.
_NOME_STOPWORDS = {"DE", "DA", "DO", "DAS", "DOS", "E"}


def _tokens_nome(nome: str) -> set[str]:
    """Tokens significativos (≥3 letras, sem conectivos) do nome normalizado."""
    return {
        t
        for t in _normalizar_nome(nome).split()
        if len(t) >= 3 and t not in _NOME_STOPWORDS
    }


def nomes_compativeis(a: str, b: str) -> bool:
    """`True` se `a` e `b` podem ser a MESMA pessoa: os tokens significativos de
    um são subconjunto dos do outro (nome parcial/abreviado — "CASO" ⊆
    "CASO"; "CASO" vs "CASO
    FERREIRA OUVERNEY" → só "FERREIRA" em comum → `False`). Qualquer lado sem
    token significativo → `False` (sem sinal — não afirma compatibilidade).

    Lenitente de propósito (subset, não igualdade): usado só para SINALIZAR
    divergência de credor (warning), onde sub-avisar é o lado conservador."""
    ta, tb = _tokens_nome(a), _tokens_nome(b)
    if not ta or not tb:
        return False
    menor, maior = (ta, tb) if len(ta) <= len(tb) else (tb, ta)
    return menor <= maior


# G2/G1: razão relativa máxima entre 2 requisições do MESMO crédito (mesmo
# credor+natureza+data_base) para tratá-las como RE-EXPEDIÇÃO do mesmo precatório
# (valor deriva pouco entre emissões), não frações distintas. Δ ≤ 5% = quase igual.
REEXPEDICAO_TOLERANCIA = Decimal("0.05")


def primeiro_par_quase_igual(
    valores: list[Decimal],
) -> tuple[Decimal, Decimal] | None:
    """Menor par de valores cuja diferença relativa é ≤ `REEXPEDICAO_TOLERANCIA`
    — sinal de RE-EXPEDIÇÃO do mesmo crédito (CASO: 126.962,70 ≈ 127.104,04).
    `None` se nenhum par próximo (fração legítima — CASO 75k vs 18k). Ordena e
    compara adjacentes: se existe par próximo, dois adjacentes ordenados o são."""
    vs = sorted(v for v in valores if v is not None)
    for i in range(len(vs) - 1):
        maior = vs[i + 1]
        if maior > 0 and (maior - vs[i]) <= maior * REEXPEDICAO_TOLERANCIA:
            return (vs[i], maior)
    return None


def _extrair(rx: re.Pattern[str], texto: str) -> set[str]:
    nomes: set[str] = set()
    for bruto in rx.findall(texto or ""):
        nome = _normalizar_nome(bruto)
        if nome and not _NAO_CADASTRADO_RE.search(nome):
            nomes.add(nome)
    return nomes


def extrair_credores(texto: str) -> set[str]:
    """Nomes do(s) credor(es) do requisitório — form estadual ("Credores da RPV:
    Nome:") OU federal ("Credor :"). Vazio se ausente."""
    return _extrair(_CREDOR_RPV_RE, texto) | _extrair(_CREDOR_FEDERAL_RE, texto)


def extrair_procuradores(texto: str) -> set[str]:
    """Nomes do(s) procurador(es) (advogado) da RPV (form estadual). Vazio se ausente."""
    return _extrair(_PROCURADOR_RE, texto)


def extrair_numero_requisicao(texto: str) -> str | None:
    """Número da requisição (precatório/RPV) para deduplicar requisitórios
    re-juntados — o MESMO precatório (ex.: "297-2025") aparece em 2 documentos
    com `Documento id` diferente. Normaliza separador para "-". None se ausente."""
    m = _NUM_REQUISICAO_RE.search(texto or "")
    return m.group(1).replace("/", "-") if m else None


def detectar_oficios_honorarios_in_document(textos_por_id: dict[str, str]) -> set[str]:
    """IDs dos ofícios cujo PRÓPRIO cabeçalho/campos declaram que o crédito é de
    honorários do ADVOGADO (sinais 3 e 4, in-document).

    Sinal 4 (PJe estadual TJES/TJBA): cabeçalho "FORMULÁRIO DE HONORÁRIOS
    SUCUMBENCIAIS" ou campo de beneficiário "ADVOGADO(A) CREDOR(A)" — caso CASO.

    Diferente dos sinais 1/2 (que olham o NOME do credor/procurador), este lê o
    RÓTULO de campo do requisitório federal TRF1 — "Tipo de Requisição: Hon.
    Sucumbenciais" ou "Natureza da Obrigação (Assunto): (08.01.14.91) HONORÁRIOS
    ADVOCATÍCIOS - SUCUMBÊNCIA". Pega o caso CASO cb27c844, onde o credor é o
    advogado pessoa física (Diego Saba) e nenhum dos sinais 1/2 dispara. Aplica
    sobre texto sem acento (tolera OCR "Naureza"). Conservador: exige o rótulo de
    campo (não o termo solto, que falsaria CASO/CASO) e restringe a
    SUCUMBENCIAIS (honorário contratual pode ser do exequente).
    """
    ids: set[str] = set()
    for did, texto in textos_por_id.items():
        t = _sem_acentos(texto or "")
        if (
            _TIPO_REQ_HONORARIOS_RE.search(t)
            or _NATUREZA_HONORARIOS_RE.search(t)
            or _FORMULARIO_HON_SUCUMB_RE.search(t)
            or _ADVOGADO_CREDOR_BENEF_RE.search(t)
        ):
            ids.add(did)
    return ids


def detectar_oficios_advogado(textos_por_id: dict[str, str]) -> set[str]:
    """IDs dos ofícios cujo credor é, na verdade, o ADVOGADO (honorários).

    Três sinais determinísticos de alta precisão:
    (1) o credor da RPV é o **procurador nomeado em OUTRO ofício** do caso (form
        estadual; caso CASO pp247 = procurador da pp246);
    (2) o próprio credor é uma **sociedade de advocacia** — "X ADVOCACIA",
        "SOCIEDADE ... DE ADVOGADOS" (caso CASO federal: "CASO");
    (3) o PRÓPRIO cabeçalho do ofício declara honorários sucumbenciais (federal
        TRF1; caso CASO cb27c844 — advogado pessoa física, que (1)/(2) não
        pegam). Ver `detectar_oficios_honorarios_in_document`.
    Conservador (exige `other != did` no sinal 1). Formatos sem credor parseável
    não disparam nos sinais 1/2; o sinal 3 exige rótulo de campo do requisitório.
    """
    credores = {did: extrair_credores(t) for did, t in textos_por_id.items()}
    procuradores = {did: extrair_procuradores(t) for did, t in textos_por_id.items()}

    advogado: set[str] = set()
    for did, creds in credores.items():
        if not creds:
            continue
        # (2) credor é sociedade de advocacia
        if any(_SOCIEDADE_ADVOCACIA_RE.search(c) for c in creds):
            advogado.add(did)
            continue
        # (1) credor == procurador de OUTRO ofício
        outros_procuradores: set[str] = set()
        for outro, procs in procuradores.items():
            if outro != did:
                outros_procuradores |= procs
        if creds & outros_procuradores:
            advogado.add(did)
    # (3) sinal in-document (independe de credor parseável) — união por id.
    advogado |= detectar_oficios_honorarios_in_document(textos_por_id)
    return advogado
