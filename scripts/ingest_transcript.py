"""
scripts/ingest_transcript.py — Manually ingest a YouTube/Audio transcript into the agent pipeline.

Usage:
  python scripts/ingest_transcript.py --topic "Your Topic Title" --file path/to/transcript.txt --site owaisabdullah-dev
  or paste directly into transcript.txt in the project root and run:
  python scripts/ingest_transcript.py --topic "Your Topic Title"
"""

import argparse
import os
import sys
from lib.db import get_session, Site, KeywordLedger, ArticleModel
from sdk import service


def ingest(topic: str, transcript: str, site_slug: str = "owaisabdullah-dev", create_article_now: bool = True):
    with get_session() as s:
        site = s.query(Site).filter(Site.slug == site_slug).first()
        if not site:
            available = [s.slug for s in s.query(Site).all()]
            print(f"❌ Error: Site '{site_slug}' not found. Available sites: {available}")
            sys.exit(1)

        # 1. Create or update in KeywordLedger with priority 100.0 (top of queue)
        kw = s.query(KeywordLedger).filter(
            KeywordLedger.site_id == site.id,
            KeywordLedger.keyword == topic
        ).first()

        research_snapshot = {
            "subject": topic,
            "summary": transcript[:1500].strip(),
            "source": "manual_transcript",
            "full_transcript": transcript.strip(),
            "intent": "informational"
        }

        if kw:
            kw.priority_score = 100.0
            kw.status = "approved"
            kw.research_snapshot = research_snapshot
            print(f"🔄 Updated existing keyword '{topic}' to priority 100.0 (ID={kw.id})")
        else:
            kw = KeywordLedger(
                site_id=site.id,
                keyword=topic,
                intent="informational",
                status="approved",
                priority_score=100.0,
                research_snapshot=research_snapshot
            )
            s.add(kw)
            s.commit()
            s.refresh(kw)
            print(f"✅ Injected keyword '{topic}' into ledger with priority 100.0 (ID={kw.id})")

        # 2. Optionally submit directly into ArticleModel so it's ready for Brief/Content generation
        if create_article_now:
            brief_payload = {
                "title": topic,
                "keyword": topic,
                "notes": f"Generated from video transcript:\n\n{transcript[:1000]}...",
                "source_transcript": transcript
            }
            # Check if article already exists for this keyword
            existing_art = s.query(ArticleModel).filter(
                ArticleModel.site_id == site.id,
                ArticleModel.keyword_id == kw.id
            ).first()

            if existing_art:
                existing_art.meta = {**(existing_art.meta or {}), "brief": brief_payload, "keyword": topic, "transcript": transcript}
                s.commit()
                art_id = existing_art.id
                print(f"🔄 Updated existing article #{art_id} with transcript payload.")
            else:
                art = service.submit_article(
                    site_slug=site.slug,
                    keyword=topic,
                    title=topic,
                    brief=brief_payload
                )
                art_id = art["id"] if isinstance(art, dict) else art.id
                print(f"🚀 Created Article #{art_id} ready for Brief/Draft stage!")

        s.commit()
        print("\n🎉 Done! You can view and run it in the console at:")
        print(f"   http://localhost:3000/articles/{art_id}")
        return kw.id, art_id


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Ingest a transcript as top priority")
    parser.add_argument("--topic", type=str, required=True, help="Topic / Article Title")
    parser.add_argument("--file", type=str, default="transcript.txt", help="Path to transcript text file (default: transcript.txt)")
    parser.add_argument("--site", type=str, default="owaisabdullah-dev", help="Site slug (default: owaisabdullah-dev)")
    args = parser.parse_args()

    if not os.path.exists(args.file):
        print(f"❌ Error: Transcript file '{args.file}' not found.")
        print(f"👉 Please create '{args.file}' and paste your transcript inside, then rerun.")
        sys.exit(1)

    with open(args.file, "r", encoding="utf-8") as f:
        text = f.read().strip()

    if not text:
        print(f"❌ Error: '{args.file}' is empty.")
        sys.exit(1)

    ingest(topic=args.topic, transcript=text, site_slug=args.site)
