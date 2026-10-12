"""Número de meses do RRA vindo por URL: nunca derruba a tela.

Antes: `int(_qp_get("meses") or 0)` estourava ValueError com "12.5", "12.500"
ou "abc" — e a tela inteira caía com o traceback. Agora o valor inválido cai
em 0 com um aviso.
"""
from __future__ import annotations

import pytest

from pssir_util import calcular, preencher
from streamlit.testing.v1 import AppTest

from pssir_util import APP


def _abrir(meses: str) -> AppTest:
    at = AppTest.from_file(APP, default_timeout=90)
    at.query_params["meses"] = meses
    at.run()
    return at


def _meses(at):
    return [n for n in at.number_input if "Número de meses" in n.label][0]


@pytest.mark.parametrize("bruto", ["12.5", "12.500", "abc", "-3", "1e2"])
def test_meses_invalido_por_url_cai_em_zero_com_aviso(bruto):
    at = _abrir(bruto)
    assert not at.exception, [e.value for e in at.exception]
    assert _meses(at).value == 0
    assert any("meses" in w.value and bruto in w.value for w in at.warning), \
        [w.value for w in at.warning]


def test_meses_valido_por_url_continua_igual():
    at = _abrir("12")
    assert not at.exception
    assert _meses(at).value == 12
    assert not any("meses" in w.value for w in at.warning)


def test_calcula_normalmente_depois_de_um_meses_invalido():
    at = _abrir("12.500")
    assert not at.exception
    preencher(at, meses=0)
    calcular(at)
    assert not at.exception
