import { query } from "./db";

export interface Proposal {
  id: number;
  proposal_number: string | null;
  proposal_date: string | null;
  client_name: string;
  client_doc: string | null;
  client_contact: string | null;
  precatorio_number: string | null;
  tribunal: string | null;
  ente_devedor: string | null;
  natureza: string | null;
  valor_face: number;
  valor_proposta: number;
  desagio: number;
  forma_pagamento: string | null;
  validade: string | null;
  observacoes: string | null;
  responsavel: string | null;
  created_by: string | null;
  created_at: string;
}

export interface ProposalInput {
  proposal_number?: string | null;
  proposal_date?: string | null;
  client_name: string;
  client_doc?: string | null;
  client_contact?: string | null;
  precatorio_number?: string | null;
  tribunal?: string | null;
  ente_devedor?: string | null;
  natureza?: string | null;
  valor_face?: number;
  valor_proposta?: number;
  desagio?: number;
  forma_pagamento?: string | null;
  validade?: string | null;
  observacoes?: string | null;
  responsavel?: string | null;
}

// Numeric columns come back from pg as strings — normalize to number.
function normalize(row: any): Proposal {
  return {
    ...row,
    valor_face: Number(row.valor_face),
    valor_proposta: Number(row.valor_proposta),
    desagio: Number(row.desagio),
  };
}

const RETURNING = `
  id, proposal_number, proposal_date, client_name, client_doc, client_contact,
  precatorio_number, tribunal, ente_devedor, natureza, valor_face, valor_proposta,
  desagio, forma_pagamento, validade, observacoes, responsavel, created_by, created_at
`;

export async function listProposals(): Promise<Proposal[]> {
  const rows = await query<any>(
    `SELECT ${RETURNING} FROM proposals ORDER BY created_at DESC`
  );
  return rows.map(normalize);
}

export async function getProposal(id: number): Promise<Proposal | null> {
  const rows = await query<any>(
    `SELECT ${RETURNING} FROM proposals WHERE id = $1`,
    [id]
  );
  return rows[0] ? normalize(rows[0]) : null;
}

export async function createProposal(
  input: ProposalInput,
  createdBy: string | null
): Promise<Proposal> {
  const rows = await query<any>(
    `INSERT INTO proposals (
       proposal_number, proposal_date, client_name, client_doc, client_contact,
       precatorio_number, tribunal, ente_devedor, natureza, valor_face, valor_proposta,
       desagio, forma_pagamento, validade, observacoes, responsavel, created_by
     ) VALUES (
       $1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13, $14, $15, $16, $17
     )
     RETURNING ${RETURNING}`,
    [
      input.proposal_number ?? null,
      input.proposal_date ?? null,
      input.client_name,
      input.client_doc ?? null,
      input.client_contact ?? null,
      input.precatorio_number ?? null,
      input.tribunal ?? null,
      input.ente_devedor ?? null,
      input.natureza ?? null,
      input.valor_face ?? 0,
      input.valor_proposta ?? 0,
      input.desagio ?? 0,
      input.forma_pagamento ?? null,
      input.validade ?? null,
      input.observacoes ?? null,
      input.responsavel ?? null,
      createdBy,
    ]
  );
  return normalize(rows[0]);
}

export async function deleteProposal(id: number): Promise<void> {
  await query(`DELETE FROM proposals WHERE id = $1`, [id]);
}
