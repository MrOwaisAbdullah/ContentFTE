"""
lib/jev.py — TypeSafe Jev System One helper for Python pipeline

Implements Phase 0 plumbing for jev-integration-report.md: decoupled from LLM fallback,
typed, fast, cheap judgment lane. Uses raw Decisions API via OpenRouter (httpx async)
rather than TypeSafe SDK — correct for this Python codebase per Tavily/Context7 evidence:

- Tavily hit `openrouter.ai/docs/guides/community/jev` surface table:
    Decisions API (POST https://openrouter.ai/api/alpha/decisions) = "any language with plain HTTP"
    System One API (POST https://openrouter.ai/api/v1/systemone) = "you already use TypeSafe SDK"
  This repo does NOT use TypeSafe SDK; it uses raw HTTP (Tavily, Sanity) + openai-agents via OpenRouter.
  Decisions API path avoids adding `typesafe-sdk` dep and matches existing `requests`/`httpx` usage.

- Context7 `/typesafe-ai/typesafe-sdk-python` confirms SDK is viable but requires
  `base_url="https://openrouter.ai/api"` + TYPESAFE_API_KEY env alias. Viable alternative,
  documented in docstring below, but not chosen as default to keep plumbing dependency-free
  (httpx already transitively installed via openai-agents/httpcore 0.28.1).

- Context7 `/websites/typesafe_ai` + `/openrouterteam/docs` confirm:
  timeout 1500ms, Zod-equivalent validation, retry on 408/429/5xx with Retry-After,
  response shape {model, answers: {choice,noul,score}, usage: {input_tokens,cost}}.

Mirrors TS pattern `lib/ai/jev.ts:66` (`callJev` with JEV_TIMEOUT_MS=1500, JevChoiceAnswerSchema, usage.input_tokens).

Auth: reuses existing OPENROUTER_API_KEY (custom_runner.py:126, discord_bot/bot.py:86) — no new env var.
Model: typesafe/jev-1.13 pinned (not alias ~typesafe/jev-latest) once thresholds are tuned.

Alternative SDK path (one-line switch if preferred):
    from typesafe_sdk import TypeSafeClient
    client = TypeSafeClient(api_key=os.environ["OPENROUTER_API_KEY"], base_url="https://openrouter.ai/api")
    resp = client.system_one(state={...}, questions={"is_duplicate": Noul(...)})
  Both bill to same OpenRouter account; this helper chooses raw path for consistency with pipeline's other raw HTTP calls.

Do not use for: prose/code generation, open-ended reasoning, raw image bytes (pair VLM caption → Jev per vision-bridge).
"""

import asyncio
import logging
import os
import time
from typing import Any, Dict, Literal, Optional, Union

import httpx
from pydantic import BaseModel, Field, ValidationError

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants — mirrors references/api-reference.md:129 + assets/templates/blog-pipeline.ts:8
# ---------------------------------------------------------------------------
JEV_MODEL = os.environ.get("JEV_MODEL", "typesafe/jev-1.13")
JEV_ENDPOINT = os.environ.get("JEV_ENDPOINT", "https://openrouter.ai/api/alpha/decisions")
JEV_TIMEOUT_MS = int(os.environ.get("JEV_TIMEOUT_MS", "5000"))
# Truncate state to ~28K tokens before send (Jev window 32K) — patterns.md:122
JEV_MAX_STATE_CHARS = int(os.environ.get("JEV_MAX_STATE_CHARS", "110000"))  # ~28K tokens * ~4 chars

# Retry on same codes as typesafe_sdk RetryPolicy: 408, 429, 5xx (patterns.md + SDK docs)
RETRYABLE_STATUS = {408, 429, 500, 502, 503, 504}


class JevError(Exception):
    """Typed wrapper for Jev failures — mirrors lib/ai/jev.ts JevError(status)."""

    def __init__(self, message: str, status: Optional[int] = None, retry_after: Optional[float] = None):
        super().__init__(message)
        self.status = status
        self.retry_after = retry_after
        self.name = "JevError"


# ---------------------------------------------------------------------------
# Pydantic schemas — Zod equivalent for Python (api-reference.md Response Shape)
# ---------------------------------------------------------------------------
class JevChoiceAnswer(BaseModel):
    type: Literal["choice"]
    choice: str
    probabilities: Optional[Dict[str, float]] = None
    confidence: Optional[float] = None


class JevNoulAnswer(BaseModel):
    type: Literal["noul"]
    noul: float = Field(ge=0, le=1)
    confidence: Optional[float] = None


class JevScoreAnswer(BaseModel):
    type: Literal["score"]
    score: float
    probabilities: Optional[Dict[str, float]] = None
    confidence: Optional[float] = None
    legend: Optional[Dict[str, str]] = None


class JevUsage(BaseModel):
    input_tokens: int
    output_tokens: int
    cost: Optional[float] = None


class JevResponse(BaseModel):
    model: str
    answers: Dict[str, Union[JevChoiceAnswer, JevNoulAnswer, JevScoreAnswer]]
    usage: JevUsage
    id: Optional[str] = None
    provider: Optional[str] = None


# Backwards-compat alias for callers that used JevResponseSchema name
JevResponseSchema = JevResponse

# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------
def _get_api_key() -> str:
    key = os.environ.get("OPENROUTER_API_KEY", "").strip()
    if not key:
        raise JevError("OPENROUTER_API_KEY is not set — cannot call Jev Decisions API")
    return key


def _truncate_state(state: Any) -> Any:
    """Truncate string state to JEV_MAX_STATE_CHARS; for object state, truncate string values similarly."""
    if isinstance(state, str):
        return state[:JEV_MAX_STATE_CHARS] if len(state) > JEV_MAX_STATE_CHARS else state
    if isinstance(state, dict):
        # Shallow truncate string values; deep objects are left to caller to size correctly.
        truncated: Dict[str, Any] = {}
        for k, v in state.items():
            if isinstance(v, str) and len(v) > JEV_MAX_STATE_CHARS:
                truncated[k] = v[:JEV_MAX_STATE_CHARS]
            elif isinstance(v, list):
                # For lists like excerpts, keep as-is; caller should cap items (e.g., 5-10 excerpts)
                truncated[k] = v
            else:
                truncated[k] = v
        return truncated
    return state


def _build_headers() -> Dict[str, str]:
    return {
        "Authorization": f"Bearer {_get_api_key()}",
        "Content-Type": "application/json",
        "HTTP-Referer": os.environ.get("OPENROUTER_SITE_URL", "https://owaisabdullah.dev"),
        "X-Title": os.environ.get("OPENROUTER_APP_TITLE", "ContentFTE-SEO-Blog-Agent"),
    }


def _validate_questions(questions: Dict[str, Any]) -> None:
    if not questions:
        raise JevError("questions must be non-empty mapping")
    for key, q in questions.items():
        qtype = q.get("type") if isinstance(q, dict) else getattr(q, "type", None)
        if qtype not in ("choice", "noul", "score"):
            raise JevError(f"Question '{key}' has unknown type '{qtype}' — expected choice|noul|score")
        if qtype == "score":
            criteria = q.get("criteria") if isinstance(q, dict) else getattr(q, "criteria", None)
            if not criteria or len(criteria) < 2:
                raise JevError(f"Score question '{key}' requires at least 2 criteria entries")


# ---------------------------------------------------------------------------
# Core API — async primary (pipeline is async), sync wrapper for discord_bot sync paths
# ---------------------------------------------------------------------------
async def call_jev(
    state: Any,
    questions: Dict[str, Any],
    *,
    model: Optional[str] = None,
    timeout_ms: Optional[int] = None,
    max_retries: int = 2,
) -> JevResponse:
    """
    Call Jev Decisions API via OpenRouter. Mirrors lib/ai/jev.ts callJev.

    Args:
        state: string | object | array — structured program state, prefer structured over concatenated paragraph.
        questions: mapping name -> {type, instructions, criteria?} — Choice/Noul/Score. All evaluated in parallel.
        model: override JEV_MODEL (default typesafe/jev-1.13 pinned)
        timeout_ms: override JEV_TIMEOUT_MS (default 1500)
        max_retries: retries on 408/429/5xx with Retry-After respect (default 2)

    Returns:
        JevResponse with typed answers + usage (input_tokens, cost). Validate via this schema before branching.

    Raises:
        JevError on empty questions, Score<2 criteria, non-2xx after retries, timeout, validation failure.
        Caller maps to typed fallback per risk (patterns.md Fallback Policy) — never throw in user-facing path.
    """
    _validate_questions(questions)
    _model = model or JEV_MODEL
    _timeout_ms = timeout_ms if timeout_ms is not None else JEV_TIMEOUT_MS
    _state = _truncate_state(state)
    payload = {"model": _model, "state": _state, "questions": questions}

    last_error: Optional[JevError] = None
    for attempt in range(max_retries + 1):
        try:
            timeout = httpx.Timeout(timeout=_timeout_ms / 1000.0, connect=5.0)
            async with httpx.AsyncClient(timeout=timeout) as client:
                started = time.perf_counter()
                resp = await client.post(JEV_ENDPOINT, json=payload, headers=_build_headers())
                latency_ms = (time.perf_counter() - started) * 1000

                if resp.status_code in RETRYABLE_STATUS and attempt < max_retries:
                    # Respect Retry-After if present (typesafe_sdk RetryPolicy does)
                    retry_after = resp.headers.get("retry-after") or resp.headers.get("retry-after-ms")
                    delay = 1.0
                    if retry_after:
                        try:
                            # retry-after-ms is ms, Retry-After is seconds or HTTP date (we handle seconds only)
                            if "retry-after-ms" in {k.lower() for k in resp.headers.keys()}:
                                delay = float(retry_after) / 1000.0
                            else:
                                delay = float(retry_after)
                        except ValueError:
                            pass
                    logger.warning(f"Jev retry {attempt+1}/{max_retries} after {resp.status_code}, delay {delay:.1f}s")
                    await asyncio.sleep(delay)
                    continue

                if not resp.is_success:
                    body = resp.text[:2000]
                    raise JevError(f"Jev API error {resp.status_code}: {body}", status=resp.status_code)

                try:
                    data = resp.json()
                except Exception as e:
                    raise JevError(f"Jev response not JSON: {e}", status=resp.status_code)

                try:
                    parsed = JevResponse.model_validate(data)
                except ValidationError as e:
                    raise JevError(f"Jev validation failed: {e}", status=resp.status_code)

                # Verify all requested keys answered
                missing = [k for k in questions.keys() if k not in parsed.answers]
                if missing:
                    raise JevError(f"Jev did not answer: {missing}", status=resp.status_code)

                logger.info(
                    f"Jev OK model={parsed.model} latency={latency_ms:.0f}ms "
                    f"input_tokens={parsed.usage.input_tokens} cost=${parsed.usage.cost or 0:.6f} "
                    f"questions={list(questions.keys())}"
                )
                return parsed

        except httpx.TimeoutException as e:
            last_error = JevError(f"Jev request timed out after {_timeout_ms}ms: {e}")
            if attempt < max_retries:
                await asyncio.sleep(0.5 * (attempt + 1))
                continue
            raise last_error
        except JevError:
            raise
        except Exception as e:
            last_error = JevError(f"Jev request failed: {e}")
            if attempt < max_retries:
                await asyncio.sleep(0.5 * (attempt + 1))
                continue
            raise last_error

    raise last_error or JevError("Jev failed after retries")


def call_jev_sync(
    state: Any,
    questions: Dict[str, Any],
    *,
    model: Optional[str] = None,
    timeout_ms: Optional[int] = None,
    max_retries: int = 2,
) -> JevResponse:
    """
    Synchronous wrapper for call_jev — for discord_bot sync paths or scripts.
    Uses httpx sync client with same timeout/retry semantics.
    """
    _validate_questions(questions)
    _model = model or JEV_MODEL
    _timeout_ms = timeout_ms if timeout_ms is not None else JEV_TIMEOUT_MS
    _state = _truncate_state(state)
    payload = {"model": _model, "state": _state, "questions": questions}

    last_error: Optional[JevError] = None
    for attempt in range(max_retries + 1):
        try:
            timeout = httpx.Timeout(timeout=_timeout_ms / 1000.0, connect=5.0)
            with httpx.Client(timeout=timeout) as client:
                started = time.perf_counter()
                resp = client.post(JEV_ENDPOINT, json=payload, headers=_build_headers())
                latency_ms = (time.perf_counter() - started) * 1000

                if resp.status_code in RETRYABLE_STATUS and attempt < max_retries:
                    retry_after = resp.headers.get("retry-after") or resp.headers.get("retry-after-ms")
                    delay = 1.0
                    if retry_after:
                        try:
                            if "retry-after-ms" in {k.lower() for k in resp.headers.keys()}:
                                delay = float(retry_after) / 1000.0
                            else:
                                delay = float(retry_after)
                        except ValueError:
                            pass
                    time.sleep(delay)
                    continue

                if resp.status_code not in range(200, 300):
                    body = resp.text[:2000]
                    raise JevError(f"Jev API error {resp.status_code}: {body}", status=resp.status_code)

                try:
                    data = resp.json()
                except Exception as e:
                    raise JevError(f"Jev response not JSON: {e}", status=resp.status_code)

                try:
                    parsed = JevResponse.model_validate(data)
                except ValidationError as e:
                    raise JevError(f"Jev validation failed: {e}", status=resp.status_code)

                missing = [k for k in questions.keys() if k not in parsed.answers]
                if missing:
                    raise JevError(f"Jev did not answer: {missing}", status=resp.status_code)

                logger.info(
                    f"Jev OK (sync) model={parsed.model} latency={latency_ms:.0f}ms "
                    f"input_tokens={parsed.usage.input_tokens} cost=${parsed.usage.cost or 0:.6f}"
                )
                return parsed

        except httpx.TimeoutException as e:
            last_error = JevError(f"Jev request timed out after {_timeout_ms}ms: {e}")
            if attempt < max_retries:
                time.sleep(0.5 * (attempt + 1))
                continue
            raise last_error
        except JevError:
            raise
        except Exception as e:
            last_error = JevError(f"Jev request failed: {e}")
            if attempt < max_retries:
                time.sleep(0.5 * (attempt + 1))
                continue
            raise last_error

    raise last_error or JevError("Jev failed after retries")


# ---------------------------------------------------------------------------
# Validation helper — offline shape check without network (mirrors scripts/validate-jev-call.js)
# ---------------------------------------------------------------------------
def validate_jev_response(data: Dict[str, Any]) -> JevResponse:
    """Validate a mock/real Jev response dict without calling the API. Useful for tests."""
    return JevResponse.model_validate(data)


# ---------------------------------------------------------------------------
# Convenience: log format for cost accounting (store alongside label per patterns.md)
# ---------------------------------------------------------------------------
def jev_log_fields(resp: JevResponse, latency_ms: Optional[float] = None) -> Dict[str, Any]:
    """Extract loggable fields per patterns.md: probabilities+confidence+latencyMs+usage.input_tokens"""
    out: Dict[str, Any] = {
        "model": resp.model,
        "usage": {"input_tokens": resp.usage.input_tokens, "cost": resp.usage.cost},
    }
    if latency_ms is not None:
        out["latency_ms"] = round(latency_ms, 1)
    for key, ans in resp.answers.items():
        if isinstance(ans, JevChoiceAnswer):
            out[key] = {"choice": ans.choice, "confidence": ans.confidence, "probabilities": ans.probabilities}
        elif isinstance(ans, JevNoulAnswer):
            out[key] = {"noul": ans.noul, "confidence": ans.confidence}
        elif isinstance(ans, JevScoreAnswer):
            out[key] = {"score": ans.score, "confidence": ans.confidence, "probabilities": ans.probabilities}
    return out
