"use client";

import { useEffect, useState } from "react";
import { Trash2, UserPlus, Wand2, Eye, EyeOff, Copy, Check, Pencil, X } from "lucide-react";
import { api, type UserRecord } from "@/lib/api";
import { type Role } from "@/lib/auth";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { Button } from "@/components/ui/button";

const inputClass =
  "flex h-9 w-full rounded-md border border-input bg-transparent px-3 py-1 text-sm shadow-sm outline-none focus-visible:ring-1 focus-visible:ring-ring";

function fmtDate(iso: string): string {
  return new Date(iso).toLocaleDateString("pt-BR", { day: "2-digit", month: "2-digit", year: "numeric" });
}

// Data + hora do último acesso; "Nunca" quando o usuário ainda não logou.
function fmtLastLogin(iso: string | null): string {
  if (!iso) return "Nunca";
  return new Date(iso).toLocaleString("pt-BR", {
    day: "2-digit",
    month: "2-digit",
    year: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}

// Índice aleatório criptográfico (crypto.getRandomValues) — melhor que Math.random.
function randInt(max: number): number {
  const buf = new Uint32Array(1);
  crypto.getRandomValues(buf);
  return Math.floor((buf[0] / 2 ** 32) * max);
}

// Gera uma senha forte de 16 chars, sem caracteres ambíguos (0/O/1/l/I),
// garantindo ao menos 1 maiúscula, 1 minúscula, 1 dígito e 1 símbolo.
function generatePassword(length = 16): string {
  const upper = "ABCDEFGHJKLMNPQRSTUVWXYZ";
  const lower = "abcdefghijkmnpqrstuvwxyz";
  const digits = "23456789";
  const symbols = "!@#$%&*?-_=+";
  const all = upper + lower + digits + symbols;
  const pick = (set: string) => set[randInt(set.length)];
  const chars = [pick(upper), pick(lower), pick(digits), pick(symbols)];
  while (chars.length < length) chars.push(pick(all));
  // Embaralha (Fisher–Yates) para não fixar a posição dos obrigatórios.
  for (let i = chars.length - 1; i > 0; i--) {
    const j = randInt(i + 1);
    [chars[i], chars[j]] = [chars[j], chars[i]];
  }
  return chars.join("");
}

export default function UsersPage() {
  const [users, setUsers] = useState<UserRecord[]>([]);
  const [name, setName] = useState("");
  const [email, setEmail] = useState("");
  const [phone, setPhone] = useState("");
  const [password, setPassword] = useState("");
  const [role, setRole] = useState<Role>("padrao");
  const [showPass, setShowPass] = useState(false);
  const [copied, setCopied] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [ok, setOk] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  // Edição de telefone de um usuário (modal).
  const [editing, setEditing] = useState<UserRecord | null>(null);

  function handleGenerate() {
    setPassword(generatePassword());
    setShowPass(true); // revela para o admin poder copiar e repassar
    setCopied(false);
  }

  async function handleCopy() {
    if (!password) return;
    try {
      await navigator.clipboard.writeText(password);
      setCopied(true);
      setTimeout(() => setCopied(false), 1800);
    } catch {
      /* clipboard indisponível — ignora */
    }
  }

  function load() {
    api.users
      .list()
      .then(setUsers)
      .catch((e) => setError(e.message));
  }

  useEffect(load, []);

  async function onSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    setOk(null);
    setSaving(true);
    try {
      const created = await api.users.create({ name, email, password, role, phone });
      setOk(`Usuário ${created.name} criado.`);
      setName("");
      setEmail("");
      setPhone("");
      setPassword("");
      setRole("padrao");
      setShowPass(false);
      setCopied(false);
      load();
    } catch (e: any) {
      setError(e.message);
    } finally {
      setSaving(false);
    }
  }

  async function onDelete(u: UserRecord) {
    if (!confirm(`Excluir o usuário ${u.name}?`)) return;
    setError(null);
    try {
      await api.users.remove(u.id);
      load();
    } catch (e: any) {
      setError(e.message);
    }
  }

  return (
    <div className="mx-auto max-w-5xl space-y-6 p-4 sm:p-6 md:p-8">
      <header>
        <h1 className="text-2xl font-semibold tracking-tight">Usuários</h1>
        <p className="text-sm text-muted-foreground">Gerencie o acesso à plataforma.</p>
      </header>

      {/* Add user form */}
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <UserPlus className="h-4 w-4" />
            Adicionar usuário
          </CardTitle>
          <CardDescription>Defina o nível de acesso: admin ou padrão.</CardDescription>
        </CardHeader>
        <CardContent>
          <form onSubmit={onSubmit} className="space-y-4">
            <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
              <div className="space-y-1.5">
                <label htmlFor="u-name" className="text-sm font-medium">Nome</label>
                <input id="u-name" className={inputClass} value={name} onChange={(e) => setName(e.target.value)} required />
              </div>
              <div className="space-y-1.5">
                <label htmlFor="u-email" className="text-sm font-medium">E-mail</label>
                <input id="u-email" type="email" className={inputClass} value={email} onChange={(e) => setEmail(e.target.value)} required />
              </div>
              <div className="space-y-1.5">
                <label htmlFor="u-phone" className="text-sm font-medium">Telefone</label>
                <input id="u-phone" className={inputClass} value={phone} onChange={(e) => setPhone(e.target.value)} placeholder="(27) 99999-9999" required />
              </div>
              <div className="space-y-1.5">
                <div className="flex items-center justify-between">
                  <label htmlFor="u-pass" className="text-sm font-medium">Senha</label>
                  <button
                    type="button"
                    onClick={handleGenerate}
                    className="flex items-center gap-1 text-xs font-medium text-primary hover:underline"
                  >
                    <Wand2 className="h-3.5 w-3.5" />
                    Gerar senha segura
                  </button>
                </div>
                <div className="relative">
                  <input
                    id="u-pass"
                    type={showPass ? "text" : "password"}
                    className={inputClass + " pr-16 font-mono"}
                    value={password}
                    onChange={(e) => setPassword(e.target.value)}
                    minLength={4}
                    required
                  />
                  <div className="absolute inset-y-0 right-1 flex items-center gap-0.5">
                    <button
                      type="button"
                      onClick={() => setShowPass((v) => !v)}
                      className="rounded p-1 text-muted-foreground hover:text-foreground"
                      aria-label={showPass ? "Ocultar senha" : "Mostrar senha"}
                    >
                      {showPass ? <EyeOff className="h-4 w-4" /> : <Eye className="h-4 w-4" />}
                    </button>
                    <button
                      type="button"
                      onClick={handleCopy}
                      disabled={!password}
                      className="rounded p-1 text-muted-foreground hover:text-foreground disabled:opacity-40"
                      aria-label="Copiar senha"
                    >
                      {copied ? <Check className="h-4 w-4 text-green-600" /> : <Copy className="h-4 w-4" />}
                    </button>
                  </div>
                </div>
              </div>
              <div className="space-y-1.5">
                <label htmlFor="u-role" className="text-sm font-medium">Perfil</label>
                <select id="u-role" className={inputClass} value={role} onChange={(e) => setRole(e.target.value as Role)}>
                  <option value="padrao">Padrão</option>
                  <option value="admin">Admin</option>
                </select>
              </div>
            </div>

            {error ? <p className="rounded-md bg-secondary px-3 py-2 text-sm">{error}</p> : null}
            {ok ? <p className="rounded-md bg-secondary px-3 py-2 text-sm">{ok}</p> : null}

            <div className="flex justify-end">
              <Button type="submit" disabled={saving} className="gap-2">
                <UserPlus className="h-4 w-4" />
                {saving ? "Salvando…" : "Adicionar"}
              </Button>
            </div>
          </form>
        </CardContent>
      </Card>

      {/* User list */}
      <Card>
        <CardHeader>
          <CardTitle>Usuários cadastrados</CardTitle>
          <CardDescription>{users.length} usuário(s)</CardDescription>
        </CardHeader>
        <CardContent className="px-0">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Nome</TableHead>
                <TableHead>E-mail</TableHead>
                <TableHead className="hidden lg:table-cell">Telefone</TableHead>
                <TableHead>Perfil</TableHead>
                <TableHead className="hidden sm:table-cell">Último acesso</TableHead>
                <TableHead className="hidden md:table-cell">Criado em</TableHead>
                <TableHead className="text-right">Ações</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {users.map((u) => (
                <TableRow key={u.id}>
                  <TableCell className="font-medium">{u.name}</TableCell>
                  <TableCell className="text-muted-foreground">{u.email}</TableCell>
                  <TableCell className="hidden text-muted-foreground lg:table-cell">
                    {u.phone ? u.phone : <span className="italic opacity-70">—</span>}
                  </TableCell>
                  <TableCell>
                    <span
                      className={
                        "inline-flex rounded-full px-2 py-0.5 text-xs font-medium " +
                        (u.role === "admin"
                          ? "bg-primary text-primary-foreground"
                          : "bg-secondary text-secondary-foreground")
                      }
                    >
                      {u.role === "admin" ? "Admin" : "Padrão"}
                    </span>
                  </TableCell>
                  <TableCell className="hidden text-muted-foreground sm:table-cell">
                    {u.last_login_at ? (
                      fmtLastLogin(u.last_login_at)
                    ) : (
                      <span className="italic opacity-70">Nunca</span>
                    )}
                  </TableCell>
                  <TableCell className="hidden text-muted-foreground md:table-cell">{fmtDate(u.created_at)}</TableCell>
                  <TableCell className="text-right">
                    <Button variant="ghost" size="icon" onClick={() => setEditing(u)} aria-label={`Editar telefone de ${u.name}`}>
                      <Pencil className="h-4 w-4" />
                    </Button>
                    <Button variant="ghost" size="icon" onClick={() => onDelete(u)} aria-label={`Excluir ${u.name}`}>
                      <Trash2 className="h-4 w-4" />
                    </Button>
                  </TableCell>
                </TableRow>
              ))}
              {!users.length ? (
                <TableRow>
                  <TableCell colSpan={7} className="py-10 text-center text-muted-foreground">
                    Nenhum usuário ainda.
                  </TableCell>
                </TableRow>
              ) : null}
            </TableBody>
          </Table>
        </CardContent>
      </Card>

      {editing ? (
        <EditPhoneModal
          user={editing}
          onClose={() => setEditing(null)}
          onSaved={() => {
            setEditing(null);
            load();
          }}
        />
      ) : null}
    </div>
  );
}

function EditPhoneModal({
  user,
  onClose,
  onSaved,
}: {
  user: UserRecord;
  onClose: () => void;
  onSaved: () => void;
}) {
  const [phone, setPhone] = useState(user.phone ?? "");
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  async function onSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    if (!phone.trim()) {
      setError("Informe o telefone.");
      return;
    }
    setSaving(true);
    try {
      await api.users.update(user.id, { phone: phone.trim() });
      onSaved();
    } catch (e: any) {
      setError(e.message);
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4" onClick={onClose}>
      <div className="w-full max-w-sm rounded-lg border bg-card p-6 shadow-lg" onClick={(e) => e.stopPropagation()}>
        <div className="mb-4 flex items-center justify-between">
          <h2 className="flex items-center gap-2 text-lg font-semibold">
            <Pencil className="h-5 w-5" />
            Telefone de {user.name}
          </h2>
          <button onClick={onClose} className="rounded-md p-1 text-muted-foreground hover:bg-accent hover:text-foreground" aria-label="Fechar">
            <X className="h-4 w-4" />
          </button>
        </div>
        <form onSubmit={onSubmit} className="space-y-4">
          <div className="space-y-1.5">
            <label className="text-sm font-medium">Telefone</label>
            <input
              className={inputClass}
              value={phone}
              onChange={(e) => setPhone(e.target.value)}
              placeholder="(27) 99999-9999"
              autoFocus
              required
            />
          </div>
          {error ? <p className="rounded-md bg-secondary px-3 py-2 text-sm">{error}</p> : null}
          <div className="flex justify-end gap-2 pt-1">
            <Button type="button" variant="outline" onClick={onClose}>
              Cancelar
            </Button>
            <Button type="submit" disabled={saving}>
              {saving ? "Salvando…" : "Salvar"}
            </Button>
          </div>
        </form>
      </div>
    </div>
  );
}
