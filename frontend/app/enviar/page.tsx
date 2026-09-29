"use client";

import { useRef, useState } from "react";
import { CheckCircle2, FileUp, Loader2, Paperclip, X } from "lucide-react";
import { enviarCaptacao } from "@/lib/api";
import { maskProcesso, maskTelefone } from "@/lib/masks";
import { Button } from "@/components/ui/button";

// Página PÚBLICA: é o link que o cedente/advogado recebe. Não exige login e é a
// única rota do app fora do portão do middleware, junto com /login.
const MAX_ARQUIVOS = 10;
const MAX_MB_ARQUIVO = 10;
const MAX_MB_TOTAL = 30;
const ACEITOS = ".pdf,.jpg,.jpeg,.png,.webp,.heic,.doc,.docx,.xls,.xlsx";

const inputClass =
  "flex h-10 w-full rounded-md border border-input bg-background px-3 py-1 text-sm shadow-sm outline-none focus-visible:ring-2 focus-visible:ring-ring";
const textareaClass =
  "flex w-full rounded-md border border-input bg-background px-3 py-2 text-sm shadow-sm outline-none focus-visible:ring-2 focus-visible:ring-ring";

function mb(bytes: number): string {
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`;
}

export default function EnviarPage() {
  const fileRef = useRef<HTMLInputElement>(null);
  const [arquivos, setArquivos] = useState<File[]>([]);
  // Campos com máscara precisam ser controlados para reformatar a cada tecla.
  const [telefone, setTelefone] = useState("");
  const [processo, setProcesso] = useState("");
  const [enviando, setEnviando] = useState(false);
  const [erro, setErro] = useState<string | null>(null);
  const [protocolo, setProtocolo] = useState<number | null>(null);

  const total = arquivos.reduce((s, f) => s + f.size, 0);

  function adicionar(lista: FileList | null) {
    if (!lista) return;
    setErro(null);
    const novos = [...arquivos];
    for (const f of Array.from(lista)) {
      if (novos.length >= MAX_ARQUIVOS) {
        setErro(`Você pode enviar no máximo ${MAX_ARQUIVOS} arquivos.`);
        break;
      }
      if (f.size > MAX_MB_ARQUIVO * 1024 * 1024) {
        setErro(`"${f.name}" tem ${mb(f.size)} — o limite por arquivo é ${MAX_MB_ARQUIVO} MB.`);
        continue;
      }
      if (!novos.some((x) => x.name === f.name && x.size === f.size)) novos.push(f);
    }
    setArquivos(novos);
    if (fileRef.current) fileRef.current.value = "";
  }

  async function onSubmit(e: React.FormEvent<HTMLFormElement>) {
    e.preventDefault();
    setErro(null);

    if (total > MAX_MB_TOTAL * 1024 * 1024) {
      setErro(`O total dos anexos é ${mb(total)} e o limite é ${MAX_MB_TOTAL} MB.`);
      return;
    }

    const form = new FormData(e.currentTarget);
    form.delete("arquivos"); // o input de arquivo é controlado pela lista abaixo
    arquivos.forEach((f) => form.append("arquivos", f));

    setEnviando(true);
    try {
      const r = await enviarCaptacao(form);
      setProtocolo(r.id);
      window.scrollTo({ top: 0, behavior: "smooth" });
    } catch (err: any) {
      setErro(err?.message ?? "Não foi possível enviar. Tente novamente.");
    } finally {
      setEnviando(false);
    }
  }

  if (protocolo !== null) {
    return (
      <Moldura>
        <div className="space-y-4 py-6 text-center">
          <CheckCircle2 className="mx-auto h-12 w-12 text-emerald-600" />
          <h2 className="text-xl font-semibold">Recebemos suas informações</h2>
          <p className="text-sm text-muted-foreground">
            Seu protocolo é <strong className="text-foreground">#{protocolo}</strong>. Nossa equipe vai
            analisar e entrar em contato pelos dados informados.
          </p>
          <Button
            variant="outline"
            onClick={() => {
              setProtocolo(null);
              setArquivos([]);
              setTelefone("");
              setProcesso("");
            }}
          >
            Enviar outro precatório
          </Button>
        </div>
      </Moldura>
    );
  }

  return (
    <Moldura>
      <form onSubmit={onSubmit} className="space-y-6">
        <Secao titulo="Seus dados">
          <Campo id="nome" label="Nome ou escritório" obrigatorio>
            <input id="nome" name="nome" className={inputClass} maxLength={160} required />
          </Campo>
          <div className="grid gap-4 sm:grid-cols-2">
            <Campo id="email" label="E-mail de contato" obrigatorio>
              <input id="email" name="email" type="email" className={inputClass} maxLength={160} required />
            </Campo>
            <Campo id="telefone" label="Telefone / WhatsApp" obrigatorio>
              <input id="telefone" name="telefone" className={inputClass} required
                inputMode="tel" autoComplete="tel" placeholder="(27) 99999-0000"
                value={telefone} onChange={(e) => setTelefone(maskTelefone(e.target.value))} />
            </Campo>
          </div>
        </Secao>

        <Secao titulo="Sobre o precatório">
          <div className="grid gap-4 sm:grid-cols-2">
            <Campo id="processo" label="Número do processo de execução">
              <input id="processo" name="processo" className={inputClass} maxLength={120}
                inputMode="numeric" placeholder="0000000-00.0000.0.00.0000"
                value={processo} onChange={(e) => setProcesso(maskProcesso(e.target.value))} />
            </Campo>
            <Campo id="referente_a" label="A quem se refere o crédito">
              <input id="referente_a" name="referente_a" className={inputClass} maxLength={200} />
            </Campo>
            <Campo id="credor_advogado" label="Credor / advogado">
              <input id="credor_advogado" name="credor_advogado" className={inputClass} maxLength={200} />
            </Campo>
            <Campo id="honorarios" label="Honorários">
              <input id="honorarios" name="honorarios" className={inputClass} maxLength={120}
                placeholder="Ex.: 30% ou R$ 10.000,00" />
            </Campo>
          </div>
        </Secao>

        <Secao titulo="Documentos">
          <div
            onDragOver={(e) => e.preventDefault()}
            onDrop={(e) => {
              e.preventDefault();
              adicionar(e.dataTransfer.files);
            }}
            className="rounded-lg border border-dashed p-6 text-center"
          >
            <FileUp className="mx-auto mb-2 h-6 w-6 text-muted-foreground" />
            <p className="text-sm">
              Arraste os arquivos aqui ou{" "}
              <button type="button" className="font-medium underline" onClick={() => fileRef.current?.click()}>
                escolha do seu computador
              </button>
            </p>
            <p className="mt-1 text-xs text-muted-foreground">
              PDF, imagens, Word e Excel · até {MAX_ARQUIVOS} arquivos, {MAX_MB_ARQUIVO} MB cada
            </p>
            <input ref={fileRef} type="file" name="arquivos" multiple accept={ACEITOS} className="hidden"
              onChange={(e) => adicionar(e.target.files)} />
          </div>

          {arquivos.length ? (
            <ul className="space-y-2">
              {arquivos.map((f, i) => (
                <li key={`${f.name}-${i}`} className="flex items-center gap-2 rounded-md border px-3 py-2 text-sm">
                  <Paperclip className="h-4 w-4 flex-shrink-0 text-muted-foreground" />
                  <span className="min-w-0 flex-1 truncate">{f.name}</span>
                  <span className="flex-shrink-0 text-xs text-muted-foreground">{mb(f.size)}</span>
                  <button type="button" aria-label={`Remover ${f.name}`}
                    className="rounded p-1 text-muted-foreground hover:bg-accent hover:text-foreground"
                    onClick={() => setArquivos(arquivos.filter((_, idx) => idx !== i))}>
                    <X className="h-4 w-4" />
                  </button>
                </li>
              ))}
              <li className="text-right text-xs text-muted-foreground">
                {arquivos.length} arquivo(s) · {mb(total)} de {MAX_MB_TOTAL} MB
              </li>
            </ul>
          ) : null}
        </Secao>

        <Secao titulo="Observações">
          <Campo id="observacoes" label="Algo que devamos saber">
            <textarea id="observacoes" name="observacoes" rows={4} className={textareaClass} maxLength={2000} />
          </Campo>
        </Secao>

        {erro ? <p className="rounded-md bg-red-50 px-3 py-2 text-sm text-red-700">{erro}</p> : null}

        <Button type="submit" className="w-full gap-2" disabled={enviando}>
          {enviando ? <Loader2 className="h-4 w-4 animate-spin" /> : null}
          {enviando ? "Enviando…" : "Enviar informações"}
        </Button>
        <p className="text-center text-xs text-muted-foreground">
          Os dados enviados são usados apenas para a análise do seu precatório pela equipe da Precatur.
        </p>
      </form>
    </Moldura>
  );
}

function Moldura({ children }: { children: React.ReactNode }) {
  return (
    <main className="min-h-screen bg-secondary/40 px-4 py-8 sm:py-12">
      <div className="mx-auto w-full max-w-2xl space-y-6">
        <header className="space-y-2 text-center">
          {/* eslint-disable-next-line @next/next/no-img-element */}
          <img src="/precatur-logo.png" alt="Precatur" className="mx-auto h-12 w-auto object-contain" />
          <h1 className="text-2xl font-semibold tracking-tight">Envie seu precatório para análise</h1>
          <p className="text-sm text-muted-foreground">
            Preencha os dados e anexe os documentos. Nossa equipe analisa e retorna com uma proposta.
          </p>
        </header>
        <div className="rounded-lg border bg-card p-5 shadow-sm sm:p-8">{children}</div>
      </div>
    </main>
  );
}

function Secao({ titulo, children }: { titulo: string; children: React.ReactNode }) {
  return (
    <section className="space-y-4">
      <h2 className="text-sm font-semibold uppercase tracking-wider text-muted-foreground">{titulo}</h2>
      {children}
    </section>
  );
}

function Campo({ id, label, obrigatorio, children }: {
  id: string; label: string; obrigatorio?: boolean; children: React.ReactNode;
}) {
  return (
    <div className="space-y-1.5">
      <label htmlFor={id} className="text-sm font-medium">
        {label}
        {obrigatorio ? <span className="text-red-600"> *</span> : null}
      </label>
      {children}
    </div>
  );
}
