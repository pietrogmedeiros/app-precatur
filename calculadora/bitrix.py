"""I/O com o CRM (Bitrix24) — a ÚNICA parte deste app que conhece campo UF_*.

Fronteira de propósito: a calculadora calcula, este módulo fala com o CRM.
Quando o fluxo migrar para o hub da VM, é este arquivo que muda de casa (vira
`bitrix_sync`), não a tela.

Três guardas, todas herdadas do worker v0 que já rodou contra cards reais:

  TRAVA DE FUNIL   escreve só em `BITRIX_CATEGORIA` (9 = Vendas, o sandbox).
                   Card de outro funil devolve erro, não silêncio.
  SÓ CAMPO VAZIO   nunca sobrescreve o que um humano preencheu.
  IDEMPOTÊNCIA     o comentário de auditoria leva um marcador; rodar de novo no
                   mesmo card não empilha nem duplica.

Escrever por webhook é o caminho validado — BAIXAR anexo do card é que exige
cookie/OAuth, e por isso o desenho novo faz o advogado subir os PDFs aqui.
"""
from __future__ import annotations

import base64
import json
import os
import re
from datetime import date
from decimal import Decimal, InvalidOperation
from pathlib import Path

import httpx

# ── campos (fonte única: bitrix_campos.json, sincronizado por CI a partir de
# Callix/bitrix_sync/campos.json — ver .github/workflows/sincronizar-campos-
# bitrix.yml e Precatur/INDICE.md) ─────────────────────────────────────────
# NUNCA hardcode um UF_CRM_* aqui de novo. Editar valor = editar campos.json
# no Callix, que se propaga sozinho no próximo sync diário (ou manual via
# workflow_dispatch).
#
# ⚠ O CRM tem 3-4 gerações de cada campo de anexo ("Anexo - Ofício" existe 4
# vezes). Os IDs abaixo são os que ESTÃO no layout do funil 9 — escrever em
# qualquer um dos outros grava num campo que o advogado não vê no card.
_CAMPOS = json.loads(
    (Path(__file__).parent / "bitrix_campos.json").read_text(encoding="utf-8")
)["campos"]


def _campo(chave: str) -> str:
    return _CAMPOS[chave]["id"]


CAMPO_VALOR = _campo("valor_atualizado")            # Cálculo Atualizado (Valor)
CAMPO_HON_CONTR = _campo("honorarios_contratuais_pct")  # Honorários Contratuais (%)
CAMPO_PRECATORIO = _campo("numero_precatorio")      # Nº Precatório (seção SDR)
CAMPO_NATUREZA = _campo("natureza")                 # Natureza (texto livre)
CAMPO_NUM_OFICIO = _campo("numero_oficio")          # Número Ofício
CAMPO_CPF = _campo("cpf")                           # CPF (seção SDR do layout do funil 9)

# O campo "Natureza" é texto LIVRE e o time já escreveu 747 vezes. Levantei o
# vocabulário real do funil 0 antes de inventar o meu: as formas dominantes são
# femininas e acentuadas — "Remuneratória" (43) supera "Remuneratório" (21),
# "Indenizatória" (31) supera "Indenizatório" (19). Escrever fora desse padrão
# criaria uma 12ª grafia num campo que já sofre de dispersão.
#
# ⚠ O campo mistura DOIS eixos: o tributário (remuneratória/indenizatória, que é
# o que extraímos e decide PSS/IR) e o de preferência constitucional
# (alimentar/comum, 40 ocorrências). Só escrevemos o tributário.
NATUREZA_CRM = {
    "remuneratorio": "Remuneratória",
    "previdenciario": "Previdenciária",
    "indenizatorio": "Indenizatória",
    "misto": "Mista",
}

# peça → (campo, aceita múltiplos arquivos)
ANEXOS = {
    "memorial": (_campo("anexo_memorial"), True),    # Anexo - Cálculo Atualizado
    "conta": (_campo("anexo_conta"), False),         # Anexo - Cálculos Homologados
    "oficio": (_campo("anexo_oficio"), True),        # Anexo - Ofício
    "sentenca": (_campo("anexo_sentenca"), True),    # Anexo - Sentença / Acórdão
}

MARCADOR = "[pre-analise]"
VAZIO = (None, "", "0", "0|BRL", "R$ 0,00", [], {})

# Rótulo humano de cada campo — como aparece NO CARD. Ninguém deve precisar ler
# `UF_CRM_1769029222658` para conferir o que vai ser gravado; o ID é endereço
# interno, e mostrar endereço no lugar de nome é jogar a tradução no advogado.
ROTULOS = {
    CAMPO_VALOR: "Cálculo Atualizado (Valor)",
    CAMPO_HON_CONTR: "Honorários Contratuais (%)",
    CAMPO_PRECATORIO: "Nº Precatório",
    CAMPO_NATUREZA: "Natureza",
    CAMPO_NUM_OFICIO: "Número Ofício",
    ANEXOS["memorial"][0]: "Anexo - Cálculo Atualizado",
    ANEXOS["conta"][0]: "Anexo - Cálculos Homologados",
    ANEXOS["oficio"][0]: "Anexo - Ofício",
    ANEXOS["sentenca"][0]: "Anexo - Sentença / Acórdão",
}


def descrever(campos: dict) -> list[str]:
    """`{UF_*: valor}` → linhas legíveis, com o VALOR que será gravado.

    Conferência de verdade é ver o número indo para o campo certo, não uma
    lista de identificadores.
    """
    linhas = []
    for campo, valor in campos.items():
        rot = ROTULOS.get(campo, campo)
        if isinstance(valor, list):          # anexo múltiplo
            nomes = ", ".join(a["fileData"][0] for a in valor if isinstance(a, dict))
            linhas.append(f"{rot}: {nomes}")
        elif isinstance(valor, dict):        # anexo de arquivo único
            linhas.append(f"{rot}: {valor.get('fileData', ['?'])[0]}")
        else:
            linhas.append(f"{rot}: {valor}")
    return sorted(linhas)


def categorias_permitidas() -> list[int]:
    """Funis em que ESTE ambiente pode escrever. `BITRIX_CATEGORIA` aceita lista.

    Era um funil só. Virou lista em 16/10/2026 porque a pré-análise acontece em
    dois lugares no CRM da casa: o funil 9 e o funil 0, onde mora a etapa
    "PRÉ ANÁLISE - FEDERAL". O advogado chegava no card federal pela busca por
    ID e o envio recusava — a trava certa, no card errado.

    Um valor só (`BITRIX_CATEGORIA=9`) continua valendo exatamente como antes.
    """
    bruto = str(os.environ.get("BITRIX_CATEGORIA", "9")).replace(";", ",")
    return [int(p) for p in bruto.split(",") if p.strip()] or [9]


def categoria_permitida() -> int:
    """O funil "de casa" — o primeiro da lista. É o que a busca filtra."""
    return categorias_permitidas()[0]


def _funil_permitido(deal: dict) -> bool:
    return str(deal.get("CATEGORY_ID")) in {str(c) for c in categorias_permitidas()}


def _recusa_de_funil(deal_id: int, deal: dict) -> RuntimeError:
    permitidas = ", ".join(str(c) for c in categorias_permitidas())
    return RuntimeError(
        f"funil proibido: o card #{deal_id} está no funil {deal.get('CATEGORY_ID')} "
        f"e este ambiente só escreve no {permitidas}.")


def habilitado() -> bool:
    return bool(os.environ.get("BITRIX_WEBHOOK"))


def _bx(metodo: str, **params):
    wh = (os.environ.get("BITRIX_WEBHOOK") or "").rstrip("/")
    if not wh:
        raise RuntimeError("BITRIX_WEBHOOK não configurado neste ambiente.")
    r = httpx.post(f"{wh}/{metodo}.json", json=params, timeout=180.0)
    d = r.json()
    if d.get("error"):
        raise RuntimeError(f"{metodo}: {d.get('error_description') or d['error']}")
    return d.get("result")


def carregar_deal(deal_id: int) -> dict:
    d = _bx("crm.deal.get", id=int(deal_id))
    if not d:
        raise RuntimeError(f"card #{deal_id} não encontrado")
    return d


_ETAPAS: dict[str, dict[str, str]] = {}


def nome_da_etapa(funil: str | int, stage_id: str) -> str:
    """`C9:PREPAYMENT_INVOICE` → "Pré-Análise".

    O advogado não decora STATUS_ID, e mostrá-lo é o mesmo erro dos `UF_CRM_*`:
    empurrar endereço interno para quem só quer o nome. A lista vem do próprio
    CRM (`crm.status.list`), com cache por funil — muda raramente e uma chamada
    por sessão basta.
    """
    if not stage_id:
        return ""
    entidade = f"DEAL_STAGE_{funil}" if str(funil) not in ("", "0") else "DEAL_STAGE"
    if entidade not in _ETAPAS:
        try:
            itens = _bx("crm.status.list", filter={"ENTITY_ID": entidade}) or []
            _ETAPAS[entidade] = {s["STATUS_ID"]: s["NAME"] for s in itens}
        except Exception:  # noqa: BLE001 — inclui erro de REDE (httpx), não só RuntimeError
            # Traduzir um rótulo é cosmético: se falhar, mostra o ID cru e o
            # trabalho continua. Deixar a exceção subir derrubaria o ENVIO por
            # causa de um nome de etapa — trocar a função pelo produto.
            _ETAPAS[entidade] = {}
    return _ETAPAS[entidade].get(stage_id) or stage_id


def _pct(valor) -> str | None:
    """Percentual do card em número puro: `"30% "` → `"30"`.

    O campo é texto livre e o time escreve com `%`, espaço, às vezes vírgula. A
    calculadora recusa `"30%"` ("Valor inválido") — e o preenchimento
    automático, que existe para poupar digitação, virava um erro na tela.

    ⚠ O time também escreve FRASE onde deveria ir número: "Não consta nos
    autos", "Não encontrado", "Não consta contrato de honorários". Sem filtro
    numérico, a limpeza de espaços virava `Nãoconstanosaultos` e entregava a
    prosa como se fosse percentual — o advogado apagava o campo à mão. Medido
    no ledger de adjudicação (24/08/2026): **5 dos 9 registros** tinham esse
    texto em `hc`, o campo mais corrigido de todos. Frase não é ausência de
    dado com aparência de dado: é ausência, e ausência se escreve None.
    """
    if valor is None:
        return None
    limpo = str(valor).replace("%", "").replace(" ", "").strip()
    limpo = limpo.rstrip(".,")
    if not limpo:
        return None
    # Só número (inteiro ou com 1-2 casas decimais). Qualquer outra coisa é
    # ANOTAÇÃO do time, não percentual — ver o aviso no docstring.
    if not re.fullmatch(r"\d{1,3}(?:[.,]\d{1,2})?", limpo):
        return None
    return limpo


def resumo_do_card(deal_id: int) -> dict:
    """O que o CARD sabe e o PROCESSO não.

    Dois campos justificam ler o card ANTES de extrair:

    - **honorários contratuais**: vêm do contrato com o cliente, não dos autos.
      Só 20% dos casos medidos os declaram em algum documento, e sem eles o
      "líquido" sai igual ao bruto — 43% de diferença num número que o comercial
      lê como proposta.
    - **nº do precatório**: o ANO dele é a âncora do período de graça (vale
      −5,4%), e é determinístico — está digitado no card, não escondido no PDF.
    """
    d = carregar_deal(deal_id)
    portal = (os.environ.get("BITRIX_PORTAL")
              or "https://precatur.bitrix24.com.br").rstrip("/")
    return {
        "id": int(deal_id),
        "titulo": d.get("TITLE") or "",
        "funil": str(d.get("CATEGORY_ID")),
        "etapa": nome_da_etapa(d.get("CATEGORY_ID"), d.get("STAGE_ID") or ""),
        "etapa_id": d.get("STAGE_ID") or "",
        "url": f"{portal}/crm/deal/details/{int(deal_id)}/",
        "honorarios_contratuais_pct": _pct(d.get(CAMPO_HON_CONTR)),
        "numero_precatorio": (d.get(CAMPO_PRECATORIO) or "").strip() or None,
        "deal": d,
    }


# ── achar o card sem saber o ID ────────────────────────────────────────────
# O advogado não decora número de negócio. Ele tem à mão o NOME do cliente, o
# CPF, ou o link do card aberto no navegador — e é por qualquer um desses que a
# tela deve aceitar entrar.
_RE_ID_URL = re.compile(r"/deal/details/(\d+)")
_RE_SO_DIGITOS = re.compile(r"^#?\s*(\d{1,9})\s*$")


def resolver_id(texto: str) -> int | None:
    """ID a partir do que o advogado tiver: `2273`, `#2273` ou o link do card."""
    texto = (texto or "").strip()
    if not texto:
        return None
    m = _RE_ID_URL.search(texto) or _RE_SO_DIGITOS.match(texto)
    return int(m.group(1)) if m else None


def buscar_cards(termo: str, limite: int = 12) -> list[dict]:
    """Cards do funil permitido por NOME ou CPF.

    CPF entra com 11 dígitos (com ou sem pontuação) — é o identificador que não
    tem grafia ambígua. Nome usa `%TITLE`, o LIKE do Bitrix.

    O CPF é procurado nas DUAS grafias, porque o campo no CRM guarda as duas e o
    filtro do Bitrix é igualdade literal: buscar "12345678900" não acha um card
    gravado "123.456.789-00", e vice-versa. Medido em 10/08/2026 — 77% do funil 0
    está formatado e 11% em dígitos puros; procurar só uma forma deixava a maior
    parte da base invisível para a busca por CPF.
    """
    termo = (termo or "").strip()
    if len(termo) < 3:
        return []
    # Lista: o Bitrix trata array como "IN" (conferido contra o CRM da casa em
    # 16/10/2026). Se a busca só olhasse o funil de casa, o card federal seria
    # invisível por nome e só apareceria por ID — e é por nome que se procura.
    base = {"CATEGORY_ID": categorias_permitidas()}
    digitos = re.sub(r"\D", "", termo)
    filtros = []
    if len(digitos) == 11:
        pontuado = f"{digitos[:3]}.{digitos[3:6]}.{digitos[6:9]}-{digitos[9:]}"
        filtros = [{**base, CAMPO_CPF: digitos}, {**base, CAMPO_CPF: pontuado}]
    filtros.append({**base, "%TITLE": termo})
    vistos, out = set(), []
    for filtro in filtros:
        for d in (_bx("crm.deal.list", filter=filtro,
                      select=["ID", "TITLE", "STAGE_ID"]) or []):
            if d["ID"] in vistos:
                continue
            vistos.add(d["ID"])
            out.append({"id": int(d["ID"]), "titulo": d.get("TITLE") or "",
                        "etapa": d.get("STAGE_ID") or ""})
    return out[:limite]


def _auditoria_anterior(deal_id: int) -> list[dict]:
    try:
        coms = _bx("crm.timeline.comment.list",
                   filter={"ENTITY_ID": int(deal_id), "ENTITY_TYPE": "deal"}) or []
    except RuntimeError:
        return []
    return [c for c in coms if MARCADOR in (c.get("COMMENT") or "")]


def _arquivo(nome: str, conteudo: bytes) -> dict:
    return {"fileData": [nome, base64.b64encode(conteudo).decode("ascii")]}


def brl(valor: Decimal) -> str:
    """Dinheiro na grafia da casa: `R$ 88.086,53`.

    ⚠ NÃO usar `88086.53|BRL`: essa é a sintaxe de campo MONEY do Bitrix, e
    "Cálculo Atualizado (Valor)" é `string` — o sufixo ia parar no card como
    texto literal. Levantei o formato nos 704 cards já preenchidos do funil 0:
    `R$ 999.999,99` domina (150 + 124 + …), e `|BRL` não aparece em nenhum.
    """
    inteiro = f"{valor:,.2f}"                    # 88,086.53 (padrão en)
    return "R$ " + inteiro.replace(",", "·").replace(".", ",").replace("·", ".")


_MESES = ("Janeiro", "Fevereiro", "Março", "Abril", "Maio", "Junho",
          "Julho", "Agosto", "Setembro", "Outubro", "Novembro", "Dezembro")


def _mes_ano(d) -> str | None:
    """`date` ou 'YYYY-MM-DD' → 'Agosto/2026'. None quando não dá para ler.

    Nome do mês por tabela, não por `strftime('%B')`: o locale do servidor é o
    do sistema (a VM roda em inglês) e o campo sairia "August/2026" no card.
    """
    if d is None:
        return None
    if not isinstance(d, date):
        try:
            d = date.fromisoformat(str(d)[:10])
        except ValueError:
            return None
    return f"{_MESES[d.month - 1]}/{d.year}"


def brl_atualizado(valor: Decimal, data_alvo=None) -> str:
    """`R$ 180.443,82 (Atualizado para Agosto/2026)`.

    Pedido dos advogados (25/08/2026): o valor sozinho no card não diz A QUE
    DATA ele está atualizado, e um "Cálculo Atualizado" de três meses atrás é
    indistinguível de um de hoje na hora de fazer a proposta.

    Não é invenção de formato — é a convenção que o time já usa à mão (ex.:
    #1323 SAYONARA MIOTTO, "R$ 293.921,22 (Atualizado para Junho/2026)").

    Seguro para o warehouse: o extrator de valores do `stg_bitrix__deals`
    descarta tokens `^(19|20)\\d{2}$`, então o "2026" do sufixo não vira um
    segundo número e o campo continua com `valor_liquido_status = 'ok'`.
    Conferido no #1323, que tem exatamente esta grafia.

    Sem data legível devolve só o valor — melhor sem sufixo que com um errado.
    """
    txt = brl(valor)
    mes = _mes_ano(data_alvo)
    return f"{txt} (Atualizado para {mes})" if mes else txt


def _dec(x) -> Decimal | None:
    """Dinheiro em Decimal, venha de onde vier.

    `calcular_dict` serializa os valores como STRING ("88086.53"), não Decimal —
    formatar isso com `:.2f` estoura com "Unknown format code 'f' for object of
    type 'str'". Converter na fronteira do módulo é mais barato que confiar no
    tipo que o chamador manda.
    """
    if x is None or isinstance(x, Decimal):
        return x
    try:
        return Decimal(str(x).strip().replace(" ", ""))
    except (InvalidOperation, ValueError):
        return None


def montar(deal: dict, valor_liquido=None, hon_contratuais=None, numero_precatorio=None,
           natureza=None, numero_oficio=None,
           memorial_pdf: bytes | None = None, pecas: dict | None = None,
           atualizado_para=None) -> tuple[dict, list[str]]:
    """Campos a escrever + o que foi PULADO (e por quê). Não toca no CRM.

    `pecas` = {"conta": [(nome, bytes)], "oficio": [...], "sentenca": [...]}.
    """
    campos: dict = {}
    pulados: list[str] = []

    def _resumo(valor) -> str:
        """O que JÁ está no campo, em uma linha. Campo de arquivo devolve o
        objeto interno do CRM (`[{'id': 33695, 'showUrl': '/bitrix/...'}]`);
        cortar isso em 34 caracteres joga lixo na tela."""
        if isinstance(valor, list):
            return f"{len(valor)} arquivo(s)"
        if isinstance(valor, dict):
            return "1 arquivo"
        texto = str(valor)
        return texto if len(texto) <= 40 else texto[:39] + "…"

    def por(campo: str, novo, rotulo: str):
        atual = deal.get(campo)
        if atual in VAZIO:
            campos[campo] = novo
        else:
            pulados.append(f"{rotulo}: já preenchido no card ({_resumo(atual)})")

    _valor = _dec(valor_liquido)
    if _valor is not None:
        por(CAMPO_VALOR, brl_atualizado(_valor, atualizado_para),
            "Cálculo Atualizado (Valor)")
    elif valor_liquido is not None:
        pulados.append(f"Cálculo Atualizado (Valor): valor ilegível ({valor_liquido!r})")
    if hon_contratuais:
        por(CAMPO_HON_CONTR, str(hon_contratuais), "Honorários Contratuais (%)")
    if natureza:
        # a chave interna (remuneratorio…) vira a grafia da casa; valor fora do
        # vocabulário conhecido NÃO é escrito — inventar grafia é pior que vazio
        rotulo_nat = NATUREZA_CRM.get(str(natureza).strip().lower())
        if rotulo_nat:
            por(CAMPO_NATUREZA, rotulo_nat, "Natureza")
        else:
            pulados.append(f"Natureza: valor desconhecido ({natureza!r}) — não escrevi")
    if numero_oficio:
        por(CAMPO_NUM_OFICIO, str(numero_oficio).strip(), "Número Ofício")
    if numero_precatorio:
        por(CAMPO_PRECATORIO, str(numero_precatorio), "Nº Precatório")
    if memorial_pdf:
        campo, _ = ANEXOS["memorial"]
        por(campo, [_arquivo(f"memorial_calculo_{deal.get('ID')}.pdf", memorial_pdf)],
            "Anexo - Cálculo Atualizado")

    for chave, arquivos in (pecas or {}).items():
        if not arquivos or chave not in ANEXOS:
            continue
        campo, multiplo = ANEXOS[chave]
        # campo de arquivo ÚNICO (a conta homologada é assim) só aceita um: manda
        # o primeiro e avisa, em vez de estourar ou perder o resto em silêncio.
        if not multiplo:
            nome, dados = arquivos[0]
            por(campo, _arquivo(nome, dados), ROTULOS.get(campo, chave))
            if len(arquivos) > 1:
                pulados.append(f"{ROTULOS.get(campo, chave)}: o campo aceita 1 arquivo, "
                               f"{len(arquivos) - 1} não foram enviados")
        else:
            por(campo, [_arquivo(n, b) for n, b in arquivos], ROTULOS.get(campo, chave))

    return campos, pulados


def sobrescrever_valor(deal_id: int, texto: str) -> dict:
    """Escreve `texto` em *Cálculo Atualizado (Valor)* MESMO com o campo cheio.

    A única porta que contorna o "só campo vazio" de `montar` — e por isso o
    contrato do chamador (Fase 2) é journal-PRIMEIRO: registrar a entrada no
    `valor_journal` do hub ANTES de chamar aqui, e concluí-la depois. Este
    módulo escreve; quem audita é o journal.

    Sem comentário na timeline, por decisão de desenho (01/09/2026): a trilha
    da sobrescrita é interna (hub), não poluição do card. `texto` vazio limpa
    o campo — é o que uma reversão de primeiro envio legitimamente faz.

    Mesma trava de funil do `enviar`: card fora de `BITRIX_CATEGORIA` recusa.
    """
    deal = carregar_deal(deal_id)
    if not _funil_permitido(deal):
        raise _recusa_de_funil(deal_id, deal)
    _bx("crm.deal.update", id=int(deal_id), fields={CAMPO_VALOR: texto})
    return {"aplicado": True, "valor_antes": deal.get(CAMPO_VALOR)}


def enviar(deal_id: int, campos: dict, linhas_auditoria: list[str],
           aplicar: bool = False, autor: str | None = None) -> dict:
    """Grava no card. `aplicar=False` é ensaio: não chama nada que escreve.

    `autor` é quem estava logado na calculadora (`auth.usuario_atual()`). Entra
    no comentário de auditoria porque é ele que o comercial lê no card: "o
    advogado conferiu" não diz a quem perguntar quando o número é questionado.
    None (ambiente sem login individual) mantém o texto genérico de antes — sem
    autor é melhor que com autor chutado num registro que fica no CRM.
    """
    deal = carregar_deal(deal_id)
    if not _funil_permitido(deal):
        raise _recusa_de_funil(deal_id, deal)

    anteriores = _auditoria_anterior(deal_id)
    quem = f"por {autor.strip()}" if (autor or "").strip() else "pelo advogado"
    comentario = (f"{MARCADOR} Pré-análise: valores extraídos dos documentos anexados e "
                  f"cálculo conferido {quem} na calculadora.\n\n"
                  + "\n".join(linhas_auditoria))

    if not aplicar:
        return {"ensaio": True, "ja_rodou_antes": bool(anteriores),
                "campos": sorted(campos), "descricao": descrever(campos),
                "comentario": comentario}
    # ⚠ Rodar de novo COMPLETA o card; não é bloqueado.
    #
    # A trava original recusava tudo quando já havia auditoria na timeline, e
    # isso barrou o caso legítimo que apareceu no teste: o card tinha 6 campos
    # gravados, ganhou dois campos NOVOS ainda vazios (Natureza e Número
    # Ofício), e a segunda passada foi recusada inteira — trabalho perdido por
    # uma guarda protegendo o que não precisava.
    #
    # Quem protege o dado humano é `montar`, que só preenche campo VAZIO. Sobra
    # a auditoria, e essa não pode EMPILHAR: o comentário anterior é substituído
    # por um novo, que descreve o estado atual do card.
    if not campos:
        return {"nada_novo": True, "ja_rodou_antes": bool(anteriores),
                "detalhe": "nenhum campo novo a gravar — o resto já está preenchido no card."}

    _bx("crm.deal.update", id=int(deal_id), fields=campos)
    for c in anteriores:
        try:
            _bx("crm.timeline.comment.delete", id=c["ID"])
        except RuntimeError:
            pass
    _bx("crm.timeline.comment.add",
        fields={"ENTITY_ID": int(deal_id), "ENTITY_TYPE": "deal", "COMMENT": comentario})
    return {"aplicado": True, "campos": sorted(campos),
            "descricao": descrever(campos), "completou": bool(anteriores)}
