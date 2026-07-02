# ---- build stage ----
FROM node:20-alpine AS build
WORKDIR /app
COPY package*.json ./
RUN npm install
COPY . .
# Empty NEXT_PUBLIC_API_URL => client calls are relative (/api/*), proxied
# server-side to the backend (see next.config.mjs rewrites).
ENV NEXT_PUBLIC_API_URL=""
# Next resolves rewrites at BUILD time, so the proxy target is baked here.
# Defaults to the compose service name; override with --build-arg BACKEND_URL=...
ARG BACKEND_URL=http://api:8080
ENV BACKEND_URL=$BACKEND_URL
RUN npm run build

# ---- runtime stage ----
FROM node:20-alpine AS runtime
ENV NODE_ENV=production
ENV PORT=3000
WORKDIR /app
# Standalone output bundles a minimal server + only the needed node_modules.
COPY --from=build /app/.next/standalone ./
COPY --from=build /app/.next/static ./.next/static
COPY --from=build /app/public ./public
EXPOSE 3000
CMD ["node", "server.js"]
