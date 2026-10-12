#!/usr/bin/env bash
# Deploy da VM — substitui ~/deploy-calculadora.sh (cron a cada 2 min).
#
# MUDANÇA: reinicia só o serviço cujos arquivos mudaram. Antes, qualquer commit
# reiniciava a calculadora e derrubava a sessão de quem estava calculando —
# inclusive commits que só mexiam na pré-análise.
set -euo pipefail

REPO=/home/ubuntu/calculadora
cd "$REPO"

ANTES=$(git rev-parse HEAD)
git fetch --quiet origin main
DEPOIS=$(git rev-parse origin/main)

[ "$ANTES" = "$DEPOIS" ] && exit 0

echo "$(date '+%F %T') deploy: ${ANTES:0:7} -> ${DEPOIS:0:7}"
MUDOU=$(git diff --name-only "$ANTES" "$DEPOIS")
git reset --hard --quiet origin/main

if ! git diff --quiet "$ANTES" "$DEPOIS" -- requirements.txt; then
  echo "$(date '+%F %T') requirements.txt mudou — reinstalando deps"
  "$REPO/.venv/bin/pip" install -q -r requirements.txt
  DEPS_MUDARAM=1
fi

# A calculadora reinicia quando muda o que ELA usa: a entrada, o motor, os
# índices, o memorial — ou as dependências. `telas/` e `prefill/` não entram:
# são da pré-análise, e é justamente essa a economia.
# `bitrix_campos\.json` entra na lista porque `bitrix.py` só lê esse arquivo
# na IMPORTAÇÃO (uma vez, na subida do processo) — se o sync diário do CI
# trocar só o JSON (sem tocar em nenhum .py), o arquivo no disco muda mas o
# processo rodando continua com os valores antigos em memória até reiniciar
# por outro motivo. Sem esta linha, o sync existe e nunca é aplicado de fato.
if [ -n "${DEPS_MUDARAM:-}" ] || echo "$MUDOU" | grep -qE '^(Calculadora\.py|memorial\.py|auth\.py|estado\.py|ponte\.py|bitrix\.py|hub\.py|bitrix_campos\.json|precaturia/|assets/|\.streamlit/)'; then
  sudo systemctl restart calculadora
  echo "$(date '+%F %T') calculadora reiniciada"
else
  echo "$(date '+%F %T') calculadora intacta (nada que ela use mudou)"
fi

# A pré-análise usa quase tudo — reinicia em qualquer mudança de código.
# `bitrix_campos\.json` entra pelo mesmo motivo de cima: `telas/pre_analise.py`
# importa `bitrix.py`, que só lê o JSON na subida do processo.
# `is-enabled` guarda o caso de o serviço ainda não existir: com `set -e`, um
# restart de unidade inexistente abortaria o deploy DEPOIS de já ter mexido na
# calculadora, deixando o estado pela metade.
if systemctl list-unit-files preanalise.service >/dev/null 2>&1    && systemctl cat preanalise.service >/dev/null 2>&1; then
  if [ -n "${DEPS_MUDARAM:-}" ] || echo "$MUDOU" | grep -qE '\.py$|^\.streamlit/|^bitrix_campos\.json$'; then
    sudo systemctl restart preanalise
    echo "$(date '+%F %T') pre-analise reiniciada"
  fi
fi

echo "$(date '+%F %T') deploy OK"
