from agents import function_tool
import os
import re
import base64
import requests
import json
from slugify import slugify
import textstat
from language_tool_python import LanguageTool
import time
from lib.sanity_adapter import SanityAdapter
from lib import image_vision
from lib import image_format
from lib import image_provenance
from tools.sheet_tool import log_image_usage
from dotenv import load_dotenv
import tempfile
import logging
from typing import List, Dict, Any, Optional
from pydantic import BaseModel, Field

load_dotenv()

logger = logging.getLogger(__name__)

# Global variable to track fetch_internal_links_tool usage
fetch_internal_links_usage_count = 0
MAX_INTERNAL_LINKS_CALLS = 3


def reset_internal_links_counter():
    """Reset the per-stage internal links call counter. Call at the start of
    each pipeline stage so every stage gets its own budget of 3 calls."""
    global fetch_internal_links_usage_count
    fetch_internal_links_usage_count = 0

# Define Pydantic model for FAQ items
class FAQItem(BaseModel):
    question: str = Field(..., description="The FAQ question")
    answer: str = Field(..., description="The FAQ answer")

# ContentSpark AI – Brand Context Engine
@function_tool
def get_brand_context_tool():
    """
    Returns the single source of truth for all ContentSpark AI messaging.
    Use this object to:
      • Feed GPT / Gemini prompts
      • Generate landing-page copy
      • Create social captions, ads, emails, changelogs, help-docs
      • QA every asset before it ships
    """
    return {
        # Core Identity
        "company_name": "ContentSpark AI",
        "tagline": "Your brand voice, on autopilot.",
        "mission": (
            "We help creators, agencies, and SMBs create scroll-stopping, "
            "on-brand social content in minutes—then remember every nuance "
            "so their voice stays unmistakably theirs, forever."
        ),

        # Brand Personality
        "tone": (
            "Creative, upbeat, and supportive—like a friendly co-pilot who’s "
            "fluent in memes AND metrics. We celebrate small wins, demystify AI, "
            "and never gate-keep a good growth hack."
        ),
        "voice_examples": {
            "good": [
                "Your next caption is 3 clicks away—let’s spark it ✨",
                "We just auto-planned your week of posts. Go grab a coffee ☕️"
            ],
            "avoid": [
                "Our paradigm-shifting technology revolutionizes the space."
            ]
        },

        # Visual & Emoji Language
        "primary_emojis": ["✨", "📈", "🎯", "🧠", "🚀"],
        "accent_emojis": ["☕️", "😎", "🔥", "🤝"],
        "color_palette": {
            "primary": "#3B82F6",  # Spark Blue
            "accent": "#10B981",   # Growth Green
            "neutral": "#F8FAFC",  # Cloud White
            "warning": "#F59E0B"   # Warm Amber
        },

        # Audience Personas
        "personas": {
            "solo_creator": {
                "name": "Solo Creator",
                "pain": "No time, inconsistent voice, stuck in Canva hell",
                "gain": "One hub to ideate, write, schedule, and grow",
                "trigger": "Hit 1 000 followers → need daily posts"
            },
            "micro_agency": {
                "name": "Micro-Agency (2-10 clients)",
                "pain": "Juggling 5 Google Docs, 3 tones, 2 interns",
                "gain": "Multi-profile memory + approval flows = scale",
                "trigger": "Client #3 threatens to churn"
            },
            "smb_owner": {
                "name": "SMB Owner",
                "pain": "Marketing on nights/weekends, zero design skills",
                "gain": "AI does 80 %, they tweak 20 %, results in 5 min",
                "trigger": "Quarterly sales dip"
            },
        },

        # Messaging Pillars
        "key_messages": [
            "Brand consistency without brain drain.",
            "From blank page to scheduled post in under 3 minutes.",
            "Your brand voice—saved, searchable, and AI-ready.",
            "Scale social without sounding like everyone else."
        ],

        # Differentiators → Proof Points
        "proof_points": {
            "memory": (
                "Our vector memory recalls every caption you’ve ever posted, "
                "keeping tone and emojis locked in—even across 50 clients."
            ),
            "speed": (
                "Average user goes from prompt to scheduled post in 2 min 37 s "
                "(measured via PostHog)."
            ),
            "price": (
                "Up to 83 % cheaper than Hootsuite for 10 profiles."
            )
        },
        "preferred_terms": {
            "AI": "your creative sidekick",
            "users": "creators & teams",
            "analytics": "insights that matter",
            "scheduling": "calendar on autoplay"
        },
        
        # Language Rules
        "banned_words": ["enterprise", "solution", "synergy", "leverage (as verb)", "disruptive", "cutting-edge", "game-changer", "revolutionary", "revolutionize", "dive in", "venture", "innovative", "realm", "adhere", "delve", "reimagine", "robust", "orchestrate", "diverse", "commendable", "embrace", "paramount", "beacon", "captivate", "commendable", "advancement in the realm", "aims to bridge", "aims to democratize", "aims to foster innovation and collaboration", "becomes increasingly evident", "behind the veil", "breaking barriers", "breakthrough has the potential to revolutionize the way", "bringing us", "bringing us closer to a future", "by combining the capabilities", "by harnessing the power", "capturing the attention", "continue to advance", "continue to make significant strides", "continue to push the boundaries", "continues to progress rapidly", "crucial to be mindful", "crucially", "cutting-edge", "drive the next big", "encompasses a wide range of real-life scenarios", "enhancement further enhances", "ensures that even", "essential to understand the nuances", "excitement", "exciting opportunities", "exciting possibilities", "exciting times lie ahead as we unlock the potential of", "excitingly", "expanded its capabilities", "expect to witness transformative breakthroughs", "expect to witness transformative breakthroughs in their capabilities", "exploration of various potential answers", "explore the fascinating world", "exploring new frontiers", "exploring this avenue", "foster the development", "future might see us placing", "groundbreaking way", "groundbreaking advancement", "groundbreaking study", "groundbreaking technology", "have come a long way in recent years", "hold promise", "implications are profound", "improved efficiency in countless ways", "in conclusion", "in the fast-paced world", "innovative service", "intrinsic differences", "it discovered an intriguing approach", "it remains to be seen", "it serves as a stepping stone towards the realization", "latest breakthrough signifies", "latest offering", "let’s delve into the exciting details", "main message to take away", "make informed decisions", "mark a significant step forward", "mind-boggling figure","more robust evaluation","for instance","navigate the landscape","notably","one step closer","one thing is clear","only time will tell","opens up exciting possibilities","paving the way for enhanced performance","possibilities are endless","potentially revolutionizing the way","push the boundaries","raise fairness concerns","raise intriguing questions","rapid pace of development","rapidly developing","redefine the future","remarkable abilities","remarkable breakthrough","remarkable proficiency","remarkable success","remarkable tool","remarkably","elevate ","captivate ","tapestry ","delve ","leverage ","resonate ","foster ","endeavor ","embark ","unleash ","renowned","represent a major milestone","represents a significant milestone in the field","revolutionize the way","revolutionizing the way","risks of drawing unsupported conclusions","seeking trustworthiness","significant step forward","significant strides","the necessity of clear understanding","there is still room for improvement","transformative power","truly exciting","uncover hidden trends","understanding of the capabilities","unleashing the potential","unlocking the power","unraveling","we can improve understanding and decision-making","welcome your thoughts","what sets this apart","what’s more","with the introduction","bespoke","whimsical","meticulous","emerge","refrain","vibrant","reimagine","evolve","supercharge","pivotal"],

        # Call-to-Actions (CTA Library)
        "ctas": {
            "waitlist": "Save my spot + import my posts",
            "trial": "Start free, no card",
            "upgrade": "Unlock unlimited profiles",
            "share": "Show off my Brand DNA file"
        },

        # Social Caption Templates
        "caption_templates": [
            "✨ New week, new posts—crafted in 3 minutes flat. Who else is letting AI handle the grind? #ContentSpark",
            "📈 When your AI remembers every emoji you’ve ever used… consistency level: expert.",
            "☕️ Just batch-created 30 days of content before my latte cooled. Game on.",
            "🧠 Your brand voice deserves a memory. Export & share your .brand file today!"
        ],

        # Support & Help Tone
        "support_tone": (
            "We’re in your DMs with GIFs, step-by-step Loom videos, "
            "and zero corporate fluff—because your growth > our inbox zero."
        ),

        # Compliance & Trust
        "data_message": (
            "Your captions stay yours. 256-bit AES encryption, GDPR/CCPA ready, "
            "and we’ll delete everything with one click."
        )
    }

# The portfolio site's own API is the source of truth for anything that
# changes over time (current job, bio, skills) -- hardcoding that here would
# just go stale. Only the brand-voice constants below (tone, banned words,
# CTAs, etc.) stay static, since those are a style guide, not biographical fact.
AUTHOR_PROFILE_API_URL = "https://owaisabdullah.dev/api/profile"


# Owais Abdullah – Personal Brand Context
@function_tool
def get_author_context_tool():
    """
    Returns the single source of truth for all Owais Abdullah.
    Use this object to:
      • Guide GPT/Gemini prompts
      • Write website copy, captions, ads, and outreach emails
      • Keep a consistent tone across all platforms
    """
    static_context = {
        # Core Identity
        "brand_name": "Owais Abdullah",
        "tagline": "Web, AI & Automation—Made Simple.",
        "mission": (
            "Helping businesses and creators build smarter web experiences, "
            "AI-driven tools, and automation systems—without overcomplicating technology."
        ),

        # Brand Personality
        "tone": (
            "Approachable, clear, and solution-focused—like a tech-savvy friend who "
            "breaks complex ideas into simple, actionable steps. Confident but never arrogant."
        ),
        "voice_examples": {
            "good": [
                "Smart tools don’t need to feel complicated—let’s make them work for you.",
                "From your idea to a live, polished product—handled with care and precision.",
                "Your project deserves more than templates—it deserves thoughtful development."
            ],
            "avoid": [
                "Our paradigm-shifting solution will revolutionize the digital landscape.",
                "This disruptive technology will change everything overnight."
            ]
        },

        # Visual & Emoji Language
        "primary_emojis": ["🚀", "🤖", "⚙️", "🌐", "💡"],
        "accent_emojis": ["📈", "🛠️", "✅", "☕"],
        "color_palette": {
            "primary": "#3A69FF",   # Your primary accent
            "accent": "#1E293B",    # Dark slate for contrast
            "neutral": "#F8FAFC",   # Soft white
            "highlight": "#10B981"  # Secondary pop of green
        },

        # Audience Personas
        "personas": {
            "startup_founder": {
                "name": "Startup Founder",
                "pain": "Limited resources, need reliable web or AI tools quickly.",
                "gain": "A partner who can design, build, and ship efficiently.",
                "trigger": "Looking to launch an MVP or improve workflows."
            },
            "smb_owner": {
                "name": "Small Business Owner",
                "pain": "Wants an online presence or automation without technical headaches.",
                "gain": "A clear plan and smooth delivery of their site or app.",
                "trigger": "Needs to boost sales or streamline operations."
            },
            "creator": {
                "name": "Content Creator",
                "pain": "Struggles with scaling content and repurposing efficiently.",
                "gain": "AI tools that handle research, posting, and automation.",
                "trigger": "Ready to grow across multiple platforms."
            },
        },

        # Messaging Pillars
        "key_messages": [
            "Web and AI development without unnecessary complexity.",
            "Your ideas, built into reliable apps, sites, or agents.",
            "Automation and AI that save time and boost results.",
            "Partnership over jargon—clear, honest communication at every step."
        ],

        # Differentiators → Proof Points
        "proof_points": {
            "experience": "2+ years delivering professional web apps, AI tools, and automation workflows.",
            "breadth": "Full-stack expertise: React, Next.js, TypeScript, Tailwind CSS, Python, Sanity, WordPress, and AI agents.",
            "track_record": "Projects include e-commerce marketplaces, SEO blog agents, AI social tools, and renting platforms."
        },

        # Preferred and Banned Terms
        "preferred_terms": {
            "AI": "smart automation",
            "users": "clients or creators",
            "website": "web experience",
            "tool": "solution"
        },

        "banned_words": ["enterprise", "solution", "synergy", "leverage (as verb)", "disruptive", "cutting-edge", "game-changer", "revolutionary", "revolutionize", "dive in", "venture", "innovative", "realm", "adhere", "delve", "reimagine", "robust", "orchestrate", "diverse", "commendable", "embrace", "paramount", "beacon", "captivate", "commendable", "advancement in the realm", "aims to bridge", "aims to democratize", "aims to foster innovation and collaboration", "becomes increasingly evident", "behind the veil", "breaking barriers", "breakthrough has the potential to revolutionize the way", "bringing us", "bringing us closer to a future", "by combining the capabilities", "by harnessing the power", "capturing the attention", "continue to advance", "continue to make significant strides", "continue to push the boundaries", "continues to progress rapidly", "crucial to be mindful", "crucially", "cutting-edge", "drive the next big", "encompasses a wide range of real-life scenarios", "enhancement further enhances", "ensures that even", "essential to understand the nuances", "excitement", "exciting opportunities", "exciting possibilities", "exciting times lie ahead as we unlock the potential of", "excitingly", "expanded its capabilities", "expect to witness transformative breakthroughs", "expect to witness transformative breakthroughs in their capabilities", "exploration of various potential answers", "explore the fascinating world", "exploring new frontiers", "exploring this avenue", "foster the development", "future might see us placing", "groundbreaking way", "groundbreaking advancement", "groundbreaking study", "groundbreaking technology", "have come a long way in recent years", "hold promise", "implications are profound", "improved efficiency in countless ways", "in conclusion", "in the fast-paced world", "innovative service", "intrinsic differences", "it discovered an intriguing approach", "it remains to be seen", "it serves as a stepping stone towards the realization", "latest breakthrough signifies", "latest offering", "let’s delve into the exciting details", "main message to take away", "make informed decisions", "mark a significant step forward", "mind-boggling figure","more robust evaluation","for instance","navigate the landscape","notably","one step closer","one thing is clear","only time will tell","opens up exciting possibilities","paving the way for enhanced performance","possibilities are endless","potentially revolutionizing the way","push the boundaries","raise fairness concerns","raise intriguing questions","rapid pace of development","rapidly developing","redefine the future","remarkable abilities","remarkable breakthrough","remarkable proficiency","remarkable success","remarkable tool","remarkably","elevate ","captivate ","tapestry ","delve ","leverage ","resonate ","foster ","endeavor ","embark ","unleash ","renowned","represent a major milestone","represents a significant milestone in the field","revolutionize the way","revolutionizing the way","risks of drawing unsupported conclusions","seeking trustworthiness","significant step forward","significant strides","the necessity of clear understanding","there is still room for improvement","transformative power","truly exciting","uncover hidden trends","understanding of the capabilities","unleashing the potential","unlocking the power","unraveling","we can improve understanding and decision-making","welcome your thoughts","what sets this apart","what’s more","with the introduction","bespoke","whimsical","meticulous","emerge","refrain","vibrant","reimagine","evolve","supercharge","pivotal"],

        # Call-to-Actions (CTAs)
        "ctas": {
            "hire": "Let’s build your project",
            "contact": "Reach out today",
            "learn_more": "See Owais’s work",
            "start": "Start your web or AI journey"
        },

        # Social Caption Templates
        "caption_templates": [
            "🚀 Another idea turned into reality. Smart tools, clean code, and clear results.",
            "🤖 Built an AI agent today that saves hours of manual work—what could it do for you?",
            "⚙️ Websites and automations that actually make life easier—not harder."
        ],

        # Support & Help Tone
        "support_tone": (
            "Helpful and straightforward. Provide clear answers without fluff, and guide the user confidently."
        ),

        # Compliance & Trust
        "data_message": (
            "Any shared data stays private and is only used for delivering requested services. "
            "Your privacy and trust come first."
        )
    }

    try:
        response = requests.get(AUTHOR_PROFILE_API_URL, timeout=10)
        response.raise_for_status()
        profile = response.json()
    except Exception as e:
        logger.warning(f"get_author_context_tool: live profile fetch failed, using static context only: {e}")
        return static_context

    current_roles = [
        f"{job.get('title')} at {job.get('company')}"
        for job in profile.get("work", [])
        if str(job.get("end", "")).strip().lower() == "present"
    ]
    static_context["live_profile"] = {
        "about": profile.get("about"),
        "summary": profile.get("summary"),
        "current_roles": current_roles,
        "skills": profile.get("skills", []),
        "key_highlights": [h.get("description") for h in profile.get("keyHighlights", []) if h.get("description")],
    }
    return static_context


# The brain is separate from get_author_context_tool above: that's a static style
# guide (tone, banned words, personas) that barely changes. This is the owner's
# actual first-hand stories, opinions, and numbers, meant to grow over time as
# entries are added -- see brain/README.md for the format.
BRAIN_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "brain")


@function_tool
def get_brain_notes_tool(topic: str):
    """
    Searches the brain/ knowledge base for the owner's real stories, opinions, and
    numbers relevant to `topic`. Use this before drafting, in addition to (not instead
    of) get_author_context_tool -- that tool controls how the writing sounds, this one
    is what the writer actually knows first-hand.

    Returns matching entries with their full text, or an empty list with a message if
    nothing matches -- an empty result is expected and fine; it means write from
    general research as usual and do NOT invent a personal anecdote or number to fill
    the gap.
    """
    if not os.path.isdir(BRAIN_DIR):
        return {"notes": [], "message": "No brain/ directory found."}

    topic_words = {w.lower() for w in re.findall(r"[a-zA-Z0-9]+", topic) if len(w) > 2}
    matches = []
    for fname in sorted(os.listdir(BRAIN_DIR)):
        if not fname.endswith(".md") or fname.startswith("_") or fname.lower() == "readme.md":
            continue
        path = os.path.join(BRAIN_DIR, fname)
        try:
            with open(path, "r", encoding="utf-8") as f:
                text = f.read()
        except Exception:
            continue

        lines = text.splitlines()
        title = lines[0].lstrip("#").strip() if lines else fname
        tags_line = next((l for l in lines[:6] if l.lower().startswith("tags:")), "")
        tags = {t.strip().lower() for t in tags_line.split(":", 1)[1].split(",")} if tags_line else set()
        title_words = {w.lower() for w in re.findall(r"[a-zA-Z0-9]+", title)}

        if topic_words & (tags | title_words):
            matches.append({"file": fname, "title": title, "content": text})

    if not matches:
        return {
            "notes": [],
            "message": "No brain notes found for this topic. Write from general research as usual -- do not invent a personal anecdote, story, or number to fill this gap.",
        }
    return {"notes": matches, "message": f"Found {len(matches)} brain note(s) relevant to '{topic}'."}


@function_tool
def textstat_tool(content: str):
    """Analyzes readability of the content using textstat."""
    try:
        flesch_reading_ease = textstat.flesch_reading_ease(content)
        flesch_kincaid_grade = textstat.flesch_kincaid_grade(content)
        smog_index = textstat.smog_index(content)
        
        feedback = []
        if flesch_reading_ease < 60:
            feedback.append("Content is difficult to read. Aim for simpler sentences and words (Flesch Reading Ease < 60).")
        if flesch_kincaid_grade > 8:
            feedback.append("Content is written at a high reading level. Target a grade 8 or lower for broader accessibility.")
        if smog_index > 10:
            feedback.append("SMOG index indicates complex text. Simplify for better comprehension.")
        
        return {
            "flesch_reading_ease": flesch_reading_ease,
            "flesch_kincaid_grade": flesch_kincaid_grade,
            "smog_index": smog_index,
            "feedback": feedback if feedback else ["Readability is good."]
        }
    except Exception as e:
        return {"error": f"Readability analysis failed: {str(e)}"}

@function_tool
def grammar_check_tool(content: str):
    """Checks grammar and style using LanguageTool."""
    try:
        tool = LanguageTool('en-US')
        matches = tool.check(content)
        feedback = []
        
        for match in matches[:10]:
            feedback.append(f"Grammar/Style issue at '{match.context}': {match.message} (Suggested: {match.replacements[0] if match.replacements else 'review manually'})")
        
        tool.close()
        return {
            "issues_count": len(matches),
            "feedback": feedback if feedback else ["No grammar or style issues detected."]
        }
    except Exception as e:
        return {"error": f"Grammar check failed: {str(e)}"}

# --- Image provenance registry ---
# The true origin of an image (which AI model produced it, or which stock
# provider supplied it) is decided inside the two image tools below, but it
# used to be lost by the time the post reached Sanity: post_to_sanity_tool
# only ever received the final image_path/URL and had to guess from its
# shape, so a Cloudflare-generated local .png was indistinguishable from any
# other local file (it got reported as "Local"). Recording the id at
# generation/fetch time and looking it up again at publish time keeps the
# provenance authoritative without relying on an LLM echoing a `source`
# field back through the Preparation -> Posting agent handoff.
_IMAGE_SOURCE_REGISTRY: Dict[str, str] = {}


def _image_source_key(value: Any) -> str:
    """Normalizes an image id (local path or URL) so the same image is found
    regardless of slash direction, query string, or letter case."""
    v = str(value or "").strip()
    if not v:
        return ""
    if v.lower().startswith(("http://", "https://")):
        return v.split("?", 1)[0].rstrip("/").lower()
    return os.path.normpath(v).lower()


def record_image_source(image_id: Any, source: str) -> None:
    key = _image_source_key(image_id)
    if not key or not source:
        return
    # Bounded so a long-lived Discord bot process doesn't accumulate an entry
    # per generated image forever. Evicts oldest-first; a run only ever
    # generates a handful of images between selection and publish, so the
    # 512-entry window is never close to being hit in practice.
    if key not in _IMAGE_SOURCE_REGISTRY and len(_IMAGE_SOURCE_REGISTRY) >= 512:
        _IMAGE_SOURCE_REGISTRY.pop(next(iter(_IMAGE_SOURCE_REGISTRY)))
    _IMAGE_SOURCE_REGISTRY[key] = str(source)


def lookup_image_source(image_id: Any) -> Optional[str]:
    """Returns the recorded source for an image id, or None if unknown. Also
    matches on basename, because the Preparation Agent re-echoes the path
    through a plain-text block on its way to the Posting Agent and can still
    alter separators or expand the 8.3 short name."""
    key = _image_source_key(image_id)
    if not key:
        return None
    if key in _IMAGE_SOURCE_REGISTRY:
        return _IMAGE_SOURCE_REGISTRY[key]
    base = os.path.basename(key)
    if base:
        for known_key, source in _IMAGE_SOURCE_REGISTRY.items():
            if os.path.basename(known_key) == base:
                return source
    return None


def _fetch_stock_image(keyword: str, slot: str = "") -> Dict[str, Any]:
    """Fetches a stock image with alt text from Pexels (plain fn for internal
    callers such as _select_inpost_image). `slot` labels the image_logs row
    (featured/inpost) for cost-per-post accounting (stock cost is always 0)."""
    started = time.time()
    try:
        url = f"https://api.pexels.com/v1/search?query={keyword}&per_page=1"
        headers = {"Authorization": os.environ['PEXELS_API_KEY']}
        response = requests.get(url, headers=headers)
        response.raise_for_status()
        photo = response.json()['photos'][0]
        # Ensure the URL uses proper forward slashes and is properly formatted
        image_url = photo['src']['medium'].replace('\\\\', '/').replace(' ', '%20')
        # Validate that the URL is properly formatted
        if not image_url.startswith('http'):
            image_url = 'https://' + image_url.lstrip('https://').lstrip('http://')
        record_image_source(image_url, STOCK_IMAGE_SOURCE_LABEL)
        # Logged alongside the AI attempts so image_logs answers "what image
        # source did this run actually end up with" for fallback runs too.
        log_image_usage(
            STOCK_IMAGE_SOURCE_LABEL, "stock", keyword, "success",
            time.time() - started, detail="pexels", cost_usd=0.0, slot=slot,
        )
        return {"image_url": image_url, "alt_text": f"{keyword} stock image", "source": "Pexels", "evaluation_score": 8.5, "feedback": "High quality stock photo from Pexels"}
    except Exception as e:
        logger.error(f"Failed to fetch stock image from Pexels: {e}")
        log_image_usage(
            STOCK_IMAGE_SOURCE_LABEL, "stock", keyword, "error",
            time.time() - started, detail=str(e)[:500], cost_usd=0.0, slot=slot,
        )
        return {"error": f"Failed to fetch stock image from Pexels: {str(e)}"}


@function_tool
def get_stock_image_tool(keyword: str):
    """Fetches a stock image with alt text from Pexels.

    Direct stock fetch -- NO relevancy gate. Only used through
    select_inpost_image_tool for in-post images (which gates the candidate
    with a VLM+Jev relevancy score first). Featured images never use stock."""
    return _fetch_stock_image(keyword)

# Default model: flux-2-klein-4b, overridable via CLOUDFLARE_IMAGE_MODEL so
# swapping is an env change and not a code change.
#
# Why klein-4b: the free tier is 10,000 Neurons/day shared across all models,
# and this pipeline now runs a generate -> VLM+Jev check -> regenerate loop,
# so a post can consume 2-3 generations. Measured 2026-10-04 live costs for
# one 1280x720 image:
#   flux-2-klein-4b  ~110 n  -> ~90 generations/day
#   flux-2-klein-9b ~1364 n  -> ~7/day
#   flux-2-dev      ~2640 n  -> ~3/day
# klein-4b is ~12x cheaper than dev and ~2.3s-30s per call, and klein-4b
# also accepts an `image` reference (img2img), which the retry loop needs.
#
# KNOWN LIMITATION: klein-4b misspelled baked-in headline text in 3/3 live
# tests ("SPEC-DRIFIEN" / "SPEC-DRITEN" / "DRVVIEN"). Its Qwen3-4B text
# encoder is too weak for legible on-image titles. Handle it with the
# router below rather than by paying the 9b price on every image.
CLOUDFLARE_IMAGE_MODEL = os.environ.get("CLOUDFLARE_IMAGE_MODEL") or "@cf/black-forest-labs/flux-2-klein-4b"

# Router: first attempt is textless on the cheap model; only when that fails
# QA does the loop escalate to the text-capable model WITH a headline.
# Measured 2026-10-04: klein-4b garbles text 3/3, klein-9b and flux-2-dev
# spell "SPEC-DRIVEN WORKFLOW" correctly. Costs per 1280x720 image:
#   klein-4b ~110 n (~90/day)   klein-9b ~1364 n (~7/day)
# Worst case (all 3 attempts used) = 110 + 1364*2 ~= 2.8k n of 10k/day.
IMAGE_TEXT_MODEL = (
    os.environ.get("IMAGE_TEXT_MODEL") or "@cf/black-forest-labs/flux-2-klein-9b"
)
IMAGE_ROUTER = (os.environ.get("IMAGE_ROUTER") or "1").strip().lower() not in (
    "0",
    "false",
    "no",
    "off",
)

# Max generate -> validate -> regenerate cycles per post before accepting
# the best-scoring attempt or falling back to stock. Keeps worst-case
# neuron spend bounded (3 x ~110 n ~= 330 n of the 10,000/day pool).
IMAGE_MAX_REVISIONS = int(os.environ.get("IMAGE_MAX_REVISIONS") or "3")

# Image-provider quota circuit breaker: once a provider reports a
# quota/rate-limit (e.g. Cloudflare's daily neuron pool exhausted -- seen
# live 2026-10-08), EVERY image generation call short-circuits for the
# cooldown window instead of burning the revision loop on guaranteed
# failures. Cooldown is env-tunable; stock (Pexels) is unaffected.
IMAGE_QUOTA_COOLDOWN_S = int(os.environ.get("IMAGE_QUOTA_COOLDOWN_S") or "3600")
_IMAGE_QUOTA_UNTIL = 0.0
_QUOTA_MARKERS = ("quota", "rate limit", "ratelimit", "too many requests",
                  "429", "daily limit", "exceeded your", "exhausted",
                  "out of capacity", "insufficient credit", "limit reached")


def image_quota_active() -> bool:
    """True while the quota circuit breaker is engaged (fails open)."""
    try:
        return time.time() < _IMAGE_QUOTA_UNTIL
    except Exception:
        return False


def _mark_image_quota(detail: str) -> bool:
    """Arm the breaker when an API error smells like quota/rate-limiting.
    Returns True (and arms) only for quota-shaped errors; anything else
    leaves the loop to handle the failure normally."""
    global _IMAGE_QUOTA_UNTIL
    low = (detail or "").lower()
    if not any(marker in low for marker in _QUOTA_MARKERS):
        return False
    try:
        _IMAGE_QUOTA_UNTIL = time.time() + max(60, IMAGE_QUOTA_COOLDOWN_S)
    except Exception:
        pass
    logger.warning(
        f"Image provider quota/rate-limit detected; skipping image "
        f"generation for {IMAGE_QUOTA_COOLDOWN_S}s: {detail[:200]}"
    )
    return True

# Jev gate: VLM assessment passes only if BOTH the blog-topic match AND the
# house-style match clear these floors. Below either floor, regenerate with
# the previous image attached as reference plus the VLM's stated mismatches.
# Thresholds live in lib/image_vision.py (single source of truth); re-exported
# here because tools.py is where callers already look for image knobs.
IMAGE_MATCH_THRESHOLD = image_vision.IMAGE_MATCH_THRESHOLD
IMAGE_STYLE_THRESHOLD = image_vision.IMAGE_STYLE_THRESHOLD

# Human-readable source labels written into the generated_posts "Image
# Source" column. The AI label embeds the model id verbatim so "which model
# made this image" is answerable from the sheet alone.
STOCK_IMAGE_SOURCE_LABEL = "Pexels (stock photo)"


def _cloudflare_source_label(model: Optional[str] = None) -> str:
    return f"Cloudflare Workers AI ({model or CLOUDFLARE_IMAGE_MODEL})"


# Per-image cost in USD for the image_logs "Cost (USD)" column (spec 5.9).
# Cloudflare Workers AI bills in Neurons at $0.011 / 1,000; measured
# 2026-10-04 per 1280x720 image: klein-4b ~110n, klein-9b ~1364n,
# flux-2-dev ~2640n. Pexels stock is free (0.0). IMAGE_COST_DEFAULT_USD
# keeps the log honest for any new/renamed model id we have not measured.
IMAGE_COST_USD: Dict[str, float] = {
    "@cf/black-forest-labs/flux-2-klein-4b": 0.0012,
    "@cf/black-forest-labs/flux-2-klein-9b": 0.0150,
    "@cf/black-forest-labs/flux-2-dev": 0.0290,
}
IMAGE_COST_DEFAULT_USD = float(os.environ.get("IMAGE_COST_DEFAULT_USD") or "0.0012")


def _image_cost_usd(model: Optional[str]) -> float:
    """Measured USD cost of one generated image, or the env-tunable default
    for unmeasured model ids."""
    if not model:
        return IMAGE_COST_DEFAULT_USD
    return IMAGE_COST_USD.get(model, IMAGE_COST_DEFAULT_USD)


def _image_plan(attempt: int) -> tuple:
    """Which model + typography this attempt should use.

    Router off: every attempt uses the configured model with a headline.
    Router on: attempt 1 is the cheap model with zero text (it cannot
    misspell what it never renders); attempt 2+ escalate to IMAGE_TEXT_MODEL
    with a headline."""
    if not IMAGE_ROUTER:
        return CLOUDFLARE_IMAGE_MODEL, "headline"
    if attempt <= 1:
        return CLOUDFLARE_IMAGE_MODEL, "none"
    return IMAGE_TEXT_MODEL, "headline"


# How many times _generate_image_cloudflare sends one payload before moving
# to the next payload variant (reference image first, then none). Cloudflare
# rejects before rendering on failure, so a wasted retry costs latency and
# zero Neurons.
_GEN_TRIES_PER_PAYLOAD = 2
_GEN_RETRY_DELAY = 1.0

# Errors worth resending verbatim. `"code":3030` is Workers AI content
# moderation ("Your output has been flagged") and is demonstrably flaky: the
# identical prompt succeeded, failed, then succeeded again within minutes.
_RETRYABLE_ERROR_MARKERS = (
    '"code":3030',
    '"code": 3030',
    "flagged",
    "HTTP 429",
    "HTTP 500",
    "HTTP 502",
    "HTTP 503",
    "HTTP 504",
    "timed out",
    "Connection",
)


def _retryable_generation_error(detail: str) -> bool:
    return any(marker in (detail or "") for marker in _RETRYABLE_ERROR_MARKERS)


def _generate_image_cloudflare(
    prompt: str, keyword: str, reference_b64: Optional[str] = None,
    model: Optional[str] = None, slot: str = "featured",
) -> Optional[Dict[str, Any]]:
    """Primary AI image generator via Cloudflare Workers AI (10,000 free
    Neurons/day, no credit card required). Returns None on failure -- the
    caller decides what (if anything) substitutes; this function never
    fetches stock itself.

    `reference_b64` is an optional base64 PNG/JPEG of the previous attempt.
    FLUX.2 [klein] unifies generation and editing in one model, so passing it
    lets the model revise toward the prompt instead of starting blind. If the
    model rejects the reference, we retry once without it rather than failing
    the whole post.

    On success the bytes on disk are tagged with IPTC
    `trainedAlgorithmicMedia` provenance (lib/image_provenance, zero cost)
    and the result dict carries `cost_usd` for the per-image audit row."""
    account_id = os.environ.get("CLOUDFLARE_ACCOUNT_ID")
    api_token = os.environ.get("CLOUDFLARE_API_TOKEN")
    if not account_id or not api_token:
        logger.info("CLOUDFLARE_ACCOUNT_ID/CLOUDFLARE_API_TOKEN not set; skipping Cloudflare Workers AI image generation.")
        return None
    if image_quota_active():
        logger.info("Image quota circuit breaker active; skipping Cloudflare Workers AI call.")
        return None
    model = model or CLOUDFLARE_IMAGE_MODEL

    url = f"https://api.cloudflare.com/client/v4/accounts/{account_id}/ai/run/{model}"
    headers = {"Authorization": f"Bearer {api_token}"}
    # FLUX.2 requires multipart/form-data even for a text-only prompt (a
    # documented quirk of this model family on Workers AI).
    # (None, value) tuples send plain form fields without attaching a file.
    base_fields = {
        "prompt": prompt,
        "width": "1280",   # 16:9 landscape, standard blog hero-image framing
        "height": "720",   # both divisible by 16 as FLUX.2 requires
    }

    def _post(fields: Dict[str, str]):
        body = b""
        boundary = "----cf" + str(int(time.time() * 1000))
        for name, value in fields.items():
            body += (
                f"--{boundary}\r\n"
                f'Content-Disposition: form-data; name="{name}"\r\n\r\n'
                f"{value}\r\n"
            ).encode("utf-8")
        body += f"--{boundary}--\r\n".encode("utf-8")
        return requests.post(
            url,
            headers={**headers, "Content-Type": f"multipart/form-data; boundary={boundary}"},
            data=body,
            timeout=90,
        )

    attempts = []
    if reference_b64:
        attempts.append({**base_fields, "image": reference_b64})
    attempts.append(base_fields)

    last_error: Optional[str] = None

    def _log_attempt(status: str, started: float, detail: str = "", with_ref: bool = False) -> None:
        # One row per API attempt in image_logs, so "which image generation
        # model ran, how long it took, how much it cost, and how many times the
        # generate -> validate -> regenerate loop actually called it" is
        # answerable from the sheet alone. Reference=yes marks the img2img
        # revision attempts; slot/prompt feed the per-image cost audit
        # (spec 5.9: prompt, model, cost, generation ms per image).
        latency_s = time.time() - started
        log_image_usage(
            model,
            "generate",
            keyword,
            status,
            latency_s,
            reference="yes" if with_ref else "no",
            detail=detail,
            # Rejections happen before rendering (free); only successful
            # generations consume Neurons, so error rows must not inflate
            # the per-image cost audit.
            cost_usd=_image_cost_usd(model) if status == "success" else 0.0,
            slot=slot,
            prompt=prompt,
            latency_ms=round(latency_s * 1000, 1),
        )

    for fields in attempts:
        with_ref = "image" in fields
        for try_no in range(1, _GEN_TRIES_PER_PAYLOAD + 1):
            attempt_started = time.time()
            response = None
            detail = ""
            image_b64 = None
            try:
                response = _post(fields)
                if not response.ok:
                    # Keep the body: Cloudflare explains 400s as JSON there.
                    detail = f"HTTP {response.status_code} :: {response.text[:400]}"
                else:
                    payload = response.json()
                    if not payload.get("success"):
                        detail = json.dumps(payload.get("errors"))[:500]
                    else:
                        image_b64 = (payload.get("result") or {}).get("image")
                        if not image_b64:
                            detail = "response missing image data"
            except Exception as e:
                detail = str(e)

            if image_b64:
                image_bytes = base64.b64decode(image_b64)
                # flux-2 answers with JPEG regardless of what the caller asked
                # for. Sniff the real format so the temp file's extension, the
                # VLM data URI and Sanity's Content-Type all agree with the bytes.
                suffix = image_format.sniff_ext(image_bytes, fallback=".jpg")
                with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
                    tmp.write(image_bytes)
                    local_path = tmp.name
                # Spec 5.9 / playbook 12: IPTC Digital Source Type
                # = trainedAlgorithmicMedia on every AI image. Best-effort --
                # a tagging failure must not discard a generated image.
                iptc_ok = image_provenance.tag_trained_algorithmic_media(local_path)
                logger.info(
                    f"Successfully generated image via Cloudflare Workers AI ({model}, "
                    f"reference={'yes' if with_ref else 'no'}): {local_path} "
                    f"(iptc_trained_algorithmic_media={'ok' if iptc_ok else 'failed'})"
                )
                source_label = _cloudflare_source_label(model)
                record_image_source(local_path, source_label)
                _log_attempt("success", attempt_started, detail="ok", with_ref=with_ref)
                return {
                    "image_url": local_path,
                    "alt_text": f"{keyword} illustration",
                    "source": source_label,
                    "model": model,
                    "cost_usd": _image_cost_usd(model),
                    "iptc_trained_algorithmic_media": iptc_ok,
                    "evaluation_score": 8.5,
                    "feedback": f"Generated via Cloudflare Workers AI {model} (primary AI image generator, genuinely free tier)",
                }

            last_error = detail
            logger.error(f"Cloudflare Workers AI image generation failed: {detail}")
            _log_attempt("error", attempt_started, detail=detail[:500], with_ref=with_ref)
            # Quota/rate-limit errors arm the circuit breaker: stop BOTH the
            # retry loop and the router ladder immediately (every further
            # call would fail the same way and only burn latency/log rows).
            if _mark_image_quota(detail):
                return None
            # Workers AI's moderation flag (code 3030) fires intermittently on
            # the very same prompt -- live evidence: the identical request
            # succeeded seconds earlier and failed later. One blind retry is
            # cheaper than abandoning the attempt.
            if try_no < _GEN_TRIES_PER_PAYLOAD and _retryable_generation_error(detail):
                time.sleep(_GEN_RETRY_DELAY)
                continue
            # Fall through to the next payload (i.e. drop the image reference,
            # which some flags blame the input image for).
            break

    logger.error(f"Cloudflare Workers AI image generation gave up: {last_error}")
    return None


# The house thumbnail prompt, verbatim from the manual workflow that produced
# every existing thumbnail on owaisabdullah.dev. Kept as one block so the
# visual identity (cinematic 3D tech storytelling, deep-navy foundation with
# electric blue/cyan plus violet or amber accents, expressive original
# characters, minimal on-image text) stays identical across posts; only the
# article-specific slots are filled per run.
#
# NOTE: ~4.2k chars before the router's closing rule (~4.7k filled). Workers
# AI does not publish a maxLength for the flux-2 family (flux-1-schnell caps
# prompts at 2048); both klein-4b and klein-9b accept the filled prompt live.
# If a model swap starts rejecting prompts, trim this block first.
_HOUSE_IMAGE_PROMPT_TEMPLATE = '''Create a premium cinematic hero thumbnail for a technical blog post published on owaisabdullah.dev. The site name is context for the brand only -- never typeset it, never show it as a logo, badge or watermark.

**Visual identity:** Cinematic 3D tech storytelling, polished CGI, expressive original characters, sophisticated lighting, rich environments, and strong visual metaphors. The result should feel like high-end animated-film concept art blended with premium technology editorial artwork—not a generic SaaS advertisement.

**Format and composition**
- Landscape 16:9 aspect ratio, ideally 1600 × 900 pixels.
- Compose for a website blog card and a full-width article hero.
- Establish one unmistakable focal point with clear foreground, middle ground, and background.
- Use dramatic perspective, cinematic depth of field, realistic material details, atmospheric lighting, and carefully controlled visual complexity.
- Keep the main subject large, recognizable, and readable at small thumbnail sizes.
- [INSERT HEADLINE SPACE LINE]

**Color and lighting**
- Use deep navy, midnight blue, and charcoal as the usual foundation.
- Add electric blue and cyan lighting, with violet, magenta, or pink accents where they suit the subject.
- Introduce warm amber, orange, or gold highlights to create contrast and depth.
- Adapt the palette to the specific product, logo, or article topic rather than forcing identical colors onto every image.
- Use luminous accents, subtle reflections, atmospheric haze, and rich shadows without excessive neon.

**Character direction**
- When a character helps tell the story, create a distinctive, expressive, high-quality 3D cartoon character designed specifically for this article.
- Explore different character types, silhouettes, personalities, poses, facial expressions, costumes, and materials across different posts.
- The character must embody the article's subject or represent its central conflict, transformation, tool, or outcome.
- Characters can be cute, clever, mysterious, mischievous, intimidating, competitive, heroic, or humorous depending on the topic.
- Do not automatically use robots, hoodie-wearing developers, people at desks, or the same mascot in every image.
- For articles that work better with objects, creatures, environments, or abstract visual metaphors, do not force a human character into the composition.

**Topic-specific storytelling**
Before designing the image, identify the article's central idea and translate it into one memorable visual scene. Explore original concepts such as a character battle, a magical transformation, a miniature automated city, a branching decision system, a dramatic before-and-after scene, or a powerful symbolic object.
Use the actual article topic and relevant brand identity to guide the imagery. Include recognizable logos only when appropriate, and preserve their supplied shapes and colors as closely as possible.

[INSERT TYPOGRAPHY]

**Avoid**
Generic stock imagery, repetitive compositions, the same robot mascot across posts, generic people staring at laptops, cluttered floating dashboards, excessive icons, walls of text, flat corporate illustrations, cheap-looking plastic materials, oversaturated neon everywhere, watermarks, misspelled text, and irrelevant decorative technology.

**Most important rule:** Every thumbnail must have its own original visual concept and character direction. Maintain the recognizable cinematic quality and overall visual polish of owaisabdullah.dev, but vary the subject, composition, color balance, setting, and storytelling from one article to the next.

**Article title:** [INSERT TITLE]

**Article URL or summary:** [INSERT URL OR SUMMARY]

**Brand logo or reference image:** [ATTACH IF RELEVANT]'''

# Exact slot markers from the original manual template, replaced per post.
_TITLE_SLOT = "[INSERT TITLE]"
_SUMMARY_SLOT = "[INSERT URL OR SUMMARY]"
_LOGO_SLOT = "[ATTACH IF RELEVANT]"
_TYPOGRAPHY_SLOT = "[INSERT TYPOGRAPHY]"
_HEADLINE_SPACE_SLOT = "[INSERT HEADLINE SPACE LINE]"

# Typography directives the router swaps into the template.
# "headline" is the original house wording, verbatim. "none" exists because
# klein-4b's text encoder garbles baked-in words (3/3 live tests:
# SPEC-DRIFIEN / SPEC-DRITEN / SPEC-DRVIEN), so the cheap first pass never
# asks for text -- and therefore cannot misspell it.
_HOUSE_TYPOGRAPHY = '''**Typography**
- Keep on-image text minimal: ideally a short title or 2-5-word hook.
- Use bold, clean, legible typography with strong contrast.
- Prioritize the visual story over explanatory text.
- Do not invent product specifications, prices, performance numbers, or unsupported claims.
- Avoid tiny labels, crowded UI panels, unnecessary slogans, and excessive text.'''

_NO_TEXT_TYPOGRAPHY = '''**Typography - NO TEXT AT ALL**
- Render zero on-image words, letters, numbers, captions or labels.
- No headline, no subtitle, no signboards, no screen UI text, no watermarks.
- Tell the whole story with the scene; the page supplies the real title in HTML.
- Anything that would normally carry writing should instead show abstract shapes, glow or texture.'''

_TEXT_MODES = {
    "headline": (
        _HOUSE_TYPOGRAPHY,
        "Reserve clean negative space for a short headline only when needed.",
    ),
    "none": (
        _NO_TEXT_TYPOGRAPHY,
        "Do not leave negative space for text; fill the frame with the scene.",
    ),
}

# The mid-prompt "NO TEXT AT ALL" block is not enough on its own: klein-4b
# still baked the article title into the frame (live run read back
# "Spec-Drivien Workom ..."), which is exactly the garbling the cheap pass
# exists to avoid. Mirrored at the END of the prompt, after the article
# title it is copying, because last-instruction-wins is what these models
# actually obey.
_NO_TEXT_CLOSING_RULE = '''**FINAL RULE - this overrides every instruction above.**
- The rendered image must contain ZERO text: no headline, no title, no subtitle, no sign, no label, no number, no caption, no watermark, no word-shaped logos.
- Do not write the article title or anything else into the picture.
- Everything written in this prompt describes the SUBJECT of the image; it is not copy to be typeset.
- Where an object would naturally carry writing, show blank material, glowing lines or abstract glyph texture instead.'''

# Headline mode needs the mirror-image guard. Live escalation run: klein-9b
# obeyed "do not invent a brand logo or watermark" in the middle of the
# prompt, then burned the domain into the corner as one anyway -- VLM read it
# back as text_seen="owaisabdullah.dev", issue="watermark", blog score 0.04,
# which throws away an otherwise good (style 0.81) image.
_HEADLINE_CLOSING_RULE = '''**FINAL RULE - this overrides every instruction above.**
- The image may carry exactly ONE piece of text: a short headline (2-5 words) taken from the article title below.
- Never render a URL, the domain owaisabdullah.dev, a site name, an author name, a signature, a logo, a watermark, a badge or a corner label.
- No subtitle, no body copy, no UI text, no prices or numbers, no credits.
- Any surface that would normally hold a logo or URL stays blank or abstract.'''

# Cap on an agent-supplied scene concept so a model that tries to write a
# whole replacement prompt cannot blow past the flux-2 prompt limits.
_SCENE_CONCEPT_MAX_CHARS = 600


def _build_house_prompt(
    title: str,
    summary: str,
    scene_concept: str = None,
    text_mode: str = "headline",
) -> str:
    """Fill the house template's per-article slots and append the agent's
    scene concept (if any) as an explicit direction, without letting it
    replace the house style.

    `text_mode` picks the typography block: "headline" (original house
    wording, used on the text-capable model) or "none" (zero on-image text,
    used on the cheap model so it cannot misspell anything)."""
    prompt = _HOUSE_IMAGE_PROMPT_TEMPLATE
    prompt = prompt.replace(_TITLE_SLOT, (title or "").strip() or "[Article title unavailable]")
    prompt = prompt.replace(_SUMMARY_SLOT, (summary or "").strip() or "[Article summary unavailable]")
    # No image can actually be attached over this tool boundary, so say so
    # explicitly instead of leaving a placeholder that invites the model to
    # invent a logo.
    prompt = prompt.replace(_LOGO_SLOT, "none supplied - do not invent a brand logo or watermark")

    typography, space_line = _TEXT_MODES.get(text_mode, _TEXT_MODES["headline"])
    prompt = prompt.replace(_TYPOGRAPHY_SLOT, typography)
    prompt = prompt.replace(_HEADLINE_SPACE_SLOT, space_line)

    concept = (scene_concept or "").strip()
    if concept:
        if len(concept) > _SCENE_CONCEPT_MAX_CHARS:
            concept = concept[:_SCENE_CONCEPT_MAX_CHARS].rstrip() + "..."
        prompt += f"\n\n**Scene concept chosen for this post:** {concept}"

    if text_mode == "none":
        # "**Article title:** <headline>" is the single strongest instruction
        # to typeset, so relabel it and close with the hard no-text rule.
        prompt = prompt.replace(
            "**Article title:**",
            "**Article subject (describe only - never write it into the picture):**",
        )
        prompt += "\n\n" + _NO_TEXT_CLOSING_RULE
    else:
        # Allow the headline, but pin down exactly how much text is legal so
        # the model cannot promote the brand line into a watermark.
        prompt += "\n\n" + _HEADLINE_CLOSING_RULE
    return prompt


def _file_to_b64(path: str) -> Optional[str]:
    try:
        with open(path, "rb") as fh:
            return base64.b64encode(fh.read()).decode("ascii")
    except OSError as e:
        logger.warning(f"Cannot re-read generated image as reference: {path}: {e}")
        return None


def _rank_image_verdict(verdict: Dict[str, Any]) -> float:
    """Best-attempt scoring: a passing QA beats a failing one, then higher
    Jev Noul scores win. Fallback (unjudgeable) scores lowest but still > 0
    so we always keep something."""
    blog = verdict.get("matches_blog")
    style = verdict.get("matches_style")
    score = 0.0
    if isinstance(blog, (int, float)):
        score += float(blog)
    if isinstance(style, (int, float)):
        score += float(style)
    if verdict.get("passed"):
        score += 1000.0
    elif verdict.get("fallback") and blog is None:
        score += 0.001
    return score


@function_tool
def generate_image_tool(keyword: str, title: str = None, summary: str = None,
                        custom_prompt: str = None, slot: str = "featured"):
    """Generates a blog image using Cloudflare Workers AI
    (genuinely free, no credit card, no per-key credential fragility).

    The image is ALWAYS built from owaisabdullah.dev's house cinematic
    thumbnail prompt -- you do not write the image prompt yourself. Pass:

    - keyword: the post's topic/keyword (also used for alt text)
    - title: the post's article title (fills the house prompt's title slot)
    - summary: the post's 50-160 char SEO summary (fills the summary slot)
    - custom_prompt: OPTIONAL, one short sentence naming the specific visual
      scene you want for THIS post (e.g. "two gears meshing, one cracked and
      one new, showing legacy code being replaced"). It is appended as a
      scene concept; it never replaces the house style.
    - slot: "featured" (default, hero thumbnail) or "inpost" (body image) --
      only labels the image_logs cost/audit row.

    Each attempt is checked by a VLM (which actually looks at the pixels)
    plus Jev, which decides whether the image matches the article topic AND
    the house style. If either check misses its threshold the image is
    regenerated with the previous attempt attached as a reference and the
    VLM's specific complaints written into the prompt -- up to
    IMAGE_MAX_REVISIONS attempts. The best attempt is always returned.

    A model router runs inside the loop (IMAGE_ROUTER, on by default):
    attempt 1 uses the cheap model (flux-2-klein-4b, ~110 Neurons) with
    ZERO on-image text, because that model garbles baked-in words. Only if
    it fails QA does the loop escalate to IMAGE_TEXT_MODEL
    (flux-2-klein-9b, ~1364 Neurons) WITH a headline, which spells
    correctly. Set IMAGE_ROUTER=0 to pin everything to CLOUDFLARE_IMAGE_MODEL.

    Returns a dict with image_url/alt_text/source plus a `qa` block
    {passed, matches_blog, matches_style, attempts, model, router, issues}.
    A non-passing `qa.passed` is NOT an error -- an image is returned if any
    attempt succeeded. On total failure, returns an error dict: featured
    images do NOT fall back to stock (brand control) -- the caller publishes
    without a featured image and flags it; in-post images go through
    select_inpost_image_tool's stock-first gate instead."""
    return _generate_image(keyword, title, summary, custom_prompt, slot)


def _generate_image(keyword: str, title: Optional[str] = None,
                    summary: Optional[str] = None,
                    custom_prompt: Optional[str] = None,
                    slot: str = "featured") -> Dict[str, Any]:
    """Plain-function body of generate_image_tool for internal callers
    (e.g. _select_inpost_image, which must not call the decorated tool).
    See the tool docstring for the contract; `slot` labels the audit rows
    (featured/inpost) and is returned in the result dict."""
    best: Optional[Dict[str, Any]] = None
    best_verdict: Dict[str, Any] = {}
    best_rank = -1.0
    reference_b64: Optional[str] = None
    revision_suffix = ""
    previous_model: Optional[str] = None
    attempts = 0
    qa_trace: List[Dict[str, Any]] = []
    router_plan: List[str] = []

    # Freepik was removed as a provider here (persistent 401 -- an invalid/
    # expired key that was never rotated -- and a one-time trial credit
    # rather than an ongoing free tier to begin with). Cloudflare Workers AI
    # is the sole AI generator now; on failure the caller decides the
    # substitute (featured: publish flagged-without-image; in-post: the
    # stock-first gate already ran, so it also reports failure).
    loop_started = time.time()
    for attempt in range(1, IMAGE_MAX_REVISIONS + 1):
        if image_quota_active():
            log_image_usage(
                CLOUDFLARE_IMAGE_MODEL,
                "result",
                title or keyword,
                "skipped",
                time.time() - loop_started,
                detail=f"attempts=0/{IMAGE_MAX_REVISIONS} quota circuit breaker active "
                       f"(provider rate/quota limit)",
                cost_usd=0.0,
                slot=slot,
            )
            return {"error": "Image provider quota exhausted - skipping generation "
                             "(circuit breaker; retry after cooldown)",
                    "quota": True, "slot": slot}
        model, text_mode = _image_plan(attempt)
        router_plan.append(f"a{attempt}={model.rsplit('/', 1)[-1]}/{text_mode}")
        base_prompt = _build_house_prompt(
            title, summary, custom_prompt, text_mode=text_mode
        )
        if attempt == 1 and len(base_prompt) > 6000:
            logger.warning(
                f"Thumbnail prompt is {len(base_prompt)} chars; flux-2 prompt limits are unpublished "
                f"and flux-1-schnell caps at 2048. If generation fails, trim _HOUSE_IMAGE_PROMPT_TEMPLATE."
            )

        # Escalating to a different model means starting clean: a textless
        # 4b image is the wrong edit source for 9b's headline pass, and the
        # two models do not share an img2img latent space.
        switching = previous_model is not None and model != previous_model
        if switching:
            reference_b64 = None
            revision_suffix = ""
        previous_model = model
        prompt = base_prompt + revision_suffix

        result = _generate_image_cloudflare(
            prompt, title or keyword, reference_b64=reference_b64,
            model=model, slot=slot,
        )
        if not result:
            # This router step produced nothing (rate limit, Cloudflare's
            # content-moderation flag -- seen live as HTTP 400 code 3030
            # "Your output has been flagged" -- or a network blip). Keep the
            # loop alive so the next plan step still runs instead of handing
            # back an image that already failed QA.
            logger.warning(
                f"Image generation returned nothing on attempt {attempt} "
                f"({model.rsplit('/', 1)[-1]}); continuing to the next plan step."
            )
            continue
        attempts = attempt
        image_path = result["image_url"]

        verdict = image_vision.validate_thumbnail(image_path, title, summary)
        rank = _rank_image_verdict(verdict)
        qa_trace.append(
            {
                "attempt": attempt,
                "model": model,
                "text_mode": text_mode,
                "passed": verdict.get("passed"),
                "matches_blog": verdict.get("matches_blog"),
                "matches_style": verdict.get("matches_style"),
                "issues": (verdict.get("issues") or [])[:5],
                "vlm": (verdict.get("vlm") or {}).get("model"),
                "fallback": verdict.get("fallback"),
                "latency_ms": verdict.get("latency_ms"),
            }
        )
        logger.info(
            f"Image QA attempt {attempt}/{IMAGE_MAX_REVISIONS} ({model.rsplit('/', 1)[-1]}, "
            f"text={text_mode}): passed={verdict.get('passed')} "
            f"matches_blog={verdict.get('matches_blog')} matches_style={verdict.get('matches_style')} "
            f"issues={len(verdict.get('issues') or [])}"
        )

        if rank > best_rank:
            # Keep the winner; discard any previous runner-up's temp file.
            if best and best.get("image_url") and best["image_url"] != image_path:
                try:
                    os.remove(best["image_url"])
                except OSError:
                    pass
            best, best_verdict, best_rank = result, verdict, rank

        if verdict.get("passed"):
            break

        # Reject this attempt: use it as the edit reference for the next one.
        next_reference = _file_to_b64(image_path)
        if not next_reference:
            break
        guidance = image_vision.revision_guidance(verdict)
        revision_suffix = (
            f"\n\n**Revision required (attempt {attempt + 1} of {IMAGE_MAX_REVISIONS}). "
            f"The previous image attached as a reference did not pass QA:**\n{guidance}\n\n"
            f"Keep the same article subject but improve on the reference. "
            f"The attached reference is the FAILED attempt, not an asset to preserve."
        )
        reference_b64 = next_reference

    if not best:
        log_image_usage(
            CLOUDFLARE_IMAGE_MODEL,
            "result",
            title or keyword,
            "failed",
            time.time() - loop_started,
            detail=f"attempts=0/{IMAGE_MAX_REVISIONS} router={','.join(router_plan)} all generation attempts failed",
            cost_usd=0.0,
            slot=slot,
        )
        return {"error": "All image generation services failed", "slot": slot}

    best_model = best.get("model") or CLOUDFLARE_IMAGE_MODEL
    # A non-passing QA is not an error: an image was produced and further
    # attempts would only burn neuron quota. Report it for observability.
    qa = {
        "passed": bool(best_verdict.get("passed")),
        "matches_blog": best_verdict.get("matches_blog"),
        "matches_style": best_verdict.get("matches_style"),
        "threshold_blog": image_vision.IMAGE_MATCH_THRESHOLD,
        "threshold_style": image_vision.IMAGE_STYLE_THRESHOLD,
        "attempts": attempts,
        "max_revisions": IMAGE_MAX_REVISIONS,
        "model": best_model,
        "router": router_plan,
        "issues": best_verdict.get("issues") or [],
        "text_seen": best_verdict.get("text_seen"),
        "fallback": bool(best_verdict.get("fallback")),
        "trace": qa_trace,
    }
    best["qa"] = qa
    if title:
        best["alt_text"] = title
    best["slot"] = slot
    # One summary row per call: the VLM/Jev verdict for the winning attempt,
    # so image_logs answers "did it pass, and after how many tries" without
    # having to join the per-attempt rows above it. Cost = the winning
    # attempt's measured generation cost (the per-attempt rows above carry
    # each attempt's own cost).
    log_image_usage(
        best_model,
        "result",
        title or keyword,
        "passed" if qa["passed"] else "failed",
        time.time() - loop_started,
        detail=(
            f"attempts={attempts}/{IMAGE_MAX_REVISIONS} router={','.join(router_plan)} "
            f"blog={qa['matches_blog']} style={qa['matches_style']} "
            f"issues={'; '.join(str(i) for i in (qa['issues'] or [])[:3])}"
        ),
        cost_usd=best.get("cost_usd", 0.0),
        slot=slot,
    )
    return best


def _download_image_to_temp(url: str) -> Optional[str]:
    """Download a remote image (e.g. Pexels) to a temp file so the VLM can
    inspect the actual pixels. Returns None on any failure."""
    try:
        response = requests.get(url, timeout=30)
        response.raise_for_status()
        ext = os.path.splitext(url.split("?", 1)[0])[-1] or ".jpg"
        with tempfile.NamedTemporaryFile(delete=False, suffix=ext) as tmp:
            tmp.write(response.content)
            return tmp.name
    except Exception as e:
        logger.warning(f"Image download failed for VLM gate: {e}")
        return None


def _select_inpost_image(
    topic: str,
    section_summary: str = "",
    alt_text: str = "",
    fetch_stock=None,
    score=None,
    generate=None,
) -> Dict[str, Any]:
    """Stock-first in-post image selection (spec 5.9).

    Pexels candidate -> download -> VLM + Jev topic-relevancy on a 0-100
    scale: >= 90 (IMAGE_STOCK_RELEVANCY_THRESHOLD) keeps the free stock
    image; below 90, or stock unavailable/undownloadable, it generates with
    the house AI model instead. If both fail it returns an error dict --
    the caller then skips the image entirely (spec 5.9's ultimate fallback,
    "publish without an image + flag"); it never substitutes an unvetted
    image.

    Alt text = section_summary (spec 5.9). `fetch_stock`/`score`/`generate`
    hooks exist for tests; production callers use the defaults
    (_fetch_stock_image, image_vision.score_topic_relevancy, _generate_image).
    """
    fetch_stock = fetch_stock or _fetch_stock_image
    score_fn = score or image_vision.score_topic_relevancy
    generate_fn = generate or _generate_image
    threshold = int(image_vision.IMAGE_STOCK_RELEVANCY_THRESHOLD * 100)
    chosen_alt = (alt_text or "").strip() or (section_summary or "").strip()
    gate_started = time.time()
    gate: Dict[str, Any] = {"threshold": threshold, "decision": None}

    def _log_gate(status: str, detail: str, latency_ms=None) -> None:
        log_image_usage(
            STOCK_IMAGE_SOURCE_LABEL, "gate", topic, status,
            time.time() - gate_started, detail=detail, cost_usd=0.0,
            slot="inpost", latency_ms=latency_ms,
        )

    stock: Optional[Dict[str, Any]] = None
    if (topic or "").strip():
        try:
            stock = fetch_stock(topic, "inpost")
        except Exception as e:
            logger.warning(f"fetch_stock raised for {topic!r}: {e}")
            stock = {"error": str(e)}

    if stock and stock.get("image_url"):
        stock_url = str(stock["image_url"])
        local = stock_url if not stock_url.startswith("http") else _download_image_to_temp(stock_url)
        if local:
            verdict = score_fn(local, topic, section_summary) or {}
            score_val = verdict.get("score")
            passed = bool(verdict.get("passed"))
            gate.update(
                stock_candidate=stock_url,
                stock_score=score_val,
                stock_passed=passed,
                stock_fallback=bool(verdict.get("fallback")),
                latency_ms=verdict.get("latency_ms"),
            )
            issues = "; ".join(str(i) for i in (verdict.get("issues") or [])[:3])
            _log_gate(
                "stock_accepted" if passed else "stock_below_threshold",
                f"score={score_val}/100 threshold={threshold} "
                f"fallback={verdict.get('fallback')} issues={issues}",
                latency_ms=verdict.get("latency_ms"),
            )
            if passed:
                if local != stock_url:
                    try:
                        os.remove(local)
                    except OSError:
                        pass
                out = dict(stock)
                out.update(
                    alt_text=chosen_alt or stock.get("alt_text"),
                    # Keep the historical 0-10 evaluation_score consumers
                    # happy while the gate truth lives in relevancy_score.
                    relevancy_score=score_val if isinstance(score_val, (int, float)) else threshold,
                    evaluation_score=round((score_val if isinstance(score_val, (int, float)) else threshold) / 10.0, 1),
                    feedback=f"VLM topic-relevancy {score_val}/100 >= {threshold}: free stock accepted",
                    slot="inpost",
                    gate=gate,
                )
                gate["decision"] = "stock_accepted"
                return out
            # Below threshold: the local copy was only for the VLM check.
            if local != stock_url:
                try:
                    os.remove(local)
                except OSError:
                    pass
        else:
            gate.update(stock_candidate=stock_url, stock_passed=False, stock_download_failed=True)
            _log_gate("stock_undownloadable", "could not download candidate for VLM check")
    else:
        gate.update(stock_candidate=None, stock_passed=False,
                    stock_error=(stock or {}).get("error", "no candidate") if isinstance(stock, dict) else "no candidate")
        _log_gate("stock_unavailable", str(gate.get("stock_error") or "no candidate")[:200])

    # Stock rejected/unavailable -> AI generation with the house prompt.
    try:
        ai = generate_fn(
            keyword=topic, title=topic, summary=section_summary,
            custom_prompt=None, slot="inpost",
        )
    except Exception as e:
        logger.warning(f"_select_inpost_image generation raised: {e}")
        ai = {"error": str(e)}
    if ai and ai.get("image_url"):
        out = dict(ai)
        if chosen_alt:
            out["alt_text"] = chosen_alt
        gate["decision"] = "ai_generated"
        out["slot"] = "inpost"
        out["gate"] = gate
        return out

    gate["decision"] = "failed"
    return {
        "error": "No in-post image available: stock failed the relevancy "
                 "gate (or was unavailable) and AI generation also failed. "
                 "Skip the image for this section and flag it.",
        "slot": "inpost",
        "gate": gate,
    }


@function_tool
def select_inpost_image_tool(topic: str, section_summary: str = "",
                             alt_text: str = ""):
    """Stock-first VLM-gated image for an in-post (body) slot (spec 5.9).

    Pass the SECTION topic, the section's one-sentence summary (also used
    as alt text unless you pass alt_text explicitly), and optionally an
    explicit alt text.

    How it decides (you cannot bypass this gate):
    1. Fetches the best Pexels stock candidate for the topic (free).
    2. Downloads it and a VLM looks at the actual pixels; Jev scores topic
       relevancy 0-100 (style/stock-ness are ignored -- relevancy only).
    3. Score >= 90 returns the stock image (evaluation_score = score/10,
       relevancy_score = score, source=Pexels).
    4. Score < 90, or stock unavailable/undownloadable, generates an
       AI image instead with the house style prompt (slot=inpost).
    5. If BOTH fail, returns an error dict -- report it and continue
       WITHOUT an image for that section; never insert an unvetted image.

    Returns image_url/alt_text/source (+ gate block with the score and
    decision) like the other image tools."""
    return _select_inpost_image(topic, section_summary, alt_text)

@function_tool
def post_to_sanity_tool(
    title: str,
    summary: str,
    content: str,
    categories: List[str],
    image_path: str,
    slug: Optional[str] = None,
    alt_text: Optional[str] = None,
    faqs: Optional[List[Any]] = None
) -> Dict[str, Any]:
    """
    Posts a blog to Sanity CMS using the updated SanityAdapter.

    Args:
        title (str): Title of the blog post.
        summary (str): Summary or description of the blog post.
        content (str): Main blog content in Markdown format (with integrated links).
        categories (List[str]): List of categories.
        image_path (str): Local path or URL of the featured image.
        slug (Optional[str]): Unique slug for the blog post URL.
        alt_text (Optional[str]): Alt text for the featured image.
        faqs (Optional[List[FAQItem]]): List of FAQs as structured objects with question and answer.

    Returns:
        Dict[str, Any]: Result containing status, post_id, image info, or errors.
    """
    try:
        # Initialize SanityAdapter
        adapter = SanityAdapter(
            project_id=os.environ['SANITY_PROJECT_ID'],
            # GitHub Actions resolves ${{ secrets.SANITY_DATASET }} to an empty
            # string (not an absent key) when the secret isn't configured, so
            # os.environ.get(key, default) never falls through to 'production'
            # -- the key exists in os.environ, just with an empty value. Use
            # `or` instead so both "unset" and "set but empty" fall back.
            dataset=os.environ.get('SANITY_DATASET') or "production",
            token=os.environ['SANITY_API_TOKEN']
        )

        # --- Image Handling ---
        # Check if image_path is a URL Sanity can fetch directly (no need to download)
        if image_path and image_path.startswith('http'):
            pexel_url = 'pexels' in image_path.lower()

            if pexel_url:
                # Pexels URLs can be passed directly to Sanity
                logger.info(f"Detected Pexel URL, passing directly to Sanity: {image_path}")
                local_image_path = image_path
                temp_file = None
            else:
                # For other URLs, download to a temporary file
                normalized_image_path = image_path.replace('\\\\', '/').strip()
                clean_image_url = normalized_image_path.split('?', 1)[0]
                temp_file = None
                try:
                    response = requests.get(clean_image_url)
                    response.raise_for_status()
                    ext = os.path.splitext(clean_image_url)[-1] or '.jpg'
                    with tempfile.NamedTemporaryFile(delete=False, suffix=ext) as tmp:
                        tmp.write(response.content)
                        local_image_path = tmp.name
                        temp_file = tmp.name
                except Exception as e:
                    logger.error(f"Failed to download image from URL: {clean_image_url}. Error: {e}")
                    return {
                        "status": "error",
                        "post_id": None,
                        "image_id": None,
                        "image_url": None,
                        "image_source": "Download Failed",
                        "image_alt_text": alt_text or f"{title} image",
                        "error": f"Failed to download image from URL: {e}"
                    }
        else:
            # For local file paths
            if image_path:
                normalized_image_path = os.path.normpath(image_path)
            else:
                normalized_image_path = None
            
            local_image_path = normalized_image_path
            temp_file = None
            
            # Check if the file exists at the normalized path
            if local_image_path and not os.path.exists(local_image_path):
                logger.error(f"Image file not found at path: {local_image_path}")
                return {
                    "status": "error",
                    "post_id": None,
                    "image_id": None,
                    "image_url": None,
                    "image_source": "Local Error",
                    "image_alt_text": alt_text or f"{title} image",
                    "error": f"Image file not found at path: {local_image_path}"
                }
            elif local_image_path:
                logger.info(f"Found image file at path: {local_image_path}")

        logger.info(f"Passing local_image_path to SanityAdapter: {local_image_path}")
        logger.info(f"File exists at local_image_path: {os.path.exists(local_image_path) if local_image_path else 'No image path provided'}")
        if local_image_path and os.path.exists(local_image_path):
            logger.info(f"Size of file at local_image_path: {os.path.getsize(local_image_path)} bytes")
        else:
            logger.info("Using direct URL for image upload to Sanity")

        # Convert FAQItem objects or dictionaries to plain dictionaries for SanityAdapter
        faqs_list = []
        if faqs:
            for faq in faqs:
                if hasattr(faq, 'dict'):  # Pydantic model
                    faq_dict = faq.dict()
                    if 'question' in faq_dict and 'answer' in faq_dict:
                        faqs_list.append(faq_dict)
                elif isinstance(faq, dict):  # Regular dictionary
                    if 'question' in faq and 'answer' in faq:
                        faqs_list.append(faq)
                else:
                    logger.warning(f"Skipping invalid FAQ item: {faq}")
        
        # --- Sanity CMS Posting ---
        result = adapter.post_blog(
            title=title,
            summary=summary,
            content=content,
            categories=categories,
            local_image_path=local_image_path,
            slug=slug,
            alt_text=alt_text,
            faqs=faqs_list
        )

        # --- Cleanup ---
        # Clean up temporary files created for downloading images
        if temp_file and os.path.exists(temp_file):
            try:
                os.remove(temp_file)
                logger.info(f"Successfully removed temporary file: {temp_file}")
            except Exception as e:
                logger.warning(f"Failed to remove temporary file {temp_file}: {e}")

        # --- Return Result ---
        if result["status"] == "success":
            # Prefer the source recorded when the image was actually
            # generated/fetched (see _IMAGE_SOURCE_REGISTRY) -- it is the
            # only place that still knows the model id after the image has
            # been reduced to a path. The shape heuristic below only exists
            # as a fallback for images the registry never saw (older runs,
            # or an image that arrived by some other route).
            image_source = lookup_image_source(image_path) if image_path else None
            if not image_source:
                if not image_path:
                    # Spec 5.9 ultimate fallback: featured generation failed
                    # and stock must never substitute for the featured slot.
                    # Publish anyway, flagged, so the sheet records it.
                    image_source = "None (no featured image - flagged)"
                elif image_path.startswith('http'):
                    image_source = "Pexel" if 'pexels' in image_path.lower() else "Downloaded"
                else:
                    image_source = "Local"
                
            return {
                "status": "success",
                "post_id": result["post_id"],
                "post_url": result.get("post_url"),
                "image_id": result.get("image_id"),
                "image_url": result.get("image_url"),
                "image_source": image_source,
                "image_alt_text": alt_text or f"{title} image",
                "notes": "Post created successfully in Sanity CMS."
            }
        else:
            image_source = "None"
            if image_path:
                if image_path.startswith('http'):
                    image_source = "Pexel" if 'pexels' in image_path.lower() else "Download Failed"
                else:
                    image_source = "Local Error"
                    
            return {
                "status": "error",
                "post_id": None,
                "image_id": result.get("image_id"),
                "image_url": result.get("image_url"),
                "image_source": image_source,
                "image_alt_text": alt_text or f"{title} image",
                "error": f"Failed to post to Sanity: {result.get('error', 'Unknown error from adapter')}"
            }

    except Exception as e:
        if 'temp_file' in locals() and temp_file and os.path.exists(temp_file):
            os.remove(temp_file)
        return {
            "status": "error",
            "post_id": None,
            "image_id": None,
            "image_url": None,
            "image_source": "None",
            "image_alt_text": alt_text or f"{title} image",
            "error": f"Unexpected error in post_to_sanity_tool: {str(e)}"
        }

@function_tool
def fetch_internal_links_tool(topic: str, max_results: int = 3, exclude_slug: str = None):
    """
    Fetches related posts from Sanity CMS for a given topic to create internal links.
    Args:
        topic: Topic for the topic cluster (e.g., "What is AI agents").
        max_results: Maximum number of posts to return (default: 3).
        exclude_slug: Slug of the current post to exclude.
    Returns:
        dict: Result containing status, links, and message or error.
    """
    global fetch_internal_links_usage_count
    
    # Increment usage counter
    fetch_internal_links_usage_count += 1
    
    # Check if usage has exceeded the limit
    if fetch_internal_links_usage_count > MAX_INTERNAL_LINKS_CALLS:
        logger.warning(f"fetch_internal_links_tool usage exceeded limit of {MAX_INTERNAL_LINKS_CALLS}. Skipping call.")
        return {
            "status": "warning",
            "links": [],
            "message": f"Tool usage limit of {MAX_INTERNAL_LINKS_CALLS} exceeded. Skipping call.",
            "warning": f"Tool usage limit of {MAX_INTERNAL_LINKS_CALLS} exceeded. Skipping call."
        }
    
    logger.info(f"fetch_internal_links_tool called {fetch_internal_links_usage_count}/{MAX_INTERNAL_LINKS_CALLS} times")
    
    try:
        adapter = SanityAdapter(
            project_id=os.environ['SANITY_PROJECT_ID'],
            # GitHub Actions resolves ${{ secrets.SANITY_DATASET }} to an empty
            # string (not an absent key) when the secret isn't configured, so
            # os.environ.get(key, default) never falls through to 'production'
            # -- the key exists in os.environ, just with an empty value. Use
            # `or` instead so both "unset" and "set but empty" fall back.
            dataset=os.environ.get('SANITY_DATASET') or "production",
            token=os.environ['SANITY_API_TOKEN']
        )
        links = adapter.fetch_internal_links(topic=topic, max_results=max_results, exclude_slug=exclude_slug)
        return {
            "status": "success",
            "links": links,
            "message": f"Fetched {len(links)} internal links for topic '{topic}'."
        }
    except Exception as e:
        logger.error(f"Failed to fetch internal links: {e}")
        return {
            "status": "error",
            "links": [],
            "error": f"Failed to fetch internal links: {str(e)}"
        }


@function_tool
def get_existing_categories_tool() -> dict:
    """Returns the title of every category that already exists in Sanity.
    Call this BEFORE deciding on a post's CATEGORIES, and prefer reusing an
    existing category (matching case-insensitively or by meaning, e.g. an
    existing "AI Agents" should be reused instead of inventing "AI Agent
    Tools" or "AI-Powered Agents") over inventing a new, near-duplicate one.
    Only propose a genuinely new category name if none of the existing ones
    reasonably fit the post's topic -- a consistent, reused category set is
    what makes categories useful as a real taxonomy instead of a different
    ad hoc label on every single post."""
    try:
        adapter = SanityAdapter(
            project_id=os.environ['SANITY_PROJECT_ID'],
            dataset=os.environ.get('SANITY_DATASET') or "production",
            token=os.environ['SANITY_API_TOKEN']
        )
        categories = adapter.list_categories()
        return {
            "status": "success",
            "existing_categories": categories,
            "message": f"Found {len(categories)} existing categories." if categories else "No categories exist yet -- this may be the first post, or category creation hasn't happened yet.",
        }
    except Exception as e:
        logger.error(f"Failed to list existing categories: {e}")
        return {
            "status": "error",
            "existing_categories": [],
            "error": f"Failed to list existing categories: {str(e)}"
        }