"use client";

import { useEffect, useRef, useState } from "react";
import { Camera, KeyRound, Loader2, Trash2, UserRound } from "lucide-react";
import { api, type Me } from "@/lib/api";
import { patchSessionUser, roleLabel } from "@/lib/auth";
import { maskTelefone } from "@/lib/masks";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";

const inputClass =
  "flex h-10 w-full rounded-md border border-input bg-background px-3 py-1 text-sm shadow-sm outline-none focus-visible:ring-2 focus-visible:ring-ring";

const LADO = 256; // foto guardada quadrada, suficiente para o menu e a tela

// Reduz e corta a imagem no navegador antes de enviar: o arquivo da câmera de um
// celular tem vários MB, e o que precisamos cabe em dezenas de KB.
function preparaFoto(arquivo: File): Promise<string> {
  return new Promise((resolve, reject) => {
    const leitor = new FileReader();
    leitor.onerror = () => reject(new Error("Não foi possível ler a imagem."));
    leitor.onload = () => {
      const img = new Image();
      img.onerror = () => reject(new Error("Arquivo de imagem inválido."));
      img.onload = () => {
        const lado = Math.min(img.width, img.height);
        const canvas = document.createElement("canvas");
        canvas.width = LADO;
        canvas.height = LADO;
        const ctx = canvas.getContext("2d");
        if (!ctx) return reject(new Error("Não foi possível processar a imagem."));
        ctx.drawImage(img, (img.width - lado) / 2, (img.height - lado) / 2, lado, lado, 0, 0, LADO, LADO);
        resolve(canvas.toDataURL("image/jpeg", 0.85));
      };
      img.src = String(leitor.result);
    };
    leitor.readAsDataURL(arquivo);
  });
}

function iniciais(nome: string): string {
  return nome.split(" ").filter(Boolean).slice(0, 2).map((p) => p[0]?.toUpperCase()).join("");
}

function fmtData(iso: string | null): string {
  if (!iso) return "—";
  const d = new Date(iso);
  return `${d.toLocaleDateString("pt-BR")} às ${d.toLocaleTimeString("pt-BR", { hour: "2-digit", minute: "2-digit" })}`;
}

export default function PerfilPage() {
  const [me, setMe] = useState<Me | null>(null);
  const [nome, setNome] = useState("");
  const [telefone, setTelefone] = useState("");
  const [carregando, setCarregando] = useState(true);
  const [salvando, setSalvando] = useState(false);
  const [erro, setErro] = useState<string | null>(null);
  const [ok, setOk] = useState<string | null>(null);
  const fotoRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    api
      .me()
      .then((m) => {
        setMe(m);
        setNome(m.name);
        setTelefone(m.phone ?? "");
      })
      .catch((e) => setErro(e.message))
      .finally(() => setCarregando(false));
  }, []);

  // Um único ponto de gravação: a tela toda usa isto e atualiza o menu lateral
  // na mesma hora, sem exigir novo login.
  async function salvar(dados: Parameters<typeof api.updateProfile>[0], mensagem: string) {
    setErro(null);
    setOk(null);
    setSalvando(true);
    try {
      const m = await api.updateProfile(dados);
      setMe(m);
      setNome(m.name);
      setTelefone(m.phone ?? "");
      patchSessionUser({ name: m.name, phone: m.phone, avatar: m.avatar ?? null });
      window.dispatchEvent(new Event("perfil-atualizado"));
      setOk(mensagem);
    } catch (e: any) {
      setErro(e.message);
    } finally {
      setSalvando(false);
    }
  }

  async function escolheFoto(arquivo: File) {
    setErro(null);
    try {
      await salvar({ avatar: await preparaFoto(arquivo) }, "Foto atualizada.");
    } catch (e: any) {
      setErro(e.message);
    } finally {
      if (fotoRef.current) fotoRef.current.value = "";
    }
  }

  if (carregando) return <p className="p-8 text-center text-sm text-muted-foreground">Carregando…</p>;
  if (!me) return <p className="p-8 text-center text-sm text-red-600">{erro ?? "Não foi possível carregar o perfil."}</p>;

  return (
    <div className="mx-auto max-w-3xl space-y-6 p-4 sm:p-6 md:p-8">
      <header>
        <h1 className="flex items-center gap-2 text-2xl font-semibold tracking-tight">
          <UserRound className="h-6 w-6" />
          Meu perfil
        </h1>
        <p className="text-sm text-muted-foreground">Seus dados, sua foto e sua senha.</p>
      </header>

      {erro ? <p className="rounded-md bg-secondary px-3 py-2 text-sm text-red-600">{erro}</p> : null}
      {ok ? <p className="rounded-md bg-secondary px-3 py-2 text-sm text-green-700">{ok}</p> : null}

      <Card>
        <CardHeader>
          <CardTitle>Foto</CardTitle>
          <CardDescription>Aparece no menu e ajuda o time a reconhecer quem fez cada ação.</CardDescription>
        </CardHeader>
        <CardContent className="flex flex-wrap items-center gap-5">
          <div className="flex h-24 w-24 flex-shrink-0 items-center justify-center overflow-hidden rounded-full bg-secondary text-xl font-semibold">
            {me.avatar ? (
              // eslint-disable-next-line @next/next/no-img-element
              <img src={me.avatar} alt="" className="h-full w-full object-cover" />
            ) : (
              iniciais(me.name)
            )}
          </div>
          <div className="space-y-2">
            <input ref={fotoRef} type="file" accept="image/jpeg,image/png,image/webp" className="hidden"
              onChange={(e) => e.target.files?.[0] && escolheFoto(e.target.files[0])} />
            <div className="flex flex-wrap gap-2">
              <Button variant="outline" className="gap-2" disabled={salvando} onClick={() => fotoRef.current?.click()}>
                <Camera className="h-4 w-4" />
                {me.avatar ? "Trocar foto" : "Escolher foto"}
              </Button>
              {me.avatar ? (
                <Button variant="ghost" className="gap-2 text-red-600" disabled={salvando}
                  onClick={() => salvar({ removerAvatar: true }, "Foto removida.")}>
                  <Trash2 className="h-4 w-4" />
                  Remover
                </Button>
              ) : null}
            </div>
            <p className="text-xs text-muted-foreground">
              JPEG, PNG ou WebP. A imagem é recortada em quadrado e reduzida automaticamente.
            </p>
          </div>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>Dados</CardTitle>
          <CardDescription>O e-mail é sua credencial de acesso e o perfil é definido pela administração.</CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="grid gap-4 sm:grid-cols-2">
            <label className="block space-y-1.5 text-sm font-medium">
              <span>Nome</span>
              <input className={inputClass} value={nome} maxLength={120} onChange={(e) => setNome(e.target.value)} />
            </label>
            <label className="block space-y-1.5 text-sm font-medium">
              <span>Telefone / WhatsApp</span>
              <input className={inputClass} inputMode="tel" value={telefone} placeholder="(27) 99999-0000"
                onChange={(e) => setTelefone(maskTelefone(e.target.value))} />
              <span className="block text-xs font-normal text-muted-foreground">
                Usado como contato do responsável no rodapé das propostas.
              </span>
            </label>
            <Campo rotulo="E-mail" valor={me.email} />
            <Campo rotulo="Perfil de acesso" valor={roleLabel(me.role)} />
          </div>

          <div className="flex justify-end">
            <Button disabled={salvando || (nome.trim() === me.name && telefone === (me.phone ?? ""))}
              onClick={() => salvar({ name: nome.trim(), phone: telefone }, "Dados atualizados.")}>
              {salvando ? "Salvando…" : "Salvar alterações"}
            </Button>
          </div>

          <div className="grid gap-2 border-t pt-4 text-xs text-muted-foreground sm:grid-cols-2">
            <span>Conta criada em {fmtData(me.created_at ?? null)}</span>
            <span>Último acesso em {fmtData(me.last_login_at ?? null)}</span>
          </div>
        </CardContent>
      </Card>

      <TrocarSenha />
    </div>
  );
}

function Campo({ rotulo, valor }: { rotulo: string; valor: string }) {
  return (
    <div className="space-y-1.5">
      <span className="text-sm font-medium">{rotulo}</span>
      <div className={`${inputClass} flex items-center bg-secondary/60 text-muted-foreground`}>{valor}</div>
    </div>
  );
}

function TrocarSenha() {
  const [atual, setAtual] = useState("");
  const [nova, setNova] = useState("");
  const [confirma, setConfirma] = useState("");
  const [salvando, setSalvando] = useState(false);
  const [erro, setErro] = useState<string | null>(null);
  const [ok, setOk] = useState<string | null>(null);

  async function enviar(e: React.FormEvent) {
    e.preventDefault();
    setErro(null);
    setOk(null);
    if (nova.length < 4) return setErro("A nova senha deve ter ao menos 4 caracteres.");
    if (nova !== confirma) return setErro("A confirmação não confere com a nova senha.");
    setSalvando(true);
    try {
      await api.changePassword(atual, nova);
      setOk("Senha alterada.");
      setAtual("");
      setNova("");
      setConfirma("");
    } catch (e: any) {
      setErro(e.message);
    } finally {
      setSalvando(false);
    }
  }

  return (
    <Card id="senha">
      <CardHeader>
        <CardTitle className="flex items-center gap-2">
          <KeyRound className="h-5 w-5" />
          Senha
        </CardTitle>
        <CardDescription>Para trocar, confirme a senha atual.</CardDescription>
      </CardHeader>
      <CardContent>
        <form onSubmit={enviar} className="space-y-4">
          <div className="grid gap-4 sm:grid-cols-3">
            <label className="block space-y-1.5 text-sm font-medium">
              <span>Senha atual</span>
              <input type="password" className={inputClass} value={atual} autoComplete="current-password"
                onChange={(e) => setAtual(e.target.value)} required />
            </label>
            <label className="block space-y-1.5 text-sm font-medium">
              <span>Nova senha</span>
              <input type="password" className={inputClass} value={nova} autoComplete="new-password"
                onChange={(e) => setNova(e.target.value)} required />
            </label>
            <label className="block space-y-1.5 text-sm font-medium">
              <span>Repita a nova senha</span>
              <input type="password" className={inputClass} value={confirma} autoComplete="new-password"
                onChange={(e) => setConfirma(e.target.value)} required />
            </label>
          </div>
          {erro ? <p className="rounded-md bg-secondary px-3 py-2 text-sm text-red-600">{erro}</p> : null}
          {ok ? <p className="rounded-md bg-secondary px-3 py-2 text-sm text-green-700">{ok}</p> : null}
          <div className="flex justify-end">
            <Button type="submit" disabled={salvando}>
              {salvando ? <Loader2 className="h-4 w-4 animate-spin" /> : null}
              {salvando ? "Alterando…" : "Alterar senha"}
            </Button>
          </div>
        </form>
      </CardContent>
    </Card>
  );
}
