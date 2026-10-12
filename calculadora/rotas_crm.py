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
    return {"bitrix": bitrix.habilitado(), "hub": hub is not None,
            "funil_permitido": bitrix.categoria_permitida() if bitrix.habilitado() else None}


@router.get("/cards")
def cards(termo: str, limite: int = 12) -> dict:
    """Busca por nome, CPF, ID ou link colado — o advogado não decora ID."""
    bx = _bitrix()
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
        raise HTTPException(status_code=502, detail=str(exc)) from exc


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
        raise HTTPException(status_code=502, detail=str(exc)) from exc

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

    campos, pulados = bx.montar(
        deal, valor_liquido=liquido, hon_contratuais=hon_con,
        atualizado_para=alvo,
        numero_precatorio=(corpo.get("numero_precatorio") or "").strip() or None,
        numero_oficio=(corpo.get("numero_oficio") or "").strip() or None,
        natureza=(corpo.get("natureza") or None),
        memorial_pdf=pdf_bytes, pecas=None)

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
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    resposta["pulados"] = pulados
    resposta["linhas_auditoria"] = linhas
    if avisos:
        resposta["avisos"] = avisos
    return resposta
