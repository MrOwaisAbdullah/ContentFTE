"""Plan SEC-03: per-site API keys. A key for site A must never read, change or even confirm the
existence of site B's data, and must not exceed its scopes.

The matrix below drives EVERY route in sdk/authz.ROUTES as a site-A key against site-B resources.
"""
from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from sdk import authz, keys
from sdk.server import router

MASTER = "master-secret-key"
ALL = ["read", "write", "approve", "publish", "admin"]


@pytest.fixture
def world(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'iso.db'}")
    monkeypatch.setenv("SDK_MASTER_KEY", MASTER)
    monkeypatch.delenv("SDK_ALLOW_UNAUTHENTICATED", raising=False)
    import lib.db as db
    if db._engine is not None:
        db._engine.dispose()
    db._engine = None
    db._SessionLocal = None
    from sdk import service
    service.init()

    app = FastAPI()
    app.include_router(router)
    client = TestClient(app, raise_server_exceptions=False)

    from lib.db import Article, KeywordLedger, get_session
    ids: dict = {}
    for slug in ("site-a", "site-b"):
        service.upsert_site(slug, slug.upper(), "custom", f"https://{slug}.test", {"require_approval": False})
        art = service.submit_article(slug, keyword=f"{slug} keyword")
        s = get_session()
        try:
            a = s.get(Article, art["id"])
            a.content_md, a.status, a.title = f"Body of {slug}.", "drafted", f"Post {slug}"
            kw = s.get(KeywordLedger, a.keyword_id)
            ids[slug] = {"article": a.id, "keyword": kw.id}
            s.commit()
        finally:
            s.close()

    mint = lambda slug, scopes, label="": keys.create_site_key(slug, label=label, scopes=scopes)["key"]  # noqa: E731
    w = {
        "client": client, "service": service, "ids": ids,
        "a_all": mint("site-a", ALL, "a-all"), "a_read": mint("site-a", ["read"], "a-read"),
        "b_all": mint("site-b", ALL, "b-all"),
    }
    yield w
    if db._engine is not None:
        db._engine.dispose()
    db._engine = None
    db._SessionLocal = None


def H(key):
    return {"X-Site-Key": key}


# --------------------------------------------------------------------------- table <-> router
def test_every_route_is_classified_and_nothing_stale():
    actual = {(m, r.path) for r in router.routes for m in r.methods - {"HEAD", "OPTIONS"}}
    assert actual - set(authz.ROUTES) == set(), "route(s) missing from sdk/authz.ROUTES (site keys would be refused)"
    assert set(authz.ROUTES) - actual == set(), "stale ROUTES entry for a route that no longer exists"


# --------------------------------------------------------------------------- the matrix
def _fill(template: str, ids: dict) -> str:
    b = ids["site-b"]
    return (template.replace("{article_id}", str(b["article"])).replace("{keyword_id}", str(b["keyword"]))
            .replace("{site_slug}", "site-b").replace("{name}", "x.png").replace("{key_id}", "1")
            .replace("{stage}", "content").replace("{post_id}", "1"))


BODIES = {
    "approve": {"approved": True, "force": True}, "publish": {"mode": "draft", "force": True},
    "content": {"content_md": "HIJACKED"}, "meta": {"title": "HIJACKED"},
    "build": {}, "generate": {}, "keys": {"label": "x"}, "sites": {"slug": "site-b", "name": "HIJACKED"},
    "elementor": {"elements": []}, "test-connection": {},
}


def _body_for(template: str):
    for k, v in BODIES.items():
        if template.rstrip("/").endswith("/" + k) or f"/{k}/" in template or template.endswith(k):
            return v
    return {}


FOREIGN_RULES = [(m, t, r) for (m, t), (r, _) in authz.ROUTES.items()
                 if r in (authz.ARTICLE, authz.KEYWORD, authz.SITE_PATH, authz.PLATFORM)]


@pytest.mark.parametrize("method,template,kind", FOREIGN_RULES,
                         ids=[f"{m} {t.removeprefix('/sdk/v1')}" for m, t, _ in FOREIGN_RULES])
def test_site_a_key_is_refused_on_site_b_resources_and_nothing_changes(world, method, template, kind):
    path = _fill(template, world["ids"])
    kwargs = {"headers": H(world["a_all"])}
    if method in ("POST", "PATCH", "PUT"):
        kwargs["json"] = _body_for(template)
    r = world["client"].request(method, path, **kwargs)
    assert r.status_code in (403, 404), f"{method} {path} -> {r.status_code} {r.text[:120]}"
    # the foreign article/site is untouched
    from lib.db import Article, Site, get_session
    s = get_session()
    try:
        art = s.get(Article, world["ids"]["site-b"]["article"])
        assert art is not None and art.title == "Post site-b" and art.content_md == "Body of site-b."
        assert s.query(Site).filter_by(slug="site-b").count() == 1
    finally:
        s.close()


def test_foreign_articles_look_exactly_like_missing_ones(world):
    c, ids = world["client"], world["ids"]
    foreign = c.get(f"/sdk/v1/articles/{ids['site-b']['article']}", headers=H(world["a_all"]))
    missing = c.get("/sdk/v1/articles/999999", headers=H(world["a_all"]))
    assert foreign.status_code == 404
    assert foreign.json()["detail"].replace(str(ids["site-b"]["article"]), "N") \
        == missing.json()["detail"].replace("999999", "N")           # no existence oracle


# --------------------------------------------------------------------------- SELF routes
def test_own_resources_work(world):
    c, ids = world["client"], world["ids"]
    r = c.get(f"/sdk/v1/articles/{ids['site-a']['article']}", headers=H(world["a_all"]))
    assert r.status_code == 200 and r.json()["title"] == "Post site-a"
    assert c.get("/sdk/v1/sites/site-a/queue", headers=H(world["a_all"])).status_code == 200
    assert c.get(f"/sdk/v1/articles/{ids['site-a']['article']}/gate", headers=H(world["a_all"])).status_code == 200


def test_listing_is_pinned_to_the_keys_site(world):
    c = world["client"]
    own = c.get("/sdk/v1/articles", headers=H(world["a_all"]))
    assert own.status_code == 200 and {a["site_slug"] for a in own.json()["articles"]} == {"site-a"}
    assert c.get("/sdk/v1/articles?site_slug=site-b", headers=H(world["a_all"])).status_code == 403
    assert c.get("/sdk/v1/articles/stats?site_slug=site-b", headers=H(world["a_all"])).status_code == 403
    assert c.get("/sdk/v1/spend/summary?site_slug=site-b", headers=H(world["a_all"])).status_code == 403
    # the platform key still sees both
    both = c.get("/sdk/v1/articles", headers=H(MASTER)).json()["articles"]
    assert {a["site_slug"] for a in both} == {"site-a", "site-b"}


def test_stats_and_spend_default_to_own_site_when_unspecified(world):
    c = world["client"]
    stats = c.get("/sdk/v1/articles/stats", headers=H(world["a_all"]))
    assert stats.status_code == 200 and stats.json()["site_slug"] == "site-a"
    assert c.get("/sdk/v1/spend/summary", headers=H(world["a_all"])).status_code == 200


def test_list_sites_shows_only_the_keys_own_site(world):
    c = world["client"]
    assert [s["slug"] for s in c.get("/sdk/v1/sites", headers=H(world["a_all"])).json()["sites"]] == ["site-a"]
    assert {s["slug"] for s in c.get("/sdk/v1/sites", headers=H(MASTER)).json()["sites"]} == {"site-a", "site-b"}


def test_submitting_is_pinned_to_the_keys_site(world):
    c = world["client"]
    foreign = c.post("/sdk/v1/articles", headers=H(world["a_all"]),
                     json={"site_slug": "site-b", "keyword": "sneaky"})
    assert foreign.status_code == 403
    own = c.post("/sdk/v1/articles", headers=H(world["a_all"]), json={"site_slug": "site-a", "keyword": "legit"})
    assert own.status_code == 200
    from lib.db import Article, get_session
    s = get_session()
    try:
        assert s.get(Article, own.json()["id"]).site.slug == "site-a"
        assert s.query(Article).filter(Article.title == "sneaky").count() == 0
    finally:
        s.close()


# --------------------------------------------------------------------------- scopes
def test_a_read_key_cannot_write_approve_publish_or_delete(world):
    c, aid = world["client"], world["ids"]["site-a"]["article"]
    rk = H(world["a_read"])
    assert c.get(f"/sdk/v1/articles/{aid}", headers=rk).status_code == 200
    assert c.get(f"/sdk/v1/articles/{aid}/content", headers=rk).status_code == 200
    for method, path, body, scope in [
        ("PATCH", f"/sdk/v1/articles/{aid}/content", {"content_md": "x"}, "write"),
        ("POST", f"/sdk/v1/articles/{aid}/approve", {"approved": True}, "approve"),
        ("POST", f"/sdk/v1/articles/{aid}/publish", {}, "publish"),
        ("DELETE", f"/sdk/v1/articles/{aid}", None, "admin"),
        ("POST", "/sdk/v1/articles", {"site_slug": "site-a", "keyword": "k"}, "write"),
    ]:
        r = c.request(method, path, headers=rk, **({"json": body} if body is not None else {}))
        assert r.status_code == 403 and scope in r.json()["detail"], (method, path, r.text)


def test_scope_implication_rules():
    from sdk.auth import AuthContext
    admin = AuthContext(kind="site", site_slug="s", scopes=frozenset({"admin"}))
    assert all(admin.allows(x) for x in ("read", "write", "approve", "publish", "admin"))
    approver = AuthContext(kind="site", site_slug="s", scopes=frozenset({"approve"}))
    assert approver.allows("read") and approver.allows("approve")
    assert not approver.allows("write") and not approver.allows("publish")
    assert not AuthContext(kind="site", site_slug="s", scopes=frozenset()).allows("read")


# --------------------------------------------------------------------------- platform-only + mgmt
def test_site_keys_cannot_mint_or_manage_keys(world):
    c = world["client"]
    for method, path, body in [("POST", "/sdk/v1/sites/site-a/keys", {"scopes": ["admin"]}),
                               ("GET", "/sdk/v1/sites/site-a/keys", None),
                               ("DELETE", "/sdk/v1/sites/site-a/keys/1", None)]:
        r = c.request(method, path, headers=H(world["a_all"]), **({"json": body} if body else {}))
        assert r.status_code == 403, (method, path)


def test_key_lifecycle_create_list_use_revoke(world):
    c = world["client"]
    made = c.post("/sdk/v1/sites/site-a/keys", headers=H(MASTER),
                  json={"label": "marketing site", "scopes": ["read", "publish"]})
    assert made.status_code == 200
    body = made.json()
    assert body["key"].startswith("cfte_") and body["scopes"] == ["read", "publish"] and "once" in body["note"]
    assert body["prefix"] == body["key"][:12]

    listing = c.get("/sdk/v1/sites/site-a/keys", headers=H(MASTER)).json()
    row = next(k for k in listing["keys"] if k["id"] == body["id"])
    flat = repr(listing)
    assert body["key"] not in flat and "key_hash" not in flat and row["active"] is True

    from lib.db import ApiKey, get_session
    s = get_session()
    try:
        stored = s.get(ApiKey, body["id"])
        assert stored.key_hash != body["key"] and len(stored.key_hash) == 64     # only the hash is stored
        assert body["key"] not in (stored.key_hash, stored.prefix, stored.label)
    finally:
        s.close()

    assert c.get("/sdk/v1/sites/site-a/health", headers=H(body["key"])).status_code in (200, 404)  # works
    assert c.delete(f"/sdk/v1/sites/site-a/keys/{body['id']}", headers=H(MASTER)).json()["revoked"] is True
    assert c.get("/sdk/v1/sites/site-a/health", headers=H(body["key"])).status_code == 401      # dead at once


def test_revoking_another_sites_key_id_is_not_found(world):
    c = world["client"]
    other = c.post("/sdk/v1/sites/site-b/keys", headers=H(MASTER), json={}).json()
    r = c.delete(f"/sdk/v1/sites/site-a/keys/{other['id']}", headers=H(MASTER))
    assert r.status_code == 404
    assert c.get("/sdk/v1/sites/site-b/health", headers=H(other["key"])).status_code in (200, 404)  # still alive


def test_unknown_scope_and_unknown_site_are_rejected(world):
    c = world["client"]
    assert c.post("/sdk/v1/sites/site-a/keys", headers=H(MASTER), json={"scopes": ["root"]}).status_code == 400
    assert c.post("/sdk/v1/sites/nope/keys", headers=H(MASTER), json={}).status_code == 404


def test_default_scope_is_read_only(world):
    made = world["client"].post("/sdk/v1/sites/site-a/keys", headers=H(MASTER), json={}).json()
    assert made["scopes"] == ["read"]


# --------------------------------------------------------------------------- authentication edges
def test_bad_keys_are_401_and_the_master_key_still_works(world):
    c = world["client"]
    assert c.get("/sdk/v1/sites").status_code == 401
    assert c.get("/sdk/v1/sites", headers=H("cfte_" + "A" * 43)).status_code == 401      # well-formed, unknown
    assert c.get("/sdk/v1/sites", headers=H("garbage")).status_code == 401
    assert c.get("/sdk/v1/sites", headers=H(MASTER)).status_code == 200


def test_site_keys_are_not_accepted_on_mcp(world, monkeypatch):
    from starlette.responses import PlainTextResponse
    from sdk.auth import KeyAuthMiddleware

    async def inner(scope, receive, send):
        if scope["type"] == "http":
            await PlainTextResponse("reached")(scope, receive, send)

    app = FastAPI()
    app.mount("/mcp", KeyAuthMiddleware(inner))
    c = TestClient(app)
    assert c.post("/mcp/", json={}, headers=H(world["a_all"])).status_code == 401   # MCP bypasses REST scoping
    assert c.post("/mcp/", json={}, headers=H(MASTER)).text == "reached"


def test_site_keys_work_even_when_no_master_key_is_configured(world, monkeypatch):
    monkeypatch.delenv("SDK_MASTER_KEY", raising=False)
    c = world["client"]
    assert c.get("/sdk/v1/sites", headers=H(world["a_all"])).status_code == 200
    assert c.get("/sdk/v1/sites").status_code == 503            # platform door stays closed


# --------------------------------------------------------------------------- housekeeping
def test_deleting_a_site_deletes_its_keys(world):
    c = world["client"]
    key = world["b_all"]
    assert c.delete("/sdk/v1/sites/site-b", headers=H(MASTER)).status_code == 200
    from lib.db import ApiKey, get_session
    s = get_session()
    try:
        assert s.query(ApiKey).filter(ApiKey.key_hash == keys.hash_key(key)).count() == 0
    finally:
        s.close()
    assert c.get("/sdk/v1/sites", headers=H(key)).status_code == 401


def test_list_sites_reports_active_key_counts(world):
    sites = {s["slug"]: s for s in world["client"].get("/sdk/v1/sites", headers=H(MASTER)).json()["sites"]}
    assert sites["site-a"]["active_keys"] == 2 and sites["site-a"]["has_key"] is True
    assert sites["site-b"]["active_keys"] == 1


def test_idempotency_is_not_shared_between_sites(world):
    c = world["client"]
    a = c.post("/sdk/v1/articles", headers={**H(world["a_all"]), "Idempotency-Key": "k1"},
               json={"site_slug": "site-a", "keyword": "same"}).json()
    b = c.post("/sdk/v1/articles", headers={**H(world["b_all"]), "Idempotency-Key": "k1"},
               json={"site_slug": "site-b", "keyword": "same"}).json()
    assert a["id"] != b["id"]
    again = c.post("/sdk/v1/articles", headers={**H(world["a_all"]), "Idempotency-Key": "k1"},
                   json={"site_slug": "site-a", "keyword": "same"}).json()
    assert again["id"] == a["id"]                                 # replay within a site still dedupes


def test_last_used_is_recorded_and_throttled(world):
    from datetime import datetime, timezone
    from lib.db import ApiKey, get_session
    kh = keys.hash_key(world["a_all"])
    s = get_session()
    try:
        assert s.query(ApiKey).filter_by(key_hash=kh).one().last_used_at is None
    finally:
        s.close()
    world["client"].get("/sdk/v1/sites", headers=H(world["a_all"]))
    s = get_session()
    try:
        first = s.query(ApiKey).filter_by(key_hash=kh).one().last_used_at
        assert first is not None
    finally:
        s.close()
    world["client"].get("/sdk/v1/sites", headers=H(world["a_all"]))
    s = get_session()
    try:
        assert s.query(ApiKey).filter_by(key_hash=kh).one().last_used_at == first   # not rewritten each call
    finally:
        s.close()


# --------------------------------------------------------------------------- canaries
def test_canary_the_matrix_would_catch_a_missing_ownership_check(world, monkeypatch):
    """Prove the tests above can fail: with the ownership lookup disabled, a site-A key DOES read
    site B's article. If this ever stops being true the matrix is no longer testing anything."""
    monkeypatch.setattr(authz, "_owner_of_article", lambda _id: None)
    aid_b = world["ids"]["site-b"]["article"]
    r = world["client"].get(f"/sdk/v1/articles/{aid_b}", headers=H(world["a_all"]))
    assert r.status_code == 200 and r.json()["title"] == "Post site-b"


def test_canary_unlisted_routes_default_to_denied_for_site_keys(world, monkeypatch):
    """A new endpoint nobody classified must be unreachable with a site key (fail closed)."""
    monkeypatch.delitem(authz.ROUTES, ("GET", "/sdk/v1/sites"))
    assert world["client"].get("/sdk/v1/sites", headers=H(world["a_all"])).status_code == 403
    assert world["client"].get("/sdk/v1/sites", headers=H(MASTER)).status_code == 200   # platform unaffected
