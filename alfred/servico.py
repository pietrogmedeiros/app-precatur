"""Alfred como serviço interno do App Precatur.

A API do Alfred (`scripts/api.py`) entra INTACTA — ela já resolve autenticação por
papel, máscara de CPF, limite por minuto e o log sem dado pessoal. Este módulo só
embrulha:

  1. **Atribuição da consulta.** O log do Alfred identifica *quem consultou* pelo
     rótulo do token — é a trilha de auditoria que a base com nome e CPF exige.
     Vindo pelo app, o token é um por PAPEL, então o rótulo sozinho diria apenas
     "completo" e se perderia a pessoa. O Express manda o usuário logado no
     cabeçalho `X-Alfred-Usuario` e aqui ele entra no log, ao lado do papel.

  2. **Segredo compartilhado.** O serviço escuta só em 127.0.0.1; isto é a segunda
     tranca, para que outro processo do contêiner não consulte a base.

  3. **Banco ausente vira resposta legível.** O banco mora num volume e não na
     imagem: subir o app antes de enviá-lo é um caminho real. Sem isto, cada
     consulta devolvia "Internal Server Error" seco, e a causa (um arquivo que
     falta num volume) não aparecia em lugar nenhum da tela.

Nada aqui lê o banco nem calcula: continua tudo em `alfred_core.py`.
"""
from __future__ import annotations

import logging
import os
import time

from scripts.api import app  # noqa: F401 — a aplicação do Alfred, sem alteração

log = logging.getLogger("alfred.app")

SEGREDO = os.environ.get("ALFRED_SEGREDO") or ""
# Rotas que não exigem o segredo: a saúde é lida pelo boot do contêiner.
ABERTAS = {"/saude"}


@app.exception_handler(FileNotFoundError)
async def banco_ausente(request, exc: FileNotFoundError):
    """`conecta()` levanta isto quando `data/alfred.db` não existe."""
    from fastapi.responses import JSONResponse

    log.error("banco ausente: %s", exc)
    return JSONResponse(
        {"detail": "A base de precatórios ainda não foi enviada para este "
                   "ambiente — o arquivo alfred.db não está no volume."},
        status_code=503)


@app.middleware("http")
async def identidade_e_tranca(request, call_next):
    """Atribui a consulta a quem a fez e barra chamada sem o segredo."""
    from fastapi.responses import JSONResponse

    caminho = request.url.path
    if SEGREDO and caminho not in ABERTAS:
        if request.headers.get("x-alfred-segredo") != SEGREDO:
            return JSONResponse({"detail": "segredo inválido"}, status_code=401)

    # A UI antiga (ui.html, servida em "/") não é exposta pelo app: a tela é a
    # do Next. Mantê-la acessível seria uma segunda porta para a mesma base,
    # com um login diferente do nosso.
    if caminho == "/":
        return JSONResponse({"detail": "não disponível"}, status_code=404)

    quem = request.headers.get("x-alfred-usuario") or "?"
    t0 = time.perf_counter()
    resposta = await call_next(request)
    if caminho not in ABERTAS:
        log.info("APP %s %s -> %s (%.0f ms) quem=%s",
                 request.method, caminho, resposta.status_code,
                 (time.perf_counter() - t0) * 1000, quem)
    return resposta
