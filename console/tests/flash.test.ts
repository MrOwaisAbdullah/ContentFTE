import { test } from "node:test";
import assert from "node:assert/strict";
import { FLASH_MESSAGES, resolveFlash } from "../lib/flash.ts";

test("a known code resolves to its fixed message", () => {
  assert.equal(resolveFlash("saved")?.text, "Saved.");
  assert.equal(resolveFlash("instance_changed")?.tone, "error");
});

test("free text from a crafted link is never displayed", () => {
  assert.equal(resolveFlash("Article published successfully"), null);
  assert.equal(resolveFlash("<img src=x onerror=alert(1)>"), null);
  assert.equal(resolveFlash("Your session expired, call +1-555-0100"), null);
});

test("prototype keys and odd shapes are not codes", () => {
  for (const v of ["__proto__", "constructor", "toString", "", "  ", null, undefined, "A".repeat(80)]) {
    assert.equal(resolveFlash(v as string | null | undefined), null);
  }
});

test("every message is plain text (no markup) so it can be rendered safely", () => {
  for (const m of Object.values(FLASH_MESSAGES)) assert.ok(!/[<>]/.test(m.text));
});
