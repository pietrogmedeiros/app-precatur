import { pool, query } from "./db";

export interface PricingRow {
  year: string;
  values: number[]; // 4 trimestres, em % (76 = 76%)
  asset: string;
  // Opcionais: quando ausentes, a linha vale para qualquer natureza e qualquer
  // valor. Permitem desdobrar uma praça por natureza e por faixa de valor, como
  // fazem as tabelas de mercado, sem mexer nas tabelas que já existem.
  natureza?: "alimentar" | "comum" | null;
  faixa?: { min?: number | null; max?: number | null } | null;
}

export interface PricingEntity {
  key: string;
  label: string;
  esfera?: "federal" | "estadual" | "municipal" | null;
  uf?: string | null;
  municipio?: string | null;
  description: string;
  position: number;
  fixed_deduction: number;
  municipal_reference: boolean;
  /** Oculta na barra da Precificação; segue valendo para a calculadora pública. */
  hidden: boolean;
  rows: PricingRow[];
  updated_by: string | null;
  updated_at: string;
}

export interface PricingPatch {
  rows?: PricingRow[];
  fixed_deduction?: number;
  description?: string;
  hidden?: boolean;
}

const MUNICIPAL_KEY = "municipal";
// Só estas vêm da planilha comercial — mesmo recorte do importador do HTML.
export const IMPORTABLE_KEYS = ["federal", "estadual", "municipal"] as const;

function normalize(row: any): PricingEntity {
  return {
    ...row,
    fixed_deduction: Number(row.fixed_deduction),
    rows: Array.isArray(row.rows) ? row.rows : [],
  };
}

// Entes que seguem a curva municipal recebem as linhas dela na leitura, em vez
// de guardarem uma cópia que poderia ficar para trás.
export async function listPricing(): Promise<PricingEntity[]> {
  const entities = (await query<any>(
    `SELECT key, label, description, position, fixed_deduction, municipal_reference,
            hidden, esfera, uf, municipio, rows, updated_by, updated_at
       FROM pricing_entities
      ORDER BY position, key`
  )).map(normalize);

  const municipal = entities.find((e) => e.key === MUNICIPAL_KEY);
  return entities.map((e) =>
    e.municipal_reference && municipal
      ? { ...e, rows: municipal.rows, updated_by: municipal.updated_by, updated_at: municipal.updated_at }
      : e
  );
}

// Valida e limpa as linhas. Devolve a mensagem de erro em vez de lançar, para a
// rota responder 400 com o motivo exato.
export function validateRows(input: unknown): { rows: PricingRow[] } | { error: string } {
  if (!Array.isArray(input) || input.length === 0) {
    return { error: "A tabela precisa ter ao menos uma linha." };
  }
  if (input.length > 40) return { error: "A tabela aceita no máximo 40 linhas." };

  const rows: PricingRow[] = [];
  for (let i = 0; i < input.length; i++) {
    const r: any = input[i];
    const n = i + 1;
    const year = typeof r?.year === "string" ? r.year.trim() : String(r?.year ?? "").trim();
    if (!year) return { error: `Linha ${n}: informe a safra/regra.` };
    if (year.length > 40) return { error: `Linha ${n}: safra/regra com mais de 40 caracteres.` };

    if (!Array.isArray(r?.values) || r.values.length !== 4) {
      return { error: `Linha ${n} (${year}): são necessários 4 percentuais, um por trimestre.` };
    }
    const values = r.values.map((v: unknown) => (typeof v === "string" ? Number(v.replace(",", ".")) : Number(v)));
    const bad = values.findIndex((v: number) => !Number.isFinite(v) || v < 0 || v > 100);
    if (bad !== -1) {
      return { error: `Linha ${n} (${year}), ${bad + 1}º tri: percentual deve estar entre 0 e 100.` };
    }

    const asset = typeof r?.asset === "string" && r.asset.trim() ? r.asset.trim() : "Precatório";
    if (asset.length > 40) return { error: `Linha ${n}: tipo de ativo com mais de 40 caracteres.` };

    // Natureza e faixa são opcionais: sem elas a linha vale para as duas
    // naturezas e qualquer valor. Precisam ser preservadas aqui — se caíssem,
    // salvar a tabela pela tela desfaria o desdobramento (caso de Alagoas, que
    // paga preços diferentes para alimentar e comum em 2027).
    const natureza = r?.natureza === "alimentar" || r?.natureza === "comum" ? r.natureza : null;

    let faixa: PricingRow["faixa"] = null;
    if (r?.faixa && typeof r.faixa === "object") {
      const lim = (v: unknown) => (v == null || v === "" ? null : Number(v));
      const min = lim(r.faixa.min);
      const max = lim(r.faixa.max);
      if ((min != null && !Number.isFinite(min)) || (max != null && !Number.isFinite(max))) {
        return { error: `Linha ${n} (${year}): faixa de valor inválida.` };
      }
      if (min != null && max != null && min >= max) {
        return { error: `Linha ${n} (${year}): a faixa precisa ter mínimo menor que o máximo.` };
      }
      if (min != null || max != null) faixa = { min, max };
    }

    // Arredonda a 2 casas: evita 76.00000000001 vindo de planilha.
    rows.push({
      year,
      values: values.map((v: number) => Math.round(v * 100) / 100),
      asset,
      ...(natureza ? { natureza } : {}),
      ...(faixa ? { faixa } : {}),
    });
  }
  return { rows };
}

// Cadastro de praça nova. A chave é derivada do nome e serve de identificador
// estável; o endereço (esfera/UF/município) é o que faz a calculadora achar a
// regra certa.
export async function criaPraca(dados: {
  key: string; label: string; description: string; esfera: string | null;
  uf: string | null; municipio: string | null; fixed_deduction: number; rows: PricingRow[];
  criadoPor: string | null;
}): Promise<PricingEntity[]> {
  const existe = await query(`SELECT 1 FROM pricing_entities WHERE key = $1`, [dados.key]);
  if (existe.length) throw new PricingError(409, "Já existe uma praça com esse identificador.");

  // Entra depois das atuais na ordem da tela.
  const pos = await query<{ max: number }>(`SELECT COALESCE(MAX(position), 0) + 1 AS max FROM pricing_entities`);

  await query(
    `INSERT INTO pricing_entities
       (key, label, description, position, fixed_deduction, municipal_reference,
        esfera, uf, municipio, rows, updated_by)
     VALUES ($1,$2,$3,$4,$5,false,$6,$7,$8,$9,$10)`,
    [
      dados.key, dados.label, dados.description, Number(pos[0]?.max ?? 1), dados.fixed_deduction,
      dados.esfera, dados.uf, dados.municipio, JSON.stringify(dados.rows), dados.criadoPor,
    ]
  );
  return listPricing();
}

export class PricingError extends Error {
  constructor(public status: number, message: string) {
    super(message);
  }
}

// Atualiza entes numa transação só, guardando a versão anterior de cada um.
// Se qualquer ente falhar, nada é gravado — uma importação nunca fica pela metade.
export async function updatePricing(
  patches: Record<string, PricingPatch>,
  changedBy: string | null,
  source: "import" | "edit"
): Promise<PricingEntity[]> {
  const client = await pool.connect();
  try {
    await client.query("BEGIN");
    for (const [key, patch] of Object.entries(patches)) {
      const cur = await client.query(
        `SELECT key, description, fixed_deduction, municipal_reference, rows
           FROM pricing_entities WHERE key = $1 FOR UPDATE`,
        [key]
      );
      const entity = cur.rows[0];
      if (!entity) throw new PricingError(404, `Ente "${key}" não encontrado.`);
      if (entity.municipal_reference) {
        throw new PricingError(
          400,
          `"${key}" segue a curva do Regime Geral Municipal — edite a tabela Municipal.`
        );
      }

      await client.query(
        `INSERT INTO pricing_history (entity_key, rows, fixed_deduction, description, changed_by, source)
         VALUES ($1, $2, $3, $4, $5, $6)`,
        [key, JSON.stringify(entity.rows), entity.fixed_deduction, entity.description, changedBy, source]
      );

      await client.query(
        `UPDATE pricing_entities
            SET rows = COALESCE($2::jsonb, rows),
                fixed_deduction = COALESCE($3, fixed_deduction),
                description = COALESCE($4, description),
                hidden = COALESCE($6, hidden),
                updated_by = $5,
                updated_at = now()
          WHERE key = $1`,
        [
          key,
          patch.rows ? JSON.stringify(patch.rows) : null,
          patch.fixed_deduction ?? null,
          patch.description ?? null,
          changedBy,
          patch.hidden ?? null,
        ]
      );
    }
    await client.query("COMMIT");
  } catch (err) {
    await client.query("ROLLBACK").catch(() => {});
    throw err;
  } finally {
    client.release();
  }
  return listPricing();
}
