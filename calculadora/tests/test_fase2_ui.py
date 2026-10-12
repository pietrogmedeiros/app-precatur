"""Fase 2 na tela — snapshot no envio, reabrir, sobrescrita e reversão.

O que estes testes protegem, em ordem de gravidade:

  1. journal-PRIMEIRO. A intenção entra no journal ANTES de o card ser
     tocado, e sobrescrita/reversão são BLOQUEADAS quando o hub falha —
     nada pode ser escrito sem trilha;
  2. motivo obrigatório na sobrescrita — sem ele o clique não escreve nada;
  3. `?snapshot=` reabre o formulário FIEL à entrada congelada, inclusive
     os campos que a URL não cobria (superpreferência, regime, modo);
  4. a reversão com o card mudado pede aceite explícito (409 → confirmar).

Mesma técnica de test_prefill_handoff: AppTest roda o app de verdade;
`hub`/`bitrix` são os módulos reais com as funções de rede monkeypatchadas.
"""
from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

_RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_RAIZ))
_APP = str(_RAIZ / "Calculadora.py")


def _texto(at: AppTest, key: str) -> str | None:
    achados = [t for t in at.text_input if t.key == key]
    return achados[0].value if achados else None


def _botao(at: AppTest, *, key: str | None = None, rotulo: str | None = None):
    if key is not None:
        achados = [b for b in at.button if b.key == key]
    else:
        achados = [b for b in at.button if rotulo in (b.label or "")]
    assert achados, f"botão não encontrado (key={key!r}, rotulo={rotulo!r})"
    return achados[0]


@pytest.fixture
def app() -> AppTest:
    return AppTest.from_file(_APP, default_timeout=90)


@pytest.fixture
def ambiente(monkeypatch):
    monkeypatch.setenv("BITRIX_WEBHOOK", "https://exemplo.invalido/rest/1/token")
    monkeypatch.setenv("HUB_URL", "https://exemplo.invalido/api")


def _mock_bitrix(monkeypatch, eventos: list, valor_atual: str = ""):
    import bitrix
    monkeypatch.setattr(bitrix, "carregar_deal", lambda i: {
        "ID": int(i), "TITLE": "TESTE", "CATEGORY_ID": "9", "STAGE_ID": "C9:X",
        bitrix.CAMPO_VALOR: valor_atual})
    monkeypatch.setattr(bitrix, "_auditoria_anterior", lambda i: [])
    monkeypatch.setattr(bitrix, "_ETAPAS", {"DEAL_STAGE_9": {"C9:X": "Pré-Análise"}})

    def _bx_falso(metodo, **params):
        eventos.append((metodo, params))
        return []
    monkeypatch.setattr(bitrix, "_bx", _bx_falso)
    monkeypatch.setattr(bitrix, "sobrescrever_valor", lambda deal, txt: (
        eventos.append(("sobrescrever_valor", {"deal": deal, "texto": txt}))
        or {"aplicado": True}))
    return bitrix


def _mock_hub(monkeypatch, eventos: list):
    import hub
    monkeypatch.setattr(hub, "caso_do_card", lambda d: {"id": "caso-1"})
    monkeypatch.setattr(hub, "documentos_do_caso", lambda c: [])
    monkeypatch.setattr(hub, "registrar_adjudicacao",
                        lambda *a, **k: eventos.append(("adjudicacao", {})) or {})
    monkeypatch.setattr(hub, "gravar_snapshot", lambda cid, payload, memorial_pdf=None: (
        eventos.append(("snapshot", {"caso": cid, "payload": payload,
                                     "memorial": memorial_pdf}))
        or {"id": "snap-1"}))
    monkeypatch.setattr(hub, "journal_registrar", lambda cid, **kw: (
        eventos.append(("journal", {"caso": cid, **kw})) or {"id": "jr-1", **kw}))
    monkeypatch.setattr(hub, "journal_concluir", lambda jid, status, erro=None: (
        eventos.append(("concluir", {"id": jid, "status": status, "erro": erro}))
        or {}))
    return hub


def _so(eventos: list, nome: str) -> list[dict]:
    return [dados for evento, dados in eventos if evento == nome]


def _calcular(at: AppTest) -> AppTest:
    at.session_state["_prefill_params"] = {
        "vt": "150.000,00", "vp": "100.000,00", "vj": "50.000,00",
        "data_calculo": "2025-01-15", "card": "2273",
    }
    at.run()
    [b for b in at.button if "Calcular" in (b.label or "")][0].click().run()
    return at


# ───────────────────── envio: snapshot + journal ─────────────────────

def test_envio_grava_snapshot_e_journal_na_ordem_certa(app, ambiente, monkeypatch):
    """A intenção (journal) precede a escrita no card; a conclusão vem depois.
    E o snapshot serializa a ENTRADA REAL — é dele que o reabrir vai semear."""
    eventos: list = []
    _mock_bitrix(monkeypatch, eventos)
    _mock_hub(monkeypatch, eventos)

    at = _calcular(app)
    _botao(at, rotulo="Enviar para o card").click().run()
    assert not at.exception

    snaps = _so(eventos, "snapshot")
    assert len(snaps) == 1, "o envio tinha de congelar exatamente um snapshot"
    payload = snaps[0]["payload"]
    assert payload["entrada"]["valor_total"] == "150000.00"
    assert payload["entrada"]["data_calculo"] == "2025-01-15"
    assert payload["resultado"].get("cenario_homologado"), "o res inteiro vai junto"
    assert payload["motor_versao"] and len(payload["motor_versao"]) == 12, \
        "sem motor_versao a divergência futura vira mistério"
    assert payload["ultimo_mes_real"].get("SELIC"), "até onde o índice era real"

    js = _so(eventos, "journal")
    assert len(js) == 1
    assert js[0]["tipo"] == "envio"
    assert js[0]["snapshot_id"] == "snap-1", "o journal aponta o cálculo de origem"
    assert js[0]["valor_depois"].startswith("R$ ")

    # a ordem é o contrato: journal antes do update, conclusão depois
    nomes = [e for e, _ in eventos]
    assert nomes.index("journal") < nomes.index("crm.deal.update")
    assert _so(eventos, "concluir") == [{"id": "jr-1", "status": "aplicado",
                                         "erro": None}]


def test_hub_fora_do_ar_nao_derruba_o_envio(app, ambiente, monkeypatch):
    """No ENVIO o hub é best-effort (mesma regra do ledger): snapshot/journal
    falhando, o advogado ainda manda o valor — com aviso, nunca em silêncio."""
    eventos: list = []
    _mock_bitrix(monkeypatch, eventos)
    hub = _mock_hub(monkeypatch, eventos)

    def _cai(*a, **k):
        raise RuntimeError("hub 500")
    monkeypatch.setattr(hub, "gravar_snapshot", _cai)
    monkeypatch.setattr(hub, "journal_registrar", _cai)

    at = _calcular(app)
    _botao(at, rotulo="Enviar para o card").click().run()
    assert not at.exception
    assert ("crm.deal.update" in [e for e, _ in eventos]), "o envio tinha de seguir"
    assert any("snapshot não gravou" in (c.value or "") for c in at.caption)


# ───────────────────── reabrir: ?snapshot=<id> ─────────────────────

_SNAP_CONTA = {
    "id": "snap-9", "case_id": "caso-9", "deal_id": "2387",
    "criado_em": "2026-03-10T12:00:00", "autor": "ana",
    "valor_liquido": "88086.53",
    "valor_card": "R$ 88.086,53 (Atualizado para Março/2026)",
    "motor_versao": "abc123abc123", "ultimo_mes_real": {"SELIC": "2026-02"},
    "memorial_pdf_hash": None,
    "entrada": {
        "valor_total": "150000.00", "valor_principal_corrigido": "100000.00",
        "valor_juros": "50000.00", "data_calculo": "2025-01-15",
        "valor_superpreferencia": "30000.00",
        "data_pagamento_superpreferencia": "2025-06-01",
        "valor_pss": "1234.56", "natureza_tributaria": "remuneratorio",
        "honorarios_contratuais_pct": "20", "modalidade": "precatorio",
        "esfera": "federal",
        "_tela": {"referencia": "Precatório 123", "ente_devedor": "União",
                  "ano_orcamentario": "2026"},
    },
}


def test_snapshot_na_url_semeia_ate_o_que_a_url_nao_cobria(app, ambiente, monkeypatch):
    """Superpreferência e PSS por valor nunca viajaram na URL — o snapshot
    tem de trazê-los de volta, junto com a identificação (caso + card)."""
    import hub
    monkeypatch.setattr(hub, "snapshot", lambda sid: dict(_SNAP_CONTA))
    app.query_params["snapshot"] = "snap-9"
    app.run()
    assert not app.exception

    assert _texto(app, "vt") == "150000.00"
    assert _texto(app, "sp_val") == "30000.00", "superpreferência não voltou"
    assert _texto(app, "pss") == "1234.56"
    assert _texto(app, "hc") == "20"
    assert _texto(app, "ref") == "Precatório 123"
    assert app.session_state["bx_deal"] == "2387", "o card viaja com o snapshot"

    sp_data = [d for d in app.date_input
               if "superpreferência" in (d.label or "")][0]
    assert sp_data.value == date(2025, 6, 1)
    pss_radio = [r for r in app.radio if r.key is None and "PSS" in str(r.label)]
    # o radio do PSS não tem key; identifica pelo conjunto de opções
    pss_radio = [r for r in app.radio if "Por alíquota (%)" in (r.options or [])]
    assert pss_radio[0].value == "Valor no ofício (R$)"
    ente = [s for s in app.selectbox if "Ente/Entidade devedora" in (s.label or "")][0]
    assert ente.value == "União"
    esf = [s for s in app.selectbox if "Esfera" in (s.label or "")][0]
    assert esf.value.startswith("Federal")

    assert any("Cálculo congelado" in (m.value or "") for m in app.markdown), \
        "o painel do snapshot congelado não apareceu"
    # não é extração de ofício — o aviso do prefill não pode aparecer
    assert not any("pré-preenchidos" in (i.value or "") for i in app.info)


def test_snapshot_originario_reabre_modo_e_regime(app, ambiente, monkeypatch):
    """Modo e preset de regime não existiam como params — e sem eles um caso
    originário reabria como conta, silenciosamente errado."""
    import hub
    snap = {
        "id": "snap-8", "case_id": "caso-8", "deal_id": None,
        "criado_em": "2026-02-01T00:00:00", "autor": None,
        "valor_liquido": "1.00", "valor_card": None, "motor_versao": None,
        "ultimo_mes_real": None, "memorial_pdf_hash": None,
        "entrada": {
            "valor_originario": "50000.00", "data_base": "2010-05-01",
            "data_calculo": "2020-01-01",
            # o regime EXPANDIDO, como `build_regime` do preset composto gera
            "regime": [
                {"indice": "IPCA-E", "inicio_tipo": "data_base",
                 "inicio_data": None, "fim_tipo": "data",
                 "fim_data": "2021-12-09"},
                {"indice": "SELIC", "inicio_tipo": "data",
                 "inicio_data": "2021-12-09", "fim_tipo": "data_calculo",
                 "fim_data": None},
            ],
        },
    }
    monkeypatch.setattr(hub, "snapshot", lambda sid: snap)
    app.query_params["snapshot"] = "snap-8"
    app.run()
    assert not app.exception

    modo = [r for r in app.radio if "Ponto de partida" in (r.label or "")][0]
    assert modo.value.startswith("Modo originário"), "reabriu no modo errado"
    assert _texto(app, "vo") == "50000.00"
    regime = [s for s in app.selectbox if "Regime (índice SGS)" in (s.label or "")][0]
    assert regime.value.startswith("Composto"), "o preset do regime não voltou"


# ───────────────────── sobrescrita ─────────────────────

def _ate_a_sobrescrita(at: AppTest) -> AppTest:
    """Calcula, aponta o card e carrega o valor atual — a antessala."""
    at = _calcular(at)
    _botao(at, key="bx_sob_ver").click().run()
    return at


def test_sobrescrita_sem_motivo_nao_escreve(app, ambiente, monkeypatch):
    eventos: list = []
    _mock_bitrix(monkeypatch, eventos, valor_atual="R$ 1,00 (velho)")
    _mock_hub(monkeypatch, eventos)

    at = _ate_a_sobrescrita(app)
    assert "R$ 1,00 (velho)" in " ".join(m.value or "" for m in at.markdown), \
        "o valor atual do card tem de estar na tela antes da decisão"
    _botao(at, key="bx_sob_go").click().run()

    assert any("motivo" in (e.value or "").lower() for e in at.error)
    assert not _so(eventos, "journal"), "sem motivo, nada pode chegar ao journal"
    assert "sobrescrever_valor" not in [e for e, _ in eventos], \
        "sem motivo, o card não pode ser tocado"


def test_sobrescrita_e_journal_primeiro_hub_caido_bloqueia(app, ambiente, monkeypatch):
    """A regra que difere do envio: sem trilha, sem sobrescrita."""
    eventos: list = []
    _mock_bitrix(monkeypatch, eventos, valor_atual="R$ 1,00 (velho)")
    hub = _mock_hub(monkeypatch, eventos)

    def _cai(*a, **k):
        raise RuntimeError("hub fora do ar")
    monkeypatch.setattr(hub, "journal_registrar", _cai)
    monkeypatch.setattr(hub, "gravar_snapshot", _cai)

    at = _ate_a_sobrescrita(app)
    [t for t in at.text_input if t.key == "bx_sob_motivo"][0] \
        .set_value("conta retificada").run()
    _botao(at, key="bx_sob_go").click().run()

    assert any("BLOQUEADA" in (e.value or "") for e in at.error)
    assert "sobrescrever_valor" not in [e for e, _ in eventos], \
        "journal falhou e o card foi escrito mesmo assim — quebra o desenho"


def test_sobrescrita_feliz_registra_escreve_e_conclui(app, ambiente, monkeypatch):
    eventos: list = []
    _mock_bitrix(monkeypatch, eventos, valor_atual="R$ 1,00 (velho)")
    _mock_hub(monkeypatch, eventos)

    at = _ate_a_sobrescrita(app)
    [t for t in at.text_input if t.key == "bx_sob_motivo"][0] \
        .set_value("conta retificada pelo juízo").run()
    _botao(at, key="bx_sob_go").click().run()
    assert not at.exception

    js = _so(eventos, "journal")
    assert len(js) == 1 and js[0]["tipo"] == "sobrescrita"
    assert js[0]["motivo"] == "conta retificada pelo juízo"
    assert js[0]["valor_antes"] == "R$ 1,00 (velho)", \
        "valor_antes é o que o card mostrava — a evidência do journal"
    assert js[0]["snapshot_id"] == "snap-1", \
        "valor calculado NESTA tela carrega o snapshot que o explica"
    escritas = [d for e, d in eventos if e == "sobrescrever_valor"]
    assert len(escritas) == 1 and escritas[0]["texto"].startswith("R$ ")
    nomes = [e for e, _ in eventos]
    assert nomes.index("journal") < nomes.index("sobrescrever_valor")
    assert {"id": "jr-1", "status": "aplicado", "erro": None} in _so(eventos, "concluir")


# ───────────────────── reversão ─────────────────────

_ENTRADA_APLICADA = {
    "id": "j1", "tipo": "sobrescrita", "status": "aplicado",
    "valor_antes": "R$ 1,00", "valor_depois": "R$ 2,00", "deal_id": "2387",
    "criado_em": "2026-08-01T00:00:00", "autor": "ana", "motivo": "x",
    "erro": None, "snapshot_id": None, "reverte_id": None,
    "aplicado_em": "2026-08-01T00:00:01",
}


def _ate_a_reversao(at: AppTest, monkeypatch, eventos) -> AppTest:
    import hub
    monkeypatch.setattr(hub, "snapshots_do_caso", lambda c: [])
    monkeypatch.setattr(hub, "journal_do_caso", lambda c: [dict(_ENTRADA_APLICADA)])
    at.query_params["caso"] = "caso-1"
    at.run()
    _botao(at, key="_f2_carregar").click().run()
    [t for t in at.text_input if t.key == "_f2_rev_motivo"][0] \
        .set_value("sobrescrita foi engano").run()
    return at


def test_reversao_com_card_mudado_pede_aceite(app, ambiente, monkeypatch):
    eventos: list = []
    _mock_bitrix(monkeypatch, eventos, valor_atual="R$ 9,99")
    hub = _mock_hub(monkeypatch, eventos)

    def _diverge(cid, **kw):
        raise hub.DivergenciaCard({"divergencia": "o card mudou",
                                   "card_agora": "R$ 9,99",
                                   "esperado": "R$ 2,00"})
    monkeypatch.setattr(hub, "journal_registrar", _diverge)

    at = _ate_a_reversao(app, monkeypatch, eventos)
    _botao(at, key="_f2_rev_go").click().run()

    assert any("mudou depois" in (w.value or "") for w in at.warning), \
        "o 409 tem de virar aviso legível, com os dois valores"
    assert "sobrescrever_valor" not in [e for e, _ in eventos], \
        "divergência sem aceite não pode escrever"


def test_reversao_feliz_restaura_o_valor_da_entrada(app, ambiente, monkeypatch):
    eventos: list = []
    _mock_bitrix(monkeypatch, eventos, valor_atual="R$ 2,00")
    _mock_hub(monkeypatch, eventos)

    at = _ate_a_reversao(app, monkeypatch, eventos)
    _botao(at, key="_f2_rev_go").click().run()
    assert not at.exception

    js = _so(eventos, "journal")
    assert len(js) == 1 and js[0]["tipo"] == "reversao"
    assert js[0]["reverte_id"] == "j1"
    assert js[0]["valor_antes"] == "R$ 2,00", "lido do card na hora, não da lista"
    assert js[0]["valor_depois"] == "R$ 1,00", "reverter É restaurar o valor_antes"
    escritas = [d for e, d in eventos if e == "sobrescrever_valor"]
    assert escritas == [{"deal": 2387, "texto": "R$ 1,00"}]
    assert {"id": "jr-1", "status": "aplicado", "erro": None} in _so(eventos, "concluir")


# ───────────────────── sem hub ─────────────────────

def test_sobrescrita_indisponivel_sem_hub_diz_por_que(app, monkeypatch):
    monkeypatch.setenv("BITRIX_WEBHOOK", "https://exemplo.invalido/rest/1/token")
    monkeypatch.delenv("HUB_URL", raising=False)
    eventos: list = []
    _mock_bitrix(monkeypatch, eventos)

    at = _calcular(app)
    assert not at.exception
    assert any("sobrescrita sem trilha" in (c.value or "").lower()
               for c in at.caption), "tem de dizer que é desenho, não falha"
