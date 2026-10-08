/**
 * Smoke test for the built package (npm run smoke, after npm run build).
 * Renders ContentFTEArticle with a representative delivery payload and
 * checks the portfolio-parity contract, plus exercises the client entry.
 */
import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { createRequire } from "node:module";
import { ContentFTEArticle } from "./dist/renderer.js";
import { ContentFTEClient } from "./dist/contentfte.js";

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

// client entry (ESM)
const client = new ContentFTEClient("https://engine.example.com", "site-key");
check(typeof client.submitArticle === "function" && typeof client.getContent === "function", "ContentFTEClient methods present");
check(typeof client.getContent === "function" && typeof client.listSites === "function", "client listSites/getContent present");

// CJS entry still loads
const require = createRequire(import.meta.url);
const cjs = require("./dist/contentfte.cjs");
check(typeof cjs.ContentFTEClient === "function", "CJS require of contentfte entry works");

if (failures.length) {
  console.error(`\n${failures.length} smoke check(s) failed`);
  process.exit(1);
}
console.log("\nAll smoke checks passed.");
