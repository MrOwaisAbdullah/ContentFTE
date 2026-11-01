// Run: node --no-warnings --experimental-strip-types --test sanity/webhooks/auth.test.ts   (from sdk/)
import {test} from "node:test";
import assert from "node:assert/strict";
import {checkSharedSecret, queryAllowed, safeEqual} from "./auth.ts";

test("safeEqual compares by value, never matches empties, and ignores length differences safely", () => {
  assert.equal(safeEqual("abc", "abc"), true);
  assert.equal(safeEqual("abc", "abd"), false);
  assert.equal(safeEqual("abc", "abcd"), false);
  assert.equal(safeEqual("", ""), false);
  assert.equal(safeEqual(null, "x"), false);
  assert.equal(safeEqual("x", undefined), false);
});

test("the header secret authenticates", () => {
  assert.deepEqual(checkSharedSecret("s3cret", {header: "s3cret"}), {ok: true, via: "header"});
  assert.equal(checkSharedSecret("s3cret", {header: "wrong"}).ok, false);
});

test("a query-string secret is refused unless explicitly allowed", () => {
  const off = checkSharedSecret("s3cret", {query: "s3cret"});
  assert.equal(off.ok, false);
  assert.equal(off.reason, "query-secret-disabled");
  assert.deepEqual(checkSharedSecret("s3cret", {query: "s3cret"}, {allowQuery: true}), {ok: true, via: "query"});
  assert.equal(checkSharedSecret("s3cret", {query: "nope"}, {allowQuery: true}).ok, false);
});

test("an unconfigured server never authenticates anything", () => {
  assert.equal(checkSharedSecret(undefined, {header: ""}).ok, false);
  assert.equal(checkSharedSecret("", {header: ""}).ok, false);
  assert.equal(checkSharedSecret(null, {header: "x"}).reason, "not-configured");
});

test("queryAllowed reads the env flag", () => {
  assert.equal(queryAllowed({}), false);
  assert.equal(queryAllowed({REVALIDATE_ALLOW_QUERY_SECRET: "1"}), true);
  assert.equal(queryAllowed({REVALIDATE_ALLOW_QUERY_SECRET: "no"}), false);
});

import {createHmac} from "node:crypto";
import {verifyCfteSignature} from "./auth.ts";

const sign = (secret: string, body: string, t: number) =>
  `t=${t},v1=${createHmac("sha256", secret).update(`${t}.${body}`).digest("hex")}`;

test("a ContentFTE delivery signature verifies, and tampering/replay/garbage do not", () => {
  const body = '{"a":1,"title":"x"}';
  const now = 1_800_000_000;
  const h = sign("k", body, now);
  assert.equal(verifyCfteSignature("k", body, h, 300, now), true);
  assert.equal(verifyCfteSignature("k", body + " ", h, 300, now), false);
  assert.equal(verifyCfteSignature("other", body, h, 300, now), false);
  assert.equal(verifyCfteSignature("k", body, h, 300, now + 301), false);
  assert.equal(verifyCfteSignature("k", body, "t=abc,v1=zz", 300, now), false);
  assert.equal(verifyCfteSignature("k", body, "", 300, now), false);
  assert.equal(verifyCfteSignature("", body, h, 300, now), false);
});
