"""Orquestrador do pré-preenchimento: PDF do processo → campos da calculadora.

Dois modos, mesma máquina:

  AUTÔNOMO  (`preencher`): substrato → homologação(regex) → radar → juiz(LLM
            escolhe conta+ofício) → extração → prova. É o expander "Anexar
            processo" do formulário.

  ASSISTIDO (`analisar` + `extrair_cortes`): o HUMANO fica no loop do corte.
            `analisar` roda só a parte determinística (substrato + radar +
            homologação, ZERO LLM) e devolve as faixas SUGERIDAS já rotuladas;
            o advogado confirma/ajusta/rotula; `extrair_cortes` extrai dos cortes
            confirmados. É o "assistente de corte" (M1).

Ambos convergem em `_montar_resultado`, que preenche as seções 1 (conta), 3
(natureza/PSS/IR), 4 (honorários) e 5 (precatório/graça). Saída: {ok, campos,
query, citacoes, prova, ...}. `query` = params que o `Calculadora.py` JÁ
consome. `citacoes` = {pagina: [valores]} para o visualizador.

100% self-contained: fitz + numpy + httpx. Sem backend, sem torch, sem Google.
"""
from __future__ import annotations

import re
import sys
from datetime import date

from . import radar as R
from .apresentacao import extrair_data_envio_tribunal
from .deterministico import honorarios as _det_honorarios
from .deterministico import numero_cnj as _det_cnj
from .deterministico import valor_presente
from .extracao import extrair, extrair_natureza, extrair_oficio
from .homologacao import achar_homologacao
from . import ocr as _ocr
from . import marcadores as _M
from . import pje as _pje
from .llm import LLM, salvage_json
from .substrato import MIN_TEXTO_NATIVO, processar_pdf

# campo extraído → param que a calculadora consome
MAPA_PARAM = {
    "valor_total": "vt", "valor_principal": "vp", "valor_juros": "vj", "valor_selic": "vs",
    "valor_pss": "valor_pss", "valor_ir": "valor_ir",
    "honorarios_contratuais_pct": "hc", "honorarios_sucumbenciais_pct": "hs",
    "natureza_tributaria": "natureza", "modalidade": "modalidade",
    "data_calculo": "data_calculo",
}
TOL_PROVA = 0.01

# sentinela: distingue "não passei ocr_fn" de "passei None de propósito"
_PADRAO = object()

# Rótulos das faixas do assistente. São o vocabulário fechado que o `data_editor`
# oferece e que `extrair_cortes` roteia (conta → extrair; ofício → extrair_oficio).
TIPO_CONTA = "Conta homologada"
TIPO_OFICIO = "Ofício requisitório"
TIPO_SENTENCA = "Sentença / acórdão"
TIPO_OUTRO = "Outro / não usar"
TIPOS = [TIPO_CONTA, TIPO_OFICIO, TIPO_OUTRO]

# Sinais para SUGERIR o rótulo da faixa (o humano corrige). Precisam DISTINGUIR
# conta de ofício — por isso NÃO reuso `radar._FORTE`/`radar.parece_conta`, que
# tratam "requisição de pagamento" como sinal de conta (é recall do radar, amplo
# de propósito) e rotulariam todo ofício como conta. O catálogo, com o papel de
# cada marcador e a medição que o justifica, está em `marcadores`.


# ente extraído (texto livre) → opção EXATA da calculadora (senão o advogado digita)
_ENTE_KNOWN = [
    ("uniao", "União"), ("união", "União"), ("fazenda nacional", "União"),
    ("inss", "INSS"), ("seguro social", "INSS"),
    ("espírito santo", "Estado do Espírito Santo"), ("espirito santo", "Estado do Espírito Santo"),
    ("rio de janeiro", "Estado do Rio de Janeiro"), ("minas gerais", "Estado de Minas Gerais"),
    ("bahia", "Estado da Bahia"), ("goiás", "Estado de Goiás"), ("goias", "Estado de Goiás"),
    ("mato grosso", "Estado de Mato Grosso"), ("são paulo", "Estado de São Paulo"),
    # ⚠ ORDEM IMPORTA: "alagoas previdência" CONTÉM "alagoas". O laço devolve a
    # primeira chave que casa, então a autarquia tem de vir ANTES do estado —
    # invertido, todo precatório da Alagoas Previdência viraria "Estado de Alagoas".
    ("alagoas previdência", "Alagoas Previdência"), ("alagoas previdencia", "Alagoas Previdência"),
    ("alagoas", "Estado de Alagoas"),
    # ⚠ só o PREFIXO: o _qp_index da calc casa por `opcao.split(" — ")[0]`, então
    # devolver o rótulo inteiro "IPAJM — Instituto…" nunca casaria (cairia em "não
    # informar"). IPAJM é a única opção com " — " no rótulo.
    ("ipajm", "IPAJM"),
    ("rio previdência", "Rio Previdência (RJ)"), ("rio previdencia", "Rio Previdência (RJ)"),
]


# ⚠ tem de casar LETRA A LETRA com a opção do `_ENTE_OPCOES` do Calculadora.py:
# o `_qp_index` compara a string inteira (não há " — " nesta opção para cortar).
ENTE_OUTRO = "Outro (digitar abaixo)"


def _norm_ente(raw: str | None) -> str | None:
    if not raw:
        return None
    low = raw.lower()
    for chave, opcao in _ENTE_KNOWN:
        if chave in low:
            return opcao
    return None  # desconhecido → deixa o advogado escolher "Outro"


PROMPT_SEL = """Você recebe TRECHOS candidatos de um processo de precatório brasileiro. Aponte:
(a) a CONTA DE LIQUIDAÇÃO HOMOLOGADA — a conta de cálculo (Principal, Juros, Selic, Total) que
    serve de base ao requisitório (versão FINAL/operativa, não rascunho nem listagem mês a mês,
    trazendo o TOTAL da execução);
(b) o OFÍCIO REQUISITÓRIO / requisição de pagamento (precatório ou RPV) — a peça que requisita
    o pagamento, com beneficiário, valor e honorários. Se não houver, use null.

{dica}

Responda SOMENTE com JSON:
{{"conta_ref":"ppA-B","oficio_ref":"ppC-D ou null","valor_total_conta":"...","citacao_trecho":"..."}}

TRECHOS:

"""


def _bloco(paginas, a, b):
    idx = {p["pagina"]: p for p in paginas}
    out = [f"=== TRECHO pp{a}-{b} ==="]
    for pg in range(a, b + 1):
        p = idx.get(pg)
        if not p:
            continue
        t = re.sub(r"\s+", " ", p.get("texto") or "")
        if len(t) > 2600:
            t = t[:1200] + " [...] " + t[-1400:]
        out.append(f"[pág {pg}] {t}")
        orc = p.get("oraculo") or {}
        if orc.get("identidade") and orc.get("linhas_ok", 0) >= 2:
            out.append(f"[pág {pg} · prova: parcelas somam o total em "
                       f"{orc['linhas_ok']}/{orc['linhas']} linhas]")
    return "\n".join(out)


def _pdec(x):
    if x is None:
        return None
    if isinstance(x, str):
        x = x.replace("R$", "").strip().replace(".", "").replace(",", ".")
    try:
        return float(x)
    except (ValueError, TypeError):
        return None


def _ref(s):
    m = re.match(r"pp(\d+)-(\d+)", (s or "").strip())
    return (int(m.group(1)), int(m.group(2))) if m else None


def _prova(campos: dict) -> dict:
    def g(k):
        return _pdec((campos.get(k) or {}).get("valor"))
    p, j, s, t = g("valor_principal"), g("valor_juros") or 0.0, g("valor_selic") or 0.0, g("valor_total")
    if p is None or not t:
        return {"ok": None, "motivo": "principal/total ausentes"}
    dif = abs((p + j + s) - t)
    return {"ok": dif <= t * TOL_PROVA, "soma": round(p + j + s, 2), "total": t,
            "dif_pct": round(dif / t * 100, 2) if t else None}


def _escolher(paginas, runs, homol, llm):
    if not runs:
        return None, None
    if homol:
        ev = f" (Evento {homol['evento']})" if homol.get("evento") else ""
        dica = (f"PISTA: ato judicial na pág {homol['pagina']} HOMOLOGA os cálculos{ev}: "
                f"\"{homol['trecho']}\". A conta homologada corresponde a esse cálculo.")
    else:
        dica = "Nenhum ato explícito de homologação localizado; use o julgamento."
    prompt = PROMPT_SEL.format(dica=dica) + "\n\n".join(_bloco(paginas, a, b) for a, b in runs)
    txt, _ = llm.responder(prompt)
    sel = salvage_json(txt) or {}
    return _ref(sel.get("conta_ref")), _ref(sel.get("oficio_ref"))


def montar_query(campos: dict, data_apres: date | None) -> dict:
    q = {}
    for campo, param in MAPA_PARAM.items():
        v = (campos.get(campo) or {}).get("valor")
        if v not in (None, "", "null"):
            q[param] = str(v)
    # Ente devedor. A lista da calculadora tem ~12 opções e o corpus vem de
    # tribunais do país inteiro — "Estado de Pernambuco" (caso 1653) não estava
    # lá e o campo ficava VAZIO, mesmo com o ofício declarando o ente. Fora da
    # lista agora cai em "Outro" + texto livre, que também cobre municípios e
    # autarquias (a cauda é infinita). A esfera continua saindo de graça: o
    # seletor da calculadora deduz federal/estadual do NOME do ente.
    ente_raw = (campos.get("ente_devedor") or {}).get("valor")
    ente = _norm_ente(ente_raw)
    if ente:
        q["ente"] = ente
    elif ente_raw:
        q["ente"] = ENTE_OUTRO
        q["ente_outro"] = str(ente_raw).strip()
    if data_apres:
        q["data_apres"] = data_apres.isoformat()
    # "Referência do caso" da calc (rótulo do memorial + nome do PDF):
    # beneficiário + número do precatório, o par que identifica o caso para
    # quem lê o memorial depois (o advogado edita à vontade).
    _partes = [(campos.get(k) or {}).get("valor") for k in ("beneficiario", "numero_precatorio")]
    ref = " — ".join(str(p).strip() for p in _partes if p not in (None, ""))
    if ref:
        q["ref"] = ref
    # PASSAGEM, não campos do formulário: a calculadora não renderiza os números
    # do precatório e do ofício, só os carrega para quem escreve no CRM — onde
    # cada um tem campo próprio.
    for campo in ("numero_precatorio", "numero_oficio"):
        v = (campos.get(campo) or {}).get("valor")
        if v:
            q[campo] = str(v).strip()
    return q


# ── Rotulagem das faixas sugeridas pelo radar (SUGERE, não decide) ─────────
def _label_pagina(p: dict, pg: int, homol: dict | None) -> str | None:
    """Rótulo de UMA página: conta, ofício ou None (indefinido).

    O ofício que o catálogo afirma (forte, rótulo do sistema ou formulário que
    CITA a conta) vem primeiro: o formulário diz "conforme conta de
    liquidação" e a tabela dele FECHA (principal + juros = bruto), então
    cabeçalho e oráculo o rotulavam como conta — 86 páginas de ofício nos
    anexos do Bitrix (28/10/2026). Depois, conta: pelo catálogo (que já tira a
    conta só citada numa decisão), pela página da homologação ou pela tabela
    que fecha — esta ganha de ofício fraco, para não perder a conta OBRIGATÓRIA."""
    cls = _M.classificar(p.get("texto") or "")
    if cls["tipo"] == _M.OFICIO and cls["nivel"] in ("forte", "rotulo_sistema", "citacao"):
        return TIPO_OFICIO
    orc = p.get("oraculo") or {}
    if (cls["tipo"] == _M.CONTA or (homol and homol.get("pagina") == pg)
            or (orc.get("razao", 0) or 0) >= 0.5):
        return TIPO_CONTA
    return {_M.OFICIO: TIPO_OFICIO}.get(cls["tipo"])


def _rotular_run(paginas: list[dict], a: int, b: int, homol: dict | None) -> str:
    """Rótulo ÚNICO de uma faixa [a,b] (conta > ofício > outro). Mantido para o
    caminho homogêneo; runs MISTOS são divididos por `_sugerir_para_run`."""
    idx = {p["pagina"]: p for p in paginas}
    rotulos = [_label_pagina(idx[pg], pg, homol) for pg in range(a, b + 1) if pg in idx]
    if TIPO_CONTA in rotulos:
        return TIPO_CONTA
    if TIPO_OFICIO in rotulos:
        return TIPO_OFICIO
    return TIPO_OUTRO


def _sugerir_para_run(paginas: list[dict], a: int, b: int, homol: dict | None) -> list[dict]:
    """Uma faixa do radar pode conter conta E ofício (layout comum: conta seguida
    do ofício; ou o radar fundiu vizinhos porque "requisição de pagamento" também
    é sinal de conta no radar). Se houver conta E ofício em páginas DISTINTAS,
    divide em sub-cortes contíguos por rótulo — senão o ofício some e o corte da
    conta incha. Run homogêneo → 1 corte. O humano confirma/ajusta de qualquer forma.
    """
    idx = {p["pagina"]: p for p in paginas}
    pgs = [pg for pg in range(a, b + 1) if pg in idx]
    if not pgs:
        return [{"tipo": TIPO_OUTRO, "pagina_inicio": a, "pagina_fim": b}]
    rotulos = {pg: _label_pagina(idx[pg], pg, homol) for pg in pgs}
    tem_conta = TIPO_CONTA in rotulos.values()
    tem_oficio = TIPO_OFICIO in rotulos.values()
    if not (tem_conta and tem_oficio):
        return [{"tipo": _rotular_run(paginas, a, b, homol),
                 "pagina_inicio": a, "pagina_fim": b}]

    # run misto: forward-fill dos vazios (herdam a peça anterior), depois back-fill
    # das páginas antes do 1º rótulo, e agrupa páginas contíguas de mesmo rótulo.
    seq = [rotulos[pg] for pg in pgs]
    ult = None
    for i, v in enumerate(seq):
        ult = v if v is not None else ult
        seq[i] = ult
    prox = None
    for i in range(len(seq) - 1, -1, -1):
        if seq[i] is None:
            seq[i] = prox
        else:
            prox = seq[i]
    cortes, ini = [], 0
    for i in range(1, len(seq) + 1):
        if i == len(seq) or seq[i] != seq[ini]:
            cortes.append({"tipo": seq[ini] or TIPO_OUTRO,
                           "pagina_inicio": pgs[ini], "pagina_fim": pgs[i - 1]})
            ini = i
    return cortes


def _rotular_runs(paginas: list[dict], runs, homol: dict | None) -> list[dict]:
    out: list[dict] = []
    for a, b in runs:
        out.extend(_sugerir_para_run(paginas, a, b, homol))
    return out


def _cortes_com_pje(pj: dict | None, radar: list[dict]) -> list[dict]:
    """Cortes do PJe na frente; do radar, só o que não se sobrepõe a eles.

    O tipo que o PJe já localizou deixa de ser sugerido pelo radar (vira
    "Outro"): `extrair_cortes` usa o PRIMEIRO corte de cada tipo, e uma faixa
    do radar rotulada "conta" faria `multi_conta` disparar à toa. As faixas
    continuam na lista — o humano ainda pode reclassificar.
    """
    if not pj or not pj.get("cortes"):
        return radar
    achados = {c["tipo"] for c in pj["cortes"]}
    ocupadas = {pg for c in pj["cortes"] for pg in range(c["pagina_inicio"], c["pagina_fim"] + 1)}
    resto = []
    for c in radar:
        if any(pg in ocupadas for pg in range(c["pagina_inicio"], c["pagina_fim"] + 1)):
            continue
        resto.append({**c, "tipo": TIPO_OUTRO} if c["tipo"] in achados else c)
    return list(pj["cortes"]) + resto


def _pje_seguro(fonte, paginas) -> dict | None:
    """O nível 0 é melhoria: PDF fora do padrão não pode derrubar a análise."""
    try:
        return _pje.analisar(fonte, paginas)
    except Exception as e:  # noqa: BLE001
        print(f"[pje] {type(e).__name__}: {str(e)[:160]}", file=sys.stderr)
        return None


def analisar(pdf_path: str = None, pdf_bytes: bytes = None, ocr_fn=None) -> dict:
    """PASSO 1 do assistente de corte: substrato + radar + homologação. SEM LLM.

    Devolve as `paginas` (substrato, para reusar na extração sem reprocessar o PDF)
    e os `cortes_sugeridos` (faixas já rotuladas) para o humano confirmar/ajustar.
    Custo zero — a extração (LLM) só roda depois, sobre os cortes confirmados.
    """
    fonte = pdf_bytes if pdf_bytes is not None else pdf_path
    paginas = processar_pdf(fonte, ocr_fn=ocr_fn)
    textos = [p.get("texto") or "" for p in paginas]
    homol = achar_homologacao(textos)
    rad = R.buscar(paginas, None)
    pj = _pje_seguro(fonte, paginas)
    return {
        "paginas": paginas,
        "cortes_sugeridos": _cortes_com_pje(pj, _rotular_runs(paginas, rad["runs"], homol)),
        "pje": pj,
        "homologacao": homol,
        "n_paginas": len(paginas),
        "escaneadas": sum(1 for p in paginas if not p.get("nativa")),
        "radar": {"runs": rad["runs"], "scores": rad.get("scores"),
                  "canais": rad.get("canais")},
    }


def _termos(valor, trecho):
    """Termos a destacar no visualizador: o VALOR e as linhas do TRECHO literal
    (a citação é copiada da página → casa melhor que o valor normalizado). Data
    ISO ganha a variante BR (senão "2025-08-08" não bate com "08/08/2025")."""
    out = []
    v = str(valor)
    if len(v) >= 3:
        out.append(v)
    m = re.match(r"(\d{4})-(\d{2})-(\d{2})$", v)
    if m:
        out.append(f"{m.group(3)}/{m.group(2)}/{m.group(1)}")
    for linha in re.split(r"\n+", str(trecho or "")):
        linha = linha.strip()
        if len(linha) >= 4:
            out.append(linha)
    return out


# Campos de VALOR da conta: os únicos sujeitos à trava de presença literal. Os
# demais (percentuais, datas, natureza) não são número copiado de uma célula.
CAMPOS_DE_VALOR = ("valor_total", "valor_principal", "valor_juros", "valor_selic")


def _rejeitar_valores_ausentes(campos: dict, paginas: list[dict],
                               conta_ref: tuple[int, int]) -> list[dict]:
    """Tira de `campos` todo valor que NÃO existe literalmente na conta.

    É a trava da AGREGAÇÃO: o modelo soma duas células reais ("Total Partes"
    + "Total de Sucumbências") e devolve um número que não está no documento
    — com a citação reescrita expondo a soma e a prova P+J+S=T FECHANDO, porque
    as parcelas vêm todas somadas do mesmo jeito. Sem isto a tela dava "✅ A
    conta fecha" num valor inexistente, e era o advogado quem caçava.

    Anular (e não só marcar) é de propósito: um aviso ao lado de um número já
    preenchido e com selo verde é fácil de ignorar — foi exatamente o que
    aconteceu. O valor NÃO some: vai para a lista devolvida, com a citação, e a
    tela mostra os dois e oferece "usar mesmo assim".

    Escopo = só as páginas da CONTA, que é o que o extrator leu. O mesmo número
    no ofício não salva um valor que o modelo compôs.
    """
    a, b = conta_ref
    da_conta = [p for p in paginas if a <= p["pagina"] <= b]
    conta_por_ocr = any(not p.get("nativa") for p in da_conta)
    rejeitados = []
    for campo in CAMPOS_DE_VALOR:
        d = campos.get(campo)
        if not d or valor_presente(d.get("valor"), da_conta):
            continue
        campos.pop(campo)
        rejeitados.append({"campo": campo, "param": MAPA_PARAM[campo],
                           "valor": d.get("valor"), "citacao": d.get("citacao"),
                           "conta_por_ocr": conta_por_ocr})
    return rejeitados


def _montar_resultado(paginas: list[dict], conta_ref: tuple[int, int],
                      oficio_ref: tuple[int, int] | None, homol: dict | None,
                      llm: LLM, sentenca_ref: tuple[int, int] | None = None,
                      pje: dict | None = None) -> dict:
    """Extrai conta (obrigatória) + ofício (best-effort), aplica a rede
    determinística de honorários, calcula a prova e monta query + citações.
    Compartilhado pelos dois modos (autônomo e assistido)."""
    escaneadas = sum(1 for p in paginas if not p.get("nativa"))
    textos = [p.get("texto") or "" for p in paginas]

    # conta (seção 1 + natureza) — obrigatória
    ext = extrair(paginas, conta_ref, llm, pista=_pje.pista_conta(pje, conta_ref))
    if not ext.get("ok"):
        return {"ok": False, "erro": f"extração da conta: {ext.get('erro')}",
                "conta_ref": f"pp{conta_ref[0]}-{conta_ref[1]}", "homologacao": homol}
    campos = dict(ext["campos"])
    # ANTES de tudo que lê os valores (prova, query, citações): um valor que
    # não existe na conta não pode fechar a prova nem viajar para a calculadora.
    rejeitados = _rejeitar_valores_ausentes(campos, paginas, conta_ref)

    # ofício (seções 4 e 5) — best-effort, não derruba se faltar
    if oficio_ref:
        try:
            extof = extrair_oficio(paginas, oficio_ref, llm)
            if extof.get("ok"):
                for k, v in extof["campos"].items():
                    campos.setdefault(k, v)  # conta tem prioridade em campo repetido
        except Exception:
            pass

    # SENTENÇA/ACÓRDÃO — só para a natureza tributária, e só se a conta calou.
    # A conta traz números, não a origem da dívida: o campo falta em 1/3 dos
    # casos medidos, e é ele que decide se incidem PSS e IR. Chamada condicional
    # de propósito — sem isso seria uma chamada de LLM a mais em TODO caso, para
    # um campo que 2/3 das vezes já veio.
    if sentenca_ref and "natureza_tributaria" not in campos:
        try:
            extsen = extrair_natureza(paginas, sentenca_ref, llm)
            if extsen.get("ok"):
                for k, v in extsen["campos"].items():
                    campos.setdefault(k, v)
        except Exception:
            pass

    # REDE DE SEGURANÇA determinística: honorários % com padrão de formulário são
    # regex-confiáveis (o LLM oscila — num run pega os 20%, no outro não). Preenche
    # o que o LLM deixou passar; se ambos acham e DIVERGEM, marca p/ o advogado.
    conflitos = []
    for campo, det in _det_honorarios(textos).items():
        llm_v = (campos.get(campo) or {}).get("valor")
        if campo not in campos:
            campos[campo] = det
        elif str(llm_v).replace(",", ".").rstrip("0").rstrip(".") != \
                str(det["valor"]).replace(",", ".").rstrip("0").rstrip("."):
            conflitos.append({"campo": campo, "llm": llm_v, "regex": det["valor"],
                              "pagina": det["citacao"]["pagina"]})

    # Número CNJ do requisitório: mesma rede determinística, mas restrita às
    # páginas DO OFÍCIO — a conta costuma carregar o número do processo de
    # origem, e varrer tudo faria o originário competir com o do precatório.
    # Mascarar (em vez de fatiar) preserva a numeração global das citações.
    if oficio_ref:
        _a, _b = oficio_ref
        _so_oficio = [t if _a <= i <= _b else "" for i, t in enumerate(textos, start=1)]
        for campo, det in _det_cnj(_so_oficio).items():
            llm_v = (campos.get(campo) or {}).get("valor")
            if campo not in campos:
                campos[campo] = det
            elif str(llm_v).strip() != str(det["valor"]).strip():
                conflitos.append({"campo": campo, "llm": llm_v, "regex": det["valor"],
                                  "pagina": det["citacao"]["pagina"]})

    # Formulário-ofício do PJe lido por rótulo: mesma rede (preenche o que a IA
    # deixou passar; divergência vira conflito). Só identificação — os VALORES
    # do formulário vão como alerta, porque o cartório erra (#3481).
    for campo, det in _pje.campos_oficio(pje, oficio_ref).items():
        llm_v = (campos.get(campo) or {}).get("valor")
        if campo not in campos:
            campos[campo] = det
        elif re.sub(r"\W", "", str(llm_v)).lower() != re.sub(r"\W", "", str(det["valor"])).lower():
            conflitos.append({"campo": campo, "llm": llm_v, "regex": det["valor"],
                              "pagina": det["citacao"]["pagina"]})

    # data de apresentação: determinística (eproc/TJES) tem prioridade; senão a do ofício
    data_apres = extrair_data_envio_tribunal(textos)
    if not data_apres:
        raw = (campos.get("data_apresentacao") or {}).get("valor")
        try:
            data_apres = date.fromisoformat(str(raw)[:10]) if raw else None
        except ValueError:
            data_apres = None

    prova = _prova(campos)
    citacoes: dict[int, list[str]] = {}
    for k, d in campos.items():
        cit = d.get("citacao") or {}
        pg = cit.get("pagina")
        if isinstance(pg, int):
            for t in _termos(d.get("valor"), cit.get("trecho")):
                if t not in citacoes.setdefault(pg, []):
                    citacoes[pg].append(t)

    return {
        "ok": True, "paginas": len(paginas), "escaneadas": escaneadas,
        "homologacao": homol,
        "conta_ref": f"pp{conta_ref[0]}-{conta_ref[1]}",
        "oficio_ref": f"pp{oficio_ref[0]}-{oficio_ref[1]}" if oficio_ref else None,
        "campos": campos, "prova": prova, "conflitos": conflitos,
        "rejeitados": rejeitados,
        "alertas_pje": (pje or {}).get("alertas") or [],
        "data_apresentacao": data_apres.isoformat() if data_apres else None,
        "query": montar_query(campos, data_apres),
        "citacoes": {str(k): v for k, v in citacoes.items()},
        "custo": round(llm.custo_total, 4),
    }


def _corte_ref(corte: dict, n_paginas: int | None = None) -> tuple[int, int] | None:
    """Faixa {pagina_inicio, pagina_fim} → (a, b) normalizado/validado (1-based)."""
    try:
        a, b = int(corte["pagina_inicio"]), int(corte["pagina_fim"])
    except (KeyError, TypeError, ValueError):
        return None
    a, b = min(a, b), max(a, b)
    if a < 1:
        a = 1
    if n_paginas:
        b = min(b, n_paginas)
    return (a, b) if a <= b else None


def extrair_cortes(paginas: list[dict], cortes: list[dict],
                   homol: dict | None = None, llm: LLM | None = None,
                   pje: dict | None = None) -> dict:
    """PASSO 2 do assistente: extrai os campos da calculadora dos cortes que o
    humano CONFIRMOU. `cortes` = [{tipo, pagina_inicio, pagina_fim}].

    Usa o 1º corte "Conta homologada" (obrigatório) e o 1º "Ofício requisitório"
    (opcional). A calculadora é UM CRÉDITO POR VEZ — cortes extras do mesmo tipo
    são sinalizados (`multi_conta`/`multi_oficio`), não somados.
    """
    llm = llm or LLM()
    n = len(paginas)
    contas = [c for c in cortes if c.get("tipo") == TIPO_CONTA]
    oficios = [c for c in cortes if c.get("tipo") == TIPO_OFICIO]
    if not contas:
        return {"ok": False, "erro": "marque ao menos uma faixa como 'Conta homologada'."}
    conta_ref = _corte_ref(contas[0], n)
    if not conta_ref:
        return {"ok": False, "erro": "faixa da conta com páginas inválidas."}
    oficio_ref = _corte_ref(oficios[0], n) if oficios else None

    res = _montar_resultado(paginas, conta_ref, oficio_ref, homol, llm, pje=pje)
    if res.get("ok"):
        res["multi_conta"] = len(contas) > 1
        res["multi_oficio"] = len(oficios) > 1
    return res


# ── 3º modo: PEÇAS JÁ RECORTADAS ─────────────────────────────────────────
# O jurídico anexa o ofício e a conta homologada já separados: cada peça É o
# corte, não existe processo completo. Some o radar, some o juiz — e com eles o
# único erro que os outros dois modos não sabem detectar sozinhos, o de
# LOCALIZAÇÃO (medido: conta homologada em top-1 só 54% das vezes, fila mediana
# de 22 candidatos). Sobra a extração sobre peça curta, que é o problema fácil.

def _substrato_pecas(pecas: list[tuple[str, object]], ocr_fn=None):
    """Peças separadas → UM substrato, renumerando as páginas.

    O módulo inteiro endereça página por `p["pagina"]` (1-based) num espaço
    único — duas peças no mesmo dicionário colidiriam na pág 1. Daí o offset.
    `mapa` desfaz a renumeração para a UI dizer "ofício, pág 2" em vez de
    "pág 5", e para o visualizador saber em QUAL PDF renderizar a citação.
    """
    paginas: list[dict] = []
    refs: dict[str, tuple[int, int]] = {}
    mapa: dict[int, dict] = {}
    for tipo, fonte in pecas:
        if fonte is None:
            continue
        pgs = processar_pdf(fonte, ocr_fn=ocr_fn)
        if not pgs:
            continue
        off = len(paginas)
        for p in pgs:
            local = p["pagina"]
            p["pagina"] = local + off
            mapa[p["pagina"]] = {"peca": tipo, "pagina": local}
            paginas.append(p)
        refs[tipo] = (off + 1, off + len(pgs))
    return paginas, refs, mapa


def extrair_pecas(conta=None, oficio=None, sentencas=None,
                  llm: LLM | None = None, ocr_fn=_PADRAO) -> dict:
    """Peças JÁ RECORTADAS → campos da calculadora. Cada peça aceita bytes ou
    caminho de PDF; `sentencas` é uma LISTA (um processo tem sentença, acórdão,
    embargos…).

    Papéis, e por que são diferentes:
      conta     — obrigatória, é de onde saem os DÍGITOS.
      ofício    — seções 4 e 5 (honorários, modalidade, ente, apresentação).
                  `CAMPOS_OFICIO` não pede valor nenhum, de propósito.
      sentenças — SÓ a natureza tributária, e só se a conta não a declarou.
                  Pedir valores a uma decisão convidaria o modelo a ler o da
                  condenação original em vez do da conta homologada.
    """
    llm = llm or LLM()
    # OCR por padrão: sem ele ~1 em 5 contas é recusada por ser imagem. O
    # substrato só chama em página SEM camada de texto, então peça nativa não
    # paga os ~4s. `ocr_fn` explícito (inclusive None) continua vencendo, que é
    # o que os testes usam para não depender do binário.
    if ocr_fn is _PADRAO:
        ocr_fn = _ocr.ler_pagina if _ocr.disponivel() else None
    _pecas = [(TIPO_CONTA, conta), (TIPO_OFICIO, oficio)]
    _sent = [s for s in (sentencas or []) if s is not None]
    # rótulo numerado quando há mais de uma: o `mapa_paginas` vira "Sentença /
    # acórdão 2, pág 3" na tela, em vez de um "pág 14" que não localiza nada.
    _pecas += [(TIPO_SENTENCA if len(_sent) == 1 else f"{TIPO_SENTENCA} {i + 1}", s)
               for i, s in enumerate(_sent)]
    paginas, refs, mapa = _substrato_pecas(_pecas, ocr_fn=ocr_fn)
    conta_ref = refs.get(TIPO_CONTA)
    if not conta_ref:
        return {"ok": False, "erro": "sem_conta",
                "detalhe": "a conta homologada é obrigatória — é dela que saem os valores."}

    # Guarda ANTES de gastar LLM: peça escaneada chega ao prompt como página em
    # branco, e aí o modelo devolve null (bom) ou inventa (caro). Falhar aqui é
    # explícito, instantâneo e de graça — ~1 em 5 contas do corpus é imagem pura.
    # Reusa o critério do substrato (`nativa`); com `ocr_fn` injetado o texto já
    # veio do OCR e a guarda não morde.
    a, b = conta_ref
    da_conta = [p for p in paginas if a <= p["pagina"] <= b]
    chars = sum(len(p.get("texto") or "") for p in da_conta)
    if not any(p.get("nativa") for p in da_conta) and chars < MIN_TEXTO_NATIVO:
        return {"ok": False, "erro": "conta_escaneada", "chars": chars,
                "detalhe": f"a conta tem {chars} caracteres extraíveis — é imagem. "
                           f"Precisa de OCR antes de extrair.",
                "pecas": {k: f"pp{v[0]}-{v[1]}" for k, v in refs.items()}}

    # as sentenças ficam contíguas no fim do espaço concatenado, então a faixa
    # combinada é (menor início, maior fim) — não precisa de N chamadas.
    _sent_refs = [v for k, v in refs.items() if k.startswith(TIPO_SENTENCA)]
    sentenca_ref = (min(a for a, _ in _sent_refs), max(b for _, b in _sent_refs))         if _sent_refs else None

    # OCR é leitura de IMAGEM: o dígito pode sair errado sem parecer errado (no
    # 1063 o total saiu com um centavo a mais). A tela precisa saber disso para
    # exigir conferência contra a página, então a proveniência viaja junto.
    res_ocr = [p["pagina"] for p in da_conta if not p.get("nativa") and (p.get("texto") or "")]

    res = _montar_resultado(paginas, conta_ref, refs.get(TIPO_OFICIO), None, llm,
                            sentenca_ref=sentenca_ref)
    res["conta_por_ocr"] = bool(res_ocr)
    res["mapa_paginas"] = {str(k): v for k, v in mapa.items()}
    res["pecas"] = {k: f"pp{v[0]}-{v[1]}" for k, v in refs.items()}
    return res


def preencher(pdf_path: str = None, pdf_bytes: bytes = None, llm: LLM | None = None, ocr_fn=None) -> dict:
    """PDF → campos da calculadora (seções 1, 3, 4, 5), modo AUTÔNOMO (juiz LLM
    escolhe a conta e o ofício). Ponto de entrada do expander "Anexar processo"."""
    llm = llm or LLM()
    fonte = pdf_bytes if pdf_bytes is not None else pdf_path
    paginas = processar_pdf(fonte, ocr_fn=ocr_fn)
    textos = [p.get("texto") or "" for p in paginas]
    escaneadas = sum(1 for p in paginas if not p.get("nativa"))

    homol = achar_homologacao(textos)
    # Nível 0 primeiro: no PJe, índice + carimbo localizam conta e ofício sem
    # o juiz LLM (e sem o radar, que carrega o modelo de embedding).
    pj = _pje_seguro(fonte, paginas)
    if pj and pj.get("conta"):
        conta_ref = (pj["conta"]["pagina_inicio"], pj["conta"]["pagina_fim"])
        of = next((c for c in pj["cortes"] if c["tipo"] == TIPO_OFICIO), None)
        oficio_ref = (of["pagina_inicio"], of["pagina_fim"]) if of else None
    else:
        rad = R.buscar(paginas, None)
        conta_ref, oficio_ref = _escolher(paginas, rad["runs"], homol, llm)
    if not conta_ref:
        return {"ok": False, "erro": "não localizei a conta homologada",
                "paginas": len(paginas), "escaneadas": escaneadas, "homologacao": homol}
    return _montar_resultado(paginas, conta_ref, oficio_ref, homol, llm, pje=pj)


if __name__ == "__main__":
    import argparse
    import sys
    from urllib.parse import urlencode
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser()
    ap.add_argument("pdf")
    ap.add_argument("--modelo", default=None)
    args = ap.parse_args()
    r = preencher(args.pdf, llm=LLM(modelo=args.modelo))
    if not r.get("ok"):
        print("FALHOU:", r.get("erro"), "| homolog:", r.get("homologacao"))
    else:
        print(f"{r['paginas']}pp ({r['escaneadas']} escan.) | conta {r['conta_ref']} | ofício {r['oficio_ref']}")
        h = r["homologacao"]
        print(f"homologação: {('Evento '+str(h['evento'])+' pág '+str(h['pagina'])) if h else 'não detectada'}")
        pr = r["prova"]
        print(f"prova: {'✅' if pr.get('ok') else '❌ '+str(pr.get('dif_pct'))+'%' if pr.get('ok') is False else 'n/a'}"
              f" | apresentação: {r['data_apresentacao']}")
        print("CAMPOS:")
        for k, d in r["campos"].items():
            print(f"  {k:32}= {str(d['valor']):>18}  (pág {(d.get('citacao') or {}).get('pagina')})")
        print("QUERY:", "?" + urlencode(r["query"]))
        print(f"custo ${r['custo']}")
