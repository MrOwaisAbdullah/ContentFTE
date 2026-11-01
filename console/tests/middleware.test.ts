import { test } from "node:test";
import assert from "node:assert/strict";
import { createHmac } from "node:crypto";
import { validSessionToken } from "../lib/edge-session.ts";

const SECRET = "test-secret-test-secret-test-secret-123456";

// Same format lib/session.ts issues (Node crypto there, Web Crypto here — they must agree):
//   v1.<exp>.<hex HMAC-SHA256 of "v1.<exp>.console-session">
function token(expSeconds: number, secret = SECRET): string {
  const sig = createHmac("sha256", secret).update(`v1.${expSeconds}.console-session`).digest("hex");
  return `v1.${expSeconds}.${sig}`;
}
const now = Date.now();
const inAnHour = Math.floor(now / 1000) + 3600;

test("a token signed by lib/session.ts's scheme verifies at the edge", async () => {
  assert.equal(await validSessionToken(token(inAnHour), SECRET, now), true);
});

test("forged tokens are rejected (the old check accepted any non-empty cookie)", async () => {
  for (const forged of [
    "x",
    "v1.9999999999.deadbeef",
    "v2." + token(inAnHour).slice(3),
    token(inAnHour, "some-other-secret-some-other-secret-1234"),
    "",
  ]) {
    assert.equal(await validSessionToken(forged, SECRET, now), false, `should reject ${forged.slice(0, 24)}`);
  }
  assert.equal(await validSessionToken(undefined, SECRET, now), false);
});

test("an expired token is rejected", async () => {
  assert.equal(await validSessionToken(token(Math.floor(now / 1000) - 5), SECRET, now), false);
});

test("extending the expiry while keeping the old signature is rejected", async () => {
  const [v, exp, sig] = token(inAnHour).split(".");
  assert.equal(await validSessionToken(`${v}.${Number(exp) + 86_400}.${sig}`, SECRET, now), false);
});

test("fails closed without a secret", async () => {
  assert.equal(await validSessionToken(token(inAnHour), undefined, now), false);
  assert.equal(await validSessionToken(token(inAnHour), "", now), false);
});
