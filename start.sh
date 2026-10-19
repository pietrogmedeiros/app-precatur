#!/bin/sh
# Sobe os quatro processos do contêiner: o motor de cálculo (Python, :8090), o
# Alfred (Python, :8610), o backend Express (:8080) e o Next.js (:3000, o único
# exposto). Se qualquer um morrer, o contêiner sai e o EasyPanel reinicia.
set -e

# ── Alfred: semeia o volume de dados ──────────────────────────────────────
# O volume (/app/alfred/data) guarda o banco de 308 MB, que não vem na imagem.
# Os CSVs/JSONs pequenos que o núcleo lê vêm na imagem e são copiados para o
# volume SÓ quando faltarem — nunca sobrescrevem, para não desfazer uma
# atualização feita no volume.
if [ -d /app/alfred/data-seed ]; then
  mkdir -p /app/alfred/data
  for f in /app/alfred/data-seed/*; do
    [ -e "$f" ] || continue
    destino="/app/alfred/data/$(basename "$f")"
    [ -e "$destino" ] || cp -r "$f" "$destino"
  done
fi
if [ ! -f /app/alfred/data/alfred.db ]; then
  echo "[start] AVISO: /app/alfred/data/alfred.db não existe — a consulta de"
  echo "[start]        precatórios vai responder erro até o banco ser enviado"
  echo "[start]        para o volume. Ver alfred/LEIAME-EMBUTIDO.md."
fi

# UM worker, de propósito: a análise de PDF guarda o substrato em memória entre
# o passo "analisar" e o passo "extrair dos cortes". Com dois processos, o
# segundo pedido cairia no worker que não tem a sessão. A concorrência vem do
# threadpool do FastAPI (as rotas são síncronas), não de réplicas.
echo "[start] booting motor de cálculo on :8090"
( cd /app/calculadora && exec /opt/motor/bin/python -m uvicorn servico:app \
    --host 127.0.0.1 --port 8090 ) &
MOTOR_PID=$!

# UM worker aqui também: o SQLite é aberto por requisição e o cache de entes
# vive em memória do processo.
echo "[start] booting alfred on :8610"
( cd /app/alfred && exec /opt/alfred/bin/python -m uvicorn servico:app \
    --host 127.0.0.1 --port 8610 ) &
ALFRED_PID=$!

echo "[start] booting backend on :8080"
( cd /app/backend && PORT=8080 node dist/index.js ) &
BACKEND_PID=$!

echo "[start] booting frontend on :3000"
( cd /app/frontend && PORT=3000 HOSTNAME=0.0.0.0 node server.js ) &
FRONTEND_PID=$!

# Sai (e deixa o orquestrador reiniciar) assim que QUALQUER processo morrer.
#
# Aqui havia `wait -n 2>/dev/null || wait`, e isso não cumpria o que promete: o
# /bin/sh desta imagem é o dash, que não tem `wait -n`. O comando falhava, caía
# no `wait` puro — que espera TODOS — e o contêiner seguia vivo com um processo
# morto dentro. Em 19/10/2026 o backend caiu assim: o Next continuou servindo as
# páginas, nada reiniciou, e /api/* ficou 500 até alguém tentar entrar no app.
# Por isso a vigília é explícita, em POSIX puro, e diz QUEM morreu.
vigia() {
  nome=$1
  pid=$2
  kill -0 "$pid" 2>/dev/null && return 0
  echo "[start] $nome (pid $pid) morreu; derrubando o contêiner para reiniciar"
  return 1
}

while sleep 5; do
  vigia "motor de calculo" "$MOTOR_PID" || break
  vigia "alfred"           "$ALFRED_PID" || break
  vigia "backend"          "$BACKEND_PID" || break
  vigia "frontend"         "$FRONTEND_PID" || break
done

kill "$MOTOR_PID" "$ALFRED_PID" "$BACKEND_PID" "$FRONTEND_PID" 2>/dev/null || true
exit 1
