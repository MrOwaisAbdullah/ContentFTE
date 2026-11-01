import { test } from "node:test";
import assert from "node:assert/strict";
import { safeNextPath } from "../lib/safe-next.ts";
import { createLimiter } from "../lib/login-limit.ts";

test("safeNextPath keeps same-origin relative paths", () => {
  assert.equal(safeNextPath("/articles/12?tab=seo"), "/articles/12?tab=seo");
  assert.equal(safeNextPath("/"), "/");
});

test("safeNextPath rejects open-redirect shapes", () => {
  for (const bad of [
    "//evil.com",
    "/\\evil.com", // browsers read this as //evil.com
    "\\\\evil.com",
    "https://evil.com",
    "javascript:alert(1)",
    "evil.com",
    "/a\nb",
    "/a\u0000b",
  ]) {
    assert.equal(safeNextPath(bad), "/", `should reject ${JSON.stringify(bad)}`);
  }
  assert.equal(safeNextPath(null), "/");
  assert.equal(safeNextPath(undefined), "/");
});

test("limiter blocks after max failures inside the window and reports retry time", () => {
  const l = createLimiter({ max: 3, windowMs: 1000 });
  const t0 = 10_000;
  assert.equal(l.status("ip", t0).blocked, false);
  l.fail("ip", t0);
  l.fail("ip", t0 + 10);
  assert.equal(l.status("ip", t0 + 20).remaining, 1);
  l.fail("ip", t0 + 20);
  const s = l.status("ip", t0 + 30);
  assert.equal(s.blocked, true);
  assert.ok(s.retryAfterMs > 0 && s.retryAfterMs <= 1000);
  assert.equal(l.status("other", t0 + 30).blocked, false); // keys are independent
});

test("limiter forgets failures after the window and on reset", () => {
  const l = createLimiter({ max: 2, windowMs: 1000 });
  l.fail("ip", 0);
  l.fail("ip", 1);
  assert.equal(l.status("ip", 2).blocked, true);
  assert.equal(l.status("ip", 1500).blocked, false); // window elapsed
  l.fail("ip", 1600);
  l.fail("ip", 1601);
  assert.equal(l.status("ip", 1602).blocked, true);
  l.reset("ip");
  assert.equal(l.status("ip", 1603).blocked, false);
});
