"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { ArrowLeft, CheckCircle2, Loader2, ShieldAlert } from "lucide-react";
import { conferirTokenSenha, redefinirSenha } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { AuthMoldura as Moldura } from "@/components/auth-moldura";

const inputClass =
  "flex h-10 w-full rounded-md border border-input bg-background px-3 py-1 text-sm shadow-sm outline-none focus-visible:ring-2 focus-visible:ring-ring";

export default function RedefinirPage() {
  const [token, setToken] = useState("");
  const [estado, setEstado] = useState<"conferindo" | "valido" | "invalido" | "pronto">("conferindo");
  const [senha, setSenha] = useState("");
  const [confirma, setConfirma] = useState("");
  const [erro, setErro] = useState<string | null>(null);
  const [salvando, setSalvando] = useState(false);

  // O link é conferido ao abrir, sem gastar o token: melhor avisar que expirou
  // do que deixar a pessoa digitar a senha para só então recusar.
  useEffect(() => {
    const t = new URLSearchParams(window.location.search).get("token") ?? "";
    setToken(t);
    if (!t) return setEstado("invalido");
    conferirTokenSenha(t)
      .then((r) => setEstado(r.valido ? "valido" : "invalido"))
      .catch(() => setEstado("invalido"));
  }, []);

  async function enviar(e: React.FormEvent) {
    e.preventDefault();
    setErro(null);
    if (senha.length < 4) return setErro("A senha deve ter ao menos 4 caracteres.");
    if (senha !== confirma) return setErro("A confirmação não confere com a nova senha.");
    setSalvando(true);
    try {
      await redefinirSenha(token, senha);
      setEstado("pronto");
    } catch (e: any) {
      setErro(e.message);
    } finally {
      setSalvando(false);
    }
  }

  if (estado === "conferindo") {
    return <Moldura><p className="py-6 text-center text-sm text-muted-foreground">Conferindo o link…</p></Moldura>;
  }

  if (estado === "invalido") {
    return (
      <Moldura>
        <div className="space-y-4 text-center">
          <ShieldAlert className="mx-auto h-11 w-11 text-amber-600" />
          <h1 className="text-xl font-semibold">Link expirado ou já usado</h1>
          <p className="text-sm text-muted-foreground">
            Cada link vale por 1 hora e só pode ser usado uma vez. Peça um novo para continuar.
          </p>
          <Link href="/recuperar" className="inline-block text-sm font-medium underline">
            Pedir um novo link
          </Link>
        </div>
      </Moldura>
    );
  }

  if (estado === "pronto") {
    return (
      <Moldura>
        <div className="space-y-4 text-center">
          <CheckCircle2 className="mx-auto h-11 w-11 text-emerald-600" />
          <h1 className="text-xl font-semibold">Senha alterada</h1>
          <p className="text-sm text-muted-foreground">Já pode entrar com a nova senha.</p>
          <Link href="/login" className="inline-block">
            <Button className="gap-2">Ir para o login</Button>
          </Link>
        </div>
      </Moldura>
    );
  }

  return (
    <Moldura>
      <form onSubmit={enviar} className="space-y-5">
        <div className="space-y-1 text-center">
          <h1 className="text-xl font-semibold">Criar nova senha</h1>
          <p className="text-sm text-muted-foreground">Escolha uma senha que você não use em outro lugar.</p>
        </div>
        <label className="block space-y-1.5">
          <span className="text-sm font-medium">Nova senha</span>
          <input type="password" className={inputClass} value={senha} required autoFocus
            autoComplete="new-password" onChange={(e) => setSenha(e.target.value)} />
        </label>
        <label className="block space-y-1.5">
          <span className="text-sm font-medium">Repita a nova senha</span>
          <input type="password" className={inputClass} value={confirma} required
            autoComplete="new-password" onChange={(e) => setConfirma(e.target.value)} />
        </label>
        {erro ? <p className="rounded-md bg-red-50 px-3 py-2 text-sm text-red-700">{erro}</p> : null}
        <Button type="submit" className="w-full gap-2" disabled={salvando}>
          {salvando ? <Loader2 className="h-4 w-4 animate-spin" /> : null}
          {salvando ? "Salvando…" : "Salvar nova senha"}
        </Button>
        <Link href="/login" className="flex items-center justify-center gap-1.5 text-sm text-muted-foreground underline">
          <ArrowLeft className="h-4 w-4" />
          Voltar para o login
        </Link>
      </form>
    </Moldura>
  );
}
