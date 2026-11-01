import { NextResponse } from "next/server";

import { currentInstance } from "@/lib/instances";
import { verifySession } from "@/lib/session";

/* Thumbnail proxy for the Media gallery (Wave 3): a browser <img> can't
   send the engine's X-Site-Key, so bytes flow engine → console (with the
   instance headers) → browser and the engine's auth surface stays
   untouched. Session-checked like every console page; the engine remains
   the authority on which files exist (meta.images basename allowlist). */
export async function GET(
  _req: Request,
  ctx: { params: Promise<{ id: string; name: string }> },
) {
  if (!(await verifySession())) {
    return NextResponse.json({ error: "unauthorized" }, { status: 401 });
  }
  const { id, name } = await ctx.params;
  // Allow-list rather than deny-list: a plain image filename only. `..` used to
  // slip through (encodeURIComponent("..") === "..") and resolve to the article's
  // directory upstream.
  if (!/^\d+$/.test(id) || !/^\w[\w.-]{0,127}\.(png|jpe?g|webp|gif|avif)$/i.test(name) || name.includes("..")) {
    return NextResponse.json({ error: "bad image path" }, { status: 400 });
  }
  const inst = await currentInstance();
  try {
    const res = await fetch(
      `${inst.baseUrl}/sdk/v1/articles/${id}/images/${encodeURIComponent(name)}`,
      {
        cache: "no-store",
        headers: inst.apiKey ? { "X-Site-Key": inst.apiKey } : {},
        signal: AbortSignal.timeout(15_000),
      },
    );
    if (!res.ok || !res.body) {
      return NextResponse.json(
        { error: `engine image fetch failed (${res.status})` },
        { status: 404 },
      );
    }
    // Never relay an arbitrary upstream content-type (an HTML/SVG response would
    // be served from the console's origin); only raster image types pass through.
    const upstreamType = (res.headers.get("content-type") || "").split(";")[0].trim().toLowerCase();
    const contentType = /^image\/(png|jpeg|webp|gif|avif)$/.test(upstreamType)
      ? upstreamType
      : "application/octet-stream";
    return new NextResponse(res.body, {
      status: 200,
      headers: {
        "Content-Type": contentType,
        "X-Content-Type-Options": "nosniff",
        "Content-Disposition": "inline",
        "Cache-Control": "private, max-age=60",
      },
    });
  } catch {
    return NextResponse.json({ error: "engine unreachable" }, { status: 502 });
  }
}
