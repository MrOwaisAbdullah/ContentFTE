"""Per-image regenerate (spec §5.9 follow-up): ``service.regenerate_article_image``
+ ``POST /sdk/v1/articles/{id}/images/{name}/regenerate``.

Fully offline: the generation/stock hooks are monkeypatched at the tools layer
(``tools.tools._generate_image`` / ``_select_inpost_image``) and the conftest
guard keeps provider credentials out of CI. The article's own meta.images rows
are the allowlist — the same rule as the image-serving route.
"""
import os

import pytest


@pytest.fixture(autouse=True)
def _isolated_db(monkeypatch):
    workdir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                           ".test-tmp-regen")
    os.makedirs(workdir, exist_ok=True)
    db_file = os.path.join(workdir, "regen.db")
    try:
        os.remove(db_file)
    except OSError:
        pass
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db_file}")
    monkeypatch.delenv("SDK_MASTER_KEY", raising=False)
    import lib.db as db

    if db._engine is not None:
        db._engine.dispose()
    db._engine = None
    db._SessionLocal = None
    from sdk import service

    service.init()
    yield
    if db._engine is not None:
        db._engine.dispose()
    try:
        os.remove(db_file)
    except OSError:
        pass


def _client():
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from sdk.server import router

    app = FastAPI()
    app.include_router(router)
    return TestClient(app)


def _seed(tmp_path):
    """Site + article carrying one featured and one inpost staged row."""
    from lib.db import Article as ArticleModel, get_session
    from sdk import service

    feat = tmp_path / "old_featured.png"
    feat.write_bytes(b"old-featured-pixels")
    inp = tmp_path / "old_inpost.png"
    inp.write_bytes(b"old-inpost-pixels")

    service.upsert_site("regen-site", name="Regen")
    aid = service.submit_article("regen-site", keyword="regen kw")["id"]
    s = get_session()
    try:
        row = s.get(ArticleModel, aid)
        meta = dict(row.meta or {})
        meta["keyword"] = "regen kw"
        meta["summary"] = "A summary used for prompts."
        meta["images"] = [
            {"slot": "featured", "path": str(feat), "alt": "old featured alt",
             "cost_usd": 0.01, "qa": {"passed": False}},
            {"slot": "inpost", "path": str(inp), "alt": "inline old alt",
             "after_h2": 2, "cost_usd": 0.0},
        ]
        row.meta = meta
        row.content_md = ("## Intro\n\nIntro text about the topic.\n\n"
                          "## Section Two\n\nBody of section two.\n\n"
                          "## Section Three\n\nBody of section three.")
        s.commit()
    finally:
        s.close()
    return aid, feat, inp


def test_regenerate_featured_replaces_row_and_records_cost(tmp_path, monkeypatch):
    from sqlalchemy import select

    import tools.tools as tools_mod
    from lib.db import Article as ArticleModel, AuditLog, CostLedger, get_session
    from sdk import service

    aid, feat, _ = _seed(tmp_path)
    staging = tmp_path / "staging"
    monkeypatch.setenv("IMAGE_STAGING_DIR", str(staging))
    monkeypatch.setenv("CLOUDFLARE_API_TOKEN", "test-token")
    new_src = tmp_path / "generated.png"
    new_src.write_bytes(b"new-featured-pixels")

    captured: dict = {}

    def fake_generate(**kwargs):
        captured.update(kwargs)
        return {"image_url": str(new_src), "cost_usd": 0.05,
                "source": "cloudflare", "qa": {"passed": True, "matches_blog": 0.9}}

    monkeypatch.setattr(tools_mod, "_generate_image", fake_generate)

    res = service.regenerate_article_image(aid, feat.name)
    assert res["featured"] is True and res["inpost"] == 0
    assert res["errors"] == []
    assert "regenerated" in res["detail"] and "cost=$0.0500" in res["detail"]
    # same prompt context as stage-images uses for a featured image
    assert captured["slot"] == "featured"
    assert captured["keyword"] == "regen kw"

    s = get_session()
    try:
        row = s.get(ArticleModel, aid)
        img = row.meta["images"][0]
        assert img["slot"] == "featured"
        # staged copy replaced in place under the same stable name
        assert img["path"].endswith(f"article{aid}_featured.png")
        assert img["path"].startswith(str(staging))
        assert open(img["path"], "rb").read() == b"new-featured-pixels"
        # cost + QA overwritten from the new result
        assert img["cost_usd"] == 0.05
        assert img["qa"]["passed"] is True
        # audit row records the regenerate (ok + slot)
        audits = s.execute(select(AuditLog).where(
            AuditLog.action == "article.images")).scalars().all()
        assert any(a.payload.get("event") == "article.images_regenerated"
                   and a.payload.get("ok") is True
                   and a.payload.get("slot") == "featured" for a in audits)
        # the new spend lands in the cost ledger
        costs = s.execute(select(CostLedger).where(
            CostLedger.article_id == aid,
            CostLedger.kind == "image")).scalars().all()
        assert any(abs(c.amount_usd - 0.05) < 1e-9 for c in costs)
    finally:
        s.close()


def test_regenerate_inpost_targets_row_section_and_keeps_anchor(tmp_path, monkeypatch):
    import tools.tools as tools_mod
    from lib.db import Article as ArticleModel, get_session
    from sdk import service

    aid, _, inp = _seed(tmp_path)
    monkeypatch.setenv("IMAGE_STAGING_DIR", str(tmp_path / "staging"))
    monkeypatch.setenv("PEXELS_API_KEY", "test-key")
    new_src = tmp_path / "stock.png"
    new_src.write_bytes(b"stock-pixels")

    captured: dict = {}

    def fake_select(**kwargs):
        captured.update(kwargs)
        return {"image_url": str(new_src), "cost_usd": 0.0,
                "qa": {"passed": True, "style_pick": "editorial-3d"}}

    monkeypatch.setattr(tools_mod, "_select_inpost_image", fake_select)

    res = service.regenerate_article_image(aid, inp.name)
    assert res["inpost"] == 1 and res["featured"] is False
    # the row's own after_h2 pointed at the SECOND H2 — not the whole title
    assert captured["topic"] == "Section Two"
    assert "Body of section two." in captured["section_summary"]
    assert captured["alt_text"] == "inline old alt"

    s = get_session()
    try:
        row = s.get(ArticleModel, aid)
        img = row.meta["images"][1]
        # anchor + alt survive; path + QA swap in place
        assert img["after_h2"] == 2
        assert img["alt"] == "inline old alt"
        assert img["path"].endswith(f"article{aid}_inpost.png")
        assert open(img["path"], "rb").read() == b"stock-pixels"
        assert img["qa"]["style_pick"] == "editorial-3d"
    finally:
        s.close()


def test_regenerate_remote_stock_row_switches_to_url(tmp_path, monkeypatch):
    import tools.tools as tools_mod
    from lib.db import Article as ArticleModel, get_session
    from sdk import service

    aid, _, inp = _seed(tmp_path)
    monkeypatch.setenv("PEXELS_API_KEY", "test-key")
    monkeypatch.setattr(tools_mod, "_select_inpost_image",
                        lambda **kw: {"image_url": "https://cdn.example/stock.jpg",
                                      "cost_usd": 0.0, "qa": {"passed": True}})

    res = service.regenerate_article_image(aid, inp.name)
    assert res["inpost"] == 1

    s = get_session()
    try:
        row = s.get(ArticleModel, aid)
        img = row.meta["images"][1]
        # remote-only rows carry `url`, never a fake local `path`
        assert "path" not in img
        assert img["url"] == "https://cdn.example/stock.jpg"
        assert img["after_h2"] == 2
    finally:
        s.close()


def test_regenerate_unknown_name_and_no_creds_skip(tmp_path):
    from sdk import service

    aid, feat, _ = _seed(tmp_path)
    # conftest cleared CLOUDFLARE_API_TOKEN / PEXELS_API_KEY: skip cleanly
    res = service.regenerate_article_image(aid, feat.name)
    assert "no image provider credentials" in res.get("skipped", "")
    # the allowlist check runs first — an unknown name is an error regardless
    res2 = service.regenerate_article_image(aid, "nope.png")
    assert "error" in res2 and "not found" in res2["error"]

    client = _client()
    skip = client.post(f"/sdk/v1/articles/{aid}/images/{feat.name}/regenerate")
    assert skip.status_code == 200
    assert "no image provider credentials" in skip.json().get("skipped", "")
    bad = client.post(f"/sdk/v1/articles/{aid}/images/nope.png/regenerate")
    assert bad.status_code == 404
    assert "not found" in bad.json()["detail"]


def test_regenerate_route_returns_cost_detail(tmp_path, monkeypatch):
    import tools.tools as tools_mod

    aid, feat, _ = _seed(tmp_path)
    monkeypatch.setenv("IMAGE_STAGING_DIR", str(tmp_path / "staging"))
    monkeypatch.setenv("CLOUDFLARE_API_TOKEN", "test-token")
    new_src = tmp_path / "gen2.png"
    new_src.write_bytes(b"px")
    monkeypatch.setattr(tools_mod, "_generate_image",
                        lambda **kw: {"image_url": str(new_src), "cost_usd": 0.02})

    client = _client()
    res = client.post(f"/sdk/v1/articles/{aid}/images/{feat.name}/regenerate")
    assert res.status_code == 200
    body = res.json()
    assert body["featured"] is True
    assert "cost=$0.0200" in body["detail"]
