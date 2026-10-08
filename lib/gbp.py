"""§5.9 GBP ↔ website consistency checker (playbook §9 "Factory-critical").

Checks that a site's public text (home page, about page, footer, etc.) is
consistent with the Google Business Profile (GBP) data supplied by the client.
Consistency covers NAP (name/address/phone), operating hours, and services
offered — the three Factory-critical fields per playbook §9.

The checker is pure (no network, no DB).  It returns a concise report
suitable for the audit log and the operator dashboard.
"""
from __future__ import annotations

import re
from typing import Dict, List, Optional

# ---------------------------------------------------------------------------
# Normalisation helpers
# ---------------------------------------------------------------------------

_Normalized = Dict[str, str | List[str] | None]


def _normalize_phone(raw: str) -> str:
    """Keep only digits + optional leading +; strip all other chars."""
    digits = re.sub(r"\D", "", raw)
    return digits if digits else raw


def _normalize_address(raw: str) -> str:
    """Lowercase, collapse whitespace, strip leading/trailing."""
    return re.sub(r"\s+", " ", raw or "").strip().lower()


def _normalize_hours(raw: str) -> str:
    """Collapse whitespace, lower case, keep structure useful for mismatch."""
    return re.sub(r"\s+", " ", raw or "").strip().lower()


# ---------------------------------------------------------------------------
# Extraction from unstructured site text
# ---------------------------------------------------------------------------

_GBP_NAME_RE = re.compile(r"([A-Z][A-Za-z0-9'\-\s]{2,40})\s*[–-]\s*", re.IGNORECASE)
_STREET_ADDR_RE = re.compile(
    r"(?:address|addr\.?|location)\s*[:#]?\s*([A-Za-z0-9\s,'\.\-\(\)\/]{5,80})",
    re.IGNORECASE,
)
_PHONE_RE = re.compile(
    r"(?:phone|tel\.?|contact)\s*[:#]?\s*(\+?\d{1,3}\s?\d{3}[\s\-]\d{3}[\s\-]\d{4})",
    re.IGNORECASE,
)
_HOURS_RE = re.compile(
    r"(?:hours|hour|open|monday|tuesday|wednesday|thursday|friday|saturday|sunday"
    r"(?:_brief|_short|_extended)?)\s*[:#]?\s*((?:[01]\d|2[012]):[0-5]\d\s*[:–-]\s*"
    r"(?:[01]\d|2[012]):[0-5]\d\s*(?:am|pm)?(?:,\s*(?:mon|tue|wed|thu|fri|sat|sun"
    r"(?:_brief|_short|_extended)?)?)*",
    re.IGNORECASE,
)
_SERVICES_RE = re.compile(
    r"(?:services|what.?we.?offer|our.?services)\s*[:#]?\s*([A-Za-z0-9\s,';:\-\./]{3,100})",
    re.IGNORECASE,
)


def extract_gbp_fields(site_text: str) -> _Normalized:
    """Extract the four GBP-critical fields from free‑form site text.

    Returns a dict with keys: name, address, phone, hours, services.
    Missing fields are represented as ``None`` (not empty string) so the
    caller can distinguish "not found" from "found but empty".
    """
    text = site_text or ""

    # --- name ---
    name_match = _GBP_NAME_RE.search(text)
    name = name_match.group(1).strip() if name_match else None

    # --- address ---
    addr_match = _STREET_ADDR_RE.search(text)
    address = _normalize_address(addr_match.group(1)) if addr_match else None

    # --- phone ---
    phone_match = _PHONE_RE.search(text)
    phone = _normalize_phone(phone_match.group(1)) if phone_match else None

    # --- hours ---
    hours_match = _HOURS_RE.search(text)
    hours = _normalize_hours(hours_match.group(1)) if hours_match else None

    # --- services (free‑form list, split on semicolon / newline) ---
    svc_match = _SERVICES_RE.search(text)
    if svc_match:
        raw = svc_match.group(1)
        services = [s.strip() for s in re.split(r"[;,\n]+", raw) if s.strip()]
    else:
        services = None

    return {"name": name, "address": address, "phone": phone,
            "hours": hours, "services": services}


# ---------------------------------------------------------------------------
# Comparison / mismatch report
# ---------------------------------------------------------------------------

def _compare_field(gbp_val: str | None, site_val: str | None,
                   field: str) -> Dict[str, object]:
    """Return a tiny mismatch record for one GBP field."""
    if gbp_val is None and site_val is None:
        return {"match": True, "gbp": gbp_val, "site": site_val,
                "message": f"{field}: both absent"}
    if gbp_val is None or site_val is None:
        return {"match": False, "gbp": gbp_val, "site": site_val,
                "message": f"{field}: GBP {'' if gbp_val is None else 'has value'; "
                f"site {'' if site_val is None else 'has value'}"}
    gbp_l = gbp_val.lower()
    site_l = site_val.lower()
    if gbp_l == site_l:
        return {"match": True, "gbp": gbp_val, "site": site_val,
                "message": f"{field}: match"}
    # simple token‑overlap check for hours/services (sets)
    if field in ("hours", "services"):
        gbp_set = set(gbp_l.split())
        site_set = set(site_l.split())
        overlap = gbp_set & site_set
        if overlap:
            return {"match": True, "gbp": gbp_val, "site": site_val,
                    "message": f"{field}: partial overlap ({len(overlap)} tokens)"}
    return {"match": False, "gbp": gbp_val, "site": site_val,
            "message": f"{field}: GBP={gbp_l!r} vs site={site_l!r}"}


def check_gbp_consistency(*, gbp: dict, site_text: str) -> dict:
    """Compare a GBP profile against site text.

    * ``gbp`` must have some or all of: ``name``, ``address``, ``phone``,
      ``hours``, ``services`` (any mixture; missing keys are treated as
      absent).
    * ``site_text`` is the full text of the site's home/about/footer etc.

    Returns a dict with:
    - ``overall_match``: ``True`` when every present GBP field has a matching
      site field (partial overlap on hours/services counts as match).
    - ``fields``: a dict keyed by the fields that appear in *gbp*; each entry
      has ``match`` (bool), ``gbp``, ``site``, ``message``.
    - ``guidance``: a list of human‑readable fixes for every ``match`` is
      ``False``.
    """
    fields = ["name", "address", "phone", "hours", "services"]
    field_reports: dict = {}
    overall_match = True
    guidance: List[str] = []

    for fname in fields:
        if fname not in gbp:
            # field absent from GBP → nothing to mismatch; skip it
            continue
        site_val = extract_gbp_fields(site_text).get(fname)
        report = _compare_field(gbp[fname], site_val, fname)
        field_reports[fname] = report
        if not report["match"]:
            overall_match = False
            guidance.append(report["message"])

    # If GBP has no critical fields at all, treat as match (nothing to check)
    if not field_reports:
        overall_match = True

    return {
        "overall_match": overall_match,
        "fields": field_reports,
        "guidance": guidance,
    }