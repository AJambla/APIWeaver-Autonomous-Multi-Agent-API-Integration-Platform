"""Server-side fetch of a user-supplied URL (spec import), with SSRF guards.

The browser cannot fetch arbitrary origins (the page's CSP allows only its own), so the
API fetches on the user's behalf. That makes this an SSRF surface: every hop, including
redirects, is resolved and refused if it lands on a private, loopback, link-local or
metadata address, and the body is capped at the upload limit.
"""

from __future__ import annotations

from urllib.parse import urljoin

import httpx

from app.core.errors import UnprocessableEntityError
from app.services.sandbox_service import assert_public_target

MAX_REDIRECTS = 3
TIMEOUT_SECONDS = 15.0


async def fetch_text(url: str, *, max_bytes: int, allow_private: bool = False) -> tuple[str, str | None]:
    """GET `url` and return `(text, content_type)`; raises UnprocessableEntityError."""
    current = url
    async with httpx.AsyncClient(
        follow_redirects=False,
        timeout=TIMEOUT_SECONDS,
        headers={"Accept": "application/json, application/yaml, text/yaml, text/plain, */*"},
        trust_env=False,
    ) as client:
        for _ in range(MAX_REDIRECTS + 1):
            try:
                await assert_public_target(current, allow_private=allow_private)
            except ValueError as exc:
                raise UnprocessableEntityError(str(exc)) from exc
            try:
                async with client.stream("GET", current) as response:
                    if response.is_redirect:
                        location = response.headers.get("location")
                        if not location:
                            raise UnprocessableEntityError("Redirect without a Location header.")
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
            except httpx.HTTPError as exc:
                raise UnprocessableEntityError(f"Could not fetch the URL: {exc}") from exc
            if b"\x00" in body[:4096]:
                raise UnprocessableEntityError("The URL did not return a text document.")
            return body.decode("utf-8", errors="replace"), content_type
    raise UnprocessableEntityError("Too many redirects.")
