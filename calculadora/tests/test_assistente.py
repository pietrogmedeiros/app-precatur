"""Testes do assistente de corte (M1) — parte determinística, ZERO custo de IA.

Cobre: rotulagem das faixas (radar sugere), corte físico com fitz, validação de
faixa, extração dos cortes com LLM FAKE (JSON canned) e a PARIDADE entre o modo
assistido (`extrair_cortes`) e o autônomo (`preencher`) no caminho compartilhado.

Um PDF sintético (fitz) faz de processo: pág 1 = conta ("RESUMO DO CÁLCULO"),
pág 2 = ruído, pág 3 = ofício requisitório. Nenhuma chamada de rede.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import fitz
import pytest

_RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_RAIZ))

from prefill import pipeline as P  # noqa: E402
from prefill.cortar import cortar_pdf  # noqa: E402
from prefill.llm import salvage_json  # noqa: E402
from prefill.pipeline import (  # noqa: E402
    TIPO_CONTA,
    TIPO_OFICIO,
    TIPO_OUTRO,
    TIPO_SENTENCA,
    _corte_ref,
    _norm_ente,
    _rotular_run,
    _rotular_runs,
    analisar,
    extrair_cortes,
    extrair_pecas,
    montar_query,
    preencher,
)


# ── PDF sintético ────────────────────────────────────────────────────────
_CONTA = (
    "RESUMO DO CÁLCULO\n"
    "Conta de liquidação homologada — Projef\n"
    "Principal corrigido 100.000,00\n"
    "Juros moratórios 50.000,00\n"
    "Total geral da execução 150.000,00\n"
    "Data do cálculo 15/01/2025\n"
)
_RUIDO = (
    "Nada de interesse aqui. Petição intermediária juntada aos autos.\n"
    "Texto de preenchimento sem valores nem cabeçalho de conta.\n" * 3
)
_OFICIO = (
    "OFÍCIO REQUISITÓRIO Nº 123/2025\n"
    "Requisição de Pagamento — precatório\n"
    "Beneficiário: Fulano de Tal\n"
    "Ente devedor: Estado do Espírito Santo\n"
    "Valor requisitado: 150.000,00\n"
)


def _pdf() -> bytes:
    doc = fitz.open()
    for texto in (_CONTA, _RUIDO, _OFICIO):
        page = doc.new_page()
        page.insert_text((72, 72), texto, fontsize=11)
    return doc.tobytes()


@pytest.fixture(scope="module")
def pdf_bytes() -> bytes:
    return _pdf()


@pytest.fixture(scope="module")
def paginas(pdf_bytes):
    return P.processar_pdf(pdf_bytes)


# ── LLM fake: devolve JSON canned conforme o prompt ──────────────────────
_CONTA_JSON = {
    "valor_total": {"valor": "150.000,00", "citacao_pagina": 1, "citacao_trecho": "Total geral da execução 150.000,00"},
    "valor_principal": {"valor": "100.000,00", "citacao_pagina": 1, "citacao_trecho": "Principal corrigido 100.000,00"},
    "valor_juros": {"valor": "50.000,00", "citacao_pagina": 1, "citacao_trecho": "Juros moratórios 50.000,00"},
    "valor_selic": {"valor": None},
    "valor_pss": {"valor": None},
    "valor_ir": {"valor": None},
    "honorarios_contratuais_pct": {"valor": None},
    "honorarios_sucumbenciais_pct": {"valor": None},
    "data_calculo": {"valor": "2025-01-15", "citacao_pagina": 1, "citacao_trecho": "Data do cálculo 15/01/2025"},
    "natureza_tributaria": {"valor": "remuneratorio", "citacao_pagina": 1, "citacao_trecho": "servidor"},
}
_OFICIO_JSON = {
    "honorarios_contratuais_pct": {"valor": "30", "citacao_pagina": 3, "citacao_trecho": "contratuais 30%"},
    "honorarios_sucumbenciais_pct": {"valor": None},
    "modalidade": {"valor": "precatorio", "citacao_pagina": 3, "citacao_trecho": "precatório"},
    "ente_devedor": {"valor": "Estado do Espírito Santo", "citacao_pagina": 3, "citacao_trecho": "Estado do Espírito Santo"},
    "data_apresentacao": {"valor": None},
    "beneficiario": {"valor": "Fulano de Tal", "citacao_pagina": 3, "citacao_trecho": "Fulano de Tal"},
}


_SENTENCA_JSON = {
    "natureza_tributaria": {"valor": "indenizatorio", "citacao_pagina": 1,
                            "citacao_trecho": "condeno ao pagamento de danos morais"},
}


class FakeLLM:
    def __init__(self, conta_sem_natureza: bool = False):
        self.custo_total = 0.0
        self.prompts = []
        self._conta = dict(_CONTA_JSON)
        if conta_sem_natureza:                          # força o caminho da sentença
            self._conta["natureza_tributaria"] = {"valor": None}

    def responder(self, prompt, max_tokens=8192):
        self.prompts.append(prompt)
        if "conta_ref" in prompt:                       # juiz (só no modo autônomo)
            payload = {"conta_ref": "pp1-1", "oficio_ref": "pp3-3"}
        elif "dados de um OFÍCIO" in prompt:             # extração do ofício
            payload = _OFICIO_JSON
        elif "SENTENÇA ou ACÓRDÃO" in prompt:            # natureza pela decisão
            payload = _SENTENCA_JSON
        else:                                            # extração da conta
            payload = self._conta
        return json.dumps(payload), {"lat": 0.0, "custo": 0.0}

    def chamadas(self, marcador: str) -> int:
        return sum(1 for p in self.prompts if marcador in p)


# ── rotulagem (radar SUGERE) ─────────────────────────────────────────────
def test_rotular_conta_por_cabecalho(paginas):
    assert _rotular_run(paginas, 1, 1, None) == TIPO_CONTA


def test_rotular_conta_por_homologacao(paginas):
    # sem cabeçalho de conta, mas o ato de homologação cai na faixa → conta
    homol = {"pagina": 2, "evento": None, "trecho": "homologo"}
    assert _rotular_run(paginas, 2, 2, homol) == TIPO_CONTA


def test_rotular_oficio(paginas):
    assert _rotular_run(paginas, 3, 3, None) == TIPO_OFICIO


def test_rotular_outro(paginas):
    assert _rotular_run(paginas, 2, 2, None) == TIPO_OUTRO


def test_analisar_shape(pdf_bytes):
    an = analisar(pdf_bytes=pdf_bytes)
    assert an["n_paginas"] == 3
    assert an["escaneadas"] == 0
    assert isinstance(an["paginas"], list) and len(an["paginas"]) == 3
    assert an["cortes_sugeridos"]  # o radar sugeriu ao menos uma faixa
    tipos = {c["tipo"] for c in an["cortes_sugeridos"]}
    assert TIPO_CONTA in tipos  # a conta é o mínimo que precisa aparecer


# ── divisão de run misto conta+ofício (Fix #2) ──────────────────────────
def _pdf_adjacente() -> bytes:
    """conta em p1 e ofício em p2 (ADJACENTES) — o radar tende a fundir num run só."""
    doc = fitz.open()
    for texto in (_CONTA, _OFICIO):
        doc.new_page().insert_text((72, 72), texto, fontsize=11)
    return doc.tobytes()


def test_rotular_runs_divide_conta_e_oficio_adjacentes():
    paginas = P.processar_pdf(_pdf_adjacente())
    # um único run pp1-2 (como o radar entregaria) deve VIRAR dois cortes
    cortes = _rotular_runs(paginas, [(1, 2)], None)
    assert cortes == [
        {"tipo": TIPO_CONTA, "pagina_inicio": 1, "pagina_fim": 1},
        {"tipo": TIPO_OFICIO, "pagina_inicio": 2, "pagina_fim": 2},
    ]


def test_rotular_runs_homogeneo_nao_divide(paginas):
    assert _rotular_runs(paginas, [(1, 1)], None) == [
        {"tipo": TIPO_CONTA, "pagina_inicio": 1, "pagina_fim": 1}]
    assert _rotular_runs(paginas, [(3, 3)], None) == [
        {"tipo": TIPO_OFICIO, "pagina_inicio": 3, "pagina_fim": 3}]


# ── normalização de ente e ref (Fix #7 / #8) ─────────────────────────────
def test_norm_ente_ipajm_devolve_prefixo():
    # o _qp_index da calc casa por prefixo antes de " — "; devolver o rótulo
    # inteiro cairia em "não informar".
    assert _norm_ente("Autarquia IPAJM/ES") == "IPAJM"
    assert _norm_ente("UNIÃO FEDERAL") == "União"
    assert _norm_ente("Estado do Espírito Santo") == "Estado do Espírito Santo"
    assert _norm_ente("Prefeitura de Xique-Xique") is None


def test_montar_query_ref_do_beneficiario():
    campos = {"beneficiario": {"valor": "Fulano de Tal", "citacao": None}}
    q = montar_query(campos, None)
    assert q["ref"] == "Fulano de Tal"
    assert montar_query({}, None).get("ref") is None


# ── corte físico (fitz) ──────────────────────────────────────────────────
def test_cortar_pdf_produz_pecas(pdf_bytes):
    cortes = [
        {"tipo": TIPO_CONTA, "pagina_inicio": 1, "pagina_fim": 1},
        {"tipo": TIPO_OFICIO, "pagina_inicio": 3, "pagina_fim": 3},
    ]
    pecas = cortar_pdf(pdf_bytes, cortes)
    assert len(pecas) == 2
    assert pecas[0]["ref"] == "pp1-1" and pecas[0]["n_paginas"] == 1
    assert pecas[1]["ref"] == "pp3-3"
    # cada peça é um PDF válido com o nº de páginas certo
    for peca, esperado in zip(pecas, (1, 1)):
        d = fitz.open(stream=peca["pdf_bytes"], filetype="pdf")
        assert d.page_count == esperado
        d.close()


def test_cortar_pdf_faixa_de_varias_paginas(pdf_bytes):
    pecas = cortar_pdf(pdf_bytes, [{"tipo": TIPO_CONTA, "pagina_inicio": 1, "pagina_fim": 3}])
    assert len(pecas) == 1 and pecas[0]["n_paginas"] == 3


def test_cortar_pdf_clampa_e_descarta_invalidos(pdf_bytes):
    cortes = [
        {"tipo": TIPO_CONTA, "pagina_inicio": 2, "pagina_fim": 99},   # fim além do doc → clampa p/ 3
        {"tipo": TIPO_OFICIO, "pagina_inicio": "x", "pagina_fim": 1},  # inválido → descarta
    ]
    pecas = cortar_pdf(pdf_bytes, cortes, n_paginas=3)
    assert len(pecas) == 1
    assert pecas[0]["ref"] == "pp2-3" and pecas[0]["n_paginas"] == 2


# ── validação de faixa ───────────────────────────────────────────────────
def test_corte_ref_normaliza_e_valida():
    assert _corte_ref({"pagina_inicio": 5, "pagina_fim": 2}) == (2, 5)   # ordena
    assert _corte_ref({"pagina_inicio": 0, "pagina_fim": 3}) == (1, 3)   # piso 1
    assert _corte_ref({"pagina_inicio": 2, "pagina_fim": 99}, 10) == (2, 10)  # teto
    assert _corte_ref({"pagina_inicio": None, "pagina_fim": 3}) is None
    assert _corte_ref({"pagina_inicio": "a", "pagina_fim": "b"}) is None


# ── extração dos cortes (LLM fake) ───────────────────────────────────────
def test_extrair_cortes_ok(paginas):
    cortes = [
        {"tipo": TIPO_CONTA, "pagina_inicio": 1, "pagina_fim": 1},
        {"tipo": TIPO_OFICIO, "pagina_inicio": 3, "pagina_fim": 3},
    ]
    res = extrair_cortes(paginas, cortes, homol=None, llm=FakeLLM())
    assert res["ok"] is True
    assert res["conta_ref"] == "pp1-1" and res["oficio_ref"] == "pp3-3"
    assert res["prova"]["ok"] is True          # 100k + 50k = 150k fecha
    assert res["query"]["vt"] == "150.000,00"
    assert res["query"]["vp"] == "100.000,00"
    assert res["query"]["hc"] == "30"          # veio do ofício
    assert res["query"]["natureza"] == "remuneratorio"
    assert res["query"]["modalidade"] == "precatorio"
    assert res["query"]["ente"] == "Estado do Espírito Santo"
    assert res["multi_conta"] is False and res["multi_oficio"] is False


def test_extrair_cortes_sem_conta(paginas):
    res = extrair_cortes(paginas, [{"tipo": TIPO_OFICIO, "pagina_inicio": 3, "pagina_fim": 3}],
                         llm=FakeLLM())
    assert res["ok"] is False and "Conta" in res["erro"]


def test_extrair_cortes_multi_conta_sinaliza(paginas):
    cortes = [
        {"tipo": TIPO_CONTA, "pagina_inicio": 1, "pagina_fim": 1},
        {"tipo": TIPO_CONTA, "pagina_inicio": 2, "pagina_fim": 2},
    ]
    res = extrair_cortes(paginas, cortes, llm=FakeLLM())
    assert res["ok"] is True and res["multi_conta"] is True
    assert res["conta_ref"] == "pp1-1"  # usa a primeira


# ── paridade assistido × autônomo (mesmo caminho compartilhado) ──────────
def test_paridade_extrair_cortes_vs_preencher(pdf_bytes, paginas):
    cortes = [
        {"tipo": TIPO_CONTA, "pagina_inicio": 1, "pagina_fim": 1},
        {"tipo": TIPO_OFICIO, "pagina_inicio": 3, "pagina_fim": 3},
    ]
    assistido = extrair_cortes(paginas, cortes, homol=None, llm=FakeLLM())
    autonomo = preencher(pdf_bytes=pdf_bytes, llm=FakeLLM())
    # o juiz do modo autônomo escolhe pp1-1/pp3-3 (fake) → resultado idêntico
    # no que é compartilhado (campos, prova, query, refs, citações).
    for chave in ("conta_ref", "oficio_ref", "campos", "prova", "query", "citacoes"):
        assert assistido[chave] == autonomo[chave], f"divergiu em {chave}"


# ── 3º modo: peças já recortadas ─────────────────────────────────────────
def _pdf_de(*textos: str) -> bytes:
    doc = fitz.open()
    for t in textos:
        doc.new_page().insert_text((72, 72), t, fontsize=11)
    return doc.tobytes()


@pytest.fixture(scope="module")
def peca_conta() -> bytes:
    return _pdf_de(_CONTA)


@pytest.fixture(scope="module")
def peca_oficio() -> bytes:
    return _pdf_de(_OFICIO)


def test_extrair_pecas_ok(peca_conta, peca_oficio):
    res = extrair_pecas(conta=peca_conta, oficio=peca_oficio, llm=FakeLLM())
    assert res["ok"] is True
    # renumeração: a pág 1 do ofício vira a pág 2 do espaço concatenado
    assert res["pecas"] == {TIPO_CONTA: "pp1-1", TIPO_OFICIO: "pp2-2"}
    assert res["mapa_paginas"]["2"] == {"peca": TIPO_OFICIO, "pagina": 1}
    assert res["prova"]["ok"] is True           # 100k + 50k = 150k fecha
    assert res["query"]["vt"] == "150.000,00"
    assert res["query"]["hc"] == "30"           # veio do ofício
    assert res["query"]["ente"] == "Estado do Espírito Santo"


def test_extrair_pecas_so_conta(peca_conta):
    res = extrair_pecas(conta=peca_conta, llm=FakeLLM())
    assert res["ok"] is True                    # ofício é best-effort
    assert res["pecas"] == {TIPO_CONTA: "pp1-1"}
    assert res["oficio_ref"] is None
    assert res["query"]["vt"] == "150.000,00"


def test_extrair_pecas_sem_conta_recusa(peca_oficio):
    res = extrair_pecas(oficio=peca_oficio, llm=FakeLLM())
    assert res["ok"] is False and res["erro"] == "sem_conta"


def test_extrair_pecas_conta_escaneada_nao_gasta_llm(peca_oficio):
    """Peça imagem pura falha ANTES da chamada — explícito e de graça."""
    doc = fitz.open()
    doc.new_page()                              # página em branco = sem texto
    llm = FakeLLM()
    res = extrair_pecas(conta=doc.tobytes(), oficio=peca_oficio, llm=llm)
    assert res["ok"] is False and res["erro"] == "conta_escaneada"
    assert res["chars"] == 0
    assert llm.prompts == []                    # nenhum token gasto


def test_paridade_pecas_vs_cortes(peca_conta, peca_oficio):
    """Duas peças separadas ≡ as mesmas duas páginas cortadas de um PDF só."""
    juntas = P.processar_pdf(_pdf_de(_CONTA, _OFICIO))
    por_corte = extrair_cortes(juntas, [
        {"tipo": TIPO_CONTA, "pagina_inicio": 1, "pagina_fim": 1},
        {"tipo": TIPO_OFICIO, "pagina_inicio": 2, "pagina_fim": 2},
    ], homol=None, llm=FakeLLM())
    por_peca = extrair_pecas(conta=peca_conta, oficio=peca_oficio, llm=FakeLLM())
    for chave in ("conta_ref", "oficio_ref", "campos", "prova", "query", "citacoes"):
        assert por_corte[chave] == por_peca[chave], f"divergiu em {chave}"


# ── salvage_json: o modelo embrulha em array ─────────────────────────────
def test_salvage_json_desembrulha_array_de_um():
    """Visto no gemini (caso 1289): extração perfeita dentro de `[{...}]`.
    Sem desembrulhar, o chamador recebe list e o caso morre em `.get`."""
    assert salvage_json('[{"valor_total": {"valor": "1,00"}}]') == {"valor_total": {"valor": "1,00"}}
    assert salvage_json('```json\n[{"a": 1}]\n```') == {"a": 1}


def test_salvage_json_array_ambiguo_vira_none():
    """Vários objetos = qual é a conta? Abster é mais barato que escolher."""
    assert salvage_json('[{"a": 1}, {"a": 2}]') is None
    assert salvage_json('[1, 2, 3]') is None


def test_salvage_json_dict_normal_intacto():
    assert salvage_json('{"a": 1}') == {"a": 1}
    assert salvage_json("lixo sem json") is None


# ── ente fora da lista fixa e referência do caso ──────────────────────────
def _campos(**kv):
    return {k: {"valor": v, "citacao": {"pagina": 1, "trecho": ""}} for k, v in kv.items()}


def test_ente_conhecido_vai_para_a_opcao_canonica():
    q = montar_query(_campos(ente_devedor="ESTADO DO ESPIRITO SANTO"), None)
    assert q["ente"] == "Estado do Espírito Santo"
    assert "ente_outro" not in q


def test_ente_fora_da_lista_cai_em_outro_com_texto_livre():
    """Caso 1653: o ofício declara 'Estado de Pernambuco', que não está na lista
    da calculadora — antes o campo ficava vazio apesar da extração ter acertado."""
    q = montar_query(_campos(ente_devedor="Estado de Pernambuco"), None)
    assert q["ente"] == P.ENTE_OUTRO
    assert q["ente_outro"] == "Estado de Pernambuco"


def test_alagoas_estado_e_autarquia_nao_se_confundem():
    """A autarquia tem "alagoas" no nome: se a chave do estado vier primeiro no
    `_ENTE_KNOWN`, todo precatório da Alagoas Previdência cai em "Estado de
    Alagoas" — ente errado no memorial e no card."""
    assert montar_query(_campos(ente_devedor="ALAGOAS PREVIDENCIA"), None)["ente"] == "Alagoas Previdência"
    assert montar_query(_campos(ente_devedor="Alagoas Previdência"), None)["ente"] == "Alagoas Previdência"
    assert montar_query(_campos(ente_devedor="ESTADO DE ALAGOAS"), None)["ente"] == "Estado de Alagoas"


def test_entes_mapeados_existem_no_seletor_do_app():
    """Rótulo devolvido pelo prefill que não exista LETRA A LETRA no
    `_ENTE_OPCOES` deixa o seletor em '(não informar)' — falha silenciosa."""
    app = (_RAIZ / "Calculadora.py").read_text(encoding="utf-8")
    for _chave, opcao in P._ENTE_KNOWN:
        assert f'"{opcao}' in app, opcao  # prefixo: IPAJM entra como "IPAJM — ..."


def test_ente_outro_casa_com_a_opcao_do_app():
    """A constante é acoplada ao `_ENTE_OPCOES` do Calculadora.py — se alguém
    renomear a opção lá, o seletor volta a ficar em '(não informar)'."""
    app = (_RAIZ / "Calculadora.py").read_text(encoding="utf-8")
    assert f'"{P.ENTE_OUTRO}"' in app


def test_ref_junta_beneficiario_e_numero_do_precatorio():
    q = montar_query(_campos(beneficiario="FULANO DE TAL",
                             numero_precatorio="0001234-56.2024.8.17.0001"), None)
    assert q["ref"] == "FULANO DE TAL — 0001234-56.2024.8.17.0001"


def test_ref_sobrevive_a_um_dos_dois_faltando():
    assert montar_query(_campos(beneficiario="FULANO"), None)["ref"] == "FULANO"
    assert montar_query(_campos(numero_precatorio="0001234-56.2024.8.17.0001"), None)["ref"] \
        == "0001234-56.2024.8.17.0001"
    assert "ref" not in montar_query(_campos(), None)


# ── número CNJ determinístico (regex, sem LLM) ────────────────────────────
from prefill.deterministico import numero_cnj  # noqa: E402


def test_cnj_unico_no_documento_vira_campo():
    """Visto num ofício real: o número aparecia 3× no documento e o LLM devolveu
    null, porque a peça não o rotula como 'precatório nº'. Formato fechado é
    trabalho de regex, não de modelo. (Número abaixo é sintético.)"""
    paginas = ["cabeçalho", "Requisição 0000123-45.2024.8.17.8201 — Natureza Alimentar",
               "rodapé 0000123-45.2024.8.17.8201"]
    r = numero_cnj(paginas)
    assert r["numero_precatorio"]["valor"] == "0000123-45.2024.8.17.8201"
    assert r["numero_precatorio"]["citacao"]["pagina"] == 2   # 1ª ocorrência
    assert r["numero_precatorio"]["fonte"] == "regex"


def test_cnj_ambiguo_abstem():
    """Dois números = qual é o precatório e qual é o originário? Só o humano
    (ou o LLM, que lê o rótulo) decide — o regex sai de cena."""
    assert numero_cnj(["orig 0000001-11.2019.8.17.0001 e prec 0000123-45.2024.8.17.8201"]) == {}
    assert numero_cnj(["sem número nenhum"]) == {}


def test_cnj_so_procura_nas_paginas_do_oficio(peca_conta, peca_oficio):
    """A conta traz o número do processo de ORIGEM; varrer as duas peças faria
    o originário competir com o do precatório."""
    conta = _pdf_de(_CONTA + "\nProcesso originário 0000001-11.2019.8.17.0001\n")
    oficio = _pdf_de(_OFICIO + "\nRequisição 0000123-45.2024.8.17.8201\n")
    res = extrair_pecas(conta=conta, oficio=oficio, llm=FakeLLM())
    assert res["ok"] is True
    assert res["campos"]["numero_precatorio"]["valor"] == "0000123-45.2024.8.17.8201"
    assert "0000123-45.2024.8.17.8201" in res["query"]["ref"]


# ── sentença/acórdão: só a natureza, e só quando a conta calou ────────────
_SENTENCA = (
    "SENTENÇA\n"
    "Trata-se de ação indenizatória. JULGO PROCEDENTE o pedido e condeno o réu "
    "ao pagamento de danos morais no valor de R$ 100.000,00.\n"
)


@pytest.fixture(scope="module")
def peca_sentenca() -> bytes:
    return _pdf_de(_SENTENCA)


def test_sentenca_preenche_natureza_quando_a_conta_nao_traz(peca_conta, peca_sentenca):
    llm = FakeLLM(conta_sem_natureza=True)
    res = extrair_pecas(conta=peca_conta, sentencas=[peca_sentenca], llm=llm)
    assert res["ok"] is True
    assert res["campos"]["natureza_tributaria"]["valor"] == "indenizatorio"
    assert res["query"]["natureza"] == "indenizatorio"
    assert llm.chamadas("SENTENÇA ou ACÓRDÃO") == 1


def test_sentenca_NAO_e_lida_quando_a_conta_ja_declarou(peca_conta, peca_sentenca):
    """Chamada condicional: 2/3 dos casos já têm a natureza na conta, e uma
    chamada de LLM a mais em todo caso seria custo puro."""
    llm = FakeLLM()                                   # conta traz 'remuneratorio'
    res = extrair_pecas(conta=peca_conta, sentencas=[peca_sentenca], llm=llm)
    assert res["campos"]["natureza_tributaria"]["valor"] == "remuneratorio"
    assert llm.chamadas("SENTENÇA ou ACÓRDÃO") == 0


def test_varias_sentencas_ganham_rotulo_numerado(peca_conta, peca_sentenca):
    res = extrair_pecas(conta=peca_conta, sentencas=[peca_sentenca, peca_sentenca],
                        llm=FakeLLM(conta_sem_natureza=True))
    assert res["pecas"][f"{TIPO_SENTENCA} 1"] == "pp2-2"
    assert res["pecas"][f"{TIPO_SENTENCA} 2"] == "pp3-3"
    assert res["mapa_paginas"]["3"] == {"peca": f"{TIPO_SENTENCA} 2", "pagina": 1}


def test_uma_sentenca_so_nao_numera(peca_conta, peca_sentenca):
    res = extrair_pecas(conta=peca_conta, sentencas=[peca_sentenca],
                        llm=FakeLLM(conta_sem_natureza=True))
    assert TIPO_SENTENCA in res["pecas"]


def test_borda_pega_comeco_e_fim_e_pula_o_miolo():
    """Ementa e dispositivo. Acórdão vai a 59 páginas no corpus — mandar tudo
    seria pagar fundamentação para ler uma palavra."""
    from prefill.extracao import _faixa_borda
    assert _faixa_borda(1, 4) == [1, 2, 3, 4]          # curto: manda inteiro
    assert _faixa_borda(1, 20) == [1, 2, 3, 18, 19, 20]
    assert _faixa_borda(10, 30) == [10, 11, 12, 28, 29, 30]


# ── OCR: a peça escaneada deixa de ser beco sem saída ─────────────────────
from prefill import ocr as _ocr_mod  # noqa: E402


def _pdf_em_branco(paginas: int = 1) -> bytes:
    doc = fitz.open()
    for _ in range(paginas):
        doc.new_page()          # sem texto = o que um scan produz
    return doc.tobytes()


def test_ocr_desligavel_por_env(monkeypatch):
    """`PREFILL_OCR=off` precisa desligar sem depender de desinstalar nada."""
    monkeypatch.setenv("PREFILL_OCR", "off")
    assert _ocr_mod.binario() is None and _ocr_mod.disponivel() is False


def test_conta_escaneada_passa_a_ser_lida_com_ocr(peca_oficio):
    """Antes: 'a conta é uma imagem', fim. ~1 em 5 contas do corpus é assim."""
    def _ocr_falso(page):
        return ("RESUMO DO CÁLCULO\nPrincipal corrigido 100.000,00\n"
                "Juros moratórios 50.000,00\nTotal geral 150.000,00\n"
                "Data do cálculo 15/01/2025\n")

    res = extrair_pecas(conta=_pdf_em_branco(), oficio=peca_oficio,
                        llm=FakeLLM(), ocr_fn=_ocr_falso)
    assert res["ok"] is True, res.get("erro")
    assert res["conta_por_ocr"] is True, "a proveniência não chegou à tela"


def test_sem_ocr_a_recusa_continua(peca_oficio):
    """`ocr_fn=None` explícito: a guarda antiga vale, e de graça (sem LLM)."""
    llm = FakeLLM()
    res = extrair_pecas(conta=_pdf_em_branco(), oficio=peca_oficio,
                        llm=llm, ocr_fn=None)
    assert res["ok"] is False and res["erro"] == "conta_escaneada"
    assert llm.prompts == [], "gastou token numa peça ilegível"


def test_peca_nativa_nao_paga_ocr(peca_conta, peca_oficio):
    """Página com texto nunca chama o OCR — são ~4s por página."""
    chamadas = []
    extrair_pecas(conta=peca_conta, oficio=peca_oficio, llm=FakeLLM(),
                  ocr_fn=lambda page: chamadas.append(1) or "")
    assert chamadas == [], "chamou OCR em página nativa"


def test_conta_nativa_nao_marca_proveniencia_de_ocr(peca_conta):
    res = extrair_pecas(conta=peca_conta, llm=FakeLLM(), ocr_fn=None)
    assert res["conta_por_ocr"] is False


# ── trava da AGREGAÇÃO: valor que não existe na conta é rejeitado ─────────
# O caso real (números inventados): a conta traz "Total Partes" e "Total de
# Sucumbências" separados e o modelo SOMA as duas células. Como as parcelas
# vêm somadas do mesmo jeito, a prova fechava e a tela dizia "✅ A conta fecha".
_CONTA_AGREGADA = (
    "RESUMO DO CÁLCULO\n"
    "Conta de liquidação homologada — Projef\n"
    "Principal Total Partes 100.000,00\n"
    "Principal Total de Sucumbências 20.000,00\n"
    "Juros moratórios 50.000,00\n"
    "Total geral da execução 170.000,00\n"
    "Data do cálculo 15/01/2025\n"
)
_VP_AGREGADO = {"valor": "120.000,00", "citacao_pagina": 1,
                "citacao_trecho": "Total Partes -> 100.000,00; Total de Sucumbências -> 20.000,00"}


def _llm_que_agrega() -> "FakeLLM":
    llm = FakeLLM()
    llm._conta = dict(_CONTA_JSON)
    llm._conta["valor_principal"] = dict(_VP_AGREGADO)       # 100k + 20k: não existe
    llm._conta["valor_total"] = {"valor": "170.000,00", "citacao_pagina": 1,
                                 "citacao_trecho": "Total geral da execução 170.000,00"}
    return llm


def _assert_vp_rejeitado(res, por_ocr=False):
    assert res["ok"] is True, res.get("erro")
    rej = res["rejeitados"]
    assert [r["campo"] for r in rej] == ["valor_principal"]
    assert rej[0]["param"] == "vp" and rej[0]["valor"] == "120.000,00"
    assert "Sucumbências" in rej[0]["citacao"]["trecho"], "o trecho que expõe a soma sumiu"
    assert rej[0]["conta_por_ocr"] is por_ocr
    assert "valor_principal" not in res["campos"]
    assert "vp" not in res["query"], "o valor agregado ainda viaja para a calculadora"
    # com o vp agregado, 120k + 50k = 170k FECHAVA; sem ele a prova não pode dar verde
    assert res["prova"]["ok"] is not True
    # o resto, que existe na conta, segue normal
    assert res["query"]["vt"] == "170.000,00" and res["query"]["vj"] == "50.000,00"


def test_agregado_rejeitado_no_modo_pecas(peca_oficio):
    res = extrair_pecas(conta=_pdf_de(_CONTA_AGREGADA), oficio=peca_oficio, llm=_llm_que_agrega())
    _assert_vp_rejeitado(res)


def test_agregado_rejeitado_no_modo_assistido():
    pgs = P.processar_pdf(_pdf_de(_CONTA_AGREGADA, _RUIDO, _OFICIO))
    res = extrair_cortes(pgs, [{"tipo": TIPO_CONTA, "pagina_inicio": 1, "pagina_fim": 1},
                               {"tipo": TIPO_OFICIO, "pagina_inicio": 3, "pagina_fim": 3}],
                         homol=None, llm=_llm_que_agrega())
    _assert_vp_rejeitado(res)


def test_agregado_rejeitado_no_modo_autonomo():
    res = preencher(pdf_bytes=_pdf_de(_CONTA_AGREGADA, _RUIDO, _OFICIO), llm=_llm_que_agrega())
    _assert_vp_rejeitado(res)


def test_agregado_no_oficio_nao_salva_o_valor():
    """Controle negativo ponta a ponta: o ofício traz exatamente o número somado,
    mas o extrator leu a CONTA — o valor continua inexistente onde foi lido."""
    oficio = _pdf_de(_OFICIO.replace("150.000,00", "120.000,00"))
    res = extrair_pecas(conta=_pdf_de(_CONTA_AGREGADA), oficio=oficio, llm=_llm_que_agrega())
    _assert_vp_rejeitado(res)


def test_agregado_em_conta_por_ocr_marca_a_proveniencia(peca_oficio):
    res = extrair_pecas(conta=_pdf_em_branco(), oficio=peca_oficio, llm=_llm_que_agrega(),
                        ocr_fn=lambda page: _CONTA_AGREGADA)
    _assert_vp_rejeitado(res, por_ocr=True)


def test_valor_legitimo_nao_e_rejeitado(peca_conta, peca_oficio):
    """Regressão: o caminho normal (todos os valores estão na conta) fica intacto."""
    res = extrair_pecas(conta=peca_conta, oficio=peca_oficio, llm=FakeLLM())
    assert res["rejeitados"] == []
    assert res["query"]["vp"] == "100.000,00" and res["prova"]["ok"] is True


def test_zero_de_juros_nao_e_rejeitado(peca_conta):
    """O prompt manda devolver 0 quando a conta não destaca juros."""
    llm = FakeLLM()
    llm._conta = dict(_CONTA_JSON)
    llm._conta["valor_juros"] = {"valor": "0,00", "citacao_pagina": 1, "citacao_trecho": ""}
    res = extrair_pecas(conta=peca_conta, llm=llm)
    assert res["rejeitados"] == []
