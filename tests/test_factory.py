"""§7 Local Business Factory — business profile → Brand DNA + offers."""
import json
import os

import pytest

from lib import factory

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

BUSINESS = {
    "name": "Ace Dental Studio",
    "site_url": "https://acedental.example",
    "tone": "friendly, local, reassuring",
    "services": [
        "Emergency Dentistry",
        {"name": "Teeth Whitening", "description": "In-chair whitening", "cta": "Book whitening"},
    ],
    "locations": ["Austin", "Round Rock"],
    "signature_phrases": ["gentle care, every visit"],
}


@pytest.fixture
def temp_db(tmp_path):
    import lib.db as db
    old_url = os.environ.get("DATABASE_URL")
    os.environ["DATABASE_URL"] = f"sqlite:///{tmp_path / 'factory_test.db'}"
    db._engine = None
    db._SessionLocal = None
    db.init_db()
    yield db
    if db._engine is not None:
        db._engine.dispose()
    db._engine = None
    db._SessionLocal = None
    if old_url is None:
        os.environ.pop("DATABASE_URL", None)
    else:
        os.environ["DATABASE_URL"] = old_url


def test_build_offer_catalog_shape_and_urls():
    offers = factory.build_offer_catalog(BUSINESS["services"], BUSINESS["site_url"])
    assert offers[0] == {
        "name": "Emergency Dentistry", "description": "",
        "url": "https://acedental.example/services/emergency-dentistry/",
        "cta": "Get a quote",
    }
    assert offers[1]["cta"] == "Book whitening"


def test_build_brand_profile_entities_and_defaults():
    profile = factory.build_brand_profile(BUSINESS)
    assert profile["brand_name"] == "Ace Dental Studio"
    # entities: name + services + locations, de-duplicated
    assert profile["entities"] == [
        "Ace Dental Studio", "Emergency Dentistry", "Teeth Whitening",
        "Austin", "Round Rock",
    ]
    assert profile["banned_phrases"]  # defaults applied
    assert profile["reading_level"] == "grade-8"
    assert len(profile["offers"]) == 2
    assert profile["signature_phrases"] == ["gentle care, every visit"]


def test_provision_site_roundtrip(temp_db):
    from lib.brand_dna import load_profile
    from lib.factory import provision_site
    from tools.offer_tool import _clean_offers

    s = temp_db.get_session()
    try:
        res = provision_site(s, BUSINESS)
        assert res["slug"] == "ace-dental-studio"
        assert res["offers"] == 2
        profile = load_profile(s, res["site_id"])
        assert profile["brand_name"] == "Ace Dental Studio"
        # offers survive the clean_offers parse the offer tool uses
        cleaned = _clean_offers(profile.get("offers"))
        assert {o["name"] for o in cleaned} == {"Emergency Dentistry", "Teeth Whitening"}
    finally:
        s.close()


def test_provision_factory_site_tool(temp_db):
    from tools.factory_tool import provision_factory_site

    assert provision_factory_site("not json")["status"] == "error"
    assert provision_factory_site({"name": ""})["status"] == "error"
    out = provision_factory_site(json.dumps(BUSINESS))
    assert out["status"] == "ok"
    assert out["slug"] == "ace-dental-studio"
