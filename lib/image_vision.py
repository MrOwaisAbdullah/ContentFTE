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
                              Jev Noul matches_blog + matches_style
                                          |
                                          v
                        pass (>= thresholds) / regenerate with feedback

Jev is the decision lane (bounded: two Noul probabilities), the VLM is the
generation lane (open-ended description). Never send pixels to Jev.

Fail-open, per the skill's Fallback section: a verification gate that is
uncertain assumes pass. Both VLM and Jev outages therefore return
`fallback=True, passed=True` rather than burning the Cloudflare neuron quota
regenerating images we cannot judge. Never blocks the publish path.
"""

import base64
import json
import logging
import mimetypes
import os
import time
from typing import Any, Dict, List, Optional

import requests

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
    mime = mimetypes.guess_type(image_path)[0] or "image/png"
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


_VLM_PROMPT_TEMPLATE = """You are QA for a blog's hero thumbnail. Look at this image and report what is ACTUALLY visible.

Article title: {title}
Article summary: {summary}

Return ONLY a JSON object, no prose, no markdown fence:
{{
  "description": "3-5 sentences describing the actual scene: subjects, composition, setting, mood.",
  "topic_connection": "1-2 sentences: how this image connects to the article topic, or 'no clear connection' if it does not.",
  "text_seen": "Every legible on-image word exactly as spelled, or 'none'.",
  "style_notes": "1-2 sentences on art style and palette: 3D render / photo / flat vector / watercolor / line art, and the dominant colors.",
  "issues": ["specific problems: misspelled or garbled text, distorted faces/hands, clutter, watermark, off-topic subject, flat stock-photo look, oversaturated neon, not 16:9"]
}}

Rules: describe only what you can see. If nothing is legible, text_seen is 'none'. Never invent detail."""


def describe_image_vlm(
    image_path: str, article_title: str, article_summary: str
) -> Dict[str, Any]:
    """Caption a local image with a vision model. Returns a dict with
    description/topic_connection/text_seen/style_notes/issues, plus
    `model`, `fallback` and optionally `error`. Never raises."""
    data_uri = _image_data_uri(image_path)
    if not data_uri:
        return {"error": "unreadable_image", "fallback": True, "issues": []}

    prompt = _VLM_PROMPT_TEMPLATE.format(
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

_JEV_STYLE_INSTRUCTIONS = (
    "Does `image.style_notes` + `image.description` match the owaisabdullah.dev house "
    "style: cinematic 3D concept-art quality, a deep-navy/midnight/charcoal foundation "
    "with electric blue or cyan light plus violet, magenta or amber accents, one clear "
    "focal point, and minimal on-image text? Penalize flat stock photography, watercolor, "
    "hand-drawn sketch, flat corporate vector illustration, cluttered floating dashboards, "
    "oversaturated neon everywhere, watermarks, and misspelled or garbled text."
)

_JEV_TOPIC_INSTRUCTIONS = (
    "Does the image clearly represent the article's topic? A viewer should connect the "
    "scene to `article.title` without reading any caption. Off-topic, generic, or purely "
    "decorative imagery scores low. Judge from `image.description` and "
    "`image.topic_connection`, not from the title alone."
)


def judge_image_fit(
    article_title: str,
    article_summary: str,
    image_report: Dict[str, Any],
) -> Dict[str, Any]:
    """Jev Noul batched gate: matches_blog + matches_style in one call.

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
    questions = {
        "matches_blog": {"type": "noul", "instructions": _JEV_TOPIC_INSTRUCTIONS},
        "matches_style": {"type": "noul", "instructions": _JEV_STYLE_INSTRUCTIONS},
    }
    try:
        resp = call_jev_sync(state, questions)
    except JevError as e:
        logger.warning(f"judge_image_fit Jev fallback (assume pass): {e}")
        return {
            "matches_blog": 1.0,
            "matches_style": 1.0,
            "passed": True,
            "fallback": True,
            "error": str(e),
        }
    except Exception as e:
        logger.warning(f"judge_image_fit unexpected fallback (assume pass): {e}")
        return {
            "matches_blog": 1.0,
            "matches_style": 1.0,
            "passed": True,
            "fallback": True,
            "error": str(e),
        }

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
    matches_style = _noul("matches_style")
    passed = matches_blog >= IMAGE_MATCH_THRESHOLD and matches_style >= IMAGE_STYLE_THRESHOLD
    return {
        "matches_blog": round(matches_blog, 4),
        "matches_style": round(matches_style, 4),
        "threshold_blog": IMAGE_MATCH_THRESHOLD,
        "threshold_style": IMAGE_STYLE_THRESHOLD,
        "passed": bool(passed),
        "fallback": False,
        "usage": resp.usage.model_dump(),
        "model": resp.model,
    }


def validate_thumbnail(
    image_path: str, article_title: str, article_summary: str
) -> Dict[str, Any]:
    """Full check: VLM describes the pixels, Jev decides if it fits.

    Returns {passed, matches_blog, matches_style, vlm, issues, fallback}.
    Fail-open on any infrastructure problem (never blocks publish).
    Never raises.
    """
    started = time.perf_counter()
    try:
        report = describe_image_vlm(image_path, article_title, article_summary)
        if report.get("fallback"):
            # No vision -> we cannot judge -> do not spend neurons retrying.
            return {
                "passed": True,
                "matches_blog": None,
                "matches_style": None,
                "vlm": report,
                "issues": [],
                "fallback": True,
                "reason": "vlm_unavailable",
            }

        verdict = judge_image_fit(article_title, article_summary, report)
        return {
            "passed": bool(verdict["passed"]),
            "matches_blog": verdict.get("matches_blog"),
            "matches_style": verdict.get("matches_style"),
            "threshold_blog": verdict.get("threshold_blog"),
            "threshold_style": verdict.get("threshold_style"),
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
            "issues": [],
            "fallback": True,
            "error": str(e),
        }


def revision_guidance(verdict: Dict[str, Any]) -> str:
    """Build the 'do not repeat these problems' block for the next attempt."""
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
    text_seen = (verdict.get("text_seen") or "").strip().lower()
    if text_seen and text_seen not in ("none", "no", "n/a", "none."):
        parts.append(
            f"- Previous on-image text read as \"{verdict.get('text_seen')}\". "
            "Either render no text at all, or render exactly the words given, spelled correctly."
        )
    if not parts:
        parts.append("- Improve overall composition, focal clarity and palette contrast.")
    return "\n".join(parts)
