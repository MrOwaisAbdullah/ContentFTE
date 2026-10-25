import { test } from "node:test";
import assert from "node:assert/strict";
import { normalizeScores, qualityLabel, scoreBand, gateStatus } from "../lib/scores.ts";

test("normalizeScores legacy quality key", () => {
  const s = normalizeScores({ quality: 94.0 });
  assert.equal(s.overall, 94.0);
  assert.equal(s.hasSubScores, false);
});

test("normalizeScores eval-gated shape", () => {
  const s = normalizeScores({ overall: 88, sub_scores: { accuracy: 90, depth: 85 } });
  assert.equal(s.overall, 88);
  assert.equal(s.subScores.accuracy, 90);
});

test("normalizeScores handles null/undefined", () => {
  assert.equal(normalizeScores(null).overall, null);
  assert.equal(normalizeScores(undefined).overall, null);
});

test("qualityLabel legacy", () => {
  const s = normalizeScores({ quality: 94.0 });
  assert.match(qualityLabel(s, "approved"), /94\/100/);
  assert.match(qualityLabel(s, "approved"), /sub-scores not recorded/);
});

test("qualityLabel null", () => {
  const s = normalizeScores(null);
  assert.equal(qualityLabel(s, "published"), "Not scored (legacy run)");
  assert.equal(qualityLabel(s, "drafted"), "Not scored");
});

test("scoreBand", () => {
  assert.equal(scoreBand(95), "pass");
  assert.equal(scoreBand(80), "warn");
  assert.equal(scoreBand(70), "fail");
});

test("gateStatus", () => {
  assert.equal(gateStatus(null, {}), "unknown");
  assert.equal(gateStatus(95, { accuracy: 75 }), "not_clear");
  assert.equal(gateStatus(95, { accuracy: 85, depth: 90, seo: 90, voice: 90, originality: 90, citability: 90 }), "clear");
});