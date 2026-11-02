/**
 * Smoke test for the built package (npm run smoke, after npm run build).
 * Renders ContentFTEArticle with a representative delivery payload and
 * checks the portfolio-parity contract, plus exercises the client entry.
 */
import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { createRequire } from "node:module";
import { ContentFTEArticle } from "./dist/renderer.js";
import { ContentFTEClient, ContentFTEError, buildMetadata } from "./dist/contentfte.js";

const failures = [];
function check(ok, label) {
  if (ok) console.log(`  ok  ${label}`);
  else {
    failures.push(label);
    console.error(`FAIL  ${label}`);
  }
}

const payload = {
  title: "Best CRM for Agencies",
  slug: "best-crm-for-agencies",
  url: "https://example.com/best-crm-for-agencies",
  excerpt: "Pick HubSpot if you bill hourly.",
  html: "<p><strong>TL;DR</strong> fallback html body</p>",
  markdown: [
    "> **TL;DR** pick HubSpot",
    "",
    "## Quick comparison",
    "",
    "| Feature | HubSpot |",
    "| ------- | ------- |",
    "| Price   | $$$     |",
    "",
    "Visit [Google](https://google.com) or [our pricing](/pricing) — the ==key term== matters.",
    "",
    "<script>alert('xss')</script>",
  ].join("\n"),
  schema: {
    article: {
      "@context": "https://schema.org",
      "@type": "Article",
      headline: "Best CRM for Agencies <b>2026</b>",
    },
    faq: {
      "@context": "https://schema.org",
      "@type": "FAQPage",
      mainEntity: [
        {
          "@type": "Question",
          name: "Which CRM is best?",
          acceptedAnswer: { "@type": "Answer", text: "HubSpot <em>for most</em> teams" },
        },
      ],
    },
  },
};

const html = renderToStaticMarkup(
  createElement(ContentFTEArticle, { content: payload, siteOrigin: "https://example.com" }),
);

check(/<h1[^>]*>Best CRM for Agencies<\/h1>/.test(html), "title rendered as <h1>");
check(!/itemProp|itemScope|itemType=/.test(html), "no camelCase microdata leakage (JSON-LD only)");
check(html.includes("cfte-prose"), "article wrapper has cfte-prose class");
check(html.includes('class="cfte-dek"') && html.includes("Pick HubSpot if you bill hourly."), "excerpt as .cfte-dek");
check(html.includes("<blockquote>"), "TL;DR markdown blockquote rendered");
check(html.includes('id="quick-comparison"'), "rehype-slug heading id (TOC anchors)");
check(/<mark>key term<\/mark>/.test(html), "==highlight== → <mark>");
check(html.includes('rel="noopener noreferrer"') && html.includes('href="https://google.com"'), "external link opens in new tab");
check((html.match(/target="_blank"/g) ?? []).length === 1, "only external links get target=_blank");
check(html.includes('href="/pricing"'), "internal relative link stays in-tab");
check(html.includes('class="cfte-table-wrap"') && html.includes("<table>"), "table wrapped for overflow");
check(html.includes('id="faqs"'), "FAQ section id for anchors");
check(html.includes("application/ld+json"), "JSON-LD script present");
check((html.match(/application\/ld\+json/g) ?? []).length === 2, "article + FAQPage JSON-LD");
check(html.includes("\\u003c"), "JSON-LD `<` escaped (no script breakout)");
check(!html.includes("alert('xss')"), "raw <script> dropped by rehype-sanitize");

// html fallback when markdown is empty
const fallback = renderToStaticMarkup(
  createElement(ContentFTEArticle, { content: { ...payload, markdown: "" } }),
);
check(fallback.includes("<strong>TL;DR</strong> fallback html body"), "empty markdown falls back to payload.html");

// the html fallback is sanitized exactly like markdown (plan SEC-06): hostile engine HTML must not reach the page
const hostile = renderToStaticMarkup(
  createElement(ContentFTEArticle, {
    content: {
      ...payload,
      markdown: "",
      html: [
        '<p>ok <a href="javascript:alert(1)">bad link</a> <a href="https://example.com/x">good link</a></p>',
        '<img src="x" onerror="alert(2)">',
        '<script>alert(3)</script>',
        '<p onclick="alert(4)">click</p>',
        '<iframe src="https://evil.example"></iframe>',
      ].join(""),
    },
  }),
);
check(!/javascript:/i.test(hostile), "html fallback: javascript: href removed");
check(!/onerror|onclick/i.test(hostile), "html fallback: inline event handlers removed");
check(!hostile.includes("alert(3)") && !/<script>alert/.test(hostile), "html fallback: <script> dropped");
check(!/<iframe/i.test(hostile), "html fallback: <iframe> dropped");
check(hostile.includes("https://example.com/x") && hostile.includes("good link"), "html fallback: safe links and text survive");

// client entry (ESM)
const client = new ContentFTEClient("https://engine.example.com", "site-key");
check(typeof client.submitArticle === "function" && typeof client.getContent === "function", "ContentFTEClient methods present");
check(typeof client.getContent === "function" && typeof client.listSites === "function", "client listSites/getContent present");

// ---- retry rules (plan ENG-19): never retry what cannot succeed, never repeat what may have worked ----
const realFetch = globalThis.fetch;
const jsonRes = (status, body) =>
  new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
async function withFetch(script, fn) {
  const calls = [];
  let i = 0;
  globalThis.fetch = async (url, init) => {
    calls.push({ url: String(url), method: init?.method, headers: init?.headers, hasSignal: Boolean(init?.signal) });
    const out = script[Math.min(i++, script.length - 1)];
    if (out instanceof Error) throw out;
    return out;
  };
  try {
    return { calls, result: await fn() };
  } catch (error) {
    return { calls, error };
  } finally {
    globalThis.fetch = realFetch;
  }
}
const quick = () => new ContentFTEClient("https://engine.test", "k", 3, 1);

for (const status of [401, 404, 409, 422]) {
  const r = await withFetch([jsonRes(status, { detail: "quality gate failed: 2 claims" })], () => quick().getArticle(1));
  check(r.calls.length === 1, `${status} is not retried (was 3 attempts)`);
  check(r.error instanceof ContentFTEError && r.error.status === status, `${status} -> ContentFTEError with status`);
  check(String(r.error?.message).includes("quality gate failed"), `${status} keeps the server's reason`);
}

let r = await withFetch([jsonRes(503, {}), jsonRes(502, {}), jsonRes(200, { id: 1 })], () => quick().getArticle(1));
check(r.calls.length === 3 && r.result?.id === 1, "GET retries transient 5xx then succeeds");

r = await withFetch([jsonRes(503, {}), jsonRes(200, { status: "published" })], () => quick().publishArticle(7));
check(r.calls.length === 1 && r.error instanceof ContentFTEError, "POST without an idempotency key is NOT repeated after a 5xx");

r = await withFetch([new Error("network down"), jsonRes(200, {})], () => quick().generateContent(7));
check(r.calls.length === 1 && String(r.error?.message) === "network down", "POST is NOT repeated after a network error/timeout");

r = await withFetch([new Error("timeout"), jsonRes(503, {}), jsonRes(200, { id: 5 })], () => quick().submitArticle("s", "k", {}, "idem-1"));
check(r.calls.length === 3 && r.result?.id === 5, "POST with an Idempotency-Key is safe to repeat");

r = await withFetch([jsonRes(429, {}), jsonRes(200, { status: "published" })], () => quick().publishArticle(7));
check(r.calls.length === 2 && r.result?.status === "published", "429 is always repeated (request was not processed)");

r = await withFetch([jsonRes(200, { id: 1 })], () => quick().getArticle(1));
check(r.calls[0].hasSignal, "every request carries a timeout signal");

// CJS entry still loads
const require = createRequire(import.meta.url);
const cjs = require("./dist/contentfte.cjs");
check(typeof cjs.ContentFTEClient === "function", "CJS require of contentfte entry works");

// buildMetadata: payload v2 -> Next.js generateMetadata()
{
  const md = buildMetadata({
    ...payload,
    seo: { title: "Best CRM", meta_title: "Best CRM for Agencies (2026)", description: "Pick HubSpot.", canonical: "https://example.com/best-crm", focus_keyword: "crm", tldr: "" },
    image: { url: "https://cdn.example.com/hero.jpg", alt: "hero", width: 1200, height: 630 },
    og: { type: "article", title: "Best CRM for Agencies (2026)", description: "Pick HubSpot.", url: "https://example.com/best-crm", image: "https://cdn.example.com/hero.jpg", image_alt: "hero", published_time: "2026-01-01", modified_time: "2026-02-01" },
  });
  check(md.title === "Best CRM for Agencies (2026)", "buildMetadata uses meta_title");
  check(md.alternates.canonical === "https://example.com/best-crm", "buildMetadata sets canonical");
  check(md.openGraph.images?.[0]?.url === "https://cdn.example.com/hero.jpg" && md.twitter.card === "summary_large_image", "buildMetadata maps the featured image to OG + twitter card");
  const bare = buildMetadata({ ...payload });
  check(bare.twitter.card === "summary" && bare.title === "Best CRM for Agencies", "buildMetadata degrades without v2 fields");
}

if (failures.length) {
  console.error(`\n${failures.length} smoke check(s) failed`);
  process.exit(1);
}
console.log("\nAll smoke checks passed.");
