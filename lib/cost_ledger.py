"""§5.10-6 Per-post cost ledger.

Every article carries its full input cost (LLM + images + data).
Shown to the operator in Phase 1; becomes the Phase 2 "radical
transparency" customer feature. No LLM calls.
"""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from lib.db import CostLedger

KINDS = ("llm", "image", "data")


def record_cost(session: Session, article_id: int, kind: str, amount_usd: float, detail: dict | None = None) -> CostLedger:
    if kind not in (*KINDS, "total"):
        raise ValueError(f"unknown cost kind: {kind}")
    row = CostLedger(article_id=article_id, kind=kind, amount_usd=float(amount_usd), detail=detail or {})
    session.add(row)
    session.commit()
    session.refresh(row)
    return row


def article_total(session: Session, article_id: int) -> dict:
    rows = list(session.execute(select(CostLedger).where(CostLedger.article_id == article_id)).scalars())
    by_kind: dict[str, float] = {}
    for r in rows:
        if r.kind == "total":
            continue
        by_kind[r.kind] = by_kind.get(r.kind, 0.0) + r.amount_usd
    total = round(sum(by_kind.values()), 4)
    return {"by_kind": by_kind, "total_usd": total}


def record_article_costs(session: Session, article_id: int, by_kind: dict) -> dict:
    """Record several cost kinds at once, then return the running total."""
    for kind, amount in (by_kind or {}).items():
        record_cost(session, article_id, kind, float(amount))
    return article_total(session, article_id)


def finalize(session: Session, article_id: int) -> dict:
    """Write/update the per-post `total` row (§5.10-6). Idempotent."""
    totals = article_total(session, article_id)
    row = session.execute(
        select(CostLedger).where(
            CostLedger.article_id == article_id, CostLedger.kind == "total")
    ).scalars().first()
    if row is None:
        row = CostLedger(article_id=article_id, kind="total",
                         amount_usd=totals["total_usd"], detail=totals["by_kind"])
        session.add(row)
    else:
        row.amount_usd = totals["total_usd"]
        row.detail = totals["by_kind"]
    session.commit()
    session.refresh(row)
    return totals
