"""A2 batch 3 — Brand DNA distillation (spec §5.1: samples → profile,
versioned storage, CLI)."""
from __future__ import annotations

import json
import os

import pytest


@pytest.fixture(autouse=True)
def _isolated_db(monkeypatch):
    workdir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                           ".test-tmp-phase1")
    os.makedirs(workdir, exist_ok=True)
    db_file = os.path.join(workdir, "brand_dna.db")
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db_file}")
    import lib.db as db

    if db._engine is not None:
        db._engine.dispose()
    db._engine = None
    db._SessionLocal = None
    try:
        os.remove(db_file)
    except OSError:
        pass
    db.init_db()
    yield
    if db._engine is not None:
        db._engine.dispose()
    try:
        os.remove(db_file)
    except OSError:
        pass


def _fake_llm(payload: dict, *, fenced: bool = True):
    body = json.dumps(payload)
    text = f"```json\n{body}\n```" if fenced else body
    return lambda prompt: text


def test_distill_profile_normalizes_model_output():
    from lib.brand_dna import DEFAULT_PROFILE, distill_profile

    raw = {
        "tone_sliders": {"formal_casual": 7.5, "terse_expansive": -2},
        "reading_level": "grade-7",
        "signature_phrases": ["  ship it  ", "ship it", "real talk"],
        "banned_phrases": "game-changer",   # lone string, not a list
        "pov": "second",                    # junk value -> default
        "style_preset": "editorial",
    }
    profile = distill_profile(
        ["We write like humans. Real talk.", "No hype. Ever."],
        llm_fn=_fake_llm(raw))
    assert profile["tone_sliders"] == {"formal_casual": 1.0,
                                       "terse_expansive": 0.0}
    assert profile["reading_level"] == "grade-7"
    assert profile["signature_phrases"] == ["ship it", "real talk"]
    assert profile["banned_phrases"] == ["game-changer"]
    assert profile["pov"] == DEFAULT_PROFILE["pov"]
    assert profile["style_preset"] == "editorial"


def test_distill_profile_accepts_unfenced_json():
    from lib.brand_dna import distill_profile

    profile = distill_profile(
        ["sample"], llm_fn=_fake_llm({"pov": "first"}, fenced=False))
    assert profile["pov"] == "first"


def test_distill_profile_rejects_empty_samples_and_garbage():
    from lib.brand_dna import distill_profile

    with pytest.raises(ValueError, match="sample"):
        distill_profile([], llm_fn=_fake_llm({}))
    with pytest.raises(ValueError, match="sample"):
        distill_profile(["", "   "], llm_fn=_fake_llm({}))
    with pytest.raises(ValueError, match="JSON object"):
        distill_profile(["sample"], llm_fn=lambda p: "no json here")


def test_distill_profile_requires_llm_key_without_injection(monkeypatch):
    from lib import brand_dna

    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    with pytest.raises(ValueError, match="OPENROUTER_API_KEY"):
        brand_dna._default_llm("prompt")


def test_save_profile_versions_and_load_merges_defaults():
    from lib.brand_dna import save_profile, load_profile
    from lib.db import Site, get_session

    with get_session() as s:
        site = Site(slug="dna-site", name="DNA")
        s.add(site)
        s.commit()
        s.refresh(site)
        v1 = save_profile(s, site.id, {"pov": "first"})
        v2 = save_profile(s, site.id, {"reading_level": "grade-6"})
        assert (v1.version, v2.version) == (1, 2)
        loaded = load_profile(s, site.id)
        # second save wins per-field merge on top of DEFAULT_PROFILE
        assert loaded["reading_level"] == "grade-6"
        assert loaded["tone_sliders"]["formal_casual"] == 0.5


def test_build_cli_dry_run_and_save(tmp_path, monkeypatch):
    from scripts.build_brand_dna import build
    from lib.brand_dna import load_profile
    from lib.db import Site, get_session

    sample = tmp_path / "voice.txt"
    sample.write_text(
        "<p>We keep it plain. No game-changer talk.</p>", encoding="utf-8")

    with get_session() as s:
        site = Site(slug="cli-site", name="CLI")
        s.add(site)
        s.commit()

    fake = _fake_llm({"pov": "first",
                      "signature_phrases": ["plain words"]})
    dry = build(files=[str(sample)], texts=["Second sample voice.",
                                            "Third sample voice."],
                dry_run=True, site_slug="cli-site", llm_fn=fake)
    assert dry["status"] == "ok" and dry["dry_run"] is True
    assert dry["samples_used"] == 3          # tags were stripped from the file
    assert "<p>" not in json.dumps(dry["profile"])
    with get_session() as s:
        # dry run must not have versioned anything — profile is still default
        assert load_profile(s, _site_id("cli-site"))["pov"] == "second"

    saved = build(files=[str(sample)], texts=["Second sample voice.",
                                              "Third sample voice."],
                  site_slug="cli-site", llm_fn=fake)
    assert saved["status"] == "ok" and saved["version"] == 1
    with get_session() as s:
        loaded = load_profile(s, _site_id("cli-site"))
    assert loaded["pov"] == "first"
    assert loaded["signature_phrases"] == ["plain words"]


def test_build_cli_errors():
    from scripts.build_brand_dna import build

    assert build(texts=[], llm_fn=_fake_llm({}))["status"] == "error"
    bad = build(texts=["one", "two", "three"], site_slug="ghost",
                llm_fn=_fake_llm({}))
    assert bad["status"] == "error" and "not found" in bad["message"]


def _site_id(slug: str) -> int:
    from lib.db import Site, get_session
    from sqlalchemy import select

    with get_session() as s:
        return s.execute(select(Site.id).where(Site.slug == slug)).scalar_one()
