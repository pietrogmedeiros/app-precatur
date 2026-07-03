# All-in-one image for EasyPanel (single App service).
# Runs the Express backend (:8080, internal) + the Next.js frontend (:3000,
# public). The frontend proxies /api/* to 127.0.0.1:8080 in the same container.
# Only port 3000 is exposed; point your EasyPanel domain at it.

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
FROM node:20-alpine AS runtime
ENV NODE_ENV=production
WORKDIR /app

# backend + production deps
COPY backend/package*.json ./backend/
RUN cd backend && npm install --omit=dev
COPY --from=backend-build /app/backend/dist ./backend/dist
COPY --from=backend-build /app/backend/migrations ./backend/migrations

# frontend standalone bundle
COPY --from=frontend-build /app/frontend/.next/standalone ./frontend/
COPY --from=frontend-build /app/frontend/.next/static ./frontend/.next/static
COPY --from=frontend-build /app/frontend/public ./frontend/public

COPY start.sh ./start.sh
RUN chmod +x ./start.sh

EXPOSE 3000
CMD ["./start.sh"]
