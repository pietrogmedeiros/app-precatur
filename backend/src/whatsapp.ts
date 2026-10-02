// Envio do código de verificação pelo WhatsApp (API oficial da Meta).
//
// Por que não passamos pelo Chatwoot: ele não monta o componente de botão que os
// modelos da categoria "autenticação" exigem, e a Meta recusa a mensagem — o
// envio voltava com status `failed`. Falando direto com a Meta, o mesmo modelo
// é aceito.
//
// As credenciais são lidas da própria caixa de entrada do Chatwoot, que continua
// sendo o lugar onde elas são administradas: assim não existe uma segunda cópia
// do token para alguém esquecer de girar. Dá para sobrescrever por variável de
// ambiente quando for conveniente.

export class WhatsappError extends Error {}

const API_VERSION = process.env.WHATSAPP_API_VERSION ?? "v21.0";
const CACHE_MS = 10 * 60 * 1000;

interface Credenciais {
  token: string;
  phoneNumberId: string;
}
let cache: { em: number; cred: Credenciais } | null = null;

export function whatsappConfigurado(): boolean {
  return Boolean(
    (process.env.WHATSAPP_TOKEN && process.env.WHATSAPP_PHONE_NUMBER_ID) ||
      (process.env.CHATWOOT_URL && process.env.CHATWOOT_ACCOUNT_ID &&
        process.env.CHATWOOT_INBOX_ID && process.env.CHATWOOT_TOKEN)
  );
}

async function credenciais(): Promise<Credenciais> {
  if (process.env.WHATSAPP_TOKEN && process.env.WHATSAPP_PHONE_NUMBER_ID) {
    return { token: process.env.WHATSAPP_TOKEN, phoneNumberId: process.env.WHATSAPP_PHONE_NUMBER_ID };
  }
  if (cache && Date.now() - cache.em < CACHE_MS) return cache.cred;

  const base = (process.env.CHATWOOT_URL ?? "").replace(/\/+$/, "");
  const resp = await fetch(
    `${base}/api/v1/accounts/${process.env.CHATWOOT_ACCOUNT_ID}/inboxes/${process.env.CHATWOOT_INBOX_ID}`,
    { headers: { api_access_token: process.env.CHATWOOT_TOKEN as string } }
  );
  if (!resp.ok) {
    console.error("[whatsapp] não consegui ler a caixa no Chatwoot:", resp.status);
    throw new WhatsappError("Não foi possível enviar o código pelo WhatsApp agora.");
  }
  const inbox: any = await resp.json();
  const pc = inbox?.provider_config ?? {};
  if (!pc.api_key || !pc.phone_number_id) {
    throw new WhatsappError("A caixa do WhatsApp no Chatwoot está sem credenciais da Meta.");
  }
  const cred = { token: pc.api_key as string, phoneNumberId: String(pc.phone_number_id) };
  cache = { em: Date.now(), cred };
  return cred;
}

// WhatsApp exige o número com código do país: (51) 98683-2184 → 5551986832184.
export function normalizaTelefone(telefone: string): string | null {
  const d = String(telefone ?? "").replace(/\D/g, "");
  if (d.length === 10 || d.length === 11) return `55${d}`;
  if ((d.length === 12 || d.length === 13) && d.startsWith("55")) return d;
  return null;
}

export async function enviaCodigo(telefone: string, codigo: string): Promise<void> {
  const destino = normalizaTelefone(telefone);
  if (!destino) throw new WhatsappError("Telefone inválido para envio no WhatsApp.");

  if (!whatsappConfigurado()) {
    if (process.env.WHATSAPP_DEV_LOG === "true" || process.env.CHATWOOT_DEV_LOG === "true") {
      console.log(`[whatsapp:dev] código ${codigo} para +${destino} (envio real desligado)`);
      return;
    }
    throw new WhatsappError("Envio de WhatsApp não configurado.");
  }

  const { token, phoneNumberId } = await credenciais();
  const template = process.env.WHATSAPP_TEMPLATE ?? process.env.CHATWOOT_TEMPLATE ?? "codigo_verificacao";
  const lang = process.env.WHATSAPP_TEMPLATE_LANG ?? process.env.CHATWOOT_TEMPLATE_LANG ?? "pt_BR";

  const resp = await fetch(`https://graph.facebook.com/${API_VERSION}/${phoneNumberId}/messages`, {
    method: "POST",
    headers: { Authorization: `Bearer ${token}`, "Content-Type": "application/json" },
    body: JSON.stringify({
      messaging_product: "whatsapp",
      to: destino,
      type: "template",
      template: {
        name: template,
        language: { code: lang },
        // Modelo de autenticação: o código vai no corpo E no botão de copiar.
        // Mandar só o corpo faz a Meta recusar por número de parâmetros.
        components: [
          { type: "body", parameters: [{ type: "text", text: codigo }] },
          { type: "button", sub_type: "url", index: "0", parameters: [{ type: "text", text: codigo }] },
        ],
      },
    }),
  });

  if (!resp.ok) {
    const corpo = await resp.text().catch(() => "");
    console.error("[whatsapp] Meta recusou:", resp.status, corpo.slice(0, 400));
    throw new WhatsappError("Não foi possível enviar o código pelo WhatsApp agora.");
  }
}
