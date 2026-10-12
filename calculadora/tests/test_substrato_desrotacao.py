"""PDF deitado: o texto tem de sair em ordem de LEITURA e a tabela com os eixos certos.

São DUAS patologias distintas, e este módulo não tratava nenhuma:

  PÁGINA girada  `page.rotation == 90` — `remove_rotation()` resolve.
                 13,17% das páginas do corpus.
  TEXTO  girado  `page.rotation == 0` e `dir == (0,±1)` — a matriz de DESENHO é
                 que está girada; `remove_rotation()` é no-op. 2,25% das
                 páginas, mas em 42 dos 77 casos, e concentradas justamente nas
                 planilhas de cálculo.
"""

import fitz
import pytest

from prefill import substrato as S

# Uma "linha" da tabela girada = várias células no MESMO x, em y decrescentes
# (com rotate=90 o texto sobe, então y menor = mais adiante na leitura).
#
# ⚠ A ORDEM DE INSERÇÃO é o que faz este fixture valer. Linha-a-linha o PyMuPDF
# funde as células num bloco só e o `get_text` cru já sai correto — o defeito
# não aparece e o teste positivo não prova nada. O gerador real (PJe-Calc) emite
# COLUNA A COLUNA, e é isso que produz um bloco por célula e a saída órfã.
_CELULAS = [  # (x = linha de leitura, y = coluna, texto)
    (100, 700, "DIFERENCA SALARIAL"), (130, 700, "Liquido Devido"),
    (100, 600, "59.088,75"), (130, 600, "55.686,88"),
    (100, 560, "1.000,00"), (130, 560, "2.000,00"),
]


def _pdf_texto_girado(tmp_path):
    p = tmp_path / "girado.pdf"
    doc = fitz.open()
    page = doc.new_page()
    for x, y, texto in _CELULAS:          # column-major, como o gerador real
        page.insert_text((x, y), texto, rotate=90, fontsize=9)
    doc.save(p)
    doc.close()
    return p


def _pdf_normal(tmp_path):
    p = tmp_path / "normal.pdf"
    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((72, 100), "DIFERENCA SALARIAL 59.088,75 1.000,00", fontsize=9)
    page.insert_text((72, 120), "Liquido Devido 55.686,88 2.000,00", fontsize=9)
    doc.save(p)
    doc.close()
    return p


def _juntas(texto):
    import re
    return [
        ln.strip() for ln in (texto or "").splitlines()
        if re.search(r"[A-Za-zÀ-ÿ]{4,}", ln)
        and re.search(r"\d{1,3}(?:\.\d{3})*,\d{2}", ln)
    ]


# ─────────────────────────────── TEXTO ───────────────────────────────


def test_texto_girado_reune_rotulo_e_valor_na_mesma_linha(tmp_path):
    doc = fitz.open(_pdf_texto_girado(tmp_path))
    page = doc[0]
    assert page.rotation == 0, "o defeito é com a PÁGINA em pé"
    assert S.normalizar_pagina(page) == (0, -1)

    juntas = _juntas(S.texto_pagina(page))
    assert any("DIFERENCA SALARIAL" in ln and "59.088,75" in ln for ln in juntas)
    assert any("Liquido Devido" in ln and "55.686,88" in ln for ln in juntas)
    doc.close()


def test_controle_negativo_sem_a_correcao_o_valor_fica_orfao(tmp_path):
    """A correção tem de ser NECESSÁRIA — senão o teste acima não prova nada."""
    doc = fitz.open(_pdf_texto_girado(tmp_path))
    juntas = _juntas(doc[0].get_text() or "")
    assert not any("DIFERENCA SALARIAL" in ln and "59.088,75" in ln for ln in juntas), (
        "o get_text cru já juntava rótulo e valor — o fixture não reproduz o defeito"
    )
    doc.close()


def test_pagina_normal_passa_intacta(tmp_path):
    """Identidade em página normal: o acervo que já funcionava não pode mudar."""
    doc = fitz.open(_pdf_normal(tmp_path))
    page = doc[0]
    assert S.normalizar_pagina(page) == (1, 0)
    assert S.texto_pagina(page) == (page.get_text() or "")
    doc.close()


# ─────────────────────────────── TABELA ───────────────────────────────


def test_tabela_girada_reconstroi_como_a_mesma_tabela_em_pe(tmp_path):
    """Mesma tabela, deitada e em pé, tem de dar a mesma reconstrução."""
    linhas = [("Principal", ["1.000,00", "2.000,00", "3.000,00"]),
              ("Juros", ["100,00", "200,00", "300,00"])]

    em_pe = tmp_path / "pe.pdf"
    doc = fitz.open()
    page = doc.new_page()
    for i, (rot, vals) in enumerate(linhas):
        page.insert_text((60, 100 + i * 20), rot, fontsize=9)
        for j, v in enumerate(vals):
            page.insert_text((160 + j * 90, 100 + i * 20), v, fontsize=9)
    doc.save(em_pe)
    doc.close()

    deitada = tmp_path / "deitada.pdf"
    doc = fitz.open()
    page = doc.new_page()
    for i, (rot, vals) in enumerate(linhas):
        page.insert_text((100 + i * 20, 740), rot, rotate=90, fontsize=9)
        for j, v in enumerate(vals):
            page.insert_text((100 + i * 20, 640 - j * 90), v, rotate=90, fontsize=9)
    doc.save(deitada)
    doc.close()

    a = fitz.open(em_pe)
    b = fitz.open(deitada)
    t_pe = S.clusterizar_tabela(a[0])
    t_deitada = S.clusterizar_tabela(b[0])
    assert t_deitada == t_pe, f"em pé={t_pe}\ndeitada={t_deitada}"
    assert len(t_pe) == 2 and len(t_pe[0]) == 4, t_pe
    a.close()
    b.close()


def test_tabela_girada_sem_a_correcao_colapsa(tmp_path):
    """Controle negativo da tabela: sem desrotacionar, os eixos entram trocados."""
    deitada = tmp_path / "deitada.pdf"
    doc = fitz.open()
    page = doc.new_page()
    for i in range(2):
        for j, v in enumerate(["1.000,00", "2.000,00", "3.000,00"]):
            page.insert_text((100 + i * 20, 640 - j * 90), v, rotate=90, fontsize=9)
    doc.save(deitada)
    doc.close()

    d = fitz.open(deitada)
    certo = S.clusterizar_tabela(d[0])
    # força o caminho ANTIGO: direção normal = não desrotaciona
    errado = S.clusterizar_tabela(d[0], direcao=(1, 0))
    assert certo != errado, "a desrotação não mudou nada — fixture não exercita o defeito"
    assert len(certo) == 2, certo
    d.close()


# ─────────────────────────── ROBUSTEZ ───────────────────────────


def test_pagina_com_rotation_continua_tratada(tmp_path):
    """A patologia ANTIGA (rotação de página) não pode regredir."""
    p = tmp_path / "pagina_girada.pdf"
    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((72, 100), "DIFERENCA SALARIAL 59.088,75", fontsize=9)
    page.set_rotation(90)
    doc.save(p)
    doc.close()

    doc = fitz.open(p)
    assert doc[0].rotation == 90
    assert "DIFERENCA SALARIAL 59.088,75" in S.texto_pagina(doc[0])
    doc.close()


def test_remove_rotation_que_levanta_nao_derruba_a_pagina(tmp_path, monkeypatch):
    """`ValueError: bad rect` numa página não pode matar o PDF inteiro.

    E o texto ainda tem de sair legível: a página segue com `rotation`, reporta
    `dir=(0,-1)` e cai na desrotação por coordenada — a rede.
    """
    p = tmp_path / "pagina_girada.pdf"
    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((72, 100), "DIFERENCA SALARIAL 59.088,75", fontsize=9)
    page.set_rotation(90)
    doc.save(p)
    doc.close()

    doc = fitz.open(p)
    monkeypatch.setattr(
        type(doc[0]), "remove_rotation",
        lambda self: (_ for _ in ()).throw(ValueError("bad rect")),
    )
    saida = S.texto_pagina(doc[0])
    assert "DIFERENCA SALARIAL" in saida and "59.088,75" in saida, saida
    doc.close()


def test_direcao_dominante_pesa_por_caractere_nao_por_linha(tmp_path):
    """Cabeçalho horizontal curto não pode decidir o eixo da tabela girada."""
    p = tmp_path / "misto.pdf"
    doc = fitz.open()
    page = doc.new_page()
    for i in range(3):
        page.insert_text((72, 40 + i * 12), "TJ", fontsize=8)      # ~6 chars
    for i in range(12):
        page.insert_text((100 + i * 12, 700), "VALOR CORRIGIDO 1.234,56",
                         rotate=90, fontsize=8)                     # ~288 chars
    doc.save(p)
    doc.close()

    doc = fitz.open(p)
    assert S.direcao_dominante(doc[0]) == (0, -1)
    doc.close()


def test_pagina_sem_texto_nao_quebra(tmp_path):
    p = tmp_path / "vazia.pdf"
    doc = fitz.open()
    doc.new_page()
    doc.save(p)
    doc.close()

    doc = fitz.open(p)
    assert S.direcao_dominante(doc[0]) == (1, 0)
    assert S.texto_pagina(doc[0]) == ""
    assert S.clusterizar_tabela(doc[0]) == []
    doc.close()


def test_processar_pdf_usa_a_desrotacao(tmp_path):
    """O caminho de produção (`processar_pdf`) tem de herdar o conserto."""
    pags = S.processar_pdf(str(_pdf_texto_girado(tmp_path)))
    assert len(pags) == 1
    juntas = _juntas(pags[0]["texto"])
    assert any("DIFERENCA SALARIAL" in ln and "59.088,75" in ln for ln in juntas), (
        pags[0]["texto"]
    )
