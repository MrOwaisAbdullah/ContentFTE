// Same-origin relative redirect target only (plan SEC-10). Pure — usable from
// both the server action and the client login page.
//
// Rejects: absolute URLs, protocol-relative `//host`, and anything containing a
// backslash — browsers treat `/\evil.com` as `//evil.com`, which the old
// `startsWith("/") && !startsWith("//")` check let through.

export function safeNextPath(next: string | null | undefined): string {
  const n = String(next ?? "");
  if (!n.startsWith("/")) return "/";
  if (n.startsWith("//") || n.includes("\\")) return "/";
  // eslint-disable-next-line no-control-regex
  if (/[\u0000-\u001f\u007f]/.test(n)) return "/";
  return n;
}
