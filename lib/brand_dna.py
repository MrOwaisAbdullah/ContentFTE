"""§5.1 Brand DNA — per-site voice profiles, versioned in Postgres.

Implementation rule (Agrici pattern): the profile is auto-loaded at the
SYSTEM-PROMPT level for brief/draft/eval/image-prompt agents — never
passed as an optional parameter that can be forgotten.

This module is storage + injection + distillation: `distill_profile`
turns 3-5 sample texts (spec §5.1) into the structured profile via the
writer model (OpenRouter/DeepSeek by default, injectable `llm_fn` for
tests), `save_profile` versions it, `inject_into_system_prompt`/
`apply_brand_dna` auto-load it. The CLI lives in
`scripts/build_brand_dna.py`.
"""
from __future__ import annotations

import json
import os
import re
import urllib.request

from sqlalchemy import select
from sqlalchemy.orm import Session

from lib.db import BrandProfile
from lib.run_result_utils import loads_lenient

DEFAULT_PROFILE = {
    "tone_sliders": {"formal_casual": 0.5, "terse_expansive": 0.5},
    "reading_level": "grade-8",
    "signature_phrases": [],
    "banned_phrases": [],
    "pov": "second",
    "style_preset": "photoreal",
}

# Writer model for distillation (spec §5.1 "DeepSeek distills"): the
# repo's OpenRouter-paid DeepSeek id (blog_agent/custom_runner LLM_MODELS),
# overridable per site/operator.
DISTILL_ENDPOINT = "https://openrouter.ai/api/v1/chat/completions"
DISTILL_MODEL = (os.environ.get("BRAND_DNA_MODEL") or "").strip() \
    or "deepseek/deepseek-v4-flash-0731"
# Each sample is truncated — voice distillation needs style, not full length.
_SAMPLE_MAX_CHARS = 6000
_FENCE_RE = re.compile(r"```(?:json)?\s*(\{.*\})\s*```", re.DOTALL)

DISTILL_SYSTEM = (
    "You are a brand-voice analyst. You read sample texts from ONE brand "
    "and distill a precise, reusable voice profile. Output ONLY one JSON "
    "object, no prose, no markdown outside a ```json fence, with exactly "
    "these keys:\n"
    '  "tone_sliders": {"formal_casual": <0..1, 0=formal 1=casual>, '
    '"terse_expansive": <0..1, 0=terse 1=expansive>},\n'
    '  "reading_level": <e.g. "grade-8" — grade number of the dominant '
    "reading level>,\n"
    '  "signature_phrases": [<2-6 short phrases this brand actually uses '
    "repeatedly — quote them verbatim from the samples>],\n"
    '  "banned_phrases": [<clichés, hype words, or topics the samples '
    "conspicuously avoid — infer conservatively>],\n"
    '  "pov": <"first" | "second" | "third" — the dominant narrative '
    'point of view>,\n'
    '  "style_preset": <one word or two for image/visual tone, e.g. '
    '"photoreal" | "flat" | "editorial">\n'
    "Be conservative: only assert what the samples support. Never invent "
    "signature phrases that do not appear in the samples."
)


def _default_llm(prompt: str, *, model: str | None = None) -> str:
    """One chat-completion call to the writer model (OpenRouter)."""
    key = (os.environ.get("OPENROUTER_API_KEY") or "").strip()
    if not key:
        raise ValueError(
            "OPENROUTER_API_KEY is not set — distillation needs a writer "
            "model (set it, or pass llm_fn=... to distill_profile)")
    body = json.dumps({
        "model": (model or DISTILL_MODEL),
        "messages": [{"role": "system", "content": DISTILL_SYSTEM},
                     {"role": "user", "content": prompt}],
        "temperature": 0.2,
        "max_tokens": 1500,
    }).encode("utf-8")
    req = urllib.request.Request(
        DISTILL_ENDPOINT, data=body, method="POST",
        headers={"Content-Type": "application/json; charset=utf-8",
                 "Authorization": f"Bearer {key}",
                 "HTTP-Referer": os.environ.get("OPENROUTER_SITE_URL",
                                                "https://owaisabdullah.dev"),
                 "X-Title": os.environ.get("OPENROUTER_APP_TITLE",
                                           "ContentFTE")})
    with urllib.request.urlopen(req, timeout=90) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    try:
        return str(data["choices"][0]["message"]["content"])
    except (KeyError, IndexError, TypeError) as exc:
        raise ValueError(f"unexpected model response shape: {exc}") from exc


def _extract_json(text: str) -> dict:
    """Fenced-or-raw JSON object out of model text; raises ValueError."""
    match = _FENCE_RE.search(text or "")
    payload = match.group(1) if match else (text or "")
    parsed = loads_lenient(payload)
    if not isinstance(parsed, dict):
        raise ValueError("distillation model did not return a JSON object")
    return parsed


def _clamp(value, default: float = 0.5) -> float:
    try:
        num = float(value)
    except (TypeError, ValueError):
        return default
    return max(0.0, min(1.0, num))


def _phrase_list(value) -> list[str]:
    """Model junk → clean list[str]: strings only, trimmed, de-duped,
    order-preserving (a lone string becomes a 1-item list)."""
    if isinstance(value, str):
        value = [value]
    if not isinstance(value, list):
        return []
    out: list[str] = []
    for item in value:
        text = str(item).strip()
        if text and text not in out:
            out.append(text)
    return out


def normalize_profile(raw: dict) -> dict:
    """Coerce a model's distillation output onto DEFAULT_PROFILE: clamp
    sliders to 0..1, restrict pov, keep phrase lists as clean str lists.
    Never raises — junk fields fall back to their defaults."""
    raw = raw if isinstance(raw, dict) else {}
    sliders = raw.get("tone_sliders")
    sliders = sliders if isinstance(sliders, dict) else {}
    pov = str(raw.get("pov") or "").strip().lower()
    if pov not in ("first", "second", "third"):
        pov = DEFAULT_PROFILE["pov"]
    reading = str(raw.get("reading_level") or "").strip() \
        or DEFAULT_PROFILE["reading_level"]
    style = str(raw.get("style_preset") or "").strip() \
        or DEFAULT_PROFILE["style_preset"]
    return {
        "tone_sliders": {
            "formal_casual": _clamp(sliders.get("formal_casual")),
            "terse_expansive": _clamp(sliders.get("terse_expansive")),
        },
        "reading_level": reading,
        "signature_phrases": _phrase_list(raw.get("signature_phrases")),
        "banned_phrases": _phrase_list(raw.get("banned_phrases")),
        "pov": pov,
        "style_preset": style,
    }


def distill_profile(samples: list[str], *, llm_fn=None,
                    model: str | None = None) -> dict:
    """spec §5.1: sample texts → structured brand profile.

    `llm_fn(prompt) -> str` defaults to the writer model over OpenRouter;
    tests inject a fake. Raises ValueError on empty input or unparsable
    model output (the CLI reports and exits non-zero)."""
    texts = [s.strip() for s in (samples or [])
             if isinstance(s, str) and s.strip()]
    if not texts:
        raise ValueError(
            "at least one non-empty sample is required (spec §5.1: 3-5 "
            "samples — pasted text, files, or URLs)")
    numbered = "\n\n".join(
        f"--- Sample {i} ---\n{t[:_SAMPLE_MAX_CHARS]}"
        for i, t in enumerate(texts, 1))
    prompt = (
        f"Distill the brand voice profile from these {len(texts)} "
        f"sample(s) from the same brand:\n\n{numbered}")
    fn = llm_fn or (lambda p: _default_llm(p, model=model))
    return normalize_profile(_extract_json(fn(prompt)))


def save_profile(session: Session, site_id: int, profile: dict) -> BrandProfile:
    latest = session.execute(
        select(BrandProfile)
        .where(BrandProfile.site_id == site_id)
        .order_by(BrandProfile.version.desc())
        .limit(1)
    ).scalar_one_or_none()
    version = (latest.version + 1) if latest else 1
    row = BrandProfile(site_id=site_id, version=version, profile={**DEFAULT_PROFILE, **profile})
    session.add(row)
    session.commit()
    session.refresh(row)
    return row


def load_profile(session: Session, site_id: int) -> dict:
    row = session.execute(
        select(BrandProfile)
        .where(BrandProfile.site_id == site_id)
        .order_by(BrandProfile.version.desc())
        .limit(1)
    ).scalar_one_or_none()
    if row is None:
        return dict(DEFAULT_PROFILE)
    return dict(row.profile or DEFAULT_PROFILE)


def inject_into_system_prompt(base_prompt: str, profile: dict) -> str:
    """Prepend Brand DNA as a non-optional system block. Call for brief,
    draft, eval, and image-prompt agents."""
    p = {**DEFAULT_PROFILE, **(profile or {})}
    sliders = p.get("tone_sliders", {})
    block = (
        "[BRAND DNA — auto-loaded, applies to everything below]\n"
        f"- tone formal↔casual: {sliders.get('formal_casual', 0.5)}; "
        f"terse↔expansive: {sliders.get('terse_expansive', 0.5)}\n"
        f"- reading level: {p.get('reading_level')}; POV: {p.get('pov')}\n"
        f"- signature phrases: {', '.join(p.get('signature_phrases', [])) or '(none)'}\n"
        f"- banned phrases/clients: {', '.join(p.get('banned_phrases', [])) or '(none)'}\n"
        f"- image style preset: {p.get('style_preset')}\n"
    )
    return f"{block}\n{base_prompt}"


_INJECTION_MARK = "[BRAND DNA — auto-loaded"


def apply_brand_dna(agents: list, profile: dict) -> list[str]:
    """§5.1 Agrici rule — system-prompt-level injection for brief, draft,
    eval, and image-prompt agents. Mutates `agent.instructions` in place so
    agents created via `.as_tool()` (e.g. get_evaluation_feedback) pick it
    up too (as_tool keeps a live reference, verified against openai-agents).

    Idempotent: re-applying (e.g. re-running lifespan) will not double-inject.
    Returns the list of agent names that were injected.
    """
    injected: list[str] = []
    for agent in agents:
        current = agent.instructions or ""
        if _INJECTION_MARK in current:
            continue
        agent.instructions = inject_into_system_prompt(current, profile)
        injected.append(agent.name)
    return injected
