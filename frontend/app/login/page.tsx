"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { login } from "@/lib/api";
import { setSession } from "@/lib/auth";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";

// Chave única do "Lembrar-me". Guarda e-mail + senha para pré-preencher o
// próximo login. Atenção: a senha fica em texto puro no navegador — só use em
// máquinas pessoais/confiáveis.
const REMEMBER_KEY = "precatur:remember";

export default function LoginPage() {
  const router = useRouter();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [remember, setRemember] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  // Ao abrir a tela, restaura as credenciais salvas (se o "Lembrar-me" estava
  // marcado da última vez).
  useEffect(() => {
    try {
      const raw = localStorage.getItem(REMEMBER_KEY);
      if (!raw) return;
      const saved = JSON.parse(raw) as { email?: string; password?: string };
      if (saved.email) setEmail(saved.email);
      if (saved.password) setPassword(saved.password);
      setRemember(true);
    } catch {
      /* dados corrompidos — ignora */
    }
  }, []);

  // Pede ao gerenciador de senhas do navegador para salvar as credenciais.
  // Necessário porque o login usa navegação client-side (router.push), e o
  // Chrome não dispara o prompt "salvar senha" sozinho em SPAs. Chromium-only;
  // Safari/Firefox salvam pelos atributos name/autocomplete do formulário.
  async function saveCredential(id: string, secret: string) {
    try {
      const PasswordCredential = (window as any).PasswordCredential;
      if (PasswordCredential && navigator.credentials?.store) {
        const cred = new PasswordCredential({ id, password: secret, name: id });
        await navigator.credentials.store(cred);
      }
    } catch {
      /* sem suporte ou usuário recusou — ignora silenciosamente */
    }
  }

  async function onSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    setLoading(true);
    try {
      const { token, user } = await login(email, password);
      setSession(token, user);
      // Persiste (ou limpa) as credenciais conforme o "Lembrar-me".
      if (remember) {
        localStorage.setItem(REMEMBER_KEY, JSON.stringify({ email, password }));
      } else {
        localStorage.removeItem(REMEMBER_KEY);
      }
      await saveCredential(email, password);
      router.push("/sales");
      router.refresh();
    } catch (err: any) {
      setError(err?.message ?? "Falha ao entrar.");
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="flex min-h-screen items-center justify-center bg-background px-4">
      <div className="w-full max-w-sm">
        <div className="mb-8 flex flex-col items-center text-center">
          {/* eslint-disable-next-line @next/next/no-img-element */}
          <img src="/precatur-logo.png" alt="Precatur" className="h-16 w-auto" />
          <p className="mt-4 text-sm text-muted-foreground">Entre para acessar o painel</p>
        </div>

        <Card>
          <CardContent className="p-6">
            <form onSubmit={onSubmit} className="space-y-4">
              <div className="space-y-1.5">
                <label htmlFor="email" className="text-sm font-medium">
                  E-mail
                </label>
                <input
                  id="email"
                  name="email"
                  type="email"
                  autoComplete="username"
                  placeholder="voce@precatur.com"
                  value={email}
                  onChange={(e) => setEmail(e.target.value)}
                  className="flex h-9 w-full rounded-md border border-input bg-transparent px-3 py-1 text-sm shadow-sm outline-none focus-visible:ring-1 focus-visible:ring-ring"
                  required
                />
              </div>

              <div className="space-y-1.5">
                <label htmlFor="password" className="text-sm font-medium">
                  Senha
                </label>
                <input
                  id="password"
                  name="password"
                  type="password"
                  autoComplete="current-password"
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  className="flex h-9 w-full rounded-md border border-input bg-transparent px-3 py-1 text-sm shadow-sm outline-none focus-visible:ring-1 focus-visible:ring-ring"
                  required
                />
              </div>

              <label htmlFor="remember" className="flex cursor-pointer items-center gap-2 text-sm text-muted-foreground">
                <input
                  id="remember"
                  type="checkbox"
                  checked={remember}
                  onChange={(e) => setRemember(e.target.checked)}
                  className="h-4 w-4 rounded border-input accent-primary"
                />
                Lembrar meu login e senha neste dispositivo
              </label>

              {error ? (
                <p className="rounded-md bg-secondary px-3 py-2 text-sm text-foreground">{error}</p>
              ) : null}

              <Button type="submit" className="w-full" disabled={loading}>
                {loading ? "Entrando…" : "Entrar"}
              </Button>
            </form>
          </CardContent>
        </Card>

        <p className="mt-6 text-center text-xs text-muted-foreground">
          App Precatur · Painel de vendas
        </p>
      </div>
    </div>
  );
}
