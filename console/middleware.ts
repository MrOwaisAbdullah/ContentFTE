// Preserves the intended destination when an unauthenticated request is
// redirected to /login (UX-17). Edge runtime: only checks cookie presence;
// real verification still happens server-side in requireSession().
import { NextResponse } from "next/server";
import type { NextRequest } from "next/server";

const COOKIE = "console_session";

export function middleware(req: NextRequest) {
  const { pathname } = req.nextUrl;
  if (pathname === "/login") return NextResponse.next();
  if (pathname.startsWith("/_next") || pathname.startsWith("/api")) return NextResponse.next();
  if (pathname.startsWith("/login")) return NextResponse.next();
  const hasSession = Boolean(req.cookies.get(COOKIE)?.value);
  if (hasSession) return NextResponse.next();
  const url = req.nextUrl.clone();
  url.pathname = "/login";
  url.searchParams.set("next", pathname + (req.nextUrl.search || ""));
  return NextResponse.redirect(url);
}

export const config = {
  matcher: ["/((?!_next/static|_next/image|favicon.ico).*)"],
};