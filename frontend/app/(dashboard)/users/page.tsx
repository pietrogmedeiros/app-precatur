"use client";

import { useEffect, useState } from "react";
import { Trash2, UserPlus } from "lucide-react";
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

export default function UsersPage() {
  const [users, setUsers] = useState<UserRecord[]>([]);
  const [name, setName] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [role, setRole] = useState<Role>("padrao");
  const [error, setError] = useState<string | null>(null);
  const [ok, setOk] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

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
      const created = await api.users.create({ name, email, password, role });
      setOk(`Usuário ${created.name} criado.`);
      setName("");
      setEmail("");
      setPassword("");
      setRole("padrao");
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
                <label htmlFor="u-pass" className="text-sm font-medium">Senha</label>
                <input id="u-pass" type="password" className={inputClass} value={password} onChange={(e) => setPassword(e.target.value)} minLength={4} required />
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
                <TableHead>Perfil</TableHead>
                <TableHead className="hidden sm:table-cell">Criado em</TableHead>
                <TableHead className="text-right">Ações</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {users.map((u) => (
                <TableRow key={u.id}>
                  <TableCell className="font-medium">{u.name}</TableCell>
                  <TableCell className="text-muted-foreground">{u.email}</TableCell>
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
                  <TableCell className="hidden text-muted-foreground sm:table-cell">{fmtDate(u.created_at)}</TableCell>
                  <TableCell className="text-right">
                    <Button variant="ghost" size="icon" onClick={() => onDelete(u)} aria-label={`Excluir ${u.name}`}>
                      <Trash2 className="h-4 w-4" />
                    </Button>
                  </TableCell>
                </TableRow>
              ))}
              {!users.length ? (
                <TableRow>
                  <TableCell colSpan={5} className="py-10 text-center text-muted-foreground">
                    Nenhum usuário ainda.
                  </TableCell>
                </TableRow>
              ) : null}
            </TableBody>
          </Table>
        </CardContent>
      </Card>
    </div>
  );
}
