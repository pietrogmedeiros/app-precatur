#!/bin/bash
# Rotina do NACP: coleta incremental do DJEN + carga no alfred.db + restart.
#
# Roda na VM (cron). Idempotente: pode rodar de novo no mesmo dia sem duplicar
# nada — atos deduplicam por id_djen e a carga usa INSERT OR REPLACE.
#
# POR QUE INCREMENTAL: a varredura completa da janela de 8 meses baixa ~35 mil
# publicacoes para usar ~1.700 (o DJEN nao filtra por classe no servidor) e leva
# ~15 min. A incremental cobre ~10 dias, baixa ~900 e termina em segundos.
#
# A SOBREPOSICAO de 10 dias (SOBREPOSICAO_DIAS no coletor) existe porque o DJEN
# publica com atraso: um ato do dia 5 pode aparecer no dia 12. Retomar exatamente
# onde parou perderia essas publicacoes para sempre.
#
# SEGURANCA DO BANCO (auditoria A2, 30/09/2026). A versao anterior copiava o banco
# com `cp` sem checkpoint, ignorava falha do cp e, no rollback, fazia `mv` com o
# servico no ar. Com o backup de slot unico, um cp que falhasse em silencio faria o
# rollback devolver o banco DO DIA ANTERIOR. Agora:
#   - trava ~/alfred/.alfred.lock (a mesma do deploy): rotina e deploy nunca se cruzam;
#   - backup pela API de backup do SQLite (inclui o que estiver no WAL) + quick_check,
#     e o backup velho e' apagado ANTES: nunca se restaura um backup de outra rodada;
#   - restauracao sempre com o servico PARADO e sem -wal/-shm (WAL de outro banco
#     aplicado sobre o restaurado o corromperia);
#   - sucesso = /saude com HTTP 200 e a MESMA contagem de precatorios de antes
#     (a carga do NACP nao mexe em precatorio). `is-active` nao basta: com
#     Restart=always o servico aparece ativo mesmo em crash-loop.
#
# Instalar:
#   crontab -e
#   50 6 * * * /home/ubuntu/alfred/scripts/rotina_nacp.sh BA >> /home/ubuntu/alfred/log/nacp.log 2>&1
set -euo pipefail

BASE="${ALFRED_BASE:-/home/ubuntu/alfred}"
PY="$BASE/.venv/bin/python"
UF="${1:-BA}"
SAUDE_URL="${ALFRED_SAUDE_URL:-http://127.0.0.1:8600/saude}"
LOCK_ESPERA="${ALFRED_LOCK_ESPERA:-900}"     # segundos esperando um deploy terminar
DB=data/alfred.db
BAK=data/alfred.db.rotina.bak
cd "$BASE"
mkdir -p log

echo "===== $(date -Is)  rotina NACP $UF"

# 0) trava compartilhada com o deploy — espera, nao atropela
exec 9>"$BASE/.alfred.lock"
if ! flock -w "$LOCK_ESPERA" 9; then
    echo "!! trava ocupada ha ${LOCK_ESPERA}s (deploy em andamento?) — nada feito"
    exit 1
fi
echo "   trava obtida $(date -Is)"

# ---- /saude: mesma logica no scripts/vm_troca.sh (manter as duas iguais) ----
SAUDE_TENTATIVAS="${ALFRED_SAUDE_TENTATIVAS:-30}"   # x 2 s = 60 s

le_saude() {       # uma leitura: "<http_code> <precatorios|->"; 000 = sem resposta
    local r code n
    r=$(curl -s -m 5 -w '\n%{http_code}' "$SAUDE_URL" 2>/dev/null) || true
    code=${r##*$'\n'}
    [[ $code =~ ^[0-9]{3}$ ]] || code=000
    n=$(printf '%s' "$r" | grep -o '"precatorios":[0-9]*' | cut -d: -f2) || true
    echo "$code ${n:--}"
}

contagem_antes() { # espera ate 60 s a API responder 200 com contagem (pode estar subindo)
    local code n
    for _ in $(seq "$SAUDE_TENTATIVAS"); do
        read -r code n < <(le_saude)
        if [ "$code" = 200 ] && [ "$n" != - ]; then echo "$n"; return 0; fi
        sleep 2
    done
    return 1
}

espera_saude() {   # $1 = contagem exigida. Sem resposta (subindo): espera ate 60 s.
                   # Resposta DEFINITIVA errada (5xx, contagem diferente) 3x seguidas: falha ja'.
    local code=000 n=- erradas=0
    for _ in $(seq "$SAUDE_TENTATIVAS"); do
        read -r code n < <(le_saude)
        if [ "$code" = 200 ] && [ "$n" = "$1" ]; then
            echo "   saude OK: HTTP 200, precatorios=$n"
            return 0
        fi
        if [ "$code" != 000 ]; then
            erradas=$((erradas + 1))
            if [ "$erradas" -ge 3 ]; then
                echo "!! saude: 3 respostas erradas seguidas (HTTP $code, precatorios=$n; esperado 200 e $1)"
                return 1
            fi
        fi
        sleep 2
    done
    echo "!! saude: nenhuma resposta boa em $((SAUDE_TENTATIVAS * 2)) s (ultima: HTTP $code, precatorios=$n; esperado $1)"
    return 1
}

restaura() {
    echo "!! restaurando o banco do backup DESTA rodada"
    sudo systemctl stop alfred.service
    rm -f "$DB-wal" "$DB-shm"
    mv -f "$BAK" "$DB"
    sudo systemctl start alfred.service
    if espera_saude "$ANTES"; then
        echo "   restaurado"
    else
        echo "!!! restauracao SEM saude — intervir a mao"
    fi
}

if ! ANTES=$(contagem_antes); then
    echo "!! /saude sem resposta boa ha $((SAUDE_TENTATIVAS * 2)) s antes da rotina — nada feito (sem como validar depois)"
    exit 1
fi
echo "   antes: $ANTES precatorios"

# 1) coleta incremental — se falhar, PARA. Carregar com JSON pela metade
#    apagaria atos do acervo (o merge parte do que esta no arquivo).
if ! "$PY" scripts/fetch_djen_nacp.py --uf "$UF" --incremental; then
    echo "!! coleta falhou — nada foi carregado no banco"
    exit 1
fi

# 2) backup consistente. O velho sai ANTES: se este falhar, nao sobra backup de
#    outro dia para uma restauracao devolver.
rm -f "$BAK" "$BAK-wal" "$BAK-shm"
if ! "$PY" - "$DB" "$BAK" <<'EOF'
import sqlite3, sys
src = sqlite3.connect(sys.argv[1])
dst = sqlite3.connect(sys.argv[2])
try:
    src.backup(dst)                       # copia pagina a pagina, WAL incluido
    ok = dst.execute("PRAGMA quick_check").fetchone()[0]
    n = dst.execute("SELECT COUNT(*) FROM precatorio").fetchone()[0]
finally:
    dst.close()
    src.close()
print(f"   backup: quick_check={ok}, {n} precatorios")
sys.exit(0 if ok == "ok" and n > 0 else 1)
EOF
then
    rm -f "$BAK" "$BAK-wal" "$BAK-shm"
    echo "!! backup falhou — nada carregado, banco intocado"
    exit 1
fi

# 3) carga (idempotente, uma transacao so': se morrer no meio, o SQLite desfaz)
if ! "$PY" scripts/db_nacp.py --uf "$UF"; then
    echo "!! carga falhou"
    restaura
    exit 1
fi

# 4) o servico le o banco na consulta, mas reinicia barato e garante estado limpo
sudo systemctl restart alfred.service
if ! espera_saude "$ANTES"; then
    restaura
    exit 1
fi

echo "OK $(date -Is)"
