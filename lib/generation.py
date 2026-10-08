"""§5.5/§5.13 real generation behind generate_article — PURE helpers.

Brief composition (template + ledger research + submitted brief), prompt
rendering for content_generator_agent, and agent-output parsing (JSON
envelope with lenient/fenced parsing, plus raw-Markdown salvage mirroring
the proven paths in scripts/run_stage.py). No LLM calls, nothing raises —
the runner lives in blog_agent/generation.py and the orchestration (status
transitions, persistence, audit) lives in sdk/service.generate_content.
"""
from __future__ import annotations

import json
import re
from datetime import datetime, timezone

from lib.brief_templates import template_for, template_text, word_floor_for
from lib.run_result_utils import loads_lenient

# Same turn budget as the content stage in scripts/run_stage.py.
MAX_TURNS = 30

# Envelope keys content_generator_agent is instructed to return (examples in
# its instructions); parsing matches keys leniently (case/spacing-insensitive)
# because fallback models re-case them — confirmed live in run_stage.
ENVELOPE_STATUS_KEY = "status"
CONTENT_KEYS = ("Generated Content", "Title", "Summary", "FAQs",
                "Quality Score", "Claims Notes")

_JSON_FENCE_RE = re.compile(r"```(?:json)?\s*(\{.*\})\s*```", re.DOTALL)
_TITLE_HEADING_RE = re.compile(r"^#{1,3}\s+(.+?)\s*\n", re.MULTILINE)
_SUMMARY_LABEL_RE = re.compile(
    r"^\*\*(?:Meta Description|Summary)\*\*:?\s*(.+)$", re.MULTILINE | re.IGNORECASE)
_FAQ_JSON_RE = re.compile(r"\[\s*\{.*?\"question\".*?\}\s*\]", re.DOTALL)
_FAQ_LABEL_RE = re.compile(r"^(?:#{2,3}\s*FAQs?|\*\*FAQs?\*\*)\s*$",
                           re.MULTILINE | re.IGNORECASE)
_SECTION_BREAK_RE = re.compile(r"^(?:#{2,3}\s+.+|\*\*[A-Z][a-zA-Z ]*\*\*:?)\s*$",
                               re.MULTILINE)
_FAQ_PAIR_RE = re.compile(r"\*\*(.+?)\*\*\s*\n(.+?)(?=\n\*\*|\Z)", re.DOTALL)
_TRAILING_RULE_RE = re.compile(r"\n-{3,}\s*\n")

_MIN_BODY_CHARS = 200


def get_field(d: dict, name: str, default: str = "") -> str | dict | list | None:
    """Lenient field lookup: prompt examples show exact key casing ("Generated
    Content") but fallback models return "generated_content" or nest fields
    under a "data"/"result" wrapper — match after stripping case and
    non-alphanumerics, then one level into dict-valued fields.
    Mirrors _get_field in scripts/run_stage.py (confirmed live shapes)."""
    if not isinstance(d, dict):
        return default

    def norm(key: str) -> str:
        return re.sub(r"[^a-z0-9]", "", str(key).lower())

    target = norm(name)
    for key, value in d.items():
        if norm(key) == target:
            return value
    for value in d.values():
        if isinstance(value, dict):
            for nested_key, nested_value in value.items():
                if norm(nested_key) == target:
                    return nested_value
    return default


def parse_faqs(raw) -> list[dict] | None:
    """FAQs arrive as a JSON string or a list of {question, answer}; normalize
    to a list or None. Never raises."""
    if not raw:
        return None
    if isinstance(raw, str):
        text = raw.strip()
        if not text:
            return None
        try:
            raw = json.loads(text)
        except (ValueError, TypeError):
            return None
    if isinstance(raw, dict):
        raw = [raw]
    if not isinstance(raw, list):
        return None
    items = [f for f in raw
             if isinstance(f, dict) and f.get("question") and f.get("answer")]
    return items or None


def parse_score(raw) -> float | None:
    """'Quality Score' as int/str/'85/100'/'85.5' -> float, else None."""
    if raw is None or raw == "":
        return None
    if isinstance(raw, (int, float)):
        return float(raw)
    m = re.search(r"\d+(?:\.\d+)?", str(raw))
    return float(m.group()) if m else None


def build_brief_payload(*, keyword: str, intent: str = "",
                        brief_meta: dict | None = None,
                        research_snapshot: str = "",
                        volume=None, difficulty=None) -> dict:
    """Compose the generation brief in-memory from what the Article has:
    the submitted brief dict (§5.12, often just a title), the ledger row's
    research (§5.16), and the deterministic intent template (§5.16). When no
    hand-written brief exists, the template still gives the agent the
    required structure so output shape stays stable."""
    meta = brief_meta or {}
    parts: list[str] = [f"# {keyword}" if keyword else "# Untitled"]
    description = str(meta.get("description") or "").strip()
    if description:
        parts.append(description)
    for key in ("brief_content", "content", "sections", "outline"):
        body = meta.get(key)
        if isinstance(body, str) and body.strip():
            parts.append(body.strip())
            break
    research: list[str] = []
    if volume is not None:
        research.append(f"- Search volume: {volume}")
    if difficulty is not None:
        research.append(f"- Difficulty: {difficulty}")
    if research_snapshot:
        research.append(f"- Research snapshot: {str(research_snapshot).strip()}")
    if research:
        parts.append("Research:\n" + "\n".join(research))
    # Deterministic structure contract for the intent (§5.16).
    parts.append(template_text(intent))
    brief_markdown = "\n\n".join(p for p in parts if p)

    sources = meta.get("sources") or meta.get("external_source_links") or meta.get("links") or []
    if not isinstance(sources, list):
        sources = [sources] if sources else []
    faqs = parse_faqs(meta.get("faqs")) or []
    internal_links = meta.get("internal_links") or []
    if not isinstance(internal_links, list):
        internal_links = []
    return {
        "keyword": keyword,
        "intent": intent,
        "brief_markdown": brief_markdown,
        "faqs": faqs,
        "sources": sources,
        "summary": str(meta.get("summary") or description or "").strip(),
        "template_intent": intent,
        # Link graph for the article path: real candidates the publisher
        # supplied (or service enrichment found on the WP site). Rendered
        # as hard requirements by render_prompt; never invent URLs.
        "internal_links": internal_links,
        "site_base_url": str(meta.get("site_base_url") or "").strip(),
    }


def render_prompt(brief: dict) -> str:
    """Turn-level prompt for content_generator_agent.

    The agent's own instructions are sheet-centric (find the brief in
    content_briefs, append to generated_posts). This prompt overrides that
    for the Article path: the brief is embedded here, and the orchestrator
    (service.generate_content) persists the envelope — no worksheet reads
    or writes are needed for this run.

    Also carries the deterministic gates the checks in service._content_checks
    enforce (intent-aware word floor, current year, internal/external links,
    Bottom Line), so a single-shot model has everything it needs in one message."""
    payload = json.dumps(brief, ensure_ascii=False, default=str)
    today = datetime.now(timezone.utc)
    year = today.year
    intent = str(brief.get("template_intent") or brief.get("intent") or "")
    min_words = word_floor_for(intent)
    target = str(template_for(intent).get("word_target", "1500-2500"))
    internal_links = brief.get("internal_links") or []
    sources = brief.get("sources") or []
    site_base = str(brief.get("site_base_url") or "").strip()
    revision_feedback = brief.get("revision_feedback") or []

    lines = [
        "Generate ONE complete blog post for the brief below.",
        "",
        "IMPORTANT — Article-path overrides (this run):",
        "- The brief is provided in this message. Do NOT call "
        "manage_sheet_data_tool / find_row_by_key to look up content_briefs "
        "— there is nothing to find; work only from the JSON below.",
        "- Do NOT append to any worksheet (no generated_posts, no "
        "content_briefs writes). The orchestrator persists your result; a "
        "worksheet write is unnecessary for this run.",
        "- Follow the rest of your instructions (author context, brain "
        "notes, tactics pack, TL;DR block, question-form H2s, Sources box, "
        "anti-AI-pattern checklist).",
        "",
        "HARD REQUIREMENTS (checked deterministically after you return):",
        f"- TODAY IS {today.strftime('%d %B %Y')}. The current year is "
        f"{year}. Never write the post as if it belongs to a past year: "
        f"no \"in {year - 1}\" (or older) in the title, headings, or body "
        f"unless quoting a historical event with an explicit date.",
        f"- Length: at least {min_words} words (this brief's intent targets "
        f"{target} — length matches intent; a flagship informational post "
        "should aim 1500-2500). Short drafts are rejected and re-run.",
        "- Structure: TL;DR near the top (first ~800 chars), `## Sources` "
        "as the LAST section, 3+ FAQs, question-form H2s.",
        "- Close with a `## Bottom Line` section (60-100 words) placed "
        "immediately BEFORE `## Sources`: a decisive verdict/answer that "
        "summarizes the takeaway and includes 1-2 of the internal links "
        "below — this is what a reader who stops at the summary still "
        "gets (and where they go next).",
    ]
    if internal_links:
        lines.append(
            f"- INTERNAL LINKS: weave at least 3 of these REAL URLs into "
            f"the body prose (not a link list) as natural anchors "
            f"(e.g. \"see our {site_base or 'related'} guide\"):\n"
            + "\n".join(f"  - {l.get('title', '')}: {l.get('url', '')}"
                        for l in internal_links if isinstance(l, dict))
            + "\n  Never invent internal URLs. Anchor text should read "
            "naturally and mention the target topic."
        )
    else:
        lines.append("- INTERNAL LINKS: none were supplied — do NOT invent "
                     "site URLs (broken links are a publish blocker).")
    if sources:
        lines.append(
            f"- EXTERNAL SOURCES: cite at least 1 of the brief's sources "
            "NATURALLY IN THE BODY PROSE (a sentence that links to it while "
            "making the point), not only in the `## Sources` list:\n"
            + "\n".join(f"  - {s}" if isinstance(s, str)
                        else f"  - {s.get('title', s.get('url', ''))}: "
                             f"{s.get('url', '')}"
                        for s in sources)
        )
    if revision_feedback:
        lines += [
            "",
            "PREVIOUS DRAFT FAILED THESE CHECKS — fix every one:",
            *[f"- {fb}" for fb in revision_feedback],
        ]
    lines += [
        "",
        "Return ONLY the JSON envelope (no prose before/after):",
        '{"status": "success", "Title": "...", "Generated Content": "<full '
        'markdown body, NO H1 — Title is the H1>", "Summary": "<50-160 '
        'chars, meta description>", "FAQs": "<JSON string array of '
        '{question, answer} pairs, 5-7>", "Quality Score": "<0-100>", '
        '"Claims Notes": "...", "errors": [], "warnings": []}',
        "",
        f"BRIEF (JSON):\n{payload}",
    ]
    return "\n".join(lines)


def parse_generation_output(output) -> dict | None:
    """Agent output -> envelope dict, or None when nothing is salvageable.
    Accepts: an already-parsed dict, a JSON envelope (raw or ```json
    fenced, lenient about raw newlines inside string values), or raw
    Markdown of a full post (fallback models skip the envelope — the same
    confirmed-live shapes scripts/run_stage.py salvages)."""
    if isinstance(output, dict):
        return output
    if not isinstance(output, str) or not output.strip():
        return None
    text = output.strip()
    fence = _JSON_FENCE_RE.search(text)
    parsed = loads_lenient(fence.group(1) if fence else text)
    if isinstance(parsed, dict):
        return parsed
    return _salvage_markdown_post(text)


def _salvage_markdown_post(text: str) -> dict | None:
    """Recover {Title, Generated Content, Summary, FAQs} from a raw Markdown
    post. Too-short/no-title outputs fall through as failures."""
    if not text.startswith("#"):
        return None
    title_match = _TITLE_HEADING_RE.match(text)
    if not title_match:
        return None
    title = title_match.group(1).strip()
    body = text[title_match.end():]

    summary = ""
    summary_match = _SUMMARY_LABEL_RE.search(body)
    if summary_match:
        summary = summary_match.group(1).strip()
        body = body[:summary_match.start()] + body[summary_match.end():]

    faqs: list[dict] = []
    json_match = _FAQ_JSON_RE.search(body)
    if json_match:
        candidate = loads_lenient(json_match.group(0))
        if isinstance(candidate, list) and candidate and all(
                isinstance(item, dict) and "question" in item and "answer" in item
                for item in candidate):
            faqs = candidate
            body = body[:json_match.start()] + body[json_match.end():]

    faq_label_match = _FAQ_LABEL_RE.search(body)
    if faq_label_match:
        if faqs:
            body = body[:faq_label_match.start()] + body[faq_label_match.end():]
        else:
            section_start = faq_label_match.end()
            next_section_match = _SECTION_BREAK_RE.search(body, section_start)
            section_end = next_section_match.start() if next_section_match else len(body)
            for question, answer in _FAQ_PAIR_RE.findall(body[section_start:section_end]):
                question = question.strip().strip("*").strip()
                answer = " ".join(answer.strip().splitlines()).strip()
                if question and answer:
                    faqs.append({"question": question, "answer": answer})
            body = body[:faq_label_match.start()] + body[section_end:]

    body = _TRAILING_RULE_RE.sub("\n", body)
    body = re.sub(r"\n{3,}", "\n\n", body).strip()
    if not title or len(body) < _MIN_BODY_CHARS:
        return None
    if not summary:
        plain_intro = re.sub(r"^#{2,3}\s+.+$", "", body, count=1, flags=re.MULTILINE)
        plain_intro = re.sub(r"[#*_`\[\]()]", "", plain_intro).strip()
        plain_intro = re.sub(r"\s+", " ", plain_intro)
        summary = plain_intro[:160].rsplit(" ", 1)[0] if len(plain_intro) > 160 else plain_intro
    return {
        "status": "success",
        "Title": title,
        "Generated Content": body,
        "Summary": summary,
        "FAQs": faqs,
        "Quality Score": "",
    }
