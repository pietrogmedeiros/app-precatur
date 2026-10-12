"""Carimbo do PJe (`prefill/substrato.py`) — o que `texto_util` some e o que fica.

Commit B do plano do diagnóstico vt/vp/vj/vs (10-11/09/2026): 10 contas do
TJMG são 100% carimbo de assinatura digital — o carimbo sozinho passa dos 50
caracteres de `MIN_TEXTO_NATIVO`, a página é marcada `nativa`, o OCR nunca
roda, e o LLM só vê o carimbo (devolve null, corretamente — o problema é que
a conta real nunca chega a ser lida). `texto_util` passa a remover as duas
variantes do carimbo ANTES da contagem, sem mudar o limiar.

⚠ Pré-requisito: Commit A (`--psm 1` em `prefill/ocr.py`) já em produção —
sem ele, mandar uma página de carimbo invertida para o OCR reintroduziria o
risco de alucinação que o Commit A resolveu (ver commit `1cb1de5`).
"""
from __future__ import annotations

import sys
from pathlib import Path

import fitz
import pytest

_RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_RAIZ))

from prefill import substrato as S  # noqa: E402


def _pagina(texto: str) -> fitz.Page:
    """PDF de 1 página com `texto` como camada NATIVA (não é scan) — o mesmo
    formato que `eh_nativa`/`texto_util` recebem em produção. Salva e reabre
    (como `tests/test_assistente.py:_pdf_de` já faz) em vez de ler a página
    recém-criada direto: `insert_text` não garante que `get_text()` reflita
    o desenho sem essa volta pelo documento salvo."""
    doc = fitz.open()
    doc.new_page().insert_text((72, 72), texto, fontsize=11)
    return fitz.open(stream=doc.tobytes(), filetype="pdf")[0]


# ── as duas variantes reais do carimbo (nomes fictícios — nenhum dado real) ──
_VARIANTE_1 = (
    "Num. 4017538048 - Pág. 11\n"
    "Assinado eletronicamente por: FULANO DE TAL - 14/06/2021 14:16:59\n"
    "https://pje.tjmg.jus.br:443/pje/Processo/ConsultaDocumento/listView.seam"
    "?x=21061414165879400004015605417\n"
    "Número do documento: 21061414165879400004015605417"
)
_VARIANTE_2 = "Este documento foi gerado pelo usuário 166.***.***-24 em 10/09/2026 08:46:24"


def test_so_carimbo_variante_1_vai_para_ocr():
    pagina = _pagina(_VARIANTE_1)
    assert S.eh_nativa(pagina) is False, "carimbo sozinho não pode passar do limiar"


def test_so_carimbo_variante_2_vai_para_ocr():
    pagina = _pagina(_VARIANTE_2)
    assert S.eh_nativa(pagina) is False


def test_carimbo_mais_tabela_real_continua_nativa():
    """O carimbo some, mas a conta por trás dele mantém a página acima do
    limiar — é o caso que o Commit B resolve: hoje esta página TAMBÉM já é
    nativa (o carimbo infla o total), então o teste real é que ela CONTINUA
    nativa depois, não que vira nova."""
    texto = _VARIANTE_1 + (
        "\n\nTOTAL GERAL                R$ 51.111,00\n"
        "Principal corrigido        R$ 45.678,90\n"
        "Juros moratorios           R$ 5.432,10"
    )
    pagina = _pagina(texto)
    assert S.eh_nativa(pagina) is True


def test_pagina_so_descritiva_sem_carimbo_nao_vira_falso_positivo():
    """Sem carimbo e sem R$ — não pode ser confundida com carimbo só porque
    é curta ou não fala de dinheiro."""
    texto = (
        "MM. Juiz, 1) Foi aplicada a tabela divulgada pela Central de "
        "Precatórios do TJMG - CEPREC, a qual se funda na evolução da "
        "variação do INPC, TR e IPCA-e, conforme explicações na nota ao "
        "final da referida tabela que segue em anexo."
    )
    pagina = _pagina(texto)
    assert S.eh_nativa(pagina) is True
    assert S.texto_util(texto) == texto, "nenhuma linha desta página é carimbo"


def test_conta_curta_formato_americano_continua_nativa():
    """Réplica ESTRUTURAL do #3579 do diagnóstico (formato decimal americano,
    '500.00') — nomes/processo são fictícios, sem dado real."""
    texto = (
        "RESUMO DE CALCULO PROCESSO N.º 0000000-00.0000.0.00.0000 "
        "AUTOR(A): FULANO DE TAL REU: MUNICIPIO DE TESTE "
        "HONORARIOS ADVOCATICIOS 500.00 R$ "
        "DATA PARA CORRECAO (SENTENCA) 14/11/2014 "
        "INDICE DE CORRECAO MONETARIA (CEPREC DE 10/2016) 1.1"
    )
    pagina = _pagina(texto)
    assert S.eh_nativa(pagina) is True
    assert S.texto_util(texto) == texto


def test_pagina_nativa_comum_sai_identica():
    """A remoção só pode afetar linha de carimbo — conteúdo comum de conta
    (o mesmo `_CONTA` usado no resto da suíte) sai byte a byte igual."""
    texto = (
        "RESUMO DO CÁLCULO\n"
        "Conta de liquidação homologada — Projef\n"
        "Principal corrigido 100.000,00\n"
        "Juros moratórios 50.000,00\n"
        "Total geral da execução 150.000,00\n"
        "Data do cálculo 15/01/2025\n"
    )
    assert S.texto_util(texto) == texto
