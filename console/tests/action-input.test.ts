import { test } from "node:test";
import assert from "node:assert/strict";
import { cleanText, parseId, parsePublishMode, parseReturnPath, parseSlug } from "../lib/action-input.ts";

test("ids: positive integers only", () => {
  assert.equal(parseId("42"), 42);
  assert.equal(parseId(" 7 "), 7);
  for (const bad of ["", "0", "-1", "1.5", "1e3", "0x10", "NaN", "abc", "12abc", "99999999999", " ", null, undefined, "01"]) {
    assert.equal(parseId(bad as string), null, String(bad));
  }
});

test("publish mode falls back to the safe default, never to live", () => {
  assert.equal(parsePublishMode("publish"), "publish");
  assert.equal(parsePublishMode("auto"), "auto");
  assert.equal(parsePublishMode("draft"), "draft");
  assert.equal(parsePublishMode(" auto "), "auto"); // surrounding whitespace is trimmed, not rejected
  for (const bad of ["", "LIVE", "publish now", "drop table", null, undefined, "__proto__"]) {
    assert.equal(parsePublishMode(bad as string), "draft", String(bad));
  }
});

test("the return path can only be one of the fixed queue pages (no open redirect)", () => {
  assert.equal(parseReturnPath("/publish"), "/publish");
  for (const bad of ["https://evil.example", "//evil.example", "/\\evil.example", "/articles", "", "/publish?x=1", null]) {
    assert.equal(parseReturnPath(bad as string), null, String(bad));
  }
});

test("site slugs match what the engine accepts", () => {
  assert.equal(parseSlug("my-blog-2"), "my-blog-2");
  for (const bad of ["", "Has Space", "UPPER", "a/b", "../x", "-lead", "x".repeat(64), "über"]) {
    assert.equal(parseSlug(bad), null, bad);
  }
});

test("free text is trimmed and capped", () => {
  assert.equal(cleanText("  hello  ", 10), "hello");
  assert.equal(cleanText("x".repeat(50), 5), "xxxxx");
  assert.equal(cleanText(undefined, 5), "");
});
