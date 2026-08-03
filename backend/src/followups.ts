import { query } from "./db";

export interface Followup {
  id: number;
  title: string;
  body: string;
  created_by_id: number | null;
  created_by: string | null;
  created_by_name: string | null;
  created_at: string;
  updated_at: string;
}

export interface FollowupInput {
  title: string;
  body: string;
}

export interface FollowupAuthor {
  id: number;
  email: string;
  name: string;
}

const COLUMNS = `
  id, title, body, created_by_id, created_by, created_by_name, created_at, updated_at
`;

// pg devolve BIGINT como string — normaliza os ids para número, senão a
// comparação de dono (created_by_id === user.sub) falha silenciosamente.
function normalize(row: any): Followup {
  return {
    ...row,
    id: Number(row.id),
    created_by_id: row.created_by_id == null ? null : Number(row.created_by_id),
  };
}

export async function listFollowups(): Promise<Followup[]> {
  const rows = await query<any>(
    `SELECT ${COLUMNS} FROM followups ORDER BY created_at DESC`
  );
  return rows.map(normalize);
}

export async function getFollowup(id: number): Promise<Followup | null> {
  const rows = await query<any>(`SELECT ${COLUMNS} FROM followups WHERE id = $1`, [id]);
  return rows[0] ? normalize(rows[0]) : null;
}

export async function createFollowup(
  input: FollowupInput,
  author: FollowupAuthor | null
): Promise<Followup> {
  const rows = await query<any>(
    `INSERT INTO followups (title, body, created_by_id, created_by, created_by_name)
     VALUES ($1, $2, $3, $4, $5)
     RETURNING ${COLUMNS}`,
    [input.title, input.body, author?.id ?? null, author?.email ?? null, author?.name ?? null]
  );
  return normalize(rows[0]);
}

export async function updateFollowup(id: number, input: FollowupInput): Promise<Followup> {
  const rows = await query<any>(
    `UPDATE followups
        SET title = $2, body = $3, updated_at = now()
      WHERE id = $1
      RETURNING ${COLUMNS}`,
    [id, input.title, input.body]
  );
  return normalize(rows[0]);
}

export async function deleteFollowup(id: number): Promise<void> {
  await query(`DELETE FROM followups WHERE id = $1`, [id]);
}
