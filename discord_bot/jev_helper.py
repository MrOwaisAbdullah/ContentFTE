"""
discord_bot/jev_helper.py — isolated Jev helper for bot Docker context

Bot's Docker build context is discord_bot/ only (COPY bot.py — see Dockerfile),
so it cannot import lib/jev.py from the main repo. This file is a
dependency-light duplicate of lib/jev.py core logic using `requests` (already
in discord_bot/requirements.txt) instead of httpx+pydantic.

If you add httpx/pydantic to discord_bot/requirements.txt, you can replace
this with `from lib.jev import call_jev_sync` and update Dockerfile to
`COPY ../lib/jev.py lib/jev.py` — but the isolated copy is the minimal
change that preserves deploy independence (pipeline and bot deploy separately).

Auth: OPENROUTER_API_KEY (already in bot env, bot.py:86). Model pinned.
"""

import os
import time
import logging
import requests

logger = logging.getLogger("jev_helper")

JEV_MODEL = os.environ.get("JEV_MODEL", "typesafe/jev-1.13")
JEV_ENDPOINT = os.environ.get("JEV_ENDPOINT", "https://openrouter.ai/api/alpha/decisions")
JEV_TIMEOUT_MS = int(os.environ.get("JEV_TIMEOUT_MS", "5000"))
RETRYABLE_STATUS = {408, 429, 500, 502, 503, 504}


class JevError(Exception):
    def __init__(self, message: str, status=None):
        super().__init__(message)
        self.status = status
        self.name = "JevError"


def _headers():
    key = os.environ.get("OPENROUTER_API_KEY", "").strip()
    if not key:
        raise JevError("OPENROUTER_API_KEY not set")
    return {
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
        "HTTP-Referer": os.environ.get("OPENROUTER_SITE_URL", "https://owaisabdullah.dev"),
        "X-Title": os.environ.get("OPENROUTER_APP_TITLE", "ContentFTE-Discord-Bot"),
    }


def call_jev_sync(state, questions, model=None, timeout_ms=None, max_retries=2):
    """
    Sync Jev call for bot (requests). Validates minimal shape, respects Retry-After.
    Returns raw dict with `answers` + `usage` (caller does Noul/Choice extraction).
    On JevError/timeout caller should fall back (never block approval queue) per SKILL.md Fallback.
    """
    if not questions:
        raise JevError("questions must be non-empty")
    for k, q in questions.items():
        t = q.get("type")
        if t not in ("choice", "noul", "score"):
            raise JevError(f"Question '{k}' unknown type '{t}'")
        if t == "score" and len(q.get("criteria") or []) < 2:
            raise JevError(f"Score '{k}' requires >=2 criteria")

    _model = model or JEV_MODEL
    _timeout = (timeout_ms if timeout_ms is not None else JEV_TIMEOUT_MS) / 1000.0
    payload = {"model": _model, "state": state, "questions": questions}

    last_err = None
    for attempt in range(max_retries + 1):
        try:
            resp = requests.post(JEV_ENDPOINT, json=payload, headers=_headers(), timeout=(5.0, _timeout))
            if resp.status_code in RETRYABLE_STATUS and attempt < max_retries:
                delay = 1.0
                ra = resp.headers.get("retry-after") or resp.headers.get("retry-after-ms")
                if ra:
                    try:
                        if "retry-after-ms" in {k.lower() for k in resp.headers.keys()}:
                            delay = float(ra) / 1000.0
                        else:
                            delay = float(ra)
                    except ValueError:
                        pass
                logger.warning(f"Jev retry {attempt+1}/{max_retries} {resp.status_code} delay {delay:.1f}s")
                time.sleep(delay)
                continue
            if not 200 <= resp.status_code < 300:
                raise JevError(f"Jev API error {resp.status_code}: {resp.text[:2000]}", status=resp.status_code)
            data = resp.json()
            # Minimal validation — full pydantic lives in lib/jev.py
            if "answers" not in data or "usage" not in data:
                raise JevError(f"Jev response missing answers/usage: {data}")
            missing = [k for k in questions if k not in data["answers"]]
            if missing:
                raise JevError(f"Jev did not answer: {missing}", status=resp.status_code)
            return data
        except requests.Timeout as e:
            last_err = JevError(f"Jev timeout after {_timeout}s: {e}")
            if attempt < max_retries:
                time.sleep(0.5 * (attempt + 1))
                continue
            raise last_err
        except JevError:
            raise
        except Exception as e:
            last_err = JevError(f"Jev request failed: {e}")
            if attempt < max_retries:
                time.sleep(0.5 * (attempt + 1))
                continue
            raise last_err
    raise last_err or JevError("Jev failed after retries")


# Convenience wrappers for A1 duplicate check — returns matching topic string (bot.py expects Optional[str])
# General use case: Choice over existing topics + "none" (typed, no hallucination). Caps to 100 to stay under 255 limit.

def _build_duplicate_choice_state(candidate: str, existing: list):
    # Cap and map to choice keys — deterministic, no LLM invention
    capped = existing[-100:]  # newest 100; avoids 255 limit
    key_to_topic = {}
    criteria = {"none": "No existing topic is the same specific story as `candidate` — all are different angles or subjects."}
    for i, topic in enumerate(capped):
        key = f"topic_{i}"
        # Truncate very long topics to keep state bounded (keep first 200 chars for display)
        short = topic[:200]
        criteria[key] = f"Existing topic: '{short}' — SAME specific story as `candidate` if candidate covers essentially this exact topic/angle."
        key_to_topic[key] = topic
    state = {"candidate": candidate, "existing": capped}
    return state, criteria, key_to_topic

def check_duplicate_topic(candidate: str, existing: list, threshold_conf=0.65):
    """
    Legacy wrapper — returns (is_duplicate: bool, raw: dict|None, fallback: bool).
    Prefer `find_duplicate_topic` below for bot.py which needs the matching string.
    """
    matched = find_duplicate_topic(candidate, existing, threshold_conf=threshold_conf)
    if matched[2]:  # fallback
        return False, None, True
    is_dup = matched[0] is not None
    return is_dup, matched[1], False

def find_duplicate_topic(candidate: str, existing: list, threshold_conf=0.65):
    """
    Returns (matched_topic: Optional[str], raw: dict|None, fallback: bool).
    Choice-based: picks which existing topic (if any) is same story, or "none".
    Confidence-gated: below threshold → treat as no duplicate (advisory, never blocking).
    Never raises — fallback returns (None, None, True).
    """
    if not candidate or not existing:
        return None, None, True
    state, criteria, key_to_topic = _build_duplicate_choice_state(candidate, existing)
    try:
        data = call_jev_sync(
            state=state,
            questions={
                "duplicate_choice": {
                    "type": "choice",
                    "instructions": "Which existing topic, if any, is essentially the SAME specific story/topic as `candidate`? Choose `none` if no close match exists.",
                    "criteria": criteria,
                }
            },
        )
        ans = data["answers"]["duplicate_choice"]
        choice = str(ans.get("choice", "none"))
        conf = float(ans.get("confidence", 0) or 0)
        if choice == "none" or conf < threshold_conf:
            return None, data, False
        return key_to_topic.get(choice), data, False
    except JevError as e:
        logger.warning(f"find_duplicate_topic Jev fallback: {e}")
        return None, None, True
