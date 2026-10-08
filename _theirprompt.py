import os, json, time, base64, urllib.request
from urllib.error import HTTPError

env = {}
with open(".env", "r", encoding="utf-8", errors="replace") as fh:
    for line in fh:
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, _, v = line.partition("=")
            env[k.strip()] = v.strip().strip('"').strip("'")
ACC, TOK = env["CLOUDFLARE_ACCOUNT_ID"], env["CLOUDFLARE_API_TOKEN"]

PROMPT = """Create a premium cinematic hero thumbnail for a technical blog post on **owaisabdullah.dev**.

**Visual identity:** Cinematic 3D tech storytelling, polished CGI, expressive original characters, sophisticated lighting, rich environments, and strong visual metaphors. The result should feel like high-end animated-film concept art blended with premium technology editorial artwork—not a generic SaaS advertisement.

**Format and composition**
- Landscape 16:9 aspect ratio, ideally 1600 × 900 pixels.
- Compose for a website blog card and a full-width article hero.
- Establish one unmistakable focal point with clear foreground, middle ground, and background.
- Use dramatic perspective, cinematic depth of field, realistic material details, atmospheric lighting, and carefully controlled visual complexity.
- Keep the main subject large, recognizable, and readable at small thumbnail sizes.
- Reserve clean negative space for a short headline only when needed.

**Color and lighting**
- Use deep navy, midnight blue, and charcoal as the usual foundation.
- Add electric blue and cyan lighting, with violet, magenta, or pink accents where they suit the subject.
- Introduce warm amber, orange, or gold highlights to create contrast and depth.
- Adapt the palette to the specific product, logo, or article topic rather than forcing identical colors onto every image.
- Use luminous accents, subtle reflections, atmospheric haze, and rich shadows without excessive neon.

**Character direction**
- When a character helps tell the story, create a distinctive, expressive, high-quality 3D cartoon character designed specifically for this article.
- Explore different character types, silhouettes, personalities, poses, facial expressions, costumes, and materials across different posts.
- The character must embody the article's subject or represent its central conflict, transformation, tool, or outcome.
- Characters can be cute, clever, mysterious, mischievous, intimidating, competitive, heroic, or humorous depending on the topic.
- Do not automatically use robots, hoodie-wearing developers, people at desks, or the same mascot in every image.
- For articles that work better with objects, creatures, environments, or abstract visual metaphors, do not force a human character into the composition.

**Topic-specific storytelling**
Before designing the image, identify the article's central idea and translate it into one memorable visual scene. Explore original concepts such as a character battle, a magical transformation, a miniature automated city, a branching decision system, a dramatic before-and-after scene, or a powerful symbolic object.
Use the actual article topic and relevant brand identity to guide the imagery. Include recognizable logos only when appropriate, and preserve their supplied shapes and colors as closely as possible.

**Typography**
- Keep on-image text minimal: ideally a short title or 2-5-word hook.
- Use bold, clean, legible typography with strong contrast.
- Prioritize the visual story over explanatory text.
- Do not invent product specifications, prices, performance numbers, or unsupported claims.
- Avoid tiny labels, crowded UI panels, unnecessary slogans, and excessive text.

**Avoid**
Generic stock imagery, repetitive compositions, the same robot mascot across posts, generic people staring at laptops, cluttered floating dashboards, excessive icons, walls of text, flat corporate illustrations, cheap-looking plastic materials, oversaturated neon everywhere, watermarks, misspelled text, and irrelevant decorative technology.

**Most important rule:** Every thumbnail must have its own original visual concept and character direction. Maintain the recognizable cinematic quality and overall visual polish of owaisabdullah.dev, but vary the subject, composition, color balance, setting, and storytelling from one article to the next.

**Article title:** Spec-Driven Workflow

**Article URL or summary:** How spec-driven development eliminates AI code errors. Compare structured specifications with prompts for reliable LLM coding.

**Brand logo or reference image:** [ATTACH IF RELEVANT]"""

print("PROMPT length:", len(PROMPT), "chars,", len(PROMPT.split()), "words")


def run(model, timeout=180):
    url = f"https://api.cloudflare.com/client/v4/accounts/{ACC}/ai/run/{model}"
    fields = {"prompt": (None, PROMPT), "width": (None, "1280"), "height": (None, "720")}
    b = "----cf" + str(int(time.time() * 1000))
    parts = []
    for name, (fn, val) in fields.items():
        head = f'--{b}\r\nContent-Disposition: form-data; name="{name}"'
        if fn:
            head += f'; filename="{fn}"'
        head += "\r\n\r\n"
        parts.append(head.encode() + str(val).encode() + b"\r\n")
    parts.append(f"--{b}--\r\n".encode())
    req = urllib.request.Request(url, data=b"".join(parts), method="POST", headers={
        "Authorization": f"Bearer {TOK}",
        "Content-Type": f"multipart/form-data; boundary={b}"})
    t0 = time.time()
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            raw = r.read()
        dt = time.time() - t0
        p = json.loads(raw)
        if p.get("errors"):
            return {"ok": False, "dt": dt, "err": json.dumps(p["errors"])[:600]}
        img = (p.get("result") or {}).get("image") or p.get("image")
        if not img:
            return {"ok": False, "dt": dt, "err": f"keys={list((p.get('result') or p).keys())}"}
        return {"ok": True, "dt": dt, "data": base64.b64decode(img)}
    except HTTPError as e:
        return {"ok": False, "dt": time.time() - t0,
                "err": f"HTTP {e.code}: {e.read()[:500].decode(errors='replace')}"}
    except Exception as e:
        return {"ok": False, "dt": time.time() - t0, "err": f"{type(e).__name__}: {e}"}


plan = [
    ("@cf/black-forest-labs/flux-2-klein-4b", "theirprompt_flux-2-klein-4b.png"),
    ("@cf/black-forest-labs/flux-2-klein-9b", "theirprompt_flux-2-klein-9b.png"),
    ("@cf/black-forest-labs/flux-2-dev",      "theirprompt_flux-2-dev.png"),
]
for model, out in plan:
    r = run(model)
    tag = model.split("/")[-1]
    if r["ok"]:
        open(out, "wb").write(r["data"])
        print(f"OK   {tag:18s} {r['dt']:6.1f}s  {len(r['data'])/1024:7.1f} KB -> {out}")
    else:
        print(f"FAIL {tag:18s} {r['dt']:6.1f}s  {r['err']}")
