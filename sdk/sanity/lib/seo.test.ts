// Run: node --no-warnings --experimental-strip-types --test sanity/lib/seo.test.ts   (from sdk/)
import { test } from "node:test";
import assert from "node:assert/strict";
import {
  SEO_DESCRIPTION_FALLBACK_MAX,
  SEO_TITLE_FALLBACK_MAX,
  resolveSeoDescription,
  resolveSeoTitle,
  truncateAtWord,
} from "./seo.ts";

const LONG_SUMMARY =
  "Artificial intelligence isn't just a buzzword anymore. It's reshaping how teams plan, write, ship and " +
  "support software, and the differences between assistants, automations and fully agentic systems decide " +
  "where the real productivity gains show up. This guide breaks down each term, the architecture behind it, " +
  "and when each one is the right tool for the job in a real production workflow today.";

test("explicit seoTitle / seoDescription are returned untouched, however long", () => {
  const seoDescription = "x".repeat(300);
  assert.equal(resolveSeoDescription({ seoDescription, summary: "s" }), seoDescription);
  assert.equal(resolveSeoTitle({ seoTitle: "  Hand-written title  ", title: "t" }), "Hand-written title");
});

test("fallback description is shortened at a word boundary with an ellipsis", () => {
  assert.ok(LONG_SUMMARY.length > 300);
  const d = resolveSeoDescription({ summary: LONG_SUMMARY });
  assert.ok(d.length <= SEO_DESCRIPTION_FALLBACK_MAX, `got ${d.length}`);
  assert.ok(d.endsWith("…"));
  assert.ok(LONG_SUMMARY.startsWith(d.slice(0, -1)), "must be a clean prefix, no mid-word cut");
  assert.ok(!/\s…$/.test(d));
});

test("fallback title is shortened too, short ones are left alone", () => {
  const long = "AI Agents, Automations, and Agentic AI - What's Really Different in Practice for Teams Today?";
  const t = resolveSeoTitle({ title: long });
  assert.ok(t.length <= SEO_TITLE_FALLBACK_MAX);
  assert.ok(t.endsWith("…"));
  assert.equal(resolveSeoTitle({ title: "Short title" }), "Short title");
});

test("empty inputs yield an empty string, not 'undefined' or a lone ellipsis", () => {
  assert.equal(resolveSeoTitle({}), "");
  assert.equal(resolveSeoDescription({ summary: "   " }), "");
});

test("truncateAtWord never exceeds max and handles a single huge token", () => {
  assert.equal(truncateAtWord("short", 10), "short");
  const out = truncateAtWord("a".repeat(500), 40);
  assert.ok(out.length <= 40);
  assert.ok(out.endsWith("…"));
  assert.equal(truncateAtWord("one  two\n three", 100), "one two three"); // whitespace collapsed
});
