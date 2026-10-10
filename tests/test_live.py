"""One test against the real GitHub API. Skipped unless DEJABUILT_LIVE=1."""

from __future__ import annotations

import os

import pytest

from dejabuilt.github import Client, discover_token
from dejabuilt.inspection import inspect_repo
from dejabuilt.search import search

pytestmark = [
    pytest.mark.live,
    pytest.mark.skipif(os.environ.get("DEJABUILT_LIVE") != "1", reason="set DEJABUILT_LIVE=1"),
]


def test_search_and_inspect_against_github() -> None:
    client = Client(token=discover_token(os.environ))
    queries, repos = search(client, ["cpython in:name"], limit=5)
    assert queries[0].error is None
    assert "python/cpython" in [repo.full_name for repo in repos]
    assert inspect_repo(client, "python/cpython").errors == ()
