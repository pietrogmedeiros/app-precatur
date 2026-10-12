"""OCR local (`prefill/ocr.py`) — o `--psm 1` e por que ele não pode regredir.

Medido no diagnóstico de 10-11/09/2026 (ledger de adjudicação): conta escaneada
de CABEÇA PARA BAIXO (24 casos do TJAL) saía como lixo girado ("opejosojoud…")
sem `--psm 1`, e o LLM "consertava" o que recebeu inventando dígitos — que por
coincidência somavam ao total real em 9 de 10 casos, driblando a prova
aritmética da tela. `--psm 0` (só OSD) foi testado e REPROVADO nesse corpus:
errou a orientação de 106/106 páginas do TJAL. `--psm 1` (LSTM+OSD) recuperou
59/86 valores nas invertidas sem regredir nenhuma das 28 contas que já liam
certo — é essa a mudança que os testes abaixo travam.
"""
from __future__ import annotations

import re
import subprocess

import fitz
import pytest

from prefill import ocr as O


def test_comando_inclui_psm_1(monkeypatch):
    """Trava contra reversão acidental: sem `--psm 1` a conta invertida do
    TJAL volta a produzir a alucinação coerente medida no diagnóstico."""
    chamado = {}

    class _Completo:
        returncode = 0
        stdout = b"texto"
        stderr = b""

    def _fake_run(cmd, **kwargs):
        chamado["cmd"] = cmd
        return _Completo()

    monkeypatch.setattr(O, "binario", lambda: "tesseract")
    monkeypatch.setattr(O, "idioma", lambda: None)  # isola do argumento -l
    monkeypatch.setattr(subprocess, "run", _fake_run)

    doc = fitz.open()
    pagina = doc.new_page()
    O.ler_pagina(pagina)
    doc.close()

    cmd = chamado["cmd"]
    assert "--psm" in cmd, f"comando sem --psm: {cmd}"
    assert cmd[cmd.index("--psm") + 1] == "1", f"psm não é 1: {cmd}"


# ── páginas-imagem sintéticas (simulam scan: SEM camada de texto nativo) ──
#
# ⚠ Uma página curta (poucas linhas) NÃO serve de fixture: testado à mão, o
# tesseract só corrige a rotação (via OSD embutido no `--psm 1`) quando a
# página tem densidade de texto — poucas linhas centralizadas leem a mesma
# sopa de letra invertida com QUALQUER psm, invertida ou não. Por isso o
# fixture imita uma página A4 cheia (cabeçalho + tabela de ~28 linhas +
# totais), o mesmo formato de uma conta real do corpus.
_TOTAL = "R$ 51.111,00"


def _pdf_conta_sintetica(tmp_path) -> "Path":
    """PDF de 2 páginas SEM texto nativo — cada uma é uma IMAGEM (o mesmo
    formato que `page.get_pixmap()` entrega ao tesseract em produção),
    página 1 de cabeça para baixo, página 2 em pé. O conteúdo (cabeçalho +
    tabela + "TOTAL GERAL") é o mesmo nas duas; só a orientação muda.

    ⚠ A página-imagem nasce com as MESMAS dimensões em pontos da página de
    origem (A4, 595×842) — não das dimensões em PIXELS do pixmap. Usar
    pixels como pontos infla a página (o `get_pixmap(dpi=…)` de `ler_pagina`
    renderizaria de novo, a partir de um "A4" de ~34 polegadas) e falseia o
    teste: nem o tempo nem a legibilidade correspondem ao que a produção vê.
    """
    origem_doc = fitz.open()
    pagina = origem_doc.new_page(width=595, height=842)  # A4 em pontos
    pagina.insert_text((60, 50), "TRIBUNAL DE JUSTICA DO ESTADO DE ALAGOAS", fontsize=11)
    pagina.insert_text((60, 70), "RESUMO DO CALCULO JUDICIAL - PROJEF", fontsize=11)
    pagina.insert_text((60, 95), "Processo no 0700000-00.2020.8.02.0001", fontsize=10)
    pagina.insert_text((60, 115), "Requerente: FULANO DE TAL DA SILVA OLIVEIRA", fontsize=10)
    pagina.insert_text((60, 135), "Requerido: MUNICIPIO DE MACEIO", fontsize=10)
    y = 180
    pagina.insert_text(
        (60, y), "Data       Competencia   Valor Nominal    Indice         Valor Corrigido",
        fontsize=9)
    y += 20
    for i in range(28):
        val1 = 1000 + i * 137.5
        val3 = val1 * (1.05 + i * 0.001)
        linha = (f"01/{(i % 12) + 1:02d}/2019   {(i % 12) + 1:02d}/2019       "
                 f"{val1:>10,.2f}    {val3 / val1:>8.6f}    {val3:>12,.2f}")
        pagina.insert_text((60, y), linha, fontsize=8)
        y += 18
    y += 15
    pagina.insert_text((60, y), "Principal corrigido                              R$ 45.678,90",
                       fontsize=10)
    y += 20
    pagina.insert_text((60, y), "Juros moratorios                                 R$ 5.432,10",
                       fontsize=10)
    y += 20
    pagina.insert_text((60, y), f"TOTAL GERAL                                      {_TOTAL}",
                       fontsize=11)
    pagina.insert_text((60, 800), "Documento gerado eletronicamente - pagina 1 de 1", fontsize=7)
    pix = pagina.get_pixmap(dpi=300)
    origem_doc.delete_page(0)

    doc = fitz.open()
    doc.new_page(width=595, height=842).insert_image(doc[0].rect, pixmap=pix, rotate=180)
    doc.new_page(width=595, height=842).insert_image(doc[1].rect, pixmap=pix, rotate=0)
    caminho = tmp_path / "conta_sintetica.pdf"
    doc.save(caminho)
    doc.close()
    origem_doc.close()
    return caminho


def _tem_total(texto: str) -> bool:
    return re.sub(r"\s", "", _TOTAL) in re.sub(r"\s", "", texto or "")


@pytest.mark.skipif(not O.disponivel(), reason="tesseract não instalado neste ambiente")
def test_psm1_le_pagina_invertida(tmp_path):
    """O caso que o Commit A resolve: conta de cabeça para baixo (TJAL)."""
    doc = fitz.open(_pdf_conta_sintetica(tmp_path))
    try:
        texto = O.ler_pagina(doc[0])   # pág 1 = invertida
    finally:
        doc.close()
    assert _tem_total(texto), f"não recuperou o total da página invertida — leu: {texto!r}"


@pytest.mark.skipif(not O.disponivel(), reason="tesseract não instalado neste ambiente")
def test_psm1_le_pagina_em_pe(tmp_path):
    """Controle: `--psm 1` não pode regredir o caso trivial (página em pé)."""
    doc = fitz.open(_pdf_conta_sintetica(tmp_path))
    try:
        texto = O.ler_pagina(doc[1])   # pág 2 = em pé
    finally:
        doc.close()
    assert _tem_total(texto), f"regrediu na página em pé — leu: {texto!r}"
