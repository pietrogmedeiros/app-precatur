#!/usr/bin/env node
/**
 * Sonda do contêiner: pergunta aos QUATRO processos se estão de pé.
 *
 * Existe porque a vigília do start.sh é lógica de shell, e foi justamente ela
 * que falhou em 19/10/2026 — o `wait -n` não existe no dash, o contêiner ficou
 * vivo com o backend morto e nada reiniciou por três dias. Esta sonda é
 * declarativa: quem reinicia é o orquestrador, não um laço nosso.
 *
 * Em Node de propósito: a imagem é `node:20-bookworm-slim` e não tem curl nem
 * wget. Sem dependência nenhuma, só o `http` do próprio Node.
 *
 * O backend é consultado pela rota de LIVENESS (sem banco): um Postgres fora do
 * ar é problema do Postgres, e derrubar o app por causa dele só tiraria do ar a
 * tela que explica o que está acontecendo.
 */
const http = require("http");

const ALVOS = [
  { nome: "frontend", porta: 3000, caminho: "/login" },
  { nome: "backend", porta: 8080, caminho: "/api/health/live" },
  { nome: "motor de calculo", porta: 8090, caminho: "/saude" },
  { nome: "alfred", porta: 8610, caminho: "/saude" },
];

const TIMEOUT = Number(process.env.HEALTHCHECK_TIMEOUT_MS || 4000);

function pergunta({ nome, porta, caminho }) {
  return new Promise((resolve) => {
    const req = http.get(
      { host: "127.0.0.1", port: porta, path: caminho, timeout: TIMEOUT },
      (res) => {
        res.resume();
        // Qualquer resposta < 500 serve: a pergunta é "tem alguém atendendo
        // nesta porta?", não "esta rota específica deu certo". Um 401 ou um 307
        // são respostas de um processo vivo.
        resolve(res.statusCode < 500 ? null : `${nome}: HTTP ${res.statusCode}`);
      }
    );
    req.on("timeout", () => {
      req.destroy();
      resolve(`${nome}: sem resposta em ${TIMEOUT}ms`);
    });
    req.on("error", (e) => resolve(`${nome}: ${e.code || e.message}`));
  });
}

Promise.all(ALVOS.map(pergunta)).then((res) => {
  const caidos = res.filter(Boolean);
  if (caidos.length === 0) process.exit(0);
  console.error("[healthcheck] " + caidos.join(" · "));
  process.exit(1);
});
