import { test } from "node:test";
import assert from "node:assert/strict";
import { INSTANCE_FIELD, instanceMismatchMessage } from "../lib/instance-guard.ts";

test("a form rendered for the current instance is allowed", () => {
  assert.equal(instanceMismatchMessage("site1", "site1"), null);
});

test("an unstamped submission is allowed (non-browser caller / older page)", () => {
  assert.equal(instanceMismatchMessage("", "site1"), null);
  assert.equal(instanceMismatchMessage(undefined, "site1"), null);
  assert.equal(instanceMismatchMessage("   ", "site1"), null);
});

test("a stale tab (rendered for A, cookie now B) is refused with a clear message", () => {
  const msg = instanceMismatchMessage("site-a", "site-b");
  assert.ok(msg && msg.includes("'site-a'") && msg.includes("'site-b'"));
  assert.ok(msg.includes("Nothing was changed"));
});

test("field name is the one the stamp component writes", () => {
  assert.equal(INSTANCE_FIELD, "_instance");
});
