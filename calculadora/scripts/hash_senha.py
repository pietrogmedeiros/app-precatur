"""Gera uma entrada de `APP_USERS` — o `usuario:hash` do login individual.

Rodar: `python scripts/hash_senha.py [usuario]`. A senha é pedida sem eco
(`getpass`) e confirmada; o que sai na tela é só o hash, que é público por
construção — é ele que vai para `/etc/calculadora/env` e `/etc/preanalise/env`.

⚠ A senha NUNCA vai como argumento de linha de comando: argumento fica no
histórico do shell e na lista de processos da máquina. Também não é gravada em
lugar nenhum aqui — quem esquece, recadastra.

Uso típico (VM, uma pessoa por vez):

    $ python scripts/hash_senha.py ana
    ana:pbkdf2_sha256$210000$…$…

e a linha inteira é colada em `APP_USERS`, separando por vírgula quem já está
lá. Ver `ops/DEPLOY.md`.
"""
from __future__ import annotations

import getpass
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from auth import gerar_hash  # noqa: E402


def main() -> int:
    usuario = (sys.argv[1] if len(sys.argv) > 1 else input("Usuário: ")).strip()
    if not usuario:
        print("Usuário vazio.", file=sys.stderr)
        return 2
    # `:` é o separador do par na env, e `,`/`;`/quebra de linha separam as
    # entradas — um nome com qualquer um deles sairia parseado errado (ou
    # sumiria em silêncio, que é pior: a pessoa não conseguiria entrar e o
    # motivo não estaria em lugar nenhum).
    if any(c in usuario for c in ":,;"):
        print("Nome de acesso não pode conter ':', ',' nem ';'.", file=sys.stderr)
        return 2
    # `getpass` lê do CONSOLE, não do stdin — num pipe ele simplesmente fica
    # esperando teclado, sem dizer por quê. Melhor recusar na hora.
    if not sys.stdin.isatty():
        print("Rode num terminal: a senha é digitada, nunca canalizada.",
              file=sys.stderr)
        return 2
    senha = getpass.getpass("Senha: ")
    if len(senha) < 8:
        print("Senha muito curta (mínimo 8).", file=sys.stderr)
        return 2
    if senha != getpass.getpass("Repita a senha: "):
        print("As senhas não conferem.", file=sys.stderr)
        return 2
    print(f"{usuario}:{gerar_hash(senha)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
