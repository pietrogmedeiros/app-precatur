"""Montagem dos campos do CRM — puro, sem rede.

`montar` é onde mora o julgamento (o que escrever, o que pular e por quê);
`enviar` é só transporte. Testar a primeira cobre o que pode dar errado em
silêncio: escrever por cima de campo preenchido, perder arquivo num campo de
arquivo único, ou estourar por causa do TIPO do valor.
"""
from __future__ import annotations

import base64
import re
import sys
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

_RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_RAIZ))

import bitrix as B  # noqa: E402


@pytest.fixture
def card_vazio() -> dict:
    return {"ID": 2273, "TITLE": "TESTE", "CATEGORY_ID": "9"}


def test_valor_como_STRING_nao_estoura(card_vazio):
    """`calcular_dict` devolve "88086.53", não Decimal. Formatar com `:.2f`
    dava ValueError: Unknown format code 'f' for object of type 'str'."""
    campos, _ = B.montar(card_vazio, valor_liquido="88086.53")
    assert campos[B.CAMPO_VALOR] == "R$ 88.086,53"


def test_valor_como_decimal_da_no_mesmo(card_vazio):
    campos, _ = B.montar(card_vazio, valor_liquido=Decimal("88086.5"))
    assert campos[B.CAMPO_VALOR] == "R$ 88.086,50"


def test_valor_na_grafia_da_casa_e_sem_sufixo_de_money(card_vazio):
    """704 cards preenchidos no funil 0: `R$ 999.999,99` domina e `|BRL` não
    aparece em nenhum — é sintaxe de campo MONEY, e este campo é `string`."""
    campos, _ = B.montar(card_vazio, valor_liquido="1503612.82")
    gravado = campos[B.CAMPO_VALOR]
    assert gravado == "R$ 1.503.612,82"
    assert "|BRL" not in gravado, "sufixo de money iria como texto literal no card"


def test_valor_leva_o_mes_a_que_esta_atualizado(card_vazio):
    """Pedido dos advogados (25/08/2026): o número sozinho não diz a QUE DATA
    ele está atualizado, e um cálculo de três meses atrás fica indistinguível
    de um de hoje na hora da proposta.

    A grafia não é nova — é a que o time já usa à mão (#1323 SAYONARA MIOTTO)."""
    campos, _ = B.montar(card_vazio, valor_liquido="180443.82",
                         atualizado_para=date(2026, 8, 25))
    assert campos[B.CAMPO_VALOR] == "R$ 180.443,82 (Atualizado para Agosto/2026)"


def test_mes_em_portugues_independe_do_locale(card_vazio):
    """`strftime('%B')` devolveria "August" na VM, que roda em inglês — daí a
    tabela de meses em vez da biblioteca."""
    campos, _ = B.montar(card_vazio, valor_liquido="1000",
                         atualizado_para="2026-03-01")
    assert "Março/2026" in campos[B.CAMPO_VALOR]


def test_sufixo_nao_cria_um_SEGUNDO_numero_para_o_warehouse(card_vazio):
    r"""O `stg_bitrix__deals` extrai os números do texto e só marca o valor como
    'ok' quando encontra UM. O ano do sufixo não pode virar o segundo: o
    extrator descarta tokens `^(19|20)\d{2}$`, e este teste fixa a premissa do
    lado de cá — se alguém trocar o sufixo por algo com número (ex.: "08/2026"
    virando "8.2026"), o painel de valor quebra em silêncio."""
    campos, _ = B.montar(card_vazio, valor_liquido="180443.82",
                         atualizado_para=date(2026, 8, 25))
    numeros = [t for t in re.findall(r"\d[\d.,]*", campos[B.CAMPO_VALOR])
               if not re.fullmatch(r"(19|20)\d{2}", t)]
    assert numeros == ["180.443,82"], numeros


def test_sem_data_grava_so_o_valor(card_vazio):
    """Sufixo errado é pior que sufixo nenhum."""
    campos, _ = B.montar(card_vazio, valor_liquido="1000", atualizado_para=None)
    assert campos[B.CAMPO_VALOR] == "R$ 1.000,00"


def test_valor_ilegivel_vira_pulo_explicito(card_vazio):
    """Não escrever é aceitável; escrever lixo no campo de dinheiro não é."""
    campos, pulados = B.montar(card_vazio, valor_liquido="—")
    assert B.CAMPO_VALOR not in campos
    assert any("ilegível" in p for p in pulados)


def test_nunca_sobrescreve_campo_preenchido():
    card = {"ID": 1, "CATEGORY_ID": "9", B.CAMPO_VALOR: "99999.99|BRL"}
    campos, pulados = B.montar(card, valor_liquido="123.45")
    assert B.CAMPO_VALOR not in campos
    assert any("já preenchido" in p for p in pulados)


def test_anexo_de_arquivo_unico_avisa_o_que_ficou_de_fora(card_vazio):
    """"Anexo - Cálculos Homologados" não é múltiplo: manda o primeiro e conta
    quantos sobraram, em vez de estourar ou perder em silêncio."""
    campo, multiplo = B.ANEXOS["conta"]
    assert multiplo is False, "premissa: o campo da conta é de arquivo único"
    campos, pulados = B.montar(
        card_vazio, pecas={"conta": [("a.pdf", b"AAA"), ("b.pdf", b"BBB")]})
    assert campos[campo]["fileData"][0] == "a.pdf"
    assert any("não foram enviados" in p for p in pulados)


def test_anexo_multiplo_manda_todos(card_vazio):
    campo, multiplo = B.ANEXOS["sentenca"]
    assert multiplo is True
    campos, _ = B.montar(
        card_vazio, pecas={"sentenca": [("s1.pdf", b"AAA"), ("s2.pdf", b"BBB")]})
    assert [f["fileData"][0] for f in campos[campo]] == ["s1.pdf", "s2.pdf"]
    assert base64.b64decode(campos[campo][0]["fileData"][1]) == b"AAA"


def test_campos_sao_os_do_layout_do_funil_9():
    """Guarda contra copiar o ID errado: o CRM tem 4 campos "Anexo - Ofício" e
    3 "Anexo - Cálculos Homologados", de gerações diferentes. Estes são os que
    estavam no layout do funil 9 em 05/08/2026 (conferido por API)."""
    assert B.CAMPO_VALOR == "UF_CRM_1769608301759"
    assert B.CAMPO_HON_CONTR == "UF_CRM_1769029890257"
    assert B.CAMPO_PRECATORIO == "UF_CRM_1769029222658"
    assert B.ANEXOS["memorial"][0] == "UF_CRM_1770463886064"
    assert B.ANEXOS["conta"][0] == "UF_CRM_1769029938097"
    assert B.ANEXOS["oficio"][0] == "UF_CRM_1771523008362"
    assert B.ANEXOS["sentenca"][0] == "UF_CRM_1773082937422"


def test_descricao_e_legivel_por_humano(card_vazio):
    """O advogado confere o que vai ser gravado, não uma lista de UF_CRM_*.
    Endereço interno na tela é jogar a tradução para quem está conferindo."""
    campos, _ = B.montar(card_vazio, valor_liquido="88086.53",
                         numero_precatorio="0000123-45.2024.8.17.8201",
                         memorial_pdf=b"%PDF",
                         pecas={"conta": [("calculo_homologado.pdf", b"A")],
                                "sentenca": [("s1.pdf", b"B"), ("s2.pdf", b"C")]})
    linhas = B.descrever(campos)
    assert "Cálculo Atualizado (Valor): R$ 88.086,53" in linhas
    assert "Nº Precatório: 0000123-45.2024.8.17.8201" in linhas
    assert "Anexo - Cálculos Homologados: calculo_homologado.pdf" in linhas
    assert "Anexo - Sentença / Acórdão: s1.pdf, s2.pdf" in linhas
    assert not any("UF_CRM" in l for l in linhas), "sobrou identificador cru na tela"


def test_todo_campo_escrito_tem_rotulo():
    """Guarda: campo novo sem rótulo apareceria como UF_CRM_* na tela."""
    escritos = {B.CAMPO_VALOR, B.CAMPO_HON_CONTR, B.CAMPO_PRECATORIO}
    escritos |= {campo for campo, _ in B.ANEXOS.values()}
    assert escritos <= set(B.ROTULOS), f"sem rótulo: {escritos - set(B.ROTULOS)}"


def test_pulado_tambem_usa_nome_humano():
    card = {"ID": 1, "CATEGORY_ID": "9", B.ANEXOS["oficio"][0]: [{"id": 1}]}
    _, pulados = B.montar(card, pecas={"oficio": [("o.pdf", b"A")]})
    assert any(p.startswith("Anexo - Ofício:") for p in pulados), pulados


# ── natureza e número do ofício ───────────────────────────────────────────
def test_natureza_usa_a_grafia_da_casa(card_vazio):
    """747 cards já preenchidos: "Remuneratória" (43) supera "Remuneratório"
    (21), "Indenizatória" (31) supera "Indenizatório" (19). Escrever fora do
    padrão criaria mais uma grafia num campo que já sofre de dispersão."""
    campos, _ = B.montar(card_vazio, natureza="indenizatorio")
    assert campos[B.CAMPO_NATUREZA] == "Indenizatória"
    campos, _ = B.montar(card_vazio, natureza="REMUNERATORIO")
    assert campos[B.CAMPO_NATUREZA] == "Remuneratória"


def test_natureza_desconhecida_nao_e_escrita(card_vazio):
    """O campo mistura dois eixos ('alimentar'/'comum' também aparecem lá). Só
    escrevemos o tributário; inventar grafia é pior que deixar vazio."""
    campos, pulados = B.montar(card_vazio, natureza="alimentar")
    assert B.CAMPO_NATUREZA not in campos
    assert any("desconhecido" in p for p in pulados)


def test_numero_do_oficio_vai_para_o_campo_proprio(card_vazio):
    """Dois números distintos: o do ofício (N/AAAA) e o CNJ do precatório."""
    campos, _ = B.montar(card_vazio, numero_oficio="057/2025",
                         numero_precatorio="0000123-45.2024.8.17.8201")
    assert campos[B.CAMPO_NUM_OFICIO] == "057/2025"
    assert campos[B.CAMPO_PRECATORIO] == "0000123-45.2024.8.17.8201"
    assert B.CAMPO_NUM_OFICIO != B.CAMPO_PRECATORIO


def test_varias_sentencas_viram_varios_arquivos_no_card(card_vazio):
    """O campo do card aceita múltiplos — todas as peças devem chegar lá."""
    campos, _ = B.montar(card_vazio, pecas={"sentenca": [
        ("sentenca_1.pdf", b"A"), ("sentenca_2.pdf", b"B"), ("sentenca_3.pdf", b"C")]})
    anexos = campos[B.ANEXOS["sentenca"][0]]
    assert [a["fileData"][0] for a in anexos] == [
        "sentenca_1.pdf", "sentenca_2.pdf", "sentenca_3.pdf"]


# ── rodar de novo COMPLETA o card ─────────────────────────────────────────
class _CRMFalso:
    """Dublê do webhook: registra o que foi chamado, sem rede."""

    def __init__(self, deal, auditoria=()):
        self.deal, self.auditoria = deal, list(auditoria)
        self.updates, self.comentarios, self.apagados = [], [], []

    def instalar(self, monkeypatch):
        monkeypatch.setattr(B, "carregar_deal", lambda i: self.deal)
        monkeypatch.setattr(B, "_auditoria_anterior", lambda i: self.auditoria)

        def _bx(metodo, **p):
            if metodo == "crm.deal.update":
                self.updates.append(p["fields"])
            elif metodo == "crm.timeline.comment.add":
                self.comentarios.append(p["fields"]["COMMENT"])
            elif metodo == "crm.timeline.comment.delete":
                self.apagados.append(p["id"])
            return True
        monkeypatch.setattr(B, "_bx", _bx)
        return self


def test_segunda_passada_grava_os_campos_novos(monkeypatch):
    """O caso real: card com 6 campos gravados ganha 2 campos NOVOS ainda
    vazios. A trava antiga recusava tudo — trabalho perdido por uma guarda
    protegendo o que não precisava (quem protege o dado humano é `montar`)."""
    crm = _CRMFalso({"ID": 2273, "CATEGORY_ID": "9", B.CAMPO_VALOR: "88086.53|BRL"},
                    auditoria=[{"ID": 555}]).instalar(monkeypatch)
    campos, pulados = B.montar(crm.deal, valor_liquido="99999.99",
                               natureza="indenizatoria" and "indenizatorio",
                               numero_oficio="057/2025")
    assert B.CAMPO_VALOR not in campos, "não pode sobrescrever o que já está lá"
    r = B.enviar(2273, campos, ["linha"], aplicar=True)

    assert r.get("aplicado") and r.get("completou") is True
    assert crm.updates == [{B.CAMPO_NATUREZA: "Indenizatória",
                            B.CAMPO_NUM_OFICIO: "057/2025"}]


def test_auditoria_substitui_a_anterior_em_vez_de_empilhar(monkeypatch):
    crm = _CRMFalso({"ID": 1, "CATEGORY_ID": "9"},
                    auditoria=[{"ID": 111}, {"ID": 222}]).instalar(monkeypatch)
    B.enviar(1, {B.CAMPO_NUM_OFICIO: "1/2026"}, ["linha"], aplicar=True)
    assert crm.apagados == [111, 222], "comentário antigo ficou na timeline"
    assert len(crm.comentarios) == 1


def test_sem_campo_novo_nao_toca_no_card(monkeypatch):
    """Card completo: nem update, nem comentário novo. Silêncio útil."""
    crm = _CRMFalso({"ID": 1, "CATEGORY_ID": "9"}, auditoria=[{"ID": 1}]).instalar(monkeypatch)
    r = B.enviar(1, {}, ["linha"], aplicar=True)
    assert r.get("nada_novo") is True
    assert crm.updates == [] and crm.comentarios == [] and crm.apagados == []


def test_comentario_de_auditoria_nomeia_quem_conferiu(monkeypatch):
    """O comentário é o que o comercial lê quando o número é questionado —
    "o advogado conferiu" não diz a quem perguntar. O nome vem do login
    individual (`auth.usuario_atual()`)."""
    crm = _CRMFalso({"ID": 1, "CATEGORY_ID": "9"}).instalar(monkeypatch)
    B.enviar(1, {B.CAMPO_NUM_OFICIO: "1/2026"}, ["linha"], aplicar=True,
             autor="Ana Paula")
    assert "conferido por Ana Paula na calculadora" in crm.comentarios[0]


def test_sem_login_individual_o_comentario_nao_inventa_autor(monkeypatch):
    """Ambiente ainda na senha única: melhor genérico que um nome chutado
    dentro de um registro que fica no CRM."""
    crm = _CRMFalso({"ID": 1, "CATEGORY_ID": "9"}).instalar(monkeypatch)
    B.enviar(1, {B.CAMPO_NUM_OFICIO: "1/2026"}, ["linha"], aplicar=True, autor=None)
    assert "conferido pelo advogado na calculadora" in crm.comentarios[0]


def test_campo_de_arquivo_ja_preenchido_nao_vira_lixo_na_tela():
    """O CRM devolve `[{'id': 33695, 'showUrl': '/bitrix/...'}]`; cortar em 34
    caracteres jogava esse objeto interno na cara do advogado."""
    card = {"ID": 1, "CATEGORY_ID": "9",
            B.ANEXOS["oficio"][0]: [{"id": 33697, "showUrl": "/bitrix/x"}]}
    _, pulados = B.montar(card, pecas={"oficio": [("o.pdf", b"A")]})
    assert pulados == ["Anexo - Ofício: já preenchido no card (1 arquivo(s))"]


# ── achar o card sem saber o ID ───────────────────────────────────────────
def test_resolver_id_aceita_numero_hash_e_link():
    """O advogado tem o card ABERTO no navegador — colar o link tem que bastar."""
    assert B.resolver_id("2273") == 2273
    assert B.resolver_id("#2273") == 2273
    assert B.resolver_id("  2273 ") == 2273
    assert B.resolver_id("https://precatur.bitrix24.com.br/crm/deal/details/2273/") == 2273
    assert B.resolver_id("https://x.bitrix24.com.br/crm/deal/details/2273/?IFRAME=Y") == 2273


def test_resolver_id_devolve_none_para_nome():
    """Nome não vira ID — cai na busca, que é outro caminho."""
    assert B.resolver_id("Maria Simulada") is None
    assert B.resolver_id("") is None
    assert B.resolver_id("123.456.789-00") is None


def test_busca_por_cpf_usa_o_campo_e_nao_o_titulo(monkeypatch):
    """CPF é o identificador sem grafia ambígua: 11 dígitos entram pelo campo
    próprio, não pelo LIKE do título."""
    chamadas = []

    def _bx(metodo, **p):
        chamadas.append(p.get("filter"))
        return []
    monkeypatch.setattr(B, "_bx", _bx)
    B.buscar_cards("123.456.789-00")
    assert chamadas[0].get(B.CAMPO_CPF) == "12345678900"
    assert all(f.get("CATEGORY_ID") == B.categoria_permitida() for f in chamadas)


def test_busca_por_cpf_tenta_as_duas_grafias(monkeypatch):
    """O filtro do Bitrix é igualdade literal e o CRM guarda as duas grafias:
    procurar só dígitos deixava invisíveis os 77% do funil 0 que estão
    pontuados (e o contrário, os cards criados pela integração)."""
    chamadas = []

    def _bx(metodo, **p):
        chamadas.append(p.get("filter"))
        return []
    monkeypatch.setattr(B, "_bx", _bx)

    for entrada in ("123.456.789-00", "12345678900"):
        chamadas.clear()
        B.buscar_cards(entrada)
        por_cpf = [f.get(B.CAMPO_CPF) for f in chamadas if B.CAMPO_CPF in f]
        assert por_cpf == ["12345678900", "123.456.789-00"], entrada
        assert any("%TITLE" in f for f in chamadas), "o fallback por nome some"


def test_busca_por_nome_nao_vaza_para_outro_funil(monkeypatch):
    chamadas = []

    def _bx(metodo, **p):
        chamadas.append(p.get("filter"))
        return []
    monkeypatch.setattr(B, "_bx", _bx)
    B.buscar_cards("Maria")
    assert chamadas == [{"CATEGORY_ID": B.categoria_permitida(), "%TITLE": "Maria"}]


def test_busca_ignora_termo_curto(monkeypatch):
    monkeypatch.setattr(B, "_bx", lambda *a, **k: (_ for _ in ()).throw(
        AssertionError("não devia consultar o CRM")))
    assert B.buscar_cards("ma") == []


# ── nada de identificador interno na tela ─────────────────────────────────
def test_etapa_vira_nome_humano(monkeypatch):
    """`UC_K2AH4V` não diz nada ao advogado — é o mesmo erro dos `UF_CRM_*`."""
    chamadas = []

    def _bx(metodo, **p):
        chamadas.append(p["filter"]["ENTITY_ID"])
        return [{"STATUS_ID": "C9:PREPAYMENT_INVOICE", "NAME": "Pré-Análise"},
                {"STATUS_ID": "C9:UC_PRE_FIM", "NAME": "Pré Análise Finalizada"}]
    monkeypatch.setattr(B, "_bx", _bx)
    monkeypatch.setattr(B, "_ETAPAS", {})

    assert B.nome_da_etapa(9, "C9:PREPAYMENT_INVOICE") == "Pré-Análise"
    assert chamadas == ["DEAL_STAGE_9"]
    B.nome_da_etapa(9, "C9:UC_PRE_FIM")
    assert chamadas == ["DEAL_STAGE_9"], "deveria usar o cache, não bater de novo"


def test_etapa_do_funil_0_usa_a_entidade_sem_sufixo(monkeypatch):
    vistos = []
    monkeypatch.setattr(B, "_ETAPAS", {})
    monkeypatch.setattr(B, "_bx", lambda m, **p: vistos.append(p["filter"]["ENTITY_ID"]) or [])
    B.nome_da_etapa(0, "UC_K2AH4V")
    assert vistos == ["DEAL_STAGE"]


def test_etapa_desconhecida_devolve_o_id_em_vez_de_vazio(monkeypatch):
    monkeypatch.setattr(B, "_ETAPAS", {"DEAL_STAGE_9": {}})
    assert B.nome_da_etapa(9, "C9:XPTO") == "C9:XPTO"


def test_percentual_do_card_vira_numero_puro():
    """O campo é texto livre: o time escreve "30%", "30% ", "30,5%". A
    calculadora recusava "30%" com "Valor inválido" — e o preenchimento
    automático, que existe para poupar digitação, virava erro na tela."""
    assert B._pct("30% ") == "30"
    assert B._pct("30") == "30"
    assert B._pct("30,5%") == "30,5"
    assert B._pct("  ") is None
    assert B._pct(None) is None
    # PROSA no campo de percentual = ausência, não dado. O time escreve isto
    # com frequência, e sem o filtro a limpeza de espaços entregava
    # "Nãoconstanosaultos" como se fosse percentual — medido no ledger de
    # adjudicação (24/08/2026): 5 dos 9 registros, o campo mais corrigido.
    assert B._pct("Não consta nos autos") is None
    assert B._pct("Não encontrado") is None
    assert B._pct("Não consta contrato de honorários") is None
    assert B._pct("a definir") is None
    # o que É número continua passando
    assert B._pct("12.5") == "12.5"
    assert B._pct("0") == "0"
