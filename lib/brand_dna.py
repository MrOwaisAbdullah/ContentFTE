"""§5.1 Brand DNA — per-site voice profiles, versioned in Postgres.

Implementation rule (Agrici pattern): the profile is auto-loaded at the
SYSTEM-PROMPT level for brief/draft/eval/image-prompt agents — never
passed as an optional parameter that can be forgotten.

This module is storage + injection. Distillation (samples → profile)
happens via the existing writer model in a later wiring commit; the
schema here is what that step writes to.
"""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from lib.db import BrandProfile

DEFAULT_PROFILE = {
    "tone_sliders": {"formal_casual": 0.5, "terse_expansive": 0.5},
    "reading_level": "grade-8",
    "signature_phrases": [],
    "banned_phrases": [],
    "pov": "second",
    "style_preset": "photoreal",
}


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
