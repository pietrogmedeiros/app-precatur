"use client";

import { useState } from "react";
import Link from "next/link";
import { ArrowLeft, Loader2, MailCheck } from "lucide-react";
import { esqueciSenha } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { AuthMoldura as Moldura } from "@/components/auth-moldura";

const inputClass =
  "flex h-10 w-full rounded-md border border-input bg-background px-3 py-1 text-sm shadow-sm outline-none focus-visible:ring-2 focus-visible:ring-ring";

export default function RecuperarPage() {
  const [email, setEmail] = useState("");
  const [enviado, setEnviado] = useState(false);
  const [carregando, setCarregando] = useState(false);
  const [erro, setErro] = useState<string | null>(null);

  async function enviar(e: React.FormEvent) {
    e.preventDefault();
    setErro(null);
    setCarregando(true);
    try {
      await esqueciSenha(email.trim());
      setEnviado(true);
    } catch (e: any) {
      setErro(e.message);
    } finally {
      setCarregando(false);
    }
  }

  return (
    <Moldura>
      {enviado ? (
        <div className="space-y-4 text-center">
          <MailCheck className="mx-auto h-11 w-11 text-emerald-600" />
          <h1 className="text-xl font-semibold">Verifique seu e-mail</h1>
          <p className="text-sm text-muted-foreground">
            Se existir uma conta com <strong className="text-foreground">{email.trim()}</strong>, enviamos
            um link para criar uma nova senha. Ele vale por 1 hora.
          </p>
          <p className="text-xs text-muted-foreground">
            Não chegou? Confira a caixa de spam ou tente de novo em alguns minutos.
          </p>
          <Link href="/login" className="inline-flex items-center gap-1.5 text-sm font-medium underline">
            <ArrowLeft className="h-4 w-4" />
            Voltar para o login
          </Link>
        </div>
      ) : (
        <form onSubmit={enviar} className="space-y-5">
          <div className="space-y-1 text-center">
            <h1 className="text-xl font-semibold">Esqueci minha senha</h1>
            <p className="text-sm text-muted-foreground">
              Informe seu e-mail e enviaremos um link para criar uma nova senha.
            </p>
          </div>
          <label className="block space-y-1.5">
            <span className="text-sm font-medium">E-mail</span>
            <input id="email" type="email" className={inputClass} value={email} required autoFocus
              autoComplete="email" onChange={(e) => setEmail(e.target.value)} />
          </label>
          {erro ? <p className="rounded-md bg-red-50 px-3 py-2 text-sm text-red-700">{erro}</p> : null}
          <Button type="submit" className="w-full gap-2" disabled={carregando}>
            {carregando ? <Loader2 className="h-4 w-4 animate-spin" /> : null}
            {carregando ? "Enviando…" : "Enviar link de redefinição"}
          </Button>
          <Link href="/login" className="flex items-center justify-center gap-1.5 text-sm text-muted-foreground underline">
            <ArrowLeft className="h-4 w-4" />
            Voltar para o login
          </Link>
        </form>
      )}
    </Moldura>
  );
}
