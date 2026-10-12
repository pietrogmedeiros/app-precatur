"""Alíquota do PSS no modo "Por alíquota": vazio bloqueia, 14 é o padrão.

Decisão do time (30/09/2026): campo vazio ou só espaços, no modo "Por
alíquota", é erro — antes o motor trocava em silêncio por 14%. O campo nasce
com 14, então o uso normal não muda; o que muda é quem APAGA o número.
Só vale nesse modo: em "Não descontar" e "Valor no ofício (R$)" o texto do campo
(vazio ou não) segue ignorado. Contratuais/sucumbenciais vazios continuam
válidos (vazio = sem honorário).
"""
from __future__ import annotations

from decimal import Decimal

import pytest

from pssir_util import (ALIQ, DATA_CALC, NAO, VALOR, calcular, erros, espiar_motor,
                        novo_app, preencher, radios, rodar, tem_memorial, texto)

MSG = ("Alíquota do PSS: informe a alíquota (maior que 0) ou escolha outro modo "
       "(Não descontar ou Valor no ofício (R$))")


@pytest.fixture
def ambiente(monkeypatch):
    monkeypatch.setenv("BITRIX_WEBHOOK", "https://exemplo.invalido/rest/1/token")
    monkeypatch.setenv("HUB_URL", "https://exemplo.invalido/api")


def _tem_envio(at) -> bool:
    return any("Enviar para o card" in (e.label or "") for e in at.expander)


# ── o bloqueio ───────────────────────────────────────────────────────────────

@pytest.mark.parametrize("vazio", ["", " ", "   ", "\t"])
def test_aliquota_vazia_ou_so_espacos_bloqueia(monkeypatch, ambiente, vazio):
    reg = espiar_motor(monkeypatch)
    at = rodar(pss_modo=ALIQ, aliq=vazio)
    assert not at.exception
    assert MSG in erros(at), erros(at)
    assert "entrada" not in reg, "o motor não pode ter rodado"
    assert not tem_memorial(at) and not _tem_envio(at)


def test_bloqueio_persiste_no_rerun(monkeypatch, ambiente):
    espiar_motor(monkeypatch)
    at = rodar(pss_modo=ALIQ, aliq="")
    at.run()
    assert MSG in erros(at)
    assert not tem_memorial(at) and not _tem_envio(at)


def test_mensagem_de_zero_continua_a_do_commit_anterior(monkeypatch):
    espiar_motor(monkeypatch)
    at = rodar(pss_modo=ALIQ, aliq="0")
    assert any("Informe uma alíquota maior que 0 ou escolha Não descontar" in m
               for m in erros(at)), erros(at)


# ── só nesse modo ────────────────────────────────────────────────────────────

@pytest.mark.parametrize("modo, pss", [(NAO, None), (VALOR, "1.234,56")])
@pytest.mark.parametrize("vazio", ["", "   "])
def test_outros_modos_ignoram_a_aliquota_vazia(monkeypatch, modo, pss, vazio):
    reg = espiar_motor(monkeypatch)
    at = rodar(pss_modo=modo, pss=pss, aliq=vazio)
    assert not at.exception and erros(at) == []
    assert "entrada" in reg


@pytest.mark.parametrize("campo", ["hc", "hs"])
def test_honorarios_vazios_continuam_validos(monkeypatch, campo):
    reg = espiar_motor(monkeypatch)
    at = preencher(novo_app(), pss_modo=ALIQ)
    texto(at, campo).set_value("")
    calcular(at)
    assert not at.exception and erros(at) == []
    assert "entrada" in reg


# ── o padrão 14 e o help ─────────────────────────────────────────────────────

def test_padrao_14_calcula_normalmente(monkeypatch):
    reg = espiar_motor(monkeypatch)
    at = novo_app()
    assert texto(at, "apss").value == "14"
    preencher(at, pss_modo=ALIQ)            # não toca na alíquota: fica o 14
    calcular(at)
    assert not at.exception and erros(at) == []
    assert reg["entrada"].aliquota_pss_pct == Decimal("14")
    assert Decimal(reg["res"]["cenario_homologado"]["valor_pss"]) == Decimal("14000.00")


def test_help_do_campo_cita_14_e_nao_descontar():
    h = texto(novo_app(), "apss").help or ""
    assert "14%" in h and "Não descontar" in h
    assert h == ("Padrão 14%. Informe um valor maior que 0. "
                 "Para não descontar PSS, escolha 'Não descontar'.")


# ── caminhos que SEMEIAM o campo: nenhum deixa vazio ─────────────────────────

def test_a_sem_url_o_campo_vem_com_14():
    assert texto(novo_app(), "apss").value == "14"


@pytest.mark.parametrize("params", [{"pss_modo": "aliquota"},
                                    {"pss_modo": "aliquota", "apss": ""}])
def test_b_url_pss_modo_aliquota_sem_apss_abre_com_14(monkeypatch, params):
    reg = espiar_motor(monkeypatch)
    at = novo_app(params)
    assert radios(at)[0].value == ALIQ
    assert texto(at, "apss").value == "14"
    preencher(at, pss_modo=ALIQ)
    calcular(at)
    assert not at.exception and erros(at) == []
    assert reg["entrada"].aliquota_pss_pct == Decimal("14")


def _snapshot(entrada_extra: dict) -> dict:
    return {
        "id": "snap-al", "case_id": "caso-al", "deal_id": "2387",
        "criado_em": "2026-03-10T12:00:00", "autor": "ana",
        "valor_liquido": "1", "valor_card": "R$ 1,00", "motor_versao": "x",
        "ultimo_mes_real": {}, "memorial_pdf_hash": None,
        "entrada": {"valor_total": "150000.00", "valor_principal_corrigido": "100000.00",
                    "valor_juros": "50000.00", "data_calculo": "2025-01-15",
                    "natureza_tributaria": "remuneratorio", "estimar_pss": True,
                    **entrada_extra},
    }


def _hub(monkeypatch, snap):
    monkeypatch.setenv("BITRIX_WEBHOOK", "https://exemplo.invalido/rest/1/token")
    monkeypatch.setenv("HUB_URL", "https://exemplo.invalido/api")
    import hub
    monkeypatch.setattr(hub, "snapshot", lambda sid: dict(snap))


@pytest.mark.parametrize("extra, esperado", [
    ({}, "14"),                                  # ausente
    ({"aliquota_pss_pct": None}, "14"),          # nula
    ({"aliquota_pss_pct": "14"}, "14"),
    ({"aliquota_pss_pct": "11.5"}, "11.5"),
])
def test_c_snapshot_estimar_pss_nunca_abre_a_aliquota_vazia(monkeypatch, extra, esperado):
    _hub(monkeypatch, _snapshot(extra))
    reg = espiar_motor(monkeypatch)
    at = novo_app({"snapshot": "snap-al"})
    assert radios(at)[0].value == ALIQ
    assert texto(at, "apss").value == esperado
    for d in at.date_input:
        if d.label.startswith("Data de atualização"):
            d.set_value(DATA_CALC)
    calcular(at)
    assert not at.exception and erros(at) == []
    assert "entrada" in reg


def test_d_reabrir_na_mesma_sessao_depois_de_apagar_a_aliquota_volta_a_14(monkeypatch):
    """O campo tem key + value=: o estado do widget poderia segurar o vazio
    apagado antes. Não segura — o snapshot sem alíquota reabre com 14."""
    _hub(monkeypatch, _snapshot({}))
    at = novo_app()
    texto(at, "apss").set_value("").run()
    assert texto(at, "apss").value == ""
    at.query_params["snapshot"] = "snap-al"
    at.run()
    assert not at.exception
    assert texto(at, "apss").value == "14"
