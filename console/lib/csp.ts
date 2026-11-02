// Content-Security-Policy with a per-request nonce (SEC-15). Pure, so it can be unit-tested; middleware.ts applies it.
//
// Why a nonce: Next.js emits inline bootstrap scripts, so `script-src 'self'` alone breaks the app and
// `'unsafe-inline'` defeats the point. A nonce lets exactly the scripts Next renders (it reads the nonce from the
// request's CSP header) run, and `'strict-dynamic'` lets those scripts load their chunks.
//
// MODE (env CSP_MODE):
//   report-only  (default) the policy is sent as Content-Security-Policy-Report-Only: the browser REPORTS what it
//                would block in the devtools console but blocks nothing. Safe to ship; check a few pages, then:
//   enforce      send it as Content-Security-Policy. Verify in a browser first - this build could not.
//   off          no nonce policy (the static frame-ancestors/base-uri/form-action policy in next.config.ts stays).

export type CspMode = "report-only" | "enforce" | "off";

export function cspMode(raw: string | undefined = process.env.CSP_MODE): CspMode {
  const v = (raw ?? "").trim().toLowerCase();
  if (v === "enforce" || v === "off") return v;
  return "report-only";
}

export function newNonce(): string {
  const bytes = new Uint8Array(16);
  crypto.getRandomValues(bytes);
  let s = "";
  for (const b of bytes) s += String.fromCharCode(b);
  return btoa(s);
}

export function buildCsp(nonce: string, opts: { dev?: boolean } = {}): string {
  const script = ["'self'", `'nonce-${nonce}'`, "'strict-dynamic'"];
  if (opts.dev) script.push("'unsafe-eval'"); // React Fast Refresh needs eval in development only
  return [
    "default-src 'self'",
    `script-src ${script.join(" ")}`,
    "style-src 'self' 'unsafe-inline'", // Next/Tailwind inject inline styles; style injection is far lower risk than script
    "img-src 'self' data: blob: https:",
    "font-src 'self' data:",
    "connect-src 'self'",
    "object-src 'none'",
    "frame-ancestors 'none'",
    "base-uri 'self'",
    "form-action 'self'",
  ].join("; ");
}

/** The header name and value to send, or null when the nonce policy is switched off. */
export function cspHeader(
  nonce: string,
  mode: CspMode = cspMode(),
  dev: boolean = process.env.NODE_ENV !== "production",
): { name: string; value: string } | null {
  if (mode === "off") return null;
  return {
    name: mode === "enforce" ? "Content-Security-Policy" : "Content-Security-Policy-Report-Only",
    value: buildCsp(nonce, { dev }),
  };
}
