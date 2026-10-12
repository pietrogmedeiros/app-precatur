"""`motor_versao` do snapshot — o SHA do deploy tem de ser capturável em runtime.

O que estes testes protegem: o snapshot da Fase 2 usa `sha_do_deploy()` para
explicar divergência de recálculo. Se a função devolvesse lixo (uma string que
não é commit) o registro mentiria; se estourasse exceção, derrubaria o envio
por causa de um metadado. Ela só pode devolver SHA verdadeiro ou None.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

_RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_RAIZ))

from versao import sha_do_deploy  # noqa: E402

_SHA = "ff1b636350b609fc6d7880739b5b25430bf90d37"


@pytest.fixture(autouse=True)
def _sem_env_do_render(monkeypatch):
    """A env do Render não pode vazar da máquina para os testes de `.git`."""
    monkeypatch.delenv("RENDER_GIT_COMMIT", raising=False)


def _git_fabricado(tmp_path: Path, head: str, arquivos: dict[str, str] | None = None) -> Path:
    git = tmp_path / ".git"
    git.mkdir()
    (git / "HEAD").write_text(head, encoding="utf-8")
    for rel, conteudo in (arquivos or {}).items():
        destino = git / rel
        destino.parent.mkdir(parents=True, exist_ok=True)
        destino.write_text(conteudo, encoding="utf-8")
    return tmp_path


# ── o caminho da VM: checkout com ref solta ───────────────────────────────
def test_ref_solta(tmp_path):
    raiz = _git_fabricado(tmp_path, "ref: refs/heads/main\n",
                          {"refs/heads/main": _SHA + "\n"})
    assert sha_do_deploy(raiz) == _SHA[:12]


def test_packed_refs_quando_a_ref_solta_nao_existe(tmp_path):
    """`git pack-refs`/`gc` recolhe as refs soltas — o deploy não roda gc,
    mas a versão não pode depender do housekeeping do git."""
    raiz = _git_fabricado(
        tmp_path, "ref: refs/heads/main\n",
        {"packed-refs": ("# pack-refs with: peeled fully-peeled sorted\n"
                         f"{_SHA} refs/heads/main\n"
                         f"^{'a' * 40}\n")})
    assert sha_do_deploy(raiz) == _SHA[:12]


def test_head_detached(tmp_path):
    raiz = _git_fabricado(tmp_path, _SHA + "\n")
    assert sha_do_deploy(raiz) == _SHA[:12]


# ── quando não dá para saber, a resposta é None — nunca invenção ──────────
def test_sem_git_devolve_none(tmp_path):
    assert sha_do_deploy(tmp_path) is None


def test_ref_que_nao_resolve_devolve_none(tmp_path):
    raiz = _git_fabricado(tmp_path, "ref: refs/heads/main\n")
    assert sha_do_deploy(raiz) is None


def test_conteudo_que_nao_e_sha_devolve_none(tmp_path):
    """HEAD corrompido não pode virar `motor_versao`: melhor lacuna visível
    que uma "versão" que nenhum `git show` encontra."""
    raiz = _git_fabricado(tmp_path, "isto nao e um sha\n")
    assert sha_do_deploy(raiz) is None


# ── Render: o commit vem da env, não de checkout ──────────────────────────
def test_env_do_render_tem_prioridade(tmp_path, monkeypatch):
    monkeypatch.setenv("RENDER_GIT_COMMIT", "b" * 40)
    raiz = _git_fabricado(tmp_path, "ref: refs/heads/main\n",
                          {"refs/heads/main": _SHA + "\n"})
    assert sha_do_deploy(raiz) == "b" * 12


def test_env_do_render_com_lixo_e_ignorada(tmp_path, monkeypatch):
    monkeypatch.setenv("RENDER_GIT_COMMIT", "main")
    raiz = _git_fabricado(tmp_path, "ref: refs/heads/main\n",
                          {"refs/heads/main": _SHA + "\n"})
    assert sha_do_deploy(raiz) == _SHA[:12]


# ── este repositório, de verdade ──────────────────────────────────────────
def test_o_processo_atual_se_identifica():
    """A confirmação que a Fase 2 exige: SEM raiz apontada e SEM env, o
    processo rodando deste checkout sabe dizer seu próprio commit."""
    sha = sha_do_deploy()
    assert sha is not None and len(sha) == 12
    assert all(c in "0123456789abcdef" for c in sha)
