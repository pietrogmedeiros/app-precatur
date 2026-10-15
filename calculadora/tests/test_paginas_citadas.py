"""Visualizador das citações: a página de onde o número saiu, com ele destacado.

É o que fecha a conferência — sem isto o advogado só tem a palavra do modelo e
um "pág. 7". O teste não usa LLM (nem precisa): a rota consome as citações que a
extração produz, e é esse contrato que está sendo verificado.

O caso que justifica o teste é a TRADUÇÃO da página: as citações vêm no espaço
concatenado das peças (conta 1..n, ofício em seguida), e renderizar a pág 7 do
concatenado como pág 7 da conta mostraria a página errada — ou nenhuma.
"""
from __future__ import annotations

import base64
import os

import fitz
import pytest

os.environ.setdefault("PREFILL_ENABLED", "1")

import rotas_documentos as R  # noqa: E402


def _pdf(paginas: list[str]) -> bytes:
    doc = fitz.open()
    for texto in paginas:
        pg = doc.new_page()
        pg.insert_text((72, 144), texto, fontsize=12)
    return doc.tobytes()


@pytest.fixture
def sessao_de_duas_pecas():
    """Conta de 2 páginas + ofício de 1, como `extrair_pecas` as concatena."""
    conta = _pdf(["sem valor nesta pagina", "Total apurado R$ 183.087,97"])
    oficio = _pdf(["Processo 0801539-43.2019.8.12.0017"])
    sid = R._guardar([], {}, pdfs={"Conta homologada": conta, "Ofício requisitório": oficio})
    R._anotar_citacoes(sid, {
        # pág 2 do concatenado = pág 2 da conta; pág 3 = pág 1 do ofício
        "citacoes": {"2": ["183.087,97"], "3": ["0801539-43.2019.8.12.0017"]},
        "mapa_paginas": {"2": {"peca": "Conta homologada", "pagina": 2},
                         "3": {"peca": "Ofício requisitório", "pagina": 1}},
    })
    yield sid
    R._SESSOES.pop(sid, None)


def test_renderiza_cada_citacao_na_peca_e_pagina_certas(sessao_de_duas_pecas):
    paginas = R.paginas_citadas(sessao_de_duas_pecas)["paginas"]
    onde = {(p["peca"], p["pagina"]): p for p in paginas}

    assert set(onde) == {("Conta homologada", 2), ("Ofício requisitório", 1)}
    for p in paginas:
        assert p["n_marcas"] >= 1, f"{p['peca']} pág {p['pagina']} saiu sem destaque"
        assert base64.b64decode(p["png"])[:4] == b"\x89PNG"


def test_valor_que_nao_esta_na_pagina_devolve_pagina_sem_marca():
    """Não achar é informação: o número não está escrito assim ali.

    Devolver a página mesmo assim é de propósito — sumir com ela deixaria o
    advogado sem saber se o modelo citou a página errada ou se a tela falhou.
    """
    sid = R._guardar([], {}, pdfs={"Conta homologada": _pdf(["nada aqui"])})
    R._anotar_citacoes(sid, {"citacoes": {"1": ["999.999,99"]},
                             "mapa_paginas": {"1": {"peca": "Conta homologada", "pagina": 1}}})
    try:
        paginas = R.paginas_citadas(sid)["paginas"]
        assert len(paginas) == 1
        assert paginas[0]["n_marcas"] == 0
    finally:
        R._SESSOES.pop(sid, None)


def test_sem_mapa_a_pagina_citada_e_a_do_proprio_processo():
    """Modos 'autônomo' e 'assistente de corte': um PDF só, sem concatenação."""
    sid = R._guardar([], {}, pdfs={R.PECA_PROCESSO: _pdf(["pagina um", "Total R$ 42,00"])})
    R._anotar_citacoes(sid, {"citacoes": {"2": ["42,00"]}, "mapa_paginas": {}})
    try:
        paginas = R.paginas_citadas(sid)["paginas"]
        assert [(p["peca"], p["pagina"]) for p in paginas] == [(R.PECA_PROCESSO, 2)]
        assert paginas[0]["n_marcas"] >= 1
    finally:
        R._SESSOES.pop(sid, None)


def test_sessao_expirada_pede_o_pdf_de_novo():
    from fastapi import HTTPException
    with pytest.raises(HTTPException) as erro:
        R.paginas_citadas("0" * 32)
    assert erro.value.status_code == 410
