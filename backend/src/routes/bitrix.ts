import { Router } from "express";

export const bitrixRouter = Router();

// Base do webhook REST do Bitrix (ex.: https://.../rest/97/<token>). Injetada por env.
const BITRIX_BASE = process.env.BITRIX_WEBHOOK_BASE ?? "";
// Timeout do upstream (ms).
const UPSTREAM_TIMEOUT_MS = 15_000;

// Mapa TR (código do estado no CNJ) → sigla do tribunal estadual (J = 8).
const TJ_POR_TR: Record<string, string> = {
  "01": "TJAC", "02": "TJAL", "03": "TJAP", "04": "TJAM", "05": "TJBA",
  "06": "TJCE", "07": "TJDFT", "08": "TJES", "09": "TJGO", "10": "TJMA",
  "11": "TJMT", "12": "TJMS", "13": "TJMG", "14": "TJPA", "15": "TJPB",
  "16": "TJPR", "17": "TJPE", "18": "TJPI", "19": "TJRJ", "20": "TJRN",
  "21": "TJRS", "22": "TJRO", "23": "TJRR", "24": "TJSC", "25": "TJSE",
  "26": "TJSP", "27": "TJTO",
};

// Extrai o ID do deal de um ID numérico OU de um link .../crm/deal/details/{id}/.
function extractId(ref: string): string | null {
  const s = ref.trim();
  if (/^\d+$/.test(s)) return s;
  const m = s.match(/crm\/deal\/details\/(\d+)/);
  return m ? m[1] : null;
}

// Campo money "286478.14|BRL" → 286478.14 (number). Ausente/ inválido → null.
function parseMoney(v: unknown): number | null {
  if (v === undefined || v === null || v === "") return null;
  const val = String(v).split("|")[0];
  const n = parseFloat(val);
  return Number.isNaN(n) ? null : n;
}

// String não-vazia (com trim) → string; caso contrário null. Nunca "".
function str(v: unknown): string | null {
  if (v === undefined || v === null) return null;
  const s = String(v).trim();
  return s === "" ? null : s;
}

// Deriva a sigla do tribunal do nº CNJ NNNNNNN-DD.AAAA.J.TR.OOOO (segmento J.TR).
function tribunalFromCNJ(proc: string | null): string | null {
  if (!proc) return null;
  const m = proc.match(/\d{7}-\d{2}\.\d{4}\.(\d)\.(\d{2})\.\d{4}/);
  if (!m) return null;
  const J = m[1];
  const TR = m[2];
  if (J === "8") return TJ_POR_TR[TR] ?? null;          // estadual
  if (J === "4") return `TRF${parseInt(TR, 10)}`;       // federal
  if (J === "5") return `TRT${parseInt(TR, 10)}`;       // trabalho
  return null;
}

// Natureza do CRM → enum "alimentar" | "comum" | null.
function normalizeNatureza(v: unknown): "alimentar" | "comum" | null {
  const s = str(v);
  if (!s) return null;
  const n = s.toLowerCase();
  if (n.startsWith("aliment")) return "alimentar";   // Alimentar / Alimentício / ALIMENTAR
  if (n.startsWith("comum")) return "comum";
  return null;                                        // ex.: Indenizatória
}

// Junta telefone e/ou email num único string ("tel / email"), ou null.
function joinContact(tel: string | null, email: string | null): string | null {
  const parts = [tel, email].filter((p): p is string => !!p);
  return parts.length ? parts.join(" / ") : null;
}

// GET a um método REST do Bitrix, com timeout via AbortController.
async function bitrixGet(method: string, params: Record<string, string>): Promise<any> {
  const base = BITRIX_BASE.replace(/\/+$/, "");
  const qs = new URLSearchParams(params).toString();
  const url = `${base}/${method}.json?${qs}`;
  const ctrl = new AbortController();
  const t = setTimeout(() => ctrl.abort(), UPSTREAM_TIMEOUT_MS);
  try {
    const r = await fetch(url, { signal: ctrl.signal });
    // O Bitrix responde JSON mesmo em erro de negócio (ex.: HTTP 400 "Not found").
    // Deixe o chamador distinguir 404 vs 502; só falhas de rede/timeout/parse sobem.
    return await r.json();
  } finally {
    clearTimeout(t);
  }
}

// GET /api/bitrix/deal?ref=<id|link> → hidrata a proposta a partir do CRM.
bitrixRouter.get("/deal", async (req, res) => {
  // Sem base configurada não há como falar com o Bitrix.
  if (!BITRIX_BASE) {
    return res.status(500).json({
      error: { code: "INTERNAL", message: "BITRIX_WEBHOOK_BASE não configurada." },
    });
  }

  const ref = typeof req.query.ref === "string" ? req.query.ref : "";
  const id = extractId(ref);
  if (!id) {
    return res.status(400).json({
      error: { code: "INVALID_REF", message: "ref ausente ou inválido (nem ID nem link válido)." },
    });
  }

  // Busca do deal (e do contato para fallback de telefone/email).
  let deal: any;
  let contactPhone: string | null = null;
  let contactEmail: string | null = null;
  try {
    const dealResp = await bitrixGet("crm.deal.get", { id });
    // Erro de negócio do Bitrix: "Not found" → 404; qualquer outro erro → 502.
    if (dealResp?.error !== undefined || dealResp?.error_description) {
      const desc = String(dealResp.error_description ?? dealResp.error ?? "");
      if (/not found/i.test(desc)) {
        return res.status(404).json({
          error: { code: "DEAL_NOT_FOUND", message: "Deal não encontrado para o ref informado." },
        });
      }
      throw new Error(`bitrix error: ${desc}`);
    }
    deal = dealResp?.result;
    if (!deal) {
      return res.status(404).json({
        error: { code: "DEAL_NOT_FOUND", message: "Deal não encontrado para o ref informado." },
      });
    }

    const contactId = String(deal.CONTACT_ID ?? "");
    if (/^\d+$/.test(contactId) && parseInt(contactId, 10) > 0) {
      const contactResp = await bitrixGet("crm.contact.get", { id: contactId });
      const c = contactResp?.result;
      if (c) {
        contactPhone = c.PHONE?.[0]?.VALUE ? String(c.PHONE[0].VALUE) : null;
        contactEmail = c.EMAIL?.[0]?.VALUE ? String(c.EMAIL[0].VALUE) : null;
      }
    }
  } catch (err) {
    // Timeout ou erro do upstream Bitrix.
    console.error("[bitrix] upstream error:", err);
    return res.status(502).json({
      error: { code: "BITRIX_UNAVAILABLE", message: "Bitrix indisponível ou tempo esgotado." },
    });
  }

  // Mapeamento CRM → contrato (ver bitrix-map.md).
  const processo = str(deal.UF_CRM_1769029199756);
  const telefone = str(deal.UF_CRM_1769029332435) ?? contactPhone;

  return res.json({
    dealId: String(deal.ID),
    clientName: str(deal.TITLE),
    clientDoc: str(deal.UF_CRM_1769029151931),
    clientContact: joinContact(telefone, contactEmail),
    precatorioNumber: str(deal.UF_CRM_1769029222658),
    tribunal: tribunalFromCNJ(processo),
    enteDevedor: str(deal.UF_CRM_1769029263875),
    natureza: normalizeNatureza(deal.UF_CRM_1769029436243),
    valorFace: parseMoney(deal.UF_CRM_1769029177954),
    valorProposta: parseMoney(deal.UF_CRM_1769087212986),
    meta: {
      fetchedAt: new Date().toISOString(),
      source: "bitrix",
    },
  });
});
