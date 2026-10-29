"""Nível 0 do PJe (`prefill/pje.py`) — índice + carimbo, ZERO LLM.

Reproduz, num PDF sintético (nomes e números fictícios), a anatomia do caso
#3481 (TJMG, 05/10/2026) que motivou o módulo:

  - o índice lista os documentos com título e tipo em colunas;
  - o laudo traz DUAS contas (a antiga e a operativa) — só a âncora do
    dispositivo distingue;
  - a sentença diz "conforme apontado pelo Perito", não "homologo";
  - os embargos corrigem a data da sentença, e a intimação repete a decisão;
  - o ofício do cartório tem principal = bruto e data-base errada;
  - o formulário de honorários é juntado duas vezes (versões);
  - a certidão de aprovação CITA "ofício precatório" sem ser um;
  - uma página escaneada só tem o carimbo como texto.
"""
from __future__ import annotations

import sys
from pathlib import Path

import fitz
import pytest

_RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_RAIZ))

from prefill import pipeline as P  # noqa: E402
from prefill import pje as J  # noqa: E402
from prefill.substrato import processar_pdf  # noqa: E402

# Id → (data, título, tipo, [páginas de conteúdo])
_LAUDO = "4600000021"
_SENT = "6200000060"
_INTIM = "6400000006"
_EMB = "8000000096"
_PET = "9500000470"
_OF_PRINC = "9600000381"
_OF_HON_V1 = "9700000608"
_OF_HON_V2 = "9700000916"
_CERT = "9900000543"

_LAUDO_P1 = """Perito Contábil - Página 1 de 2
Valores atualizados a 04/2020 (verificação do excesso):
Valor Atualizado 10.000,00 Juros 5.000,00 Total 15.000,00
Valores atualizados a 07/2021 (data do laudo):
Valor Atualizado 12.000,00 Juros 8.000,00 Total 20.000,00"""
_LAUDO_P2 = """Perito Contábil - Página 2 de 2
Valor Atualizado a 07/2021 R$ 12.000,00
Juros Moratórios R$ 8.000,00
Sub Total R$ 20.000,00
Honorários Advocatícios R$ 2.000,00
Valor Total R$ 22.000,00"""
_SENTENCA = f"""SENTENÇA
Laudo pericial juntado em id. {_LAUDO}.
Conforme ff. 01/02 do id. {_LAUDO}, segundo o perito, não houve excesso.
O executado alegou que o devido seria R$ 13.000,00.
III - DISPOSITIVO
Do exposto, NÃO ACOLHO a impugnação, condenando o Município a pagar
os valores corrigidos até 13/10/2020, conforme o Perito, qual seja R$ 22.000,00."""
_EMBARGOS = f"""SENTENÇA
Embargos de declaração. Erro material: o perito atualizou até 15/07/2021,
conforme laudo pericial de Id. {_LAUDO}. ACOLHO para que passe a constar:
"Do exposto, NÃO ACOLHO a impugnação, condenando o Município a pagar os valores
corrigidos até 15/07/2021, conforme apontado pelo Perito, qual seja R$ 22.000,00." """
_PETICAO = """Petição: o valor total da condenação, até 15/07/21, é R$ 22.000,00,
sendo o principal R$ 20.000,00 e os honorários sucumbenciais R$ 2.000,00."""
_OFICIO_PRINC_1 = """OFÍCIO PRECATÓRIO - BENEFICIÁRIO PRINCIPAL
Resolução nº 303/2019 do Conselho Nacional de Justiça
Nº 11500072 / 2022
REQUISIÇÃO PARA PAGAMENTO DE PRECATÓRIO
1.1. Numeração única do processo judicial:
5000999-51.2020.8.13.0140
2.20. Valor destacado:
R$
2.35. Data-base:
__/__/___
3.1. Entidade devedora / Ente devedor:
MUNICÍPIO DE VILA FICTÍCIA
4.1. Nome do beneficiário principal:
FULANO DE TAL
4.15. Valor Bruto:
R$20.000,00"""
_OFICIO_PRINC_2 = """4.16. Valor Principal Corrigido:
R$20.000,00
4.17. Data-base:
(data correspondente ao termo final utilizado na
elaboração da conta de liquidação).
28/12/2012
4.20. Valor da assistência médica:
R$
4.32. Valor dos juros moratórios:
R$8.000,00
5.3. VALOR TOTAL REQUISITADO: (=soma de 1+2):
R$20.000,00"""


def _oficio_hon(preenchido: bool) -> str:
    v = (lambda x: x) if preenchido else (lambda x: "")
    return f"""OFÍCIO PRECATÓRIO - BENEFICIÁRIO DOS HONORÁRIOS SUCUMBENCIAIS
Nº 13300099 / 2023
REQUISIÇÃO PARA PAGAMENTO DE PRECATÓRIO
4.1. Nome do beneficiário dos honorários sucumbenciais:
{v('BELTRANA ADVOGADA')}
5.1. Valor Bruto:
R$ {v('2.000,00')}
5.2. Valor Principal Corrigido:
R${v('1.200,00')}
5.3. Data-base:
{v('15/07/2021')}
5.5.1. Valor correspondente dos juros moratórios:
R${v('800,00')}"""


_CERTIDAO = """CERTIDÃO DE APROVAÇÃO DE OFÍCIO PRECATÓRIO Nº 15000065 / 2023
Certifico que o Ofício Precatório foi aprovado."""

# (id, data, título, tipo, [páginas])
_DOCS = [
    (_LAUDO, "15/07/2021", "Laudo Pericial", "Laudo Pericial", [_LAUDO_P1, _LAUDO_P2]),
    (_SENT, "20/10/2021", "Sentença", "Sentença", [_SENTENCA]),
    (_INTIM, "21/10/2021", "Sentença", "Intimação", [_SENTENCA]),
    (_EMB, "31/01/2022", "Despacho", "Sentença", [_EMBARGOS]),
    (_PET, "02/09/2022", "Expedição de precatório autônomo", "Manifestação", [_PETICAO]),
    (_OF_PRINC, "02/12/2022", "Formulário-Ofício Precatório-Beneficiário Principal",
     "Documento de Comprovação", [_OFICIO_PRINC_1, None, _OFICIO_PRINC_2]),  # None = escaneada
    (_OF_HON_V1, "12/04/2023", "Formulário Ofício Honorários Sucumbenciais", "Formulários",
     [_oficio_hon(False)]),
    (_OF_HON_V2, "14/04/2023", "SEI - Formulário-Ofício Honorários Sucumbenciais",
     "Documento de Comprovação", [_oficio_hon(True)]),
    (_CERT, "26/04/2024", "Certidão de Aprovação de Ofício Precatório", "Certidão", [_CERTIDAO]),
]


def _escrever(page, texto, x=40, y=60, fs=9):
    for i, linha in enumerate(texto.splitlines()):
        page.insert_text((x, y + i * 12), linha, fontsize=fs)


def _pdf_pje() -> bytes:
    doc = fitz.open()
    # índice em colunas, como o PJe exporta (Tipo no x≈473, título no x≈197)
    idx = doc.new_page()
    _escrever(idx, "PJe - Processo Judicial Eletrônico\nNúmero: 5000999-51.2020.8.13.0140")
    y = 160
    for x, w in ((63, "Id."), (107, "Data da Assinatura"), (197, "Documento"), (473, "Tipo")):
        idx.insert_text((x, y), w, fontsize=9)
    for d, data, titulo, tipo, _ in _DOCS:
        y += 14
        idx.insert_text((45, y), d, fontsize=9)
        idx.insert_text((102, y), data, fontsize=9)
        idx.insert_text((150, y), "10:00", fontsize=9)
        # título longo quebra linha, como no PJe
        corte = titulo.rfind(" ", 0, 40) if len(titulo) > 40 else -1
        t1, t2 = (titulo[:corte], titulo[corte:]) if corte > 0 else (titulo, "")
        idx.insert_text((197, y), t1, fontsize=9)
        idx.insert_text((430, y), tipo, fontsize=9)
        if t2:
            y += 10
            idx.insert_text((197, y), t2.strip(), fontsize=9)
    for d, _, _, _, paginas in _DOCS:
        for n, conteudo in enumerate(paginas, start=1):
            page = doc.new_page()
            page.insert_text((40, 30), f"Num. {d} - Pág. {n}", fontsize=7)
            if conteudo:
                _escrever(page, conteudo)
            if d == _OF_PRINC and n == 1:
                # checkbox: o X à esquerda da opção marcada, na mesma linha
                page.insert_text((40, 400), "2.1. Natureza do Crédito", fontsize=9)
                page.insert_text((200, 400), "X", fontsize=9)
                page.insert_text((212, 400), "Comum OU", fontsize=9)
                page.insert_text((280, 400), "Alimentar/Preferencial", fontsize=9)
    return doc.tobytes()


def _pagina_de(pdf: bytes, doc_id: str, n: int = 1) -> int:
    d = fitz.open(stream=pdf, filetype="pdf")
    for i in range(d.page_count):
        if f"Num. {doc_id} - Pág. {n}" in d[i].get_text():
            return i + 1
    raise AssertionError(doc_id)


@pytest.fixture(scope="module")
def pdf():
    return _pdf_pje()


@pytest.fixture(scope="module")
def paginas(pdf):
    return processar_pdf(pdf)


@pytest.fixture(scope="module")
def res(pdf, paginas):
    return J.analisar(pdf, paginas)


# ── índice e carimbo ─────────────────────────────────────────────────────
def test_indice_separa_titulo_e_tipo_e_junta_quebra_de_linha(pdf):
    ind = J.ler_indice(fitz.open(stream=pdf, filetype="pdf"))
    assert set(ind) == {d[0] for d in _DOCS}
    assert ind[_INTIM]["titulo"] == "Sentença" and ind[_INTIM]["tipo"] == "Intimação"
    assert ind[_OF_PRINC]["titulo"] == "Formulário-Ofício Precatório-Beneficiário Principal"
    assert ind[_OF_PRINC]["data"] == "2022-12-02"


def test_pagina_sem_carimbo_herda_so_entre_vizinhas_do_mesmo_documento():
    assert J.mapear_paginas(["Num. 111111111 - Pág. 1", "", "Num. 111111111 - Pág. 3"]) == \
        ["111111111"] * 3
    # borda entre dois documentos: não chuta
    assert J.mapear_paginas(["Num. 111111111 - Pág. 1", "", "Num. 222222222 - Pág. 1"])[1] is None


def test_carimbo_vem_do_pdf_mesmo_quando_o_substrato_zerou_a_pagina(pdf, paginas, res):
    """Página só com carimbo fica abaixo de MIN_TEXTO_NATIVO e o substrato zera
    o texto dela; o mapeamento não pode depender disso (#3481: 55 páginas)."""
    pg = _pagina_de(pdf, _OF_PRINC, 2)
    assert not paginas[pg - 1]["nativa"] and paginas[pg - 1]["texto"] == ""
    assert res["paginas_mapeadas"] == res["n_paginas"] - 1  # só o índice fica sem Id


def test_pdf_fora_do_pje_devolve_none():
    doc = fitz.open()
    _escrever(doc.new_page(), "RESUMO DO CÁLCULO\nTotal 1.000,00")
    assert J.analisar(doc.tobytes()) is None


# ── conta homologada ─────────────────────────────────────────────────────
def test_conta_e_o_documento_citado_pelas_decisoes_com_ancora_na_pagina_operativa(pdf, res):
    c = res["conta"]
    assert c["id"] == _LAUDO
    assert c["votos"] >= 3
    # a âncora é o valor do dispositivo, na página do RESUMO (a 1ª tem a conta antiga)
    assert c["ancora"]["valor"] == "22.000,00"
    assert c["ancora"]["pagina"] == _pagina_de(pdf, _LAUDO, 2)


def test_peticao_que_transcreve_o_valor_nao_vira_conta(res):
    assert res["conta"]["id"] != _PET


def test_decisao_decisiva_e_a_mais_recente_e_nao_a_copia_da_intimacao(res):
    d = res["decisao"]
    assert d["id"] == _EMB
    assert d["datas"] == ["2021-07-15"]
    # valor rejeitado na fundamentação (13.000,00) não entra
    assert "13.000,00" not in d["valores"]


def test_sentencas_pelo_tipo_do_indice_sem_a_copia_da_intimacao(res):
    # o embargo tem título "Despacho" e tipo "Sentença": vale o tipo
    assert [d["id"] for d in res["sentencas"]] == [_SENT, _EMB]


# ── ofícios ──────────────────────────────────────────────────────────────
def test_oficio_principal_lido_por_rotulo(res):
    o = next(o for o in res["oficios"] if o["beneficiario_tipo"] == "principal")
    c = o["campos"]
    assert c["valor_bruto"] == "20.000,00"
    assert c["valor_principal"] == "20.000,00"
    assert c["valor_juros"] == "8.000,00"
    # item VAZIO (4.20) não rouba o valor do item seguinte; penhora (2.35) sem data não conta
    assert c["data_base"] == "2012-12-28"
    assert c["ente_devedor"] == "MUNICÍPIO DE VILA FICTÍCIA"
    assert c["beneficiario"] == "FULANO DE TAL"
    assert c["numero_oficio"] == "11500072/2022"
    assert c["numero_processo"] == "5000999-51.2020.8.13.0140"
    assert c["natureza_credito"] == "comum"


def test_versao_preenchida_mais_recente_e_certidao_fora(res):
    ids = [o["id"] for o in res["oficios"]]
    assert _OF_HON_V2 in ids and _OF_HON_V1 not in ids
    assert _CERT not in ids
    assert len(res["oficios"]) == 2


def test_cortes_conta_e_oficio_do_credor_primeiro(res):
    tipos = [(c["tipo"], c["origem"]) for c in res["cortes"]]
    assert tipos[0] == (P.TIPO_CONTA, "pje")
    assert tipos[1] == (P.TIPO_OFICIO, "pje")
    assert "principal" in res["cortes"][1]["motivo"]


# ── alertas ──────────────────────────────────────────────────────────────
def test_alerta_principal_igual_ao_bruto_sugere_bruto_menos_juros(pdf, res):
    al = next(a for a in res["alertas"] if a["tipo"] == "oficio_aritmetica")
    assert al["sugestao"]["valor_principal"] == "12.000,00"
    assert _pagina_de(pdf, _LAUDO, 2) in al["sugestao"]["paginas_conta"]


def test_alerta_data_base_contra_a_decisao(res):
    al = next(a for a in res["alertas"] if a["tipo"] == "oficio_data_base")
    assert "28/12/2012" in al["mensagem"] and "15/07/2021" in al["mensagem"]


def test_alerta_sucumbencia_separada(res):
    al = next(a for a in res["alertas"] if a["tipo"] == "sucumbencia_separada")
    assert "20.000,00" in al["mensagem"]


def test_oficio_de_honorarios_nao_e_cobrado_contra_a_conta(res):
    """Os valores do ofício do advogado são uma fração da conta — não estão
    nela, e cobrá-los seria alarme falso."""
    assert not [a for a in res["alertas"] if a["tipo"] == "oficio_fora_da_conta"]


# ── integração ───────────────────────────────────────────────────────────
def test_pista_so_quando_a_ancora_esta_na_faixa(res):
    a, b = res["conta"]["pagina_inicio"], res["conta"]["pagina_fim"]
    pista = J.pista_conta(res, (a, b))
    assert "22.000,00" in pista and "15/07/2021" in pista
    assert J.pista_conta(res, (1, a - 1)) is None
    assert J.pista_conta(None, (a, b)) is None


def test_campos_oficio_so_do_oficio_dentro_da_faixa(res):
    o = res["cortes"][1]
    campos = J.campos_oficio(res, (o["pagina_inicio"], o["pagina_fim"]))
    assert campos["numero_oficio"]["valor"] == "11500072/2022"
    assert campos["numero_oficio"]["fonte"] == "pje"
    assert J.campos_oficio(res, (1, 1)) == {}


def test_analisar_poe_os_cortes_do_pje_na_frente(pdf):
    r = P.analisar(pdf_bytes=pdf)
    assert r["pje"]["conta"]["id"] == _LAUDO
    assert r["cortes_sugeridos"][0]["origem"] == "pje"
    contas = [c for c in r["cortes_sugeridos"] if c["tipo"] == P.TIPO_CONTA]
    assert len(contas) == 1  # o radar não sugere uma segunda conta


class _FakeLLM:
    custo_total = 0.0

    def __init__(self):
        self.prompts = []

    def responder(self, prompt, max_tokens=8192):
        self.prompts.append(prompt)
        if "conta_ref" in prompt:
            raise AssertionError("o juiz LLM não deveria rodar quando o PJe achou a conta")
        if "dados de um OFÍCIO" in prompt:
            return '{"numero_oficio": {"valor": null}}', {}
        return ('{"valor_total": {"valor": "20.000,00", "citacao_pagina": 3}, '
                '"valor_principal": {"valor": "12.000,00", "citacao_pagina": 3}, '
                '"valor_juros": {"valor": "8.000,00", "citacao_pagina": 3}}'), {}


def test_preencher_pula_o_juiz_e_manda_a_pista(pdf):
    llm = _FakeLLM()
    r = P.preencher(pdf_bytes=pdf, llm=llm)
    assert r["ok"], r
    assert r["prova"]["ok"] is True
    assert any("PISTA (lida dos autos, sem IA)" in p for p in llm.prompts)
    # rede do formulário preenche o que a IA devolveu nulo
    assert r["campos"]["numero_oficio"]["valor"] == "11500072/2022"
    assert {a["tipo"] for a in r["alertas_pje"]} >= {"oficio_aritmetica", "sucumbencia_separada"}
    # a sentença e o embargo vão como faixas para anexar no card
    assert len(r["sentenca_refs"]) == 2


# ── TJES (card #6105, 29/10/2026): Id de 8 dígitos, que quebra linha no índice,
# sentença como "Documento de comprovação" e formulário de requisição próprio ──


def test_carimbo_com_id_de_8_digitos():
    assert J.mapear_paginas(["texto\nNum. 28498531 - Pág. 1"]) == ["28498531"]


def test_indice_junta_id_que_quebrou_linha():
    doc = fitz.open()
    p = doc.new_page()
    p.insert_text((38, 100), "Id.", fontsize=8)
    p.insert_text((68, 100), "Data", fontsize=8)
    p.insert_text((143, 100), "Documento", fontsize=8)
    p.insert_text((490, 100), "Tipo", fontsize=8)
    for y, fim, titulo in ((130, "537", "Doc. 04 - Sentença"), (170, "539", "Doc. 06 - Acórdão")):
        p.insert_text((38, y), "28498", fontsize=8)
        p.insert_text((68, y), "25/07/2023", fontsize=8)
        p.insert_text((115, y), "09:13", fontsize=8)
        p.insert_text((143, y), titulo, fontsize=8)
        p.insert_text((440, y), "Documento de comprovação", fontsize=8)
        p.insert_text((43, y + 12), fim, fontsize=8)
    ind = J.ler_indice(doc)
    assert set(ind) == {"28498537", "28498539"}
    assert ind["28498537"]["titulo"] == "Doc. 04 - Sentença"
    assert ind["28498537"]["tipo"] == "Documento de comprovação"


@pytest.mark.parametrize("titulo, tipo, esperado", [
    ("Doc. 04 - Sentença", "Documento de comprovação", True),
    ("Doc. 08 - Acórdão de julgamento dos embargos", "Documento de comprovação", True),
    ("Despacho", "Sentença", True),
    ("Cumprimento de Sentença", "Petição Inicial", False),
    ("Sentença", "Intimação", False),
    ("Impugnação à sentença", "Petição (outras)", False),
])
def test_sentenca_pelo_titulo_quando_o_tipo_e_generico(titulo, tipo, esperado):
    assert J._e_sentenca({"titulo": titulo, "tipo": tipo}) is esperado


def test_formulario_de_requisicao_do_tjes():
    doc = fitz.open()
    p = doc.new_page()
    _escrever(p, """REQUISIÇÃO DE PRECATÓRIO/RPV N.º 001/2025
C – NATUREZA DO CRÉDITO
( ) Honorários Sucumbenciais e Indenizações por morte ou invalidez.
F – VALOR REQUISITADO
Valor atualizado do crédito: (oitocentos e dois mil reais) R$ 802.000,00""")
    o = J.ler_oficio(doc, 1, 1)
    assert o["campos"]["valor_total_requisitado"] == "802.000,00"
    assert o["campos"]["numero_oficio"] == "001/2025"
    assert o["beneficiario_tipo"] == "principal"
