"""OCR local (tesseract) para as peças sem camada de texto.

~1 em 5 contas homologadas do corpus é imagem pura: sem OCR a tela recusa e o
advogado fica sem saída. Roda local, custo zero, ~4s por página a 300 dpi.

⚠ O QUE O OCR NÃO É: fonte de dígito confiável. Medido na conta do caso 1063 —
principal 114.065,54 + juros 40.750,01 = 154.815,55, e o total foi lido como
154.815,5**6**. Um centavo, no campo que vira proposta. Quem denuncia isso é a
prova aritmética da tela, não o modelo e não o próprio OCR.

Por isso o contrato: o OCR ALIMENTA A CONFERÊNCIA (o advogado vê os valores e a
página), nunca decide sozinho.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys

DPI = 300          # abaixo disso a tesseract erra dígito com frequência
TIMEOUT_S = 120
_IDIOMA_CACHE: list[str | None] = []


def binario() -> str | None:
    """Caminho do tesseract, ou None. Respeita `PREFILL_OCR=off`."""
    if (os.environ.get("PREFILL_OCR") or "").lower() in ("off", "0", "false"):
        return None
    caminho = os.environ.get("TESSERACT_BIN") or shutil.which("tesseract")
    if caminho:
        return caminho
    # instalação padrão do Windows não entra no PATH
    padrao = r"C:\Program Files\Tesseract-OCR\tesseract.exe"
    return padrao if os.path.exists(padrao) else None


def disponivel() -> bool:
    return binario() is not None


def idioma() -> str | None:
    """`por` se o pacote existir, senão `eng`, senão o padrão do tesseract.

    O binário sozinho NÃO traz idioma: no Windows deste projeto só havia `eng`,
    e pedir `por` faz a tesseract falhar inteira ("Tesseract couldn't load any
    languages"). Cair para o inglês lê pior acentuação, mas dígito — que é o
    que importa aqui — sai igual.
    """
    if _IDIOMA_CACHE:
        return _IDIOMA_CACHE[0]
    exe = binario()
    escolhido = None
    if exe:
        try:
            r = subprocess.run([exe, "--list-langs"], capture_output=True,
                               text=True, timeout=30)
            langs = {l.strip() for l in (r.stdout or "").splitlines()[1:]}
            escolhido = "por" if "por" in langs else ("eng" if "eng" in langs else None)
            if escolhido != "por":
                print(f"[ocr] pacote 'por' ausente; usando {escolhido or 'padrão'} "
                      f"(instale tesseract-ocr-por)", file=sys.stderr)
        except Exception as e:  # noqa: BLE001
            print(f"[ocr] não consegui listar idiomas: {type(e).__name__}", file=sys.stderr)
    _IDIOMA_CACHE.append(escolhido)
    return escolhido


def ler_pagina(page) -> str:
    """Texto de UMA página escaneada. Injetado como `ocr_fn` no substrato, que
    só chama em página sem camada de texto — página nativa nunca paga os 4s.

    ⚠ `--psm 1` (auto-orientação + segmentação, LSTM+OSD): sem ele, conta
    escaneada de CABEÇA PARA BAIXO (medido: 24 casos do TJAL) sai como lixo
    girado ("opejosojoud…") e o LLM "conserta" o que recebeu inventando
    dígitos — que por coincidência somam ao total real em 9 de 10 casos, e a
    prova aritmética da tela não denuncia. `--psm 0` (só OSD, sem texto) foi
    testado e REPROVADO nesse corpus: errou a orientação de 106/106 páginas
    do TJAL (confundia acento/tabela com script Katakana/Japanese). Medido
    por conta a 300dpi: invertidas foram de 1/86 a 59/86 valores recuperados
    com `--psm 1`, sem regressão nas 28 contas que já liam certo.
    """
    exe = binario()
    if not exe:
        return ""
    try:
        png = page.get_pixmap(dpi=DPI).tobytes("png")
        # `-` nas duas pontas: entrada por stdin, saída por stdout. Sem arquivo
        # temporário, que num servidor multiusuário é uma cópia a menos do
        # documento do cliente em disco.
        cmd = [exe, "-", "stdout", "--psm", "1"]
        lang = idioma()
        if lang:
            cmd += ["-l", lang]
        r = subprocess.run(cmd, input=png, capture_output=True, timeout=TIMEOUT_S)
        if r.returncode != 0:
            # ⚠ NÃO engolir: um pacote de idioma faltando desligaria o OCR em
            # silêncio, e a tela só diria "a conta é uma imagem" para sempre.
            # No serviço isto cai no journalctl.
            print(f"[ocr] tesseract falhou ({r.returncode}): "
                  f"{r.stderr.decode('utf-8', 'replace')[:200]}", file=sys.stderr)
            return ""
        return r.stdout.decode("utf-8", "replace")
    except Exception as e:  # noqa: BLE001 — OCR é melhoria; falhar não derruba a análise
        print(f"[ocr] {type(e).__name__}: {str(e)[:160]}", file=sys.stderr)
        return ""
