"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { BarChart3, Users, ChevronLeft, ChevronRight, LogOut, Menu, X, UserCog, FileText, KeyRound } from "lucide-react";
import { cn } from "@/lib/utils";
import { clearSession, getUser, type SessionUser } from "@/lib/auth";
import { Button } from "@/components/ui/button";
import { ChangePasswordModal } from "@/components/change-password-modal";

const DASHBOARD_NAV = [
  { href: "/sales", label: "Dados Sales", icon: BarChart3 },
];

const PROPOSAL_NAV = [{ href: "/proposta", label: "Gerar Proposta", icon: FileText }];

const ADMIN_NAV = [{ href: "/users", label: "Usuários", icon: UserCog }];

function initials(name: string): string {
  return name
    .split(" ")
    .filter(Boolean)
    .slice(0, 2)
    .map((p) => p[0]?.toUpperCase())
    .join("");
}

export function DashboardShell({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  const router = useRouter();
  const [collapsed, setCollapsed] = useState(false);
  const [mobileOpen, setMobileOpen] = useState(false);
  const [pwOpen, setPwOpen] = useState(false);
  const [user, setUser] = useState<SessionUser | null>(null);

  // Restore collapse preference and session user (client only).
  useEffect(() => {
    setCollapsed(localStorage.getItem("sidebar:collapsed") === "1");
    setUser(getUser());
  }, []);

  const isAdmin = user?.role === "admin";

  function toggleCollapsed() {
    setCollapsed((v) => {
      const next = !v;
      localStorage.setItem("sidebar:collapsed", next ? "1" : "0");
      return next;
    });
  }

  // Close the mobile drawer whenever the route changes.
  useEffect(() => {
    setMobileOpen(false);
  }, [pathname]);

  function logout() {
    clearSession();
    router.push("/login");
    router.refresh();
  }

  return (
    <div className="flex min-h-screen">
      {/* Mobile backdrop */}
      {mobileOpen ? (
        <div
          className="no-print fixed inset-0 z-30 bg-black/40 md:hidden"
          onClick={() => setMobileOpen(false)}
        />
      ) : null}

      {/* Sidebar */}
      <aside
        className={cn(
          "no-print",
          "z-40 flex flex-col border-r bg-card transition-all duration-200",
          "fixed inset-y-0 left-0 md:sticky md:top-0 md:h-screen md:translate-x-0",
          collapsed ? "md:w-[74px]" : "md:w-64",
          "w-64",
          mobileOpen ? "translate-x-0" : "-translate-x-full"
        )}
      >
        {/* Collapse toggle — floating circle on the sidebar's right edge (desktop only) */}
        <button
          onClick={toggleCollapsed}
          aria-label={collapsed ? "Expandir menu" : "Recolher menu"}
          className="absolute top-14 -right-3.5 z-50 hidden h-7 w-7 items-center justify-center rounded-full border bg-background text-muted-foreground shadow-sm transition-colors hover:bg-accent hover:text-foreground md:flex"
        >
          {collapsed ? <ChevronRight className="h-4 w-4" /> : <ChevronLeft className="h-4 w-4" />}
        </button>

        {/* Brand */}
        <div className="flex h-16 items-center gap-3 border-b px-4">
          {/* eslint-disable-next-line @next/next/no-img-element */}
          <img
            src="/precatur-shield.png"
            alt="Precatur"
            className="h-9 w-9 flex-shrink-0 object-contain"
          />
          {!collapsed ? (
            <span className="truncate text-[15px] font-semibold tracking-tight">App Precatur</span>
          ) : null}
          <button
            className="ml-auto rounded-md p-1.5 text-muted-foreground hover:bg-accent md:hidden"
            onClick={() => setMobileOpen(false)}
            aria-label="Fechar menu"
          >
            <X className="h-4 w-4" />
          </button>
        </div>

        {/* Nav */}
        <nav className="flex-1 space-y-1 overflow-y-auto p-3">
          <NavGroup title="Dashboard" items={DASHBOARD_NAV} collapsed={collapsed} pathname={pathname} />
          <NavGroup title="Proposta" items={PROPOSAL_NAV} collapsed={collapsed} pathname={pathname} />
          {isAdmin ? (
            <NavGroup
              title="Administração"
              items={ADMIN_NAV}
              collapsed={collapsed}
              pathname={pathname}
            />
          ) : null}

          {/* Meu Acesso — ações pessoais, disponíveis a qualquer usuário */}
          <div className="pb-1">
            <p
              className={cn(
                "px-3 pb-1 pt-3 text-xs font-semibold uppercase tracking-wider text-muted-foreground",
                collapsed && "md:sr-only"
              )}
            >
              Meu Acesso
            </p>
            <NavAction
              label="Trocar senha"
              icon={KeyRound}
              collapsed={collapsed}
              onClick={() => {
                setPwOpen(true);
                setMobileOpen(false);
              }}
            />
          </div>
        </nav>

        {/* Sair — fixado no rodapé do menu (nav é flex-1 e empurra pra baixo) */}
        <div className="border-t p-3">
          <NavAction label="Sair" icon={LogOut} collapsed={collapsed} onClick={logout} />
        </div>

        <div
          className={cn(
            "p-4 text-xs text-muted-foreground",
            collapsed && "md:hidden"
          )}
        >
          App Precatur · v1.0
        </div>
      </aside>

      {/* Main column */}
      <div className="flex min-w-0 flex-1 flex-col">
        {/* Header */}
        <header className="no-print sticky top-0 z-20 flex h-16 items-center gap-2 border-b bg-background/80 px-4 backdrop-blur md:px-6">
          <Button
            variant="ghost"
            size="icon"
            className="md:hidden"
            onClick={() => setMobileOpen(true)}
            aria-label="Abrir menu"
          >
            <Menu className="h-5 w-5" />
          </Button>

          <div className="ml-auto flex items-center gap-2">
            <div className="flex h-8 w-8 items-center justify-center rounded-full bg-secondary text-xs font-semibold">
              {user ? initials(user.name) : "…"}
            </div>
            <div className="hidden leading-tight sm:block">
              <div className="text-sm font-medium">{user?.name ?? ""}</div>
              <div className="text-[11px] capitalize text-muted-foreground">{user?.role ?? ""}</div>
            </div>
          </div>
        </header>

        <main className="flex-1">{children}</main>
      </div>

      <ChangePasswordModal open={pwOpen} onClose={() => setPwOpen(false)} />
    </div>
  );
}

// Item de menu que dispara uma ação (não navega), com o mesmo visual do NavGroup.
function NavAction({
  label,
  icon: Icon,
  collapsed,
  onClick,
}: {
  label: string;
  icon: typeof Users;
  collapsed: boolean;
  onClick: () => void;
}) {
  return (
    <button
      onClick={onClick}
      title={collapsed ? label : undefined}
      className={cn(
        "mb-1 flex w-full items-center gap-3 rounded-md px-3 py-2 text-sm font-medium transition-colors",
        "text-muted-foreground hover:bg-accent hover:text-accent-foreground",
        collapsed && "md:justify-center md:px-0"
      )}
    >
      <Icon className="h-4 w-4 flex-shrink-0" />
      <span className={cn(collapsed && "md:hidden")}>{label}</span>
    </button>
  );
}

function NavGroup({
  title,
  items,
  collapsed,
  pathname,
}: {
  title: string;
  items: { href: string; label: string; icon: typeof Users }[];
  collapsed: boolean;
  pathname: string;
}) {
  return (
    <div className="pb-1">
      <p
        className={cn(
          "px-3 pb-1 pt-3 text-xs font-semibold uppercase tracking-wider text-muted-foreground",
          collapsed && "md:sr-only"
        )}
      >
        {title}
      </p>
      {items.map(({ href, label, icon: Icon }) => {
        const active = pathname === href || pathname.startsWith(href + "/");
        return (
          <Link
            key={href}
            href={href}
            title={collapsed ? label : undefined}
            className={cn(
              "mb-1 flex items-center gap-3 rounded-md px-3 py-2 text-sm font-medium transition-colors",
              collapsed && "md:justify-center md:px-0",
              active
                ? "bg-primary text-primary-foreground"
                : "text-muted-foreground hover:bg-accent hover:text-accent-foreground"
            )}
          >
            <Icon className="h-4 w-4 flex-shrink-0" />
            <span className={cn(collapsed && "md:hidden")}>{label}</span>
          </Link>
        );
      })}
    </div>
  );
}
