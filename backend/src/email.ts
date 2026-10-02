// Envio de e-mail pelo Resend (o domínio precatur.pro já está apontado lá).
//
// Sem RESEND_API_KEY o envio falha de propósito: um "enviamos o link" que não
// envia nada deixaria a pessoa esperando para sempre. Em desenvolvimento,
// EMAIL_DEV_LOG=true imprime o conteúdo no log em vez de enviar.

export class EmailError extends Error {}

const REMETENTE = process.env.EMAIL_FROM ?? "Precatur <nao-responder@precatur.pro>";

export function emailConfigurado(): boolean {
  return Boolean(process.env.RESEND_API_KEY);
}

export async function enviaEmail(para: string, assunto: string, html: string, texto: string): Promise<void> {
  if (!emailConfigurado()) {
    if (process.env.EMAIL_DEV_LOG === "true") {
      console.log(`[email:dev] para ${para} · ${assunto}\n${texto}`);
      return;
    }
    throw new EmailError("Envio de e-mail não configurado (RESEND_API_KEY).");
  }

  const resp = await fetch("https://api.resend.com/emails", {
    method: "POST",
    headers: {
      Authorization: `Bearer ${process.env.RESEND_API_KEY}`,
      "Content-Type": "application/json",
    },
    body: JSON.stringify({ from: REMETENTE, to: [para], subject: assunto, html, text: texto }),
  });

  if (!resp.ok) {
    const corpo = await resp.text().catch(() => "");
    console.error("[email] Resend recusou:", resp.status, corpo.slice(0, 400));
    throw new EmailError("Não foi possível enviar o e-mail agora.");
  }
}

/* ------------------------- Modelo: redefinir senha ------------------------ */

// HTML de e-mail não é HTML de site: tabela no lugar de flex, estilo em linha e
// largura fixa, porque Gmail e Outlook removem <style> e não entendem boa parte
// do CSS moderno.
export function emailRedefinicao(nome: string, link: string, validadeMin: number) {
  // O logo precisa de um endereço PÚBLICO: o cliente de e-mail busca a imagem
  // pelos servidores dele (o Gmail usa um proxy), então uma URL de
  // desenvolvimento quebra a imagem. Por isso tem variável própria e não
  // acompanha o APP_URL, que em teste aponta para a máquina local.
  const logo =
    process.env.EMAIL_LOGO_URL ??
    `${(process.env.APP_PUBLIC_URL ?? process.env.APP_URL ?? "").replace(/\/+$/, "")}/precatur-logo.png`;
  const assunto = "Redefinição de senha · App Precatur";

  const html = `<!doctype html>
<html lang="pt-BR"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width">
<title>${assunto}</title></head>
<body style="margin:0;padding:0;background:#f4f4f5;">
  <!-- texto de pré-visualização: aparece na lista do e-mail, antes de abrir -->
  <div style="display:none;max-height:0;overflow:hidden;opacity:0;">
    Link para criar uma nova senha no App Precatur. Vale por ${validadeMin} minutos.
  </div>
  <table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="background:#f4f4f5;padding:32px 12px;">
    <tr><td align="center">
      <table role="presentation" width="100%" cellpadding="0" cellspacing="0"
             style="max-width:520px;background:#ffffff;border:1px solid #e4e4e7;border-radius:12px;">
        <tr><td align="center" style="padding:32px 32px 8px;">
          <img src="${logo}" width="150" alt="PRECATUR"
               style="display:block;width:150px;max-width:60%;height:auto;border:0;
                      font-family:Arial,Helvetica,sans-serif;font-size:18px;font-weight:bold;
                      letter-spacing:2px;color:#09090b;text-decoration:none;">
        </td></tr>
        <tr><td style="padding:16px 32px 0;font-family:Arial,Helvetica,sans-serif;">
          <h1 style="margin:0 0 12px;font-size:20px;line-height:1.3;color:#09090b;">Redefinição de senha</h1>
          <p style="margin:0 0 12px;font-size:15px;line-height:1.6;color:#3f3f46;">
            Olá, ${nome}. Recebemos um pedido para criar uma nova senha da sua conta no App Precatur.
          </p>
          <p style="margin:0 0 24px;font-size:15px;line-height:1.6;color:#3f3f46;">
            Clique no botão abaixo. O link vale por <strong>${validadeMin} minutos</strong> e só pode ser usado uma vez.
          </p>
        </td></tr>
        <tr><td align="center" style="padding:0 32px 24px;">
          <!-- bulletproof button: <a> com padding, que funciona em todo cliente -->
          <a href="${link}"
             style="display:inline-block;background:#09090b;color:#ffffff;text-decoration:none;
                    font-family:Arial,Helvetica,sans-serif;font-size:15px;font-weight:bold;
                    padding:14px 28px;border-radius:8px;">Criar nova senha</a>
        </td></tr>
        <tr><td style="padding:0 32px 8px;font-family:Arial,Helvetica,sans-serif;">
          <p style="margin:0 0 6px;font-size:13px;line-height:1.6;color:#71717a;">
            Se o botão não funcionar, copie e cole este endereço no navegador:
          </p>
          <p style="margin:0 0 24px;font-size:13px;line-height:1.6;word-break:break-all;">
            <a href="${link}" style="color:#3f3f46;">${link}</a>
          </p>
        </td></tr>
        <tr><td style="padding:0 32px 32px;font-family:Arial,Helvetica,sans-serif;">
          <table role="presentation" width="100%" cellpadding="0" cellspacing="0"
                 style="background:#fafafa;border:1px solid #e4e4e7;border-radius:8px;">
            <tr><td style="padding:14px 16px;font-size:13px;line-height:1.6;color:#52525b;">
              <strong>Não foi você?</strong> Pode ignorar esta mensagem — sua senha continua a mesma
              enquanto o link não for usado.
            </td></tr>
          </table>
        </td></tr>
      </table>
      <p style="margin:16px 0 0;font-family:Arial,Helvetica,sans-serif;font-size:12px;line-height:1.6;color:#a1a1aa;">
        Esta mensagem foi enviada automaticamente pelo App Precatur. Não responda a este e-mail.
      </p>
    </td></tr>
  </table>
</body></html>`;

  const texto = `Olá, ${nome}.

Recebemos um pedido para criar uma nova senha da sua conta no App Precatur.

Abra este endereço para continuar (vale por ${validadeMin} minutos e só pode ser usado uma vez):
${link}

Não foi você? Pode ignorar esta mensagem — sua senha continua a mesma enquanto o link não for usado.

Mensagem automática. Não responda a este e-mail.`;

  return { assunto, html, texto };
}
