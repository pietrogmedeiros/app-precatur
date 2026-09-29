import { pool, query } from "./db";

export const STATUSES = ["novo", "em_analise", "aprovado", "recusado"] as const;
export type SubmissionStatus = (typeof STATUSES)[number];

export interface SubmissionFileMeta {
  id: number;
  filename: string;
  content_type: string;
  size_bytes: number;
}

export interface Submission {
  id: number;
  nome: string;
  email: string;
  telefone: string;
  processo: string | null;
  referente_a: string | null;
  credor_advogado: string | null;
  honorarios: string | null;
  observacoes: string | null;
  status: SubmissionStatus;
  status_by: string | null;
  status_at: string | null;
  created_at: string;
  files: SubmissionFileMeta[];
}

export interface SubmissionInput {
  nome: string;
  email: string;
  telefone: string;
  processo: string | null;
  referente_a: string | null;
  credor_advogado: string | null;
  honorarios: string | null;
  observacoes: string | null;
}

export interface IncomingFile {
  originalname: string;
  mimetype: string;
  size: number;
  buffer: Buffer;
}

// Os ids vêm do pg como string (BIGSERIAL) — normaliza para número, senão
// comparações e a URL de download ficam inconsistentes.
function normalize(row: any): Submission {
  return {
    ...row,
    id: Number(row.id),
    files: (row.files ?? []).map((f: any) => ({ ...f, id: Number(f.id), size_bytes: Number(f.size_bytes) })),
  };
}

// A lista NUNCA seleciona a coluna `data`: trazer os bytes de todos os anexos
// derrubaria a tela. Só o download lê o conteúdo.
const FILES_JSON = `
  COALESCE(
    (SELECT json_agg(json_build_object(
        'id', f.id, 'filename', f.filename,
        'content_type', f.content_type, 'size_bytes', f.size_bytes
      ) ORDER BY f.id)
     FROM submission_files f WHERE f.submission_id = s.id),
    '[]'::json
  ) AS files
`;

const COLUMNS = `
  s.id, s.nome, s.email, s.telefone, s.processo, s.referente_a, s.credor_advogado,
  s.honorarios, s.observacoes, s.status, s.status_by, s.status_at, s.created_at
`;

export async function listSubmissions(): Promise<Submission[]> {
  const rows = await query<any>(
    `SELECT ${COLUMNS}, ${FILES_JSON} FROM submissions s ORDER BY s.created_at DESC`
  );
  return rows.map(normalize);
}

export async function getSubmission(id: number): Promise<Submission | null> {
  const rows = await query<any>(
    `SELECT ${COLUMNS}, ${FILES_JSON} FROM submissions s WHERE s.id = $1`,
    [id]
  );
  return rows[0] ? normalize(rows[0]) : null;
}

export async function getFile(
  submissionId: number,
  fileId: number
): Promise<{ filename: string; content_type: string; data: Buffer } | null> {
  const rows = await query<any>(
    `SELECT filename, content_type, data FROM submission_files
      WHERE id = $1 AND submission_id = $2`,
    [fileId, submissionId]
  );
  return rows[0] ?? null;
}

// Envio e anexos numa transação só: nunca fica um envio sem os arquivos que o
// cedente mandou, nem arquivo órfão.
export async function createSubmission(
  input: SubmissionInput,
  files: IncomingFile[],
  meta: { ip: string | null; userAgent: string | null }
): Promise<Submission> {
  const client = await pool.connect();
  try {
    await client.query("BEGIN");
    const created = await client.query(
      `INSERT INTO submissions
         (nome, email, telefone, processo, referente_a, credor_advogado,
          honorarios, observacoes, ip, user_agent)
       VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10)
       RETURNING id`,
      [
        input.nome, input.email, input.telefone, input.processo, input.referente_a,
        input.credor_advogado, input.honorarios, input.observacoes,
        meta.ip, meta.userAgent,
      ]
    );
    const id = Number(created.rows[0].id);
    for (const f of files) {
      await client.query(
        `INSERT INTO submission_files (submission_id, filename, content_type, size_bytes, data)
         VALUES ($1, $2, $3, $4, $5)`,
        [id, f.originalname, f.mimetype, f.size, f.buffer]
      );
    }
    await client.query("COMMIT");
    return (await getSubmission(id))!;
  } catch (err) {
    await client.query("ROLLBACK").catch(() => {});
    throw err;
  } finally {
    client.release();
  }
}

export async function updateStatus(
  id: number,
  status: SubmissionStatus,
  by: string | null
): Promise<Submission | null> {
  const rows = await query<any>(
    `UPDATE submissions SET status = $2, status_by = $3, status_at = now()
      WHERE id = $1 RETURNING id`,
    [id, status, by]
  );
  return rows[0] ? getSubmission(id) : null;
}

// Contagem por IP na última hora — trava simples contra envio em massa no
// endpoint público.
export async function countRecentByIp(ip: string, minutes: number): Promise<number> {
  const rows = await query<{ count: string }>(
    `SELECT COUNT(*) AS count FROM submissions
      WHERE ip = $1 AND created_at > now() - ($2 || ' minutes')::interval`,
    [ip, String(minutes)]
  );
  return Number(rows[0]?.count ?? 0);
}
