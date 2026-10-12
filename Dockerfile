# All-in-one image for EasyPanel (single App service).
# Runs the Express backend (:8080, internal) + the Next.js frontend (:3000,
# public) + o motor de cálculo em Python (:8090) + o Alfred (:8610), ambos
# internos. O frontend encaminha
# /api/* para 127.0.0.1:8080 no mesmo contêiner, e o Express encaminha a
# calculadora para 127.0.0.1:8090.
# Only port 3000 is exposed; point your EasyPanel domain at it.
#
# Por que o Python vem junto: o motor de precatórios é o MESMO código que o
# jurídico já usa (cenários, IR-RRA, PSS, regimes históricos, séries do BACEN).
# Reescrevê-lo em TypeScript mudaria o número; empacotá-lo mantém a paridade.

# ---- build backend ----
FROM node:20-alpine AS backend-build
WORKDIR /app/backend
COPY backend/package*.json ./
RUN npm install
COPY backend/tsconfig.json ./
COPY backend/src ./src
COPY backend/migrations ./migrations
RUN npm run build

# ---- build frontend (standalone) ----
FROM node:20-alpine AS frontend-build
WORKDIR /app/frontend
COPY frontend/package*.json ./
RUN npm install
COPY frontend/ ./
ENV NEXT_PUBLIC_API_URL=""
# Both processes share the container, so the proxy target is localhost.
ENV BACKEND_URL=http://127.0.0.1:8080
RUN npm run build

# ---- runtime ----
# Debian (slim) em vez de Alpine: as rodas do PyMuPDF e do numpy são compiladas
# para glibc; no musl o build teria de compilar tudo da fonte a cada deploy.
FROM node:20-bookworm-slim AS runtime
ENV NODE_ENV=production
WORKDIR /app

# Python do motor + tesseract para as contas escaneadas (~1 em 5 do corpus).
RUN apt-get update \
 && apt-get install -y --no-install-recommends \
      python3 python3-pip python3-venv tesseract-ocr tesseract-ocr-por \
 && rm -rf /var/lib/apt/lists/*

# backend + production deps
COPY backend/package*.json ./backend/
RUN cd backend && npm install --omit=dev
COPY --from=backend-build /app/backend/dist ./backend/dist
COPY --from=backend-build /app/backend/migrations ./backend/migrations

# frontend standalone bundle
COPY --from=frontend-build /app/frontend/.next/standalone ./frontend/
COPY --from=frontend-build /app/frontend/.next/static ./frontend/.next/static
COPY --from=frontend-build /app/frontend/public ./frontend/public

# motor de cálculo (Python) num venv próprio
COPY calculadora/requisitos-servico.txt ./calculadora/requisitos-servico.txt
RUN python3 -m venv /opt/motor \
 && /opt/motor/bin/pip install --no-cache-dir -r ./calculadora/requisitos-servico.txt
COPY calculadora/ ./calculadora/

# Alfred (consulta de precatórios) num venv próprio. O BANCO não vem na imagem:
# são 308 MB que mudam sem o código mudar — ele mora no volume montado em
# /app/alfred/data. Os CSVs pequenos que o núcleo lê vêm aqui em `data-seed/` e
# o start.sh os copia para o volume quando faltarem.
COPY alfred/requisitos-servico.txt ./alfred/requisitos-servico.txt
RUN python3 -m venv /opt/alfred \
 && /opt/alfred/bin/pip install --no-cache-dir -r ./alfred/requisitos-servico.txt
COPY alfred/ ./alfred/

COPY start.sh ./start.sh
RUN chmod +x ./start.sh

EXPOSE 3000
CMD ["./start.sh"]
