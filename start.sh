#!/bin/sh
# Start the backend (internal :8080) then the Next.js server (public :3000).
# If either process exits, the container exits so EasyPanel restarts it.
set -e

echo "[start] booting backend on :8080"
( cd /app/backend && PORT=8080 node dist/index.js ) &
BACKEND_PID=$!

echo "[start] booting frontend on :3000"
( cd /app/frontend && PORT=3000 HOSTNAME=0.0.0.0 node server.js ) &
FRONTEND_PID=$!

# Exit (and let the orchestrator restart) as soon as either process dies.
wait -n 2>/dev/null || wait
EXIT=$?
echo "[start] a process exited (code $EXIT); shutting down"
kill "$BACKEND_PID" "$FRONTEND_PID" 2>/dev/null || true
exit "$EXIT"
