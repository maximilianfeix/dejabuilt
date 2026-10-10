"""A small read-only GitHub API client.

Design constraints (see docs/DESIGN.md):

- Requests go to one fixed host. No URL taken from a response is ever requested.
- Redirects are refused, so credentials cannot be forwarded to another host.
- The token never appears in an error message, a log line or a return value.
- Transport, clock, sleeper and the credential helper are injected, so tests
  run without a network and without waiting.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import time
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from typing import Any

API_BASE = "https://api.github.com"
USER_AGENT = "dejabuilt"
MAX_BODY_BYTES = 2_000_000
MAX_DETAIL_CHARS = 200
JSON = "application/vnd.github+json"
RAW = "application/vnd.github.raw+json"

STOP_KINDS = frozenset({"auth", "rate_limit", "secondary_rate_limit", "network"})
"""After one of these, the next request would fail the same way, so none is sent."""


class GitHubError(Exception):
    """A request failed. `kind` is stable and safe to show; so is the message."""

    def __init__(self, kind: str, message: str, status: int | None = None) -> None:
        super().__init__(message)
        self.kind = kind
        self.status = status

    def __str__(self) -> str:
        return f"{self.kind}: {self.args[0]}"


@dataclass(frozen=True)
class Response:
    status: int
    headers: Mapping[str, str] = field(default_factory=dict)
    body: bytes = b""

    def header(self, name: str) -> str | None:
        wanted = name.lower()
        return next((v for k, v in self.headers.items() if k.lower() == wanted), None)


Transport = Callable[[str, Mapping[str, str], float], Response]
Runner = Callable[..., "subprocess.CompletedProcess[str]"]


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args: Any, **kwargs: Any) -> None:
        return None


def urllib_transport(url: str, headers: Mapping[str, str], timeout: float) -> Response:
    """Perform one GET with the standard library. Never follows redirects."""
    opener = urllib.request.build_opener(_NoRedirect)
    request = urllib.request.Request(url, headers=dict(headers), method="GET")
    try:
        with opener.open(request, timeout=timeout) as reply:
            return Response(reply.status, dict(reply.headers.items()), reply.read(MAX_BODY_BYTES))
    except urllib.error.HTTPError as error:
        return Response(error.code, dict(error.headers.items()), error.read(MAX_BODY_BYTES))
    except (urllib.error.URLError, TimeoutError, OSError) as error:
        raise GitHubError("network", f"could not reach GitHub ({type(error).__name__})") from None


def discover_token(
    env: Mapping[str, str],
    which: Callable[[str], str | None] = shutil.which,
    run: Runner = subprocess.run,
) -> str | None:
    """Find a token: GH_TOKEN, GITHUB_TOKEN, then the GitHub CLI. None if there is none."""
    for name in ("GH_TOKEN", "GITHUB_TOKEN"):
        value = env.get(name, "").strip()
        if value:
            return value
    executable = which("gh")
    if not executable:
        return None
    try:
        result = run(
            [executable, "auth", "token", "--hostname", "github.com"],
            capture_output=True,
            text=True,
            timeout=5,
            shell=False,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    token = result.stdout.strip() if result.returncode == 0 else ""
    return token or None


class Client:
    """Read-only access to api.github.com with bounded rate-limit retries."""

    def __init__(
        self,
        token: str | None = None,
        transport: Transport = urllib_transport,
        sleep: Callable[[float], None] = time.sleep,
        clock: Callable[[], float] = time.time,
        max_retries: int = 2,
        max_wait: float = 60.0,
        timeout: float = 20.0,
    ) -> None:
        self._token = token
        self._transport = transport
        self._sleep = sleep
        self._clock = clock
        self._max_retries = max_retries
        self._max_wait = max_wait
        self._timeout = timeout
        self._stopped_by: str | None = None

    @property
    def authenticated(self) -> bool:
        return bool(self._token)

    def get_json(self, path: str, params: Mapping[str, str | int] | None = None) -> Any:
        response = self._request(path, params, JSON)
        try:
            return json.loads(response.body.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            raise GitHubError("server", "GitHub returned a body that is not JSON") from None

    def get_text(self, path: str, max_chars: int) -> str:
        response = self._request(path, None, RAW)
        return response.body.decode("utf-8", errors="replace")[:max_chars]

    def _request(self, path: str, params: Mapping[str, str | int] | None, accept: str) -> Response:
        url = build_url(path, params)
        if self._stopped_by:
            raise GitHubError(f"skipped after {self._stopped_by}", "request not sent")
        headers = {
            "Accept": accept,
            "User-Agent": USER_AGENT,
            "X-GitHub-Api-Version": "2022-11-28",
        }
        if self._token:
            headers["Authorization"] = f"Bearer {self._token}"

        attempt = 0
        while True:
            try:
                response = self._transport(url, headers, self._timeout)
            except GitHubError as unreachable:
                raise self._final(unreachable) from None
            if 200 <= response.status < 300:
                return response
            failure = self._to_error(response)
            wait = self._retry_wait(response, failure)
            if wait is None or attempt >= self._max_retries:
                raise self._final(failure)
            attempt += 1
            self._sleep(wait)

    def _final(self, error: GitHubError) -> GitHubError:
        """Remember a failure that would repeat, so later requests are not sent."""
        if error.kind in STOP_KINDS:
            self._stopped_by = error.kind
        return error

    def _retry_wait(self, response: Response, error: GitHubError) -> float | None:
        """Seconds to wait before retrying, or None if this failure is final."""
        if error.kind not in ("rate_limit", "secondary_rate_limit"):
            return None
        retry_after = _number(response.header("retry-after"))
        if retry_after is not None:
            wait = retry_after
        elif error.kind == "rate_limit":
            reset = _number(response.header("x-ratelimit-reset"))
            wait = (reset - self._clock() + 1) if reset is not None else self._max_wait + 1
        else:
            wait = self._max_wait
        return max(wait, 0.0) if wait <= self._max_wait else None

    def _to_error(self, response: Response) -> GitHubError:
        status = response.status
        detail = self._redact(_api_message(response.body))[:MAX_DETAIL_CHARS]
        if 300 <= status < 400:
            return GitHubError(
                "redirect", "GitHub answered with a redirect; it was refused", status
            )
        if status == 401:
            return GitHubError("auth", "GitHub rejected the credentials", status)
        if status in (403, 429):
            return self._forbidden(response, detail)
        if status == 404:
            return GitHubError("not_found", "not found", status)
        if status == 422:
            return GitHubError("invalid", f"GitHub rejected the request: {detail}", status)
        if status >= 500:
            return GitHubError("server", f"GitHub server error {status}", status)
        return GitHubError("http", f"unexpected HTTP status {status}", status)

    def _forbidden(self, response: Response, detail: str) -> GitHubError:
        status = response.status
        if response.header("x-ratelimit-remaining") == "0":
            hint = "" if self._token else " Set GH_TOKEN or log in with `gh auth login` for more."
            return GitHubError("rate_limit", f"GitHub rate limit reached.{hint}", status)
        if response.header("retry-after") or "secondary rate limit" in detail.lower():
            return GitHubError(
                "secondary_rate_limit", "GitHub asked to slow down (secondary rate limit)", status
            )
        if status == 429:
            return GitHubError("rate_limit", "GitHub rate limit reached", status)
        return GitHubError("forbidden", f"GitHub refused the request: {detail}", status)

    def _redact(self, text: str) -> str:
        return text.replace(self._token, "[redacted]") if self._token else text


def build_url(path: str, params: Mapping[str, str | int] | None = None) -> str:
    """Join a path onto the fixed API base. Rejects anything that could leave the host."""
    if not path.startswith("/") or path.startswith("//") or "://" in path or "\\" in path:
        raise GitHubError("invalid", "request path must be an absolute path on api.github.com")
    if any(ord(ch) < 0x21 or ord(ch) == 0x7F for ch in path) or "?" in path or "#" in path:
        raise GitHubError("invalid", "request path contains characters that are not allowed")
    query = f"?{urllib.parse.urlencode(params)}" if params else ""
    return f"{API_BASE}{path}{query}"


def _api_message(body: bytes) -> str:
    """The `message` field of a GitHub error body on one line; empty if there is none.

    Not shortened here: the caller must redact the token first, or a token cut in
    half by the limit would no longer match and its first half would be shown.
    """
    try:
        payload = json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return ""
    message = payload.get("message") if isinstance(payload, dict) else None
    return " ".join(message.split()) if isinstance(message, str) else ""


def _number(value: str | None) -> float | None:
    try:
        return float(value) if value is not None else None
    except ValueError:
        return None
