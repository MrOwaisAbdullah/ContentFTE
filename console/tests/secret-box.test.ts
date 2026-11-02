import { test } from "node:test";
import assert from "node:assert/strict";
import { isSealed, openSecret, sealSecret } from "../lib/secret-box.ts";

const K = "k".repeat(40);

test("a sealed key is not readable and round-trips", () => {
  const sealed = sealSecret("cfte_supersecret", K);
  assert.ok(isSealed(sealed) && !sealed.includes("supersecret"));
  assert.equal(openSecret(sealed, K), "cfte_supersecret");
});

test("every seal uses a fresh IV (same input, different output)", () => {
  assert.notEqual(sealSecret("x1234567", K), sealSecret("x1234567", K));
});

test("without a key nothing changes, and plaintext is still readable (no flag day)", () => {
  assert.equal(sealSecret("plain", undefined), "plain");
  assert.equal(openSecret("plain", undefined), "plain");
  assert.equal(openSecret("plain", K), "plain");
  assert.equal(sealSecret("", K), "");
});

test("a wrong key, a missing key or tampering yields an empty key, never an exception", () => {
  const sealed = sealSecret("secret-value", K);
  assert.equal(openSecret(sealed, "z".repeat(40)), "");
  assert.equal(openSecret(sealed, undefined), "");
  const [iv, tag, ct] = sealed.slice("enc:v1:".length).split(".");
  const tampered = `enc:v1:${iv}.${tag}.${Buffer.from("AAAA").toString("base64url")}${ct}`;
  assert.equal(openSecret(tampered, K), "");
  assert.equal(openSecret("enc:v1:garbage", K), "");
});

test("sealing twice does not double-encrypt", () => {
  const once = sealSecret("abc12345", K);
  assert.equal(sealSecret(once, K), once);
});
