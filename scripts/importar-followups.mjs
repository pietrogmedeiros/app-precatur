#!/usr/bin/env node
// Carrega a biblioteca de follow-ups (backend/seeds/followups.json) pela API do
// app — alternativa ao seeds/followups.sql para quando não há acesso ao psql da
// VM. Roda de qualquer máquina que enxergue o domínio do app.
//
// Uso:
//   APP_URL=https://app.precatur.exemplo \
//   ADMIN_EMAIL=admin@precatur.com \
//   ADMIN_PASSWORD='...' \
//   node scripts/importar-followups.mjs
//
// Idempotente: pula todo follow-up cujo título já exista.
// Passe --dry para só listar o que seria criado, sem gravar nada.

import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const AQUI = path.dirname(fileURLToPath(import.meta.url));
const SEED = path.join(AQUI, "..", "backend", "seeds", "followups.json");

const APP_URL = (process.env.APP_URL ?? "").replace(/\/+$/, "");
const ADMIN_EMAIL = process.env.ADMIN_EMAIL;
const ADMIN_PASSWORD = process.env.ADMIN_PASSWORD;
const DRY = process.argv.includes("--dry");

if (!APP_URL || !ADMIN_EMAIL || !ADMIN_PASSWORD) {
  console.error(
    "Faltam variáveis. Exemplo:\n" +
      "  APP_URL=https://seu-app ADMIN_EMAIL=admin@precatur.com ADMIN_PASSWORD='...' \\\n" +
      "  node scripts/importar-followups.mjs"
  );
  process.exit(1);
}

const itens = JSON.parse(fs.readFileSync(SEED, "utf8"));
console.log(`${itens.length} follow-ups no arquivo de carga.`);

async function api(caminho, { token, method = "GET", body } = {}) {
  const res = await fetch(APP_URL + caminho, {
    method,
    headers: {
      ...(body ? { "Content-Type": "application/json" } : {}),
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
    },
    body: body ? JSON.stringify(body) : undefined,
  });
  const texto = await res.text();
  let json = null;
  try {
    json = texto ? JSON.parse(texto) : null;
  } catch {
    /* resposta não-JSON (ex.: HTML de erro do proxy) */
  }
  if (!res.ok) {
    const msg = json?.message ?? json?.error?.message ?? texto.slice(0, 200);
    throw new Error(`${method} ${caminho} → ${res.status}: ${msg}`);
  }
  return json;
}

const login = await api("/api/auth/login", {
  method: "POST",
  body: { email: ADMIN_EMAIL, password: ADMIN_PASSWORD },
});
const token = login?.token;
if (!token) throw new Error("Login não retornou token.");
console.log(`Autenticado como ${login.user?.name ?? ADMIN_EMAIL}.`);

const existentes = await api("/api/followups", { token });
const titulos = new Set(existentes.map((f) => f.title));
console.log(`${existentes.length} follow-up(s) já cadastrados.`);

const novos = itens.filter((i) => !titulos.has(i.title));
if (!novos.length) {
  console.log("Nada a fazer — todos os títulos já existem.");
  process.exit(0);
}

if (DRY) {
  console.log(`\n[--dry] ${novos.length} seriam criados:`);
  novos.forEach((n, i) => console.log(`  ${String(i + 1).padStart(2)}. ${n.title}`));
  process.exit(0);
}

let criados = 0;
const falhas = [];
for (const item of novos) {
  try {
    await api("/api/followups", {
      token,
      method: "POST",
      body: { title: item.title, body: item.body },
    });
    criados++;
    console.log(`  ok  ${item.title}`);
  } catch (e) {
    falhas.push({ titulo: item.title, erro: e.message });
    console.log(`  ERRO ${item.title} — ${e.message}`);
  }
}

console.log(`\n${criados} criado(s), ${falhas.length} falha(s).`);
process.exit(falhas.length ? 1 : 0);
