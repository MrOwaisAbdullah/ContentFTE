"""
lib/jev_tools.py — @function_tool wrappers for OpenAI Agents SDK

Exposes Jev helpers as tools agents can call. Each tool is sync (function_tool)
and internally calls lib/jev.py sync variant with fallback — never throws in
agent path (returns fallback dict instead).

General use case, not repo-specific — any SEO blog agent can import these.
"""

import json
import logging
import os

from agents.decorators import tool as function_tool  # correct per openai-agents-python docs (Context7 /openai/openai-agents-python): from agents.decorators import tool
# alias kept as function_tool for this repo's existing import style — both map to same function in 0.19.2

from lib.jev import JevError, call_jev_sync

logger = logging.getLogger(__name__)


def jev_is_relevant(question: str, excerpts_json: str) -> str:
    """Plain function for direct calls (tests, workflow code). Wrapped as tool below."""
    """
    Jev Noul is_relevant ×N batched — filters search excerpts before expensive extract/crawl.

    Args:
        question: topic/question string
        excerpts_json: JSON string of [{"id": "r0", "excerpt": "..."}, ...] up to 10 items (each excerpt truncated to ~800 chars by caller)
    Returns:
        JSON string: {"relevant": [{"id":..., "excerpt":..., "noul":..., "confidence":...}], "fallback": bool, "usage": {...}|None}
        Caller keeps only relevant (noul>=0.65) for tavily_extract. On fallback (JevError/timeout) returns all excerpts so data is not lost.
    """
    try:
        excerpts = json.loads(excerpts_json)
        if not isinstance(excerpts, list):
            return json.dumps({"error": "excerpts_json must be list of {id, excerpt}", "relevant": [], "fallback": True})
    except Exception as e:
        return json.dumps({"error": f"Invalid excerpts_json: {e}", "relevant": [], "fallback": True})

    batch = excerpts[:10]
    state = {"question": question, "excerpts": batch}
    questions = {}
    for ex in batch:
        qkey = f"{ex['id']}_relevant"
        questions[qkey] = {"type": "noul", "instructions": f"Is `excerpts[id==\"{ex['id']}\"].excerpt` relevant to `question` for this article angle?"}
    try:
        resp = call_jev_sync(state, questions)
        relevant = []
        for ex in batch:
            ans = resp.answers.get(f"{ex['id']}_relevant")
            if ans is None:
                continue
            # ans is dict-like after pydantic? JevResponse uses model_validate, ans is model
            noul = float(getattr(ans, "noul", ans.get("noul", 0)) if isinstance(ans, dict) else getattr(ans, "noul", 0))
            conf = float(getattr(ans, "confidence", ans.get("confidence", 0) or 0) if isinstance(ans, dict) else getattr(ans, "confidence", 0) or 0)
            if noul >= 0.65:
                relevant.append({**ex, "noul": noul, "confidence": conf})
        return json.dumps({"relevant": relevant, "fallback": False, "usage": resp.usage.model_dump(), "kept": f"{len(relevant)}/{len(batch)}"})
    except JevError as e:
        logger.warning(f"jev_is_relevant_tool fallback (return all): {e}")
        return json.dumps({"relevant": excerpts, "fallback": True, "error": str(e), "kept": f"{len(excerpts)}/{len(excerpts)}"})
    except Exception as e:
        logger.warning(f"jev_is_relevant_tool unexpected fallback: {e}")
        return json.dumps({"relevant": excerpts, "fallback": True, "error": str(e)})


# Wrapped tool for agents (OpenAI Agents SDK tool calling)
jev_is_relevant_tool = function_tool(jev_is_relevant)


def jev_gate_blog_topic(topic: str, brief: str = "") -> str:
    """Plain function for direct calls. Wrapped as tool below."""
    """
    Jev batched gate: needs_research (Noul) + intent (Choice) + trend (Score) in one call (1 latency unit).

    Args:
        topic: keyword/topic string
        brief: optional brief/context (may be empty)
    Returns:
        JSON string: {"needs_research": bool, "intent": "informational|transactional|navigational|comparison", "trend": float, "fallback": bool, "usage": {...}|None}
        On fallback returns needs_research=True, intent=informational (safe defaults that preserve data, never block).
    """
    state = {"topic": topic, "brief": brief}
    questions = {
        "needs_research": {"type": "noul", "instructions": "Does this topic require citations or fresh sources beyond common knowledge? Think PII, pricing, legal, medical, or stats where a stale answer harms."},
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
        "trend": {"type": "score", "instructions": "How timely and trend-sensitive is this topic?", "criteria": ["Evergreen: true for years", "Seasonal: cycles yearly", "Trending now: viral or news-driven"]},
    }
    try:
        resp = call_jev_sync(state, questions)
        needs = float(getattr(resp.answers["needs_research"], "noul", resp.answers["needs_research"].get("noul", 0)) if isinstance(resp.answers["needs_research"], dict) else getattr(resp.answers["needs_research"], "noul", 0)) >= 0.6
        # Choice
        intent_ans = resp.answers["intent"]
        intent = str(getattr(intent_ans, "choice", intent_ans.get("choice", "informational")) if isinstance(intent_ans, dict) else getattr(intent_ans, "choice", "informational"))
        trend_ans = resp.answers["trend"]
        trend = float(getattr(trend_ans, "score", trend_ans.get("score", 0)) if isinstance(trend_ans, dict) else getattr(trend_ans, "score", 0))
        return json.dumps({"needs_research": needs, "intent": intent, "trend": trend, "fallback": False, "usage": resp.usage.model_dump()})
    except JevError as e:
        logger.warning(f"jev_gate_blog_topic_tool fallback: {e}")
        return json.dumps({"needs_research": True, "intent": "informational", "trend": 0.0, "fallback": True, "error": str(e)})
    except Exception as e:
        logger.warning(f"jev_gate_blog_topic_tool unexpected fallback: {e}")
        return json.dumps({"needs_research": True, "intent": "informational", "trend": 0.0, "fallback": True, "error": str(e)})


jev_gate_blog_topic_tool = function_tool(jev_gate_blog_topic)


def jev_score_draft_quality(draft: str, facts_json: str, live_profile_json: str = "") -> str:
    """Plain function for direct calls. Wrapped as tool below."""
    """
    Jev Verified Cascade gate: fact_supported (Noul) + on_brand (Noul) + is_stack_aligned (Noul) + quality (Score) batched.
    Uses live_profile {about_me, summary, skills, current_roles} from AUTHOR_PROFILE_API_URL vs fallback static tagline/proof_points.

    Args:
        draft: markdown draft (truncated to ~80k chars)
        facts_json: JSON string of ["excerpt 1", "excerpt 2", ...] or joined string
        live_profile_json: JSON string of {about_me, summary, skills: string[], current_roles} from get_author_context_tool (live_profile). If empty, stack check is skipped (backward compat) but logs fallback.
    Returns:
        JSON string: {"supported": float, "on_brand": float, "stack_aligned": float, "score": float, "publish_ready": bool, "fallback": bool, "usage": {...}|None}
        Gate: publish_ready = supported>=0.7 && score>=1.5 && on_brand>=0.6 && stack_aligned>=0.7 (if live_profile provided; else stack check skipped)
        On fallback returns publish_ready=False (requires full evaluator).
    """
    try:
        facts = json.loads(facts_json) if facts_json.strip().startswith("[") else [facts_json]
        if isinstance(facts, str):
            facts = [facts]
    except Exception:
        facts = [facts_json]
    facts_joined = "\n---\n".join(facts) if isinstance(facts, list) else str(facts)
    if not facts_joined.strip():
        facts_joined = "No facts provided"
    # Parse live_profile for stack/about_me alignment; fallback static is {"about_me": "Web, AI & Automation—Made Simple.", ...} from tools.py:185
    live_profile = None
    if live_profile_json and live_profile_json.strip():
        try:
            live_profile = json.loads(live_profile_json) if live_profile_json.strip().startswith("{") else None
        except Exception:
            live_profile = None
    state: dict = {"draft": draft[:80000], "facts": facts_joined[:80000]}
    if live_profile:
        # Trim skills to keep state bounded
        lp = dict(live_profile)
        if isinstance(lp.get("skills"), list) and len(lp["skills"]) > 40:
            lp["skills"] = lp["skills"][:40]
        state["live_profile"] = lp
    questions: dict = {
        "fact_supported": {"type": "noul", "instructions": "Is every factual claim in `draft` supported by `facts`? Draft must not invent numbers, dates, or quotes not in `facts`."},
        "on_brand": {"type": "noul", "instructions": "Is `draft` consistent with plain expert tone per `live_profile.about_me` (e.g. Spec-Driven Developer...), no inflated AI language like \"cutting-edge\" or \"seamless\"?"},
        "quality": {"type": "score", "instructions": "How ready is this draft to publish?", "criteria": ["Reject: inaccurate or thin", "Needs edits: usable but gaps remain", "Publish-ready: accurate, complete, on-brand & stack-aligned"]},
    }
    if live_profile:
        questions["is_stack_aligned"] = {"type": "noul", "instructions": "Does `draft`'s tech mentions (frameworks, DB, infra, e.g. Next.js/TypeScript/Python/Claude Code/PostgreSQL/pgvector/R2/Docker) match only items in `live_profile.skills` + `live_profile.summary` core stack + `live_profile.about_me` — not invented stacks like generic WordPress/PHP when live is Next.js?"}
    try:
        resp = call_jev_sync(state, questions)
        # Handle dict vs model
        def _noul(key):
            ans = resp.answers[key]
            return float(getattr(ans, "noul", ans.get("noul", 0)) if isinstance(ans, dict) else getattr(ans, "noul", 0))
        def _score(key):
            ans = resp.answers[key]
            return float(getattr(ans, "score", ans.get("score", 0)) if isinstance(ans, dict) else getattr(ans, "score", 0))
        supported = _noul("fact_supported")
        on_brand = _noul("on_brand")
        score = _score("quality")
        if "is_stack_aligned" in resp.answers:
            stack_aligned = _noul("is_stack_aligned")
            publish_ready = supported >= 0.7 and score >= 1.5 and on_brand >= 0.6 and stack_aligned >= 0.7
            return json.dumps({"supported": supported, "on_brand": on_brand, "stack_aligned": stack_aligned, "score": score, "publish_ready": publish_ready, "fallback": False, "usage": resp.usage.model_dump()})
        publish_ready = supported >= 0.7 and score >= 1.5 and on_brand >= 0.6
        return json.dumps({"supported": supported, "on_brand": on_brand, "stack_aligned": 1.0, "score": score, "publish_ready": publish_ready, "fallback": False, "usage": resp.usage.model_dump()})
    except JevError as e:
        logger.warning(f"jev_score_draft_quality_tool fallback: {e}")
        return json.dumps({"supported": 0, "on_brand": 0, "stack_aligned": 0, "score": 0, "publish_ready": False, "fallback": True, "error": str(e)})
    except Exception as e:
        logger.warning(f"jev_score_draft_quality_tool unexpected fallback: {e}")
        return json.dumps({"supported": 0, "on_brand": 0, "stack_aligned": 0, "score": 0, "publish_ready": False, "fallback": True, "error": str(e)})


jev_score_draft_quality_tool = function_tool(jev_score_draft_quality)


def jev_classify_category(keyword_topic: str, existing_categories_json: str) -> str:
    """
    Jev Choice category over existing taxonomy (≤255). Plain function for direct calls. Wrapped as tool below.

    Args:
        keyword_topic: topic string to classify
        existing_categories_json: JSON string of ["SEO", "AI Agents", ...] existing category titles
    Returns:
        JSON string: {"action": "reuse"|"propose_new", "category": str, "confidence": float, "fallback": bool, "usage": {...}|None}
        On fallback returns propose_new with first category or topic title.
    """
    try:
        existing = json.loads(existing_categories_json)
        if not isinstance(existing, list):
            existing = []
    except Exception:
        existing = []
    if not existing:
        return json.dumps({"action": "propose_new", "category": keyword_topic.strip().title()[:60], "confidence": 0, "fallback": True})
    criteria = {c: f"Posts about {c}" for c in existing[:255]}
    state = {"keyword_topic": keyword_topic}
    questions = {"category": {"type": "choice", "instructions": "Which existing category best fits `keyword_topic`?", "criteria": criteria}}
    try:
        resp = call_jev_sync(state, questions)
        ans = resp.answers["category"]
        choice = str(getattr(ans, "choice", ans.get("choice", existing[0])) if isinstance(ans, dict) else getattr(ans, "choice", existing[0]))
        conf = float(getattr(ans, "confidence", ans.get("confidence", 0) or 0) if isinstance(ans, dict) else getattr(ans, "confidence", 0) or 0)
        action = "reuse" if conf >= 0.6 else "propose_new"
        return json.dumps({"action": action, "category": choice, "confidence": conf, "fallback": False, "usage": resp.usage.model_dump()})
    except JevError as e:
        logger.warning(f"jev_classify_category_tool fallback: {e}")
        return json.dumps({"action": "propose_new", "category": existing[0] if existing else keyword_topic.strip().title()[:60], "confidence": 0, "fallback": True, "error": str(e)})
    except Exception as e:
        logger.warning(f"jev_classify_category_tool unexpected fallback: {e}")
        return json.dumps({"action": "propose_new", "category": existing[0] if existing else keyword_topic.strip().title()[:60], "confidence": 0, "fallback": True, "error": str(e)})


jev_classify_category_tool = function_tool(jev_classify_category)


# --- Additional general SEO pipeline gates (remaining from integration report) ---

def jev_score_brief_quality(brief_content: str, faqs_json: str) -> str:
    """Jev Score brief completeness — C1. Returns {score, fallback, usage}."""
    try:
        faqs = faqs_json[:2000] if isinstance(faqs_json, str) else str(faqs_json)
    except Exception:
        faqs = ""
    state = {"brief_content": brief_content[:80000], "faqs": faqs}
    questions = {
        "brief_quality": {
            "type": "score",
            "instructions": "How ready is this brief to generate a post?",
            "criteria": ["Reject: missing H1 or <4 H2 or FAQ malformed", "Needs edits: has shape but thin", "Ready: H1 + 4-6 H2 + 5-7 FAQs + links + summary 50-160 chars"],
        }
    }
    try:
        resp = call_jev_sync(state, questions)
        ans = resp.answers["brief_quality"]
        score = float(getattr(ans, "score", ans.get("score", 0)) if isinstance(ans, dict) else getattr(ans, "score", 0))
        return json.dumps({"score": score, "ready": score >= 1.5, "fallback": False, "usage": resp.usage.model_dump()})
    except JevError as e:
        logger.warning(f"jev_score_brief_quality fallback: {e}")
        return json.dumps({"score": 0, "ready": False, "fallback": True, "error": str(e)})
    except Exception as e:
        logger.warning(f"jev_score_brief_quality unexpected fallback: {e}")
        return json.dumps({"score": 0, "ready": False, "fallback": True, "error": str(e)})


jev_score_brief_quality_tool = function_tool(jev_score_brief_quality)


def jev_verify_claim(claim: str, excerpt: str) -> str:
    """Jev Noul claim_supported — D2 per-claim verification. Returns {supported, confidence, fallback}."""
    state = {"claim": claim, "excerpt": excerpt}
    questions = {"claim_supported": {"type": "noul", "instructions": "Is `claim` supported by `excerpt`? Every fact/number in claim must be stated in excerpt or direct entailment."}}
    try:
        resp = call_jev_sync(state, questions)
        ans = resp.answers["claim_supported"]
        supported = float(getattr(ans, "noul", ans.get("noul", 0)) if isinstance(ans, dict) else getattr(ans, "noul", 0))
        conf = float(getattr(ans, "confidence", ans.get("confidence", 0) or 0) if isinstance(ans, dict) else getattr(ans, "confidence", 0) or 0)
        return json.dumps({"supported": supported, "confidence": conf, "fallback": False, "usage": resp.usage.model_dump()})
    except JevError as e:
        logger.warning(f"jev_verify_claim fallback: {e}")
        return json.dumps({"supported": 0, "confidence": 0, "fallback": True, "error": str(e)})
    except Exception as e:
        logger.warning(f"jev_verify_claim unexpected fallback: {e}")
        return json.dumps({"supported": 0, "confidence": 0, "fallback": True, "error": str(e)})


jev_verify_claim_tool = function_tool(jev_verify_claim)


def jev_score_title_hook(title: str, summary: str, intent: str = "") -> str:
    """Jev Score hook_strength — D4 title/summary gate. Returns {score, ready, fallback}."""
    state = {"title": title, "summary": summary, "intent": intent}
    questions = {
        "hook_strength": {
            "type": "score",
            "instructions": "How strong is this title+summary as a SERP hook for intent?",
            "criteria": ["Generic label, no reason to click", "Usable but flat", "Strong: specific angle/number/promise matching intent"],
        }
    }
    try:
        resp = call_jev_sync(state, questions)
        ans = resp.answers["hook_strength"]
        score = float(getattr(ans, "score", ans.get("score", 0)) if isinstance(ans, dict) else getattr(ans, "score", 0))
        return json.dumps({"score": score, "ready": score >= 1.2, "fallback": False, "usage": resp.usage.model_dump()})
    except JevError as e:
        logger.warning(f"jev_score_title_hook fallback: {e}")
        return json.dumps({"score": 0, "ready": False, "fallback": True, "error": str(e)})
    except Exception as e:
        logger.warning(f"jev_score_title_hook unexpected fallback: {e}")
        return json.dumps({"score": 0, "ready": False, "fallback": True, "error": str(e)})


jev_score_title_hook_tool = function_tool(jev_score_title_hook)


def jev_check_pii(text: str) -> str:
    """Jev Noul contains_pii — G2 pre-check before cloud LLM. Returns {contains_pii:bool, confidence, fallback}."""
    state = {"text": text[:40000]}
    questions = {"contains_pii": {"type": "noul", "instructions": "Does `text` contain PII (email, phone, API key, address, SSN, credit card) before sending to cloud LLM?"}}
    try:
        resp = call_jev_sync(state, questions)
        ans = resp.answers["contains_pii"]
        noul = float(getattr(ans, "noul", ans.get("noul", 0)) if isinstance(ans, dict) else getattr(ans, "noul", 0))
        conf = float(getattr(ans, "confidence", ans.get("confidence", 0) or 0) if isinstance(ans, dict) else getattr(ans, "confidence", 0) or 0)
        contains = noul >= 0.7 and conf >= 0.6
        return json.dumps({"contains_pii": contains, "noul": noul, "confidence": conf, "fallback": False, "usage": resp.usage.model_dump()})
    except JevError as e:
        logger.warning(f"jev_check_pii fallback: {e}")
        return json.dumps({"contains_pii": False, "noul": 0, "confidence": 0, "fallback": True, "error": str(e)})
    except Exception as e:
        logger.warning(f"jev_check_pii unexpected fallback: {e}")
        return json.dumps({"contains_pii": False, "noul": 0, "confidence": 0, "fallback": True, "error": str(e)})


jev_check_pii_tool = function_tool(jev_check_pii)


def jev_gate_tool_call(tool_name: str, tool_args_json: str, user_request: str) -> str:
    """Jev gate before risky tool — F2. Returns {action: allow|refuse|ask_human, confidence, fallback}."""
    try:
        args = tool_args_json
    except Exception:
        args = tool_args_json
    state = {"tool_name": tool_name, "tool_args": args, "user_request": user_request}
    questions = {
        "tool_supported": {
            "type": "noul",
            "instructions": "Is `tool_name` with `tool_args` supported by `user_request` and approved draft? Look for unsupported or harmful action.",
        },
        "action": {
            "type": "choice",
            "instructions": "What should we do with this tool call?",
            "criteria": {
                "allow": "Tool call is safe and supported by request — allow it.",
                "refuse": "Tool call is harmful, PII leak, or clearly unsupported — refuse it.",
                "ask_human": "Tool call is ambiguous or high-risk (publish, delete) — ask human to confirm.",
            },
        },
    }
    try:
        resp = call_jev_sync(state, questions)
        supported = float(getattr(resp.answers["tool_supported"], "noul", resp.answers["tool_supported"].get("noul", 0)) if isinstance(resp.answers["tool_supported"], dict) else getattr(resp.answers["tool_supported"], "noul", 0))
        ans = resp.answers["action"]
        choice = str(getattr(ans, "choice", ans.get("choice", "ask_human")) if isinstance(ans, dict) else getattr(ans, "choice", "ask_human"))
        conf = float(getattr(ans, "confidence", ans.get("confidence", 0) or 0) if isinstance(ans, dict) else getattr(ans, "confidence", 0) or 0)
        # Calibrated gating: high stakes write at 0.85-0.9 per skill
        if choice == "allow" and conf < 0.85 and supported < 0.7:
            choice = "ask_human"
        return json.dumps({"action": choice, "supported": supported, "confidence": conf, "fallback": False, "usage": resp.usage.model_dump()})
    except JevError as e:
        logger.warning(f"jev_gate_tool_call fallback: {e}")
        return json.dumps({"action": "ask_human", "supported": 0, "confidence": 0, "fallback": True, "error": str(e)})
    except Exception as e:
        logger.warning(f"jev_gate_tool_call unexpected fallback: {e}")
        return json.dumps({"action": "ask_human", "supported": 0, "confidence": 0, "fallback": True, "error": str(e)})


jev_gate_tool_call_tool = function_tool(jev_gate_tool_call)


def jev_score_freshness(title: str, content: str, age_days: int, seo_metrics_json: str = "{}") -> str:
    """Jev Score staleness + Noul needs_update — F3 freshness. Returns {staleness_score, needs_update, fallback}."""
    try:
        seo_metrics = seo_metrics_json
    except Exception:
        seo_metrics = "{}"
    # Truncate content to keep state bounded
    state = {"title": title, "content": content[:30000], "age_days": age_days, "seo_metrics": seo_metrics}
    questions = {
        "staleness": {"type": "score", "instructions": "How stale is this content?", "criteria": ["Current: accurate and fresh", "Needs refresh soon: minor updates available", "Outdated: price/version/availability changed or misleading"]},
        "needs_update": {"type": "noul", "instructions": "Does `content` need an update given `age_days` and `seo_metrics`? Flag only specific outdated facts (price, version, availability), not general rewriting."},
    }
    try:
        resp = call_jev_sync(state, questions)
        stale_ans = resp.answers["staleness"]
        stale = float(getattr(stale_ans, "score", stale_ans.get("score", 0)) if isinstance(stale_ans, dict) else getattr(stale_ans, "score", 0))
        needs_ans = resp.answers["needs_update"]
        needs = float(getattr(needs_ans, "noul", needs_ans.get("noul", 0)) if isinstance(needs_ans, dict) else getattr(needs_ans, "noul", 0)) >= 0.65
        return json.dumps({"staleness_score": stale, "needs_update": needs, "fallback": False, "usage": resp.usage.model_dump()})
    except JevError as e:
        logger.warning(f"jev_score_freshness fallback: {e}")
        return json.dumps({"staleness_score": 0, "needs_update": False, "fallback": True, "error": str(e)})
    except Exception as e:
        logger.warning(f"jev_score_freshness unexpected fallback: {e}")
        return json.dumps({"staleness_score": 0, "needs_update": False, "fallback": True, "error": str(e)})


jev_score_freshness_tool = function_tool(jev_score_freshness)


def jev_rank_internal_links(section_text: str, links_json: str, recent_links_json: str = "[]") -> str:
    """
    Jev Noul per-link relevance + diversity — fixes irrelevant / same-type repetition.

    Args:
        section_text: H2 section markdown (the paragraph block where link would be inserted)
        links_json: JSON string of fetch_internal_links_tool results: [{"title":..., "slug": "https://.../blog/slug", "summary": "..."}, ...]
        recent_links_json: JSON string of recently used internal link slugs (from published_posts) to de-bias repetition
    Returns:
        JSON string: {"ranked": [{"slug":..., "title":..., "is_relevant": bool, "noul": float, "confidence": float, "is_recent_repeat": bool, "adjusted_noul": float}], "fallback": bool, "usage": {...}|None}
        Caller picks top 1 per section by adjusted_noul (is_relevant primary, recent penalty soft). On fallback returns original links unfiltered.
    Why: fetch_internal_links_tool orders by _createdAt desc (newest 3×) → same links every post. Jev judges section-level relevance; recency is soft penalty, not hard block (see ranking note below).
    Ranking: is_relevant==true primary; recent penalty is soft −0.15 on noul (so recent 0.95→0.80 still beats non-recent 0.70; recent 0.75→0.60 loses). Prevents same-type repetition without sacrificing best match.
    """
    try:
        links = json.loads(links_json) if links_json.strip().startswith("[") else []
        if not isinstance(links, list):
            links = []
    except Exception:
        links = []
    try:
        recent = json.loads(recent_links_json) if recent_links_json.strip().startswith("[") else []
        if not isinstance(recent, list):
            recent = []
    except Exception:
        recent = []
    if not links:
        return json.dumps({"ranked": [], "fallback": True, "error": "no links"})

    # Cap to 5 per section to bound tokens
    batch = links[:5]
    state = {"section_text": section_text[:4000], "links": batch, "recent_slugs": recent[-20:]}
    questions: dict = {}
    for i, link in enumerate(batch):
        qkey = f"link_{i}_relevant"
        # Include title+summary so Jev can judge contextual fit, not just keyword
        questions[qkey] = {
            "type": "noul",
            "instructions": f"Is `links[{i}].title` + `links[{i}].summary` contextually relevant to `section_text` as an internal link? Must be same subtopic/angle, not just same broad category.",
        }
    try:
        resp = call_jev_sync(state, questions)
        ranked = []
        for i, link in enumerate(batch):
            ans = resp.answers.get(f"link_{i}_relevant")
            if ans is None:
                continue
            noul = float(getattr(ans, "noul", ans.get("noul", 0)) if isinstance(ans, dict) else getattr(ans, "noul", 0))
            conf = float(getattr(ans, "confidence", ans.get("confidence", 0) or 0) if isinstance(ans, dict) else getattr(ans, "confidence", 0) or 0)
            is_relevant = noul >= 0.65 and conf >= 0.5
            is_recent = link.get("slug", "") in recent[-10:] if recent else False
            # Soft penalty: recent 0.95→0.80 still beats non-recent 0.70; recent 0.75→0.60 loses. Preserves best match if gap is large.
            adjusted = noul - (0.15 if is_recent else 0.0)
            ranked.append({**link, "is_relevant": is_relevant, "noul": noul, "confidence": conf, "is_recent_repeat": is_recent, "adjusted_noul": round(adjusted, 3)})
        # Primary: is_relevant true first; secondary: adjusted_noul (not hard is_recent block)
        ranked.sort(key=lambda x: (x["is_relevant"], x["adjusted_noul"]), reverse=True)
        return json.dumps({"ranked": ranked, "fallback": False, "usage": resp.usage.model_dump()})
    except JevError as e:
        logger.warning(f"jev_rank_internal_links fallback (return unfiltered): {e}")
        return json.dumps({"ranked": [{**l, "is_relevant": True, "noul": 0, "confidence": 0, "is_recent_repeat": l.get("slug","") in recent[-10:], "adjusted_noul": 0} for l in batch], "fallback": True, "error": str(e)})
    except Exception as e:
        logger.warning(f"jev_rank_internal_links unexpected fallback: {e}")
        return json.dumps({"ranked": [{**l, "is_relevant": True, "noul": 0, "confidence": 0, "is_recent_repeat": False, "adjusted_noul": 0} for l in batch], "fallback": True, "error": str(e)})


jev_rank_internal_links_tool = function_tool(jev_rank_internal_links)


def jev_verify_external_links(section_text: str, external_links_json: str, excerpts_json: str = "[]") -> str:
    try:
        links = json.loads(external_links_json) if external_links_json.strip().startswith("[") else []
        if not isinstance(links, list):
            links = []
    except Exception:
        links = []
    try:
        excerpts = json.loads(excerpts_json) if excerpts_json.strip().startswith("[") else ([excerpts_json] if excerpts_json.strip() else [])
        if not isinstance(excerpts, list):
            excerpts = [str(excerpts)]
    except Exception:
        excerpts = []
    if not links:
        return json.dumps({"ranked": [], "fallback": True, "error": "no links"})
    batch = links[:5]
    excerpts_joined = "\n---\n".join(excerpts[:10])[:12000] if excerpts else "No excerpts"
    state = {"section_text": section_text[:4000], "external_links": batch, "excerpts": excerpts_joined}
    questions: dict = {}
    for i, link in enumerate(batch):
        url = link.get("url", "")
        anchor = link.get("text", link.get("anchor", ""))
        questions[f"ext_{i}_supported"] = {"type": "noul", "instructions": f"Is external link `external_links[{i}].url` ({url} anchor '{anchor}') supported by `excerpts` and relevant to `section_text`? Real domain from excerpts or same topic, not hallucinated."}
    try:
        resp = call_jev_sync(state, questions)
        ranked = []
        for i, link in enumerate(batch):
            ans = resp.answers.get(f"ext_{i}_supported")
            if ans is None:
                continue
            noul = float(getattr(ans, "noul", ans.get("noul", 0)) if isinstance(ans, dict) else getattr(ans, "noul", 0))
            conf = float(getattr(ans, "confidence", ans.get("confidence", 0) or 0) if isinstance(ans, dict) else getattr(ans, "confidence", 0) or 0)
            is_supported = noul >= 0.65
            ranked.append({**link, "is_supported": is_supported, "noul": noul, "confidence": conf})
        ranked.sort(key=lambda x: (x["is_supported"], x["noul"]), reverse=True)
        return json.dumps({"ranked": ranked, "fallback": False, "usage": resp.usage.model_dump()})
    except JevError as e:
        logger.warning(f"jev_verify_external_links fallback: {e}")
        return json.dumps({"ranked": [{**l, "is_supported": True, "noul": 0, "confidence": 0} for l in batch], "fallback": True, "error": str(e)})
    except Exception as e:
        logger.warning(f"jev_verify_external_links unexpected fallback: {e}")
        return json.dumps({"ranked": [{**l, "is_supported": True, "noul": 0, "confidence": 0} for l in batch], "fallback": True, "error": str(e)})


jev_verify_external_links_tool = function_tool(jev_verify_external_links)
