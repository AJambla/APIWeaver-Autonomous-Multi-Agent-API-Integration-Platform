"""Server-side fetch of a user-supplied URL (spec import), with SSRF guards.

The browser cannot fetch arbitrary origins (the page's CSP allows only its own), so the
API fetches on the user's behalf. That makes this an SSRF surface: every hop, including
redirects, is resolved and refused if it lands on a non-public address, and the body is
capped at the upload limit.

Each hop connects to the exact address that was vetted, with the original Host header
and TLS SNI (certificates are still verified against the real hostname). Checking the
name and then letting httpx resolve it again was a DNS-rebinding hole: a short-TTL record
could answer the check with a public address and the connection with 169.254.169.254.
"""

from __future__ import annotations

import asyncio
import ipaddress
from urllib.parse import urljoin, urlsplit, urlunsplit

import httpx

from app.core.errors import UnprocessableEntityError
from app.services.sandbox_service import resolve_public_address

MAX_REDIRECTS = 3
TIMEOUT_SECONDS = 15.0
# Per-operation timeouts alone let a server drip one byte per read indefinitely.
TOTAL_DEADLINE_SECONDS = 60.0


async def _pinned_request(url: str, *, allow_private: bool) -> tuple[str, dict[str, str], dict]:
    """(url to connect to, extra headers, request extensions) for one hop."""
    parts = urlsplit(url)
    if parts.scheme not in ("http", "https") or not parts.hostname:
        raise UnprocessableEntityError(f"Only absolute http(s) URLs can be fetched, got {url!r}.")
    if allow_private:
        return url, {}, {}
    port = parts.port or (443 if parts.scheme == "https" else 80)
    try:
        address = await resolve_public_address(parts.hostname, port)
    except ValueError as exc:
        raise UnprocessableEntityError(str(exc)) from exc
    host_literal = f"[{address}]" if ipaddress.ip_address(address).version == 6 else address
    netloc = f"{host_literal}:{parts.port}" if parts.port else host_literal
    pinned = urlunsplit((parts.scheme, netloc, parts.path or "/", parts.query, ""))
    host_header = f"{parts.hostname}:{parts.port}" if parts.port else parts.hostname
    extensions = {"sni_hostname": parts.hostname} if parts.scheme == "https" else {}
    return pinned, {"Host": host_header}, extensions


async def fetch_text(url: str, *, max_bytes: int, allow_private: bool = False) -> tuple[str, str | None]:
    """GET `url` and return `(text, content_type)`; raises UnprocessableEntityError."""
    try:
        async with asyncio.timeout(TOTAL_DEADLINE_SECONDS):
            return await _fetch(url, max_bytes=max_bytes, allow_private=allow_private)
    except TimeoutError as exc:
        raise UnprocessableEntityError("Fetching the URL took too long.") from exc


async def _fetch(url: str, *, max_bytes: int, allow_private: bool) -> tuple[str, str | None]:
    current = url
    async with httpx.AsyncClient(
        follow_redirects=False,
        timeout=TIMEOUT_SECONDS,
        headers={"Accept": "application/json, application/yaml, text/yaml, text/plain, */*"},
        trust_env=False,
    ) as client:
        for _ in range(MAX_REDIRECTS + 1):
            target, headers, extensions = await _pinned_request(current, allow_private=allow_private)
            try:
                request = client.build_request("GET", target, headers=headers, extensions=extensions)
                response = await client.send(request, stream=True)
                try:
                    if response.is_redirect:
                        location = response.headers.get("location")
                        if not location:
                            raise UnprocessableEntityError("Redirect without a Location header.")
                        # Resolve against the *original* URL, never the pinned address.
                        current = urljoin(current, location)
                        continue
                    if response.status_code >= 400:
                        raise UnprocessableEntityError(
                            f"The URL answered {response.status_code} {response.reason_phrase}."
                        )
                    declared = response.headers.get("content-length")
                    if declared and declared.isdigit() and int(declared) > max_bytes:
                        raise UnprocessableEntityError("The document is larger than the upload limit.")
                    chunks: list[bytes] = []
                    size = 0
                    async for chunk in response.aiter_bytes():
                        size += len(chunk)
                        if size > max_bytes:
                            raise UnprocessableEntityError("The document is larger than the upload limit.")
                        chunks.append(chunk)
                    body = b"".join(chunks)
                    content_type = response.headers.get("content-type")
                finally:
                    await response.aclose()
            except httpx.HTTPError as exc:
                raise UnprocessableEntityError(f"Could not fetch the URL: {exc}") from exc
            if b"\x00" in body[:4096]:
                raise UnprocessableEntityError("The URL did not return a text document.")
            return body.decode("utf-8", errors="replace"), content_type
    raise UnprocessableEntityError("Too many redirects.")
