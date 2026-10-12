# -*- coding: utf-8 -*-
"""API do Alfred — FASE 3. Busca de precatorio -> parecer com as metricas calculadas.

  set ALFRED_TOKENS=tokenleitor:leitor,tokenchefe:completo
  python -m uvicorn scripts.api:app --host 127.0.0.1 --port 8000

  curl -H "Authorization: Bearer <token>" \
       http://127.0.0.1:8000/precatorio/0003762-88.2024.8.08.0000

Toda a logica vem de alfred_core.py, que por sua vez usa modelo_p23.py. Esta camada
so faz HTTP, autenticacao e mascaramento — nao calcula nada.

DECISOES DE PRIVACIDADE (o minimo acordado; HMAC/cifra ficam p/ depois)
  1. AUTENTICACAO em tudo, menos /saude. Bearer token, comparado em tempo constante
     (compare_digest) para nao vazar o token por timing. Tokens vem da variavel de
     ambiente ALFRED_TOKENS, nunca do repositorio.
  2. MASCARA POR PADRAO: CPF sai '000.***.***-00'. So o papel 'completo' ve inteiro,
     e apenas em /precatorio/{n}?completo=1.
  3. CPF NUNCA EM URL: a busca por CPF e' POST /busca (corpo), porque o log de acesso
     do uvicorn registra metodo+caminho — se o CPF fosse query string, iria para o log.
     Numero de processo, que e' dado publico, pode ir no caminho.
  4. LOG SEM DADO PESSOAL: o middleware abaixo registra so metodo, rota, status e
     duracao. Corpo de requisicao e resposta nao sao logados.
  5. O banco (data/alfred.db) fica FORA de qualquer diretorio servido — esta API nao
     monta arquivos estaticos de proposito.
"""
import hmac
import importlib.util
import logging
import os
import pathlib
import re
import sys
import threading
import time

from urllib.parse import quote

from fastapi import Depends, FastAPI, HTTPException, Query
from fastapi.responses import HTMLResponse, JSONResponse, Response
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, Field

# BASE resolvido a partir do proprio arquivo: funciona no Windows e na VM Linux.
# ALFRED_BASE sobrepoe quando o codigo roda de outro lugar.
BASE = os.environ.get("ALFRED_BASE") or str(pathlib.Path(__file__).resolve().parents[1])
_spec = importlib.util.spec_from_file_location("alfred_core", os.path.join(BASE, "scripts", "alfred_core.py"))
core = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(core)
_spec_ras = importlib.util.spec_from_file_location("rastreia", os.path.join(BASE, "scripts", "rastreia.py"))
RAS = importlib.util.module_from_spec(_spec_ras)
_spec_ras.loader.exec_module(RAS)

_spec_pdf = importlib.util.spec_from_file_location("parecer_pdf", os.path.join(BASE, "scripts", "parecer_pdf.py"))
parecer_pdf = importlib.util.module_from_spec(_spec_pdf)
_spec_pdf.loader.exec_module(parecer_pdf)

log = logging.getLogger("alfred")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

app = FastAPI(title="Precatur — precatorios", version="1.0",
              description="Busca de precatorios e projecao de pagamento (art. 100 §20/§23).")


# ------------------------------------------------------------------ auth
def _tokens():
    """ALFRED_TOKENS='tok:papel[:rotulo],...' -> {tok: (papel, rotulo)}.

    O ROTULO identifica a PESSOA no log de acesso (trilha de auditoria da LGPD, agora
    que a base tem nome+CPF). Token POR PESSOA em vez de senha compartilhada: da p/
    revogar um so e atribuir cada consulta. Sem rotulo, cai p/ um prefixo do token
    (nunca o token inteiro, que e' segredo)."""
    bruto = os.environ.get("ALFRED_TOKENS", "").strip()
    out = {}
    for par in bruto.split(","):
        p = par.split(":")
        if len(p) >= 2 and p[0].strip():
            tok = p[0].strip()
            papel = p[1].strip() or "leitor"
            rotulo = p[2].strip() if len(p) >= 3 and p[2].strip() else "tok:" + tok[:4]
            out[tok] = (papel, rotulo)
    return out


def _ident(token):
    """(papel, rotulo) do token em tempo constante; (None, None) se invalido."""
    for t, (pp, rot) in _tokens().items():         # compare_digest: nao vaza por timing
        if hmac.compare_digest(token or "", t):
            return pp, rot
    return None, None


# HTTPBearer (e nao Header cru) para que o /docs mostre o botao "Authorize" e o
# navegador vire um cliente utilizavel sem curl.
seguranca = HTTPBearer(auto_error=False, description="token do ALFRED_TOKENS")


def papel(cred: HTTPAuthorizationCredentials = Depends(seguranca)):
    """Bearer token -> papel. 401 se ausente/invalido."""
    if not _tokens():
        raise HTTPException(500, "ALFRED_TOKENS nao configurado no ambiente")
    if cred is None or not cred.credentials:
        raise HTTPException(401, "informe: Authorization: Bearer <token>")
    pp, _ = _ident(cred.credentials)
    if pp is None:
        raise HTTPException(401, "token invalido")
    return pp


# Rate limit por token: uma senha vazada NAO exporta a base inteira de PII varrendo
# /busca. Janela deslizante de 60s em memoria (uvicorn 1 worker). Humano faz ~10-20/min;
# 90 e' folgado p/ uso normal e trava scraping. Nao vale p/ a UI (/) nem /saude.
LIMITE_POR_MIN = 90
_janela = {}


@app.middleware("http")
async def log_e_limite(request, call_next):
    """Log ATRIBUIVEL (quem consultou) + rate limit. Nunca loga corpo, query ou o CPF/termo."""
    rotulo, tok = "anon", ""
    auth = request.headers.get("authorization", "")
    if auth[:7].lower() == "bearer ":
        tok = auth[7:].strip()
        _, r = _ident(tok)
        rotulo = r or "?"
    if tok and request.url.path not in ("/", "/saude"):
        agora = time.monotonic()
        dq = _janela.setdefault(tok, [])
        while dq and agora - dq[0] > 60:
            dq.pop(0)
        if len(dq) >= LIMITE_POR_MIN:
            log.warning("RATE-LIMIT %s %s user=%s", request.method, request.url.path, rotulo)
            return JSONResponse({"detail": "muitas consultas — aguarde um minuto"}, status_code=429)
        dq.append(agora)
    t0 = time.perf_counter()
    resp = await call_next(request)
    ms = (time.perf_counter() - t0) * 1000
    log.info("%s %s -> %s (%.0f ms) user=%s", request.method, request.url.path, resp.status_code, ms, rotulo)
    return resp


# ------------------------------------------------------------------ modelos
class Busca(BaseModel):
    termo: str = Field(..., min_length=3,
                       description="nº de precatorio, nº de origem, CPF/CNPJ ou nome do credor")
    limite: int = Field(50, ge=1, le=100, description="resultados por pagina")
    pagina: int = Field(1, ge=1, description="pagina (1-based)")
    ordem: str = Field("valor", pattern="^(valor|nome)$", description="ordenacao: valor | nome")


# ------------------------------------------------------------------ rotas
@app.get("/", include_in_schema=False)
def ui():
    """Interface web (arquivo unico, sem CDN). Nao ha diretorio estatico montado:
    o HTML e' lido e devolvido, e o banco continua fora de qualquer caminho servido."""
    p = os.path.join(BASE, "scripts", "ui.html")
    if not os.path.exists(p):
        raise HTTPException(404, "ui.html nao encontrado")
    return HTMLResponse(open(p, encoding="utf-8").read())


@app.get("/eu", tags=["servico"])
def eu(p: str = Depends(papel)):
    """Quem sou eu. A tela de login usa esta rota para validar a senha digitada."""
    return {"papel": p, "cpf_completo": p == "completo"}


@app.get("/saude", tags=["servico"])
def saude():
    """Unica rota sem autenticacao. Nao expoe dado algum."""
    try:
        cx = core.conecta()
        n = cx.execute("SELECT COUNT(*) FROM precatorio").fetchone()[0]
        cx.close()
        return {"ok": True, "precatorios": n}
    except Exception as e:                                        # noqa: BLE001
        return JSONResponse({"ok": False, "erro": type(e).__name__}, status_code=503)


@app.post("/busca", tags=["consulta"])
def rota_busca(q: Busca, p: str = Depends(papel)):
    """Busca por termo. E' POST de proposito: CPF em corpo, nunca em URL (ver item 3)."""
    cx = core.conecta()
    try:
        # pagina + total REAL (sem LIMIT, p/ paginacao) numa passada so'
        rs, criterio, total = core.busca_pagina(cx, q.termo, q.limite, (q.pagina - 1) * q.limite, q.ordem)
        itens = [{
            "id": r["id"],
            "numero": r["numero_fmt"], "tribunal": r["tribunal"], "ordem": r["ordem"],
            "credor": core.mascara_cpf_no_texto(r["credor"]), "cpf_cnpj": core.mascara_cpf(r["cpf_cnpj"]),
            "municipio": r["municipio"], "uf": r["uf"], "valor": r["valor"],
        } for r in rs]
        out = {"criterio": criterio, "total": len(itens), "itens": itens,
               "total_encontrado": total, "pagina": q.pagina, "limite": q.limite,
               "paginas": max(1, (total + q.limite - 1) // q.limite)}
        if not itens and q.pagina == 1:
            out["explicacao"] = core.explica_vazio(cx, q.termo)
            # "nao encontrado" esconde tres situacoes muito diferentes (credito ainda
            # em conhecimento / requisitado mas nao autuado / precatorio fora da base).
            # O DataJud separa as tres. So' para numero CNJ, e sem derrubar a busca se
            # a API do CNJ estiver fora — o rastreio e' um extra, nao um requisito.
            if len(re.sub(r"\D", "", q.termo or "")) == 20:
                try:
                    out["rastreio"] = RAS.rastrear(q.termo)
                except Exception as e:                                   # noqa: BLE001
                    log.warning("rastreio falhou: %s", type(e).__name__)
        return out
    finally:
        cx.close()


@app.get("/precatorio/{numero}", tags=["consulta"])
def rota_precatorio(numero: str, p: str = Depends(papel),
                    completo: bool = Query(False, description="CPF sem mascara (papel 'completo')")):
    """Parecer de um precatorio pelo nº dele OU do processo de origem."""
    if completo and p != "completo":
        raise HTTPException(403, "seu papel nao autoriza CPF sem mascara")
    d = re.sub(r"\D", "", numero)
    if len(d) < 15:
        raise HTTPException(400, "informe um numero de processo (>= 15 digitos)")
    cx = core.conecta()
    try:
        rs, _ = core.busca(cx, numero)
        if not rs:
            raise HTTPException(404, core.explica_vazio(cx, numero) or "precatório não encontrado")
        return {"total": len(rs),
                "pareceres": [core.parecer(cx, r, completo=completo) for r in rs]}
    finally:
        cx.close()


@app.get("/parecer_id/{pid}", tags=["consulta"])
def rota_parecer_id(pid: int, p: str = Depends(papel),
                    completo: bool = Query(False, description="CPF sem mascara (papel 'completo')")):
    """Parecer de UM precatorio pelo id interno (o que /busca devolve em `id`).
    Inequivoco -- resolve o caso do TJMG, cujo `numero` e' sequencia curta (<15
    digitos) e nao serve para /precatorio/{numero}."""
    if completo and p != "completo":
        raise HTTPException(403, "seu papel nao autoriza CPF sem mascara")
    cx = core.conecta()
    try:
        r = cx.execute("SELECT * FROM precatorio_atual WHERE id=?", (pid,)).fetchone()
        if not r:
            raise HTTPException(404, "precatório não encontrado")
        return {"total": 1, "pareceres": [core.parecer(cx, r, completo=completo)]}
    finally:
        cx.close()


@app.get("/parecer_id/{pid}/pdf", tags=["consulta"])
def rota_parecer_pdf(pid: int, p: str = Depends(papel),
                     completo: bool = Query(False, description="CPF sem mascara (papel 'completo')")):
    """PDF do parecer, gerado NO SERVIDOR (scripts/parecer_pdf.py, reportlab).

    Por que server-side e nao window.print(): rodape com disclaimer + numeracao em
    TODA pagina, nome de arquivo garantido, nenhum cabecalho/URL do navegador no
    documento, e a mascara de CPF decidida aqui pelo papel — o documento que circula
    e' controlado pela API, nao pelo browser de quem imprimiu."""
    if completo and p != "completo":
        raise HTTPException(403, "seu papel nao autoriza CPF sem mascara")
    cx = core.conecta()
    try:
        r = cx.execute("SELECT * FROM precatorio_atual WHERE id=?", (pid,)).fetchone()
        if not r:
            raise HTTPException(404, "precatório não encontrado")
        par = core.parecer(cx, r, completo=completo)
    finally:
        cx.close()
    pdf = parecer_pdf.gerar(par)
    # o parecer ja' vem com o credor mascarado; reaplica no nome do ARQUIVO por garantia
    nome = " - ".join(x for x in [core.mascara_cpf_no_texto(par["credor"].get("nome")) or "",
                                  par["precatorio"].get("numero_eproc_fmt")
                                  or par["precatorio"].get("numero") or ""] if x)
    nome = re.sub(r'[\\/:*?"<>|]+', " ", nome).strip()[:120] or f"parecer_{pid}"
    return Response(content=pdf, media_type="application/pdf", headers={
        "Content-Disposition": "attachment; filename=\"parecer.pdf\"; "
                               "filename*=UTF-8''" + quote(nome + ".pdf")})


_ENTES_CACHE = None            # o GROUP BY sobre ~900k linhas so muda no rebuild (=restart)
_ENTES_LOCK = threading.Lock()


def _build_entes():
    """Monta (e cacheia) a lista de entes: GROUP BY sobre a precatorio_atual inteira
    (~900k linhas), ~0,2 s local desde que coleta_atual virou tabela (como view com
    subquery correlacionada levava 147 s local e 416 s na VM -- auditoria A3). So' muda
    no rebuild, por isso fica cacheado ate o proximo restart e e' pre-aquecido no
    startup. O lock evita dois builds simultaneos (startup + 1o usuario)."""
    global _ENTES_CACHE
    with _ENTES_LOCK:
        if _ENTES_CACHE is not None:
            return _ENTES_CACHE
        cx = core.conecta()
        try:
            rows = cx.execute(
                "SELECT ente_id, ente_nome, tribunal, municipio, uf, COUNT(*) n "
                "FROM precatorio_atual GROUP BY ente_id "
                "ORDER BY uf IS NULL, uf, municipio, ente_nome").fetchall()
            _ENTES_CACHE = {"total": len(rows), "entes": [
                {"id": r["ente_id"], "ente": r["ente_nome"], "tribunal": r["tribunal"],
                 "municipio": r["municipio"], "uf": r["uf"], "n": r["n"]} for r in rows]}
        finally:
            cx.close()
    return _ENTES_CACHE


_DEV_CACHE = None             # lista da busca por ente devedor; tambem so' muda no rebuild


def _build_devedores():
    """Devedores para a aba 'Ente devedor' (ver alfred_core.devedores), cacheados."""
    global _DEV_CACHE
    with _ENTES_LOCK:
        if _DEV_CACHE is not None:
            return _DEV_CACHE
        cx = core.conecta()
        try:
            _DEV_CACHE = core.devedores(cx)
        finally:
            cx.close()
    return _DEV_CACHE


@app.on_event("startup")
def _prewarm_entes():
    """Aquece o cache dos entes em background: o 1o acesso nao paga o GROUP BY."""
    threading.Thread(target=lambda: (_build_entes(), _build_devedores()), daemon=True).start()


@app.get("/devedores", tags=["consulta"])
def rota_devedores(q: str = Query(..., min_length=2, max_length=80), p: str = Depends(papel)):
    """Busca da aba 'Ente devedor': municipio/Estado (todos os orgaos juntos) ou orgao sem
    municipio. So' metadado agregado, nenhum dado de credor."""
    return {"q": q, "itens": core.busca_devedor(_build_devedores(), q)}


@app.get("/ente/{chave}", tags=["consulta"])
def rota_ente(chave: str, p: str = Depends(papel)):
    """Pagina 'Saude do ente': chave = codigo IBGE (municipio, ou 2 digitos do Estado) ou
    'e<id>' para orgao sem municipio. Ver alfred_core.saude_ente."""
    if not re.fullmatch(r"e?\d{1,9}", chave):
        raise HTTPException(400, "chave invalida: use o codigo IBGE ou e<id do ente>")
    cx = core.conecta()
    try:
        s = core.saude_ente(cx, chave)
    finally:
        cx.close()
    if not s:
        raise HTTPException(404, "ente sem fila no Alfred")
    return s


@app.get("/entes", tags=["consulta"])
def rota_entes(p: str = Depends(papel)):
    """Cobertura: entes disponiveis com contagem de precatorios (alimenta o dropdown
    da UI). So metadado de cobertura — nenhum dado pessoal. Cacheado em memoria."""
    return _ENTES_CACHE if _ENTES_CACHE is not None else _build_entes()


@app.get("/entes/{ente_id}/fila", tags=["consulta"])
def rota_ente_fila(ente_id: int, p: str = Depends(papel),
                   limite: int = Query(200, ge=1, le=10000),
                   offset: int = Query(0, ge=0)):
    """Precatorios de um ente na ordem da fila — p/ navegar a cobertura pelo dropdown."""
    cx = core.conecta()
    try:
        # acumulado = soma corrida do valor na ordem da fila, calculada sobre o ente
        # inteiro (janela) e so' depois fatiada -> "carregar mais" continua de onde parou
        rows = cx.execute(
            "SELECT * FROM (SELECT *, SUM(valor) OVER (ORDER BY ordem IS NULL, ordem, id "
            "ROWS UNBOUNDED PRECEDING) AS acumulado FROM precatorio_atual WHERE ente_id=?) "
            "ORDER BY ordem IS NULL, ordem, id LIMIT ? OFFSET ?",
            (ente_id, limite, offset)).fetchall()
        total = cx.execute("SELECT COUNT(*) FROM precatorio_atual WHERE ente_id=?",
                           (ente_id,)).fetchone()[0]
        itens = [{
            "id": r["id"], "numero": r["numero_fmt"], "tribunal": r["tribunal"],
            "ordem": r["ordem"], "credor": core.mascara_cpf_no_texto(r["credor"]),
            "cpf_cnpj": core.mascara_cpf(r["cpf_cnpj"]),
            "municipio": r["municipio"], "uf": r["uf"], "valor": r["valor"],
            "acumulado": r["acumulado"],
        } for r in rows]
        return {"ente": rows[0]["ente_nome"] if rows else None,
                "tribunal": rows[0]["tribunal"] if rows else None,
                "total": total, "offset": offset, "itens": itens}
    finally:
        cx.close()


@app.get("/municipio/{ibge}", tags=["consulta"])
def rota_municipio(ibge: str, p: str = Depends(papel)):
    """Panorama do devedor: estoque e mora (fila) + comportamento de pagamento (Mapa CNJ).

    `filas` e `pagamento` vem de fontes diferentes e sao devolvidos separados de
    proposito — ver o cabecalho de scripts/db_mapa.py.
    """
    cx = core.conecta()
    try:
        m = cx.execute("SELECT * FROM municipio WHERE ibge = ?", (ibge,)).fetchone()
        if not m:
            raise HTTPException(404, "municipio nao encontrado")
        ag = cx.execute(
            "SELECT p.tribunal, COUNT(*) n, COALESCE(SUM(p.valor),0) v "
            "FROM precatorio_atual p JOIN ente e ON e.id = p.ente_id "
            "WHERE e.ibge = ? GROUP BY p.tribunal", (ibge,)).fetchall()
        pag = core.MAPA.resumo_municipio(cx, ibge)
        # plano do §23 + conformidade: "quanto deve pagar ESTE ano e esta em dia?".
        # Complementa `pagamento` (Mapa CNJ), que so olha o ano-ref anterior.
        pl = core.NACP.plano(cx, ibge) if core.NACP.existe(cx) else None
        cf = core.NACP.conformidade(cx, ibge) if core.NACP.existe(cx) else None
        return {"ibge": m["ibge"], "municipio": m["nome"], "uf": m["uf"],
                "regime": m["regime"], "rcl": m["rcl"], "ano_rcl": m["ano_rcl"],
                "plano_exercicio": None if not (pl or cf) else {
                    "fonte": "Comitê Gestor de Contas Especiais (art. 100 §23)",
                    "ano": pl["ano"] if pl else None,
                    "mora_oficial_1jan": pl["mora_1jan"] if pl else None,
                    "pct_aplicado": pl["pct_aplicado"] if pl else None,
                    "valor_do_plano_no_ano": pl["valor_anual"] if pl else None,
                    "rateio_por_justica": ({"TJ": pl["rateio_tj"], "TRT": pl["rateio_trt"],
                                            "TRF": pl["rateio_trf"]} if pl else None),
                    "pa_fiscalizacao": (pl["fonte_pa"] if pl else None) or (cf["pa"] if cf else None),
                    "conformidade": None if not cf else {
                        "situacao": cf["codigo"], "resumo": cf["texto"], "em": cf["em"],
                        "bloqueios_sisbajud_na_janela": cf["n_bloqueios_12m"]}},
                "filas": [{"tribunal": x["tribunal"], "n": x["n"], "estoque": round(x["v"], 2)}
                          for x in ag],
                "pagamento": None if not pag else {
                    "fonte": f"CNJ Mapa Anual ref. {pag['ano_ref']}", "ano_ref": pag["ano_ref"],
                    "situacao": pag["codigo"], "resumo": pag["texto"],
                    "estoque_abertura": pag["anterior"], "pago_no_ano": pag["pago"],
                    "saldo_fim_ano": pag["saldo"], "expedidos_no_ano": pag["expedidos"],
                    "taxa_quitacao": pag["taxa_quitacao"],
                    "anos_para_quitar": pag["anos_para_quitar"],
                    "tribunais_em_dia": pag["tribunais_em_dia"],
                    "tribunais_inadimplentes": pag["tribunais_inadimplentes"],
                    "por_tribunal": pag["por_tribunal"]}}
    finally:
        cx.close()


if __name__ == "__main__":
    sys.exit("rode com: python -m uvicorn scripts.api:app --host 127.0.0.1 --port 8000")
