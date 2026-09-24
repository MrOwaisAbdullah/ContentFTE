"""
lib/jev_helpers.py — Domain helpers for general SEO Blog Agent / Autonomous Content Platform

General use case, not repo-specific. Each helper wraps lib/jev.py call_jev with:
- typed state/questions per domain playbooks
- confidence-gated branching
- typed fallback (never throws in pipeline path)
- usage logging via jev_log_fields

See: .claude/skills/jev-system-one/SKILL.md "SEO Blog Agent / Autonomous Content Platform"
      references/domain-playbooks.md #8
      assets/templates/seo-blog-agent.ts

Do not use for prose generation — Jev is decision lane, LLM is generation lane.
"""

import logging
import time
from typing import Any, Dict, List, Optional, Tuple

from lib.jev import JevError, JevResponse, call_jev, call_jev_sync, jev_log_fields

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# 1) Topic intake / dedupe — Noul is_duplicate
# ---------------------------------------------------------------------------
async def check_duplicate_topic(candidate: str, existing: List[str], threshold_noul=0.6, threshold_conf=0.65) -> Dict[str, Any]:
    """Async Noul variant. Returns {is_duplicate:bool, noul, confidence, usage, fallback:bool, raw: JevResponse|None}

    Live note (docs/jev-live-test-report.json, 20 candidates): Jev Noul returns
    confidence=null — only gate on conf when the API actually returns it. Default
    noul threshold lowered 0.75→0.6 after threshold sweep (noul>=0.6: P=1.00 R=0.67
    F1=0.80 vs noul>=0.75 R=0.44). Choice path (find_duplicate_topic) still gates conf>=0.65.
    """
    if not candidate or not candidate.strip():
        return {"is_duplicate": False, "noul": 0, "confidence": 0, "usage": None, "fallback": True, "raw": None}
    # Cap to last 300 to bound tokens (state window 32k)
    state = {"candidate": candidate, "existing": existing[-300:]}
    questions = {
        "is_duplicate": {
            "type": "noul",
            "instructions": "Is `candidate` essentially the SAME specific story/topic as any one entry in `existing` -- not just the same broad subject?",
            "criteria": {
                "true": "Same product + same specific release/angle (e.g. two posts about Xiaomi AI Cube 120B run)",
                "false": "Same broad subject but different specific story (e.g. two unrelated AI-agent posts)",
            },
        }
    }
    started = time.perf_counter()
    try:
        resp = await call_jev(state, questions)
        ans = resp.answers["is_duplicate"]
        noul = float(getattr(ans, "noul", 0))
        raw_conf = getattr(ans, "confidence", None)
        conf_ok = True if raw_conf is None else float(raw_conf) >= threshold_conf
        is_dup = noul >= threshold_noul and conf_ok
        latency = (time.perf_counter() - started) * 1000
        logger.info(f"check_duplicate_topic noul={noul:.2f} conf={raw_conf} is_dup={is_dup} {jev_log_fields(resp, latency)}")
        return {"is_duplicate": is_dup, "noul": noul, "confidence": float(raw_conf or 0), "usage": resp.usage.model_dump(), "fallback": False, "raw": resp}
    except JevError as e:
        logger.warning(f"check_duplicate_topic Jev fallback (skip warning): {e}")
        return {"is_duplicate": False, "noul": 0, "confidence": 0, "usage": None, "fallback": True, "raw": None}


def _build_duplicate_choice_state(candidate: str, existing: List[str]):
    capped = existing[-100:]
    key_to_topic: Dict[str, str] = {}
    criteria: Dict[str, str] = {"none": "No existing topic is the same specific story as `candidate` — all are different angles or subjects."}
    for i, topic in enumerate(capped):
        key = f"topic_{i}"
        criteria[key] = f"Existing topic: '{topic[:200]}' — SAME specific story as `candidate` if candidate covers essentially this exact topic/angle."
        key_to_topic[key] = topic
    return {"candidate": candidate, "existing": capped}, criteria, key_to_topic


async def find_duplicate_topic(candidate: str, existing: List[str], threshold_conf=0.65) -> Dict[str, Any]:
    """
    Choice-based variant that returns which existing topic matches, or None.
    Returns {matched_topic: Optional[str], confidence, choice, usage, fallback, raw}
    Never throws — fallback returns matched_topic=None.
    """
    if not candidate or not candidate.strip() or not existing:
        return {"matched_topic": None, "confidence": 0, "choice": "none", "usage": None, "fallback": True, "raw": None}
    state, criteria, key_to_topic = _build_duplicate_choice_state(candidate, existing)
    started = time.perf_counter()
    try:
        resp = await call_jev(state, {"duplicate_choice": {"type": "choice", "instructions": "Which existing topic, if any, is essentially the SAME specific story/topic as `candidate`? Choose `none` if no close match exists.", "criteria": criteria}})
        ans = resp.answers["duplicate_choice"]
        choice = str(getattr(ans, "choice", "none"))
        conf = float(getattr(ans, "confidence", 0) or 0)
        latency = (time.perf_counter() - started) * 1000
        if choice == "none" or conf < threshold_conf:
            logger.info(f"find_duplicate_topic no match choice={choice} conf={conf:.2f} {jev_log_fields(resp, latency)}")
            return {"matched_topic": None, "confidence": conf, "choice": choice, "usage": resp.usage.model_dump(), "fallback": False, "raw": resp}
        matched = key_to_topic.get(choice)
        logger.info(f"find_duplicate_topic matched='{matched}' conf={conf:.2f} {jev_log_fields(resp, latency)}")
        return {"matched_topic": matched, "confidence": conf, "choice": choice, "usage": resp.usage.model_dump(), "fallback": False, "raw": resp}
    except JevError as e:
        logger.warning(f"find_duplicate_topic Jev fallback: {e}")
        return {"matched_topic": None, "confidence": 0, "choice": "none", "usage": None, "fallback": True, "raw": None}


def check_duplicate_topic_sync(candidate: str, existing: List[str], threshold_noul=0.6, threshold_conf=0.65) -> Dict[str, Any]:
    """Sync variant for sync callers (e.g., scripts, bot fallback sync).

    Same live-tuned defaults as async: Noul conf may be null (gate skipped when None);
    noul>=0.6 after 20-candidate sweep (see docs/jev-live-test-report.json).
    """
    if not candidate or not candidate.strip():
        return {"is_duplicate": False, "noul": 0, "confidence": 0, "usage": None, "fallback": True, "raw": None}
    state = {"candidate": candidate, "existing": existing[-300:]}
    questions = {
        "is_duplicate": {
            "type": "noul",
            "instructions": "Is `candidate` essentially the SAME specific story/topic as any one entry in `existing` -- not just the same broad subject?",
            "criteria": {
                "true": "Same product + same specific release/angle",
                "false": "Same broad subject but different specific story",
            },
        }
    }
    started = time.perf_counter()
    try:
        resp = call_jev_sync(state, questions)
        ans = resp.answers["is_duplicate"]
        noul = float(getattr(ans, "noul", 0))
        raw_conf = getattr(ans, "confidence", None)
        conf_ok = True if raw_conf is None else float(raw_conf) >= threshold_conf
        is_dup = noul >= threshold_noul and conf_ok
        latency = (time.perf_counter() - started) * 1000
        logger.info(f"check_duplicate_topic_sync noul={noul:.2f} conf={raw_conf} is_dup={is_dup} {jev_log_fields(resp, latency)}")
        return {"is_duplicate": is_dup, "noul": noul, "confidence": float(raw_conf or 0), "usage": resp.usage.model_dump(), "fallback": False, "raw": resp}
    except JevError as e:
        logger.warning(f"check_duplicate_topic_sync Jev fallback: {e}")
        return {"is_duplicate": False, "noul": 0, "confidence": 0, "usage": None, "fallback": True, "raw": None}


# ---------------------------------------------------------------------------
# 2) Research pre-filter — Noul is_relevant ×N batched (map-reduce)
# ---------------------------------------------------------------------------
async def filter_relevant_excerpts(question: str, excerpts: List[Dict[str, str]], threshold=0.65) -> Tuple[List[Dict[str, Any]], JevResponse | None]:
    """
    question: topic string; excerpts: [{id, excerpt} ... up to 10-20]
    Returns (relevant_excerpts: [{id, excerpt, noul, confidence}], JevResponse|None)
    Falls back to all excerpts on JevError (never lose data due to gate).
    """
    if not excerpts:
        return [], None
    # Cap per-call batch to 10 to keep tokens bounded; caller can chunk if >10
    batch = excerpts[:10]
    state = {"question": question, "excerpts": batch}
    questions: Dict[str, Any] = {}
    for ex in batch:
        qkey = f"{ex['id']}_relevant"
        questions[qkey] = {
            "type": "noul",
            "instructions": f"Is `excerpts[id==\"{ex['id']}\"].excerpt` relevant to `question` for this article angle?",
        }
    started = time.perf_counter()
    try:
        resp = await call_jev(state, questions)
        latency = (time.perf_counter() - started) * 1000
        relevant: List[Dict[str, Any]] = []
        for ex in batch:
            ans = resp.answers.get(f"{ex['id']}_relevant")
            if ans is None:
                continue
            noul = float(getattr(ans, "noul", 0))
            conf = float(getattr(ans, "confidence", 0) or 0)
            if noul >= threshold:
                relevant.append({**ex, "noul": noul, "confidence": conf})
        logger.info(f"filter_relevant_excerpts kept {len(relevant)}/{len(batch)} threshold={threshold} {jev_log_fields(resp, latency)}")
        return relevant, resp
    except JevError as e:
        logger.warning(f"filter_relevant_excerpts Jev fallback (return all): {e}")
        return excerpts, None


# ---------------------------------------------------------------------------
# 3) Topic gate — needs_research + intent + trend batched
# ---------------------------------------------------------------------------
async def gate_blog_topic(topic: str, brief: str = "") -> Dict[str, Any]:
    """
    Batched: Noul needs_research + Choice intent + Score trend in one call (1 latency unit, ~12x cheaper).
    Returns {needs_research:bool, intent:str, trend:float, confidence:..., usage, fallback, raw}
    """
    state = {"topic": topic, "brief": brief}
    questions = {
        "needs_research": {
            "type": "noul",
            "instructions": "Does this topic require citations or fresh sources beyond common knowledge? Think PII, pricing, legal, medical, or stats where a stale answer harms.",
        },
        "intent": {
            "type": "choice",
            "instructions": "What is the primary search intent for this topic?",
            "criteria": {
                "informational": "Reader wants to learn or understand a concept",
                "transactional": "Reader wants to buy, sign up, or compare prices",
                "navigational": "Reader wants to find a specific tool or page",
                "comparison": "Reader is comparing 2+ options before deciding",
            },
        },
        "trend": {
            "type": "score",
            "instructions": "How timely and trend-sensitive is this topic?",
            "criteria": ["Evergreen: true for years", "Seasonal: cycles yearly", "Trending now: viral or news-driven"],
        },
    }
    started = time.perf_counter()
    try:
        resp = await call_jev(state, questions)
        latency = (time.perf_counter() - started) * 1000
        needs = float(getattr(resp.answers["needs_research"], "noul", 0)) >= 0.6
        intent = str(getattr(resp.answers["intent"], "choice", "informational"))
        trend = float(getattr(resp.answers["trend"], "score", 0))
        logger.info(f"gate_blog_topic needs={needs} intent={intent} trend={trend:.2f} {jev_log_fields(resp, latency)}")
        return {
            "needs_research": needs,
            "intent": intent,
            "trend": trend,
            "usage": resp.usage.model_dump(),
            "fallback": False,
            "raw": resp,
            "latency_ms": latency,
        }
    except JevError as e:
        logger.warning(f"gate_blog_topic Jev fallback: {e}")
        return {"needs_research": True, "intent": "informational", "trend": 0.0, "usage": None, "fallback": True, "raw": None, "latency_ms": 0}


# ---------------------------------------------------------------------------
# 4) Draft QA cascade — fact_supported + on_brand + is_stack_aligned + quality Score
#     Uses live_profile {about_me, summary, skills, current_roles} from AUTHOR_PROFILE_API_URL
#     vs fallback static tagline/proof_points (tools.py:185/252) — prevents WordPress/PHP drift when live stack is Next.js
# ---------------------------------------------------------------------------
async def score_draft_quality(draft: str, facts: List[str], live_profile: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """
    Jev Verified Cascade gate. facts: list of excerpts; live_profile: {about_me, summary, skills, current_roles} from get_author_context_tool.
    Returns {supported, on_brand, stack_aligned, score, publish_ready, usage, fallback, raw}
    Gate: supported>=0.7 && score>=1.5 && on_brand>=0.6 && stack_aligned>=0.7 (if live_profile provided; else stack check skipped)
    """
    facts_joined = "\n---\n".join(facts) if isinstance(facts, list) else str(facts)
    if not facts_joined.strip():
        facts_joined = "No facts provided"
    # Build state — include live_profile so Jev can check stack/about_me alignment; fallback static still grounded but flagged
    state: Dict[str, Any] = {"draft": draft[:80000], "facts": facts_joined[:80000]}
    if live_profile:
        # Trim skills to keep state bounded; keep about_me one-line bio explicit
        lp = dict(live_profile)
        if isinstance(lp.get("skills"), list) and len(lp["skills"]) > 40:
            lp["skills"] = lp["skills"][:40]
        state["live_profile"] = lp
    questions: Dict[str, Any] = {
        "fact_supported": {
            "type": "noul",
            "instructions": "Is every factual claim in `draft` supported by `facts`? Draft must not invent numbers, dates, or quotes not in `facts`.",
        },
        "on_brand": {
            "type": "noul",
            "instructions": "Is `draft` consistent with plain expert tone per `live_profile.about_me` (e.g. Spec-Driven Developer...), no inflated AI language like \"cutting-edge\" or \"seamless\"?",
        },
        "quality": {
            "type": "score",
            "instructions": "How ready is this draft to publish?",
            "criteria": ["Reject: inaccurate or thin", "Needs edits: usable but gaps remain", "Publish-ready: accurate, complete, on-brand & stack-aligned"],
        },
    }
    if live_profile:
        # About_me is one-line bio from AUTHOR_PROFILE_API_URL `about` (e.g. "Spec-Driven Developer. AI Agent Engineer...") vs fallback tagline
        questions["is_stack_aligned"] = {
            "type": "noul",
            "instructions": "Does `draft`'s tech mentions (frameworks, DB, infra, e.g. Next.js/TypeScript/Python/Claude Code/PostgreSQL/pgvector/R2/Docker) match only items in `live_profile.skills` + `live_profile.summary` core stack + `live_profile.about_me` — not invented stacks like generic WordPress/PHP when live is Next.js?",
        }
    started = time.perf_counter()
    try:
        resp = await call_jev(state, questions)
        latency = (time.perf_counter() - started) * 1000
        supported = float(getattr(resp.answers["fact_supported"], "noul", 0))
        on_brand = float(getattr(resp.answers["on_brand"], "noul", 0))
        score = float(getattr(resp.answers["quality"], "score", 0))
        stack_aligned = 1.0
        if "is_stack_aligned" in resp.answers:
            stack_aligned = float(getattr(resp.answers["is_stack_aligned"], "noul", 0))
            publish_ready = supported >= 0.7 and score >= 1.5 and on_brand >= 0.6 and stack_aligned >= 0.7
            logger.info(f"score_draft_quality supported={supported:.2f} on_brand={on_brand:.2f} stack_aligned={stack_aligned:.2f} score={score:.2f} publish_ready={publish_ready} {jev_log_fields(resp, latency)}")
            return {"supported": supported, "on_brand": on_brand, "stack_aligned": stack_aligned, "score": score, "publish_ready": publish_ready, "usage": resp.usage.model_dump(), "fallback": False, "raw": resp, "latency_ms": latency}
        publish_ready = supported >= 0.7 and score >= 1.5 and on_brand >= 0.6
        logger.info(f"score_draft_quality supported={supported:.2f} on_brand={on_brand:.2f} score={score:.2f} publish_ready={publish_ready} {jev_log_fields(resp, latency)}")
        return {"supported": supported, "on_brand": on_brand, "stack_aligned": stack_aligned, "score": score, "publish_ready": publish_ready, "usage": resp.usage.model_dump(), "fallback": False, "raw": resp, "latency_ms": latency}
    except JevError as e:
        logger.warning(f"score_draft_quality Jev fallback (require full eval): {e}")
        return {"supported": 0, "on_brand": 0, "stack_aligned": 0, "score": 0, "publish_ready": False, "usage": None, "fallback": True, "raw": None, "latency_ms": 0}


# ---------------------------------------------------------------------------
# 5) Claim verification — Noul claim_supported per {claim, excerpt}
# ---------------------------------------------------------------------------
async def verify_claim_supported(claim: str, excerpt: str) -> Dict[str, Any]:
    """Single claim vs excerpt. Returns {supported:float, confidence, fallback}. Compose via weighted score in caller."""
    state = {"claim": claim, "excerpt": excerpt}
    questions = {
        "claim_supported": {
            "type": "noul",
            "instructions": "Is `claim` supported by `excerpt`? Every fact/number in claim must be stated in excerpt or be direct entailment.",
        }
    }
    try:
        resp = await call_jev(state, questions)
        ans = resp.answers["claim_supported"]
        return {"supported": float(getattr(ans, "noul", 0)), "confidence": float(getattr(ans, "confidence", 0) or 0), "fallback": False, "raw": resp, "usage": resp.usage.model_dump()}
    except JevError as e:
        logger.warning(f"verify_claim_supported fallback: {e}")
        return {"supported": 0, "confidence": 0, "fallback": True, "raw": None, "usage": None}


# ---------------------------------------------------------------------------
# 6) Taxonomy / CMS publish — Choice category over existing taxonomy (≤255)
# ---------------------------------------------------------------------------
async def classify_category(keyword_topic: str, existing_categories: List[str]) -> Dict[str, Any]:
    """
    Returns {action: "reuse"|"propose_new", category:str, confidence:float, usage, fallback}
    Caller: if reuse → use category directly; if propose_new → LLM suggests one name gated by Noul is_new_category_justified (or keep reuse as fallback).
    """
    if not existing_categories:
        return {"action": "propose_new", "category": keyword_topic.strip().title()[:60], "confidence": 0, "usage": None, "fallback": True, "raw": None}
    # Build criteria: each category short description
    criteria: Dict[str, str] = {}
    for c in existing_categories[:255]:
        criteria[c] = f"Posts about {c}"
    state = {"keyword_topic": keyword_topic}
    questions = {
        "category": {
            "type": "choice",
            "instructions": "Which existing category best fits `keyword_topic`?",
            "criteria": criteria,
        }
    }
    try:
        resp = await call_jev(state, questions)
        ans = resp.answers["category"]
        choice = str(getattr(ans, "choice", existing_categories[0]))
        conf = float(getattr(ans, "confidence", 0) or 0)
        # If confidence low, signal to propose new rather than force-fit
        if conf >= 0.6:
            logger.info(f"classify_category reuse={choice} conf={conf:.2f}")
            return {"action": "reuse", "category": choice, "confidence": conf, "usage": resp.usage.model_dump(), "fallback": False, "raw": resp}
        logger.info(f"classify_category low conf {conf:.2f} → propose_new, suggested={choice}")
        return {"action": "propose_new", "category": choice, "confidence": conf, "usage": resp.usage.model_dump(), "fallback": False, "raw": resp}
    except JevError as e:
        logger.warning(f"classify_category Jev fallback (propose new): {e}")
        return {"action": "propose_new", "category": existing_categories[0] if existing_categories else keyword_topic.strip().title()[:60], "confidence": 0, "usage": None, "fallback": True, "raw": None}


# ---------------------------------------------------------------------------
# 7) Internal link relevance + diversity — Noul per section+link (fixes same-type repetition)
# ---------------------------------------------------------------------------
async def rank_internal_links(section_text: str, links: List[Dict[str, str]], recent_slugs: Optional[List[str]] = None) -> Dict[str, Any]:
    """
    Ranks fetch_internal_links_tool results per H2 section. Fixes _createdAt-desc same-type repetition.
    Returns {ranked: [{slug,title,summary,is_relevant,noul,confidence,is_recent_repeat}], fallback, raw}
    """
    if not links:
        return {"ranked": [], "fallback": True, "raw": None}
    batch = links[:5]
    recent = (recent_slugs or [])[-10:]
    state = {"section_text": section_text[:4000], "links": batch, "recent_slugs": recent}
    questions: Dict[str, Any] = {}
    for i, link in enumerate(batch):
        questions[f"link_{i}_relevant"] = {"type": "noul", "instructions": f"Is `links[{i}].title` + `links[{i}].summary` contextually relevant to `section_text` as an internal link? Must be same subtopic/angle, not just same broad category."}
    try:
        resp = await call_jev(state, questions)
        ranked: List[Dict[str, Any]] = []
        for i, link in enumerate(batch):
            ans = resp.answers.get(f"link_{i}_relevant")
            if ans is None:
                continue
            noul = float(getattr(ans, "noul", 0))
            conf = float(getattr(ans, "confidence", 0) or 0)
            is_relevant = noul >= 0.65 and conf >= 0.5
            is_recent = link.get("slug", "") in recent
            adjusted = noul - (0.15 if is_recent else 0.0)
            ranked.append({**link, "is_relevant": is_relevant, "noul": noul, "confidence": conf, "is_recent_repeat": is_recent, "adjusted_noul": round(adjusted, 3)})
        ranked.sort(key=lambda x: (x["is_relevant"], x["adjusted_noul"]), reverse=True)
        return {"ranked": ranked, "fallback": False, "raw": resp}
    except JevError as e:
        logger.warning(f"rank_internal_links fallback: {e}")
        return {"ranked": [{**l, "is_relevant": True, "noul": 0, "confidence": 0, "is_recent_repeat": l.get("slug","") in recent} for l in batch], "fallback": True, "raw": None}


# ---------------------------------------------------------------------------
# 8) External link hallucination guard — Noul is_supported per external URL
# ---------------------------------------------------------------------------
async def verify_external_links(section_text: str, external_links: List[Dict[str, str]], excerpts: List[str]) -> Dict[str, Any]:
    if not external_links:
        return {"ranked": [], "fallback": True, "raw": None}
    batch = external_links[:5]
    excerpts_joined = "\n---\n".join(excerpts[:10])[:12000] if excerpts else "No excerpts"
    state: Dict[str, Any] = {"section_text": section_text[:4000], "external_links": batch, "excerpts": excerpts_joined}
    questions: Dict[str, Any] = {}
    for i, link in enumerate(batch):
        url = link.get("url", "")
        anchor = link.get("text", link.get("anchor", ""))
        questions[f"ext_{i}_supported"] = {"type": "noul", "instructions": f"Is external link `external_links[{i}].url` ({url} anchor '{anchor}') supported by `excerpts` and contextually relevant to `section_text`? Must be real domain mentioned in excerpts or same topic, not hallucinated."}
    try:
        resp = await call_jev(state, questions)
        ranked: List[Dict[str, Any]] = []
        for i, link in enumerate(batch):
            ans = resp.answers.get(f"ext_{i}_supported")
            if ans is None:
                continue
            noul = float(getattr(ans, "noul", 0))
            conf = float(getattr(ans, "confidence", 0) or 0)
            is_supported = noul >= 0.65
            ranked.append({**link, "is_supported": is_supported, "noul": noul, "confidence": conf})
        ranked.sort(key=lambda x: (x["is_supported"], x["noul"]), reverse=True)
        return {"ranked": ranked, "fallback": False, "raw": resp}
    except JevError as e:
        logger.warning(f"verify_external_links fallback: {e}")
        return {"ranked": [{**l, "is_supported": True, "noul": 0, "confidence": 0} for l in batch], "fallback": True, "raw": None}


# ---------------------------------------------------------------------------
# 9) Human-in-the-loop routing — Score priority + Noul is_safe/needs_update
# ---------------------------------------------------------------------------
async def route_human_review(draft: str, seo_metrics: Optional[Dict[str, Any]] = None, age_days: Optional[int] = None) -> Dict[str, Any]:
    """
    General Score priority + Noul gates for publish/repurpose/freshness.
    Returns {priority_score:float, is_safe:bool, needs_update:bool, fallback}
    Thresholds per patterns.md: priority>=1.5 → human review, is_safe<0.5 → block.
    """
    seometrics = seo_metrics or {}
    state = {"draft": draft[:40000], "seo_metrics": seometrics, "age_days": age_days}
    questions: Dict[str, Any] = {
        "priority": {
            "type": "score",
            "instructions": "How urgently does this draft need human review before publishing?",
            "criteria": ["Low: auto-publish safe", "Medium: quick check", "High: needs review/block"],
        },
        "is_safe": {
            "type": "noul",
            "instructions": "Is `draft` safe for public publishing (no hate, PII, unverified risky claim)?",
        },
    }
    if age_days is not None:
        questions["needs_update"] = {
            "type": "noul",
            "instructions": "Is this content outdated and needing an update given `age_days` and `seo_metrics`?",
        }
    try:
        resp = await call_jev(state, questions)
        prio = float(getattr(resp.answers["priority"], "score", 0))
        safe = float(getattr(resp.answers["is_safe"], "noul", 1)) >= 0.5
        needs_up = False
        if "needs_update" in resp.answers:
            needs_up = float(getattr(resp.answers["needs_update"], "noul", 0)) >= 0.65
        return {"priority_score": prio, "is_safe": safe, "needs_update": needs_up, "usage": resp.usage.model_dump(), "fallback": False, "raw": resp}
    except JevError as e:
        logger.warning(f"route_human_review fallback: {e}")
        return {"priority_score": 1.0, "is_safe": True, "needs_update": False, "usage": None, "fallback": True, "raw": None}
