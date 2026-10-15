"""
lib/image_vision.py — VLM caption + Jev decision for generated blog thumbnails

Fixes the gap that `image_quality_evaluation_agent` (an LLM agent) can only
ever receive text: it has no image input mechanism, so its scores were
generated from a filename, not from pixels.

Architecture follows the Jev vision-bridge (jev-system-one skill,
references/vision-bridge.md) — Jev state is text-only, so:

    image bytes -> VLM (vision) -> caption/JSON -> Jev Noul state -> typed decision

    Image path  -->  VLM  -->  {description, text_seen, style_notes, issues}
                                          |
                                          v
              slot=featured: matches_blog + matches_style (house style)
              slot=inpost:   matches_blog + clean + theme_fit (body image).
                             The look itself is ALSO a Jev decision: see
                             choose_inpost_style() below, which ranks the
                             candidate art directions before generation.
                                          |
                                          v
                        pass (>= thresholds) / regenerate with feedback

Jev is the decision lane (bounded Noul probabilities), the VLM is the
generation lane (open-ended description). Never send pixels to Jev.

Fail-open, per the skill's Fallback section: a verification gate that is
uncertain assumes pass. Both VLM and Jev outages therefore return
`fallback=True, passed=True` rather than burning the Cloudflare neuron quota
regenerating images we cannot judge. Never blocks the publish path.
"""

import base64
import json
import logging
import os
import time
from typing import Any, Dict, List, Optional

import requests

from lib import image_format
from lib.site_env import SITE_HOST
from lib.jev import JevError, call_jev_sync
from lib.run_result_utils import loads_lenient

logger = logging.getLogger(__name__)

# Primary VLM. Default is the most reliable model in this project's own
# error-rate analysis (2026-10-04, 851 log entries): gemini-flash-latest
# failed 87.95% of the time while gemini-3.5-flash-lite failed 9.34%.
# Each Gemini model also has its OWN independent free daily quota, so the
# fallback list below drains several buckets before giving up.
IMAGE_VLM_MODEL = os.environ.get("IMAGE_VLM_MODEL") or "gemini-3.5-flash-lite"
IMAGE_VLM_FALLBACKS = [
    m.strip()
    for m in (
        os.environ.get("IMAGE_VLM_FALLBACKS")
        or "gemini-3.1-flash-lite,gemini-3.6-flash,gemini-3.5-flash,gemini-flash-latest"
    ).split(",")
    if m.strip()
]
IMAGE_VLM_TIMEOUT = int(os.environ.get("IMAGE_VLM_TIMEOUT") or "60")
IMAGE_VLM_ENDPOINT = os.environ.get("IMAGE_VLM_ENDPOINT") or (
    "https://generativelanguage.googleapis.com/v1beta/openai/chat/completions"
)

# VLM description is kept short: it is Jev state, and shorter state is
# cheaper (patterns.md: state window 32K, but prefer named short fields).
_VLM_MAX_TOKENS = 700
_VLM_MAX_IMAGE_BYTES = 8 * 1024 * 1024


def _image_data_uri(image_path: str) -> Optional[str]:
    """Read a local image as a data URI for the OpenAI-compatible vision call."""
    try:
        with open(image_path, "rb") as fh:
            raw = fh.read()
    except OSError as e:
        logger.warning(f"Cannot read image for VLM: {image_path}: {e}")
        return None
    if not raw:
        logger.warning(f"Empty image file: {image_path}")
        return None
    if len(raw) > _VLM_MAX_IMAGE_BYTES:
        logger.warning(f"Image too large for VLM ({len(raw)} bytes), skipping: {image_path}")
        return None
    mime = image_format.sniff_mime(raw, fallback="image/png")
    return f"data:{mime};base64,{base64.b64encode(raw).decode('ascii')}"


def _vlm_request(model: str, data_uri: str, prompt: str) -> Optional[Dict[str, Any]]:
    """One OpenAI-compatible chat call against Gemini with an image part."""
    api_key = (os.environ.get("GEMINI_API_KEY") or "").strip()
    if not api_key:
        logger.warning("GEMINI_API_KEY not set; cannot run image VLM.")
        return None
    payload = {
        "model": model,
        "messages": [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": prompt},
                    {"type": "image_url", "image_url": {"url": data_uri}},
                ],
            }
        ],
        "temperature": 0.2,
        "max_tokens": _VLM_MAX_TOKENS,
    }
    try:
        started = time.perf_counter()
        resp = requests.post(
            IMAGE_VLM_ENDPOINT,
            json=payload,
            headers={"Authorization": f"Bearer {api_key}"},
            timeout=IMAGE_VLM_TIMEOUT,
        )
        latency_ms = (time.perf_counter() - started) * 1000
        if resp.status_code != 200:
            logger.warning(f"VLM {model} HTTP {resp.status_code}: {resp.text[:300]}")
            return None
        body = resp.json()
        content = body["choices"][0]["message"]["content"]
        usage = body.get("usage") or {}
        logger.info(
            f"VLM {model} ok latency={latency_ms:.0f}ms "
            f"in={usage.get('prompt_tokens')} out={usage.get('completion_tokens')}"
        )
        if isinstance(content, list):
            content = "".join(
                part.get("text", "") if isinstance(part, dict) else str(part) for part in content
            )
        return {"text": str(content), "model": model, "latency_ms": round(latency_ms, 1)}
    except requests.Timeout:
        logger.warning(f"VLM {model} timed out after {IMAGE_VLM_TIMEOUT}s")
    except Exception as e:
        logger.warning(f"VLM {model} failed: {e}")
    return None


_VLM_PROMPT_TEMPLATE = """You are QA for an image on a blog. Look at this image and report what is ACTUALLY visible.

Image role: {role}
Title (article or section): {title}
Summary/context: {summary}

Return ONLY a JSON object, no prose, no markdown fence:
{{
  "description": "3-5 sentences describing the actual scene: subjects, composition, setting, mood.",
  "topic_connection": "1-2 sentences: how this image connects to the title above, or 'no clear connection' if it does not.",
  "text_seen": "Every legible on-image word exactly as spelled, or 'none'.",
  "style_notes": "1-2 sentences on art style and palette: 3D render / photo / flat vector / watercolor / line art, and the dominant colors.",
  "issues": ["specific problems: {issue_examples}"]
}}

Rules: describe only what you can see. If nothing is legible, text_seen is 'none'. Never invent detail."""

_VLM_ROLE_FEATURED = (
    "the article's hero thumbnail (featured image; judged against the site's "
    "house cinematic style)"
)
_VLM_ROLE_INPOST = (
    "an in-article body image that illustrates one section (NOT the hero "
    "thumbnail; any clean art style is acceptable)"
)
_VLM_ISSUES_FEATURED = (
    "misspelled or garbled text, distorted faces/hands, clutter, watermark, "
    "off-topic subject, flat stock-photo look, oversaturated neon, not 16:9"
)
_VLM_ISSUES_INPOST = (
    "any legible text (body images must be text-free), garbled word-like "
    "shapes, distorted faces/hands, clutter, watermark, off-topic subject, "
    "unreadable composition"
)


def describe_image_vlm(
    image_path: str, article_title: str, article_summary: str, slot: str = "featured"
) -> Dict[str, Any]:
    """Caption a local image with a vision model. Returns a dict with
    description/topic_connection/text_seen/style_notes/issues, plus
    `model`, `fallback` and optionally `error`. Never raises.

    `slot` picks the QA framing: "featured" (hero thumbnail; house style is
    judged) or "inpost" (body image; any clean style passes, text does not)."""
    data_uri = _image_data_uri(image_path)
    if not data_uri:
        return {"error": "unreadable_image", "fallback": True, "issues": []}

    prompt = _VLM_PROMPT_TEMPLATE.format(
        role=_VLM_ROLE_INPOST if slot == "inpost" else _VLM_ROLE_FEATURED,
        issue_examples=_VLM_ISSUES_INPOST if slot == "inpost" else _VLM_ISSUES_FEATURED,
        title=(article_title or "").strip() or "(untitled)",
        summary=(article_summary or "").strip() or "(no summary)",
    )

    tried: List[str] = []
    candidates = [IMAGE_VLM_MODEL] + [m for m in IMAGE_VLM_FALLBACKS if m != IMAGE_VLM_MODEL]
    for model in candidates:
        tried.append(model)
        out = _vlm_request(model, data_uri, prompt)
        if not out:
            continue
        parsed = loads_lenient(out["text"])
        if not isinstance(parsed, dict):
            logger.warning(f"VLM {model} returned non-JSON, raw: {out['text'][:300]}")
            continue
        issues = parsed.get("issues")
        if isinstance(issues, str):
            issues = [issues] if issues.strip() else []
        if not isinstance(issues, list):
            issues = []
        return {
            "description": str(parsed.get("description") or "").strip(),
            "topic_connection": str(parsed.get("topic_connection") or "").strip(),
            "text_seen": str(parsed.get("text_seen") or "none").strip(),
            "style_notes": str(parsed.get("style_notes") or "").strip(),
            "issues": [str(i) for i in issues][:8],
            "model": model,
            "fallback": False,
        }

    logger.warning(f"All VLM models failed after trying {tried}")
    return {"error": "vlm_unavailable", "fallback": True, "tried": tried, "issues": []}


# ---------------------------------------------------------------------------
# Jev decision lane — bounded, typed, cheap. Never receives pixels.
# ---------------------------------------------------------------------------
IMAGE_MATCH_THRESHOLD = float(os.environ.get("IMAGE_MATCH_THRESHOLD") or "0.65")
IMAGE_STYLE_THRESHOLD = float(os.environ.get("IMAGE_STYLE_THRESHOLD") or "0.6")
# In-post lane 2: how clean/text-free the body image is. Baked-in text and
# garbled artifacts are disqualifying whoever painted them.
IMAGE_CLEAN_THRESHOLD = float(os.environ.get("IMAGE_CLEAN_THRESHOLD") or "0.6")
# In-post lane 3: how well the actual pixels sit in the site's visual world
# (deep navy + cyan/violet/amber, premium tech) -- judged loosely so any
# clean medium can pass, tight enough to bounce clip-art / generic looks.
# This lane judges the EXECUTION of whichever style was attempted; WHICH
# style to attempt is Jev's choose_inpost_style() ranking below.
IMAGE_THEME_THRESHOLD = float(os.environ.get("IMAGE_THEME_THRESHOLD") or "0.55")

_JEV_STYLE_INSTRUCTIONS = (
    "Does `image.style_notes` + `image.description` match the owaisabdullah.dev house "
    "style: cinematic 3D concept-art quality, a deep-navy/midnight/charcoal foundation "
    "with electric blue or cyan light plus violet, magenta or amber accents, one clear "
    "focal point, and minimal on-image text? Penalize flat stock photography, watercolor, "
    "hand-drawn sketch, flat corporate vector illustration, cluttered floating dashboards, "
    "oversaturated neon everywhere, watermarks, and misspelled or garbled text."
).replace("owaisabdullah.dev", SITE_HOST)

_JEV_TOPIC_INSTRUCTIONS = (
    "Does the image clearly represent the article's topic? A viewer should connect the "
    "scene to `article.title` without reading any caption. Off-topic, generic, or purely "
    "decorative imagery scores low. Judge from `image.description` and "
    "`image.topic_connection`, not from the title alone."
)

_JEV_CLEAN_INSTRUCTIONS = (
    "Is the image clean and safe to publish as a body image inside the article? "
    "Penalize: any legible baked-in text (words, letters, numbers, UI copy, "
    "watermarks, word-shaped logos) -- body images must be text-free; garbled or "
    "misspelled word-like shapes; distorted faces or hands; obvious rendering "
    "glitches; cluttered, unreadable compositions. Do NOT penalize the art style "
    "itself: a clean photo, 3D render, vector, isometric or macro look are all "
    "acceptable for body images."
)

_JEV_INPOST_THEME_INSTRUCTIONS = (
    "Does this image belong on the site -- a premium technical blog whose visual "
    "world is cinematic tech storytelling: deep navy, electric blue/cyan, and "
    "violet, magenta or amber accents? Judge theme fit, not novelty: a clean "
    "photo, 3D render, isometric diorama, blueprint or macro look can all belong "
    "when the palette, polish and mood read as part of that world. Penalize looks "
    "that clash with it: clip-art vibes, unrelated pastels, oversaturated neon, "
    "generic corporate imagery, cheap template looks. Body images must NOT copy "
    "the hero thumbnail, so do not reward sameness with the featured style."
)

# Style-pick lane: one Noul per candidate direction, ranked by Jev instead of
# a blind hash rotation. The section text is the state; each question carries
# one candidate's art direction.
_JEV_STYLE_PICK_INSTRUCTIONS = (
    "Would this art direction be a strong choice for an in-article illustration "
    "of the section below, on a premium technical blog? Art direction: {style}. "
    "The site's visual world is cinematic tech storytelling: deep navy, electric "
    "blue/cyan, with violet, magenta or amber accents and a premium finish. "
    "Score high when the direction would carry this section's idea vividly and "
    "feel native to that world; score low when it would clash with the theme, "
    "look generic or cheap, or struggle to carry the idea. Judge the direction "
    "itself, not the section's topic."
)


def judge_image_fit(
    article_title: str,
    article_summary: str,
    image_report: Dict[str, Any],
    slot: str = "featured",
) -> Dict[str, Any]:
    """Jev Noul batched gate, one call. slot="featured": matches_blog +
    matches_style (house thumbnail). slot="inpost": matches_blog + clean
    (text-free, uncluttered) + theme_fit (belongs to the site's visual
    world). Which in-post style gets ATTEMPTED is picked by
    choose_inpost_style() below; this gate judges the pixels that came back.

    Fail-open: JevError/timeout returns fallback=True with passed=True so a
    Jev outage never costs image generations. Never raises.
    """
    state = {
        "article": {
            "title": (article_title or "").strip(),
            "summary": (article_summary or "").strip(),
        },
        "image": {
            "description": (image_report.get("description") or "")[:2000],
            "topic_connection": (image_report.get("topic_connection") or "")[:600],
            "text_seen": (image_report.get("text_seen") or "none")[:200],
            "style_notes": (image_report.get("style_notes") or "")[:600],
        },
    }

    def _fallback(error: str) -> Dict[str, Any]:
        out: Dict[str, Any] = {
            "matches_blog": 1.0,
            "passed": True,
            "fallback": True,
            "slot": slot,
            "error": error,
        }
        if slot == "inpost":
            out["clean"] = 1.0
            out["theme_fit"] = 1.0
        else:
            out["matches_style"] = 1.0
        return out

    if slot == "inpost":
        questions = {
            "matches_blog": {"type": "noul", "instructions": _JEV_TOPIC_INSTRUCTIONS},
            "clean": {"type": "noul", "instructions": _JEV_CLEAN_INSTRUCTIONS},
            "theme_fit": {"type": "noul", "instructions": _JEV_INPOST_THEME_INSTRUCTIONS},
        }
    else:
        questions = {
            "matches_blog": {"type": "noul", "instructions": _JEV_TOPIC_INSTRUCTIONS},
            "matches_style": {"type": "noul", "instructions": _JEV_STYLE_INSTRUCTIONS},
        }
    try:
        resp = call_jev_sync(state, questions)
    except JevError as e:
        logger.warning(f"judge_image_fit Jev fallback (assume pass): {e}")
        return _fallback(str(e))
    except Exception as e:
        logger.warning(f"judge_image_fit unexpected fallback (assume pass): {e}")
        return _fallback(str(e))

    def _noul(key: str, default: float = 0.0) -> float:
        ans = resp.answers.get(key)
        if ans is None:
            return default
        if isinstance(ans, dict):
            val = ans.get("noul")
        else:
            val = getattr(ans, "noul", None)
        try:
            return float(val) if val is not None else default
        except (TypeError, ValueError):
            return default

    matches_blog = _noul("matches_blog")
    if slot == "inpost":
        clean = _noul("clean")
        theme_fit = _noul("theme_fit")
        passed = (
            matches_blog >= IMAGE_MATCH_THRESHOLD
            and clean >= IMAGE_CLEAN_THRESHOLD
            and theme_fit >= IMAGE_THEME_THRESHOLD
        )
        return {
            "matches_blog": round(matches_blog, 4),
            "clean": round(clean, 4),
            "theme_fit": round(theme_fit, 4),
            "threshold_blog": IMAGE_MATCH_THRESHOLD,
            "threshold_clean": IMAGE_CLEAN_THRESHOLD,
            "threshold_theme": IMAGE_THEME_THRESHOLD,
            "passed": bool(passed),
            "fallback": False,
            "slot": slot,
            "usage": resp.usage.model_dump(),
            "model": resp.model,
        }
    matches_style = _noul("matches_style")
    passed = matches_blog >= IMAGE_MATCH_THRESHOLD and matches_style >= IMAGE_STYLE_THRESHOLD
    return {
        "matches_blog": round(matches_blog, 4),
        "matches_style": round(matches_style, 4),
        "threshold_blog": IMAGE_MATCH_THRESHOLD,
        "threshold_style": IMAGE_STYLE_THRESHOLD,
        "passed": bool(passed),
        "fallback": False,
        "slot": slot,
        "usage": resp.usage.model_dump(),
        "model": resp.model,
    }


def choose_inpost_style(
    article_title: str,
    article_summary: str,
    candidates: List[tuple],
) -> Dict[str, Any]:
    """Jev style pick for an in-post image: one Noul per candidate art
    direction, ranked best-first. The look is chosen by the same decision
    stack that judges the finished pixels -- not a blind rotation.

    `candidates` is [(name, style_direction), ...] (the
    tools._INPOST_STYLE_PICKS shape). Returns {order: [names best-first],
    scores: {name: noul}, fallback: bool} plus model/usage when judged.

    Fail-open: Jev down -> fallback=True with an empty order; the caller
    falls back to its deterministic hash pick. Never raises.
    """
    if not candidates:
        return {"order": [], "scores": {}, "fallback": True, "error": "no_candidates"}
    state = {
        "section": {
            "title": (article_title or "").strip(),
            "summary": (article_summary or "").strip(),
        },
    }
    index_to_name = {}
    questions = {}
    for idx, (name, direction) in enumerate(candidates):
        key = f"style_{idx}"
        index_to_name[key] = name
        questions[key] = {
            "type": "noul",
            "instructions": _JEV_STYLE_PICK_INSTRUCTIONS.format(style=direction),
        }
    try:
        resp = call_jev_sync(state, questions)
    except JevError as e:
        logger.warning(f"choose_inpost_style Jev fallback: {e}")
        return {"order": [], "scores": {}, "fallback": True, "error": str(e)}
    except Exception as e:
        logger.warning(f"choose_inpost_style unexpected fallback: {e}")
        return {"order": [], "scores": {}, "fallback": True, "error": str(e)}

    answers = getattr(resp, "answers", None) or {}
    scores: Dict[str, float] = {}
    for key, name in index_to_name.items():
        ans = answers.get(key)
        if isinstance(ans, dict):
            val = ans.get("noul")
        else:
            val = getattr(ans, "noul", None) if ans is not None else None
        try:
            scores[name] = round(float(val), 4) if val is not None else 0.0
        except (TypeError, ValueError):
            scores[name] = 0.0
    if not any(scores.values()):
        return {"order": [], "scores": scores, "fallback": True, "error": "no_nouls"}

    out: Dict[str, Any] = {
        "order": sorted(scores, key=lambda n: scores[n], reverse=True),
        "scores": scores,
        "fallback": False,
        "model": getattr(resp, "model", None),
    }
    usage = getattr(resp, "usage", None)
    if usage is not None:
        try:
            out["usage"] = usage.model_dump()
        except Exception:  # noqa: BLE001 -- telemetry only, never block the pick
            pass
    return out


def validate_thumbnail(
    image_path: str, article_title: str, article_summary: str, slot: str = "featured"
) -> Dict[str, Any]:
    """Full check: VLM describes the pixels, Jev decides if it fits.

    `slot` picks the extra Jev lanes: "featured" -> matches_style (house
    thumbnail style); "inpost" -> clean (text-free, uncluttered) + theme_fit
    (belongs to the site's visual world -- any clean medium may pass, a
    clip-art/generic look fails). Which in-post look was ATTEMPTED is Jev's
    choose_inpost_style() pick; this gate judges the pixels that came back.
    Name kept for compatibility -- despite the name it validates both slots.

    Returns {passed, matches_blog, matches_style|clean+theme_fit, vlm,
    issues, fallback}. Fail-open on any infrastructure problem (never
    blocks publish). Never raises.
    """
    started = time.perf_counter()
    try:
        report = describe_image_vlm(image_path, article_title, article_summary, slot=slot)
        if report.get("fallback"):
            # No vision -> we cannot judge -> do not spend neurons retrying.
            return {
                "passed": True,
                "matches_blog": None,
                "matches_style": None,
                "clean": None,
                "theme_fit": None,
                "slot": slot,
                "vlm": report,
                "issues": [],
                "fallback": True,
                "reason": "vlm_unavailable",
            }

        verdict = judge_image_fit(article_title, article_summary, report, slot=slot)
        return {
            "passed": bool(verdict["passed"]),
            "matches_blog": verdict.get("matches_blog"),
            "matches_style": verdict.get("matches_style"),
            "clean": verdict.get("clean"),
            "theme_fit": verdict.get("theme_fit"),
            "threshold_blog": verdict.get("threshold_blog"),
            "threshold_style": verdict.get("threshold_style"),
            "threshold_clean": verdict.get("threshold_clean"),
            "threshold_theme": verdict.get("threshold_theme"),
            "slot": slot,
            "vlm": {k: v for k, v in report.items() if k != "error"},
            "issues": report.get("issues") or [],
            "text_seen": report.get("text_seen"),
            "fallback": bool(verdict.get("fallback")),
            "usage": verdict.get("usage"),
            "latency_ms": round((time.perf_counter() - started) * 1000, 1),
        }
    except Exception as e:
        logger.warning(f"validate_thumbnail unexpected fallback (assume pass): {e}")
        return {
            "passed": True,
            "matches_blog": None,
            "matches_style": None,
            "clean": None,
            "theme_fit": None,
            "slot": slot,
            "issues": [],
            "fallback": True,
            "error": str(e),
        }


def revision_guidance(verdict: Dict[str, Any], slot: str = "featured") -> str:
    """Build the 'do not repeat these problems' block for the next attempt.

    Slot-aware: featured problems push back toward the house style; in-post
    problems push toward text-free cleanliness and back into the site's
    visual world -- body images may use any clean, theme-fitting medium and
    must never be told to return to the house thumbnail look."""
    parts: List[str] = []
    issues = [i for i in (verdict.get("issues") or []) if isinstance(i, str) and i.strip()]
    if issues:
        parts.append("- Fix these specific problems from the previous image:\n"
                     + "\n".join(f"  * {i}" for i in issues[:6]))
    blog = verdict.get("matches_blog")
    style = verdict.get("matches_style")
    if blog is not None and float(blog) < IMAGE_MATCH_THRESHOLD:
        conn = (verdict.get("vlm") or {}).get("topic_connection") or ""
        parts.append(
            "- The scene does not read as the article topic"
            + (f' (previous assessment: "{conn[:200]}")' if conn else "")
            + ". Make the connection to the topic unmistakable and central."
        )
    if style is not None and float(style) < IMAGE_STYLE_THRESHOLD:
        notes = (verdict.get("vlm") or {}).get("style_notes") or ""
        parts.append(
            "- The style is off-brand"
            + (f' (previous: "{notes[:200]}")' if notes else "")
            + ". Return to cinematic 3D concept art with a deep-navy foundation, "
            "electric blue/cyan light and violet, magenta or amber accents; one clear "
            "focal point; no flat stock-photo or watercolor look."
        )
    clean = verdict.get("clean")
    if clean is not None and float(clean) < IMAGE_CLEAN_THRESHOLD:
        notes = (verdict.get("vlm") or {}).get("style_notes") or ""
        parts.append(
            "- The previous image was not clean enough for an article body"
            + (f' (previous: "{notes[:200]}")' if notes else "")
            + ". Keep it text-free, uncluttered, one clear subject, no distorted "
            "shapes or glitches."
        )
    theme = verdict.get("theme_fit")
    if theme is not None and float(theme) < IMAGE_THEME_THRESHOLD:
        notes = (verdict.get("vlm") or {}).get("style_notes") or ""
        parts.append(
            "- The look drifted away from the site's visual world"
            + (f' (previous: "{notes[:200]}")' if notes else "")
            + ". Follow the art-direction block above exactly: deep navy with "
            "electric blue/cyan and violet, magenta or amber accents, premium "
            "cinematic finish; no clip-art or generic corporate look."
        )
    text_seen = (verdict.get("text_seen") or "").strip().lower()
    if text_seen and text_seen not in ("none", "no", "n/a", "none."):
        if slot == "inpost":
            parts.append(
                f"- Previous on-image text read as \"{verdict.get('text_seen')}\". "
                "Body images must contain NO text at all -- remove every word, "
                "letter, number and watermark."
            )
        else:
            parts.append(
                f"- Previous on-image text read as \"{verdict.get('text_seen')}\". "
                "Either render no text at all, or render exactly the words given, spelled correctly."
            )
    if not parts:
        parts.append("- Improve overall composition, focal clarity and palette contrast.")
    return "\n".join(parts)


# ---------------------------------------------------------------------------
# Stock-first in-post relevancy gate (spec 5.9)
#
# For each in-post slot: Pexels candidate -> VLM describes the pixels
# against the SECTION topic -> ONE Jev Noul on topic relevancy -> score
# 0-100. >= 90 keeps the free stock image; below 90 the caller generates
# with Klein 4B instead.
#
# Deliberately NOT judge_image_fit: that gate has a style lane which
# explicitly penalizes flat stock photography (house-style rule), which
# would fail every stock image for being stock. Stock is judged on topic
# relevancy alone; house style only applies to generated images (the
# thumbnail lane above).
# ---------------------------------------------------------------------------
IMAGE_STOCK_RELEVANCY_THRESHOLD = float(
    os.environ.get("IMAGE_STOCK_RELEVANCY_THRESHOLD") or "0.90"
)

_STOCK_TOPIC_INSTRUCTIONS = (
    "Does the image clearly illustrate the given section topic? Judge ONLY "
    "topic relevancy: art style, production quality, and whether the image "
    "looks like stock photography are IRRELEVANT for this question. An image "
    "whose subject directly depicts the topic scores high; generic-but-"
    "adjacent imagery scores mid; off-topic or decorative imagery scores low. "
    "Judge from `image.description` and `image.topic_connection`, not from "
    "the topic text alone."
)


def score_topic_relevancy(
    image_path: str, topic: str, context: str = ""
) -> Dict[str, Any]:
    """VLM + Jev topic-relevancy score (0-100) for one candidate image
    against a section topic.

    Returns {score, noul, threshold, passed, fallback, usage, vlm_model,
    latency_ms, issues, topic_connection}. Fail-open like every other gate in
    this module: a VLM or Jev outage returns score=100/fallback=True/passed=True
    so an infrastructure blip never costs image generations or blocks a post.
    Never raises.
    """
    started = time.perf_counter()
    try:
        report = describe_image_vlm(image_path, topic or "", context or "")
        if report.get("fallback"):
            return {
                "score": 100,
                "noul": None,
                "threshold": IMAGE_STOCK_RELEVANCY_THRESHOLD,
                "passed": True,
                "fallback": True,
                "reason": "vlm_unavailable",
                "latency_ms": round((time.perf_counter() - started) * 1000, 1),
                "issues": [],
            }

        state = {
            "section": {
                "topic": (topic or "").strip(),
                "summary": (context or "").strip()[:600],
            },
            "image": {
                "description": (report.get("description") or "")[:2000],
                "topic_connection": (report.get("topic_connection") or "")[:600],
            },
        }
        questions = {
            "matches_topic": {"type": "noul", "instructions": _STOCK_TOPIC_INSTRUCTIONS},
        }
        try:
            resp = call_jev_sync(state, questions)
        except Exception as e:
            logger.warning(f"score_topic_relevancy Jev fallback (accept stock): {e}")
            return {
                "score": 100,
                "noul": None,
                "threshold": IMAGE_STOCK_RELEVANCY_THRESHOLD,
                "passed": True,
                "fallback": True,
                "error": str(e),
                "latency_ms": round((time.perf_counter() - started) * 1000, 1),
                "issues": report.get("issues") or [],
            }

        ans = resp.answers.get("matches_topic")
        if isinstance(ans, dict):
            noul = ans.get("noul")
        else:
            noul = getattr(ans, "noul", None)
        try:
            noul_f = float(noul) if noul is not None else 0.0
        except (TypeError, ValueError):
            noul_f = 0.0
        score = int(round(noul_f * 100))
        return {
            "score": score,
            "noul": round(noul_f, 4),
            "threshold": IMAGE_STOCK_RELEVANCY_THRESHOLD,
            "passed": bool(noul_f >= IMAGE_STOCK_RELEVANCY_THRESHOLD),
            "fallback": False,
            "usage": resp.usage.model_dump() if hasattr(resp.usage, "model_dump") else None,
            "model": resp.model,
            "vlm_model": report.get("model"),
            "issues": report.get("issues") or [],
            "topic_connection": report.get("topic_connection") or "",
            "latency_ms": round((time.perf_counter() - started) * 1000, 1),
        }
    except Exception as e:
        logger.warning(f"score_topic_relevancy unexpected fallback (accept stock): {e}")
        return {
            "score": 100,
            "noul": None,
            "threshold": IMAGE_STOCK_RELEVANCY_THRESHOLD,
            "passed": True,
            "fallback": True,
            "error": str(e),
            "issues": [],
        }
