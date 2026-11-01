/**
 * Next.js route that Sanity publish webhooks call to revalidate the site and
 * (optionally) ping IndexNow.
 *
 * Save as `app/api/revalidate/route.ts`.
 * Also copy `auth.ts` next to it (constant-time secret checks + the ContentFTE delivery verifier).
 *
 * Env:
 *   SANITY_REVALIDATE_SECRET  shared secret (the ONLY accepted value; there
 *                             is deliberately no hardcoded default)
 *   INDEXNOW_KEY              optional; omit and IndexNow pings are skipped
 *   NEXT_PUBLIC_SITE_URL      e.g. https://example.com (for IndexNow host)
 *   REVALIDATE_ALLOW_QUERY_SECRET  set to 1 ONLY while migrating: lets the secret arrive as ?secret=
 *                             (it ends up in access logs). Default: header or Sanity signature only.
 *
 * Authenticate with Sanity's signature header (preferred) or `x-webhook-secret: <secret>`.
 *
 * NEVER commit a real key or secret -- the file this replaces had both
 * inline, and they had to be treated as compromised.
 */
import {NextRequest, NextResponse} from "next/server";
import {after} from "next/server";
import {revalidatePath, revalidateTag} from "next/cache";
import {checkSharedSecret, queryAllowed} from "./auth";

export const dynamic = "force-dynamic";

const CORE_PATHS = ["/", "/blog", "/sitemap.xml"];

export async function GET(request: NextRequest) {
  const {searchParams} = request.nextUrl;
  const path = searchParams.get("path");
  const tag = searchParams.get("tag");

  const verdict = checkSharedSecret(
    validSecretValue(),
    {header: request.headers.get("x-webhook-secret"), query: searchParams.get("secret")},
    {allowQuery: queryAllowed()},
  );
  if (!verdict.ok) {
    return NextResponse.json({message: "Invalid token"}, {status: 401});
  }

  if (tag) {
    revalidateTag(tag, "default");
    return NextResponse.json({revalidated: true, tag, now: Date.now()});
  }
  if (path) {
    revalidatePath(path);
    pingIndexNow([path]);
    return NextResponse.json({revalidated: true, path, now: Date.now()});
  }

  for (const p of CORE_PATHS) revalidatePath(p);
  pingIndexNow(CORE_PATHS);
  return NextResponse.json({revalidated: true, defaultPaths: CORE_PATHS, now: Date.now()});
}

export async function POST(request: NextRequest) {
  const {searchParams} = request.nextUrl;
  const rawBody = await request.text();

  const validSecret = validSecretValue();
  if (!validSecret) {
    return NextResponse.json(
      {message: "SANITY_REVALIDATE_SECRET is not configured"},
      {status: 500}
    );
  }

  // Sanity's native HMAC signature (preferred), or the shared secret in the
  // x-webhook-secret header. The secret is compared in constant time; it is no longer read from the
  // JSON body, and a ?secret= query value only works while REVALIDATE_ALLOW_QUERY_SECRET=1.
  const signature = request.headers.get("sanity-webhook-signature");

  let signatureValid = false;
  if (signature) {
    try {
      const {isValidSignature} = await import("@sanity/webhook");
      signatureValid = await isValidSignature(rawBody, signature, validSecret);
    } catch {
      signatureValid = false;
    }
  }

  let body: any = null;
  try {
    body = rawBody.trim() ? JSON.parse(rawBody) : null;
  } catch {
    body = null;
  }

  const directValid = checkSharedSecret(
    validSecret,
    {header: request.headers.get("x-webhook-secret"), query: searchParams.get("secret")},
    {allowQuery: queryAllowed()},
  ).ok;

  if (!signatureValid && !directValid) {
    return NextResponse.json({message: "Invalid token or signature"}, {status: 401});
  }

  return handleRevalidation(body);
}

function handleRevalidation(body: any) {
  const revalidated: string[] = [];
  const type = body?._type || body?.type;
  const slug = body?.slug?.current || body?.slug;

  if (type === "post") {
    for (const p of CORE_PATHS) revalidatePath(p);
    revalidated.push(...CORE_PATHS);
    if (slug) {
      revalidatePath(`/blog/${slug}`);
      revalidated.push(`/blog/${slug}`);
    }
  } else if (body?.path) {
    revalidatePath(body.path);
    revalidated.push(body.path);
  }
  if (revalidated.length === 0) {
    for (const p of CORE_PATHS) revalidatePath(p);
    revalidated.push(...CORE_PATHS);
  }

  pingIndexNow(revalidated);
  return NextResponse.json({revalidated: true, paths: revalidated, now: Date.now()});
}

function validSecretValue(): string | null {
  return process.env.SANITY_REVALIDATE_SECRET || process.env.REVALIDATE_SECRET || null;
}

function pingIndexNow(paths: string[]) {
  const key = process.env.INDEXNOW_KEY;
  const base = process.env.NEXT_PUBLIC_SITE_URL;
  if (!key || !base) return; // IndexNow is optional
  const host = new URL(base).hostname;
  const urlList = paths
    .filter((p) => typeof p === "string" && !p.startsWith("/api"))
    .map((p) => (p.startsWith("http") ? p : `${base}${p.startsWith("/") ? "" : "/"}${p}`));

  const send = () =>
    fetch("https://api.indexnow.org/indexnow", {
      method: "POST",
      headers: {"Content-Type": "application/json; charset=utf-8"},
      body: JSON.stringify({host, key, keyLocation: `${base}/${key}.txt`, urlList}),
      signal: AbortSignal.timeout(4000),
    }).catch(() => {
      // IndexNow is best-effort; never fail a revalidation over it.
    });
  // A bare fire-and-forget fetch is killed when a serverless function returns its response; `after`
  // keeps the invocation alive until the ping has been sent.
  try {
    after(send);
  } catch {
    void send(); // outside a request scope (e.g. tests): fall back to the old behaviour
  }
}
