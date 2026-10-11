"""SEO/AEO fields: Sanity schema + engine writes them + delivery payload.

Live gaps fixed together (2026-10-08):
1. A Sanity post had no focus keyword, no SEO title/description and no
   first-class TL;DR — WordPress gets all three (Yoast/Rank Math meta +
   the TL;DR blockquote) while a Sanity site got none of them.
2. The TL;DR was only ever inline content, so every consumer had to parse
   a blockquote out of Portable Text to read the single most quotable
   sentence in the post.

Character limits follow the Yoast/Rank Math "green" thresholds and are
warnings, never hard errors — the missing-featured-image incident is the
reason no new REQUIRED field is added to this schema.
"""
from __future__ import annotations

import os


def _read(rel: str) -> str:
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    with open(os.path.join(root, rel), encoding="utf-8") as fh:
        return fh.read()


def test_extract_tldr_recovers_the_blockquote():
    from lib.geo import extract_tldr, tldr_block

    answer = " ".join(["word"] * 50)
    md = f"# Title\n\n{tldr_block(answer)}\n\nBody text."
    assert extract_tldr(md) == answer
    # plain prose TL;DR variants the model is allowed to emit
    for variant in ("> **TL;DR:** a b c", "> TL;DR - x y z", ">  TL;DR — q"):
        assert extract_tldr(variant) in ("a b c", "x y z", "q")
    # no TL;DR -> empty, never a crash
    assert extract_tldr("no blockquote here") == ""
    assert extract_tldr("") == "" and extract_tldr(None) == ""


def test_extract_tldr_only_looks_at_the_top():
    """A late blockquote that merely starts with "TL;DR:" inside body prose
    must not be mistaken for the TL;DR field."""
    from lib.geo import extract_tldr

    md = ("Body paragraph.\n\n## Later\n\n> TL;DR: buried summary")
    assert extract_tldr(md) == ""


def test_sanity_schema_declares_seo_and_tldr_fields():
    src = _read(os.path.join("sdk", "sanity", "schemaTypes", "postType.ts"))
    for field in ("seoTitle", "seoDescription", "focusKeyword", "tldr"):
        assert f'name: "{field}"' in src, f"post schema missing {field}"
    # Yoast/Rank Math green limits
    assert "Rule.max(60)" in src      # SEO title
    assert "Rule.max(160)" in src     # meta description

    def field_block(field: str) -> str:
        start = src.index(f'name: "{field}"')
        # a defineField block ends at the next defineField or the closing
        # preview block; the next field always starts with `name: "`.
        nxt = src.find('name: "', start + len(field))
        return src[start:nxt if nxt != -1 else len(src)]

    # None of the new fields may be required. A required field is exactly
    # what silently blocked the 2026-10-08 post from ever being published.
    for field in ("seoTitle", "seoDescription", "focusKeyword", "tldr"):
        assert ".required()" not in field_block(field), (
            f"{field} must not be required -- that is the publish-blocker "
            "pattern that left a live post stuck in Draft")

    # the vetted required set (mainImage + alt, categories) is still present
    assert 'name: "mainImage"' in src and 'name: "alt"' in src
    assert "Rule.required().min(1)" in src      # categories, as the live schema has it
    assert "Rule.required()" in src             # title/slug/mainImage/content


def test_post_blog_accepts_and_writes_seo_fields():
    src = _read(os.path.join("lib", "sanity_adapter.py"))
    for token in ("focus_keyphrase: str = \"\"",
                  "seo_title: str = \"\"",
                  "seo_description: str = \"\"",
                  "tldr: str = \"\"",
                  'document["focusKeyword"]',
                  'document["seoTitle"]',
                  'document["seoDescription"]',
                  'document["tldr"]'):
        assert token in src, f"sanitity adapter missing {token}"


def test_post_to_sanity_tool_passes_seo_fields_through():
    src = _read(os.path.join("tools", "tools.py"))
    assert "focus_keyphrase=focus_keyphrase or \"\"," in src
    assert "seo_title=seo_title or \"\"," in src
    assert "seo_description=seo_description or \"\"," in src
    assert "tldr=tldr or \"\"," in src


def test_posting_workflow_derives_seo_fields_deterministically():
    src = _read(os.path.join("blog_agent", "posting_agent.py"))
    for token in ('post_fields["TLDR"] = extract_tldr(',
                  'post_fields["SEO_TITLE"] = post_fields.get("TITLE", "")',
                  'post_fields["SEO_DESCRIPTION"] = post_fields.get("SUMMARY", "")',
                  'post_fields["FOCUS_KEYWORD"] = post_fields.get("KEYWORD_TOPIC", "")'):
        assert token in src, f"posting workflow missing derivation: {token}"
    # the Posting Agent must forward them to the tool
    assert "- focus_keyphrase: the extracted FOCUS_KEYWORD" in src
    assert "- tldr: the extracted TLDR" in src


def test_delivery_payload_carries_seo_block():
    from lib.custom_site import build_delivery_payload

    md = "> **TL;DR** - The answer is forty two for everything.\n\nBody."
    payload = build_delivery_payload(
        title="SEO title", markdown=md, meta_description="meta description",
        focus_keyword="best crm")
    seo = payload["seo"]
    assert seo["title"] == "SEO title"
    assert seo["description"] == "meta description"
    assert seo["focus_keyword"] == "best crm"
    assert seo["tldr"] == "The answer is forty two for everything."
    # additive only -- existing keys untouched
    for key in ("title", "slug", "url", "excerpt", "html", "markdown",
                "markdown_alternate", "faq_html", "schema"):
        assert key in payload
    # no TL;DR in the markdown -> empty string, not a crash
    plain = build_delivery_payload(title="t", markdown="body only")
    assert plain["seo"]["tldr"] == "" and plain["seo"]["focus_keyword"] == ""


# ---------------------------------------------------------------------------
# Sanity package + skill (the "full package" the user asked for)
# ---------------------------------------------------------------------------

def test_sanity_package_ships_complete_studio():
    """A site must be able to `cp -r sdk/sanity ./sanity` and get a working
    studio: config, env, schema, client helpers, SEO fallback, webhook."""
    base = _read_dir("sdk", "sanity")
    for rel in ("sanity.config.ts", "cli.config.ts", "env.ts", "structure.ts",
                "index.ts", "README.md",
                "schemaTypes/index.ts", "schemaTypes/postType.ts",
                "lib/client.ts", "lib/image.ts", "lib/seo.ts",
                "webhooks/revalidate.ts"):
        assert os.path.isfile(os.path.join(base, rel)), f"missing {rel}"
    # the engine-owned types are all present
    for name in ("postType", "authorType", "categoryType", "blockContentType"):
        assert os.path.isfile(os.path.join(base, "schemaTypes", f"{name}.ts"))


def test_sanity_package_has_no_hardcoded_credentials():
    """A real site's webhook shipped with an inline IndexNow key and a
    hardcoded default secret; the packaged version must not repeat that."""
    for rel in ("env.ts", "webhooks/revalidate.ts"):
        src = _read(os.path.join("sdk", "sanity", rel))
        for marker in ("4ecdaee7", "owais-revalidate", "y2wkvags"):
            assert marker not in src, f"{rel} still carries a live credential"
    # and the secret must have no fallback value
    reval = _read(os.path.join("sdk", "sanity", "webhooks", "revalidate.ts"))
    assert 'process.env.SANITY_REVALIDATE_SECRET' in reval


def test_seo_fallback_rule_is_a_single_shared_function():
    """`seoTitle ?? title` and `seoDescription ?? summary` must be defined
    once, not re-invented per site."""
    seo_src = _read(os.path.join("sdk", "sanity", "lib", "seo.ts"))
    assert "post.seoTitle" in seo_src and "post.title" in seo_src
    assert "post.seoDescription" in seo_src and "post.summary" in seo_src
    # the schema documents the same chain
    schema_src = _read(os.path.join("sdk", "sanity", "schemaTypes", "postType.ts"))
    assert "Falls back to the post title" in schema_src
    assert "Falls back to Summary" in schema_src


def test_skill_documents_sanity_schema_and_fallbacks():
    skill = _read(os.path.join("skills", "contentfte", "SKILL.md"))
    assert "references/sanity.md" in skill
    assert "content-fte/sanity" in skill                       # SDK entry point
    assert "seoTitle || title" in skill                        # the fallback chain
    assert "seoDescription || summary" in skill
    assert "stuck in Draft" in skill                           # publish-blocker pointer

    ref = _read(os.path.join("skills", "contentfte", "references",
                             "sanity.md"))
    for marker in ("seoTitle", "seoDescription", "focusKeyword", "tldr",
                   "resolveSeoTitle", "generateMetadata",
                   "mainImage", "60 characters", "160 characters",
                   "40-60 word", "Rule.required()"):
        assert marker in ref, f"references/sanity.md missing: {marker}"
    # the TL;DR answer to "is it in our code" is documented, not implied
    assert "inline" in ref


def test_sdk_manifest_ships_the_sanity_package():
    pkg = _read(os.path.join("sdk", "package.json"))
    assert '"./sanity"' in pkg            # import path for consumers
    assert '"sanity"' in pkg              # shipped in files[]


def _read_dir(*parts: str) -> str:
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(root, *parts)
