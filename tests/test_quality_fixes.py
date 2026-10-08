"""Quality-fix batch: revise loop, staging, focus keyphrase, pricing, quota.

Covers the production defects found in the comparison run (short posts,
no first-try images, images after the FAQ, stale year, missing Yoast focus
keyphrase, no internal/external in-body links) plus the user-selected
tasks: per-post LLM cost pricing and the image-provider quota guard.

Everything runs offline: fakes for generate_fn and the image tools,
isolated sqlite DB, provider credentials stripped by tests/conftest.py.
"""
from __future__ import annotations

import asyncio
import json
import os

import pytest


@pytest.fixture(autouse=True)
def _isolated_db(monkeypatch):
    workdir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                           ".test-tmp-phase1")
    os.makedirs(workdir, exist_ok=True)
    db_file = os.path.join(workdir, "quality_fixes.db")
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
    try:
        os.remove(db_file)
    except OSError:
        pass
    from sdk import service

    service.init()
    yield
    if db._engine is not None:
        db._engine.dispose()
    try:
        os.remove(db_file)
    except OSError:
        pass


# ---------------------------------------------------------------------------
# Deterministic checks (sdk.service._content_checks / _content_sections)
# ---------------------------------------------------------------------------
def _long_body(*, with_sources=True, with_tldr=True, stale=False):
    parts = []
    if with_tldr:
        parts.append("> **TL;DR** - A direct quotable answer to the "
                     "primary keyword question in forty-ish words so "
                     "engines can lift it verbatim from the page.")
    parts.append("## What does the tool actually do?\n\n"
                 + "It automates the workflow end to end. " * 90)
    parts.append("## How do you choose between the options?\n\n"
                 + "Compare pricing, limits and integrations carefully. " * 90)
    if stale:
        parts.append("## What changed in 2025?\n\n"
                     + "Last year shipped a big release. " * 40)
    if with_sources:
        parts.append("## Sources\n\n- [Vendor docs](https://example.com/docs)")
    return "\n\n".join(parts)


def test_content_sections_excludes_trailing_sources_and_keeps_index():
    from sdk import service

    sections = service._content_sections(_long_body())
    assert [s["index"] for s in sections] == [1, 2]
    assert all("Sources" not in s["heading"] for s in sections)
    assert sections[0]["heading"].startswith("What does")


def test_content_sections_counts_faq_as_trailing_only():
    from sdk import service

    md = "## One\n\na\n\n## Frequently Asked Questions\n\n**Q?**\n\nA.\n\n## Two\n\nb"
    sections = service._content_sections(md)
    # FAQ heading is skipped as a target but Two keeps its absolute index
    assert [s["index"] for s in sections] == [1, 3]


def test_content_checks_pass_on_complete_draft():
    from sdk import service

    md = _long_body() + "\n\nSee [our guide](https://site.test/related) and " \
        "[the docs](https://vendor.test/docs)."
    checks = service._content_checks(
        content=md, title="Best Tool in 2026", summary="Short summary.",
        faqs=[{"question": "Q1", "answer": "A"},
              {"question": "Q2", "answer": "A"},
              {"question": "Q3", "answer": "A"}],
        brief={"internal_links": [{"title": "Guide", "url": "https://site.test/related"}],
               "site_base_url": "https://site.test",
               "sources": ["https://vendor.test/docs"]})
    assert service._checks_pass(checks), checks


def test_content_checks_flag_short_no_sources_no_faq_draft():
    from sdk import service

    checks = service._content_checks(
        content="Tiny draft.", title="T", summary="S" * 200,
        faqs=[{"question": "Q", "answer": "A"}], brief={})
    assert not checks["words"]["pass"]
    assert not checks["sources"]["pass"]
    assert not checks["faqs"]["pass"]
    assert not checks["tldr"]["pass"]
    assert not checks["summary"]["pass"]
    # no link candidates/sources in the brief -> those checks are absent
    assert "internal_links" not in checks and "external_links" not in checks
    assert not service._checks_pass(checks)


def test_content_checks_stale_year_and_link_floor():
    from sdk import service

    checks = service._content_checks(
        content=_long_body(stale=True), title="Best Tool in 2025",
        summary="ok", faqs=[{"question": str(i), "answer": "a"} for i in range(3)],
        brief={})
    assert not checks["stale_year"]["pass"]

    # candidates exist but content has none -> fail; one link each -> pass.
    # with_sources=False so the body itself carries no external URL (the
    # Sources link would otherwise make the "miss" case pass).
    brief = {"internal_links": [{"title": "a", "url": "https://site.test/a"}],
             "site_base_url": "https://site.test",
             "sources": ["https://vendor.test"]}
    base = _long_body(with_sources=False)
    miss = service._content_checks(content=base, title="ok 2026",
                                   summary="s", faqs=[], brief=brief)
    assert not miss["internal_links"]["pass"]
    assert not miss["external_links"]["pass"]
    hit = service._content_checks(
        content=base + "\n\nAlso [our take](https://site.test/a) and "
                       "[source](https://vendor.test/x).",
        title="ok", summary="s",
        faqs=[{"question": str(i), "answer": "a"} for i in range(3)],
        brief=brief)
    assert hit["internal_links"]["pass"] and hit["external_links"]["pass"]


def test_focus_keyphrase_prefers_submitted_keyword():
    from sdk import service

    assert service._focus_keyphrase({"keyword": "meta kw"}, {"keyword": "brief kw"}) == "brief kw"
    assert service._focus_keyphrase({"keyword": "meta kw"}, {}) == "meta kw"
    assert service._focus_keyphrase({}, {}) == ""


def test_merge_usage_sums_tokens_and_dedupes_models():
    from sdk import service

    merged = service._merge_usage(
        {"requests": 1, "input_tokens": 100, "output_tokens": 50,
         "total_tokens": 150, "models": ["gemini-3.5-flash"]},
        {"requests": 2, "input_tokens": 300, "output_tokens": 25,
         "total_tokens": 325, "models": ["gemini-3.5-flash", "deepseek-v4-flash"]})
    assert merged["requests"] == 3
    assert merged["input_tokens"] == 400
    assert merged["total_tokens"] == 475
    assert merged["models"] == ["gemini-3.5-flash", "deepseek-v4-flash"]
    assert service._merge_usage({}, {"requests": 1})["requests"] == 1
    assert service._merge_usage({}, None) == {}


# ---------------------------------------------------------------------------
# Revise loop (CONTENTFTE_REVISE=1): short first draft -> one feedback retry
# ---------------------------------------------------------------------------
_GOOD_ENVELOPE = {
    "status": "success",
    "Title": "Best CRM for Agencies in 2026",
    "Generated Content": _long_body(),
    "Summary": "The best CRM for agencies, compared on price and pipeline features.",
    "FAQs": json.dumps([{"question": f"Q{i}?", "answer": "Direct answer."}
                        for i in range(1, 5)]),
    "Quality Score": "92",
    "Claims Notes": "",
    "errors": [],
    "warnings": [],
}


def test_revise_loop_retries_short_draft_with_feedback(monkeypatch):
    from sdk import service

    monkeypatch.setenv("CONTENTFTE_REVISE", "1")
    monkeypatch.setenv("GEN_MIN_WORDS", "900")
    calls: list[dict] = []

    async def two_shot(brief):
        calls.append(dict(brief))
        if len(calls) == 1:
            # >=50 chars so it survives the envelope gate, but far below
            # the word floor / TL;DR / Sources / FAQ checks -> one retry
            return {"status": "success", "Title": "Short Draft",
                    "Generated Content": "## Tiny\n\n"
                    + "Too short to pass the quality gate. " * 3,
                    "Summary": "x", "FAQs": "[]", "Quality Score": "50"}
        return dict(_GOOD_ENVELOPE)

    art = service.submit_article("revise-site", keyword="revise kw")
    out = asyncio.run(service.generate_content(art["id"], generate_fn=two_shot))

    assert len(calls) == 2
    # second attempt got the failing checks fed back verbatim
    feedback = calls[1].get("revision_feedback") or []
    assert any("words" in fb for fb in feedback)
    assert out["revisions"] == 1
    assert out["needs_revision"] is False
    assert out["checks"]["words"]["pass"]
    assert "2025" not in out["title"]


def test_revise_off_keeps_single_shot(monkeypatch):
    from sdk import service

    monkeypatch.setenv("CONTENTFTE_REVISE", "0")
    calls = []

    async def one_shot(brief):
        calls.append(brief)
        return dict(_GOOD_ENVELOPE)

    art = service.submit_article("single-site", keyword="single kw")
    out = asyncio.run(service.generate_content(art["id"], generate_fn=one_shot))
    assert len(calls) == 1
    assert out["revisions"] == 0


def test_stale_title_year_fixed_mechanically(monkeypatch):
    from sdk import service

    monkeypatch.setenv("CONTENTFTE_REVISE", "0")
    env = dict(_GOOD_ENVELOPE)
    env["Title"] = "Best CRM Software in 2025"
    env["Generated Content"] = _long_body()  # body has no stale year

    async def fake(brief):
        return dict(env)

    art = service.submit_article("stale-site", keyword="stale kw")
    out = asyncio.run(service.generate_content(art["id"], generate_fn=fake))
    assert out["title"] == "Best CRM Software in 2026"
    assert out["checks"]["stale_year"]["pass"]
    assert out["needs_revision"] is False


def test_generate_records_llm_cost_from_usage(monkeypatch):
    from sqlalchemy import select

    from lib.cost_ledger import article_total
    from lib.db import CostLedger, get_session
    from blog_agent import generation as agent_generation
    from sdk import service

    monkeypatch.setenv("CONTENTFTE_REVISE", "0")
    monkeypatch.setattr(agent_generation, "LAST_USAGE", {
        "requests": 1, "input_tokens": 1_000_000, "output_tokens": 1_000_000,
        "total_tokens": 2_000_000, "models": ["gemini-3.5-flash"],
    })

    async def fake(brief):
        return dict(_GOOD_ENVELOPE)

    art = service.submit_article("cost-site", keyword="cost kw")
    out = asyncio.run(service.generate_content(art["id"], generate_fn=fake))

    # 1M in * 0.30 + 1M out * 2.50 per MTOK = 2.80
    assert out["llm_usd"] == pytest.approx(2.80, abs=0.001)
    s = get_session()
    try:
        row = s.execute(select(CostLedger).where(
            CostLedger.article_id == art["id"],
            CostLedger.kind == "llm")).scalars().first()
        assert row is not None and row.amount_usd == pytest.approx(2.80, abs=0.001)
        assert row.detail["price_source"] == "gemini-3.5-flash"
        totals = article_total(s, art["id"])
        assert totals["by_kind"]["llm"] == pytest.approx(2.80, abs=0.001)
    finally:
        s.close()


# ---------------------------------------------------------------------------
# Image staging (§5.9): first-try, section-aware, before the FAQ
# ---------------------------------------------------------------------------
def _staged_article(md: str, keyword="image kw"):
    from lib.db import Article as ArticleModel, get_session
    from sdk import service

    art = service.submit_article("stage-site", keyword=keyword)
    s = get_session()
    try:
        row = s.get(ArticleModel, art["id"])
        row.title = "Staged Post"
        row.content_md = md
        s.commit()
        return art["id"]
    finally:
        s.close()


def test_stage_images_skips_without_provider_credentials(monkeypatch):
    from sdk import service

    aid = _staged_article(_long_body())
    out = service.stage_images(aid)
    assert out["images"] == 0
    assert "no image provider credentials" in out.get("skipped", "")


def test_stage_images_persists_section_aware_rows(monkeypatch, tmp_path):
    import tools.tools as tools_mod
    from sqlalchemy import select

    from lib.db import Article as ArticleModel, AuditLog, get_session
    from sdk import service

    monkeypatch.setenv("CLOUDFLARE_API_TOKEN", "fake-token")
    monkeypatch.setenv("IMAGE_STAGING_DIR", str(tmp_path))

    featured_src = tmp_path / "gen_featured.jpg"
    featured_src.write_bytes(b"\xff\xd8\xff\xe0featured")
    inpost_src = tmp_path / "gen_inpost.jpg"
    inpost_src.write_bytes(b"\xff\xd8\xff\xe0inpost")

    generated: list[dict] = []

    def fake_generate(**kwargs):
        generated.append(kwargs)
        return {"image_url": str(featured_src), "alt_text": "featured alt",
                "cost_usd": 0.0012, "source": "test"}

    def fake_select_inpost(**kwargs):
        generated.append(kwargs)
        return {"image_url": str(inpost_src), "cost_usd": 0.0012,
                "alt_text": kwargs.get("alt_text")}

    monkeypatch.setattr(tools_mod, "_generate_image", fake_generate)
    monkeypatch.setattr(tools_mod, "_select_inpost_image", fake_select_inpost)

    aid = _staged_article(_long_body())
    out = service.stage_images(aid)

    assert out["featured"] is True
    assert out["inpost"] == 1
    assert out["images"] == 2
    # in-post generation was driven by the section, not the whole article
    # (pool = sections[1:], so the first target is the SECOND H2)
    section_call = [g for g in generated if "topic" in g][0]
    assert section_call["topic"].startswith("How do you choose")
    assert section_call["section_summary"]
    assert "image kw:" in section_call["alt_text"]

    s = get_session()
    try:
        row = s.get(ArticleModel, aid)
        rows = row.meta["images"]
        assert rows[0]["slot"] == "featured" and rows[0]["path"].endswith("featured.jpg")
        assert rows[0]["alt"]  # summary/keyword alt, not the meta description
        inpost = [r for r in rows if r["slot"] == "inpost"][0]
        assert inpost["after_h2"] == 2          # second section, inline
        assert os.path.isfile(inpost["path"])   # copied to staging dir
        assert row.meta["image_staging"]["reason"] == "manual"
        assert row.meta.get("image_costs_recorded") is True
        audited = s.execute(select(AuditLog).where(
            AuditLog.article_id == aid,
            AuditLog.action == "article.images")).scalars().first()
        assert audited is not None
    finally:
        s.close()

    # idempotent: a second call leaves the staged rows alone
    again = service.stage_images(aid)
    assert again["images"] == 2
    assert "already staged" in again.get("skipped", "")


def test_publish_stages_images_when_missing(monkeypatch, tmp_path):
    import tools.tools as tools_mod
    from lib.db import Article as ArticleModel, get_session
    from sdk import service

    monkeypatch.setenv("CLOUDFLARE_API_TOKEN", "fake-token")
    monkeypatch.setenv("IMAGE_STAGING_DIR", str(tmp_path))
    src = tmp_path / "pub.jpg"
    src.write_bytes(b"\xff\xd8\xff\xe0pub")

    monkeypatch.setattr(tools_mod, "_generate_image",
                        lambda **kw: {"image_url": str(src), "cost_usd": 0.0012})
    monkeypatch.setattr(tools_mod, "_select_inpost_image",
                        lambda **kw: {"image_url": str(src), "cost_usd": 0.0012})

    service.upsert_site("pub-site", site_type="wordpress", base_url="http://wp.test")
    art = service.submit_article("pub-site", keyword="publish stage kw")
    aid = art["id"]
    s = get_session()
    try:
        row = s.get(ArticleModel, aid)
        row.title = "Publish Staged"
        row.content_md = _long_body()
        row.status = "approved"
        s.commit()
    finally:
        s.close()

    out = service.publish_article(aid, mode="draft")
    assert out["status"] == "published"
    s = get_session()
    try:
        row = s.get(ArticleModel, aid)
        assert row.meta.get("images"), "publish must stage images when none exist"
        assert row.meta["image_staging"]["reason"] == "publish"
        assert row.meta.get("image_costs_recorded") is True
        # WP is unconfigured in tests -> push failed open, staging persisted
        assert "wp" in out and out["wp"].get("ok") is False
    finally:
        s.close()


# ---------------------------------------------------------------------------
# Yoast/RankMath focus keyphrase + meta description length
# ---------------------------------------------------------------------------
def test_meta_payload_carries_focus_keyphrase_for_all_plugins():
    from lib.wordpress import PreparedPost, WordPressConnector, WPConfig

    conn = WordPressConnector(WPConfig(base_url="https://x", username="u",
                                       app_password="p"))
    post = PreparedPost(title="T", html="<p>x</p>",
                        meta_description="d", focus_keyphrase="best crm")
    meta = conn._meta_payload(post)["meta"]
    assert meta["_yoast_wpseo_focuskw"] == "best crm"
    assert meta["rank_math_focus_keyword"] == "best crm"


def test_build_prepared_post_truncates_long_meta_description():
    from lib.wordpress import build_prepared_post

    long_desc = " ".join(["word"] * 60)  # 240+ chars
    post = build_prepared_post(title="T", markdown="## Hi\n\nbody",
                               meta_description=long_desc,
                               focus_keyphrase="kw")
    assert len(post.meta_description) <= 155
    assert post.focus_keyphrase == "kw"
    # truncation lands on a word boundary (no dangling partial word)
    assert not post.meta_description.endswith("wor")


# ---------------------------------------------------------------------------
# Inline images: out-of-range rows land BEFORE Sources/FAQ, never after
# ---------------------------------------------------------------------------
def test_inject_trailing_image_before_sources_plain():
    from lib import wp_render

    body = "<h2>Answer</h2><p>body</p><h2>Sources</h2><p>refs</p>"
    out = wp_render.inject_inpost_images(
        body, [{"url": "/tail.jpg", "alt": "tail"}])
    assert out.index("/tail.jpg") < out.index("<h2>Sources</h2>")


def test_inject_trailing_image_before_faq_blocks_mode():
    from lib import wp_render

    body = ("<!-- wp:heading --><h2>Answer</h2><!-- /wp:heading -->"
            "<!-- wp:paragraph --><p>body</p><!-- /wp:paragraph -->"
            "<!-- wp:heading --><h2>Frequently Asked Questions</h2><!-- /wp:heading -->"
            "<!-- wp:details --><details></details><!-- /wp:details -->")
    out = wp_render.inject_inpost_images(
        body, [{"url": "/tail.jpg", "alt": "tail"}])
    assert out.index("/tail.jpg") < out.index("Frequently Asked Questions")


def test_inject_appends_only_when_no_boundary():
    from lib import wp_render

    body = "<h2>Only section</h2><p>body</p>"
    out = wp_render.inject_inpost_images(body, [{"url": "/tail.jpg", "alt": "t"}])
    assert out.rstrip().endswith("</figure>")
    assert out.index("/tail.jpg") > out.index("<p>body</p>")


# ---------------------------------------------------------------------------
# Prompt gates: current year, Bottom Line, links, revision feedback
# ---------------------------------------------------------------------------
def test_render_prompt_carries_hard_requirements(monkeypatch):
    from datetime import datetime, timezone

    from lib import generation

    monkeypatch.setenv("GEN_MIN_WORDS", "900")
    year = datetime.now(timezone.utc).year
    prompt = generation.render_prompt({
        "keyword": "kw", "brief_markdown": "# kw",
        "internal_links": [{"title": "Guide", "url": "https://site.test/g"}],
        "site_base_url": "https://site.test",
        "sources": ["https://vendor.test/docs"],
        "revision_feedback": ['words: {"pass": false, "value": 120}'],
    })
    assert f"current year is {year}" in prompt
    assert "## Bottom Line" in prompt
    assert "at least 900 words" in prompt
    assert "https://site.test/g" in prompt
    assert "https://vendor.test/docs" in prompt
    assert "PREVIOUS DRAFT FAILED THESE CHECKS" in prompt


def test_render_prompt_forbids_invented_internal_links():
    from lib import generation

    prompt = generation.render_prompt(
        {"keyword": "kw", "brief_markdown": "# kw",
         "internal_links": [], "sources": []})
    assert "do NOT invent" in prompt


def test_brief_payload_exposes_link_graph():
    from lib import generation

    brief = generation.build_brief_payload(
        keyword="kw",
        brief_meta={"internal_links": [{"title": "a", "url": "https://x.test/a"}],
                    "site_base_url": "https://x.test",
                    "sources": ["https://v.test/1"]})
    assert brief["internal_links"] == [{"title": "a", "url": "https://x.test/a"}]
    assert brief["site_base_url"] == "https://x.test"
    assert brief["sources"] == ["https://v.test/1"]


def test_enrich_brief_skips_non_wordpress_and_unconfigured(monkeypatch):
    from lib.db import Article as ArticleModel, get_session
    from sdk import service

    # non-wordpress site -> brief untouched (no network attempt)
    art = service.submit_article("enrich-custom", keyword="enrich kw")
    brief = {"keyword": "enrich kw"}
    s = get_session()
    try:
        row = s.get(ArticleModel, art["id"])
        enriched = service._enrich_brief_with_links(row, brief, "enrich kw")
        assert enriched == brief
    finally:
        s.close()

    # wordpress site but no WP_* creds (stripped by conftest) -> untouched
    service.upsert_site("enrich-wp", site_type="wordpress", base_url="http://x")
    art2 = service.submit_article("enrich-wp", keyword="enrich kw2")
    s = get_session()
    try:
        row = s.get(ArticleModel, art2["id"])
        enriched = service._enrich_brief_with_links(row, dict(brief), "enrich kw2")
        assert "internal_links" not in enriched
    finally:
        s.close()


# ---------------------------------------------------------------------------
# LLM pricing (lib.cost_ledger.usage_cost)
# ---------------------------------------------------------------------------
def test_usage_cost_known_model_rates():
    from lib.cost_ledger import usage_cost

    usd, detail = usage_cost({
        "input_tokens": 1_000_000, "output_tokens": 1_000_000,
        "models": ["providers/gemini-3.5-flash"],
    })
    assert usd == pytest.approx(0.30 + 2.50, abs=1e-6)
    assert detail["price_source"] == "gemini-3.5-flash"
    assert detail["estimate"] is True


def test_usage_cost_unknown_model_uses_default_estimate(monkeypatch):
    from lib.cost_ledger import usage_cost

    monkeypatch.setenv("LLM_PRICE_INPUT_PER_M", "0.50")
    monkeypatch.setenv("LLM_PRICE_OUTPUT_PER_M", "1.50")
    usd, detail = usage_cost({"input_tokens": 1_000_000,
                              "output_tokens": 1_000_000,
                              "models": ["mystery-model-x"]})
    assert usd == pytest.approx(2.00, abs=1e-6)
    assert detail["price_source"] == "default-estimate"


def test_usage_cost_zero_tokens_is_free():
    from lib.cost_ledger import usage_cost

    assert usage_cost({}) == (0.0, {})
    assert usage_cost({"input_tokens": 0, "output_tokens": 0}) == (0.0, {})


# ---------------------------------------------------------------------------
# Image-provider quota circuit breaker (tools.tools)
# ---------------------------------------------------------------------------
def test_quota_guard_arms_on_rate_limit_and_skips_generation(monkeypatch):
    import tools.tools as tools_mod

    monkeypatch.setattr(tools_mod, "_IMAGE_QUOTA_UNTIL", 0.0)
    monkeypatch.setattr(tools_mod, "log_image_usage", lambda *a, **k: True)

    assert tools_mod.image_quota_active() is False
    assert tools_mod._mark_image_quota("HTTP 429 :: rate limit exceeded") is True
    assert tools_mod.image_quota_active() is True

    # even a would-be-successful call short-circuits while armed
    def _boom(*a, **k):
        raise AssertionError("cloudflare called while quota armed")

    monkeypatch.setattr(tools_mod, "_generate_image_cloudflare", _boom)
    out = tools_mod._generate_image(keyword="kw", title="t")
    assert out.get("quota") is True
    assert "quota exhausted" in out.get("error", "")


def test_quota_guard_ignores_non_quota_errors(monkeypatch):
    import tools.tools as tools_mod

    monkeypatch.setattr(tools_mod, "_IMAGE_QUOTA_UNTIL", 0.0)
    assert tools_mod._mark_image_quota("HTTP 400 :: content flagged (code 3030)") is False
    assert tools_mod.image_quota_active() is False
    # a plain moderation flag must not silence later, unrelated prompts
    assert tools_mod._mark_image_quota("network timeout") is False
    assert tools_mod.image_quota_active() is False


def test_quota_guard_reported_by_stage_images(monkeypatch):
    import tools.tools as tools_mod
    from sdk import service

    monkeypatch.setattr(tools_mod, "_IMAGE_QUOTA_UNTIL", 0.0)
    monkeypatch.setattr(tools_mod, "log_image_usage", lambda *a, **k: True)
    monkeypatch.setenv("CLOUDFLARE_API_TOKEN", "fake-token")
    tools_mod._mark_image_quota("HTTP 429 :: daily limit reached")
    try:
        aid = _staged_article(_long_body())
        out = service.stage_images(aid)
        assert out["images"] == 0
        assert any("quota" in e.lower() for e in out.get("errors", [])) or \
               out.get("featured") is False
    finally:
        monkeypatch.setattr(tools_mod, "_IMAGE_QUOTA_UNTIL", 0.0)
