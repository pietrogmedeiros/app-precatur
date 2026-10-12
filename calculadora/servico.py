"""Serviço HTTP do motor de cálculo — o Streamlit sem Streamlit.

O app Precatur (Next + Express) não fala Python. Em vez de reescrever 5 mil
linhas de cálculo jurídico em TypeScript — e com elas o risco de o número mudar —
o motor continua rodando como está e passa a atender por HTTP, dentro do mesmo
contêiner, só em 127.0.0.1. Quem abre a porta para o mundo é o Express, que já
tem o login e os papéis.

Fronteira: aqui NÃO há regra de negócio nova. Cada rota lê o formulário com
`formulario.ler` (paridade com a tela antiga), chama o motor e devolve o que ele
disse. O que é conta mora em `precaturia/`; o que é tela mora no Next.
"""
from __future__ import annotations

import logging
import os
from datetime import date
from decimal import Decimal
from typing import Any

from fastapi import Body, FastAPI, File, Form, Header, HTTPException, UploadFile
from fastapi.responses import JSONResponse, Response

import formulario
import memorial
import numeros
import rotas_crm
import rotas_documentos
import versao
from formulario import ErroDeFormulario
from precaturia.pipeline import calculadora
from precaturia.pipeline.indices import series as _series

log = logging.getLogger("calculadora")

app = FastAPI(title="Precatur — motor de cálculo", docs_url=None, redoc_url=None)
app.include_router(rotas_documentos.router)
app.include_router(rotas_crm.router)

# Segredo compartilhado com o Express. O serviço só escuta em 127.0.0.1, então
# isto é a segunda tranca: impede que outro processo do contêiner chame o motor.
SEGREDO = os.environ.get("MOTOR_SEGREDO") or ""


def _confere(segredo: str | None) -> None:
    if SEGREDO and segredo != SEGREDO:
        raise HTTPException(status_code=401, detail="segredo inválido")


# ─────────────────────────── saúde e metadados ───────────────────────────

@app.get("/saude")
def saude() -> dict:
    """Vivo? Quais índices o BACEN já publicou de verdade?"""
    reais = {i: _series.ultimo_mes_real(i) for i in ("SELIC", "IPCA", "IPCA-E", "INPC")}
    return {"ok": True, "indices_ultimo_mes_real": reais, "versao": _versao()}


def _versao() -> str | None:
    """De qual código este motor está rodando. Na imagem não há `.git`, então
    `versao` cai no `UPSTREAM.txt` gravado quando o motor foi copiado."""
    return versao.sha_do_deploy()


@app.get("/opcoes")
def opcoes() -> dict:
    """As listas que a tela precisa desenhar — fonte única, aqui."""
    return {
        "regimes": [{"valor": k, "rotulo": v} for k, v in formulario.REGIME_OPCOES.items()],
        "naturezas_historicas": list(formulario.NATUREZAS_HISTORICAS),
        "naturezas_tributarias": list(formulario.NATUREZAS_TRIBUTARIAS),
        "entes": formulario.ENTES,
        "pss_modos": formulario.PSS_MODOS,
        "ir_modos": formulario.IR_MODOS,
        "anos_orcamentarios": [str(a) for a in range(2020, 2041)],
    }


# ───────────────────────────────  cálculo  ───────────────────────────────

def _meses_projetados(res: dict) -> tuple[str, str] | None:
    """Data-alvo além do último mês REAL de algum índice → (mes_alvo, ultimo).

    Cópia da função homônima do `Calculadora.py`: é o que dispara o aviso de
    "projeção Focus, não índice publicado".
    """
    at = (res.get("cenario_homologado") or {}).get("atualizacao") or {}
    data_alvo = at.get("data_alvo")
    if not data_alvo:
        return None
    mes_alvo = str(data_alvo)[:7]
    reais = [r for r in (_series.ultimo_mes_real(i) for i in ("SELIC", "IPCA", "IPCA-E")) if r]
    if not reais:
        return None
    min_real = min(reais)
    return (mes_alvo, min_real) if mes_alvo > min_real else None


def _aviso_projecao(res: dict) -> str | None:
    proj = _meses_projetados(res)
    if not proj:
        return None
    return (f"Atualização usa projeção do Boletim Focus/BACEN para os meses após "
            f"{proj[1]} (até {proj[0]}) — estimativa de mercado, não índice publicado.")


def _rodar(bruto: dict) -> tuple[formulario.Formulario, dict]:
    form = formulario.ler(bruto)
    try:
        res = calculadora.calcular_dict(form.entrada)
    except Exception as exc:  # noqa: BLE001 — erro do motor vira 422 legível
        raise ErroDeFormulario([f"Erro no cálculo: {exc}"]) from exc
    return form, res


def _redes_de_protecao(form: formulario.Formulario, res: dict) -> list[str]:
    """As duas travas da tela antiga: declarado maior que o bruto, e líquido
    negativo. Ambas impedem memorial e envio ao card — valor digitado errado
    (centavos no lugar de reais) não pode virar proposta."""
    erros: list[str] = []
    cen = res.get("cenario_homologado") or {}
    total = cen.get("valor_total_atualizado")

    declarados = [(rot, v) for rot, modo, v in (
        ("PSS", form.pss_modo_label, form.entrada.valor_pss),
        ("IR", form.ir_modo_label, form.entrada.valor_ir),
    ) if modo == "Valor no ofício (R$)" and v is not None]
    if declarados and total is not None:
        soma = sum((v for _, v in declarados), Decimal("0"))
        if soma > Decimal(str(total)):
            det = " + ".join(f"{rot} {_brl(v)}" for rot, v in declarados)
            if len(declarados) > 1:
                det += f" = {_brl(soma)}"
            erros.append(
                f"O valor declarado ({det}) é maior que o total bruto atualizado "
                f"({_brl(total)}) — o líquido ficaria negativo. Confira o que foi "
                "digitado; o PSS/IR declarado entra sem correção monetária.")

    liquido = cen.get("valor_liquido_atualizado")
    if liquido is not None and Decimal(str(liquido)) < 0:
        erros.append(
            f"O líquido ficou negativo ({_brl(liquido)}): as deduções somam mais que "
            "o crédito atualizado. Confira PSS, IR e o percentual de honorários.")
    return erros


def _brl(v) -> str:
    if v is None:
        return "—"
    d = Decimal(str(v))
    neg = d < 0
    d = abs(d).quantize(Decimal("0.01"))
    intp, dec = f"{d:.2f}".split(".")
    intp = f"{int(intp):,}".replace(",", ".")
    return f"{'-' if neg else ''}R$ {intp},{dec}"


def _sucumbenciais(form: formulario.Formulario, res: dict) -> str | None:
    """Valor do sucumbencial — informativo: NÃO sai do líquido do credor.
    Base = bruto atualizado, a mesma dos contratuais (para serem comparáveis)."""
    pct = form.honorarios_sucumbenciais_pct
    if not pct:
        return None
    base = (res.get("cenario_homologado") or {}).get("valor_total_atualizado")
    if base is None:
        return None
    return str((Decimal(str(base)) * Decimal(str(pct)) / Decimal("100")).quantize(Decimal("0.01")))


@app.post("/calcular")
def calcular(bruto: dict = Body(...), x_motor_segredo: str | None = Header(None)) -> dict:
    """Formulário → cenários + atualização + cascata. É a rota da tela."""
    _confere(x_motor_segredo)
    try:
        form, res = _rodar(bruto)
    except ErroDeFormulario as exc:
        return JSONResponse(status_code=422, content={"erros": exc.erros})

    bloqueios = _redes_de_protecao(form, res)
    if bloqueios:
        return JSONResponse(status_code=422, content={"erros": bloqueios})

    try:
        cenarios_hc = calculadora.cenarios_honorarios_contratuais(form.entrada)
    except Exception:  # noqa: BLE001 — anexo opcional não derruba o cálculo
        cenarios_hc = None

    return {
        "resultado": res,
        "avisos": form.avisos,
        "aviso_projecao": _aviso_projecao(res),
        "cenarios_honorarios": cenarios_hc,
        "sucumbenciais_valor": _sucumbenciais(form, res),
        "sucumbenciais_pct": str(form.honorarios_sucumbenciais_pct) if form.honorarios_sucumbenciais_pct else None,
        "versao_motor": _versao(),
    }


@app.post("/memorial")
def gerar_memorial(bruto: dict = Body(...), x_motor_segredo: str | None = Header(None)):
    """O mesmo cálculo, embrulhado no PDF que o advogado entrega."""
    _confere(x_motor_segredo)
    try:
        form, res = _rodar(bruto)
    except ErroDeFormulario as exc:
        return JSONResponse(status_code=422, content={"erros": exc.erros})
    bloqueios = _redes_de_protecao(form, res)
    if bloqueios:
        return JSONResponse(status_code=422, content={"erros": bloqueios})

    cen = res.get("cenario_homologado") or {}
    alvo_efetivo = (cen.get("atualizacao") or {}).get("data_alvo")

    hon_con = form.entrada.honorarios_contratuais_pct
    hon_suc = form.honorarios_sucumbenciais_pct
    if hon_con and hon_suc:
        hon = f"contr. {hon_con}% · sucumb. {hon_suc}%"
    elif hon_con:
        hon = f"contratuais {hon_con}%"
    elif hon_suc:
        hon = f"sucumbenciais {hon_suc}%"
    else:
        hon = "—"

    if form.eh_conta:
        valores = [
            ("Principal corrigido", _brl(form.valor_principal)),
            ("Juros de mora", _brl(form.valor_juros) if form.valor_juros else "—"),
            ("SELIC acumulada", _brl(form.valor_selic) if form.valor_selic else "—"),
            ("Total da conta", _brl(form.valor_total)),
            ("Honorários", hon),
        ]
    else:
        valores = [
            ("Valor originário", _brl(form.valor_originario)),
            ("Regime", f"{form.natureza_hist} (motor histórico)" if form.natureza_hist else (form.preset_label or "—")),
            ("Honorários", hon),
        ]

    datas = []
    if form.entrada.data_base:
        datas.append(("Data-base", _data_br(form.entrada.data_base)))
    datas.append(("Data do cálculo", _data_br(form.entrada.data_calculo)))
    if form.entrada.data_apresentacao:
        datas.append(("Apresentação ao tribunal", _data_br(form.entrada.data_apresentacao)))
    datas.append(("Data-alvo", _data_br(alvo_efetivo or form.data_alvo)))

    outros = []
    if form.ente_devedor:
        outros.append(("Ente devedor", form.ente_devedor))
    if form.ano_orcamentario:
        outros.append(("Ano orçamentário", form.ano_orcamentario))
    if form.entrada.natureza_tributaria:
        outros.append(("Natureza", form.entrada.natureza_tributaria))
    if form.entrada.modalidade:
        outros.append(("Modalidade", form.entrada.modalidade))
    outros.append(("PSS", form.pss_modo_label + (
        f" ({form.aliquota_pss}%)" if form.pss_modo_label.startswith("Por") and form.aliquota_pss else "")))
    outros.append(("IR-RRA", form.ir_modo_label + (
        f" ({form.meses} meses)" if form.ir_modo_label.startswith("Estimar") and form.meses else "")))

    iniciais = {
        "principal": form.valor_principal if form.valor_principal else form.valor_total,
        "juros": form.valor_juros or Decimal("0"),
        "selic": form.valor_selic or Decimal("0"),
    }

    try:
        cenarios_hc = calculadora.cenarios_honorarios_contratuais(form.entrada)
    except Exception:  # noqa: BLE001
        cenarios_hc = None

    suc_valor = _sucumbenciais(form, res)
    try:
        pdf = memorial.gerar_memorial_pdf(
            valores, datas, outros, iniciais, res, gerado_em=date.today(),
            referencia=form.referencia or "",
            aviso_projecao=_aviso_projecao(res),
            observacao_advogado=form.observacao or None,
            sucumbenciais_pct=hon_suc,
            sucumbenciais_valor=Decimal(suc_valor) if suc_valor else None,
            cenarios_honorarios=cenarios_hc,
        )
    except Exception as exc:  # noqa: BLE001
        return JSONResponse(status_code=500, content={"erros": [f"Não foi possível gerar o PDF: {exc}"]})

    return Response(content=pdf, media_type="application/pdf", headers={
        "Content-Disposition": f'attachment; filename="{_nome_arquivo(form.referencia)}"'})


def _data_br(d) -> str:
    try:
        return date.fromisoformat(str(d)[:10]).strftime("%d/%m/%Y")
    except Exception:  # noqa: BLE001
        return str(d or "—")


def _nome_arquivo(ref: str) -> str:
    """Igual ao da tela antiga: referência saneada, ou o nome padrão."""
    import re
    import unicodedata
    base = (ref or "").strip()
    if not base:
        return "memorial_calculo.pdf"
    base = unicodedata.normalize("NFKD", base).encode("ascii", "ignore").decode("ascii")
    base = re.sub(r'[\\/:*?"<>|]+', " ", base)
    base = re.sub(r"\s+", " ", base).strip()[:100].rstrip(" .-")
    return f"{base or 'memorial_calculo'}.pdf"


@app.post("/numero")
def ler_numero(corpo: dict = Body(...), x_motor_segredo: str | None = Header(None)) -> dict:
    """Lê um número digitado com as MESMAS regras do formulário.

    A tela usa isto para mostrar o valor formatado enquanto se digita sem ter
    uma segunda implementação de "1.234,56" em TypeScript — duas regras de
    leitura de número acabam diferentes, e a diferença aparece em dinheiro.
    """
    _confere(x_motor_segredo)
    texto = corpo.get("texto")
    milhar = bool(corpo.get("milhar", True))
    try:
        valor = numeros.parse_decimal_br(texto, milhar=milhar)
    except ValueError as exc:
        return {"ok": False, "erro": str(exc)}
    return {"ok": True, "valor": str(valor) if valor is not None else None,
            "formatado": _brl(valor) if valor is not None and milhar else (
                f"{valor}".rstrip("0").rstrip(".") if valor is not None else None)}
