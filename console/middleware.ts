// Gatekeeper for every page. Verifies the signed session cookie (HMAC + expiry)
// at the edge and preserves the intended destination when redirecting to
// /login (UX-17). A bare "cookie is present" check is not authentication — a
// forged value would pass it — so the signature is checked here, and engine
// calls re-verify in the data-access layer (lib/engine.ts) as defence in depth.
import { NextResponse } from "next/server";
import type { NextRequest } from "next/server";
import { validSessionToken } from "./lib/edge-session";

const COOKIE = "console_session";

export async function middleware(req: NextRequest) {
  const { pathname } = req.nextUrl;
  if (pathname === "/login" || pathname.startsWith("/login/")) return NextResponse.next();
  if (pathname.startsWith("/_next")) return NextResponse.next();
  // /api/* is excluded here and MUST authenticate inside each handler
  // (the media proxy does — see app/api/media). Any new route needs the same.
  if (pathname.startsWith("/api")) return NextResponse.next();

  if (await validSessionToken(req.cookies.get(COOKIE)?.value, process.env.SESSION_SECRET)) {
    return NextResponse.next();
  }

  const url = req.nextUrl.clone();
  url.pathname = "/login";
  url.search = "";
  url.searchParams.set("next", pathname + (req.nextUrl.search || ""));
  const res = NextResponse.redirect(url);
  if (req.cookies.get(COOKIE)) res.cookies.delete(COOKIE); // drop a stale/forged cookie
  return res;
}

export const config = {
  matcher: ["/((?!_next/static|_next/image|favicon.ico).*)"],
};
