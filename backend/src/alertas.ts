// Aviso de infraestrutura por e-mail.
//
// POR QUE EXISTE: em 19/10/2026 o processo do Express morreu e nada avisou —
// o Next seguiu servindo as páginas, o contêiner não saiu, e a API ficou três
// dias respondendo 500 até alguém tentar logar. Hoje a vigília do start.sh e o
// HEALTHCHECK fazem o contêiner se recuperar sozinho; isto aqui é o que conta
// que aconteceu, porque recuperação silenciosa esconde o problema de origem.
//
// O QUE ELE NÃO É: um monitor externo. Quem mora dentro do app não consegue
// avisar da própria morte — ele avisa da VOLTA. Se a máquina inteira cair, este
// e-mail não sai, e é por isso que a conversa sobre um vigia de fora continua
// de pé.
import { pool } from "./db";
import { emailConfigurado, enviaEmail } from "./email";

const TIPO = "reinicio";

// Intervalo mínimo entre dois avisos do mesmo tipo.
const SILENCIO_MIN = Number(process.env.ALERTA_SILENCIO_MIN ?? 30);

function destinatarios(): string[] {
  const bruto = process.env.ALERTA_EMAILS ?? "pietrogoncalvesmedeiros@gmail.com";
  return bruto.split(",").map((e) => e.trim()).filter(Boolean);
}

/**
 * Grava a tentativa e diz se o aviso pode sair agora.
 *
 * A decisão é do BANCO, num UPDATE condicional: duas instâncias subindo juntas
 * disputariam a mesma linha e as duas achariam que podem enviar se a conta
 * fosse feita no Node.
 */
async function podeAvisar(): Promise<boolean> {
  const { rowCount } = await pool.query(
    `INSERT INTO alertas_infra (tipo, ultimo_envio) VALUES ($1, now())
     ON CONFLICT (tipo) DO UPDATE SET ultimo_envio = now()
     WHERE alertas_infra.ultimo_envio < now() - ($2 || ' minutes')::interval
     RETURNING tipo`,
    [TIPO, String(SILENCIO_MIN)]
  );
  return rowCount === 1;
}

export async function avisaQueOAppVoltou(): Promise<void> {
  if (!emailConfigurado()) return;

  try {
    if (!(await podeAvisar())) {
      console.log(`[alerta] reinício não avisado: outro aviso saiu há menos de ${SILENCIO_MIN} min`);
      return;
    }
  } catch (err) {
    // Um aviso que não sai nunca pode derrubar o boot.
    console.error("[alerta] não consegui consultar alertas_infra:", err);
    return;
  }

  const quando = new Date().toLocaleString("pt-BR", { timeZone: "America/Sao_Paulo" });
  const onde = process.env.APP_PUBLIC_URL ?? process.env.APP_URL ?? "app.precatur.pro";
  const assunto = "App Precatur reiniciou";
  const texto =
    `O backend do App Precatur subiu em ${quando} (horário de Brasília).\n\n` +
    `Se ninguém implantou nem reiniciou de propósito, algum processo morreu e o ` +
    `contêiner se recuperou sozinho — o log do serviço no EasyPanel diz qual, na ` +
    `linha "[start] <processo> morreu".\n\n` +
    `Conferir: ${onde}/api/health\n`;
  const html =
    `<p>O backend do <strong>App Precatur</strong> subiu em <strong>${quando}</strong> (horário de Brasília).</p>` +
    `<p>Se ninguém implantou nem reiniciou de propósito, algum processo morreu e o contêiner ` +
    `se recuperou sozinho — o log do serviço no EasyPanel diz qual, na linha ` +
    `<code>[start] &lt;processo&gt; morreu</code>.</p>` +
    `<p>Conferir: <a href="${onde}/api/health">${onde}/api/health</a></p>`;

  for (const para of destinatarios()) {
    try {
      await enviaEmail(para, assunto, html, texto);
      console.log(`[alerta] reinício avisado a ${para}`);
    } catch (err) {
      console.error(`[alerta] falhou o aviso para ${para}:`, err);
    }
  }
}
