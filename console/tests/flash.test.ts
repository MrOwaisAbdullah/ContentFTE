import { test } from "node:test";
import assert from "node:assert/strict";
import { createHmac } from "node:crypto";
import {
  FLASH_MESSAGES,
  FLASH_SIG,
  FLASH_TS,
  canonicalFlash,
  flashFor,
  flashMessageToSign,
  hasFlash,
  withoutFlash,
} from "../lib/flash.ts";
import { validFlash } from "../lib/flash-verify.ts";

const SECRET = "x".repeat(40);
const sign = (ts: number, canonical: string) =>
  createHmac("sha256", SECRET).update(flashMessageToSign(ts, canonical)).digest("hex"); // what flash-redirect.ts does

test("canonical form is order-independent and ignores non-flash parameters", () => {
  const a = canonicalFlash(new URLSearchParams("ok=Saved&site=a&page=2"));
  const b = canonicalFlash(new URLSearchParams("page=2&ok=Saved&site=a"));
  assert.equal(a, b);
  assert.equal(a, "ok=Saved");
  assert.equal(canonicalFlash(new URLSearchParams("err=boom&ok=fine")), "err=boom\nok=fine");
});

test("a message signed by the server verifies at the edge (node HMAC == Web Crypto HMAC)", async () => {
  const now = 1_800_000_000_000;
  const ts = Math.floor(now / 1000);
  const canonical = canonicalFlash(new URLSearchParams("ok=Article #5 approved."));
  assert.equal(await validFlash(canonical, String(ts), sign(ts, canonical), SECRET, now), true);
});

test("a crafted link is rejected: no signature, wrong secret, edited text, expired, replayed later", async () => {
  const now = 1_800_000_000_000;
  const ts = Math.floor(now / 1000);
  const canonical = "ok=Article published successfully";
  const good = sign(ts, canonical);
  assert.equal(await validFlash(canonical, null, null, SECRET, now), false);                       // attacker's link
  assert.equal(await validFlash(canonical, String(ts), "0".repeat(64), SECRET, now), false);       // guessed signature
  assert.equal(await validFlash("ok=Different text", String(ts), good, SECRET, now), false);        // text edited
  assert.equal(await validFlash(canonical, String(ts), good, "another-secret-another-secret-123", now), false);
  assert.equal(await validFlash(canonical, String(ts), good, SECRET, now + 121_000), false);        // too old
  assert.equal(await validFlash(canonical, String(ts), good, SECRET, now - 121_000), false);        // from the future
  assert.equal(await validFlash(canonical, String(ts), good, undefined, now), false);               // no secret configured
  assert.equal(await validFlash(canonical, "abc", good, SECRET, now), false);
});

test("withoutFlash removes the messages and their signature but keeps real parameters", () => {
  const p = new URLSearchParams(`site=a&ok=hi&${FLASH_TS}=1&${FLASH_SIG}=ff&page=2`);
  assert.equal(hasFlash(p), true);
  assert.equal(withoutFlash(p).toString(), "site=a&page=2");
  assert.equal(hasFlash(new URLSearchParams("site=a")), false);
});

test("ok/err carry server text (capped, plain); bare keys use the default wording", () => {
  assert.deepEqual(flashFor("ok", "Article #5 approved."), { text: "Article #5 approved.", tone: "success" });
  assert.equal(flashFor("err", "boom")?.tone, "error");
  assert.equal(flashFor("ok", "x".repeat(1000))?.text.length, 300);
  assert.equal(flashFor("deleted", "5")?.text, "Deleted.");
  assert.equal(flashFor("ok", "   "), null);
  assert.equal(flashFor("bogus", "x"), null);
  assert.equal(flashFor("constructor", "x"), null);
});

test("every default message is plain text", () => {
  for (const m of Object.values(FLASH_MESSAGES)) assert.ok(!/[<>]/.test(m.text));
});
