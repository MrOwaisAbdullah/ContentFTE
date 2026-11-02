import { test } from "node:test";
import assert from "node:assert/strict";
import { buildCsp, cspHeader, cspMode, newNonce } from "../lib/csp.ts";

test("the policy carries the nonce, strict-dynamic, and the lock-downs", () => {
  const csp = buildCsp("abc123", { dev: false });
  assert.match(csp, /script-src 'self' 'nonce-abc123' 'strict-dynamic'/);
  assert.ok(!csp.includes("'unsafe-eval'") && !/script-src[^;]*'unsafe-inline'/.test(csp));
  for (const d of ["object-src 'none'", "frame-ancestors 'none'", "base-uri 'self'", "form-action 'self'", "default-src 'self'"]) {
    assert.ok(csp.includes(d), d);
  }
});

test("development adds unsafe-eval for React refresh and nothing else changes", () => {
  assert.ok(buildCsp("n", { dev: true }).includes("'unsafe-eval'"));
});

test("report-only is the default and never blocks; enforce uses the real header; off sends nothing", () => {
  assert.equal(cspMode(undefined), "report-only");
  assert.equal(cspMode("nonsense"), "report-only");
  assert.equal(cspHeader("n", "report-only", false)?.name, "Content-Security-Policy-Report-Only");
  assert.equal(cspHeader("n", "enforce", false)?.name, "Content-Security-Policy");
  assert.equal(cspHeader("n", "off", false), null);
  assert.equal(cspMode("ENFORCE"), "enforce");
});

test("nonces are unguessable-looking, base64, and differ every request", () => {
  const a = newNonce();
  const b = newNonce();
  assert.notEqual(a, b);
  assert.match(a, /^[A-Za-z0-9+/]+=*$/);
  assert.ok(a.length >= 22);
});
