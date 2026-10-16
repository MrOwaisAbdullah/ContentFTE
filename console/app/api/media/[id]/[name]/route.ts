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
  if (!/^\d+$/.test(id) || !name || /[/\\]/.test(name)) {
    return NextResponse.json({ error: "bad image path" }, { status: 400 });
  }
  const inst = await currentInstance();
  try {
    const res = await fetch(
      `${inst.baseUrl}/sdk/v1/articles/${id}/images/${encodeURIComponent(name)}`,
      {
        cache: "no-store",
        headers: inst.apiKey ? { "X-Site-Key": inst.apiKey } : {},
      },
    );
    if (!res.ok || !res.body) {
      return NextResponse.json(
        { error: `engine image fetch failed (${res.status})` },
        { status: 404 },
      );
    }
    return new NextResponse(res.body, {
      status: 200,
      headers: {
        "Content-Type": res.headers.get("content-type") || "application/octet-stream",
        "Cache-Control": "private, max-age=60",
      },
    });
  } catch {
    return NextResponse.json({ error: "engine unreachable" }, { status: 502 });
  }
}
