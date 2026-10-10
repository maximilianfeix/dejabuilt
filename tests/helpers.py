"""Builders and fakes shared by the tests. Nothing here touches the network."""

from __future__ import annotations

import json
import zlib
from collections.abc import Mapping
from datetime import datetime, timedelta, timezone
from typing import Any

from dejabuilt.github import Client, Response
from dejabuilt.models import Candidate, Inspection, QueryResult, Repo

NOW = datetime(2026, 10, 10, 12, 0, 0, tzinfo=timezone.utc)
TOKEN = "ghp_test_token_0123456789"


def days_ago(days: float) -> str:
    return (NOW - timedelta(days=days)).strftime("%Y-%m-%dT%H:%M:%SZ")


def make_repo(
    name: str = "someone/thing",
    *,
    stars: int = 10,
    pushed_days_ago: float | None = 1,
    archived: bool = False,
    repo_id: int | None = None,
    description: str = "A thing",
) -> Repo:
    return Repo(
        id=repo_id if repo_id is not None else zlib.crc32(name.encode()),
        full_name=name,
        url=f"https://github.com/{name}",
        description=description,
        stars=stars,
        archived=archived,
        created_at=days_ago(400),
        pushed_at=None if pushed_days_ago is None else days_ago(pushed_days_ago),
    )


def make_candidate(
    name: str = "someone/thing",
    *,
    mark: str = "same",
    inspection: Inspection | None = None,
    **repo_fields: Any,
) -> Candidate:
    return Candidate(
        repo=make_repo(name, **repo_fields),
        inspection=inspection or Inspection(),
        mark=mark,
        reason="does the same thing",
    )


def ok_query(query: str = "q", total: int = 5, returned: int = 5) -> QueryResult:
    return QueryResult(query=query, total_count=total, returned=returned)


def json_response(
    payload: Any, status: int = 200, headers: Mapping[str, str] | None = None
) -> Response:
    return Response(status=status, headers=dict(headers or {}), body=json.dumps(payload).encode())


def api_repo(
    name: str = "someone/thing", *, repo_id: int = 1, stars: int = 10, **extra: Any
) -> dict[str, Any]:
    """A repository the way the GitHub API returns it."""
    item: dict[str, Any] = {
        "id": repo_id,
        "full_name": name,
        "html_url": f"https://github.com/{name}",
        "description": "A thing",
        "stargazers_count": stars,
        "forks_count": 1,
        "open_issues_count": 2,
        "archived": False,
        "created_at": days_ago(400),
        "pushed_at": days_ago(1),
        "language": "Python",
    }
    item.update(extra)
    return item


class Seq:
    """Answers given one after another; the last one repeats."""

    def __init__(self, *answers: Any) -> None:
        self.answers = list(answers)

    def next(self) -> Any:
        return self.answers.pop(0) if len(self.answers) > 1 else self.answers[0]


class FakeTransport:
    """Answers requests from a table of path prefixes and records every call.

    An answer is a Response, an exception to raise, a `Seq` of answers, or any
    other value, which is sent as a JSON body.
    """

    def __init__(self, routes: Mapping[str, Any] | None = None) -> None:
        self.routes: dict[str, Any] = dict(routes or {})
        self.calls: list[tuple[str, dict[str, str]]] = []

    def __call__(self, url: str, headers: Mapping[str, str], timeout: float) -> Response:
        self.calls.append((url, dict(headers)))
        path = url.removeprefix("https://api.github.com")
        for prefix in sorted(self.routes, key=len, reverse=True):
            if path.startswith(prefix):
                return self._next(prefix)
        return json_response({"message": "Not Found"}, status=404)

    def _next(self, prefix: str) -> Response:
        answer = self.routes[prefix]
        if isinstance(answer, Seq):
            answer = answer.next()
        if isinstance(answer, Exception):
            raise answer
        if isinstance(answer, Response):
            return answer
        return json_response(answer)

    @property
    def paths(self) -> list[str]:
        return [url.removeprefix("https://api.github.com") for url, _ in self.calls]


class FakeClock:
    def __init__(self, start: float = 1_000_000.0) -> None:
        self.now = start
        self.sleeps: list[float] = []

    def time(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.now += seconds


def make_client(
    routes: Mapping[str, Any] | None = None,
    *,
    token: str | None = TOKEN,
    clock: FakeClock | None = None,
) -> tuple[Client, FakeTransport, FakeClock]:
    transport = FakeTransport(routes)
    clock = clock or FakeClock()
    client = Client(token=token, transport=transport, sleep=clock.sleep, clock=clock.time)
    return client, transport, clock
