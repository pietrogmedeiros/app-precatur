#!/bin/sh
# Sobe os três processos do contêiner: o motor de cálculo (Python, :8090), o
# backend Express (:8080) e o Next.js (:3000, o único exposto).
# Se qualquer um morrer, o contêiner sai e o EasyPanel reinicia.
set -e

# UM worker, de propósito: a análise de PDF guarda o substrato em memória entre
# o passo "analisar" e o passo "extrair dos cortes". Com dois processos, o
# segundo pedido cairia no worker que não tem a sessão. A concorrência vem do
# threadpool do FastAPI (as rotas são síncronas), não de réplicas.
echo "[start] booting motor de cálculo on :8090"
( cd /app/calculadora && exec /opt/motor/bin/python -m uvicorn servico:app \
    --host 127.0.0.1 --port 8090 ) &
MOTOR_PID=$!

echo "[start] booting backend on :8080"
( cd /app/backend && PORT=8080 node dist/index.js ) &
BACKEND_PID=$!

echo "[start] booting frontend on :3000"
( cd /app/frontend && PORT=3000 HOSTNAME=0.0.0.0 node server.js ) &
FRONTEND_PID=$!

# Exit (and let the orchestrator restart) as soon as any process dies.
wait -n 2>/dev/null || wait
EXIT=$?
echo "[start] a process exited (code $EXIT); shutting down"
kill "$MOTOR_PID" "$BACKEND_PID" "$FRONTEND_PID" 2>/dev/null || true
exit "$EXIT"
