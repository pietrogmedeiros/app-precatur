"""Envio ao CRM leva as peças da pré-análise (conta, ofício, sentença).

Antes a rota passava `pecas=None` sempre: no card #8081 (28/10/2026) só o
memorial chegou, e a conta homologada e o ofício que a própria pré-análise
tinha localizado ficaram de fora. A natureza também não ia (a tela mandava
null); isso é coberto do lado do Next.
"""
from __future__ import annotations

import sys
from pathlib import Path

import fitz
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import rotas_crm  # noqa: E402
import rotas_documentos as RD  # noqa: E402
from prefill import pipeline as P  # noqa: E402


def _pdf(n: int) -> bytes:
    doc = fitz.open()
    for i in range(1, n + 1):
        doc.new_page().insert_text((50, 72), f"pagina {i}")
    return doc.tobytes()


def _n_paginas(b: bytes) -> int:
    with fitz.open(stream=b, filetype="pdf") as d:
        return d.page_count


@pytest.fixture(autouse=True)
def _limpa():
    RD._SESSOES.clear()
    yield
    RD._SESSOES.clear()


def test_modo_processo_recorta_a_faixa_de_cada_peca():
    sid = RD._guardar([], {}, pdfs={RD.PECA_PROCESSO: _pdf(10)})
    RD._anotar_faixas(sid, {"conta": (3, 5), "oficio": (8, 8), "sentenca": None})
    pecas, aviso = RD.pecas_da_sessao(sid, 8081)
    assert aviso is None and set(pecas) == {"conta", "oficio"}
    (nome, conta), = pecas["conta"]
    assert nome == "conta_8081_pp3-5.pdf" and _n_paginas(conta) == 3
    assert _n_paginas(pecas["oficio"][0][1]) == 1


def test_modo_pecas_anexa_os_pdfs_como_vieram():
    sid = RD._guardar([], {}, pdfs={P.TIPO_CONTA: _pdf(2), P.TIPO_OFICIO: _pdf(1),
                                    f"{P.TIPO_SENTENCA} 1": _pdf(1), f"{P.TIPO_SENTENCA} 2": _pdf(1)})
    pecas, _ = RD.pecas_da_sessao(sid, 7)
    assert [n for n, _ in pecas["sentenca"]] == ["sentenca_7_1.pdf", "sentenca_7_2.pdf"]
    assert pecas["conta"][0][0] == "conta_7.pdf"


def test_sessao_expirada_avisa_em_vez_de_calar():
    pecas, aviso = RD.pecas_da_sessao("nao-existe", 1)
    assert pecas is None and "expirou" in aviso


def test_faixa_do_modo_autonomo():
    assert RD._faixa("pp126-127") == (126, 127)
    assert RD._faixa(None) is None


def test_enviar_passa_as_pecas_ao_bitrix(monkeypatch):
    sid = RD._guardar([], {}, pdfs={RD.PECA_PROCESSO: _pdf(6)})
    RD._anotar_faixas(sid, {"conta": (2, 3), "oficio": (5, 6)})
    visto = {}

    class BxFalso:
        CAMPO_VALOR = "V"

        def carregar_deal(self, deal_id):
            return {"ID": deal_id}

        def montar(self, deal, **kw):
            visto.update(kw)
            return {}, []

        def enviar(self, deal_id, campos, linhas, aplicar, autor):
            return {"ensaio": not aplicar}

    monkeypatch.setattr(rotas_crm, "_bitrix", lambda: BxFalso())
    r = rotas_crm.enviar({"deal_id": 8081, "valor_liquido": "100,00", "natureza": "remuneratorio",
                          "sessao_prefill": sid, "aplicar": False})
    assert set(visto["pecas"]) == {"conta", "oficio"}
    assert visto["natureza"] == "remuneratorio"
    assert r["pulados"] == []


def test_enviar_sem_sessao_segue_sem_anexo(monkeypatch):
    class BxFalso:
        CAMPO_VALOR = "V"

        def carregar_deal(self, deal_id):
            return {"ID": deal_id}

        def montar(self, deal, **kw):
            assert kw["pecas"] is None
            return {}, []

        def enviar(self, *a, **k):
            return {}

    monkeypatch.setattr(rotas_crm, "_bitrix", lambda: BxFalso())
    r = rotas_crm.enviar({"deal_id": 1, "sessao_prefill": "expirada", "aplicar": False})
    assert any("expirou" in p for p in r["pulados"])
