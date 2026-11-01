import asyncio
import logging
import tempfile
from typing import Any, Dict, Optional
from urllib.parse import urlparse

from agents import function_tool

from lib.safe_fetch import UnsafeURL, check_url

logger = logging.getLogger(__name__)

_ALLOWED_SCHEMES = {"http", "https"}


def _url_is_safe_public(url: str) -> Optional[str]:
    """An error message if `url` should not be navigated to, else None.

    This tool hands an LLM-directed headless browser the ability to fetch whatever URL the agent decides to
    visit - without a check that is an SSRF vector (a prompt-injected or merely mistaken agent pointing the
    browser at an internal service). Uses the shared `lib.safe_fetch.check_url` (http/https only, no
    embedded credentials, every resolved address must be public - IPv4 and IPv6)."""
    try:
        check_url(url)
    except UnsafeURL as e:
        return str(e)
    except Exception as e:  # noqa: BLE001 - an unparseable URL is a refusal, not a crash
        return f"URL could not be checked: {e}"
    return None


_NON_NETWORK_SCHEMES = ("data:", "blob:", "about:")


async def _install_request_guard(page, blocked: list) -> None:
    """Re-validate EVERY request the page makes - the main navigation, each redirect hop, subresources,
    fetch/XHR - not just the first URL (SEC-19). A public page that redirects to, or embeds, an internal
    address (http://169.254.169.254/, http://localhost:8000/...) is aborted before any connection is made.
    Hostnames are checked once per page load to keep the extra DNS cost small."""
    verdicts: Dict[str, Optional[str]] = {}

    async def _guard(route) -> None:
        url = route.request.url
        if url.startswith(_NON_NETWORK_SCHEMES):
            await route.continue_()
            return
        host = (urlparse(url).hostname or "").lower()
        if host not in verdicts:
            verdicts[host] = await asyncio.to_thread(_url_is_safe_public, url)
        error = verdicts[host]
        if error:
            blocked.append({"url": url, "reason": error})
            logger.warning(f"capture_screenshot_tool: blocked request to '{url}': {error}")
            await route.abort("blockedbyclient")
        else:
            await route.continue_()

    await page.route("**/*", _guard)


@function_tool
async def capture_screenshot_tool(url: str, full_page: bool = False, wait_ms: int = 2000) -> Dict[str, Any]:
    """
    Captures a real screenshot of a PUBLIC web page with a headless browser
    (Playwright/Chromium) -- use this to illustrate a specific real tool's/
    product's actual interface in a technical post. A genuine screenshot builds
    more trust than a generic stock photo when the post is specifically about
    that tool.

    HARD REQUIREMENT: only call this with a URL that has already been verified as
    real by an earlier pipeline step (e.g. one of the post's own External Source
    Links) -- never a URL you construct, guess, or recall from training data. Same
    rule as internal links: a plausible-looking invented URL is worse than no
    screenshot at all.

    Scope limit: this cannot log in anywhere -- it only sees what a logged-out
    visitor sees. Not useful for an authenticated dashboard, and deliberately so:
    a public-only scope means there is no realistic risk of a credential or
    private data appearing in the captured image, so no redaction step is needed
    here (compare to a system that does capture authenticated pages, which must
    redact secrets before the image is ever used).

    Returns {"image_url": <local temp PNG path>, "alt_text": ..., "source_url": url}
    on success -- image_url is a local file path, the same shape
    get_stock_image_tool/generate_image_tool already return, so it can be handed
    straight to the same Sanity-upload path. Returns {"error": ...} on failure;
    the caller should fall back to get_stock_image_tool rather than treat this as
    fatal.
    """
    safety_error = _url_is_safe_public(url)
    if safety_error:
        logger.warning(f"capture_screenshot_tool: refused '{url}': {safety_error}")
        return {"error": safety_error}

    try:
        from playwright.async_api import async_playwright
    except ImportError:
        return {"error": "playwright is not installed in this environment."}

    local_path = None
    blocked: list = []
    try:
        async with async_playwright() as p:
            browser = await p.chromium.launch()
            try:
                page = await browser.new_page(viewport={"width": 1280, "height": 800})
                await _install_request_guard(page, blocked)
                await page.goto(url, timeout=20000, wait_until="load")
                await page.wait_for_timeout(wait_ms)
                with tempfile.NamedTemporaryFile(delete=False, suffix=".png") as tmp:
                    local_path = tmp.name
                await page.screenshot(path=local_path, full_page=full_page)
            finally:
                await browser.close()
    except Exception as e:
        logger.error(f"capture_screenshot_tool: failed to capture '{url}': {e}")
        if blocked:
            return {"error": f"Screenshot refused: the page tried to load a non-public address "
                             f"({blocked[0]['reason']})"}
        return {"error": f"Screenshot capture failed: {e}"}

    hostname = urlparse(url).hostname or url
    logger.info(f"capture_screenshot_tool: captured '{url}' -> {local_path}")
    return {
        "image_url": local_path,
        "alt_text": f"Screenshot of {hostname}",
        "source_url": url,
    }
