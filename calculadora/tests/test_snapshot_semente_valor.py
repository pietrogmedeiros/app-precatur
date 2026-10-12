"""O número que o advogado VÊ no campo semeado é o Decimal do snapshot.

`str(Decimal("100.000"))` é "100.000" — o texto lido como milhar valeria
100000. A semeadura escreve "100,000" e o parse devolve 100: os dois campos
(total em R$ e percentual) têm de voltar exatamente o que foi gravado.
"""
from __future__ import annotations

from decimal import Decimal

import numeros
from pssir_util import DATA_CALC, calcular, espiar_motor, novo_app, texto


def _snapshot():
    return {
        "id": "snap-sem", "case_id": "caso-sem", "deal_id": "2387",
        "criado_em": "2026-03-10T12:00:00", "autor": "ana",
        "valor_liquido": "1", "valor_card": "R$ 1,00", "motor_versao": "x",
        "ultimo_mes_real": {}, "memorial_pdf_hash": None,
        "entrada": {"valor_total": "100.000", "valor_principal_corrigido": "100.000",
                    "data_calculo": "2025-01-15", "natureza_tributaria": "remuneratorio",
                    "honorarios_contratuais_pct": "12.500"},
    }


def test_total_e_contratual_semeados_leem_o_decimal_original(monkeypatch):
    monkeypatch.setenv("BITRIX_WEBHOOK", "https://exemplo.invalido/rest/1/token")
    monkeypatch.setenv("HUB_URL", "https://exemplo.invalido/api")
    import hub
    monkeypatch.setattr(hub, "snapshot", lambda sid: _snapshot())
    reg = espiar_motor(monkeypatch)
    at = novo_app({"snapshot": "snap-sem"})

    vt, hc = texto(at, "vt").value, texto(at, "hc").value
    assert vt == "100,000" and hc == "12,500"
    # o número lido do campo, do jeito que a tela lê cada tipo de campo
    assert numeros.parse_decimal_br(vt) == Decimal("100.000") == Decimal(100)
    assert numeros.parse_decimal_br(vt) != Decimal(100000)
    assert numeros.parse_decimal_br(hc, milhar=False) == Decimal("12.500") == Decimal("12.5")

    for d in at.date_input:
        if d.label.startswith("Data de atualização"):
            d.set_value(DATA_CALC)
    calcular(at)
    assert not at.exception
    e = reg["entrada"]
    assert e.valor_total == Decimal("100.000")
    assert e.valor_principal_corrigido == Decimal("100.000")
    assert e.honorarios_contratuais_pct == Decimal("12.500")
