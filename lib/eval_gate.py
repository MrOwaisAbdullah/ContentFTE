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


def check_gate(report: EvalReport) -> dict:
    """Returns {publish: bool, reasons: [...]}. Pure function."""
    reasons: list[str] = []
    if report.overall < PUBLISH_THRESHOLD:
        reasons.append(f"overall {report.overall} < {PUBLISH_THRESHOLD}")
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
