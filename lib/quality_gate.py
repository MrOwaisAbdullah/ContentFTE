"""One deterministic quality gate that actually runs (plan SEO-01 / SEO-02 / SEO-24).

Before this, the pieces existed but nothing called them: `lib/eval_gate.check_gate` had no
production caller (the evaluator prompt even claimed "the caller still enforces" it), the
fact-check was an LLM-optional tool, and link/AEO checks ran only inside WP publish. The
live article that scored 94 taught a wrong API.

`assess()` is a pure function over an article's stored content and meta. It returns:

    {"pass": bool,
     "blocking": ["<reason>", ...],     # approval is refused unless explicitly forced
     "warnings": ["<reason>", ...],     # shown to the approver, never block
     "checks":   {...structured detail per gate...},
     "assessed_at": iso8601}

What blocks (all provable, none a judgment call):
  * a failed deterministic draft check recorded at generation time (word floor, TL;DR,
    Sources, summary length, stale year, required keywords...);
  * fact-check: numeric/date claims the research on file does not support;
  * eval gate: when all six sub-scores were recorded, any below the floor / overall < 90;
  * (opt-in) broken external links.
What only warns: AEO lint findings, missing research/sub-scores (not enough data to judge),
overall score below 90 with no sub-scores, unverifiable (bot-blocked) links.
"""
from __future__ import annotations

import os
from datetime import datetime, timezone
from typing import Any, Callable, Iterable, Optional

from lib import aeo_lint
from lib.eval_gate import PUBLISH_THRESHOLD, SUB_SCORES, EvalReport, check_gate
from lib.factcheck import extract_claims, verify_claims

# Statuses where "can't tell if it's broken" is more likely than "it is broken".
from lib.link_validator import UNVERIFIABLE_STATUSES as _UNVERIFIABLE_STATUSES


def eval_required() -> bool:
    """QUALITY_GATE_REQUIRE_EVAL=1: an ENGINE-GENERATED article must carry the evaluator's six sub-scores to be
    approved. Off by default (articles written by hand, or imported, have none); turn it on once your pipeline
    records them, so a draft that skipped the evaluator cannot ride on a cheap classifier alone (PIPE-03)."""
    return os.environ.get("QUALITY_GATE_REQUIRE_EVAL", "").strip().lower() in ("1", "true", "yes", "on")


def links_check_enabled() -> bool:
    return os.environ.get("QUALITY_GATE_CHECK_LINKS", "").strip().lower() in ("1", "true", "yes", "on")


def _check_external_links(markdown: str, head_fn: Optional[Callable[[str], tuple]] = None) -> dict:
    """HEAD every external link. Internal links are skipped here (they are validated against
    the CMS during publish). 401/403/405/429/999 are 'unverifiable', not 'broken'."""
    from lib.link_validator import _head_ok, extract_markdown_links, _is_internal_url

    head = head_fn or (lambda u: _head_ok(u, timeout=8.0))
    broken, unverifiable, checked = [], [], 0
    for link in extract_markdown_links(markdown):
        url = link["url"]
        if _is_internal_url(url):
            continue
        checked += 1
        ok, status = head(url)
        if ok:
            continue
        (unverifiable if status in _UNVERIFIABLE_STATUSES else broken).append(
            {"url": url, "status": status})
    return {"checked": checked, "broken": broken, "unverifiable": unverifiable}


def assess(
    *,
    content_md: str,
    meta: Optional[dict] = None,
    source_excerpts: Optional[Iterable[str]] = None,
    faqs: Optional[list] = None,
    check_links: Optional[bool] = None,
    head_fn: Optional[Callable[[str], tuple]] = None,
    siblings: Optional[Iterable[tuple]] = None,
) -> dict:
    meta = meta if isinstance(meta, dict) else {}
    content_md = content_md or ""
    blocking: list[str] = []
    warnings: list[str] = []
    checks: dict[str, Any] = {}

    # 1) deterministic draft checks recorded when the article was generated
    stored = (meta.get("generation") or {}).get("checks")
    if isinstance(stored, dict) and stored:
        failed = {k: v for k, v in stored.items() if isinstance(v, dict) and not v.get("pass")}
        checks["draft"] = {"failed": sorted(failed), "total": len(stored)}
        for name, val in sorted(failed.items()):
            detail = ""
            if "value" in val and "need" in val:
                detail = f" ({val['value']} vs {val['need']} needed)"
            blocking.append(f"draft check '{name}' failed{detail}")
    else:
        checks["draft"] = {"skipped": "no generation checks recorded (not engine-generated)"}

    # 1b) near-duplicate of an article the site already has (scaled-content control, SEO-05).
    #     `siblings` = (id, title, markdown) of the site's other articles; the caller supplies them.
    if siblings is not None:
        from lib import similarity
        dupes = similarity.near_duplicates(content_md, siblings)
        checks["near_duplicate"] = {"matches": dupes, "threshold": similarity.DEFAULT_THRESHOLD}
        if dupes and dupes[0]["similarity"] >= similarity.DEFAULT_THRESHOLD:
            top = dupes[0]
            blocking.append(f"near-duplicate of article #{top['id']} '{top['title']}' "
                            f"({int(top['similarity'] * 100)}% of its phrasing is shared)")
        elif dupes:
            top = dupes[0]
            warnings.append(f"overlaps article #{top['id']} '{top['title']}' "
                            f"({int(top['similarity'] * 100)}% shared phrasing) - check it is not the same article")

    # 2) fact-check against the research on file
    excerpts = [e for e in (source_excerpts or []) if str(e).strip()]
    claims = extract_claims(content_md)
    if not claims:
        checks["factcheck"] = {"claims": 0, "pass": True}
    elif not excerpts:
        checks["factcheck"] = {"claims": len(claims), "skipped": "no research on file"}
        warnings.append(f"{len(claims)} numeric/date claim(s) could not be fact-checked: "
                        "no research is stored for this article")
    else:
        res = verify_claims(claims, excerpts)
        unv = res["unverified"]
        checks["factcheck"] = {"claims": len(claims), "unverified": len(unv), "pass": not unv,
                               "examples": [{"claim": c["claim"], "context": c["context"][:140]}
                                            for c in unv[:5]]}
        if unv:
            shown = ", ".join(f"'{c['claim']}'" for c in unv[:4])
            more = f" (+{len(unv) - 4} more)" if len(unv) > 4 else ""
            blocking.append(f"{len(unv)} claim(s) not supported by the research on file: {shown}{more}")

    # 3) eval gate — only enforceable when the sub-scores were actually recorded
    scores = meta.get("scores") if isinstance(meta.get("scores"), dict) else {}
    sub = scores.get("sub_scores") if isinstance(scores.get("sub_scores"), dict) else {}
    overall = scores.get("overall", scores.get("quality"))
    if sub and all(k in sub for k in SUB_SCORES) and overall is not None:
        verdict = check_gate(EvalReport(overall=int(overall), sub_scores=dict(sub)))
        checks["eval"] = {"pass": verdict["publish"], "overall": overall, "reasons": verdict["reasons"]}
        blocking.extend(f"eval gate: {r}" for r in verdict["reasons"])
    else:
        checks["eval"] = {"skipped": "sub-scores not recorded", "overall": overall}
        if eval_required() and isinstance(meta.get("generation"), dict):
            blocking.append("no evaluator sub-scores were recorded for this engine-generated article "
                            "(the evaluation step was skipped); run the evaluation before approving")
        if overall is not None and float(overall) < PUBLISH_THRESHOLD:
            warnings.append(f"overall quality {overall} is below {PUBLISH_THRESHOLD} "
                            "(sub-scores weren't recorded, so the floor can't be enforced)")
        elif overall is None:
            warnings.append("no quality score recorded for this article")

    # 4) external links (network; opt-in)
    do_links = links_check_enabled() if check_links is None else check_links
    if do_links:
        lr = _check_external_links(content_md, head_fn)
        checks["links"] = lr
        if lr["broken"]:
            blocking.append(f"{len(lr['broken'])} broken external link(s): "
                            + ", ".join(b["url"] for b in lr["broken"][:3]))
        if lr["unverifiable"]:
            warnings.append(f"{len(lr['unverifiable'])} link(s) could not be verified (site blocks bots)")
    else:
        checks["links"] = {"skipped": "link check off (QUALITY_GATE_CHECK_LINKS=1 or check_links=True)"}

    # 5) AEO lint — advisory
    lint = aeo_lint.lint(content_md, faqs)
    checks["aeo"] = {"findings": len(lint)}
    warnings.extend(f"{f['id']}: {f['message']}" for f in lint)

    return {
        "pass": not blocking,
        "blocking": blocking,
        "warnings": warnings,
        "checks": checks,
        "assessed_at": datetime.now(timezone.utc).isoformat(),
    }
