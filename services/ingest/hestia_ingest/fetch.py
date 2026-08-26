"""The one thin HTTP shim.

Everything interesting happens in the pure builders and mappers; this module
only executes a prepared request and hands back parsed JSON plus the raw text
for the ingestion_runs ledger. Errors are typed, small, and tested against a
local socket — never the live provider.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field


class FetchError(Exception):
    """A transport or decode failure, carrying the provider for the run log."""

    def __init__(self, provider: str, detail: str) -> None:
        super().__init__(f"{provider}: {detail}")
        self.provider = provider
        self.detail = detail


@dataclass(frozen=True)
class ProviderRequest:
    provider: str
    url: str
    params: dict[str, str] = field(default_factory=dict)

    @property
    def full_url(self) -> str:
        if not self.params:
            return self.url
        return f"{self.url}?{urllib.parse.urlencode(self.params)}"


@dataclass(frozen=True)
class FetchResult:
    payload: dict
    raw_text: str


MAX_RESPONSE_BYTES = 5_000_000


def fetch_json(request: ProviderRequest, timeout_seconds: float = 30.0) -> FetchResult:
    """Execute a prepared request; JSON in, JSON out, everything else raises."""
    if not request.url.startswith(("https://", "http://localhost", "http://127.0.0.1")):
        raise FetchError(request.provider, f"refusing non-https url {request.url!r}")
    try:
        with urllib.request.urlopen(request.full_url, timeout=timeout_seconds) as response:  # noqa: S310
            body = response.read(MAX_RESPONSE_BYTES + 1)
    except urllib.error.HTTPError as error:
        raise FetchError(request.provider, f"HTTP {error.code}") from error
    except (urllib.error.URLError, TimeoutError, OSError) as error:
        raise FetchError(request.provider, f"transport failure: {error}") from error
    if len(body) > MAX_RESPONSE_BYTES:
        raise FetchError(request.provider, "response exceeded the size bound")
    text = body.decode("utf-8", errors="replace")
    try:
        payload = json.loads(text)
    except json.JSONDecodeError as error:
        raise FetchError(request.provider, f"response was not JSON: {error}") from error
    if not isinstance(payload, dict):
        raise FetchError(request.provider, "response JSON was not an object")
    return FetchResult(payload=payload, raw_text=text)
