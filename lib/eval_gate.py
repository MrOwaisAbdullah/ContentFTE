"""§5.2 Quality-gate hardening — structured eval, sub-score floor, audit.

- Eval report: overall + sub-scores (accuracy, depth, seo, voice,
  originality, citability). Any sub-score <80 blocks publish even if
  overall ≥90.
- Falsifiable guidance: every critic recommendation must carry (a)
  observation, (b) "how would we know this failed?", (c) leading
  indicator. Guidance without it is rejected → regenerated.
- Audit row for every publish decision (scores, models, tokens, cost,
  revision count). No LLM calls here.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field

from sqlalchemy.orm import Session

from lib.db import AuditLog

SUB_SCORES = ("accuracy", "depth", "seo", "voice", "originality", "citability")
PUBLISH_THRESHOLD = 90
SUB_SCORE_FLOOR = 80


@dataclass
class EvalReport:
    overall: int
    sub_scores: dict = field(default_factory=dict)
    guidance: list[dict] = field(default_factory=list)
    model_ids: dict = field(default_factory=dict)
    token_usage: dict = field(default_factory=dict)
    cost_usd: float = 0.0
    revision_count: int = 0


def computed_overall(sub_scores: dict) -> int | None:
    """Mean of the six sub-scores, or None unless all six are present and numeric."""
    try:
        vals = [float(sub_scores[k]) for k in SUB_SCORES]
    except (KeyError, TypeError, ValueError):
        return None
    return int(round(sum(vals) / len(vals)))


def overall_tolerance() -> int:
    """How far above the mean of its sub-scores the evaluator's own overall may sit (EVAL_OVERALL_TOLERANCE,
    default 5). 0 = the overall IS the mean. The rubric never defined the overall as a formula, so a little
    slack is allowed; a 94 on top of sub-scores that average 82 is not."""
    try:
        return max(0, int(os.getenv("EVAL_OVERALL_TOLERANCE", "5")))
    except ValueError:
        return 5


def effective_overall(report: EvalReport) -> int:
    """The overall the gate uses: the evaluator's own figure, capped at (mean of the six sub-scores +
    tolerance) whenever all six were recorded.

    The overall used to be whatever the model wrote, so a draft with an 82 floor everywhere could be
    reported as 94 and sail through the >=90 gate (SEO-09). The sub-scores are the evidence."""
    mean = computed_overall(report.sub_scores)
    return int(report.overall) if mean is None else min(int(report.overall), mean + overall_tolerance())


def check_gate(report: EvalReport) -> dict:
    """Returns {publish: bool, reasons: [...]}. Pure function."""
    reasons: list[str] = []
    overall = effective_overall(report)
    if overall < PUBLISH_THRESHOLD:
        if overall < report.overall:
            reasons.append(f"overall {overall} < {PUBLISH_THRESHOLD} (reported {report.overall}, but the "
                           f"sub-scores average {computed_overall(report.sub_scores)})")
        else:
            reasons.append(f"overall {overall} < {PUBLISH_THRESHOLD}")
    for name in SUB_SCORES:
        score = report.sub_scores.get(name)
        if score is None:
            reasons.append(f"missing sub-score: {name}")
        elif score < SUB_SCORE_FLOOR:
            reasons.append(f"sub-score {name}={score} < floor {SUB_SCORE_FLOOR}")
    bad_guidance = [g for g in report.guidance if not is_falsifiable(g)]
    if bad_guidance:
        reasons.append(f"{len(bad_guidance)} guidance item(s) lack falsifiability → regenerate")
    return {"publish": not reasons, "reasons": reasons}


def is_falsifiable(guidance: dict) -> bool:
    """Guidance needs observation + fail-check + leading indicator."""
    return bool(
        str(guidance.get("observation", "")).strip()
        and str(guidance.get("fail_check", "")).strip()
        and str(guidance.get("leading_indicator", "")).strip()
    )


def write_audit(
    session: Session,
    action: str,
    report: EvalReport,
    article_id: int | None = None,
    site_id: int | None = None,
) -> AuditLog:
    row = AuditLog(
        article_id=article_id,
        site_id=site_id,
        action=action,
        payload={
            "overall": report.overall,
            "sub_scores": report.sub_scores,
            "guidance": report.guidance,
            "model_ids": report.model_ids,
            "token_usage": report.token_usage,
            "cost_usd": report.cost_usd,
            "revision_count": report.revision_count,
            "gate": check_gate(report),
        },
    )
    session.add(row)
    session.commit()
    session.refresh(row)
    return row
