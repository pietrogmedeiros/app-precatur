import { NextResponse } from "next/server";
import type { NextRequest } from "next/server";

// Protect every route except /login. Auth state is the presence of the `token`
// cookie (set client-side after a successful login).
export function middleware(req: NextRequest) {
  const token = req.cookies.get("token")?.value;
  const role = req.cookies.get("role")?.value;
  const { pathname } = req.nextUrl;
  const isLogin = pathname === "/login";

  if (!token && !isLogin) {
    const url = req.nextUrl.clone();
    url.pathname = "/login";
    return NextResponse.redirect(url);
  }

  if (token && isLogin) {
    const url = req.nextUrl.clone();
    url.pathname = "/sales";
    return NextResponse.redirect(url);
  }

  // /users is admin-only (backend also enforces this).
  if (token && pathname.startsWith("/users") && role !== "admin") {
    const url = req.nextUrl.clone();
    url.pathname = "/sales";
    return NextResponse.redirect(url);
  }

  return NextResponse.next();
}

export const config = {
  // Skip Next internals, static assets, and the /api proxy (auth is enforced by
  // the backend on those routes — the middleware must not redirect them).
  matcher: ["/((?!api|_next/static|_next/image|favicon.ico|.*\\.(?:svg|png|jpg|jpeg|gif|webp|ico)$).*)"],
};
