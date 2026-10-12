"""Login individual (`APP_USERS`) — a trava e a autoria que ela habilita.

O que estes testes protegem, em ordem de gravidade:

  1. a porta. `APP_USERS` mal editada não pode virar acesso liberado, e a senha
     do time não pode abrir a conta de ninguém (nem o contrário);
  2. a autoria. `usuario_atual()` é a ÚNICA fonte do `revisor` do ledger e do
     autor no comentário do card — se ela devolvesse o nome errado, o registro
     mentiria com cara de rastro;
  3. a rampa. Enquanto `APP_PASSWORD` existir, quem não tem senha individual
     ainda entra — e entra ANÔNIMO, não como a última pessoa que logou.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

_RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_RAIZ))

import auth  # noqa: E402

_APP = str(_RAIZ / "Calculadora.py")
_HASH_ANA = auth.gerar_hash("segredo-da-ana")


@pytest.fixture(autouse=True)
def _env_limpa(monkeypatch):
    """Nenhum teste herda o ambiente da máquina: com `APP_PASSWORD` do host
    ligada, o teste do app ABERTO passaria por engano."""
    monkeypatch.delenv("APP_USERS", raising=False)
    monkeypatch.delenv("APP_PASSWORD", raising=False)


# ── hash ──────────────────────────────────────────────────────────────────
def test_hash_confere_a_senha_certa_e_recusa_a_errada():
    guardado = auth.gerar_hash("senha-boa")
    assert auth.confere_hash("senha-boa", guardado)
    assert not auth.confere_hash("senha-ruim", guardado)
    assert not auth.confere_hash("Senha-boa", guardado), "a senha é case-sensitive"


def test_hash_novo_a_cada_chamada():
    """Salt aleatório: duas pessoas com a mesma senha não têm o mesmo hash, e
    a lista em `APP_USERS` não denuncia isso a quem a lê."""
    assert auth.gerar_hash("igual") != auth.gerar_hash("igual")


@pytest.mark.parametrize("guardado", [
    "",                                   # vazio
    "senha-em-claro",                     # o erro provável de quem edita a env
    "pbkdf2_sha256$210000$naoehbase64!$x",
    "sha1$210000$AAAA$BBBB",              # algoritmo que não é o nosso
    "pbkdf2_sha256$abc$AAAA$BBBB",        # iterações não numéricas
    "pbkdf2_sha256$1$AAAA$BBBB",          # iterações abaixo do mínimo
    "pbkdf2_sha256$99999999$AAAA$BBBB",   # ...e acima do teto (travaria o app)
    "pbkdf2_sha256$210000$AAAA",          # campo faltando
])
def test_hash_malformado_e_falso_nunca_excecao(guardado):
    """Hash quebrado nega o acesso. Não libera (o perigo) e não estoura a tela
    de login com um traceback (o incômodo)."""
    assert auth.confere_hash("qualquer", guardado) is False


# ── APP_USERS ─────────────────────────────────────────────────────────────
def test_lista_aceita_virgula_ponto_e_virgula_e_quebra_de_linha(monkeypatch):
    monkeypatch.setenv("APP_USERS",
                       f" ana:{_HASH_ANA} , bruno:{_HASH_ANA}\n# comentário\n"
                       f"; carla:{_HASH_ANA}")
    assert sorted(auth.usuarios()) == ["ana", "bruno", "carla"]


def test_entrada_malformada_some_sem_derrubar_as_outras(monkeypatch):
    """Uma linha ruim no meio da env não pode custar o acesso do time inteiro
    — nem virar um usuário sem hash, que seria a porta aberta."""
    monkeypatch.setenv("APP_USERS", f"lixo-sem-hash,ana:{_HASH_ANA},:{_HASH_ANA},vazio:")
    assert list(auth.usuarios()) == ["ana"]


def test_nome_guardado_e_a_grafia_configurada(monkeypatch):
    """Digitar "ANA" entra, mas quem vai para o ledger é "Ana": o registro
    precisa de um nome estável, não do que a pessoa digitou naquele dia."""
    monkeypatch.setenv("APP_USERS", f"Ana Paula:{_HASH_ANA}")
    assert auth._autenticar("ANA PAULA", "segredo-da-ana") == (True, "Ana Paula")


# ── quem entra, e como ────────────────────────────────────────────────────
def test_usuario_certo_entra_com_nome(monkeypatch):
    monkeypatch.setenv("APP_USERS", f"ana:{_HASH_ANA}")
    assert auth._autenticar("ana", "segredo-da-ana") == (True, "ana")


@pytest.mark.parametrize("usuario,senha", [
    ("ana", "outra-senha"),      # senha errada
    ("bruno", "segredo-da-ana"), # usuário que não existe (mesmo com senha real)
    ("ana", ""),                 # senha vazia
])
def test_credencial_errada_nao_entra(monkeypatch, usuario, senha):
    monkeypatch.setenv("APP_USERS", f"ana:{_HASH_ANA}")
    assert auth._autenticar(usuario, senha) == (False, None)


def test_senha_do_time_nao_abre_a_conta_de_ninguem(monkeypatch):
    """Sem cruzamento entre os dois modos: a senha compartilhada entra como
    ANÔNIMA, nunca como a Ana — senão a autoria no ledger seria falsa."""
    monkeypatch.setenv("APP_USERS", f"ana:{_HASH_ANA}")
    monkeypatch.setenv("APP_PASSWORD", "senha-do-time")
    assert auth._autenticar("ana", "senha-do-time") == (False, None)
    assert auth._autenticar("", "senha-do-time") == (True, None)
    assert auth._autenticar("", "segredo-da-ana") == (False, None)


def test_sem_app_password_o_campo_de_usuario_e_obrigatorio(monkeypatch):
    """Fim da migração: apagada a `APP_PASSWORD`, entrar sem nome é impossível
    — é isso que torna a autoria obrigatória."""
    monkeypatch.setenv("APP_USERS", f"ana:{_HASH_ANA}")
    assert auth._autenticar("", "segredo-da-ana") == (False, None)
    assert auth._autenticar("", "") == (False, None)


# ── o fluxo na tela (AppTest roda o app de verdade) ───────────────────────
def _login(at: AppTest, usuario: str | None, senha: str) -> AppTest:
    if usuario is not None:
        at.text_input(key="_user").set_value(usuario)
    at.text_input(key="_pwd").set_value(senha)
    at.button[0].click().run()
    return at


def test_app_barrado_ate_alguem_entrar(monkeypatch):
    monkeypatch.setenv("APP_USERS", f"ana:{_HASH_ANA}")
    at = AppTest.from_file(_APP, default_timeout=90).run()
    assert not at.exception
    assert at.text_input(key="_pwd"), "sem formulário de login não há trava"
    assert not [t for t in at.text_input if t.key == "vt"], \
        "a calculadora renderizou por trás do login"


def test_login_certo_libera_a_tela_e_carrega_o_nome(monkeypatch):
    monkeypatch.setenv("APP_USERS", f"Ana:{_HASH_ANA}")
    at = _login(AppTest.from_file(_APP, default_timeout=90).run(),
                "ana", "segredo-da-ana")
    assert not at.exception
    assert at.session_state["_auth_user"] == "Ana", \
        "é este valor que vira `revisor` no ledger e autor no card"
    assert [t for t in at.text_input if t.key == "vt"], "a calculadora não abriu"
    assert "_pwd" not in at.session_state, "a senha ficou pendurada na sessão"


def test_login_errado_nao_libera(monkeypatch):
    monkeypatch.setenv("APP_USERS", f"ana:{_HASH_ANA}")
    at = _login(AppTest.from_file(_APP, default_timeout=90).run(), "ana", "chute")
    assert not at.exception
    assert "_auth_ok" not in at.session_state
    assert at.error, "erro de senha precisa aparecer na tela"


def test_senha_do_time_entra_anonima(monkeypatch):
    """A rampa da migração: entra, usa o app, e o registro sai SEM autoria —
    que é exatamente o comportamento de antes deste trabalho."""
    monkeypatch.setenv("APP_USERS", f"ana:{_HASH_ANA}")
    monkeypatch.setenv("APP_PASSWORD", "senha-do-time")
    at = _login(AppTest.from_file(_APP, default_timeout=90).run(),
                "", "senha-do-time")
    assert not at.exception
    assert at.session_state["_auth_ok"] is True
    assert at.session_state["_auth_user"] is None
    assert [t for t in at.text_input if t.key == "vt"]


def test_ambiente_legado_so_com_senha_unica(monkeypatch):
    """Ambiente ainda não migrado: nem campo de usuário aparece, e a senha
    única continua entrando — o deploy não pode exigir a env nova."""
    monkeypatch.setenv("APP_PASSWORD", "senha-do-time")
    at = AppTest.from_file(_APP, default_timeout=90).run()
    assert not [t for t in at.text_input if t.key == "_user"]
    at = _login(at, None, "senha-do-time")
    assert not at.exception
    assert at.session_state["_auth_ok"] is True
    assert at.session_state["_auth_user"] is None


def test_a_pre_analise_usa_a_mesma_trava(monkeypatch):
    """São dois processos, e cada um autentica por si. A pré-análise é a tela
    que abre PDF de cliente — ficar de fora da trava seria o pior lugar."""
    monkeypatch.setenv("APP_USERS", f"ana:{_HASH_ANA}")
    monkeypatch.setenv("PREFILL_ENABLED", "1")
    at = AppTest.from_file(str(_RAIZ / "PreAnalise.py"), default_timeout=90).run()
    assert not at.exception
    assert at.text_input(key="_user") and at.text_input(key="_pwd")
    at = _login(at, "ana", "segredo-da-ana")
    assert not at.exception
    assert at.session_state["_auth_user"] == "ana"


def test_sem_env_nenhuma_o_app_fica_aberto():
    """Uso local: sem `APP_USERS` nem `APP_PASSWORD`, nada de login (é a
    premissa de todos os outros testes de AppTest do repositório)."""
    at = AppTest.from_file(_APP, default_timeout=90).run()
    assert not at.exception
    assert not [t for t in at.text_input if t.key == "_pwd"]
    assert [t for t in at.text_input if t.key == "vt"]
