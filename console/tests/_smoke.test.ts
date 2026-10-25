import { test } from "node:test";
import assert from "node:assert/strict";
import { fmtCost } from "../lib/format.ts";

test("fmtCost null -> em dash", () => {
  assert.equal(fmtCost(null), "—");
});