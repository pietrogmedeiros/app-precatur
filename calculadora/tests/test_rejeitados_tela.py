"""Valores RECUSADOS pelo prefill na tela: aviso, "usar mesmo assim" e o ledger.

O C2 tira da proposta todo vt/vp/vj/vs que não existe na conta (a trava da
agregação). Estes testes protegem a metade que o advogado vê — porque um campo
que some SEM explicação só troca a caçada manual por outra:

  1. o aviso aparece, com o valor recusado e o trecho que expõe a soma;
  2. "usar mesmo assim" devolve o valor (à query do link / ao campo);
  3. a recusa chega à `observacao` do ledger no envio ao card.

Mesma técnica de test_prefill_handoff / test_fase2_ui: AppTest roda o script
de verdade; `hub`/`bitrix` com as funções de rede monkeypatchadas. Números
inventados.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import pytest
from streamlit.testing.v1 import AppTest

_RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_RAIZ))

from prefill import rejeitados as R  # noqa: E402

_TRECHO = "Total Partes -> 100.000,00; Total de Sucumbências -> 20.000,00"
_REJ = [{"campo": "valor_principal", "param": "vp", "valor": "120.000,00",
         "citacao": {"pagina": 1, "trecho": _TRECHO}, "conta_por_ocr": False}]


# ── funções puras ────────────────────────────────────────────────────────
def test_aplicar_sem_uso_so_anexa_rej():
    q = R.aplicar({"vt": "170.000,00"}, _REJ)
    assert "vp" not in q, "o valor recusado não pode voltar sozinho"
    assert json.loads(q["rej"]) == [{"p": "vp", "v": "120.000,00", "u": 0, "t": _TRECHO}]


def test_aplicar_com_uso_devolve_o_valor():
    q = R.aplicar({"vt": "170.000,00"}, _REJ, {"vp"})
    assert q["vp"] == "120.000,00" and json.loads(q["rej"])[0]["u"] == 1


def test_sem_rejeitados_a_query_fica_intacta():
    assert R.aplicar({"vt": "1,00"}, []) == {"vt": "1,00"}


@pytest.mark.parametrize("lixo", [None, "", "não-json", "{}", '[{"sem_p": 1}]', []])
def test_decodificar_e_tolerante(lixo):
    assert R.decodificar(lixo) == []


def test_observacao_e_json_legivel_de_volta():
    obs = R.observacao(R.decodificar(R.codificar(_REJ, {"vp"})))
    assert json.loads(obs) == {"prefill_rejeitados": [
        {"campo": "vp", "valor": "120.000,00", "usado_mesmo_assim": True, "trecho": _TRECHO}]}
    assert R.observacao([]) is None


def test_mensagem_diz_que_o_campo_ficou_vazio_e_avisa_ocr():
    m = R.mensagem(_REJ[0])
    assert "120.000,00" in m and "vazio" in m and _TRECHO in m and "OCR" not in m
    assert "OCR" in R.mensagem({**_REJ[0], "conta_por_ocr": True})


def test_mensagem_nao_afirma_partes_mais_sucumbencia():
    """A regra rejeita toda ausência da conta, não só a mistura com honorário/
    sucumbência (medido: separar por vocabulário perde 21/55 agregações
    conhecidas). Afirmar "quase sempre partes + sucumbências" induziria
    desconfiança errada nas somas LEGÍTIMAS que também caem aqui — a mensagem
    tem de ser condicional, não afirmativa."""
    m = R.mensagem(_REJ[0])
    assert "quase sempre" not in m.lower()
    assert "partes + sucumb" not in m.lower() and "partes\" + \"sucumb" not in m.lower()
    # condicional: nomeia os dois desfechos possíveis, sem apontar qual é
    assert "legítima" in m.lower() and "indevida" in m.lower()
    assert "mesmo credor" in m.lower()
    assert "honorário" in m.lower() or "honorario" in m.lower()


# ── tela de pré-análise ──────────────────────────────────────────────────
_RES = {"ok": True, "prova": {"ok": None}, "conflitos": [], "do_card": [], "custo": 0.0,
        "campos": {"valor_total": {"valor": "170.000,00",
                                   "citacao": {"pagina": 1, "trecho": "Total 170.000,00"}}},
        "query": {"vt": "170.000,00"}, "rejeitados": _REJ}


def _link(at: AppTest) -> dict:
    botoes = at.get("link_button")
    assert botoes, "sem o link para a calculadora"
    return {k: v[0] for k, v in parse_qs(urlparse(botoes[0].proto.url).query).items()}


@pytest.fixture
def tela() -> AppTest:
    at = AppTest.from_file(str(_RAIZ / "telas" / "pre_analise.py"), default_timeout=60)
    at.session_state["pre_res"] = _RES
    return at


def test_pre_analise_mostra_o_aviso_com_valor_e_trecho(tela):
    tela.run()
    assert not tela.exception
    avisos = [e.value for e in tela.error if "120.000,00" in (e.value or "")]
    assert avisos, "o valor recusado sumiu sem aviso"
    assert _TRECHO in avisos[0], "o trecho que expõe a soma não aparece"
    link = _link(tela)
    assert "vp" not in link, "o valor recusado foi para a calculadora sem o advogado pedir"
    assert json.loads(link["rej"])[0]["u"] == 0


def test_pre_analise_usar_mesmo_assim_devolve_o_valor(tela):
    tela.run()
    [c for c in tela.checkbox if c.key == "pre_usar_vp"][0].check().run()
    assert not tela.exception
    link = _link(tela)
    assert link["vp"] == "120.000,00"
    assert json.loads(link["rej"])[0]["u"] == 1, "o ledger precisa saber que foi escolha do advogado"


# ── calculadora: "Anexar processo" (PREFILL_ENABLED) ──────────────────────
def test_calculadora_usar_mesmo_assim_preenche_o_campo(monkeypatch):
    monkeypatch.setenv("PREFILL_ENABLED", "1")
    at = AppTest.from_file(str(_RAIZ / "Calculadora.py"), default_timeout=90)
    at.session_state["_prefill_result"] = {**_RES, "conta_ref": "pp1-1", "oficio_ref": None,
                                          "citacoes": {}}
    at.run()
    assert not at.exception
    assert any("120.000,00" in (e.value or "") for e in at.error), "aviso ausente na calculadora"
    [c for c in at.checkbox if c.key == "_prefill_usar_vp"][0].check().run()
    assert not at.exception
    assert [t for t in at.text_input if t.key == "vp"][0].value == "120.000,00"


# ── envio ao card: a recusa chega à observação do ledger ─────────────────
def test_envio_leva_a_recusa_para_a_observacao_do_ledger(monkeypatch):
    monkeypatch.setenv("BITRIX_WEBHOOK", "https://exemplo.invalido/rest/1/token")
    monkeypatch.setenv("HUB_URL", "https://exemplo.invalido/api")
    import bitrix
    import hub

    monkeypatch.setattr(bitrix, "carregar_deal", lambda i: {
        "ID": int(i), "TITLE": "TESTE", "CATEGORY_ID": "9", "STAGE_ID": "C9:X",
        bitrix.CAMPO_VALOR: ""})
    monkeypatch.setattr(bitrix, "_auditoria_anterior", lambda i: [])
    monkeypatch.setattr(bitrix, "_ETAPAS", {"DEAL_STAGE_9": {"C9:X": "Pré-Análise"}})
    monkeypatch.setattr(bitrix, "_bx", lambda metodo, **params: [])
    ledger: list[dict] = []
    monkeypatch.setattr(hub, "caso_do_card", lambda d: {"id": "caso-1"})
    monkeypatch.setattr(hub, "documentos_do_caso", lambda c: [])
    monkeypatch.setattr(hub, "registrar_adjudicacao",
                        lambda *a, **k: ledger.append({"args": a, **k}) or {})
    monkeypatch.setattr(hub, "gravar_snapshot", lambda cid, payload, memorial_pdf=None: {"id": "s"})
    monkeypatch.setattr(hub, "journal_registrar", lambda cid, **kw: {"id": "j", **kw})
    monkeypatch.setattr(hub, "journal_concluir", lambda jid, status, erro=None: {})

    at = AppTest.from_file(str(_RAIZ / "Calculadora.py"), default_timeout=90)
    # o que o link da pré-análise entrega: o advogado NÃO usou o vp recusado
    # e digitou o valor certo na calculadora
    at.session_state["_prefill_params"] = {
        "vt": "170.000,00", "vp": "100.000,00", "vj": "50.000,00",
        "data_calculo": "2025-01-15", "card": "2273",
        "rej": R.codificar(_REJ, set())}
    at.run()
    [b for b in at.button if "Calcular" in (b.label or "")][0].click().run()
    [b for b in at.button if "Enviar para o card" in (b.label or "")][0].click().run()
    assert not at.exception
    assert len(ledger) == 1, "o envio não gravou o ledger"
    obs = json.loads(ledger[0]["observacao"])
    assert obs == {"prefill_rejeitados": [
        {"campo": "vp", "valor": "120.000,00", "usado_mesmo_assim": False, "trecho": _TRECHO}]}


def test_envio_sem_recusa_nao_inventa_observacao(monkeypatch):
    """Regressão: sem `rej` na URL a observação continua None, como sempre foi."""
    assert R.observacao(R.decodificar(None)) is None
