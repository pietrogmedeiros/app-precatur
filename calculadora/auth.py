"""Trava de acesso, compartilhada entre as páginas do app.

Dois modos, nesta ordem:

  APP_USERS     login INDIVIDUAL. Lista `usuario:hash`, separada por vírgula
                (`;` e quebra de linha também valem), com o hash no formato
                `pbkdf2_sha256$<iterações>$<salt b64>$<derivado b64>` — gerado
                por `scripts/hash_senha.py`. Senha em claro na env NUNCA é
                aceita: entrada malformada é IGNORADA, e ignorar um usuário
                barra o acesso dele em vez de abrir a porta.
  APP_PASSWORD  a senha ÚNICA do time (o que existia antes). Continua valendo
                mesmo com `APP_USERS` configurada — é a rampa da migração: no
                dia do deploy ninguém fica de fora enquanto os hashes não estão
                distribuídos. Quem entra por ela é ANÔNIMO (`usuario_atual()`
                devolve None) e os pontos de escrita gravam sem autoria,
                exatamente como hoje. Apagar a env fecha a rampa.

Sem nenhuma das duas o app fica ABERTO (uso local/dev).

Por que autenticar de verdade passou a importar: o ledger de adjudicação
(`hub.registrar_adjudicacao`) e o comentário de auditoria no card
(`bitrix.enviar`) querem dizer QUEM conferiu o cálculo. Com senha única não
havia de onde tirar o nome — `revisor` ia None por honestidade, e o comentário
dizia "o advogado", sem dizer qual. É esse buraco que o login individual fecha;
`usuario_atual()` é a única fonte de autoria do app.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import os
import re
import secrets

# `streamlit` NÃO é importado aqui em cima — de propósito. `gerar_hash` e
# `confere_hash` são usados por `scripts/hash_senha.py`, que roda com o
# `python` puro do PATH (fora da venv da UI, muitas vezes na VM, num terminal
# qualquer). Se este módulo puxasse `streamlit` incondicionalmente, gerar um
# hash exigiria a dependência inteira da tela só para rodar `hashlib.pbkdf2`.
# É importado dentro de cada função que de fato desenha algo.

_ALGO = "pbkdf2_sha256"
_ITERACOES = 210_000        # ~0,1 s por tentativa; o custo é do atacante
# Guarda contra `APP_USERS` com um número absurdo de iterações: uma tentativa de
# login não pode travar o processo que serve a calculadora inteira.
_ITERACOES_MIN, _ITERACOES_MAX = 1_000, 2_000_000

# Hash de uma senha aleatória que ninguém tem, com o formato válido. Serve para
# gastar o MESMO tempo quando o usuário NÃO existe: sem isso, a resposta
# instantânea de "não conheço esse nome" contra os ~0,1 s de um nome real vira
# um oráculo de quem trabalha aqui — e a lista de nomes é metade do caminho de
# quem tenta entrar.
_HASH_INEXISTENTE = ("pbkdf2_sha256$210000$B9RBHRnc9cVOoBcyEZ4Wbw==$"
                     "AAyPfQINU/g9pAI2mnEYy45xNJHTexeuAlEsRJv5tYg=")


def gerar_hash(senha: str, iteracoes: int = _ITERACOES) -> str:
    """Hash novo, com salt aleatório. Usado por `scripts/hash_senha.py`."""
    salt = secrets.token_bytes(16)
    derivado = hashlib.pbkdf2_hmac("sha256", senha.encode("utf-8"), salt, iteracoes)
    return "$".join((_ALGO, str(iteracoes),
                     base64.b64encode(salt).decode(),
                     base64.b64encode(derivado).decode()))


def confere_hash(senha: str, guardado: str) -> bool:
    """Verificação em tempo constante.

    Hash malformado é FALSO, nunca exceção: um `APP_USERS` mal editado não pode
    virar nem login liberado nem tela de erro no lugar do formulário.
    """
    try:
        algo, iteracoes, salt_b64, esperado_b64 = guardado.split("$")
        if algo != _ALGO:
            return False
        rodadas = int(iteracoes)
        if not _ITERACOES_MIN <= rodadas <= _ITERACOES_MAX:
            return False
        derivado = hashlib.pbkdf2_hmac(
            "sha256", senha.encode("utf-8"),
            base64.b64decode(salt_b64, validate=True), rodadas)
        return hmac.compare_digest(derivado,
                                   base64.b64decode(esperado_b64, validate=True))
    except (ValueError, TypeError):
        return False


def usuarios() -> dict[str, tuple[str, str]]:
    """`APP_USERS` parseada: chave em minúsculas → (nome configurado, hash).

    O login é case-insensitive (ninguém lembra se cadastrou "Ana" ou "ana"), mas
    quem vai para o ledger é a grafia CONFIGURADA — o registro precisa de um
    nome estável, não do que a pessoa digitou naquele dia.
    """
    achados: dict[str, tuple[str, str]] = {}
    for entrada in re.split(r"[,;\n]", os.environ.get("APP_USERS") or ""):
        entrada = entrada.strip()
        if not entrada or entrada.startswith("#"):
            continue
        # o hash tem `$` e base64 (que não tem `:`), então o PRIMEIRO `:` é
        # sempre o separador — nome de acesso com dois-pontos não é caso real
        nome, sep, guardado = entrada.partition(":")
        nome, guardado = nome.strip(), guardado.strip()
        if sep and nome and guardado:
            achados[nome.casefold()] = (nome, guardado)
    return achados


def _autenticar(usuario: str, senha: str) -> tuple[bool, str | None]:
    """(entrou, identidade). Identidade None = entrou pela senha compartilhada.

    Nome preenchido só casa com `APP_USERS`; nome vazio só casa com
    `APP_PASSWORD`. Sem cruzamento: a senha do time não abre a conta de
    ninguém, e a senha de alguém não vale como senha do time.
    """
    if usuario.strip():
        nome, guardado = usuarios().get(usuario.strip().casefold(),
                                        ("", _HASH_INEXISTENTE))
        # o hash roda ANTES do teste de `nome` — de propósito. Curto-circuitar
        # em "não conheço esse nome" devolveria na hora e entregaria, pelo
        # relógio, quais nomes existem.
        confere = confere_hash(senha, guardado)
        return (True, nome) if confere and nome else (False, None)
    compartilhada = os.environ.get("APP_PASSWORD")
    if compartilhada and hmac.compare_digest(senha, compartilhada):
        return True, None
    return False, None


def require_password() -> None:
    """Barra a página até alguém entrar. Sem env de acesso, libera (dev local)."""
    import streamlit as st

    individual = usuarios()
    if not individual and not os.environ.get("APP_PASSWORD"):
        return
    if st.session_state.get("_auth_ok"):
        return
    with st.form("login"):
        if individual:
            st.text_input("Usuário", key="_user", placeholder="seu nome de acesso")
        st.text_input("Senha de acesso", type="password", key="_pwd")
        ok = st.form_submit_button("Entrar", type="primary")
        if individual and os.environ.get("APP_PASSWORD"):
            st.caption("Sem usuário, a senha do time ainda entra — mas o envio ao "
                       "card e o registro saem **sem autoria**.")
    if ok:
        entrou, quem = _autenticar(st.session_state.get("_user") or "",
                                   st.session_state.get("_pwd") or "")
        if entrou:
            st.session_state["_auth_ok"] = True
            st.session_state["_auth_user"] = quem
            # a senha digitada não fica pendurada na sessão depois de usada
            st.session_state.pop("_pwd", None)
            st.rerun()
        else:
            st.error("Usuário ou senha incorretos." if individual else "Senha incorreta.")
    st.stop()


def usuario_atual() -> str | None:
    """Quem está logado — a fonte de autoria dos pontos de escrita.

    None em três casos, todos legítimos: app aberto (dev), entrada pela senha
    compartilhada da migração, ou sessão ainda não autenticada. Quem grava trata
    None como "sem autoria" e NÃO inventa um nome: registro sem revisor é melhor
    que registro com revisor errado.
    """
    import streamlit as st

    return st.session_state.get("_auth_user")


def mostrar_usuario() -> None:
    """Uma linha discreta dizendo com que nome esta sessão vai gravar.

    Existe porque a máquina é compartilhada e o carimbo é silencioso: sem ver o
    nome na tela, ninguém percebe que está enviando ao card como outra pessoa.
    Só aparece onde há o que dizer — em ambiente ainda não migrado (só
    `APP_PASSWORD`) não há autoria e a linha seria ruído.
    """
    import streamlit as st

    if not st.session_state.get("_auth_ok") or not usuarios():
        return
    quem = usuario_atual()
    st.caption(f"👤 {quem} · atualize a página (F5) para trocar de usuário" if quem
               else "👤 acesso compartilhado — o envio ao card e o registro vão "
                    "**sem autoria**")
