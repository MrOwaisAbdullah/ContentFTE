import { test } from "node:test";
import assert from "node:assert/strict";
import { resolveScope } from "../lib/site-scope.ts";

test("resolveScope explicit slug", () => {
  const r = resolveScope([{ slug: "a" }, { slug: "b" }], "b");
  assert.equal(r.slug, "b");
  assert.equal(r.explicit, true);
});

test("resolveScope single site auto", () => {
  const r = resolveScope([{ slug: "only" }], "");
  assert.equal(r.slug, "only");
  assert.equal(r.singleSite, true);
});

test("resolveScope multi site no selection", () => {
  const r = resolveScope([{ slug: "a" }, { slug: "b" }], "");
  assert.equal(r.slug, "");
  assert.equal(r.singleSite, false);
});

test("resolveScope unknown slug", () => {
  const r = resolveScope([{ slug: "a" }, { slug: "b" }], "zzz");
  assert.equal(r.slug, "");
  assert.equal(r.explicit, false);
});