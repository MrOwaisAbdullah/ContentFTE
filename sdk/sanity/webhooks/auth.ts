/**
 * Authentication helpers for the revalidate webhook (SEC-13). Pure and dependency-free so they can be
 * unit-tested with `node --test`; the Next.js route imports them.
 *
 * What changed from the first version of the route:
 *  - secrets are compared in constant time (a `===` on the shared secret leaks its prefix by timing);
 *  - a secret in the QUERY STRING is rejected unless REVALIDATE_ALLOW_QUERY_SECRET=1 - URLs end up in
 *    access logs, proxies and browser history, so a secret there is a leaked secret;
 *  - a secret inside the JSON BODY is no longer accepted at all (it let anything that can write the
 *    payload also authenticate it).
 */
import {createHash, timingSafeEqual} from "node:crypto";

/** Constant-time string equality. Hashing first makes both inputs the same length, so neither the
 *  content nor the length of the expected secret is observable. */
export function safeEqual(a: string | null | undefined, b: string | null | undefined): boolean {
  if (!a || !b) return false;
  const ha = createHash("sha256").update(a).digest();
  const hb = createHash("sha256").update(b).digest();
  return timingSafeEqual(ha, hb);
}

export type SecretSources = {
  header?: string | null;   // x-webhook-secret
  query?: string | null;    // ?secret=
};

export type SecretVerdict = {ok: boolean; via?: "header" | "query"; reason?: string};

/** Check a shared secret presented by header (preferred) or - only when explicitly allowed - the query. */
export function checkSharedSecret(
  expected: string | null | undefined,
  sources: SecretSources,
  opts: {allowQuery?: boolean} = {},
): SecretVerdict {
  if (!expected) return {ok: false, reason: "not-configured"};
  if (safeEqual(sources.header, expected)) return {ok: true, via: "header"};
  if (sources.query) {
    if (!opts.allowQuery) return {ok: false, reason: "query-secret-disabled"};
    if (safeEqual(sources.query, expected)) return {ok: true, via: "query"};
  }
  return {ok: false, reason: "invalid"};
}

export function queryAllowed(env: Record<string, string | undefined> = process.env): boolean {
  return ["1", "true", "yes", "on"].includes((env.REVALIDATE_ALLOW_QUERY_SECRET ?? "").toLowerCase());
}

/**
 * Verify a ContentFTE delivery (`X-CFTE-Signature: t=<unix>,v1=<hex>`), the receiving side of
 * lib/custom_site.deliver. The MAC covers `"<t>." + rawBody`, so verify against the RAW request text
 * (`await request.text()`), not a re-serialised object. Rejects deliveries outside the tolerance window
 * (replay). De-duplicate on the `X-CFTE-Delivery` header: a retry reuses the same id.
 */
import {createHmac} from "node:crypto";

export function verifyCfteSignature(
  secret: string | null | undefined,
  rawBody: string,
  header: string | null | undefined,
  toleranceSeconds = 300,
  nowSeconds = Math.floor(Date.now() / 1000),
): boolean {
  if (!secret || !header) return false;
  const parts: Record<string, string> = {};
  for (const piece of header.split(",")) {
    const i = piece.indexOf("=");
    if (i > 0) parts[piece.slice(0, i).trim()] = piece.slice(i + 1).trim();
  }
  const ts = Number(parts.t);
  if (!Number.isFinite(ts) || !parts.v1) return false;
  if (Math.abs(nowSeconds - ts) > toleranceSeconds) return false;
  const expected = createHmac("sha256", secret).update(`${ts}.${rawBody}`).digest("hex");
  return safeEqual(expected, parts.v1);
}
