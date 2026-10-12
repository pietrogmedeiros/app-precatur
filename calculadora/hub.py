"""Cliente do hub (PrecaturIA) — onde o CASO mora.

Divisão de papéis, para não duplicar armazém:

  hub         dono do caso: o vínculo com o card do CRM (`origem`/`origem_id`,
              com índice único), os PDFs anexados e o histórico. Fica na VM.
  calculadora sem banco, por desenho — é o que permite rodar sem PII em disco.
              Só passa os documentos adiante.
  CRM         onde o resultado aparece para o comercial (ver `bitrix.py`).

Ligado por `HUB_URL`; sem ela o app funciona igual, só não guarda nada.
"""
from __future__ import annotations

import json
import os
from dataclasses import asdict
from datetime import date
from decimal import Decimal

import httpx

ORIGEM = "bitrix"          # rótulo do sistema externo no vínculo do hub
TIMEOUT = 180.0            # upload de PDF grande na rede da VM

# peça da pré-análise → tipo de documento do hub (`TIPOS_VALIDOS` da API)
TIPO_DOC = {"conta": "calculo", "oficio": "oficio", "sentenca": "sentenca"}


def habilitado() -> bool:
    return bool(os.environ.get("HUB_URL"))


def _base() -> str:
    url = (os.environ.get("HUB_URL") or "").rstrip("/")
    if not url:
        raise RuntimeError("HUB_URL não configurada neste ambiente.")
    return url


def _auth():
    usuario, senha = os.environ.get("HUB_USER"), os.environ.get("HUB_PASS")
    return (usuario, senha) if usuario and senha else None


def _req(metodo: str, rota: str, **kw):
    r = httpx.request(metodo, f"{_base()}{rota}", auth=_auth(), timeout=TIMEOUT, **kw)
    if r.status_code >= 400:
        raise RuntimeError(f"hub {metodo} {rota}: {r.status_code} {r.text[:180]}")
    return r.json()


def caso_do_card(deal_id) -> dict | None:
    """O caso já aberto para este card, se houver."""
    achados = _req("GET", "/cases", params={"origem": ORIGEM, "origem_id": str(deal_id)})
    return achados[0] if achados else None


def abrir_caso(deal_id, nome: str, url_do_card: str | None = None) -> dict:
    """Abre (ou reencontra) o caso do card.

    A API é idempotente pelo par origem+origem_id: chamar de novo para o mesmo
    card devolve o caso existente, nunca um segundo. Sem isso, cada vez que o
    advogado reabrisse o card nasceria um caso novo e os documentos ficariam
    espalhados entre eles.
    """
    return _req("POST", "/cases", data={
        "nome": nome, "origem": ORIGEM, "origem_id": str(deal_id),
        "origem_url": url_do_card or ""})


# tipo do hub → peça da pré-análise (inverso de TIPO_DOC)
PECA_DE_TIPO = {v: k for k, v in TIPO_DOC.items()}


def documentos_do_caso(case_id: str) -> list[dict]:
    """As peças da pré-análise já guardadas, em ordem de uso.

    Ignora `processo_completo`, `peticao` e os slices (documento que veio de um
    master): esta tela trabalha com peças recortadas avulsas.
    """
    caso = _req("GET", f"/cases/{case_id}")
    out = []
    for d in caso.get("documentos") or []:
        peca = PECA_DE_TIPO.get(d.get("tipo"))
        if peca and not d.get("master_document_id") and not d.get("descartado_em"):
            out.append({"id": d["id"], "peca": peca,
                        "nome": d.get("nome_arquivo") or f"{peca}.pdf",
                        "paginas": d.get("paginas")})
    ordem = {"conta": 0, "oficio": 1, "sentenca": 2}
    return sorted(out, key=lambda d: ordem.get(d["peca"], 9))


def baixar_documento(case_id: str, document_id: str) -> bytes:
    """O PDF de volta, para a tela retomar de onde parou."""
    r = httpx.get(f"{_base()}/cases/{case_id}/documents/{document_id}/raw",
                  auth=_auth(), timeout=TIMEOUT)
    if r.status_code >= 400:
        raise RuntimeError(f"hub baixar {document_id}: {r.status_code}")
    return r.content


# Campos cuja divergência entre proposta e confirmação SIGNIFICA alguma coisa.
# É deliberadamente a MESMA lista que a calculadora usa para semear os widgets
# (`Calculadora.py`, bloco `_prefilled`): o que a máquina preenche é exatamente
# o que ela pode errar. Manter as duas listas iguais é o que torna o ledger
# simétrico por construção — se um campo passar a ser semeado, ele entra aqui.
CAMPOS_LEDGER: list[tuple[str, str]] = [
    ("vt", "vt"), ("vp", "vp"), ("vj", "vj"), ("vs", "vs"),
    ("pss", "valor_pss"), ("ir", "valor_ir"),
    ("hc", "hc"), ("hs", "hs"),
    ("bx_num_oficio", "numero_oficio"),
    ("bx_num_precatorio", "numero_precatorio"),
]


def registrar_adjudicacao(case_id: str, proposto: dict, confirmado: dict,
                          faixas: list[dict] | None = None,
                          revisor: str | None = None,
                          observacao: str | None = None) -> dict:
    """Grava o par (o que a máquina propôs, o que o advogado enviou).

    Este é o único dado do fluxo que COMPÕE com o uso: cada envio revisado vira
    um ponto de gabarito, e é o corpus de gabarito — não um modelo melhor — que
    destrava a faixa verde. Sem isto o par se perde no handoff: a proposta vive
    na query string, a correção vive nesta tela, e a calculadora não tem banco.

    `revisor` vem de `auth.usuario_atual()` — o login individual (`APP_USERS`).
    None é resposta legítima (ambiente sem login individual, ou entrada pela
    senha compartilhada da migração): o par continua valendo como gabarito, só
    não diz de quem é a correção.

    ⚠ Os outros dois pontos de escrita daqui (`abrir_caso`, `guardar_documento`)
    ficam sem autoria porque a API do hub não tem onde recebê-la — POST /cases e
    POST /documents não têm campo de autor. Fechar isso é mudança no hub, não
    aqui.

    ⚠ NUNCA levanta. Quando este POST falha o advogado já mandou o valor para o
    card; derrubar a tela por causa da contabilidade seria trocar o trabalho
    dele por um registro. O chamador só loga.

    `observacao` leva os valores que o prefill RECUSOU (não existiam na conta —
    ver `prefill/rejeitados.py`). O `AdjudicacaoIn` do hub já aceita o campo;
    não vai como chave em `proposto` porque o diff do hub compara pela união das
    chaves e contaria a rejeição como correção.
    """
    return _req("POST", f"/cases/{case_id}/adjudicacoes", json={
        "proposto": proposto, "confirmado": confirmado,
        "faixas": faixas or [], "origem": "pre_analise", "revisor": revisor,
        "observacao": observacao})


# ── Fase 2: snapshot de cálculo + journal do valor ─────────────────────────
# O snapshot congela (entrada completa, resultado completo) no hub; o journal
# registra cada escrita no valor do card, journal-PRIMEIRO (a entrada nasce
# `pendente` ANTES de o card ser tocado, e é concluída depois). No ENVIO os
# dois são best-effort — a calculadora funciona sem hub; na SOBRESCRITA e na
# REVERSÃO o journal é bloqueante: sem trilha, não se escreve.


class DivergenciaCard(RuntimeError):
    """409 do journal na reversão: o card mudou DEPOIS da entrada revertida.

    Não é erro de forma, é estado do mundo — quem decide é o advogado.
    `detail` traz `card_agora`/`esperado`; reenviar com
    `confirmar_divergencia=True` é o aceite explícito de reverter por cima.
    """

    def __init__(self, detail: dict):
        super().__init__(str(detail))
        self.detail = detail or {}


def _jsonavel(x):
    if isinstance(x, Decimal):
        return str(x)
    if isinstance(x, date):
        return x.isoformat()
    if isinstance(x, dict):
        return {k: _jsonavel(v) for k, v in x.items()}
    if isinstance(x, (list, tuple)):
        return [_jsonavel(v) for v in x]
    return x


def serializar_entrada(entrada, tela: dict | None = None) -> dict:
    """A EntradaCalculadora REAL em JSON — nunca um espelho dela.

    Serializar o dataclass diretamente é o que impede a deriva que já
    aconteceu no espelho `CalculadoraRequest` do hub (ficou sem
    superpreferência): campo novo no motor entra aqui de graça.

    None é omitido (todos os defaults são None/0/False — ausência é default).
    `tela` vira a sub-chave `_tela`: metadados que NÃO são do motor
    (referência, observação, ente, ano orçamentário) mas sem os quais o
    "reabrir para editar" perde o contexto do memorial. O underscore marca
    que não é campo do dataclass — o hub guarda sem julgar.
    """
    d = {k: _jsonavel(v) for k, v in asdict(entrada).items() if v is not None}
    limpa = {k: v for k, v in (tela or {}).items() if v}
    if limpa:
        d["_tela"] = limpa
    return d


def gravar_snapshot(case_id: str, payload: dict,
                    memorial_pdf: bytes | None = None) -> dict:
    """POST multipart: o par (entrada, resultado) + o memorial do MESMO momento."""
    files = ({"memorial": ("memorial.pdf", memorial_pdf, "application/pdf")}
             if memorial_pdf else None)
    return _req("POST", f"/cases/{case_id}/snapshots",
                data={"payload": json.dumps(payload)}, files=files)


def snapshot(snapshot_id: str) -> dict:
    return _req("GET", f"/snapshots/{snapshot_id}")


def snapshots_do_caso(case_id: str) -> list[dict]:
    return _req("GET", f"/cases/{case_id}/snapshots")


def memorial_do_snapshot(snapshot_id: str) -> bytes:
    r = httpx.get(f"{_base()}/snapshots/{snapshot_id}/memorial",
                  auth=_auth(), timeout=TIMEOUT)
    if r.status_code >= 400:
        raise RuntimeError(f"hub memorial {snapshot_id}: {r.status_code}")
    return r.content


def journal_registrar(case_id: str, **campos) -> dict:
    """Entrada nova no journal (nasce `pendente`). LEVANTA em erro — o
    chamador decide a fatalidade (envio: segue; sobrescrita/reversão:
    bloqueia). O 409 de divergência vira `DivergenciaCard`, com o detalhe."""
    r = httpx.request("POST", f"{_base()}/cases/{case_id}/journal",
                      auth=_auth(), timeout=TIMEOUT, json=campos)
    if r.status_code == 409:
        try:
            detalhe = (r.json() or {}).get("detail")
        except ValueError:
            detalhe = None
        if isinstance(detalhe, dict) and "divergencia" in detalhe:
            raise DivergenciaCard(detalhe)
    if r.status_code >= 400:
        raise RuntimeError(f"hub POST journal: {r.status_code} {r.text[:180]}")
    return r.json()


def journal_concluir(entry_id: str, status: str, erro: str | None = None) -> dict:
    """Conclui a entrada: `aplicado` | `falhou`. É a segunda metade do
    journal-primeiro — se esta chamada se perder, a entrada fica `pendente`
    e aparece em GET /journal/pendencias (falha ruidosa, por desenho)."""
    return _req("PATCH", f"/journal/{entry_id}",
                json={"status": status, "erro": erro})


def journal_do_caso(case_id: str) -> list[dict]:
    return _req("GET", f"/cases/{case_id}/journal")


def guardar_documento(case_id: str, peca: str, nome_arquivo: str, conteudo: bytes) -> dict:
    """Guarda um PDF no caso. `peca` ∈ {conta, oficio, sentenca}.

    ⚠ O hub aceita UM documento avulso por tipo (`substituir=true` troca o
    anterior). Várias sentenças no mesmo caso, portanto, não cabem aqui — quem
    guarda o conjunto é o card do CRM, cujos campos de anexo são múltiplos.
    """
    tipo = TIPO_DOC.get(peca)
    if not tipo:
        raise ValueError(f"peça desconhecida: {peca}")
    return _req("POST", f"/cases/{case_id}/documents",
                data={"tipo": tipo, "substituir": "true"},
                files={"file": (nome_arquivo, conteudo, "application/pdf")})
