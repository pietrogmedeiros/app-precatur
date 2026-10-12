#!/bin/bash
# Troca atomica na VM, com rollback automatico (auditoria A2). Chamado pelo
# scripts/deploy.sh do PC — nao rodar a mao sem ter enviado os arquivos antes:
#
#   vm_troca.sh <stamp> <precatorios_esperados|-> <arquivo>...
#
# Cada <arquivo> (caminho relativo a ~/alfred, ex. data/alfred.db, scripts/api.py)
# ja' esta' na VM como <arquivo>.novo-<stamp>, com sha256 conferido pelo deploy.sh.
# Varios arquivos = UMA transacao: ou todos trocam, ou todos voltam.
#
# Ordem (nada toca a producao antes do passo 5):
#   1. confere argumentos e que todos os .novo chegaram
#   2. variaveis de ambiente que o codigo novo exige (EXIGE_ENV)
#   3. pre-voo: `bash -n` nos .sh novos; importa a API numa COPIA com os .py novos —
#      pega o crash-loop de modulo faltando/quebrado (DEPLOY.md: 14/08 e 22/09)
#   4. trava ~/alfred/.alfred.lock (a mesma do rotina_nacp.sh), espera ate 120 s
#   5. para o servico, faz backup <arquivo>.bak-<stamp>, troca, sobe
#      (deploy so' de .sh nao para o servico: nao e' codigo da API)
#   6. exige /saude HTTP 200 com a contagem esperada (a do banco enviado; so'
#      codigo: a mesma de antes). Sem resposta = API subindo, espera ate 60 s;
#      3 respostas ERRADAS seguidas (5xx, contagem diferente) = ROLLBACK na hora.
#
# Saida: 0 ok | 1 recusado sem tocar na producao | 2 trava ocupada
#        3 falhou e o rollback devolveu o estado anterior | 4 rollback SEM saude
set -euo pipefail
trap '' HUP                          # queda do SSH nao interrompe a troca no meio

BASE="${ALFRED_BASE:-/home/ubuntu/alfred}"
PY="$BASE/.venv/bin/python"
SAUDE_URL="${ALFRED_SAUDE_URL:-http://127.0.0.1:8600/saude}"
LOCK_ESPERA="${ALFRED_LOCK_ESPERA:-120}"
ENV_FILE="${ALFRED_ENV_FILE:-/etc/alfred/env}"
RETENCAO=3                           # backups de banco feitos por este script
DB=data/alfred.db

# codigo que so' funciona com uma variavel no EnvironmentFile do servico
declare -A EXIGE_ENV=([scripts/rastreia.py]=DATAJUD_APIKEY)

cd "$BASE"
mkdir -p log
exec > >(tee -a log/deploy.log) 2>&1

STAMP="${1:-}"; ESPERADO="${2:-}"
shift 2 || true
ARQS=("$@")
echo "===== $(date -Is)  deploy $STAMP: ${ARQS[*]:-}"

# enquanto nada foi trocado, qualquer saida apaga os .novo (o deploy e' refeito do PC)
FASE=preparo
limpa_novos() {
    if [ "$FASE" = preparo ]; then
        for f in "${ARQS[@]}"; do rm -f "$f.novo-$STAMP"; done
    fi
}
trap limpa_novos EXIT

recusa() { echo "!! $* — nada foi trocado"; exit 1; }

# ---- /saude: mesma logica no scripts/rotina_nacp.sh (manter as duas iguais) ----
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

# ---- 1. argumentos
[[ $STAMP =~ ^[0-9]{8}-[0-9]{6}$ ]] || recusa "stamp invalido: '$STAMP'"
[[ $ESPERADO == - || $ESPERADO =~ ^[0-9]+$ ]] || recusa "contagem esperada invalida: '$ESPERADO'"
[ ${#ARQS[@]} -ge 1 ] || recusa "nenhum arquivo"
SO_SH=1                              # so' scripts de operacao: nao reinicia a API
for f in "${ARQS[@]}"; do
    [[ $f =~ ^[A-Za-z0-9._/-]+$ && $f != *..* ]] || recusa "caminho invalido: $f"
    case "$f" in
        scripts/*.sh) ;;
        data/alfred.db|scripts/*.py|scripts/ui.html|data/*.csv) SO_SH=0 ;;
        *) recusa "fora da lista de deploy: $f" ;;
    esac
    [ -f "$f.novo-$STAMP" ] || recusa "nao chegou: $f.novo-$STAMP"
done

# ---- 2. ambiente exigido
for f in "${ARQS[@]}"; do
    v="${EXIGE_ENV[$f]:-}"
    [ -z "$v" ] && continue
    sudo grep -q "^$v=." "$ENV_FILE" || recusa "$f exige $v em $ENV_FILE"
done

# ---- 3. pre-voo
for f in "${ARQS[@]}"; do
    if [[ $f == *.sh ]]; then
        bash -n "$f.novo-$STAMP" || recusa "pre-voo: erro de sintaxe em $f"
        ! grep -q $'\r' "$f.novo-$STAMP" || recusa "pre-voo: $f tem CRLF (quebra no bash)"
    fi
done
if printf '%s\n' "${ARQS[@]}" | grep -q '^scripts/.*\.py$'; then
    ST=$(mktemp -d)
    cp -a scripts "$ST/"
    ln -s "$BASE/data" "$ST/data"
    for f in "${ARQS[@]}"; do
        if [[ $f == scripts/* ]]; then cp "$f.novo-$STAMP" "$ST/$f"; fi
    done
    if ! (cd "$ST" && ALFRED_BASE="$ST" "$PY" -c "import scripts.api"); then
        rm -rf "$ST"
        recusa "pre-voo: a API NAO importa com os arquivos novos"
    fi
    rm -rf "$ST"
    echo "   pre-voo: API importa com os arquivos novos"
fi

# ---- 4. trava
exec 9>"$BASE/.alfred.lock"
echo "   esperando a trava (ate ${LOCK_ESPERA}s)"
if ! flock -w "$LOCK_ESPERA" 9; then
    echo "!! trava ocupada ha ${LOCK_ESPERA}s (rotina_nacp em andamento?) — nada foi trocado"
    exit 2
fi
echo "   trava obtida $(date -Is)"

fecha_wal() {      # so' com o servico parado: devolve o WAL ao arquivo e some com -wal/-shm
    if [ -f "$1" ]; then
        "$PY" -c "import sqlite3,sys; c=sqlite3.connect(sys.argv[1]); c.execute('PRAGMA wal_checkpoint(TRUNCATE)'); c.close()" "$1" || return 1
    fi
    rm -f "$1-wal" "$1-shm"
}

if ! ANTES=$(contagem_antes); then
    echo "!! /saude sem resposta boa ha $((SAUDE_TENTATIVAS * 2)) s ANTES do deploy — sem como validar a troca; corrigir a mao (DEPLOY.md)"
    exit 1
fi
[ "$ESPERADO" = - ] && ESPERADO=$ANTES          # so' codigo: a contagem nao pode mudar
echo "   antes: $ANTES precatorios | esperado depois: $ESPERADO"

# ---- 5. troca
servico() { if [ "$SO_SH" = 0 ]; then sudo systemctl "$1" alfred.service; fi; }
em() { local x=$1; shift; for y in "$@"; do [ "$x" = "$y" ] && return 0; done; return 1; }
BAKS=(); NOVOS=()
rollback() {
    set +e
    echo "!! ROLLBACK $STAMP"
    servico stop
    for f in "${ARQS[@]}"; do
        if em "$f" "${NOVOS[@]}"; then
            [ "$f" = "$DB" ] && rm -f "$DB-wal" "$DB-shm"
            mv -f "$f" "$f.falhou-$STAMP"
        fi
        [ -e "$f.novo-$STAMP" ] && mv -f "$f.novo-$STAMP" "$f.falhou-$STAMP"
        if em "$f" "${BAKS[@]}"; then
            mv -f "$f.bak-$STAMP" "$f"
            echo "   devolvido: $f"
        fi
    done
    servico start
    if espera_saude "$ANTES"; then
        echo "!! FALHOU, mas a producao voltou ao estado anterior (arquivos novos em *.falhou-$STAMP)"
        exit 3
    fi
    echo "!!! ROLLBACK SEM SAUDE — intervir a mao (DEPLOY.md, 'Reverter a mao')"
    exit 4
}

FASE=troca
servico stop
ok=1
for f in "${ARQS[@]}"; do
    if [ "$f" = "$DB" ]; then fecha_wal "$DB" || { echo "!! checkpoint do banco atual falhou"; ok=0; break; }; fi
    if [[ $f == *.sh ]]; then      # o cron chama pelo caminho: tem que continuar executavel
        if [ -e "$f" ]; then chmod --reference="$f" "$f.novo-$STAMP"; else chmod 755 "$f.novo-$STAMP"; fi
    fi
    if [ -e "$f" ]; then
        mv "$f" "$f.bak-$STAMP" || { echo "!! backup de $f falhou"; ok=0; break; }
        BAKS+=("$f")
    fi
    mv "$f.novo-$STAMP" "$f" || { echo "!! troca de $f falhou"; ok=0; break; }
    NOVOS+=("$f")
    echo "   trocado: $f (anterior em $f.bak-$STAMP)"
done
[ $ok = 1 ] || rollback
servico start
[ "$SO_SH" = 1 ] && echo "   so' scripts de operacao: servico NAO reiniciado"

# ---- 6. validacao
espera_saude "$ESPERADO" || rollback

# retencao: so' os RETENCAO backups de banco mais recentes feitos por este script.
# Conta so' o arquivo do backup (nome termina no carimbo): o -wal/-shm que aparece
# quando alguem abre um backup nao e' backup, e contado roubaria vaga dos de verdade.
( ls -1t "$DB".bak-2* 2>/dev/null || true ) | grep -E '\.bak-[0-9]{8}-[0-9]{6}$' \
    | tail -n +$((RETENCAO + 1)) | while read -r v; do
    rm -f -- "$v" "$v-wal" "$v-shm"
    echo "   retencao: apagado $v"
done || true                         # sem backup nenhum, o grep sai 1: nao e' falha
echo "OK $(date -Is)  deploy $STAMP"
