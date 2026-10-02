import { Router } from "express";
import { listPricing } from "../pricing";
import { resolvePraca, escolheLinha, calcular, aplicaAbatimento, type Praca } from "../calculo";
import { registraSimulacao, buscaSimulacao } from "../simulacoes";
import { criaVerificacao, verificaCodigo, podeReenviar, mascaraTelefone, VerificacaoError } from "../verificacao";
import { enviaCodigo, WhatsappError } from "../whatsapp";

export const calculoRouter = Router();

// Rotas PÚBLICAS: alimentam a calculadora que o cedente abre por link.
// Não devolvem a tabela inteira — só o resultado da praça consultada.

const ESFERAS = ["federal", "estadual", "municipal"] as const;

function trimestreAtual(): number {
  return Math.floor(new Date().getMonth() / 3);
}

function lePraca(q: any): Praca | null {
  const esfera = String(q?.esfera ?? "").toLowerCase();
  if (!ESFERAS.includes(esfera as any)) return null;
  const uf = String(q?.uf ?? "").trim().toUpperCase().slice(0, 2) || null;
  if (esfera !== "federal" && !/^[A-Z]{2}$/.test(uf ?? "")) return null;
  return {
    esfera: esfera as Praca["esfera"],
    uf,
    municipio: String(q?.municipio ?? "").trim().slice(0, 120) || null,
  };
}

// Safras disponíveis para a praça — o formulário monta as opções com isso.
calculoRouter.get("/safras", async (req, res, next) => {
  try {
    const praca = lePraca(req.query);
    if (!praca) {
      return res.status(400).json({ error: "bad_request", message: "Informe a esfera e a UF." });
    }
    const resolvida = resolvePraca(await listPricing(), praca);
    if (!resolvida) {
      return res.status(404).json({ error: "not_found", message: "Não há tabela para essa esfera." });
    }
    const vistos = new Set<string>();
    const safras = resolvida.entity.rows
      .filter((r) => (vistos.has(r.year) ? false : vistos.add(r.year) && true))
      .map((r) => r.year);
    res.json({
      praca: { label: resolvida.entity.label, estimativa: resolvida.estimativa },
      safras,
      ativos: Array.from(new Set(resolvida.entity.rows.map((r) => r.asset))),
    });
  } catch (err) {
    next(err);
  }
});

function numero(v: unknown, max = 1_000_000_000): number {
  const n = typeof v === "string" ? Number(v.replace(",", ".")) : Number(v);
  if (!Number.isFinite(n) || n < 0) return 0;
  return Math.min(n, max);
}

calculoRouter.post("/", async (req, res, next) => {
  try {
    const b = req.body ?? {};
    const praca = lePraca(b);
    if (!praca) {
      return res.status(400).json({ error: "bad_request", message: "Informe a esfera e a UF." });
    }
    // Identificação vem antes do cálculo: a pessoa se apresenta e só então vê o
    // valor. Guardamos já na simulação, mesmo que ela não peça a proposta.
    const texto = (v: unknown, max: number) =>
      typeof v === "string" && v.trim() ? v.trim().slice(0, max) : null;
    const nome = texto(b.nome, 160);
    const email = texto(b.email, 160);
    const telefone = texto(b.telefone, 40);
    if (!nome || !email || !telefone) {
      return res.status(400).json({ error: "bad_request", message: "Informe nome, e-mail e telefone." });
    }
    if (!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email)) {
      return res.status(400).json({ error: "bad_request", message: "Informe um e-mail válido." });
    }

    const safra = String(b.safra ?? "").trim();
    if (!safra) {
      return res.status(400).json({ error: "bad_request", message: "Escolha a safra (ano previsto de pagamento)." });
    }

    const entrada = {
      principal: numero(b.principal),
      juros: numero(b.juros),
      selic: numero(b.selic),
      honorarios_pct: Math.min(100, numero(b.honorarios_pct, 100)),
      ir_pct: Math.min(100, numero(b.ir_pct, 100)),
      ir_base: b.ir_base === "bruto" ? ("bruto" as const) : ("principal" as const),
      pss: numero(b.pss),
      preferencia: numero(b.preferencia),
      outras_despesas: numero(b.outras_despesas),
    };
    if (entrada.principal + entrada.juros + entrada.selic <= 0) {
      return res.status(400).json({
        error: "bad_request",
        message: "Informe ao menos o valor principal do precatório.",
      });
    }

    const resolvida = resolvePraca(await listPricing(), praca);
    if (!resolvida) {
      return res.status(404).json({ error: "not_found", message: "Não há tabela para essa esfera." });
    }

    const registro_ip = (req.ip ?? "").slice(0, 60) || null;
    const bruto = entrada.principal + entrada.juros + entrada.selic;
    const linha = escolheLinha(resolvida.entity, {
      safra,
      ativo: b.ativo ? String(b.ativo) : null,
      natureza: b.natureza === "comum" ? "comum" : b.natureza === "alimentar" ? "alimentar" : null,
      valorBruto: bruto,
    });
    if (!linha) {
      return res.status(422).json({
        error: "sem_tabela",
        message: "Não temos preço para essa combinação de safra e tipo de ativo. Fale com nosso time.",
      });
    }

    const trimestre = trimestreAtual();
    const resultado = calcular(entrada, linha.values[trimestre]);
    const proposta = aplicaAbatimento(resultado.proposta, resolvida.entity.fixed_deduction);

    // Toda simulação é registrada, mesmo sem contato: é o histórico por praça.
    const natureza = b.natureza === "comum" ? "comum" : b.natureza === "alimentar" ? "alimentar" : null;
    const registro = await registraSimulacao({
      esfera: praca.esfera, uf: praca.uf, municipio: praca.municipio,
      praca_label: resolvida.entity.label, estimativa: resolvida.estimativa,
      safra: linha.year, ativo: linha.asset, natureza,
      ...entrada,
      bruto: resultado.bruto, honorarios: resultado.honorarios, ir: resultado.ir,
      liquido: resultado.liquido, percentual: resultado.percentual,
      abatimento: resolvida.entity.fixed_deduction, proposta,
      ip: registro_ip,
      user_agent: (req.get("user-agent") ?? "").slice(0, 300) || null,
      nome, email, telefone, processo: texto(b.processo, 120),
    });

    // O valor NÃO sai daqui: primeiro o telefone é confirmado por WhatsApp.
    try {
      const { codigo, expira_em } = await criaVerificacao(registro.id, telefone, registro_ip);
      await enviaCodigo(telefone, codigo);
      res.json({
        id: registro.id,
        verificacao: { telefone: mascaraTelefone(telefone), expira_em },
      });
    } catch (e) {
      if (e instanceof VerificacaoError) {
        return res.status(e.status).json({ error: "verificacao", message: e.message });
      }
      if (e instanceof WhatsappError) {
        return res.status(502).json({ error: "whatsapp", message: e.message });
      }
      throw e;
    }
  } catch (err) {
    next(err);
  }
});

// Confere o código e só então devolve o resultado — é a porta de entrada do
// valor. O que volta aqui é exatamente o que foi calculado e guardado.
calculoRouter.post("/:id/verificar", async (req, res, next) => {
  try {
    const id = Number(req.params.id);
    if (!Number.isInteger(id)) {
      return res.status(400).json({ error: "bad_request", message: "Simulação inválida." });
    }
    await verificaCodigo(id, String(req.body?.codigo ?? ""));
    const s = await buscaSimulacao(id);
    if (!s) return res.status(404).json({ error: "not_found", message: "Simulação não encontrada." });

    res.json({
      id: s.id,
      praca: { label: s.praca_label, estimativa: s.estimativa },
      safra: s.safra,
      ativo: s.ativo,
      abatimento: s.abatimento,
      bruto: s.bruto,
      honorarios: s.honorarios,
      honorarios_pct: s.honorarios_pct,
      ir: s.ir,
      pss: s.pss,
      preferencia: s.preferencia,
      outras_despesas: s.outras_despesas,
      liquido: s.liquido,
      percentual: s.percentual,
      proposta: s.proposta,
    });
  } catch (err) {
    if (err instanceof VerificacaoError) {
      return res.status(err.status).json({ error: "verificacao", message: err.message });
    }
    next(err);
  }
});

// Reenvio do código, com intervalo mínimo para não virar disparador.
calculoRouter.post("/:id/reenviar", async (req, res, next) => {
  try {
    const id = Number(req.params.id);
    const s = Number.isInteger(id) ? await buscaSimulacao(id) : null;
    if (!s || !s.telefone) {
      return res.status(404).json({ error: "not_found", message: "Simulação não encontrada." });
    }
    if (!(await podeReenviar(id))) {
      return res.status(429).json({ error: "aguarde", message: "Aguarde um minuto para pedir outro código." });
    }
    const { codigo, expira_em } = await criaVerificacao(id, s.telefone, (req.ip ?? "").slice(0, 60) || null);
    await enviaCodigo(s.telefone, codigo);
    res.json({ verificacao: { telefone: mascaraTelefone(s.telefone), expira_em } });
  } catch (err) {
    if (err instanceof VerificacaoError) {
      return res.status(err.status).json({ error: "verificacao", message: err.message });
    }
    if (err instanceof WhatsappError) {
      return res.status(502).json({ error: "whatsapp", message: err.message });
    }
    next(err);
  }
});
