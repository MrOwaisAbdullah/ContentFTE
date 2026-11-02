// Gatekeeper for every page. Verifies the signed session cookie (HMAC + expiry)
// at the edge and preserves the intended destination when redirecting to
// /login (UX-17). A bare "cookie is present" check is not authentication — a
// forged value would pass it — so the signature is checked here, and engine
// calls re-verify in the data-access layer (lib/engine.ts) as defence in depth.
import { NextResponse } from "next/server";
import type { NextRequest } from "next/server";
import { validSessionToken } from "./lib/edge-session";
import { FLASH_SIG, FLASH_TS, canonicalFlash, hasFlash, withoutFlash } from "./lib/flash.ts";
import { validFlash } from "./lib/flash-verify.ts";

const COOKIE = "console_session";

export async function middleware(req: NextRequest) {
  const { pathname } = req.nextUrl;
  if (pathname === "/login" || pathname.startsWith("/login/")) return NextResponse.next();
  if (pathname.startsWith("/_next")) return NextResponse.next();
  // /api/* is excluded here and MUST authenticate inside each handler
  // (the media proxy does — see app/api/media). Any new route needs the same.
  if (pathname.startsWith("/api")) return NextResponse.next();

  // Flash messages (?ok=, ?err=, ...) are shown as toasts only if a server action signed them (CON-16).
  // A crafted or stale link has them stripped: the page loads normally, with no message.
  const sp = req.nextUrl.searchParams;
  if (hasFlash(sp)) {
    const ok = await validFlash(canonicalFlash(sp), sp.get(FLASH_TS), sp.get(FLASH_SIG), process.env.SESSION_SECRET);
    if (!ok) {
      const clean = req.nextUrl.clone();
      clean.search = withoutFlash(sp).toString();
      return NextResponse.redirect(clean);
    }
  }

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
