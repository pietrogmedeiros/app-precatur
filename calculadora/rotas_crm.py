"""Rotas do CRM (Bitrix) e do hub — o que sai da calculadora para o comercial.

Nada aqui calcula. O número que vai para o card é o que está NA TELA: o advogado
já conferiu, e recalcular no envio deixaria o card receber um valor diferente do
que ele viu.

Duas regras herdadas do app original, e as duas são de confiança, não de código:

- **Ensaio antes de aplicar.** `montar` só preenche campo VAZIO; o ensaio mostra
  o que seria gravado e o que foi pulado, sem tocar no CRM.
- **Journal primeiro.** Quando o hub existe, a INTENÇÃO de escrever é registrada
  antes de o card ser tocado, e a conclusão depois. Se o envio falhar no meio,
  sobra rastro — a ordem inversa perderia justamente o caso que importa.
"""
from __future__ import annotations

import base64
from datetime import date
from decimal import Decimal, InvalidOperation

from fastapi import APIRouter, Body, HTTPException

router = APIRouter(prefix="/crm", tags=["crm"])


def _bitrix():
    import bitrix
    if not bitrix.habilitado():
        raise HTTPException(status_code=503, detail=(
            "Envio ao CRM desligado neste ambiente (BITRIX_WEBHOOK)."))
    return bitrix


def _hub():
    try:
        import hub
    except Exception:  # noqa: BLE001
        return None
    return hub if hub.habilitado() else None


def _erro_do_bitrix(exc: RuntimeError) -> HTTPException:
    """Traduz a recusa do `bitrix.py` no status que diz a verdade.

    Isto não é preciosismo de REST: o proxy que publica o app (Traefik, no
    EasyPanel) TROCA o corpo de qualquer 5xx pela página "Service is not
    reachable". Mandar "funil proibido: o card #7527 está no funil 0 e este
    ambiente só escreve no 9" dentro de um 502 é o mesmo que não mandar nada —
    a tela recebe um corpo HTML sem `message` e só consegue dizer "a calculadora
    respondeu 502". Foi exatamente o que apareceu no primeiro uso real.

    Recusa de regra (funil, card inexistente) é 4xx e chega inteira ao advogado;
    502 fica para o que é de fato falha de infraestrutura — e aí a página do
    proxy, pelo menos, não mente.
    """
    msg = str(exc)
    if msg.startswith("funil proibido"):
        return HTTPException(status_code=409, detail=msg)
    if "não encontrado" in msg:
        return HTTPException(status_code=404, detail=msg)
    return HTTPException(status_code=502, detail=msg)


def _dec(v):
    if v in (None, ""):
        return None
    try:
        return Decimal(str(v))
    except (InvalidOperation, ValueError):
        return None


def _data(v):
    if not v:
        return None
    try:
        return date.fromisoformat(str(v)[:10])
    except ValueError:
        return None


def _brl(v) -> str:
    if v is None:
        return "—"
    d = Decimal(str(v))
    neg = d < 0
    d = abs(d).quantize(Decimal("0.01"))
    intp, dec = f"{d:.2f}".split(".")
    intp = f"{int(intp):,}".replace(",", ".")
    return f"{'-' if neg else ''}R$ {intp},{dec}"


def _data_br(d) -> str:
    try:
        return date.fromisoformat(str(d)[:10]).strftime("%d/%m/%Y")
    except Exception:  # noqa: BLE001
        return str(d or "—")


@router.get("/estado")
def estado() -> dict:
    import bitrix
    hub = _hub()
    ligado = bitrix.habilitado()
    return {"bitrix": ligado, "hub": hub is not None,
            # `funil_permitido` (singular) continua por compatibilidade: é o
            # funil de casa. Quem decide a recusa é a LISTA.
            "funil_permitido": bitrix.categoria_permitida() if ligado else None,
            "funis_permitidos": bitrix.categorias_permitidas() if ligado else None}


@router.get("/cards")
def cards(termo: str, limite: int = 12) -> dict:
    """Busca por nome, CPF, ID ou link colado — o advogado não decora ID.

    ID e link NÃO passam pelo `buscar_cards`: ele filtra por `%TITLE`, e procurar
    "2693" no TÍTULO não acha o card #2693. Quem informa o ID já disse qual card
    quer, então vamos direto nele — é o que a tela antiga fazia. O funil continua
    guardado na gravação (`enviar` recusa card fora do funil permitido), e é lá
    que a recusa é explicada.
    """
    bx = _bitrix()
    deal_id = bx.resolver_id(termo)
    if deal_id is not None:
        try:
            card = bx.resumo_do_card(deal_id)
        except RuntimeError:
            return {"cards": []}       # ID que não existe: some, como um nome sem resultado
        return {"cards": [{"id": card["id"], "titulo": card["titulo"],
                           "etapa": card["etapa"], "funil": card["funil"],
                           "url": card["url"]}]}
    try:
        return {"cards": bx.buscar_cards(termo, limite=limite)}
    except RuntimeError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@router.get("/card/{deal_id}")
def card(deal_id: int) -> dict:
    """O que o card sabe e o processo não: honorário contratual e nº do precatório."""
    bx = _bitrix()
    try:
        return bx.resumo_do_card(deal_id)
    except RuntimeError as exc:
        raise _erro_do_bitrix(exc) from exc


# campo do envio → campo que a pré-análise extrai
_CAMPOS_MEDIDOS = {"numero_precatorio": "numero_precatorio", "numero_oficio": "numero_oficio",
                   "honorarios_contratuais_pct": "honorarios_contratuais_pct",
                   "natureza": "natureza_tributaria"}


def _medir_envio(sessao: str, corpo: dict) -> None:
    """Telemetria: o advogado manteve o que a pré-análise extraiu? Nunca falha."""
    try:
        from prefill import telemetria
        from rotas_documentos import extraido_da_sessao
        extraido = extraido_da_sessao(sessao)
        if extraido is None:
            return
        telemetria.registrar_envio(
            sessao, {k: extraido.get(v) for k, v in _CAMPOS_MEDIDOS.items()},
            {k: corpo.get(k) for k in _CAMPOS_MEDIDOS})
    except Exception:  # noqa: BLE001
        pass


@router.post("/enviar")
def enviar(corpo: dict = Body(...)) -> dict:
    """Ensaio (`aplicar=false`) ou gravação no card.

    O memorial chega em **base64**, o mesmo PDF que o advogado baixou: gerar
    outro aqui deixaria o card com um memorial diferente do conferido.
    """
    bx = _bitrix()
    deal_id = corpo.get("deal_id")
    if not deal_id:
        raise HTTPException(status_code=422, detail="Informe o card (deal_id).")
    deal_id = int(deal_id)
    try:
        deal = bx.carregar_deal(deal_id)
    except RuntimeError as exc:
        raise _erro_do_bitrix(exc) from exc

    liquido = _dec(corpo.get("valor_liquido"))
    hon_con = _dec(corpo.get("honorarios_contratuais_pct"))
    alvo = _data(corpo.get("atualizado_para")) or date.today()
    aviso_projecao = corpo.get("aviso_projecao") or None
    referencia = (corpo.get("referencia") or "").strip()
    autor = (corpo.get("autor") or "").strip() or None
    pdf = corpo.get("memorial_pdf")
    try:
        pdf_bytes = base64.b64decode(pdf) if pdf else None
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=422, detail=f"memorial_pdf inválido: {exc}") from exc

    # As peças da pré-análise (conta, ofício, sentença) vão junto, recortadas do
    # processo quando ele veio inteiro. Antes ia `pecas=None` sempre e o card
    # ficava só com o memorial (card #8081, 28/10/2026).
    pecas, aviso_pecas = None, None
    if corpo.get("sessao_prefill"):
        try:
            from rotas_documentos import pecas_da_sessao
            pecas, aviso_pecas = pecas_da_sessao(str(corpo["sessao_prefill"]), deal_id)
        except Exception as exc:  # noqa: BLE001 — sem anexo, o envio segue
            aviso_pecas = f"Anexos das peças: não consegui recortar ({type(exc).__name__})."

    campos, pulados = bx.montar(
        deal, valor_liquido=liquido, hon_contratuais=hon_con,
        atualizado_para=alvo,
        numero_precatorio=(corpo.get("numero_precatorio") or "").strip() or None,
        numero_oficio=(corpo.get("numero_oficio") or "").strip() or None,
        natureza=(corpo.get("natureza") or None),
        memorial_pdf=pdf_bytes, pecas=pecas)
    if aviso_pecas:
        pulados.append(aviso_pecas)

    # As linhas da auditoria são as da TELA (o que o advogado leu), não um
    # resumo derivado dos campos — é esse texto que o comercial lê no card.
    linhas = [
        f"Valor final atualizado: {_brl(liquido)}",
        f"Atualizado até {_data_br(alvo)}"
        + (f" · {aviso_projecao}" if aviso_projecao else " · índice publicado"),
        f"Honorários contratuais: {hon_con}%" if hon_con
        else "Honorários contratuais: NÃO informados — valor acima é BRUTO",
        f"Referência: {referencia or '—'}",
    ]

    aplicar = bool(corpo.get("aplicar"))
    avisos: list[str] = []

    # Journal ANTES de tocar o card (só quando o valor vai mesmo ser escrito).
    hub = _hub() if aplicar else None
    caso_id = (corpo.get("caso_id") or "").strip() or None
    if hub is not None:
        try:
            caso_id = caso_id or ((hub.caso_do_card(deal_id) or {}).get("id"))
        except Exception as exc:  # noqa: BLE001 — hub fora não impede enviar
            avisos.append(f"hub indisponível ({type(exc).__name__}) — o envio segue")
            caso_id = None
    if hub is not None and caso_id and bx.CAMPO_VALOR in campos:
        try:
            hub.journal_registrar(
                caso_id, deal_id=str(deal_id), tipo="envio",
                valor_antes=str(deal.get(bx.CAMPO_VALOR) or ""),
                valor_depois=str(campos[bx.CAMPO_VALOR]), snapshot_id=None, autor=autor)
        except Exception as exc:  # noqa: BLE001
            avisos.append(f"journal não registrou ({type(exc).__name__}) — o envio segue")

    try:
        resposta = bx.enviar(deal_id, campos, linhas, aplicar=aplicar, autor=autor)
    except RuntimeError as exc:
        raise _erro_do_bitrix(exc) from exc

    if aplicar and corpo.get("sessao_prefill"):
        _medir_envio(str(corpo["sessao_prefill"]), corpo)

    resposta["pulados"] = pulados
    resposta["linhas_auditoria"] = linhas
    if avisos:
        resposta["avisos"] = avisos
    return resposta
