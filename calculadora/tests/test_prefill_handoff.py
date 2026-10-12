"""A entrega dos valores para a calculadora ("Abrir na calculadora").

Regressão de um defeito que passou despercebido porque cada metade parecia
certa: a tela de pré-análise punha os valores na query string e a calculadora
lia a query string. Só que DUAS coisas quebravam o caminho, e as duas só
aparecem no fluxo completo:

  1. `st.switch_page` LIMPA a query string (medido em 1.58). O que a tela
     escrevia na URL não chegava do outro lado.
  2. Mesmo chegando, a semeadura era condicionada a `_key not in session_state`
     — e a chave do widget nasce na PRIMEIRA renderização da calculadora e
     sobrevive à navegação. Como o advogado abre a calculadora antes de ir à
     tela de pré-análise, a guarda pulava tudo justamente no caminho normal.

Sintoma para o usuário: a aba trocava e os campos vinham VAZIOS.

Estes testes usam o AppTest (roda o script de verdade, sem navegador).
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

_RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_RAIZ))
_APP = str(_RAIZ / "Calculadora.py")

_VALORES = {"vt": "150.000,00", "vp": "100.000,00", "vj": "50.000,00"}


def _texto(at: AppTest, key: str) -> str | None:
    achados = [t for t in at.text_input if t.key == key]
    return achados[0].value if achados else None


@pytest.fixture
def app() -> AppTest:
    return AppTest.from_file(_APP, default_timeout=90)


def test_url_direta_semeia(app):
    """Controle: sessão nova + query string (o link externo do PrecaturIA)."""
    app.query_params.update(_VALORES)
    app.run()
    assert not app.exception
    assert _texto(app, "vt") == "150.000,00"


def test_semeia_mesmo_com_a_calculadora_JA_renderizada(app):
    """O caminho normal: o advogado abriu a calculadora ANTES do prefill.

    Depois da 1ª renderização as chaves dos widgets já existem no session_state
    — era exatamente aí que a guarda antiga desistia."""
    app.run()
    assert "vt" in app.session_state, "premissa do teste: o widget cria a chave"
    assert _texto(app, "vt") == ""

    app.query_params.update(_VALORES)
    app.session_state["_prefill_done"] = False
    del app.session_state["_prefill_done"]
    app.run()
    assert _texto(app, "vt") == "150.000,00"
    assert _texto(app, "vp") == "100.000,00"


def test_entrega_por_session_state_repoe_a_url(app):
    """O caminho REAL das telas internas: `switch_page` apaga a query string,
    então elas entregam por `_prefill_params` e a calculadora repõe a URL."""
    app.run()                                   # calculadora aberta primeiro
    app.session_state["_prefill_params"] = _VALORES   # o que o botão faz
    app.run()                                   # o que o switch_page provoca
    assert not app.exception
    assert _texto(app, "vt") == "150.000,00"
    assert _texto(app, "vj") == "50.000,00"
    # a URL volta a refletir os valores (link compartilhável). No AppTest o
    # valor vem como lista, diferente do `st.query_params` em runtime.
    _url_vt = app.query_params["vt"]
    assert (_url_vt[0] if isinstance(_url_vt, list) else _url_vt) == "150.000,00"
    # e a entrega é consumida — não re-semeia por cima do que o advogado editar
    assert "_prefill_params" not in app.session_state


def test_edicao_do_advogado_sobrevive_ao_rerun(app):
    """Semeia uma vez e sai da frente: `_prefill_done` é quem garante isso."""
    app.session_state["_prefill_params"] = _VALORES
    app.run()
    assert _texto(app, "vt") == "150.000,00"
    [t for t in app.text_input if t.key == "vt"][0].set_value("999,99").run()
    assert _texto(app, "vt") == "999,99", "o prefill não pode sobrescrever a edição"


# ── os resultados sobrevivem a um clique em outro botão ───────────────────
def _calcular(at: AppTest) -> AppTest:
    """Preenche o mínimo e clica em Calcular."""
    at.session_state["_prefill_params"] = {
        "vt": "150.000,00", "vp": "100.000,00", "vj": "50.000,00",
        "data_calculo": "2025-01-15",
    }
    at.run()
    [b for b in at.button if "Calcular" in (b.label or "")][0].click().run()
    return at


def _tem_resultado(at: AppTest) -> bool:
    """"Cenário homologado" só é renderizado depois do cálculo (`render_cenario`).
    O AppTest não expõe `download_button`, então o marcador é o markdown."""
    return any("Cenário homologado" in (m.value or "") for m in at.markdown)


def test_resultado_aparece_ao_calcular(app):
    at = _calcular(app)
    assert not at.exception
    assert _tem_resultado(at), "o cálculo não produziu resultado"


def test_resultado_SOBREVIVE_a_clique_em_outro_botao(app, monkeypatch):
    """Regressão do 'cliquei em Conferir (ensaio) e não aconteceu nada'.

    Todo o bloco de resultados vivia sob `if submitted:`, que só é True na
    execução do clique em Calcular. Qualquer outro botão provocava um rerun em
    que a tela era redesenhada SEM os resultados — levando junto o handler do
    botão recém-clicado. O clique FUNCIONAVA; a tela é que sumia.

    Reproduz com o bloco do CRM na tela e o campo do card VAZIO: o handler
    responde com o erro de validação, sem tocar na rede."""
    monkeypatch.setenv("BITRIX_WEBHOOK", "https://exemplo.invalido/rest/1/token")
    at = _calcular(app)
    assert _tem_resultado(at), "premissa: o resultado apareceu"

    ensaio = [b for b in at.button if "ensaio" in (b.label or "").lower()]
    assert ensaio, "premissa: o bloco do CRM está na tela"
    ensaio[0].click().run()

    assert not at.exception
    assert _tem_resultado(at), "o resultado sumiu depois do clique"
    assert any("número do card" in (e.value or "") for e in at.error),         "o handler do botão não chegou a rodar"


# ── o formulário sobrevive à troca de tela ────────────────────────────────
def test_estado_SOBREVIVE_a_troca_de_tela_na_pre_analise(monkeypatch):
    """O Streamlit faz GC do estado dos widgets não renderizados: trocar de tela
    apagava o que estava digitado. `estado.manter()` reatribui as chaves a cada
    execução.

    Depois da separação em duas aplicações, a calculadora é página ÚNICA — quem
    tem troca de tela é a pré-análise (Pré-análise ↔ Assistente de corte), e é
    lá que a garantia precisa valer."""
    monkeypatch.setenv("PREFILL_ENABLED", "1")
    # o bloco do card só aparece com CRM configurado; o valor digitado tem menos
    # de 3 caracteres de propósito, para não disparar busca na rede
    monkeypatch.setenv("BITRIX_WEBHOOK", "https://exemplo.invalido/rest/1/token")
    at = AppTest.from_file(str(_RAIZ / "PreAnalise.py"), default_timeout=90)
    at.run()
    assert not at.exception

    alvo = [t for t in at.text_input if t.key == "pre_deal"]
    assert alvo, "premissa: a tela de pré-análise tem o campo de busca do card"
    alvo[0].set_value("AB").run()

    at.switch_page("telas/assistente_de_corte.py")
    at.run()
    at.switch_page("telas/pre_analise.py")
    at.run()

    assert not at.exception
    assert _texto(at, "pre_deal") == "AB", "o que foi digitado sumiu"


# ── ensaio do envio ao CRM com o formulário no estado PADRÃO ──────────────
def test_ensaio_com_data_alvo_vazia_nao_estoura(app, monkeypatch):
    """Regressão: `TypeError: unsupported format string passed to NoneType`.

    "Data-alvo" fica VAZIA por padrão (o motor assume hoje), então `data_alvo` é
    None — e a linha de auditoria formatava com `:%d/%m/%Y`. Só aparecia ao
    clicar em Conferir, com o formulário no estado em que o advogado o deixa.
    """
    monkeypatch.setenv("BITRIX_WEBHOOK", "https://exemplo.invalido/rest/1/token")
    import bitrix

    monkeypatch.setattr(bitrix, "carregar_deal", lambda i: {
        "ID": int(i), "TITLE": "TESTE FILA 01", "CATEGORY_ID": "9",
        "STAGE_ID": "C9:PREPAYMENT_INVOICE"})
    monkeypatch.setattr(bitrix, "_auditoria_anterior", lambda i: [])
    monkeypatch.setattr(bitrix, "_ETAPAS", {"DEAL_STAGE_9": {"C9:X": "Pré-Análise"}})

    at = _calcular(app)
    assert _tem_resultado(at), "premissa: calculou"
    [t for t in at.text_input if t.key == "bx_deal"][0].set_value("2273").run()
    [b for b in at.button if "ensaio" in (b.label or "").lower()][0].click().run()

    assert not at.exception, f"estourou: {at.exception[0].value if at.exception else ''}"
    ensaio = [i.value for i in at.info if "Ensaio" in (i.value or "")]
    assert ensaio, "o ensaio não reportou nada"
    assert "UF_CRM" not in ensaio[0], "vazou identificador interno para a tela"
    assert "Cálculo Atualizado (Valor)" in ensaio[0], "o campo não saiu com nome humano"


def test_pecas_vem_do_hub_quando_a_sessao_perdeu(app, monkeypatch):
    """Regressão: envio silenciosamente SEM anexos.

    Os valores viajam na URL e sobrevivem a um refresh; os PDFs viviam só na
    sessão. Sessão perdida (restart, refresh, expiração) = tela cheia, ensaio
    listando 3 campos em vez de 6, e ninguém percebe. O caso guardado é a fonte
    durável."""
    monkeypatch.setenv("BITRIX_WEBHOOK", "https://exemplo.invalido/rest/1/token")
    monkeypatch.setenv("HUB_URL", "https://exemplo.invalido/api")
    import bitrix
    import hub

    monkeypatch.setattr(bitrix, "carregar_deal", lambda i: {
        "ID": int(i), "TITLE": "TESTE", "CATEGORY_ID": "9", "STAGE_ID": "C9:X"})
    monkeypatch.setattr(bitrix, "_auditoria_anterior", lambda i: [])
    monkeypatch.setattr(bitrix, "_ETAPAS", {"DEAL_STAGE_9": {"C9:X": "Pré-Análise"}})
    monkeypatch.setattr(hub, "caso_do_card", lambda d: {"id": "caso-1"})
    monkeypatch.setattr(hub, "documentos_do_caso", lambda c: [
        {"id": "d1", "peca": "conta", "nome": "conta.pdf"},
        {"id": "d2", "peca": "oficio", "nome": "oficio.pdf"}])
    monkeypatch.setattr(hub, "baixar_documento", lambda c, d: b"%PDF-1.4 x")

    at = _calcular(app)                      # sessão SEM peça nenhuma
    [t for t in at.text_input if t.key == "bx_deal"][0].set_value("2273").run()
    [b for b in at.button if "ensaio" in (b.label or "").lower()][0].click().run()

    assert not at.exception
    campos = [i.value for i in at.info if "Ensaio" in (i.value or "")]
    assert campos, "o ensaio não reportou"
    # o que a TELA mostra: rótulo do card, nunca o identificador interno
    assert bitrix.ROTULOS[bitrix.ANEXOS["conta"][0]] in campos[0], "a conta não seria anexada"
    assert bitrix.ROTULOS[bitrix.ANEXOS["oficio"][0]] in campos[0], "o ofício não seria anexado"
    assert "UF_CRM" not in campos[0], "vazou identificador interno para a tela"
    assert any("hub" in (c.value or "") for c in at.caption), \
        "não avisou de onde vieram as peças"


def test_numeros_do_crm_aparecem_na_tela_e_sao_editaveis(app, monkeypatch):
    """Regressão: o Número Ofício não foi gravado porque viajava só na URL, e a
    aba tinha sido aberta antes do campo existir. Passageiro invisível some sem
    aviso; campo na tela, não."""
    monkeypatch.setenv("BITRIX_WEBHOOK", "https://exemplo.invalido/rest/1/token")
    import bitrix

    monkeypatch.setattr(bitrix, "carregar_deal", lambda i: {
        "ID": int(i), "TITLE": "T", "CATEGORY_ID": "9", "STAGE_ID": "C9:X"})
    monkeypatch.setattr(bitrix, "_auditoria_anterior", lambda i: [])
    monkeypatch.setattr(bitrix, "_ETAPAS", {"DEAL_STAGE_9": {"C9:X": "Pré-Análise"}})

    app.session_state["_prefill_params"] = {
        "vt": "150.000,00", "vp": "100.000,00", "vj": "50.000,00",
        "data_calculo": "2025-01-15", "numero_oficio": "057/2025",
        "numero_precatorio": "0000123-45.2024.8.17.8201",
    }
    app.run()
    [b for b in app.button if "Calcular" in (b.label or "")][0].click().run()

    # veio da extração e está VISÍVEL, não escondido na URL
    assert _texto(app, "bx_num_oficio") == "057/2025"
    assert _texto(app, "bx_num_precatorio") == "0000123-45.2024.8.17.8201"

    # e o que o advogado digitar é o que vai
    [t for t in app.text_input if t.key == "bx_num_oficio"][0].set_value("999/2026").run()
    [t for t in app.text_input if t.key == "bx_deal"][0].set_value("2273").run()
    [b for b in app.button if "ensaio" in (b.label or "").lower()][0].click().run()
    ensaio = [i.value for i in app.info if "Ensaio" in (i.value or "")][0]
    assert "Número Ofício: 999/2026" in ensaio, ensaio


def test_card_na_url_nao_conta_como_pre_preenchimento(app, monkeypatch):
    """`?card=2273` é o link direto da pré-análise, não preenchimento de valor.
    Tratá-lo como tal faria a calculadora avisar "honorário não encontrado nos
    documentos" numa sessão em que documento nenhum foi lido."""
    app.query_params["card"] = "2273"
    app.run()
    assert not app.exception
    assert not any("não encontrado nos documentos" in (c.value or "")
                   for c in app.caption), "avisou sobre extração que não houve"
    # o card É colhido (identificação), mas identificação não é extração: o
    # aviso de "campos pré-preenchidos a partir do ofício" não pode aparecer.
    # (o session_state do AppTest não tem `.get` — só indexação)
    assert app.session_state["bx_deal"] == "2273"
    assert not any("pré-preenchidos" in (i.value or "") for i in app.info), \
        "anunciou extração numa URL que só trazia o número do card"


def test_id_do_negocio_vem_do_link_sem_digitar(app, monkeypatch):
    """Regressão do relato dos advogados (25/08/2026): entravam pela tarefa
    (onde o card já vinha identificado), passavam pela pré-análise e, na hora
    de enviar o cálculo, tinham de REDIGITAR o número do negócio.

    A tela de pré-análise já mandava `card=<id>` no link — a calculadora é que
    não semeava `bx_deal` com ele. Redigitar não é só trabalho: é a chance de
    mandar o cálculo para o card errado, que já aconteceu no teste Rommel."""
    monkeypatch.setenv("BITRIX_WEBHOOK", "https://exemplo.invalido/rest/1/token")
    import bitrix

    monkeypatch.setattr(bitrix, "carregar_deal", lambda i: {
        "ID": int(i), "TITLE": "T", "CATEGORY_ID": "9", "STAGE_ID": "C9:X"})
    monkeypatch.setattr(bitrix, "_auditoria_anterior", lambda i: [])
    monkeypatch.setattr(bitrix, "_ETAPAS", {"DEAL_STAGE_9": {"C9:X": "Pré-Análise"}})

    app.session_state["_prefill_params"] = {
        "vt": "150.000,00", "vp": "100.000,00", "vj": "50.000,00",
        "data_calculo": "2025-01-15", "card": "2387",
    }
    app.run()
    [b for b in app.button if "Calcular" in (b.label or "")][0].click().run()

    assert _texto(app, "bx_deal") == "2387", "o advogado ainda teria de digitar"

    # e o ensaio roda sem ninguém tocar no campo — que é o ponto
    [b for b in app.button if "ensaio" in (b.label or "").lower()][0].click().run()
    assert not app.exception
    assert not any("número do card" in (e.value or "") for e in app.error)
    assert [i.value for i in app.info if "Ensaio" in (i.value or "")], \
        "o ensaio não reportou nada"


def test_pecas_vem_do_CASO_do_link_nao_do_card_digitado(app, monkeypatch):
    """Regressão do teste Rommel: analisou sob um card e enviou para outro (um
    de teste), e os anexos sumiram — a busca era pelo número digitado aqui.

    O caso é a unidade de trabalho; ele viaja no link (`?caso=`)."""
    monkeypatch.setenv("BITRIX_WEBHOOK", "https://exemplo.invalido/rest/1/token")
    monkeypatch.setenv("HUB_URL", "https://exemplo.invalido/api")
    import bitrix
    import hub

    monkeypatch.setattr(bitrix, "carregar_deal", lambda i: {
        "ID": int(i), "TITLE": "T", "CATEGORY_ID": "9", "STAGE_ID": "C9:X"})
    monkeypatch.setattr(bitrix, "_auditoria_anterior", lambda i: [])
    monkeypatch.setattr(bitrix, "_ETAPAS", {"DEAL_STAGE_9": {"C9:X": "Pré-Análise"}})

    def _nao_deve_ser_chamado(deal_id):
        raise AssertionError("procurou pelo card digitado, ignorando o caso do link")
    monkeypatch.setattr(hub, "caso_do_card", _nao_deve_ser_chamado)
    monkeypatch.setattr(hub, "documentos_do_caso", lambda c: (
        [{"id": "d1", "peca": "conta", "nome": "conta.pdf"}] if c == "caso-do-link" else []))
    monkeypatch.setattr(hub, "baixar_documento", lambda c, d: b"%PDF-1.4 x")

    app.query_params.update({"vt": "150.000,00", "vp": "100.000,00", "vj": "50.000,00",
                             "data_calculo": "2025-01-15", "caso": "caso-do-link"})
    app.run()
    [b for b in app.button if "Calcular" in (b.label or "")][0].click().run()
    # card DIFERENTE do analisado — é o cenário que perdia os anexos
    [t for t in app.text_input if t.key == "bx_deal"][0].set_value("2277").run()
    [b for b in app.button if "ensaio" in (b.label or "").lower()][0].click().run()

    assert not app.exception
    ensaio = [i.value for i in app.info if "Ensaio" in (i.value or "")][0]
    assert "Anexo - Cálculos Homologados" in ensaio, "o corte não seria anexado"
