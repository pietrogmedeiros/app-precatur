// Client-side auth/session helpers. The JWT goes in a cookie so Next middleware
// can gate routes; the role is mirrored in a cookie for admin-route redirects,
// and the user profile is kept in localStorage for the UI.

const TOKEN = "token";
const ROLE = "role";
const USER = "precatur:user";

export type Role = "admin" | "padrao";

export interface SessionUser {
  name: string;
  email: string;
  role: Role;
}

function readCookie(name: string): string | null {
  if (typeof document === "undefined") return null;
  const m = document.cookie.match(new RegExp(`(?:^|; )${name}=([^;]*)`));
  return m ? decodeURIComponent(m[1]) : null;
}

function writeCookie(name: string, value: string, maxAge: number) {
  document.cookie = `${name}=${encodeURIComponent(value)}; path=/; max-age=${maxAge}; samesite=lax`;
}

function deleteCookie(name: string) {
  document.cookie = `${name}=; path=/; max-age=0; samesite=lax`;
}

export function getToken(): string | null {
  return readCookie(TOKEN);
}

export function setSession(token: string, user: SessionUser): void {
  const maxAge = 12 * 60 * 60; // matches backend token TTL
  writeCookie(TOKEN, token, maxAge);
  writeCookie(ROLE, user.role, maxAge);
  if (typeof localStorage !== "undefined") {
    localStorage.setItem(USER, JSON.stringify(user));
  }
}

export function clearSession(): void {
  deleteCookie(TOKEN);
  deleteCookie(ROLE);
  if (typeof localStorage !== "undefined") localStorage.removeItem(USER);
}

export function getUser(): SessionUser | null {
  if (typeof localStorage === "undefined") return null;
  const raw = localStorage.getItem(USER);
  if (!raw) return null;
  try {
    return JSON.parse(raw) as SessionUser;
  } catch {
    return null;
  }
}

export function isAdmin(): boolean {
  return (getUser()?.role ?? readCookie(ROLE)) === "admin";
}
