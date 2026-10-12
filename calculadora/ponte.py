"""Ponte entre as duas aplicações: pré-análise → calculadora.

São processos separados, então a passagem de valores é uma URL — nada de
`switch_page` (que só existe dentro do mesmo app) nem de `session_state` (que
não atravessa processo). A calculadora já sabe ler esses params.

`CALCULADORA_URL` aponta para onde ela está publicada. Sem a env var, cai em
"/" — que é como o Caddy publica a calculadora no mesmo host.
"""
from __future__ import annotations

import os
from urllib.parse import urlencode


def url_calculadora(params: dict) -> str:
    # `rstrip("/")` numa base "/" devolve string vazia — daí o fallback, senão a
    # URL sai como "//?vt=…", que o navegador lê como OUTRO HOST.
    base = (os.environ.get("CALCULADORA_URL") or "").rstrip("/") or ""
    limpos = {k: str(v) for k, v in (params or {}).items() if v not in (None, "")}
    if not limpos:
        return base or "/"
    return f"{base}/?{urlencode(limpos)}"
