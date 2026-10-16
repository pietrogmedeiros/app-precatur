"""O status com que a recusa do CRM sai do motor.

Não é preciosismo de REST. O proxy que publica o app (Traefik, no EasyPanel)
substitui o corpo de qualquer 5xx pela própria página "Service is not
reachable": a explicação que viaja dentro de um 502 NUNCA chega ao advogado, e
a tela só consegue dizer "a calculadora respondeu 502" — foi o que apareceu no
primeiro envio real, com o card no funil 0 e o ambiente escrevendo só no 9.

Recusa de regra é 4xx (passa inteira); 502 fica para falha de infraestrutura.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from rotas_crm import _erro_do_bitrix  # noqa: E402


def test_funil_proibido_e_409_e_leva_a_explicacao():
    erro = _erro_do_bitrix(RuntimeError(
        "funil proibido: o card #7527 está no funil 0 e este ambiente só escreve no 9."))
    assert erro.status_code == 409
    assert "funil 0" in erro.detail and "só escreve no 9" in erro.detail


def test_card_inexistente_e_404():
    assert _erro_do_bitrix(RuntimeError("card #999999 não encontrado")).status_code == 404


def test_falha_do_bitrix_continua_502():
    # Aqui o 502 é honesto: o CRM não respondeu, e a página do proxy não mente.
    assert _erro_do_bitrix(RuntimeError("crm.deal.get: Invalid token")).status_code == 502
