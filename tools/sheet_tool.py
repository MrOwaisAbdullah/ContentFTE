import os
import json
import re
import gspread
from datetime import datetime, timezone
from google.oauth2.service_account import Credentials
from typing import List, TypedDict, Optional, Union, Any, Dict, Literal
import logging
import time

from lib.site_env import SITE_PREFIX, sheets_enabled
from agents import function_tool
from dotenv import load_dotenv
load_dotenv()  # Load environment variables from .env file if present

# Configure logging for better error tracking
logging.basicConfig(level=logging.INFO) # Adjust level as needed (DEBUG, INFO, WARNING, ERROR)
logger = logging.getLogger(__name__)

# --- Constants ---
REQUIRED_SCOPE = [
    "https://spreadsheets.google.com/feeds",
    "https://www.googleapis.com/auth/drive"
]

CREDENTIALS_ENV_VAR = "GOOGLE_CREDENTIALS" # Ensure this matches your environment variable name
SPREADSHEET_NAME = "ContentSpark" # Your main spreadsheet name

# --- Cached client/spreadsheet handles ---
# google-auth Credentials objects refresh their own tokens as needed, so it's
# safe to keep reusing one authorized gspread client across calls instead of
# re-authenticating (and re-resolving the spreadsheet by title, which costs an
# extra Drive API lookup) on every single tool invocation. This matters
# because Sheets API quota is limited to 300 requests/60s per project and
# 60/60s per user.
_gspread_clients: Dict[str, gspread.Client] = {}
_spreadsheet_handles: Dict[str, gspread.Spreadsheet] = {}


def _creds_fingerprint() -> str:
    """Stability key of the ACTIVE GOOGLE_CREDENTIALS. The client and
    spreadsheet caches are keyed by it so two instances that configure
    different service accounts in one process can never reuse each other's
    connection (the first instance's client would otherwise be frozen in
    for the process lifetime)."""
    import hashlib

    raw = os.environ.get(CREDENTIALS_ENV_VAR, "").strip()
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


def _reset_gspread_cache() -> None:
    """Drops cached client/spreadsheet handles so the next call re-authenticates."""
    _gspread_clients.clear()
    _spreadsheet_handles.clear()


# --- Helper Functions ---
def get_gspread_client() -> gspread.Client:
    """Authenticates and returns a cached gspread client, reused across calls
    (per credential fingerprint)."""
    fp = _creds_fingerprint()
    client = _gspread_clients.get(fp)
    if client is not None:
        return client

    # SHEETS_ENABLED=0 (spec §3b): a Postgres-only instance has no
    # Google creds and no Sheets -- fail loudly here, the single choke
    # point every sheet call funnels through, rather than deep inside
    # google-auth. The SDK/service path is unaffected (Postgres-native).
    if not sheets_enabled():
        raise RuntimeError(
            "Google Sheets are disabled for this instance "
            "(SHEETS_ENABLED=0); the pipeline runs on Postgres via the "
            "SDK/service layer (docs/spec-site2-postgres-frontend.md §3b).")

    credentials_info = os.environ.get(CREDENTIALS_ENV_VAR)
    if not credentials_info:
        raise ValueError(f"Environment variable {CREDENTIALS_ENV_VAR} not set.")

    try:
        creds_data = json.loads(credentials_info)
        creds = Credentials.from_service_account_info(creds_data, scopes=REQUIRED_SCOPE)
        client = gspread.authorize(creds)
        _gspread_clients[fp] = client
        logger.info("Successfully authenticated with Google Sheets API.")
        return client
    except json.JSONDecodeError as e:
        logger.error(f"Invalid JSON in {CREDENTIALS_ENV_VAR}: {e}")
        raise ValueError(f"Invalid JSON in {CREDENTIALS_ENV_VAR}") from e
    except Exception as e:
        logger.error(f"Failed to authenticate Google Sheets client: {e}")
        raise


def get_spreadsheet() -> gspread.Spreadsheet:
    """Returns a cached handle to the main ContentSpark spreadsheet
    (per credential fingerprint, like the client itself)."""
    fp = _creds_fingerprint()
    handle = _spreadsheet_handles.get(fp)
    if handle is not None:
        return handle
    client = get_gspread_client()
    handle = client.open(SPREADSHEET_NAME)
    _spreadsheet_handles[fp] = handle
    return handle


WORKSHEET_ALIASES: Dict[str, List[str]] = {
    "freshness sweep": ["freshness sweep", "freshness_sweep", "freshness_log", "freshness"],
    "freshness_sweep": ["freshness sweep", "freshness_sweep", "freshness_log", "freshness"],
    "audit": ["audit", "claims_audit", "claims audit"],
    "claims_audit": ["audit", "claims_audit", "claims audit"],
    "performance": ["performance", "search_performance", "search performance", "performance_log"],
    "search_performance": ["performance", "search_performance", "search performance", "performance_log"],
    "review": ["review", "review_feedback_log", "review_feedback", "review feedback"],
    "review_feedback_log": ["review", "review_feedback_log", "review_feedback", "review feedback"],
    "usage logs": ["usage logs", "model_usage_log", "model_usage", "usage_logs", "usage log"],
    "model_usage_log": ["usage logs", "model_usage_log", "model_usage", "usage_logs", "usage log"],
}


def resolve_worksheet(spreadsheet: gspread.Spreadsheet, worksheet_name: str) -> gspread.Worksheet:
    """Attempts to find an existing worksheet matching worksheet_name or any
    known alias (e.g. 'audit' vs 'claims_audit', 'performance' vs 'search_performance',
    'review' vs 'review_feedback_log', 'freshness sweep' vs 'freshness_sweep',
    'usage logs' vs 'model_usage_log'). Raises gspread.exceptions.WorksheetNotFound
    if neither the requested name nor any alias exists."""
    candidates = [worksheet_name]
    lowered = worksheet_name.strip().lower()
    if lowered in WORKSHEET_ALIASES:
        for alias in WORKSHEET_ALIASES[lowered]:
            if alias not in candidates:
                candidates.append(alias)
    spaced = lowered.replace("_", " ")
    underscored = lowered.replace(" ", "_")
    for variant in (spaced, underscored):
        if variant not in candidates:
            candidates.append(variant)

    for name in candidates:
        try:
            return spreadsheet.worksheet(name)
        except gspread.exceptions.WorksheetNotFound:
            continue
    raise gspread.exceptions.WorksheetNotFound(worksheet_name)


def ensure_worksheet_exists(worksheet_name: str, headers: List[str]) -> bool:
    """Creates worksheet_name (with the given header row) if it or an alias doesn't
    already exist in the spreadsheet. Self-healing schema, supports aliases so both
    'performance' and 'search_performance' resolve cleanly."""
    if not sheets_enabled():
        # Postgres mode (spec 3b): no worksheets exist to create. Return
        # True so stage callers proceed -- their writes are routed to
        # Postgres (mapped) or skipped (unmapped) by manage_sheet_data.
        return True
    try:
        spreadsheet = get_spreadsheet()
        try:
            resolve_worksheet(spreadsheet, worksheet_name)
            return True  # Already exists (as name or alias).
        except gspread.exceptions.WorksheetNotFound:
            pass
        worksheet = spreadsheet.add_worksheet(title=worksheet_name, rows=100, cols=max(len(headers), 1))
        worksheet.append_row(headers, value_input_option="USER_ENTERED")
        logger.info(f"Created new worksheet '{worksheet_name}' with headers: {headers}")
        return True
    except Exception as e:
        logger.error(f"Failed to ensure worksheet '{worksheet_name}' exists: {e}")
        return False


# The model usage worksheet. The code asks for "usage logs" and
# resolve_worksheet's alias set maps that onto the live sheet's
# "model_usage_log" tab, so both names address the same place.
MODEL_USAGE_WORKSHEET = "usage logs"
MODEL_USAGE_HEADERS = ["Timestamp", "Model", "Agent", "Stage", "Status", "Latency (s)"]


def log_model_usage(
    model: str, agent: str, stage: str, status: str, latency: float
) -> bool:
    """Appends one row to the model usage worksheet, shared by the LLM
    fallback runner so every row lands in the same six columns.

    Best-effort and never raises -- a sheet hiccup must not fail the run that
    triggered it. Returns True only if the row was actually written.

    Deliberately synchronous: a deferred ``create_task()`` can be dropped if
    the process exits right after the caller returns, which is exactly what
    happens in a one-shot GitHub Actions run.

    Every row is also mirrored to Postgres (audit_log action="usage.model")
    so a SHEETS_ENABLED=0 instance keeps the log and the console Logs screen
    reads the same rows on both instances."""
    if not model:
        return False
    wrote_sheet = False
    try:
        spreadsheet = get_spreadsheet()
        ensure_worksheet_exists(MODEL_USAGE_WORKSHEET, MODEL_USAGE_HEADERS)
        worksheet = resolve_worksheet(spreadsheet, MODEL_USAGE_WORKSHEET)
        worksheet.append_row(
            [
                datetime.now().strftime("%Y-%m-%d %H:%M:%S UTC"),
                str(model),
                str(agent or "unknown"),
                str(stage or "unknown"),
                str(status),
                f"{float(latency or 0.0):.1f}",
            ],
            value_input_option="USER_ENTERED",
        )
        wrote_sheet = True
    except Exception as e:
        logger.warning(f"model usage log append failed (non-fatal): {e}")
    try:
        from lib.store import log_usage_event
        wrote_pg = log_usage_event("model", {
            "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S UTC"),
            "model": str(model), "agent": str(agent or "unknown"),
            "stage": str(stage or "unknown"), "status": str(status),
            "latency": f"{float(latency or 0.0):.1f}",
        })
    except Exception as e:
        logger.warning(f"model usage mirror failed (non-fatal): {e}")
        wrote_pg = False
    return wrote_sheet or wrote_pg


# Dedicated image-audit worksheet, kept separate from model_usage_log so
# "which image model ran, and did it pass" is a single readable tab instead of
# being interleaved with hundreds of LLM rows. Created on first write.
IMAGE_LOG_WORKSHEET = "image_logs"
# Spec 5.9: per image we store prompt, model, cost and generation ms, plus
# the slot (featured vs inpost) so cost-per-post is answerable from the
# sheet. New columns are APPENDED after Detail so rows written before this
# change keep their column mapping; _ensure_image_log_headers extends the
# header row on demand (same self-healing pattern as generated_posts).
IMAGE_LOG_HEADERS = [
    "Timestamp",
    "Model",
    "Stage",
    "Subject",
    "Status",
    "Reference",
    "Latency (s)",
    "Detail",
    "Cost (USD)",
    "Slot",
    "Latency (ms)",
    "Prompt",
]


def _ensure_image_log_headers(worksheet) -> None:
    """Rewrite row 1 when the live sheet predates a column addition.
    Header row only — data rows are untouched, and appending values beyond
    the old column count stays aligned because new columns are appended."""
    try:
        current = worksheet.row_values(1)
        if current == IMAGE_LOG_HEADERS:
            return
        worksheet.update(f"A1", [IMAGE_LOG_HEADERS], value_input_option="USER_ENTERED")
        logger.info("Extended image_logs header row with new columns: %s", IMAGE_LOG_HEADERS)
    except Exception as e:
        logger.warning(f"image_logs header refresh failed (non-fatal): {e}")


def log_image_usage(
    model: str,
    stage: str,
    subject: str,
    status: str,
    latency: float,
    reference: str = "",
    detail: str = "",
    cost_usd: Optional[float] = None,
    slot: str = "",
    prompt: str = "",
    latency_ms: Optional[float] = None,
) -> bool:
    """Appends one row to the `image_logs` worksheet.

    One row per actual image call -- every Cloudflare generation attempt
    (Stage=`generate`, including the img2img revision attempts, which is what
    `Reference=yes` marks), every Pexels fetch (Stage=`stock`), the
    stock-vs-AI relevancy decision (Stage=`gate`), and one summary row per
    `generate_image_tool` call (Stage=`result`) carrying the VLM/Jev verdict
    so the loop's outcome is readable without joining rows.

    `cost_usd` is the per-image cost (0.0 for stock; the model's measured
    Neuron cost for generations), `slot` is featured/inpost, `prompt` the
    actual generation prompt (truncated), `latency_ms` the precise
    generation/QA latency (falls back to latency*1000).

    Best-effort and never raises: a sheet hiccup must not fail an image
    generation that already succeeded. Returns True only if the row landed."""
    try:
        if not model:
            return False
        spreadsheet = get_spreadsheet()
        ensure_worksheet_exists(IMAGE_LOG_WORKSHEET, IMAGE_LOG_HEADERS)
        worksheet = resolve_worksheet(spreadsheet, IMAGE_LOG_WORKSHEET)
        _ensure_image_log_headers(worksheet)
        if latency_ms is None:
            latency_ms = float(latency or 0.0) * 1000.0
        cost_cell = "" if cost_usd is None else f"{float(cost_usd):.4f}"
        worksheet.append_row(
            [
                datetime.now().strftime("%Y-%m-%d %H:%M:%S UTC"),
                str(model),
                str(stage or ""),
                str(subject or ""),
                str(status or ""),
                str(reference or ""),
                f"{float(latency or 0.0):.1f}",
                str(detail or "")[:500],
                cost_cell,
                str(slot or ""),
                f"{float(latency_ms):.0f}",
                str(prompt or "")[:1000],
            ],
            value_input_option="USER_ENTERED",
        )
        wrote_sheet = True
    except Exception as e:
        logger.warning(f"image log append failed (non-fatal): {e}")
        wrote_sheet = False
    # Postgres mirror (console Logs screen; sheets-disabled instances keep
    # the row as audit action="usage.image").
    try:
        from lib.store import log_usage_event
        wrote_pg = log_usage_event("image", {
            "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S UTC"),
            "model": str(model), "stage": str(stage or ""), "subject": str(subject or ""),
            "status": str(status or ""), "reference": str(reference or ""),
            "latency": f"{float(latency or 0.0):.1f}", "detail": str(detail or "")[:500],
            "cost_usd": "" if cost_usd is None else f"{float(cost_usd):.4f}",
            "slot": str(slot or ""), "latency_ms": f"{float(latency_ms or 0.0):.0f}",
            "prompt": str(prompt or "")[:1000],
        })
    except Exception as e:
        logger.warning(f"image usage mirror failed (non-fatal): {e}")
        wrote_pg = False
    return wrote_sheet or wrote_pg


# In-process record of the keyword row get_keyword_tool claimed most recently
# (row_index + exact keyword text). Confirmed live: marking the row "used" the
# moment it's selected is NOT safe against the fallback runner's behavior --
# gemini-flash-latest ran the tool (row marked used), then the model call
# itself 503'd, and run_with_fallback re-ran the whole Triage Agent from
# scratch. The re-run invoked the tool again, found nothing "available"
# (the claim had already been burned), and returned an error -- the keyword
# the user had just prioritized was lost with no research done. With this
# state, a re-invocation in the same process re-issues the SAME row instead
# of scanning past it; the workflow that owns the process then either clears
# the state on success (row legitimately stays "used") or releases the row
# back to "available" on failure via release_keyword_claim().
_keyword_claim: Dict[str, Any] = {"row_index": None, "keyword": None,
                                  "primary": "", "secondary": "",
                                  "source": None}


def _keyword_preview(keyword: str, limit: int = 80) -> str:
    """Truncates a keyword for debug printing. Keywords can be entire YouTube
    transcripts (10k+ chars pasted into the sheet), and get_keyword_tool's
    per-row debug print used to dump each one in full -- a single run's log
    became an unreadable wall of text (confirmed live)."""
    return keyword if len(keyword) <= limit else keyword[: limit - 3] + "..."


# Column names in ContentSpark_Keywords. The list is the ONLY place the
# sheet's shape is declared -- get_keyword_tool resolves every column from the
# header row, so adding a keyword column here is a one-line change and never
# silently shifts Status onto the wrong cell.
KEYWORD_SHEET_COLUMNS = {
    "subject": ("Topic/YT Transcript", "Keyword"),
    "primary": ("Primary Keyword",),
    "secondary": ("Secondary Keywords",),
    "status": ("Status",),
}


def _column_index(header: list) -> dict:
    """Map logical field -> actual column name + 1-based position, taken from
    the sheet's own header row. Falls back to a canonical name so a sheet
    whose header is missing a column still returns a readable error rather
    than a KeyError."""
    def pick(candidates):
        for cand in candidates:
            for pos, name in enumerate(header, 1):
                if str(name).strip().lower() == cand.strip().lower():
                    return cand, pos
        return candidates[0], len(header) + 1

    subject, subject_pos = pick(KEYWORD_SHEET_COLUMNS["subject"])
    primary, primary_pos = pick(KEYWORD_SHEET_COLUMNS["primary"])
    secondary, _ = pick(KEYWORD_SHEET_COLUMNS["secondary"])
    status, status_pos = pick(KEYWORD_SHEET_COLUMNS["status"])
    return {
        "subject": subject, "subject_pos": subject_pos,
        "primary": primary, "primary_pos": primary_pos,
        "secondary": secondary,
        "status": status, "status_pos": status_pos,
    }


def _sheets_disabled_error() -> Optional[Dict[str, str]]:
    """The payload get_keyword_tool returns when Sheets are off
    (SHEETS_ENABLED=0): the queue lives in the keyword_ledger and is
    served by the SDK brief endpoint, so point the caller there
    instead of surfacing an auth error from the disabled client."""
    if sheets_enabled():
        return None
    return {
        "error": (
            "Google Sheets are disabled for this instance "
            "(SHEETS_ENABLED=0); claim the next keyword via the "
            "SDK brief endpoint (contentfte_get_brief / "
            "GET /sdk/v1/sites/{slug}/brief)."
        )
    }


def claim_keyword() -> Dict[str, Any]:
    """Fetches an available keyword and marks it used (plain function; the
    @function_tool wrapper below is what agents see). Dispatches on the same
    switch as everything else: a Sheets-off instance claims from
    keyword_ledger (research_snapshot.claimed_at) instead of a gspread
    Status cell, with the identical idempotent re-claim contract."""
    if not sheets_enabled():
        return _pg_keyword_claim()
    _disabled = _sheets_disabled_error()
    if _disabled:
        return _disabled
    try:
        # Idempotent re-claim: if this process already claimed a row, hand it
        # back instead of scanning again. This is what makes a fallback re-run
        # of the Triage Agent safe -- see _keyword_claim's comment.
        if _keyword_claim["keyword"] is not None:
            return {
                "selected_keyword": _keyword_claim["keyword"],
                "primary_keyword": _keyword_claim.get("primary", ""),
                "secondary_keywords": _keyword_claim.get("secondary", ""),
                "status_update": (
                    f"Row {_keyword_claim['row_index']} already claimed by this run; "
                    "re-issuing the same keyword (sheet unchanged)."
                ),
            }

        client = get_gspread_client()
        sheet = client.open("ContentSpark_Keywords").sheet1

        # Get all records
        records = sheet.get_all_records()
        # print(f"Records retrieved: {records}")  # Debug: Print all records

        if not records:
            return {"error": "No keywords available in sheet"}

        # Find the first available keyword.
        # Column positions are resolved from the header row, NOT hardcoded:
        # the sheet's four columns are Topic/YT Transcript, Primary Keyword,
        # Secondary Keywords, Status -- so Status sits at whatever index the
        # header says. Writing to a fixed column number here would land on
        # Primary Keyword the moment the order changed.
        header = sheet.row_values(1) if sheet.row_count > 0 else []
        col = _column_index(header)

        for i, record in enumerate(records, 2):  # Start at row 2 (skip header)
            status = str(record.get(col["status"], "")).strip().lower()
            print(f"Row {i}: Topic={_keyword_preview(record.get(col['subject'], ''))}, Status={status}")  # Debug
            if status == "available":
                subject = str(record.get(col["subject"], "")).strip()
                if not subject:
                    print(f"Row {i}: Empty topic, skipping")
                    continue
                # Mark as used
                sheet.update_cell(i, col["status_pos"], "used")
                _keyword_claim["row_index"] = i
                _keyword_claim["keyword"] = subject
                _keyword_claim["primary"] = str(
                    record.get(col["primary"], "")).strip()
                _keyword_claim["secondary"] = str(
                    record.get(col["secondary"], "")).strip()
                _keyword_claim["source"] = "sheet"
                return {
                    "selected_keyword": subject,
                    "primary_keyword": _keyword_claim["primary"],
                    "secondary_keywords": _keyword_claim["secondary"],
                    "status_update": f"Row {i} marked as used"
                }

        return {"error": "No available keywords found"}

    except Exception as e:
        # print(f"Error: get_keyword_tool: {str(e)}")  # Debug
        return {"error": f"Failed to fetch keyword: {str(e)}"}


@function_tool
def get_keyword_tool():
    """Fetches an available keyword from ContentSpark_Keywords and marks it as used."""
    return claim_keyword()


def release_keyword_claim() -> bool:
    """Returns the most recently claimed keyword row to Status="available"
    and forgets the claim. Called by the research workflow whenever a run
    that claimed a keyword fails before its findings are persisted to
    research_data -- without this, any post-claim failure (model 503s, agent
    retry exhaustion, output agent failure) permanently burns the keyword
    even though nothing was researched. Best-effort: a row that no longer
    matches the claimed keyword (sheet edited/deleted mid-run) is left
    alone rather than blindly flipping some other row's Status cell."""
    row_index = _keyword_claim.get("row_index")
    keyword = str(_keyword_claim.get("keyword") or "")
    source = _keyword_claim.get("source")
    clear_keyword_claim()
    if source == "postgres":
        if row_index is None:
            return False
        try:
            from lib.db import KeywordLedger, get_session, init_db
            init_db()
            s = get_session()
            try:
                row = s.get(KeywordLedger, row_index)
                if row is None:
                    logger.warning(f"Not releasing keyword claim: ledger row {row_index} no longer exists.")
                    return False
                snap = dict(row.research_snapshot or {})
                current = str(snap.get("subject") or row.keyword)
                if current != keyword and current[:100] != keyword[:100]:
                    logger.warning(
                        f"Not releasing keyword claim: ledger row {row_index} now holds "
                        f"different content ({_keyword_preview(current)}) than what was claimed."
                    )
                    return False
                snap.pop("claimed_at", None)
                row.research_snapshot = snap
                s.commit()
                logger.info(f"Released keyword claim: ledger row {row_index} (claimed_at cleared).")
                return True
            finally:
                s.close()
        except Exception as e:
            logger.warning(f"Failed to release keyword claim on ledger row {row_index}: {e}")
            return False
    if row_index is None:
        return False
    if not sheets_enabled():
        # Legacy/sheet claim but Sheets is off now -- nothing to write to.
        return False
    try:
        client = get_gspread_client()
        sheet = client.open("ContentSpark_Keywords").sheet1
        col = _column_index(sheet.row_values(1) if sheet.row_count > 0 else [])
        current = str(sheet.cell(row_index, col["subject_pos"]).value or "")
        # Prefix compare as well as exact: guards against a mid-run sheet edit
        # shifting rows, without needing the full (possibly huge) keyword to
        # round-trip identically through the API.
        if current != keyword and current[:100] != keyword[:100]:
            logger.warning(
                f"Not releasing keyword claim: row {row_index} now holds different "
                f"content ({_keyword_preview(current)}) than what was claimed."
            )
            return False
        sheet.update_cell(row_index, col["status_pos"], "available")
        logger.info(f"Released keyword claim: row {row_index} back to 'available'.")
        return True
    except Exception as e:
        logger.warning(f"Failed to release keyword claim on row {row_index}: {e}")
        return False


def keyword_claim_keywords() -> Dict[str, str]:
    """The subject plus its keyword targets on the currently claimed row.

    Read from the process-local claim rather than any agent output, so a model
    can never reword, merge or drop the operator's keywords while relaying
    them down the pipeline."""
    return {
        "subject": str(_keyword_claim.get("keyword") or ""),
        "primary": str(_keyword_claim.get("primary") or ""),
        "secondary": str(_keyword_claim.get("secondary") or ""),
    }


def clear_keyword_claim() -> None:
    """Forgets the in-process claim WITHOUT touching the sheet -- used when a
    workflow that claimed a keyword completes successfully, so the row stays
    legitimately "used" but a later workflow in the same long-lived process
    (main.py's server) doesn't get handed the stale keyword again."""
    _keyword_claim["row_index"] = None
    _keyword_claim["keyword"] = None
    _keyword_claim["primary"] = ""
    _keyword_claim["secondary"] = ""
    _keyword_claim["source"] = None


# ---------------------------------------------------------------------------
# Postgres mode (spec-site2 3a/3b): mapped worksheets as derived views.
#
# One choke point: manage_sheet_data routes here when either switch is set,
# so no agent prompt, stage, or tool call changes. Reads are rebuilt from
# Postgres in append order (row_index = position + 2); writes map header ->
# field on the ledger/article row. Unmapped worksheets keep the Sheets path
# while Sheets is enabled and become no-op successes when it is off (3d).
# ---------------------------------------------------------------------------
_PG_MAPPED = {"research_data", "content_briefs", "generated_posts",
              # Not a table of its own: scripts/backfill_postgres.py documents
              # it as a FILTER view of generated_posts (approved, not yet
              # published), and the Preparation Agent selects its row 2 to
              # publish -- so it is derived from articles, not skipped.
              "approved_unpublished"}
_PG_READ_ACTIONS = frozenset({
    "get_worksheet", "get_all_records", "get_row", "get_column",
    "get_range", "find_row_by_key",
})
_PG_WRITE_ACTIONS = frozenset({
    "append_row", "insert_row", "update_row", "update_cell",
    "update_cells", "delete_row", "clear_sheet",
})


def _pg_reads() -> bool:
    """True when mapped worksheet reads must be served from Postgres."""
    if not sheets_enabled():
        return True
    try:
        from lib.store import use_postgres_reads
        return use_postgres_reads()
    except Exception:
        return False


def _pg_mapped_writes() -> bool:
    """True when mapped worksheet writes must go to Postgres only.

    Sheets off (site #2) or STORE_READ_SOURCE=postgres (site #1 post-flip):
    row indexes come from the Postgres views, so the write MUST land there --
    never on a Sheets row that may not even exist anymore."""
    if not sheets_enabled():
        return True
    try:
        from lib.store import use_postgres_reads
        return use_postgres_reads()
    except Exception:
        return False


def _pg_ws_key(worksheet_name: str) -> str:
    return (worksheet_name or "").strip().lower().replace(" ", "_")


def _pg_headers_for(ws_key: str) -> List[str]:
    from lib.store import _BRIEF_HEADERS, _POST_HEADERS, _RESEARCH_HEADERS
    if ws_key == "research_data":
        return [*_RESEARCH_HEADERS, "Created At"]
    if ws_key == "content_briefs":
        return [*_BRIEF_HEADERS, "Created At"]
    if ws_key in ("generated_posts", "approved_unpublished"):
        return [*_POST_HEADERS, "Created At", "Image Source",
                "Last Freshness Check", "Last Performance Check"]
    return []


def _pg_yes(value: Any) -> bool:
    return str(value).strip().lower() in ("yes", "true", "1", "y", "approved")


def _pg_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(str(value).replace(",", "").strip() or default)
    except (TypeError, ValueError):
        return default


def _pg_int(value: Any, default: int = 0) -> int:
    try:
        return int(float(str(value).replace(",", "").strip() or default))
    except (TypeError, ValueError):
        return default


def _pg_col_to_idx(letters: str) -> int:
    """'A' -> 1, 'B' -> 2, ... 'AA' -> 27 (1-based column index)."""
    n = 0
    for ch in letters.upper():
        n = n * 26 + (ord(ch) - 64)
    return n


def _pg_site(session):
    """The instance's site for worksheet views.

    Resolution mirrors the mirror writers: DEFAULT_SITE_SLUG first (their
    get_or_create_site("") target), then a single-site instance's only row so
    a forgiving setup (console-created slug, env unset) still round-trips.
    Returns None without creating anything -- reads on an unprovisioned DB
    stay empty."""
    from sqlalchemy import select as _select
    from lib.db import Site
    from lib.store import DEFAULT_SITE_SLUG
    site = session.execute(
        _select(Site).where(Site.slug == DEFAULT_SITE_SLUG)).scalar_one_or_none()
    if site is not None:
        return site
    sites = session.execute(_select(Site)).scalars().all()
    return sites[0] if len(sites) == 1 else None


def _pg_ledger_rows(session, site) -> List[Any]:
    from sqlalchemy import select as _select
    from lib.db import KeywordLedger
    return list(session.execute(
        _select(KeywordLedger).where(KeywordLedger.site_id == site.id)
        .order_by(KeywordLedger.id.asc())).scalars())


def _pg_find_ledger_row(session, site, *keys):
    """The ledger row a sheet row refers to.

    Sheets addresses research_data by its Keyword/Topic column (the subject
    the research was about) while lib.store keys the ledger row by the
    primary keyword when the operator supplied one -- so a brief written
    under the subject must land on that same research row instead of
    spinning up a second one. Exact keyword match wins, then the subject
    recorded on the row."""
    wanted = [str(k).strip() for k in keys if str(k or "").strip()]
    if not wanted or site is None:
        return None
    rows = _pg_ledger_rows(session, site)
    for k in wanted:
        for r in rows:
            if r.keyword == k:
                return r
    for k in wanted:
        for r in rows:
            if str((r.research_snapshot or {}).get("subject") or "") == k:
                return r
    return None


def _pg_article_rows(session, site) -> List[Any]:
    from sqlalchemy import select as _select
    from lib.db import Article
    return list(session.execute(
        _select(Article).where(Article.site_id == site.id)
        .order_by(Article.id.asc())).scalars())


def _pg_view(ws_key: str, session, site):
    """(headers, rows, models) for a mapped worksheet -- deterministic.

    rows and models are positionally aligned; data row i lives at sheet row
    i + 2 (row 1 is the header)."""
    headers = _pg_headers_for(ws_key)
    if ws_key == "research_data":
        models = _pg_ledger_rows(session, site) if site else []
        # Briefs are keyed by the sheet's Keyword/Topic (the subject), the
        # ledger row often by the primary keyword -- so Generated flips Yes
        # on whichever of the two the brief landed on, exactly like the
        # sheet's "mark Generated=Yes on the research row" step.
        brief_keys = set()
        for r in models:
            snap = r.research_snapshot or {}
            if snap.get("brief"):
                brief_keys.add(r.keyword)
                subject = str(snap.get("subject") or "").strip()
                if subject:
                    brief_keys.add(subject)
        rows = []
        for r in models:
            snap = r.research_snapshot or {}
            subject = str(snap.get("subject") or "").strip()
            generated = bool(snap.get("brief")) or r.keyword in brief_keys or (
                bool(subject) and subject in brief_keys)
            rows.append([
                subject or r.keyword,
                r.volume, r.difficulty, r.intent,
                str(snap.get("summary") or ""),
                str(snap.get("sources") or ""),
                str(snap.get("source_titles") or ""),
                "Yes" if generated else "No",
                str(snap.get("primary_keyword") or ""),
                str(snap.get("secondary_keywords") or ""),
                str(snap.get("Created At") or ""),
            ])
        return headers, rows, models
    if ws_key == "content_briefs":
        ledger = _pg_ledger_rows(session, site) if site else []
        models = [r for r in ledger
                  if (r.research_snapshot or {}).get("brief")]
        rows = []
        for r in models:
            snap = r.research_snapshot or {}
            rows.append([
                str(snap.get("subject") or "") or r.keyword,
                str(snap.get("brief") or ""),
                str(snap.get("faqs") or ""),
                str(snap.get("sources") or ""),
                str(snap.get("summary") or ""),
                "Yes" if snap.get("content_generated") else "No",
                str(snap.get("secondary_keywords") or ""),
                str(snap.get("Created At") or ""),
            ])
        return headers, rows, models
    if ws_key in ("generated_posts", "approved_unpublished"):
        models = _pg_article_rows(session, site) if site else []
        if ws_key == "approved_unpublished":
            # The sheet is a filtered view of generated_posts (approved and
            # not yet published) -- see scripts/backfill_postgres.py. The
            # Preparation Agent reads its row 2 as "the next post to ship",
            # so publishing on a Sheets-off instance depends on this filter.
            models = [a for a in models if a.status == "approved"]
        rows = []
        for a in models:
            meta = a.meta or {}
            scores = a.scores or {}
            stamps = meta.get("sheet_stamps") or {}
            quality = scores.get("quality", scores.get("overall", ""))
            rows.append([
                a.title, a.content_md,
                str(meta.get("faqs") or ""),
                quality if quality != "" else "",
                str(meta.get("summary") or ""),
                "Approved" if a.status in ("approved", "published") else "No",
                "Yes" if a.status == "published" else "No",
                str(meta.get("Repurpose Bundle") or ""),
                str(meta.get("Video Script Seed") or ""),
                str(meta.get("secondary_keywords") or ""),
                str(stamps.get("Created At") or ""),
                str(stamps.get("Image Source") or ""),
                str(stamps.get("Last Freshness Check") or ""),
                str(stamps.get("Last Performance Check") or ""),
            ])
        return headers, rows, models
    return headers, [], []


def _pg_apply_update(ws_key: str, model, header: str, value: Any) -> None:
    """Map one header->value write onto the model row (in place)."""
    value_str = str(value) if value is not None else ""
    if ws_key == "research_data":
        snap = dict(model.research_snapshot or {})
        if header == "Search Volume":
            model.volume = _pg_int(value_str, model.volume)
        elif header == "Difficulty":
            model.difficulty = _pg_float(value_str, model.difficulty)
        elif header == "User Intent":
            if value_str.strip():
                model.intent = value_str.strip()
        elif header == "Generated":
            pass  # derives from a brief existing in the snapshot
        elif header == "Keyword/Topic":
            snap["subject"] = value_str
        elif header == "Content Summary":
            snap["summary"] = value_str
        elif header == "Source URLs":
            snap["sources"] = value_str
        elif header == "Source Titles":
            snap["source_titles"] = value_str
        elif header == "Primary Keyword":
            snap["primary_keyword"] = value_str
        elif header == "Secondary Keywords":
            snap["secondary_keywords"] = value_str
        elif header == "Created At":
            snap["Created At"] = value_str
        else:
            stamps = dict(snap.get("stamps") or {})
            stamps[header] = value_str
            snap["stamps"] = stamps
        model.research_snapshot = snap
        return
    if ws_key == "content_briefs":
        snap = dict(model.research_snapshot or {})
        if header == "Keyword/Topic":
            pass  # identity: the brief row's key never renames
        elif header == "Brief Content":
            snap["brief"] = value_str
        elif header == "FAQs":
            snap["faqs"] = value_str
        elif header == "External Source Links":
            snap["sources"] = value_str
        elif header == "Content Summary":
            snap["summary"] = value_str
        elif header == "Secondary Keywords":
            snap["secondary_keywords"] = value_str
        elif header == "Generated":
            if _pg_yes(value_str):
                snap["content_generated"] = datetime.now(timezone.utc).isoformat()
            else:
                snap.pop("content_generated", None)
        elif header == "Created At":
            snap["Created At"] = value_str
        else:
            stamps = dict(snap.get("stamps") or {})
            stamps[header] = value_str
            snap["stamps"] = stamps
        model.research_snapshot = snap
        return
    if ws_key in ("generated_posts", "approved_unpublished"):
        meta = dict(model.meta or {})
        scores = dict(model.scores or {})
        lowered = value_str.strip().lower()
        if header == "Title":
            if value_str.strip():
                model.title = value_str.strip()
        elif header == "Generated Content":
            model.content_md = value_str
        elif header == "FAQs":
            meta["faqs"] = value_str
        elif header == "Quality Score":
            scores["quality"] = _pg_float(value_str, _pg_float(scores.get("quality"), 0.0))
        elif header == "Summary":
            meta["summary"] = value_str
        elif header == "Approve/Disapprove":
            if lowered in ("approved", "approve", "yes", "true", "1"):
                model.status = "approved"
            elif lowered in ("disapproved", "disapprove", "rejected", "reject",
                             "no", "false", "0"):
                model.status = "needs_review"
        elif header == "Published":
            if _pg_yes(value_str):
                model.status = "published"
                if model.published_at is None:
                    model.published_at = datetime.now(timezone.utc)
        elif header == "Secondary Keywords":
            meta["secondary_keywords"] = value_str
        elif header in ("Repurpose Bundle", "Video Script Seed"):
            meta[header] = value_str
        else:
            stamps = dict(meta.get("sheet_stamps") or {})
            stamps[header] = value_str
            meta["sheet_stamps"] = stamps
        model.meta = meta
        model.scores = scores
        return


def _pg_keyword_claim() -> dict:
    """Ledger-backed keyword claim for a Sheets-off instance (spec 3b).

    Claimable = no research summary, no brief, not yet claimed, not terminal.
    The claim is recorded in research_snapshot.claimed_at and released by
    clearing it; process-local _keyword_claim keeps the sheet path's
    idempotent re-claim contract."""
    if _keyword_claim["keyword"] is not None:
        return {
            "selected_keyword": _keyword_claim["keyword"],
            "primary_keyword": _keyword_claim.get("primary", ""),
            "secondary_keywords": _keyword_claim.get("secondary", ""),
            "status_update": (
                f"Ledger row {_keyword_claim['row_index']} already claimed by "
                "this run; re-issuing the same keyword (row unchanged)."
            ),
        }
    try:
        from lib.db import KeywordLedger, get_session, init_db
        from lib.ledger import TERMINAL
        init_db()
        s = get_session()
        try:
            site = _pg_site(s)
            if site is None:
                return {"error": "No available keywords found"}
            for row in _pg_ledger_rows(s, site):
                snap = dict(row.research_snapshot or {})
                if row.status in TERMINAL:
                    continue
                if snap.get("summary") or snap.get("brief") or snap.get("claimed_at"):
                    continue
                snap["claimed_at"] = datetime.now(timezone.utc).isoformat()
                row.research_snapshot = snap
                s.commit()
                subject = str(snap.get("subject") or "") or row.keyword
                primary = str(snap.get("primary_keyword") or "")
                secondary = str(snap.get("secondary_keywords") or "")
                _keyword_claim["row_index"] = row.id
                _keyword_claim["keyword"] = subject
                _keyword_claim["primary"] = primary
                _keyword_claim["secondary"] = secondary
                _keyword_claim["source"] = "postgres"
                return {
                    "selected_keyword": subject,
                    "primary_keyword": primary,
                    "secondary_keywords": secondary,
                    "status_update": f"Ledger row {row.id} marked as claimed",
                }
            return {"error": "No available keywords found"}
        finally:
            s.close()
    except Exception as e:
        return {"error": f"Failed to fetch keyword: {str(e)}"}


def _pg_cell(headers: List[str], row_values: List[Any], name: str) -> str:
    """Value of a trailing/sheet-only column from an append row ("" when the
    caller's row is shorter -- most stages append only the canonical
    columns and stamp timestamps afterwards)."""
    if name not in headers:
        return ""
    i = headers.index(name)
    if i >= len(row_values) or row_values[i] is None:
        return ""
    return str(row_values[i])


def _pg_apply_research(row, mapped: Dict[str, Any]) -> None:
    """Write research cells onto an existing ledger row.

    Used when the sheet's Keyword/Topic (subject) addresses a row that the
    store keys by the primary keyword -- mirroring by keyword would create a
    second row and leave this one looking un-researched forever. Keeps the
    brief/claims already on the row; mirrors mirror_keyword's field updates
    (including the priority-score recompute and the Generated -> briefed
    status graduation)."""
    from lib.ledger import priority_score

    row.intent = str(mapped.get("intent") or "").strip() or row.intent
    row.volume = int(mapped.get("volume") or 0)
    row.difficulty = float(mapped.get("difficulty") or 0.0)
    row.priority_score = priority_score(row.volume, row.intent, row.difficulty)
    prior = dict(row.research_snapshot or {})
    row.research_snapshot = {
        **prior,
        "summary": str(mapped.get("summary") or ""),
        "subject": str(mapped.get("subject") or "") or str(prior.get("subject") or ""),
        "primary_keyword": str(mapped.get("primary_keyword") or ""),
        "secondary_keywords": str(mapped.get("secondary_keywords") or ""),
    }
    if mapped.get("generated") and row.status in ("researched", "approved", "queued"):
        row.status = "briefed"


def _pg_apply_brief(row, mapped: Dict[str, Any]) -> None:
    """Write brief cells onto the ledger row the research already lives on
    (merge, never replace -- the research summary/keywords ride alongside)."""
    prior = dict(row.research_snapshot or {})
    row.research_snapshot = {
        **prior,
        "brief": str(mapped.get("brief_content") or ""),
        "faqs": str(mapped.get("faqs") or ""),
        "sources": str(mapped.get("sources") or ""),
        "summary": str(mapped.get("summary") or ""),
        "secondary_keywords": str(mapped.get("secondary_keywords") or ""),
    }
    if mapped.get("generated") and row.status in ("researched", "approved", "queued"):
        row.status = "briefed"


def _pg_append_row(ws_key: str, session, site, headers: List[str],
                   row_values: List[Any]) -> bool:
    """One append for a mapped worksheet (append_row and insert_row share it).

    The lib.store mappers are the canonical sheet->row conversion, but two
    things they don't do matter here: (1) mirror_keyword replaces the whole
    research_snapshot, which would drop the brief/claims a later stage
    already wrote onto this same ledger row, and (2) the trailing sheet-only
    columns (Created At, Source URLs/Titles, image/check stamps) have no
    column in the table, so they ride in the row's JSON buckets. Resolve the
    target row first (subject-aware), then merge + stash."""
    from lib import store as pg_store

    slug = site.slug if site is not None else ""

    if ws_key == "research_data":
        mapped = pg_store.map_research_row(list(row_values), headers)
        target = _pg_find_ledger_row(
            session, site, mapped.get("keyword"), mapped.get("subject"))
        if target is not None:
            _pg_apply_research(target, mapped)
            row = target
        else:
            row = pg_store.mirror_keyword(session, site_slug=slug, **mapped)
        if row is None:
            return False
        snap = dict(row.research_snapshot or {})
        for hdr, key in (("Source URLs", "sources"),
                         ("Source Titles", "source_titles"),
                         ("Created At", "Created At")):
            val = _pg_cell(headers, row_values, hdr)
            if val and not snap.get(key):
                snap[key] = val
        row.research_snapshot = snap
        session.commit()
        return True

    if ws_key == "content_briefs":
        mapped = pg_store.map_brief_row(list(row_values), headers)
        target = _pg_find_ledger_row(session, site, mapped.get("keyword"))
        if target is not None:
            _pg_apply_brief(target, mapped)
            row = target
        else:
            # No research row to attach to (brief authored directly): fall
            # back to the store, which keys the new row by the brief keyword.
            row = pg_store.mirror_brief(session, site_slug=slug, **mapped)
        if row is None:
            return False
        created = _pg_cell(headers, row_values, "Created At")
        if created:
            snap = dict(row.research_snapshot or {})
            if not snap.get("Created At"):
                snap["Created At"] = created
                row.research_snapshot = snap
        session.commit()
        return True

    art = pg_store.mirror_article(
        session, site_slug=slug,
        **pg_store.map_generated_post_row(list(row_values), headers))
    if art is None:
        return False
    stamps = {
        hdr: _pg_cell(headers, row_values, hdr)
        for hdr in ("Created At", "Image Source",
                    "Last Freshness Check", "Last Performance Check")
    }
    stamps = {k: v for k, v in stamps.items() if v}
    if stamps:
        meta = dict(art.meta or {})
        existing = dict(meta.get("sheet_stamps") or {})
        merged = {**stamps, **existing}  # an existing stamp wins over the row
        meta["sheet_stamps"] = merged
        art.meta = meta
        session.commit()
    return True


def _pg_manage(worksheet_name: str, action: str, *, data=None,
               row_values=None, row_index=None, col_index=None,
               cell_range=None, key_column=None, key_value=None):
    """Postgres-mode handler for manage_sheet_data. Returns a result dict,
    or None to fall through to the Sheets path (mixed mode's aux tabs)."""
    ws_key = _pg_ws_key(worksheet_name)
    mapped = ws_key in _PG_MAPPED

    if action in _PG_READ_ACTIONS:
        if not mapped:
            # Unmapped tabs have no Postgres table (3d): empty success only
            # when Sheets itself is off; mixed mode still reads the sheet.
            if not sheets_enabled():
                if action == "get_worksheet":
                    return {"status": "success", "worksheet_title": worksheet_name,
                            "row_count": 1, "col_count": 1}
                if action == "get_all_records":
                    return {"status": "success", "data": [], "count": 0}
                if action == "get_row":
                    return {"status": "success", "data": [],
                            "row_index": row_index or 1}
                if action == "get_column":
                    return {"status": "success", "data": [],
                            "col_index": col_index or 1}
                if action == "get_range":
                    return {"status": "success", "data": [], "range": cell_range}
                if action == "find_row_by_key":
                    return {"status": "success", "found": False,
                            "row_index": None, "data": None,
                            "message": (f"No row found for {key_column} = "
                                        f"{key_value} (Postgres mode: worksheet "
                                        "not mirrored).")}
            return None
        if not _pg_reads():
            return None
        from lib.db import get_session, init_db
        init_db()
        s = get_session()
        try:
            site = _pg_site(s)
            headers, rows, models = _pg_view(ws_key, s, site)
            if action == "get_worksheet":
                return {"status": "success", "worksheet_title": worksheet_name,
                        "row_count": len(rows) + 1, "col_count": len(headers)}
            if action == "get_all_records":
                records = [dict(zip(headers, r)) for r in rows]
                logger.info(f"Retrieved {len(records)} records from {worksheet_name} (postgres)")
                return {"status": "success", "data": records, "count": len(records)}
            if action == "get_row":
                if row_index is None:
                    return {"status": "error",
                            "message": "row_index is required for get_row action."}
                if row_index == 1:
                    return {"status": "success", "data": headers, "row_index": 1}
                pos = row_index - 2
                if 0 <= pos < len(rows):
                    return {"status": "success", "data": rows[pos],
                            "row_index": row_index}
                return {"status": "success", "data": [], "row_index": row_index}
            if action == "get_column":
                if col_index is None:
                    return {"status": "error",
                            "message": "col_index is required for get_column action."}
                if col_index < 1 or col_index > len(headers):
                    return {"status": "success", "data": [],
                            "col_index": col_index}
                values = [headers[col_index - 1]]
                values += [r[col_index - 1] for r in rows]
                return {"status": "success", "data": values,
                        "col_index": col_index}
            if action == "get_range":
                if cell_range is None:
                    return {"status": "error",
                            "message": "cell_range is required for get_range action."}
                cr = str(cell_range).strip()
                m = re.fullmatch(r"(\d+):(\d+)", cr)
                if m:
                    start, end = int(m.group(1)), int(m.group(2))
                    grid = [headers, *rows]
                    data_out = grid[start - 1:end] if start >= 1 else []
                    return {"status": "success", "data": data_out, "range": cr}
                m = re.fullmatch(r"([A-Za-z]+)(\d+):([A-Za-z]+)(\d+)", cr)
                if m:
                    c1, r1 = _pg_col_to_idx(m.group(1)), int(m.group(2))
                    c2, r2 = _pg_col_to_idx(m.group(3)), int(m.group(4))
                    grid = [headers, *rows]
                    slice_rows = grid[min(r1, r2) - 1: max(r1, r2)]
                    lo, hi = min(c1, c2), max(c1, c2)
                    data_out = [row[lo - 1: hi] for row in slice_rows]
                    return {"status": "success", "data": data_out, "range": cr}
                return {"status": "error",
                        "message": f"Range '{cr}' not supported in Postgres mode."}
            if action == "find_row_by_key":
                if key_column is None or key_value is None:
                    return {"status": "error", "message": "key_column and key_value "
                            "are required for find_row_by_key action."}
                want = str(key_value)
                for i, (rec, model) in enumerate(zip(
                        (dict(zip(headers, r)) for r in rows), models)):
                    if str(rec.get(key_column, "")) == want:
                        found = i + 2
                        return {"status": "success", "found": True,
                                "row_index": found, "data": rec,
                                "message": f"Row found for {key_column} = {want} "
                                           f"at index {found}."}
                    # Identity lookups: Keyword/Topic may be the subject on the
                    # row while the caller searches by keyword (or vice versa).
                    if key_column == "Keyword/Topic" and ws_key in (
                            "research_data", "content_briefs"):
                        snap = model.research_snapshot or {}
                        alts = {model.keyword,
                                str(snap.get("primary_keyword") or ""),
                                str(snap.get("subject") or "")}
                        if want in alts:
                            found = i + 2
                            return {"status": "success", "found": True,
                                    "row_index": found, "data": rec,
                                    "message": f"Row found for {key_column} = "
                                               f"{want} at index {found}."}
                return {"status": "success", "found": False, "row_index": None,
                        "data": None,
                        "message": f"No row found for {key_column} = {want}."}
            return None
        finally:
            s.close()

    if action in _PG_WRITE_ACTIONS:
        if mapped and _pg_mapped_writes():
            from lib.db import get_session, init_db
            init_db()
            s = get_session()
            try:
                site = _pg_site(s)
                headers, rows, models = _pg_view(ws_key, s, site)
                if action == "append_row":
                    if not row_values:
                        return {"status": "error",
                                "message": "row_values is required for append_row action."}
                    if not _pg_append_row(ws_key, s, site, headers, list(row_values)):
                        return {"status": "error",
                                "message": f"Row could not be appended to "
                                           f"{worksheet_name} (empty key column)."}
                    logger.info(f"Appended row to {worksheet_name} (postgres)")
                    return {"status": "success",
                            "message": f"Row appended to {worksheet_name}."}
                if action == "insert_row":
                    if not row_values:
                        return {"status": "error",
                                "message": "row_values and row_index are required for insert_row action."}
                    # Append order IS the ledger/article order -- a positional
                    # insert has no meaning, so treat it as an append.
                    if not _pg_append_row(ws_key, s, site, headers, list(row_values)):
                        return {"status": "error",
                                "message": f"Row could not be inserted into "
                                           f"{worksheet_name} (empty key column)."}
                    return {"status": "success",
                            "message": f"Row inserted at index {row_index} in {worksheet_name}."}
                if action == "delete_row":
                    if row_index is None:
                        return {"status": "error",
                                "message": "row_index is required for delete_row action."}
                    pos = (row_index or 1) - 2
                    if 0 <= pos < len(models):
                        model = models[pos]
                        if ws_key == "content_briefs":
                            # The delete IS the content-consumption signal:
                            # the row stays (history) but flips Generated=Yes
                            # so find_row_by_key(Generated, "No") never
                            # re-claims a brief that already produced content.
                            snap = dict(model.research_snapshot or {})
                            snap["content_generated"] = datetime.now(
                                timezone.utc).isoformat()
                            model.research_snapshot = snap
                            s.commit()
                            print(f"[pg] content_briefs row {row_index} marked "
                                  "generated (row retained).")
                        else:
                            print(f"[pg] {worksheet_name} row {row_index} delete "
                                  "skipped (rows are derived, nothing to remove).")
                    return {"status": "success",
                            "message": f"Row {row_index} deleted from {worksheet_name}."}
                if action == "update_row":
                    if row_index is None or (not row_values and data is None):
                        return {"status": "error", "message": "row_index and "
                                "row_values/data are required for update_row action."}
                    values = row_values if row_values is not None else data
                    if values and isinstance(values[0], (list, tuple)):
                        values = list(values[0])
                    if not isinstance(values, (list, tuple)):
                        return {"status": "error", "message": "For update_row, "
                                "row_values or data must be a list."}
                    if row_index == 1:
                        return {"status": "success",
                                "message": f"Row 1 updated in {worksheet_name}."}
                    pos = row_index - 2
                    if not (0 <= pos < len(models)):
                        return {"status": "error",
                                "message": f"Row {row_index} not found in {worksheet_name}."}
                    for j, val in enumerate(values):
                        if j >= len(headers):
                            break
                        _pg_apply_update(ws_key, models[pos], headers[j], val)
                    s.commit()
                    return {"status": "success",
                            "message": f"Row {row_index} updated in {worksheet_name}."}
                if action == "update_cell":
                    if row_index is None or col_index is None or data is None:
                        return {"status": "error", "message": "row_index, "
                                "col_index, and data (cell value) are required "
                                "for update_cell action."}
                    cell_value = data if isinstance(data, str) else str(data)
                    if row_index == 1:
                        # Canonical headers are fixed in Postgres mode; a new
                        # stamp column shows up via the generic bucket below.
                        return {"status": "success", "message": f"Cell "
                                f"(1, {col_index}) updated in {worksheet_name}."}
                    pos = row_index - 2
                    if not (0 <= pos < len(models)):
                        return {"status": "error",
                                "message": f"Row {row_index} not found in {worksheet_name}."}
                    header = (headers[col_index - 1]
                              if 1 <= col_index <= len(headers)
                              else f"Extra Column {col_index}")
                    _pg_apply_update(ws_key, models[pos], header, cell_value)
                    s.commit()
                    logger.info(f"Updated cell ({row_index}, {col_index}) in "
                                f"{worksheet_name} (postgres)")
                    return {"status": "success", "message": f"Cell "
                            f"({row_index}, {col_index}) updated in {worksheet_name}."}
                if action == "update_cells":
                    if cell_range is None or data is None:
                        return {"status": "error", "message": "cell_range and "
                                "data (List[List]) are required for update_cells action."}
                    m = re.search(r"([A-Za-z]*)(\d+)", str(cell_range).strip())
                    if not m:
                        return {"status": "error",
                                "message": f"Range '{cell_range}' not supported "
                                           "in Postgres mode."}
                    start_row = int(m.group(2))
                    start_col = _pg_col_to_idx(m.group(1)) if m.group(1) else 1
                    if start_row == 1:
                        return {"status": "success",
                                "message": f"Range {cell_range} updated in {worksheet_name}."}
                    pos = start_row - 2
                    if not (0 <= pos < len(models)):
                        return {"status": "error",
                                "message": f"Row {start_row} not found in {worksheet_name}."}
                    grid = data if (data and isinstance(data[0], (list, tuple))) else [data]
                    for r_off, row_vals in enumerate(grid):
                        if start_row - 1 + r_off >= len(models) + 1:
                            break
                        model = models[min(pos + r_off, len(models) - 1)]
                        for j, val in enumerate(row_vals):
                            col = start_col + j - 1
                            header = (headers[col] if 0 <= col < len(headers)
                                      else f"Extra Column {col + 1}")
                            _pg_apply_update(ws_key, model, header, val)
                    s.commit()
                    return {"status": "success",
                            "message": f"Range {cell_range} updated in {worksheet_name}."}
                if action == "clear_sheet":
                    return {"status": "error", "message": "clear_sheet is not "
                            "supported in Postgres mode (data is derived)."}
                return None
            except Exception as e:
                logger.error(f"Postgres {action} failed on '{worksheet_name}': {e}",
                             exc_info=True)
                return {"status": "error",
                        "message": f"An unexpected error occurred: {str(e)}"}
            finally:
                s.close()
        if not sheets_enabled() and not mapped:
            # 3d: aux/telemetry tabs have no Postgres table; a no-op success
            # keeps stage paths (which check status) running without a
            # Sheets client. The write itself is lost by design.
            return {"status": "success",
                    "message": f"{action} skipped on '{worksheet_name}' "
                               "(Postgres mode; worksheet not mirrored).",
                    "skipped": True}
        return None
    return None


# --- Refined Type Definitions for Schema Generation ---

# Define specific types for data based on action
# For actions returning lists of rows/columns/cells
SheetDataList = List[List[str]] # Assuming data is primarily strings/numbers rendered as strings

# For actions returning a single row/column
SheetDataRow = List[str]

# For actions returning key-value pairs (e.g., get_range for a small range)
SheetDataDict = Dict[str, Any] # Less ideal, but sometimes necessary. Try to be more specific if possible.

# For actions returning all records
SheetRecords = List[Dict[str, Any]] # List of dictionaries, keys are headers

# Specific result structures for different actions (simplified for schema)
class BaseResult(Dict[str, Any]): # Use a base Dict for flexibility in schema gen
    status: str # 'success' or 'error'
    message: str # Descriptive message

class GetWorksheetResult(BaseResult):
    worksheet_title: str
    row_count: int
    col_count: int

class GetAllRecordsResult(BaseResult):
    data: SheetRecords
    count: int

class GetRowResult(BaseResult):
     data: SheetDataRow
     row_index: int

class GetColumnResult(BaseResult):
     data: SheetDataRow # Columns are also lists of values
     col_index: int

class GetRangeResult(BaseResult):
     data: SheetDataList # or SheetDataDict if range is small/structured
     range: str

class FindRowResult(BaseResult):
     found: bool
     row_index: Optional[int] # None if not found
     data: Optional[Dict[str, str]] # Record dict if found, None if not


# --- Generic Sheet Management Tool ---
# Simplified function signature for schema generation
# Use Union of specific action literals for better hinting
def manage_sheet_data(
    worksheet_name: str,
    action: Literal[ # Specify allowed actions explicitly
        "get_worksheet", "get_all_records", "get_row", "get_column",
        "get_range", "append_row", "insert_row", "update_row",
        "update_cell", "update_cells", "delete_row", "clear_sheet",
        "find_row_by_key"
    ],
    # Use Optional types for parameters that are not always required
    data: Optional[List[List[str]]] = None, # Simplified for schema, e.g., for update_cells
    row_values: Optional[List[str]] = None, # Simplified for schema, e.g., for append/insert
    row_index: Optional[int] = None,
    col_values: Optional[List[str]] = None, # Simplified for schema
    col_index: Optional[int] = None,
    cell_range: Optional[str] = None,
    value_input_option: str = "USER_ENTERED", # Keep as string, values are constrained by gspread
    key_column: Optional[str] = None,
    key_value: Optional[str] = None, # Simplify key value type
    return_all_records: bool = False, # Remove, handled by action=get_all_records
    num_rows: Optional[int] = None, # Remove if not used
    num_cols: Optional[int] = None, # Remove if not used
    retries: int = 3,
    delay: float = 1.0
) -> BaseResult: # Simplified return type hint for schema compatibility
    """
    A generic tool to manage data in a Google Sheet worksheet.
    """
    # Postgres mode (spec 3a/3b): mapped worksheets are derived views and
    # unmapped ones are no-op successes when Sheets is off. None => fall
    # through to the Sheets path below (mixed mode's aux tabs).
    _pg_result = _pg_manage(
        worksheet_name, action, data=data, row_values=row_values,
        row_index=row_index, col_index=col_index, cell_range=cell_range,
        key_column=key_column, key_value=key_value)
    if _pg_result is not None:
        return _pg_result

    attempt = 0
    while attempt < retries:
        try:
            spreadsheet = get_spreadsheet()
            # --- Open worksheet, resolving aliases if needed ---
            worksheet = resolve_worksheet(spreadsheet, worksheet_name)
            # ---------------------------------------------------

            logger.debug(f"Performing action '{action}' on worksheet '{worksheet_name}', attempt {attempt + 1}")

            if action == "get_worksheet":
                # Returns basic worksheet info
                 return {
                    "status": "success",
                    "worksheet_title": worksheet.title,
                    "row_count": worksheet.row_count,
                    "col_count": worksheet.col_count
                }

            elif action == "get_all_records":
                records = worksheet.get_all_records()
                logger.info(f"Retrieved {len(records)} records from {worksheet_name}")
                return {"status": "success", "data": records, "count": len(records)}

            elif action == "get_row":
                if row_index is None:
                     return {"status": "error", "message": "row_index is required for get_row action."}
                row_data = worksheet.row_values(row_index)
                return {"status": "success", "data": row_data, "row_index": row_index}

            elif action == "get_column":
                if col_index is None:
                    return {"status": "error", "message": "col_index is required for get_column action."}
                col_data = worksheet.col_values(col_index)
                return {"status": "success", "data": col_data, "col_index": col_index}

            elif action == "get_range":
                if cell_range is None:
                    return {"status": "error", "message": "cell_range is required for get_range action."}
                range_data = worksheet.get(cell_range)
                return {"status": "success", "data": range_data, "range": cell_range}

            elif action == "append_row":
                if not row_values:
                     return {"status": "error", "message": "row_values is required for append_row action."}
                logger.info(f"Appending row to {worksheet_name}: {row_values}")
                worksheet.append_row(row_values, value_input_option=value_input_option)
                time.sleep(0.5)  # Small delay to ensure update is processed
                # §5.16 Sheets→Postgres cutover, step 1: dual-write mirror.
                # Best-effort -- a mirror failure must not break the Sheets
                # write that triggered it (lib.store never raises).
                try:
                    from lib.store import mirror_sheet_append
                    mirror_sheet_append(worksheet_name, list(row_values))
                except Exception as _mirror_err:
                    logger.warning(f"postgres mirror skipped ({worksheet_name}): {_mirror_err}")
                logger.info(f"Successfully appended row to {worksheet_name}")
                return {"status": "success", "message": f"Row appended to {worksheet_name}."}

            elif action == "insert_row":
                if not row_values or row_index is None:
                    return {"status": "error", "message": "row_values and row_index are required for insert_row action."}
                worksheet.insert_row(row_values, row_index, value_input_option=value_input_option)
                time.sleep(0.5)  # Small delay to ensure update is processed
                return {"status": "success", "message": f"Row inserted at index {row_index} in {worksheet_name}."}

            elif action == "update_row":
                if row_index is None or (not row_values and data is None):
                    return {"status": "error", "message": "row_index and row_values/data are required for update_row action."}
                values_to_update = row_values if row_values is not None else data # Prioritize row_values, fallback to data (if list-like)
                # Ensure data is a list for row update
                if not isinstance(values_to_update, list):
                    return {"status": "error", "message": "For update_row, row_values or data must be a list."}
                worksheet.update(f"A{row_index}", [values_to_update], value_input_option=value_input_option) # Update starting from column A
                
                # Verify that the update was successful by reading the row back
                time.sleep(0.5)  # Small delay to ensure update is processed
                updated_row = worksheet.row_values(row_index)
                
                # Compare values (making sure we're comparing the right number of values)
                if len(updated_row) >= len(values_to_update):
                    row_matches = all(updated_row[i] == str(values_to_update[i]) for i in range(len(values_to_update)))
                else:
                    # If updated row is shorter than expected, they don't match
                    row_matches = False
                
                if row_matches:
                    return {"status": "success", "message": f"Row {row_index} updated in {worksheet_name}."}
                else:
                    logger.error(f"Failed to update row {row_index} in {worksheet_name}. Expected: {values_to_update}, Got: {updated_row}")
                    return {"status": "error", "message": f"Failed to update row {row_index} in {worksheet_name}. Value verification failed."}

            elif action == "update_cell":
                if row_index is None or col_index is None or data is None: # data here is the cell value
                    return {"status": "error", "message": "row_index, col_index, and data (cell value) are required for update_cell action."}
                # For update_cell, data should be a simple string value
                cell_value = data if isinstance(data, str) else str(data)
                logger.info(f"Updating cell ({row_index}, {col_index}) in {worksheet_name} with value: {cell_value}")
                worksheet.update_cell(row_index, col_index, cell_value)
                
                # Verify that the update was successful by reading the cell back
                time.sleep(0.5)  # Small delay to ensure update is processed
                updated_value = worksheet.cell(row_index, col_index).value
                if updated_value == cell_value:
                    logger.info(f"Successfully updated cell ({row_index}, {col_index}) in {worksheet_name}")
                    return {"status": "success", "message": f"Cell ({row_index}, {col_index}) updated in {worksheet_name}."}
                else:
                    logger.error(f"Failed to update cell ({row_index}, {col_index}) in {worksheet_name}. Expected: {cell_value}, Got: {updated_value}")
                    return {"status": "error", "message": f"Failed to update cell ({row_index}, {col_index}) in {worksheet_name}. Value verification failed."}

            elif action == "update_cells":
                if cell_range is None or data is None: # data expected as List[List] for batch update
                    return {"status": "error", "message": "cell_range and data (List[List]) are required for update_cells action."}
                worksheet.update(cell_range, data, value_input_option=value_input_option)
                
                # Verify that the update was successful by reading the range back
                time.sleep(0.5)  # Small delay to ensure update is processed
                updated_range = worksheet.get(cell_range)
                
                # Compare the updated range with the expected data
                if updated_range == data:
                    return {"status": "success", "message": f"Range {cell_range} updated in {worksheet_name}."}
                else:
                    logger.error(f"Failed to update range {cell_range} in {worksheet_name}. Expected: {data}, Got: {updated_range}")
                    return {"status": "error", "message": f"Failed to update range {cell_range} in {worksheet_name}. Value verification failed."}

            elif action == "delete_row":
                if row_index is None:
                    return {"status": "error", "message": "row_index is required for delete_row action."}
                worksheet.delete_rows(row_index) # gspread uses 1-based indexing
                return {"status": "success", "message": f"Row {row_index} deleted from {worksheet_name}."}

            elif action == "clear_sheet":
                worksheet.clear()
                return {"status": "success", "message": f"All data cleared from {worksheet_name}."}

            elif action == "find_row_by_key":
                if key_column is None or key_value is None:
                    return {"status": "error", "message": "key_column and key_value are required for find_row_by_key action."}
                try:
                    records = worksheet.get_all_records()
                except Exception as e:
                    return {"status": "error", "message": f"Failed to fetch records for lookup: {str(e)}"}
                headers = worksheet.row_values(1) # Assumes headers are in row 1
                if key_column not in headers:
                    return {"status": "error", "message": f"Column '{key_column}' not found in worksheet headers."}
                key_col_index = headers.index(key_column) + 1 # Convert to 1-based index

                for i, record in enumerate(records):
                     # Check value in the specific key column
                    if str(record.get(key_column, "")) == str(key_value):
                         # Return 1-based row index (header is row 1, so data starts at row 2)
                        found_row_index = i + 2
                        return {
                            "status": "success",
                            "found": True,
                            "row_index": found_row_index,
                            "data": record,
                            "message": f"Row found for {key_column} = {key_value} at index {found_row_index}."
                        }
                return {
                    "status": "success",
                    "found": False,
                    "row_index": None,
                    "data": None,
                    "message": f"No row found for {key_column} = {key_value}."
                }

            else:
                return {"status": "error", "message": f"Unsupported action: {action}"}

        except gspread.exceptions.WorksheetNotFound:
            error_msg = f"Worksheet '{worksheet_name}' not found in spreadsheet '{SPREADSHEET_NAME}'."
            logger.error(error_msg)
            return {"status": "error", "message": error_msg}
        except gspread.exceptions.APIError as e:
            # Handle specific API errors, potentially retryable ones
            error_details = e.response.json() if hasattr(e, 'response') and e.response else str(e)
            logger.warning(f"API Error on attempt {attempt + 1} for {action}: {error_details}")
            # Drop cached client/spreadsheet in case the error was caused by a
            # stale/invalid cached handle, so the retry re-authenticates fresh.
            _reset_gspread_cache()
            if attempt < retries - 1:
                 time.sleep(delay) # Use time.sleep
                 attempt += 1
                 continue # Retry
            else:
                 return {"status": "error", "message": f"API Error after {retries} attempts: {error_details}"}
        except Exception as e:
            logger.error(f"Unexpected error during sheet operation '{action}' on '{worksheet_name}': {e}", exc_info=True)
            return {"status": "error", "message": f"An unexpected error occurred: {str(e)}"}

    # This point should ideally not be reached if retries are handled correctly in the loop
    return {"status": "error", "message": "Operation failed after maximum retries due to unknown reasons."}


@function_tool # Apply the decorator *after* defining the function with refined hints
def manage_sheet_data_tool( # Wrapper function for the decorator if needed, or apply directly
    worksheet_name: str,
    action: Literal[
        "get_worksheet", "get_all_records", "get_row", "get_column",
        "get_range", "append_row", "insert_row", "update_row",
        "update_cell", "update_cells", "delete_row", "clear_sheet",
        "find_row_by_key"
    ],
    data: Optional[Union[List[List[str]], str]] = None,
    row_values: Optional[List[str]] = None,
    row_index: Optional[int] = None,
    col_values: Optional[List[str]] = None,
    col_index: Optional[int] = None,
    cell_range: Optional[str] = None,
    value_input_option: str = "USER_ENTERED",
    key_column: Optional[str] = None,
    key_value: Optional[str] = None,
    retries: int = 3,
    delay: float = 1.0
) -> BaseResult:
    """A generic tool to manage data in a Google Sheet worksheet.
    
        Args:
        worksheet_name (str): Name of the worksheet (sub-sheet) within the main spreadsheet.
        action (str): The action to perform. Options:
                      'get_worksheet', 'get_all_records', 'get_row', 'get_column',
                      'get_range', 'append_row', 'insert_row', 'update_row',
                      'update_cell', 'update_cells', 'delete_row', 'clear_sheet',
                      'find_row_by_key'.
        data (List[List[str]], optional): Data for batch write/update actions (e.g., update_cells).
        row_values (List[str], optional): Values for a single row (append/insert).
        row_index (int, optional): 1-based row index for read/update/delete.
        col_values (List[str], optional): Values for a single column (update).
        col_index (int, optional): 1-based column index for read/update.
        cell_range (str, optional): Cell range (e.g., 'A1:C10') for get_range/update_cells.
        value_input_option (str): How to interpret values ('RAW', 'USER_ENTERED').
        key_column (str, optional): Header name of the column to use as a lookup key (for find_row_by_key).
        key_value (str, optional): Value in the key column to find the matching row (for find_row_by_key).
        retries (int): Number of times to retry the operation on failure.
        delay (float): Delay in seconds between retries.

    Returns:
        BaseResult: A dictionary containing the result. The exact structure depends on the action.
                    Success typically includes 'status': 'success' and relevant data.
                    Errors include 'status': 'error' and 'message': <error_details>.
                    Common fields: status (str), message (str).
                    Action-specific fields might include:
                    - data (varies), row_index (int), col_index (int), range (str), found (bool), count (int),
                      worksheet_title (str), row_count (int), col_count (int).
    """
    # Delegate to the main implementation
    return manage_sheet_data(
        worksheet_name=worksheet_name,
        action=action,
        data=data,
        row_values=row_values,
        row_index=row_index,
        col_values=col_values,
        col_index=col_index,
        cell_range=cell_range,
        value_input_option=value_input_option,
        key_column=key_column,
        key_value=key_value,
        retries=retries,
        delay=delay
    )

def validate_row(row, row_index):
    """Validate the row content and FAQs."""
    errors = []
    content = row.get("Generated Content", "")
    faqs = row.get("FAQs", "")

    # H1 Check
    if not re.search(r'^# .+', content, re.MULTILINE):
        errors.append("Missing H1 heading")

    # H2 Sections Check
    h2_count = len(re.findall(r'^## .+', content, re.MULTILINE))
    if not 4 <= h2_count <= 6:
        errors.append(f"Found {h2_count} H2 sections, expected 4–6")

    _internal_absolute = re.findall(
        rf"\[.+?\]\({re.escape(SITE_PREFIX)}.+?\)", content)
    internal_links = len(_internal_absolute) + len(re.findall(r'\[.+?\]\(/blog/.+?\)', content))
    if not 2 <= internal_links <= 3:
        errors.append(f"Found {internal_links} internal links, expected 2–3")

    # External Links Check
    external_links = len(re.findall(r'\[.+?\]\(https?://.+?\)', content))
    if not 2 <= external_links <= 3:
        errors.append(f"Found {external_links} external links, expected 2–3")

    # FAQs Check
    try:
        faqs_list = json.loads(faqs)
        if not (isinstance(faqs_list, list) and 5 <= len(faqs_list) <= 7 and all("question" in faq and "answer" in faq for faq in faqs_list)):
            errors.append("Invalid FAQs: fewer than 5 pairs or missing question/answer")
    except json.JSONDecodeError:
        # Attempt Markdown parsing
        faq_matches = re.findall(r'\*+\s*\*\*Q:[^\n]+\*\*\n\s*\*\*A:\*\* [^\n]+', faqs, re.MULTILINE)
        if len(faq_matches) < 5:
            errors.append("Invalid FAQs: Markdown parse error or fewer than 5 pairs")
        else:
            logger.info(f"Parsed {len(faq_matches)} FAQs from Markdown at row {row_index}")

    return errors

def main():
    # Step 1: Get all records from generated_posts
    records = get_all_records(WORKSHEET_NAME)
    if not records:
        logger.error("No records found in generated_posts")
        return

    # Step 2: Find first approved and unposted row
    approved_row = None
    row_index = None
    for i, row in enumerate(records, start=2):  # 1-based index, header is row 1
        if row.get("Approve/Disapprove") == "Approve" and row.get("Published") == "No":
            approved_row = row
            row_index = i
            break

    if not approved_row:
        logger.error("No approved and unposted rows found")
        return

    logger.info(f"Found approved row at index {row_index}: {approved_row['Keyword/Topic']}")

    # Step 3: Validate row content
    errors = validate_row(approved_row, row_index)
    if errors:
        logger.error(f"Validation errors for row {row_index}: {errors}")
        return

    # Step 4: Get Published column index
    published_col_index = get_column_index(WORKSHEET_NAME, "Published")
    if not published_col_index:
        logger.error("Cannot proceed: Published column not found")
        return

    # Step 5: Simulate successful Sanity publishing (replace with actual post_to_sanity_tool call)
    sanity_success = True  # Assume success for testing; replace with actual tool call
    if sanity_success:
        # Step 6: Update Published column
        success = update_cell(WORKSHEET_NAME, row_index, published_col_index, "Yes")
        if success:
            logger.info(f"Successfully updated Published column for row {row_index}")
        else:
            logger.error(f"Failed to update Published column for row {row_index}")