"""Catálogo de marcadores que SUGEREM o tipo de uma página (conta × ofício).

Substitui os dois regex soltos que o `pipeline` usava (`_RE_CONTA_FORTE`,
`_RE_OFICIO_FORTE`). A troca vem do levantamento de 28/10/2026 (232 casos, 34
tribunais, índice `precatur-palavras-chave` no Elasticsearch), que mediu cada
marcador nos cortes do advogado:

  * "ofício requisitório" literal só aparece em 17% dos ofícios, e `\\bRPV\\b`
    dispara em intimação, certidão e petição (precisão 0,37). Os dois sozinhos
    rotulavam como ofício qualquer página que CITA o ofício;
  * o cálculo homologado era reconhecido em 44% (TJMG 38%), porque os
    marcadores eram de SISTEMA GERADOR (Projef, SICAR, PJe-Calc), que a
    contadoria estadual não usa. Os rótulos de formulário da contadoria
    ("Total Partes ->", "III - Totalização", "Critérios e parâmetros do
    cálculo") têm especificidade alta e não estavam no código.

Por isso cada marcador tem um PAPEL, e a decisão combina papéis:

  forte     sozinho decide (precisão medida >= 0,9 entre os tipos de peça);
  fraco     só decide com um marcador de conteúdo do mesmo tipo na página;
  conteudo  decide em grupo (conta: 3 distintos, ou 2 numa página com tabela de
            valores; ofício: 2 distintos);
  veto      anula fraco e conteúdo (nunca o forte): RMI/PBC do INSS não é conta
            de liquidação; petição que PEDE a expedição não é o ofício.

O `id` de cada marcador é o mesmo do índice `precatur-palavras-chave` quando o
marcador veio de lá: a telemetria grava os ids que dispararam em cada página e
o Kibana mede a precisão real de cada um contra o corte que o advogado
confirmou. Marcador novo ganha id `marcador:app:...`.

Todos os regex rodam sobre o texto NORMALIZADO (sem acento, minúsculo): metade
dos PDFs vem com "Calculo"/"CÁLCULO"/"cálculo" e a outra metade com cedilha
perdida ("Liquidaçao" no TJGO).
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass

CONTA = "conta"
OFICIO = "oficio"
SENTENCA = "sentenca"
NAO_ALVO = "nao_alvo"

FORTE, FRACO, CONTEUDO, VETO = "forte", "fraco", "conteudo", "veto"
# SINAL: vocabulário que a sentença também usa (SELIC, IPCA-E, juros
# moratórios). Sozinho não decide — foi ele que fez 32 páginas de sentença
# virarem "conta" nos anexos do Bitrix (28/10/2026, TJMS e TRF5); só soma ao
# lado de um marcador de CONTEÚDO de conta (ver `classificar`).
SINAL = "sinal"
DECISAO = "decisao"

# mínimo de marcadores de conteúdo distintos para decidir sem um forte
MIN_CONTEUDO_CONTA = 3
MIN_CONTEUDO_CONTA_COM_TABELA = 2
MIN_VALORES_TABELA = 5
MIN_CONTEUDO_OFICIO = 2

_VALOR = re.compile(r"(?<![\d.,])\d{1,3}(?:\.\d{3})*,\d{2}(?!\d)")


def normalizar(texto: str) -> str:
    """Sem acento, minúsculo, espaços colapsados por linha (as quebras ficam:
    alguns marcadores são de início de linha)."""
    t = unicodedata.normalize("NFKD", texto or "").encode("ascii", "ignore").decode()
    return re.sub(r"[ \t]+", " ", t.lower())


@dataclass(frozen=True)
class Marcador:
    id: str
    tipo: str
    papel: str
    regex: re.Pattern


def _m(id_: str, tipo: str, papel: str, padrao: str, flags: int = 0) -> Marcador:
    return Marcador(id_, tipo, papel, re.compile(padrao, flags))


_L = "marcador:"  # prefixo dos ids do índice

MARCADORES: tuple[Marcador, ...] = (
    # ── CONTA · forte ────────────────────────────────────────────────────
    # o que o pipeline já usava (`_RE_CONTA_FORTE`), um id por termo
    _m(_L + "radar:forte:projef", CONTA, FORTE, r"projef"),
    _m(_L + "calculo_detector:strong_patterns:resumo_calculo", CONTA, FORTE, r"resumo do calculo"),
    _m(_L + "radar:forte:calculos_judiciais", CONTA, FORTE, r"calculos judiciais"),
    _m(_L + "radar:forte:sicar", CONTA, FORTE, r"\bsicar\b"),
    _m(_L + "radar:forte:demonstrativo_calculo", CONTA, FORTE, r"demonstrativo de calculo"),
    _m(_L + "radar:forte:memoria_calculo", CONTA, FORTE, r"memoria de calculo"),
    _m(_L + "calculo_detector:strong_patterns:pje_calc", CONTA, FORTE, r"e-?pcalc|pje-?calc"),
    _m(_L + "radar:forte:pfe_inss", CONTA, FORTE, r"pfe-?inss"),
    _m(_L + "radar:forte:diferenca_devida", CONTA, FORTE, r"diferenca devida"),
    _m(_L + "radar:forte:dados_liquidacao", CONTA, FORTE, r"dados da liquidacao"),
    _m(_L + "app:conta:conta_liquidacao", CONTA, FORTE, r"conta de liquidacao"),
    # medidos com precisão 1,0 no levantamento
    _m(_L + "calculo_detector:strong_patterns:sistema_integracao", CONTA, FORTE,
       r"sistema de integracao de calculos e requisicoes"),
    _m(_L + "calculo_detector:strong_patterns:demonstrativo_parcelas", CONTA, FORTE,
       r"demonstrativo de parcelas"),
    _m(_L + "calculo_detector:content_patterns:coef_correcao", CONTA, FORTE,
       r"coef\.? ?corr\.? ?monetaria"),
    _m(_L + "calculo_detector:content_patterns:valor_total_pss", CONTA, FORTE,
       r"valor total.{0,80}?somado a eventual pss"),
    # rótulos de formulário da contadoria/Projef minerados nos cortes (termo_minerado)
    _m(_L + "app:conta:total_partes", CONTA, FORTE, r"total (?:das )?partes ?-?>"),
    _m(_L + "app:conta:total_sucumbencias", CONTA, FORTE, r"total de sucumbencias ?-?>"),
    _m(_L + "app:conta:totalizacao", CONTA, FORTE, r"\biii ?[-.] ?totalizacao"),
    _m(_L + "app:conta:criterios_parametros", CONTA, FORTE, r"criterios e parametros do calculo"),
    _m(_L + "app:conta:outras_sucumbencias", CONTA, FORTE, r"outras sucumbencias: ?nao foram apuradas"),
    _m(_L + "app:conta:resumo_atualizacao", CONTA, FORTE, r"resumo da atualizacao do calculo"),
    _m(_L + "app:conta:planilha_atualizacao", CONTA, FORTE, r"planilha de atualizacao de calculo"),
    _m(_L + "app:conta:liquido_reclamante", CONTA, FORTE, r"liquido devido ao reclamante"),
    _m(_L + "app:conta:total_devido_reclamado", CONTA, FORTE, r"total devido pelo reclamado"),

    # ── CONTA · conteúdo (decide em grupo) ───────────────────────────────
    _m(_L + "calculo_detector:strong_patterns:saldo_devedor", CONTA, CONTEUDO, r"saldo devedor"),
    _m(_L + "conta_generica:vocab:fator-indice-de-corre-atualiza", CONTA, CONTEUDO,
       r"(?:fator|indice) (?:de )?(?:corre|atualiza)"),
    _m(_L + "conta_generica:vocab:total-atualizado-do-calculo-geral-devido", CONTA, CONTEUDO,
       r"total (?:atualizado|do calculo|geral|devido|da conta|\(a ?\+ ?b\))"),
    _m(_L + "conta_generica:vocab:periodo-do-calculo-data-do-calculo-atual", CONTA, CONTEUDO,
       r"periodo d[oe] calculo|data (?:do )?calculo|atualizacao (?:para|ate) \d"),
    _m(_L + "conta_generica:re_cabecalho:re_cabecalho", CONTA, SINAL,
       r"demonstrativo de (?:de )?calculos?|calculos? de atualiza|atualizacao (?:monetaria )?d[oe]s? "
       r"(?:debito|valor|credito)|(?:resumo|conferencia|planilha) d[eo]s? calculo|"
       r"liquidacao de sentenca|calculo de liquida"),
    _m(_L + "app:conta:valor_corrigido", CONTA, CONTEUDO, r"valor (?:corrigido|atualizado|original)"),
    _m(_L + "app:conta:datas_processuais", CONTA, CONTEUDO,
       r"data (?:liquidacao|ajuizamento|citacao|distribuicao|prescricao):"),
    _m(_L + "app:conta:juros_moratorios", CONTA, SINAL, r"juros (?:de mora|moratorios)"),
    _m(_L + "app:conta:indices", CONTA, SINAL, r"\bselic\b|\bipca-?e\b|\binpc\b|poupanca"),
    _m(_L + "conta_generica:vocab:contadoria", CONTA, CONTEUDO, r"contadoria"),

    # ── CONTA · veto (RMI/PBC, extratos do INSS: tabela, mas não é a conta) ─
    _m(_L + "calculo_detector:rmi_pbc_patterns:periodo_basico_calculo", CONTA, VETO,
       r"periodo basico de calculo"),
    _m(_L + "calculo_detector:rmi_pbc_patterns:rmi", CONTA, VETO,
       r"\bnova rmi\b|renda mensal inicial|\brmi original\b|sb ?/ ?media ?/ ?teto|\bind\.? ?teto\b"),
    _m(_L + "calculo_detector:nao_calculo_patterns:extrato_dossie", CONTA, VETO,
       r"extrato de dossie previdenciario|ficha sintetica|\bprovisionado\b|\bmr do periodo\b"),
    _m(_L + "calculo_detector:nao_calculo_forte_patterns:sistemas_inss", CONTA, VETO,
       r"\bsisben ?web\b|\bconbas\b|dados basicos da concessao"),

    # ── OFÍCIO · forte ───────────────────────────────────────────────────
    _m(_L + "oficio_detector:strong_patterns:requisicao_pagamento", OFICIO, FORTE,
       r"requisicao (?:de|para) pagamento"),
    _m(_L + "oficio_detector:pje_contexto:tipo_requisicao", OFICIO, FORTE, r"tipo de requisicao"),
    _m(_L + "oficio_detector:requisitorio_forma:requisitorio_forma", OFICIO, FORTE,
       r"requisito o pagamento|ao desembargador presidente|juizo requisitante|especie ?/ ?vincula|"
       r"^ ?[a-g] ?[-–] ?(?:identificac|especie|natureza|processos?|credor|valor requisitado)",
       re.M),
    _m(_L + "oficio_detector:req_sequencial:req_sequencial", OFICIO, FORTE,
       r"requisicao de (?:precatorio(?: ?/ ?rpv)?|pequeno valor)[\s\S]{0,40}?n[o.\s]+\d{1,4} ?/ ?(?:19|20)\d{2}"),
    # formulário da Res. CNJ 303/2019 (TJMG: 93-96 dos 219 ofícios do corpus)
    _m(_L + "app:oficio:oficio_precatorio_beneficiario", OFICIO, FORTE,
       r"oficio precatorio ?- ?beneficiario"),
    _m(_L + "app:oficio:juizo_origem_requisicao", OFICIO, FORTE, r"juizo de origem da requisicao"),
    _m(_L + "app:oficio:informacoes_requisicao", OFICIO, FORTE,
       r"^ ?1\. ?informacoes processuais|^ ?2\. ?informacoes sobre a requisicao", re.M),

    # ── OFÍCIO · fraco (citado em intimação, certidão e petição) ─────────
    _m(_L + "oficio_detector:strong_patterns:oficio_requisitorio", OFICIO, FRACO,
       r"oficio requisitorio|oficio precatorio"),
    _m(_L + "oficio_detector:strong_patterns:rpv", OFICIO, FRACO,
       r"requisicao de pequeno valor|\brpv\b"),
    _m(_L + "app:oficio:numero_oficio", OFICIO, FRACO,
       r"n[o.]? ?(?:do )?(?:oficio|precatorio|requisitorio)\b"),

    # ── OFÍCIO · conteúdo (campos do formulário) ─────────────────────────
    _m(_L + "oficio_detector:content_patterns:natureza_credito", OFICIO, CONTEUDO,
       r"natureza do credito"),
    _m(_L + "oficio_detector:content_patterns:data_base", OFICIO, CONTEUDO, r"data[ -]?base"),
    _m(_L + "oficio_detector:content_patterns:valor_bruto_liquido", OFICIO, CONTEUDO,
       r"valor (?:bruto|liquido|total liquido|requisitado|total requisitado)"),
    _m(_L + "oficio_detector:content_patterns:honorarios", OFICIO, CONTEUDO,
       r"honorarios (?:sucumb|contratuais)"),
    _m(_L + "app:oficio:resolucao_303", OFICIO, CONTEUDO, r"resolucao n?[o.]? ?303/2019"),
    _m(_L + "app:oficio:numeracao_unica", OFICIO, CONTEUDO, r"numeracao unica do processo"),
    _m(_L + "app:oficio:beneficiario", OFICIO, CONTEUDO, r"beneficiario|ente devedor"),

    # ── OFÍCIO · veto (pede, intima ou certifica: não é o formulário) ─────
    _m(_L + "oficio_detector:peticao_veto:peticao_veto", OFICIO, VETO,
       r"requerimento d[ae] expedic|requer(?:-se)? a expedicao|reiterar os termos d[ae] peti|"
       r"ora reiterad|(?:espera|pede) deferimento|termos em que"),
    _m(_L + "app:oficio:intimacao_certidao", OFICIO, VETO,
       r"\bfica(?:m)? (?:a parte |as partes )?intimad|\bintimem-se\b|\bcertifico\b"),

    # ── DECISÃO · veto do que decide por conteúdo (conta e ofício) ────────
    # a sentença fala de juros, índices, RPV e honorários; o que a distingue
    # é a forma (levantamento: precisão 0,72-0,98 entre os tipos de peça)
    _m(_L + "decisao_detector:strong_patterns:ante_o_exposto", DECISAO, VETO,
       r"ante o exposto|posto isso|diante do exposto|isto posto|pelo exposto"),
    _m(_L + "decisao_detector:strong_patterns:julgo_procedente", DECISAO, VETO,
       r"julgo (?:total |parcialmente )?(?:procedente|improcedente)|\bjulgo extint"),
    _m(_L + "decisao_detector:strong_patterns:acordao", DECISAO, VETO,
       r"\bacordam\b|vistos, relatados e discutidos|^ ?(?:ementa|acordao)\b", re.M),
    _m(_L + "decisao_detector:strong_patterns:relatorio", DECISAO, VETO,
       r"e o relatorio|^ ?sentenca ?$|publique-se|\bdecido\b", re.M),
)

# conta "citada": o formulário do ofício diz "conforme conta de liquidação" e
# "memória de cálculo". Com um forte de OFÍCIO na página, estes não ganham dele
# (86 páginas de ofício viravam conta nos anexos do Bitrix, 28/10/2026)
CONTA_CITAVEL = frozenset(_L + x for x in (
    "app:conta:conta_liquidacao", "radar:forte:memoria_calculo", "radar:forte:dados_liquidacao",
    "radar:forte:demonstrativo_calculo", "radar:forte:calculos_judiciais"))

DIFERENCA_DEVIDA = _L + "radar:forte:diferenca_devida"

# qualificador: ofício provisório ("prévia", "minuta") — não muda o tipo, vai no motivo
PROVISORIO = re.compile(
    r"oficio ?n[o.]? ?[:.\-]? ?previa\b|\b(?:previa|minuta) (?:de )?(?:oficio n|requisicao de pagament)"
    r"|\( ?previa ?\)")

_POR_TIPO_PAPEL: dict[tuple[str, str], tuple[Marcador, ...]] = {}
for _mk in MARCADORES:
    _POR_TIPO_PAPEL[(_mk.tipo, _mk.papel)] = _POR_TIPO_PAPEL.get((_mk.tipo, _mk.papel), ()) + (_mk,)


# ── rótulo gravado pelo próprio SISTEMA (adapter): vale mais que o texto ──
# eproc: rodapé "Evento 45, PLAN1, Página 2" — o prefixo do código diz a peça.
_RE_EPROC = re.compile(r"evento \d+ ?, ?([a-z_]+?)\d+ ?, ?pagina \d+")
_EPROC = {
    "plan": CONTA, "calc": CONTA,
    "rpv": OFICIO, "prec": OFICIO, "ofic": OFICIO, "requisit": OFICIO,
    "sent": SENTENCA, "acor": SENTENCA, "voto": SENTENCA,
    "inic": NAO_ALVO, "pet": NAO_ALVO, "pet_intercorrente": NAO_ALVO, "proacordo": NAO_ALVO,
    "execumpr": NAO_ALVO, "cumpr_sent": NAO_ALVO, "cont": NAO_ALVO, "replica": NAO_ALVO,
    "contraz": NAO_ALVO, "apelacao": NAO_ALVO, "embdecl": NAO_ALVO, "proc": NAO_ALVO,
    "declpobre": NAO_ALVO, "anexo": NAO_ALVO, "doc": NAO_ALVO, "doc_identif": NAO_ALVO,
    "extr": NAO_ALVO, "inf": NAO_ALVO, "infben": NAO_ALVO, "atoord": NAO_ALVO,
    "comunicacoes": NAO_ALVO, "com": NAO_ALVO, "cert": NAO_ALVO, "intim": NAO_ALVO,
    "procadm": NAO_ALVO,
}
# PJe-1G do TRF1: cabeçalho "Documento id 123456 - Ofício requisitório"
_RE_TRF1 = re.compile(r"documento id \d+ ?- ?([^\n]{2,60})")
_TRF1 = (  # (prefixo do rótulo, tipo) — ordem importa: o mais específico primeiro
    ("oficio enviando informacoes", NAO_ALVO), ("oficio requisitorio", OFICIO),
    ("requisicao de pequeno valor", OFICIO), ("precatorio", OFICIO), ("rpv", OFICIO),
    ("calculo de liquidacao", CONTA), ("calculo", CONTA), ("planilha", CONTA),
    ("sentenca", SENTENCA), ("acordao", SENTENCA), ("voto", SENTENCA), ("decisao", SENTENCA),
    ("peticao", NAO_ALVO), ("manifestacao", NAO_ALVO), ("impugnacao", NAO_ALVO),
    ("ato ordinatorio", NAO_ALVO), ("procuracao", NAO_ALVO), ("substabelecimento", NAO_ALVO),
)
# PJe-TJGO: rodapé "Arquivo 3: oficio_requisitorio.pdf"
_RE_ARQUIVO = re.compile(r"arquivo \d+ ?: ?([a-z0-9_\-. ]{3,80}?)\.pdf")
_ARQUIVO = (
    ("oficio_requisitorio", OFICIO), ("requisicao_de_pagamento", OFICIO),
    ("liquidacao_de_sentenca", CONTA), ("demonstrativo_de_calculo", CONTA), ("planilha", CONTA),
    ("sentenca_sign", SENTENCA), ("acordao_sign", SENTENCA), ("decisao", SENTENCA),
    ("cumprimento_de_sentenca", NAO_ALVO), ("peticao", NAO_ALVO), ("manifestacao", NAO_ALVO),
    ("inicial", NAO_ALVO), ("impugnac", NAO_ALVO), ("contrarrazoes", NAO_ALVO),
)


def rotulo_sistema(norm: str) -> dict | None:
    """{sistema, tipo, rotulo} quando a página traz o rótulo do sistema."""
    m = _RE_EPROC.search(norm)
    if m:
        cod = m.group(1)
        tipo = _EPROC.get(cod)
        if tipo is None:  # PLAN_CALC, OFIC_REQ...: pelo prefixo conhecido mais longo
            tipo = next((t for k, t in sorted(_EPROC.items(), key=lambda x: -len(x[0]))
                         if cod.startswith(k)), None)
        if tipo:
            return {"sistema": "eproc", "tipo": tipo, "rotulo": cod.upper()}
    m = _RE_TRF1.search(norm)
    if m:
        rot = m.group(1).strip()
        tipo = next((t for k, t in _TRF1 if rot.startswith(k)), None)
        if tipo:
            return {"sistema": "pje_trf1", "tipo": tipo, "rotulo": rot}
    m = _RE_ARQUIVO.search(norm)
    if m:
        nome = m.group(1)
        tipo = next((t for k, t in _ARQUIVO if k in nome), None)
        if tipo:
            return {"sistema": "pje_tjgo", "tipo": tipo, "rotulo": nome}
    return None


def disparos(norm: str) -> list[str]:
    """Ids dos marcadores que casam no texto normalizado."""
    return [mk.id for mk in MARCADORES if mk.regex.search(norm)]


def _tem(norm: str, tipo: str, papel: str) -> list[str]:
    return [mk.id for mk in _POR_TIPO_PAPEL.get((tipo, papel), ()) if mk.regex.search(norm)]


def conta_forte(texto: str) -> bool:
    """Cabeçalho/rótulo de conta que decide sozinho (usado também pelo radar)."""
    return bool(_tem(normalizar(texto), CONTA, FORTE))


def classificar(texto: str, n_valores: int | None = None) -> dict:
    """Tipo sugerido para UMA página: {tipo: conta|oficio|None, nivel, marcadores}.

    Precedência (a conta é a peça obrigatória, então ganha empate de forte):
      rótulo do sistema > conta forte > ofício forte > ofício fraco+conteúdo
      > conta por conteúdo > ofício por conteúdo.
    `nivel` diz por que decidiu — é o que a telemetria agrega.
    """
    norm = normalizar(texto)
    sis = rotulo_sistema(norm)
    achados = disparos(norm)
    out = {"tipo": None, "nivel": None, "marcadores": achados, "sistema": sis,
           "provisorio": bool(PROVISORIO.search(norm))}
    if sis and sis["tipo"] in (CONTA, OFICIO):
        out.update(tipo=sis["tipo"], nivel="rotulo_sistema")
        return out

    def ids(tipo, papel):
        prefixos = {mk.id for mk in _POR_TIPO_PAPEL.get((tipo, papel), ())}
        return [i for i in achados if i in prefixos]

    conta_f, oficio_f = ids(CONTA, FORTE), ids(OFICIO, FORTE)
    decisao = bool(ids(DECISAO, VETO))
    if conta_f and not oficio_f:
        citada = set(conta_f) <= CONTA_CITAVEL
        # formulário SEM cabeçalho forte (TJES, TJRJ): "memória de cálculo" ao
        # lado de "data-base" e "valor bruto" é o ofício citando a conta.
        # Medido em 600 cards do Bitrix: ofício confundido com conta 15% → 4%,
        # sem mudar a conta (88%/2%)
        if citada and len(ids(OFICIO, CONTEUDO)) >= 2 and not ids(OFICIO, VETO):
            out.update(tipo=OFICIO, nivel="citacao")
            return out
        # acórdão trabalhista fala em "diferenças devidas" (TRT2): na decisão,
        # conta só citada não é conta
        if decisao and set(conta_f) <= CONTA_CITAVEL | {DIFERENCA_DEVIDA}:
            conta_f = []
    if conta_f and not (oficio_f and set(conta_f) <= CONTA_CITAVEL):
        out.update(tipo=CONTA, nivel="forte")
        return out
    if oficio_f:
        out.update(tipo=OFICIO, nivel="forte")
        return out
    # rótulo do sistema dizendo que é petição/certidão/sentença: só o forte vale
    if sis:
        return out

    veto_of = decisao or bool(ids(OFICIO, VETO))
    cont_of = ids(OFICIO, CONTEUDO)
    if not veto_of and ids(OFICIO, FRACO) and cont_of:
        out.update(tipo=OFICIO, nivel="fraco+conteudo")
        return out

    cont_ct = ids(CONTA, CONTEUDO)
    if cont_ct:
        # SINAL (SELIC, juros, índices) volta a somar, mas só ao lado de um
        # conteúdo de verdade e longe de vocabulário de decisão: sozinho, ele
        # rotulava sentença; ignorado, a conta do TJMS caía de 98% para 80%.
        # Medido nos anexos do Bitrix (300 cards, 28/10/2026): conta 85% → 88%,
        # sentença confundida 5% → 7% (a regra antiga: 83% e 15%)
        cont_ct = cont_ct + ids(CONTA, SINAL)
    if n_valores is None:
        n_valores = len(_VALOR.findall(texto or ""))
    minimo = MIN_CONTEUDO_CONTA_COM_TABELA if n_valores >= MIN_VALORES_TABELA else MIN_CONTEUDO_CONTA
    if not decisao and not ids(CONTA, VETO) and len(cont_ct) >= minimo:
        out.update(tipo=CONTA, nivel="conteudo")
        return out
    if not veto_of and len(cont_of) >= MIN_CONTEUDO_OFICIO + 1:
        # sem cabeçalho nenhum, o formulário precisa de 3 campos: dois
        # ("data-base", "honorários") aparecem em qualquer decisão
        out.update(tipo=OFICIO, nivel="conteudo")
    return out


def catalogo() -> list[dict]:
    """O catálogo como documentos do índice `precatur-palavras-chave`."""
    out = []
    for mk in MARCADORES:
        out.append({
            "id": mk.id + (":app" if not mk.id.startswith(_L + "app:") else ""),
            "tipo_registro": "marcador",
            "tipo_documento": [{CONTA: "calculo_homologado", OFICIO: "oficio"}.get(mk.tipo, "sentenca")],
            "papel": mk.papel,
            "termos": [mk.regex.pattern],
            "regex": mk.regex.pattern,
            "regex_flags": ["NORMALIZADO"] + (["MULTILINE"] if mk.regex.flags & re.M else []),
            "sistema_processual": ["*"], "tribunal": ["*"], "justica": ["*"],
            "origem": {"arquivo": "calculadora/prefill/marcadores.py", "simbolo": "MARCADORES",
                       "rotulo": mk.id},
            "status": "ativo_no_app",
            "prioridade": {OFICIO: "muito_importante", CONTA: "importante"}.get(mk.tipo, "menos_importante"),
            "prioridade_ordem": {OFICIO: 1, CONTA: 2}.get(mk.tipo, 3),
        })
    return out
