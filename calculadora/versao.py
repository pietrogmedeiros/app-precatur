"""De qual código este processo está rodando — o SHA do deploy.

O snapshot de cálculo (Fase 2) grava `motor_versao` junto com entrada e
resultado: reabrir um caso meses depois pode recalcular diferente, e a
diferença precisa ser explicável — "índice novo" e "motor novo" são causas
distintas, e sem o SHA as duas viram o mesmo mistério.

Sem subprocess de propósito: a VM tem git instalado, mas o processo não deve
depender de binário externo (nem de PATH) para se identificar. O deploy da VM
é `git reset --hard origin/main` num checkout com `.git` ao lado — basta ler
`HEAD` e resolver a ref na mão. No Render não há checkout garantido em
runtime, mas a plataforma expõe o commit em `RENDER_GIT_COMMIT`.

Dentro do app Precatur não existe `.git`: o motor foi vendorizado (a imagem
copia os arquivos, não o repositório). Para esse caso o clone deixa o SHA de
origem em `UPSTREAM.txt`, que é lido como último recurso — continua sendo o
commit de onde o código veio, só que registrado no ato da cópia.

Quando nenhum caminho responde (tarball sem `.git` e sem `UPSTREAM.txt`),
devolve None: versão desconhecida se escreve None, nunca se inventa — a mesma
regra da autoria (`docs/autoria_dos_registros.md`).
"""
from __future__ import annotations

import os
from pathlib import Path

# 12 caracteres identificam o commit com folga e cabem num registro que humano
# lê; o SHA inteiro só acrescenta ruído.
_CURTO = 12


def _sha_valido(s: str) -> bool:
    return len(s) == 40 and all(c in "0123456789abcdef" for c in s.lower())


def sha_do_deploy(raiz: Path | str | None = None) -> str | None:
    """SHA (curto) do commit em que este checkout está — ou None.

    `raiz` existe para os testes apontarem um `.git` fabricado; em produção o
    padrão é o diretório deste arquivo, que é a raiz do repositório.
    """
    render = (os.environ.get("RENDER_GIT_COMMIT") or "").strip()
    if _sha_valido(render):
        return render[:_CURTO]

    base = Path(raiz if raiz is not None else Path(__file__).resolve().parent)
    git = base / ".git"
    try:
        head = (git / "HEAD").read_text(encoding="utf-8").strip()
    except OSError:
        return _do_upstream(base)

    if _sha_valido(head):                       # HEAD solto (detached)
        return head[:_CURTO]
    if not head.startswith("ref: "):
        return _do_upstream(base)

    ref = head[len("ref: "):].strip()
    try:
        solto = (git / ref).read_text(encoding="utf-8").strip()
        if _sha_valido(solto):
            return solto[:_CURTO]
    except OSError:
        pass

    # `git gc`/`pack-refs` recolhe as refs soltas para packed-refs; o deploy
    # não roda gc, mas confiar nisso seria acoplar a versão ao housekeeping.
    try:
        packed = (git / "packed-refs").read_text(encoding="utf-8")
    except OSError:
        return _do_upstream(base)
    for linha in packed.splitlines():
        linha = linha.strip()
        if not linha or linha.startswith(("#", "^")):
            continue
        partes = linha.split(None, 1)
        if len(partes) == 2 and partes[1] == ref and _sha_valido(partes[0]):
            return partes[0][:_CURTO]
    return _do_upstream(base)


def _do_upstream(base: Path) -> str | None:
    """SHA gravado pelo clone, quando a cópia veio sem `.git`."""
    try:
        linha = (base / "UPSTREAM.txt").read_text(encoding="utf-8").splitlines()[0].strip()
    except (OSError, IndexError):
        return None
    return linha[:_CURTO] if _sha_valido(linha) else None
