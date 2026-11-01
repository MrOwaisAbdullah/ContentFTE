import { test } from "node:test";
import assert from "node:assert/strict";
import {
  formBool,
  formEnum,
  formInt,
  formText,
  mergeGroup,
  redactSettings,
  redactSiteList,
} from "../lib/site-secrets.ts";

const RAW = {
  posting_frequency: "daily",
  max_posts_per_cadence: 2,
  wp: { base_url: "https://x.test", username: "editor", app_password: "abcd efgh ijkl" },
  indexing: { auto_index_on_publish: true, indexnow_key: "k1", bing_wmt_key: "k2", search_console_property: "sc-domain:x.test" },
  notifications: { discord_webhook_url: "https://discord.com/api/webhooks/1/abc", notify_on_publish: true },
};

test("redactSettings strips known secrets and reports which are set", () => {
  const { settings, secretsSet } = redactSettings(RAW);
  assert.equal(JSON.stringify(settings).includes("abcd efgh"), false);
  assert.equal(JSON.stringify(settings).includes("webhooks/1/abc"), false);
  assert.equal(settings.wp.username, "editor"); // non-secret survives
  assert.equal(settings.indexing.search_console_property, "sc-domain:x.test");
  assert.equal(settings.max_posts_per_cadence, 2);
  assert.deepEqual(secretsSet, {
    wp_app_password: true,
    indexnow_key: true,
    bing_wmt_key: true,
    discord_webhook_url: true,
  });
});

test("redactSettings flags missing/blank secrets as false", () => {
  const { secretsSet } = redactSettings({ wp: { app_password: "  " }, indexing: {} });
  assert.equal(secretsSet.wp_app_password, false);
  assert.equal(secretsSet.indexnow_key, false);
  assert.equal(redactSettings(null).secretsSet.discord_webhook_url, false);
});

test("redactSettings scrubs unknown secret-looking string keys but keeps numeric config", () => {
  const { settings } = redactSettings({
    image: { vlm_model: "qwen", provider_api_key: "sk-123", max_tokens: 512 },
    extra: { client_secret: "s3", nested: [{ access_token: "t" }] },
  });
  assert.equal("provider_api_key" in settings.image, false);
  assert.equal(settings.image.max_tokens, 512);
  assert.equal(settings.image.vlm_model, "qwen");
  assert.equal("client_secret" in settings.extra, false);
  assert.equal("access_token" in settings.extra.nested[0], false);
});

test("redactSiteList redacts every site and leaves other shapes alone", () => {
  const out = redactSiteList({ count: 1, sites: [{ slug: "a", settings: RAW }] });
  assert.equal(JSON.stringify(out).includes("abcd efgh"), false);
  assert.equal(out.sites[0].secrets_set.wp_app_password, true);
  const other = { articles: [{ id: 1, settings: { token: "keep-me" } }] };
  assert.deepEqual(redactSiteList(other), other);
  assert.equal(redactSiteList(null), null);
});

test("mergeGroup keeps stored secret when the input is blank or absent", () => {
  const cur = RAW.wp;
  const out = mergeGroup(cur, { username: "new", app_password: "" }, { secrets: ["app_password"] });
  assert.equal(out.app_password, "abcd efgh ijkl");
  assert.equal(out.username, "new");
  const out2 = mergeGroup(cur, { username: undefined, app_password: undefined }, { secrets: ["app_password"] });
  assert.deepEqual(out2, cur);
});

test("mergeGroup replaces a secret when a new value is typed, and clears on request", () => {
  const out = mergeGroup(RAW.wp, { app_password: "fresh" }, { secrets: ["app_password"] });
  assert.equal(out.app_password, "fresh");
  const cleared = mergeGroup(RAW.wp, {}, { clear: ["app_password"] });
  assert.equal(cleared.app_password, null); // null = "remove" for the deep-merging engine
  assert.equal(cleared.base_url, "https://x.test");
});

test("redactSiteList keeps the engine's secrets_set once the engine has already stripped the values", () => {
  const out = redactSiteList({
    sites: [{ slug: "a", settings: { wp: { username: "u" } }, secrets_set: { wp_app_password: true } }],
  });
  assert.equal(out.sites[0].secrets_set.wp_app_password, true);
  assert.equal(out.sites[0].secrets_set.indexnow_key, false);
  assert.equal(out.sites[0].settings.wp.username, "u");
});

test("mergeGroup does not mutate its input and tolerates a missing group", () => {
  const cur = { a: 1 };
  mergeGroup(cur, { a: 2 });
  assert.equal(cur.a, 1);
  assert.deepEqual(mergeGroup(undefined, { a: 2 }), { a: 2 });
});

test("form helpers: absent fields are undefined, values are clamped/allow-listed", () => {
  const fd = new FormData();
  fd.set("n", "9999");
  fd.set("bad", "abc");
  fd.set("mode", "publish");
  fd.set("evil", "../../etc");
  fd.set("t", "  hi  ");
  fd.set("flag", "1");
  assert.equal(formInt(fd, "n", 1, 50), 50);
  assert.equal(formInt(fd, "bad", 1, 50), undefined);
  assert.equal(formInt(fd, "missing", 1, 50), undefined);
  assert.equal(formEnum(fd, "mode", ["draft", "publish"] as const), "publish");
  assert.equal(formEnum(fd, "evil", ["draft", "publish"] as const), undefined);
  assert.equal(formText(fd, "t"), "hi");
  assert.equal(formText(fd, "missing"), undefined);
  assert.equal(formBool(fd, "flag", true), true);
  assert.equal(formBool(fd, "unchecked", true), false); // submitted group, box unticked
  assert.equal(formBool(fd, "unchecked", false), undefined); // group not submitted → untouched
});
