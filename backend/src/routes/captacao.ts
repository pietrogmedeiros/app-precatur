import { Router } from "express";
import multer from "multer";
import {
  listSubmissions, getSubmission, getFile, createSubmission, updateStatus,
  countRecentByIp, STATUSES, type SubmissionStatus,
} from "../captacao";
import { requireAuth, blockJuridico, type AuthedRequest } from "../auth";

export const captacaoRouter = Router();

/* ------------------------- Limites do envio público ----------------------- */

export const MAX_FILES = 10;
export const MAX_FILE_MB = 10;
export const MAX_TOTAL_MB = 30;
// Só formatos de documento e imagem. Nada de zip/executável/svg/html: o time vai
// baixar esses arquivos, e SVG/HTML abrem espaço para script no navegador.
const ALLOWED = new Map<string, string[]>([
  ["application/pdf", [".pdf"]],
  ["image/jpeg", [".jpg", ".jpeg"]],
  ["image/png", [".png"]],
  ["image/webp", [".webp"]],
  ["image/heic", [".heic"]],
  ["application/msword", [".doc"]],
  ["application/vnd.openxmlformats-officedocument.wordprocessingml.document", [".docx"]],
  ["application/vnd.ms-excel", [".xls"]],
  ["application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", [".xlsx"]],
]);
const EXT_OK = new Set([...ALLOWED.values()].flat());
// Envios por IP por hora. 20 porque um escritório pode legitimamente mandar
// vários precatórios em sequência — o alvo aqui é robô, não parceiro ocupado.
const MAX_POR_IP_HORA = 20;

// Endereço local/privado significa que o IP do cedente NÃO chegou até aqui (o
// proxy não repassou). Nesse caso todos os envios teriam o mesmo endereço e a
// trava derrubaria cedentes legítimos — então ela não se aplica. O valor
// continua sendo gravado para investigação.
function ipIdentificaCliente(ip: string | null): boolean {
  if (!ip) return false;
  const v = ip.replace(/^::ffff:/, "");
  if (v === "::1" || v === "127.0.0.1" || v.startsWith("127.")) return false;
  if (v.startsWith("10.") || v.startsWith("192.168.") || v.startsWith("169.254.")) return false;
  if (/^172\.(1[6-9]|2\d|3[01])\./.test(v)) return false;
  if (/^(fc|fd)/i.test(v)) return false; // faixa privada do IPv6
  return true;
}

const upload = multer({
  storage: multer.memoryStorage(),
  limits: { fileSize: MAX_FILE_MB * 1024 * 1024, files: MAX_FILES, fields: 30 },
  fileFilter: (_req, file, cb) => {
    const ext = ("." + (file.originalname.split(".").pop() ?? "")).toLowerCase();
    if (!EXT_OK.has(ext) || !ALLOWED.has(file.mimetype)) {
      return cb(new Error(`Tipo de arquivo não aceito: ${file.originalname}`));
    }
    cb(null, true);
  },
});

function texto(v: unknown, max: number): string | null {
  if (typeof v !== "string") return null;
  const t = v.trim();
  if (!t) return null;
  return t.slice(0, max);
}

/* ------------------------------ Envio público ----------------------------- */

// Sem autenticação de propósito: é o formulário que o cedente abre por link.
captacaoRouter.post("/", (req, res, next) => {
  upload.array("arquivos", MAX_FILES)(req, res, async (err: any) => {
    try {
      if (err) {
        const msg =
          err.code === "LIMIT_FILE_SIZE"
            ? `Cada arquivo pode ter no máximo ${MAX_FILE_MB} MB.`
            : err.code === "LIMIT_FILE_COUNT"
              ? `Envie no máximo ${MAX_FILES} arquivos.`
              : err.message || "Não foi possível processar os arquivos.";
        return res.status(400).json({ error: "bad_request", message: msg });
      }

      const ip = (req.ip ?? "").slice(0, 60) || null;
      if (ipIdentificaCliente(ip) && (await countRecentByIp(ip!, 60)) >= MAX_POR_IP_HORA) {
        return res.status(429).json({
          error: "too_many_requests",
          message: "Muitos envios deste dispositivo na última hora. Tente mais tarde ou fale com nosso time.",
        });
      }

      const b = req.body ?? {};
      const nome = texto(b.nome, 160);
      const email = texto(b.email, 160);
      const telefone = texto(b.telefone, 40);
      if (!nome || !email || !telefone) {
        return res.status(400).json({
          error: "bad_request",
          message: "Nome, e-mail e telefone são obrigatórios.",
        });
      }
      if (!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email)) {
        return res.status(400).json({ error: "bad_request", message: "Informe um e-mail válido." });
      }

      const files = (req.files as Express.Multer.File[] | undefined) ?? [];
      const total = files.reduce((s, f) => s + f.size, 0);
      if (total > MAX_TOTAL_MB * 1024 * 1024) {
        return res.status(400).json({
          error: "bad_request",
          message: `O total de anexos passa de ${MAX_TOTAL_MB} MB. Envie menos arquivos ou reduza o tamanho.`,
        });
      }

      const criado = await createSubmission(
        {
          nome, email, telefone,
          processo: texto(b.processo, 120),
          referente_a: texto(b.referente_a, 200),
          credor_advogado: texto(b.credor_advogado, 200),
          honorarios: texto(b.honorarios, 120),
          observacoes: texto(b.observacoes, 2000),
        },
        files.map((f) => ({
          // Nome de arquivo chega do cliente: corta caminho e caracteres de
          // controle para não virar problema na hora do download.
          originalname: (f.originalname.split(/[\\/]/).pop() ?? "arquivo")
            .replace(/[\u0000-\u001f\u007f]/g, "").slice(0, 180),
          mimetype: f.mimetype,
          size: f.size,
          buffer: f.buffer,
        })),
        { ip, userAgent: (req.get("user-agent") ?? "").slice(0, 300) || null }
      );

      // Devolve só o protocolo: a tela pública não precisa (nem deve) ver o resto.
      res.status(201).json({ id: criado.id, arquivos: criado.files.length });
    } catch (e) {
      next(e);
    }
  });
});

/* ------------------------- Acompanhamento interno ------------------------- */

captacaoRouter.get("/", requireAuth, blockJuridico, async (_req, res, next) => {
  try {
    res.json(await listSubmissions());
  } catch (err) {
    next(err);
  }
});

captacaoRouter.get("/:id", requireAuth, blockJuridico, async (req, res, next) => {
  try {
    const id = Number(req.params.id);
    if (!Number.isInteger(id)) {
      return res.status(400).json({ error: "bad_request", message: "ID inválido." });
    }
    const s = await getSubmission(id);
    if (!s) return res.status(404).json({ error: "not_found", message: "Envio não encontrado." });
    res.json(s);
  } catch (err) {
    next(err);
  }
});

captacaoRouter.get("/:id/arquivos/:fileId", requireAuth, blockJuridico, async (req, res, next) => {
  try {
    const id = Number(req.params.id);
    const fileId = Number(req.params.fileId);
    if (!Number.isInteger(id) || !Number.isInteger(fileId)) {
      return res.status(400).json({ error: "bad_request", message: "ID inválido." });
    }
    const f = await getFile(id, fileId);
    if (!f) return res.status(404).json({ error: "not_found", message: "Arquivo não encontrado." });

    const seguro = f.filename.replace(/["\r\n]/g, "_");
    res.setHeader("Content-Type", f.content_type);
    // Sempre como anexo e sem adivinhação de tipo: o arquivo veio de fora.
    res.setHeader("X-Content-Type-Options", "nosniff");
    res.setHeader(
      "Content-Disposition",
      `attachment; filename="${seguro}"; filename*=UTF-8''${encodeURIComponent(f.filename)}`
    );
    res.send(f.data);
  } catch (err) {
    next(err);
  }
});

captacaoRouter.patch("/:id", requireAuth, blockJuridico, async (req: AuthedRequest, res, next) => {
  try {
    const id = Number(req.params.id);
    if (!Number.isInteger(id)) {
      return res.status(400).json({ error: "bad_request", message: "ID inválido." });
    }
    const status = req.body?.status;
    if (!STATUSES.includes(status)) {
      return res.status(400).json({
        error: "bad_request",
        message: `Situação inválida. Use uma de: ${STATUSES.join(", ")}.`,
      });
    }
    const s = await updateStatus(id, status as SubmissionStatus, req.user?.email ?? null);
    if (!s) return res.status(404).json({ error: "not_found", message: "Envio não encontrado." });
    res.json(s);
  } catch (err) {
    next(err);
  }
});
