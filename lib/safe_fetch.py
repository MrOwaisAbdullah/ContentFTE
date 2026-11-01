"""Outbound fetches of URLs we did not choose (plan SEC-05).

Markdown images, link targets, "fetch this page's title" tool calls and the WordPress connection test
all take a URL from an LLM draft (which ingests untrusted web research) or from a caller. Fetching it
naively lets `http://169.254.169.254/...`, `http://localhost:8000/mcp`, or a public URL that 302s to
one of those turn the engine into a request proxy into its own network. The old code also had no
timeout and no size limit.

`safe_get` / `safe_head` are drop-in replacements for `requests.get` / `requests.head` that:
  * allow only http(s);
  * resolve the host and refuse it if ANY address is not globally routable (loopback, private
    ranges, link-local/cloud-metadata, multicast, reserved, IPv4-mapped IPv6 of those, ...);
  * follow redirects manually, re-validating every hop (max 3);
  * never forward credentials (Authorization / Cookie / X-Site-Key / basic auth) to a different host;
  * cap the body size and always set a timeout.

Known limit: the host is resolved here and again by `requests` when it connects, so a DNS-rebinding
attacker with control of a name's TTL could still win that race. That is a much harder attack than the
direct ones this closes; pin-by-IP would break TLS certificate checks, so it is deliberately not done.

Local development against a private host (e.g. a WordPress on localhost) is explicit:
`SAFE_FETCH_ALLOW_PRIVATE=1`.
"""
from __future__ import annotations

import ipaddress
import os
import socket
from typing import Any, Mapping, Optional
from urllib.parse import urljoin, urlsplit

import requests

MAX_REDIRECTS = 3
DEFAULT_TIMEOUT = 15.0
DEFAULT_MAX_BYTES = 15 * 1024 * 1024
_CREDENTIAL_HEADERS = {"authorization", "cookie", "x-site-key", "proxy-authorization"}
_TRUTHY = ("1", "true", "yes", "on")


class UnsafeURL(ValueError):
    """The URL points somewhere this engine must not fetch from."""


def private_hosts_allowed() -> bool:
    return os.environ.get("SAFE_FETCH_ALLOW_PRIVATE", "").strip().lower() in _TRUTHY


def _is_public_ip(raw: str) -> bool:
    try:
        ip = ipaddress.ip_address(raw.split("%", 1)[0])  # strip an IPv6 zone id
    except ValueError:
        return False
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped is not None:
        ip = ip.ipv4_mapped                                  # ::ffff:127.0.0.1 is 127.0.0.1
    return ip.is_global and not ip.is_multicast


def check_url(url: str, *, resolver=socket.getaddrinfo) -> str:
    """Return `url` if it is safe to fetch, else raise UnsafeURL. `resolver` is injectable for tests."""
    parts = urlsplit((url or "").strip())
    if parts.scheme not in ("http", "https"):
        raise UnsafeURL(f"only http(s) URLs are allowed, got '{parts.scheme or 'none'}'")
    host = parts.hostname
    if not host:
        raise UnsafeURL("URL has no host")
    if parts.username or parts.password:
        raise UnsafeURL("URLs with embedded credentials are not allowed")
    if private_hosts_allowed():
        return url
    try:
        infos = resolver(host, parts.port or (443 if parts.scheme == "https" else 80),
                         type=socket.SOCK_STREAM)
    except OSError as exc:
        raise UnsafeURL(f"cannot resolve '{host}': {exc}") from exc
    addresses = {info[4][0] for info in infos}
    if not addresses:
        raise UnsafeURL(f"'{host}' did not resolve")
    blocked = sorted(a for a in addresses if not _is_public_ip(a))
    if blocked:
        raise UnsafeURL(f"'{host}' resolves to a non-public address ({blocked[0]})")
    return url


def _strip_credentials(headers: Mapping[str, str]) -> dict:
    return {k: v for k, v in headers.items() if k.lower() not in _CREDENTIAL_HEADERS}


def safe_request(method: str, url: str, *, timeout: float = DEFAULT_TIMEOUT,
                 max_bytes: Optional[int] = DEFAULT_MAX_BYTES,
                 headers: Optional[Mapping[str, str]] = None, auth: Any = None,
                 max_redirects: int = MAX_REDIRECTS, resolver=socket.getaddrinfo,
                 **kwargs: Any) -> requests.Response:
    """`requests.request` with every guard above. Raises UnsafeURL for a disallowed target, or
    requests exceptions for ordinary network errors."""
    current = url
    hdrs = dict(headers or {})
    creds = auth
    origin = (urlsplit(url).hostname or "").lower()
    for _hop in range(max_redirects + 1):
        check_url(current, resolver=resolver)
        resp = requests.request(method, current, headers=hdrs, auth=creds, timeout=timeout,
                                allow_redirects=False, stream=True, **kwargs)
        location = resp.headers.get("Location")
        if resp.status_code in (301, 302, 303, 307, 308) and location:
            resp.close()
            current = urljoin(current, location)
            if (urlsplit(current).hostname or "").lower() != origin:
                hdrs, creds = _strip_credentials(hdrs), None      # never leak credentials cross-host
            if resp.status_code == 303:
                method = "GET"
            continue
        if method.upper() != "HEAD":
            _read_capped(resp, max_bytes)
        return resp
    raise UnsafeURL(f"too many redirects (> {max_redirects})")


def _read_capped(resp: requests.Response, max_bytes: Optional[int]) -> None:
    """Load the body into the response, refusing anything larger than `max_bytes`."""
    declared = resp.headers.get("Content-Length")
    if max_bytes is not None and declared and declared.isdigit() and int(declared) > max_bytes:
        resp.close()
        raise UnsafeURL(f"response is {declared} bytes, over the {max_bytes}-byte limit")
    chunks, total = [], 0
    for chunk in resp.iter_content(chunk_size=64 * 1024):
        total += len(chunk)
        if max_bytes is not None and total > max_bytes:
            resp.close()
            raise UnsafeURL(f"response exceeded the {max_bytes}-byte limit")
        chunks.append(chunk)
    resp._content = b"".join(chunks)          # what requests itself does after a full read
    resp._content_consumed = True


def safe_get(url: str, **kwargs: Any) -> requests.Response:
    return safe_request("GET", url, **kwargs)


def safe_head(url: str, **kwargs: Any) -> requests.Response:
    return safe_request("HEAD", url, **kwargs)
