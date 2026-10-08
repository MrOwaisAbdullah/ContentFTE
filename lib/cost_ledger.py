"""§5.10-6 Per-post cost ledger.

Every article carries its full input cost (LLM + images + data).
Shown to the operator in Phase 1; becomes the Phase 2 "radical
transparency" customer feature. No LLM calls.
"""
from __future__ import annotations

import os

from sqlalchemy import select
from sqlalchemy.orm import Session

from lib.db import CostLedger

KINDS = ("llm", "image", "data")

# USD per 1M tokens (input, output) for the router's model families —
# approximate list prices, env-tunable below. Substring match on the model
# id(s) the run reported; unknown models fall back to the *_DEFAULT env
# values (or these mid-tier estimates) and the detail records which price
# source was used, so the ledger is honest about being an estimate.
LLM_PRICES_USD_PER_MTOK: list[tuple[str, float, float]] = [
    ("gemini-3.5-flash-lite", 0.10, 0.40),
    ("gemini-3.6-flash", 0.30, 2.50),
    ("gemini-3.5-flash", 0.30, 2.50),
    ("gemini-flash", 0.30, 2.50),
    ("deepseek-v4", 0.27, 1.10),
    ("deepseek-chat", 0.27, 1.10),
    ("gpt-5-mini", 0.25, 2.00),
    ("gpt-4o-mini", 0.15, 0.60),
    ("claude-haiku", 0.80, 4.00),
    ("llama-3.3-70b", 0.10, 0.10),
]


def _default_prices() -> tuple[float, float]:
    try:
        din = float(os.environ.get("LLM_PRICE_INPUT_PER_M") or "")
    except ValueError:
        din = 0.10
    try:
        dout = float(os.environ.get("LLM_PRICE_OUTPUT_PER_M") or "")
    except ValueError:
        dout = 0.40
    return din, dout


def usage_cost(usage: dict) -> tuple[float, dict]:
    """Price a token-usage dict ({input_tokens, output_tokens, models?}).

    Returns (usd, detail) — detail records tokens, matched price source and
    the rates, so a ledger row is auditable. Unknown/absent models use the
    default estimate; zero-token usage prices to 0."""
    in_tok = int((usage or {}).get("input_tokens") or 0)
    out_tok = int((usage or {}).get("output_tokens") or 0)
    if in_tok <= 0 and out_tok <= 0:
        return 0.0, {}
    models = [str(m) for m in ((usage or {}).get("models") or [])]
    rate_in = rate_out = None
    source = "default-estimate"
    for model in models:
        low = model.lower()
        for prefix, pin, pout in LLM_PRICES_USD_PER_MTOK:
            if prefix in low:
                rate_in, rate_out = pin, pout
                source = prefix
                break
        if rate_in is not None:
            break
    if rate_in is None:
        rate_in, rate_out = _default_prices()
    usd = (in_tok / 1_000_000.0) * rate_in + (out_tok / 1_000_000.0) * rate_out
    detail = {
        "input_tokens": in_tok,
        "output_tokens": out_tok,
        "models": models,
        "price_source": source,
        "usd_per_mtok_input": rate_in,
        "usd_per_mtok_output": rate_out,
        "estimate": True,
    }
    return round(usd, 6), detail


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
