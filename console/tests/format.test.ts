import { test } from "node:test";
import assert from "node:assert/strict";
import {
  fmtCost,
  fmtNum,
  fmtCompact,
  fmtDate,
  fmtWordCount,
  fmtPercent,
  rangeDays,
  isWithinDays,
  csvEscape,
  scopeLabel,
} from "../lib/format.ts";

test("fmtCost handles null/zero/four decimals", () => {
  assert.equal(fmtCost(null), "—");
  assert.equal(fmtCost(0), "—");
  assert.equal(fmtCost(0.0912), "$0.0912");
});

test("fmtNum formats integers", () => {
  assert.equal(fmtNum(1234), "1,234");
  assert.equal(fmtNum(null), "—");
});

test("fmtCompact scales", () => {
  assert.equal(fmtCompact(1_500_000), "1.50M");
  assert.equal(fmtCompact(1500), "1.5k");
  assert.equal(fmtCompact(42), "42");
});

test("fmtDate slices iso", () => {
  assert.equal(fmtDate("2026-10-18T09:21:42+00:00"), "2026-10-18");
  assert.equal(fmtDate(null), "—");
});

test("fmtWordCount", () => {
  assert.equal(fmtWordCount(724), "724 words");
  assert.equal(fmtWordCount(0), "—");
  assert.equal(fmtWordCount(null), "—");
});

test("fmtPercent", () => {
  assert.equal(fmtPercent(12.345), "12.3%");
  assert.equal(fmtPercent(null), "—");
});

test("rangeDays", () => {
  assert.equal(rangeDays("24h"), 1);
  assert.equal(rangeDays("7d"), 7);
  assert.equal(rangeDays("30d"), 30);
  assert.equal(rangeDays("90d"), 90);
  assert.equal(rangeDays("qtd"), 65);
  assert.equal(rangeDays(undefined), 30);
});

test("isWithinDays", () => {
  const now = Date.parse("2026-10-20T00:00:00Z");
  assert.equal(isWithinDays("2026-10-19T12:00:00Z", 2, now), true);
  assert.equal(isWithinDays("2026-09-01T00:00:00Z", 2, now), false);
  assert.equal(isWithinDays(null, 2), false);
});

test("csvEscape", () => {
  assert.equal(csvEscape('a"b'), '"a""b"');
});

test("scopeLabel", () => {
  assert.equal(scopeLabel("acme"), "Scoped to acme");
  assert.equal(scopeLabel(""), "All sites (fleet)");
});