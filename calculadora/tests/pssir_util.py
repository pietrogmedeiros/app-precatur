"""Utilitário dos testes de PSS/IR no modo "Valor no ofício (R$)".

Dirige a Calculadora REAL (AppTest, sem navegador) e espia a PRIMEIRA chamada
de `calculadora.calcular_dict` — a da tela. As seguintes são a grade de
honorários do memorial (`cenarios_honorarios_contratuais`), que refaz o motor
variando só o percentual e por isso não serve de evidência do que o advogado
digitou.
"""
from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

from streamlit.testing.v1 import AppTest

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))
APP = str(RAIZ / "Calculadora.py")

NAT_REMUN = "remuneratorio — salários / vencimentos"
VALOR, NAO = "Valor no ofício (R$)", "Não descontar"
ALIQ, ESTIM = "Por alíquota (%)", "Estimar por natureza"
DATA_CALC = date(2025, 1, 15)


def espiar_motor(monkeypatch) -> dict:
    """{'chamadas': n, 'entrada': 1ª EntradaCalculadora, 'res': 1º resultado}.

    Sem a chave 'entrada' = o motor não foi chamado."""
    from precaturia.pipeline import calculadora

    reg: dict = {"chamadas": 0}
    original = calculadora.calcular_dict

    def _espiao(entrada):
        r = original(entrada)
        reg["chamadas"] += 1
        reg.setdefault("entrada", entrada)
        reg.setdefault("res", r)
        return r

    monkeypatch.setattr(calculadora, "calcular_dict", _espiao)
    return reg


def novo_app(params: dict | None = None) -> AppTest:
    at = AppTest.from_file(APP, default_timeout=90)
    for k, v in (params or {}).items():
        at.query_params[k] = v
    at.run()
    assert not at.exception
    return at


def radios(at: AppTest):
    """(radio do PSS, radio do IR) — não têm key; identifica pelas opções."""
    rp = [r for r in at.radio if "Por alíquota (%)" in (r.options or [])][0]
    ri = [r for r in at.radio if "Estimar por natureza" in (r.options or [])][0]
    return rp, ri


def texto(at: AppTest, key: str):
    return [t for t in at.text_input if t.key == key][0]


def preencher(at: AppTest, *, pss_modo=NAO, pss=None, ir_modo=NAO, ir=None,
              natureza=NAT_REMUN, meses=12, aliq=None, alvo=DATA_CALC,
              vt="150.000,00", vp="100.000,00", vj="50.000,00") -> AppTest:
    """Preenche o formulário (não clica em Calcular). `alvo=DATA_CALC` congela
    a moeda da conta — sem atualização, a conta manual é só subtração."""
    texto(at, "vt").set_value(vt)
    texto(at, "vp").set_value(vp)
    texto(at, "vj").set_value(vj)
    for d in at.date_input:
        if d.label == "Data-base":
            d.set_value(DATA_CALC)
        elif d.label.startswith("Data de atualização"):
            d.set_value(alvo)
    [s for s in at.selectbox if s.label.startswith("Natureza")][0].set_value(natureza)
    rp, ri = radios(at)
    rp.set_value(pss_modo)
    ri.set_value(ir_modo)
    if pss is not None:
        texto(at, "pss").set_value(pss)
    if ir is not None:
        texto(at, "ir").set_value(ir)
    if aliq is not None:
        texto(at, "apss").set_value(aliq)
    [n for n in at.number_input if "Número de meses" in n.label][0].set_value(meses)
    return at


def calcular(at: AppTest) -> AppTest:
    [b for b in at.button if "Calcular" in (b.label or "")][0].click().run()
    return at


def rodar(**kw) -> AppTest:
    return calcular(preencher(novo_app(), **kw))


def erros(at: AppTest) -> list[str]:
    return [e.value for e in at.error]


def tem_memorial(at: AppTest) -> bool:
    return bool(at.get("download_button"))
