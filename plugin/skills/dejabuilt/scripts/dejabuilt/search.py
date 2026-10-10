"""Run several search queries and merge what they find."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import replace
from typing import Any

from .github import Client, GitHubError
from .models import InvalidInput, QueryResult, Repo
from .sanitize import clean

MAX_QUERIES = 20
MAX_QUERY_LENGTH = 256
MAX_LIMIT = 100


def normalize_queries(queries: Sequence[str]) -> tuple[str, ...]:
    """Trim, drop blanks and duplicates, and check GitHub's limits."""
    unique = tuple(dict.fromkeys(" ".join(q.split()) for q in queries if q.strip()))
    if not unique:
        raise InvalidInput("at least one non-empty query is required")
    if len(unique) > MAX_QUERIES:
        raise InvalidInput(f"at most {MAX_QUERIES} queries per run, got {len(unique)}")
    too_long = [q for q in unique if len(q) > MAX_QUERY_LENGTH]
    if too_long:
        raise InvalidInput(f"query longer than {MAX_QUERY_LENGTH} characters: {too_long[0][:40]}…")
    return unique


def repo_from_api(item: Mapping[str, Any]) -> Repo:
    """Convert a repository object from the API, sanitizing every text field."""
    return Repo(
        id=_count(item.get("id")),
        full_name=clean(item.get("full_name"), 140),
        url=clean(item.get("html_url"), 200),
        description=clean(item.get("description")),
        stars=_count(item.get("stargazers_count")),
        forks=_count(item.get("forks_count")),
        open_issues=_count(item.get("open_issues_count")),
        archived=bool(item.get("archived")),
        created_at=clean(item.get("created_at"), 40) or None,
        pushed_at=clean(item.get("pushed_at"), 40) or None,
        language=clean(item.get("language"), 40) or None,
    )


def search(
    client: Client, queries: Sequence[str], limit: int = 20
) -> tuple[tuple[QueryResult, ...], tuple[Repo, ...]]:
    """Run each query once, sorted by stars, and merge the results by repository id.

    A failed query is recorded, never raised: results gathered so far are kept.
    After a failure that would repeat (see `github.STOP_KINDS`) the client sends
    nothing more, and the remaining queries are recorded as skipped.
    """
    if not 1 <= limit <= MAX_LIMIT:
        raise InvalidInput(f"limit must be between 1 and {MAX_LIMIT}")
    results: list[QueryResult] = []
    merged: dict[int, Repo] = {}

    for query in normalize_queries(queries):
        try:
            payload = client.get_json(
                "/search/repositories",
                {"q": query, "sort": "stars", "order": "desc", "per_page": limit},
            )
            items = _items(payload)
        except GitHubError as error:
            results.append(QueryResult(query=query, error=str(error)))
            continue
        results.append(
            QueryResult(
                query=query,
                total_count=_count(payload.get("total_count")),
                returned=len(items),
                incomplete=bool(payload.get("incomplete_results")),
            )
        )
        for item in items:
            _merge(merged, repo_from_api(item), query)

    ranked = sorted(merged.values(), key=lambda repo: (-repo.stars, repo.full_name.lower()))
    return tuple(results), tuple(ranked)


def _merge(merged: dict[int, Repo], repo: Repo, query: str) -> None:
    known = merged.get(repo.id)
    queries = (*known.matched_queries, query) if known else (query,)
    merged[repo.id] = replace(repo, matched_queries=queries)


def _items(payload: Any) -> list[Mapping[str, Any]]:
    if not isinstance(payload, Mapping):
        raise GitHubError("server", "GitHub returned an unexpected search result")
    items = payload.get("items") or []
    return [item for item in items if isinstance(item, Mapping) and item.get("full_name")]


def _count(value: Any) -> int:
    return value if isinstance(value, int) and not isinstance(value, bool) and value >= 0 else 0
