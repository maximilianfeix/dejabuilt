from __future__ import annotations

from typing import Any

import pytest

from dejabuilt.models import (
    SCHEMA_VERSION,
    Inspection,
    InvalidInput,
    PlatformHint,
    QueryResult,
    Repo,
    State,
)
from dejabuilt.policy import POLICY_VERSION, Policy
from tests.helpers import make_repo


def sample_state() -> State:
    repo = make_repo("a/b", stars=5, repo_id=9)
    seen = Inspection(
        release_tag="v1",
        release_at="2026-10-01T00:00:00Z",
        releases_seen=1,
        asset_names=("a.exe",),
        platforms=(PlatformHint("windows", "release-asset"),),
        errors=("README could not be read (server)",),
    )
    return State(
        observed_at="2026-10-10T12:00:00Z",
        queries=(QueryResult("q", total_count=3, returned=1, incomplete=True, error=None),),
        repos=(repo,),
        inspections={"a/b": seen},
        fetch_errors={"gone/repo": "not_found: not found"},
    )


def test_state_survives_a_round_trip() -> None:
    state = sample_state()
    assert State.from_dict(state.to_dict()) == state


def test_state_records_the_schema_version() -> None:
    assert sample_state().to_dict()["schema_version"] == SCHEMA_VERSION


@pytest.mark.parametrize(
    "broken",
    [
        [],
        "text",
        {"schema_version": 99, "observed_at": "x"},
        {"schema_version": SCHEMA_VERSION},
        {"schema_version": SCHEMA_VERSION, "observed_at": "x", "repos": {}},
        {"schema_version": SCHEMA_VERSION, "observed_at": "x", "repos": ["nope"]},
        {"schema_version": SCHEMA_VERSION, "observed_at": "x", "inspections": []},
        {"schema_version": SCHEMA_VERSION, "observed_at": "x", "inspections": {"a/b": 3}},
        {"schema_version": SCHEMA_VERSION, "observed_at": "x", "queries": [{"query": ""}]},
        {"schema_version": SCHEMA_VERSION, "observed_at": "x", "fetch_errors": ["a/b"]},
    ],
)
def test_malformed_state_is_rejected(broken: Any) -> None:
    with pytest.raises(InvalidInput):
        State.from_dict(broken)


@pytest.mark.parametrize(
    "fields",
    [
        {"stars": -1},
        {"stars": "12"},
        {"stars": True},
        {"id": 1.5},
        {"full_name": ""},
        {"url": None},
        {"pushed_at": 20261010},
    ],
)
def test_malformed_repo_is_rejected(fields: dict[str, Any]) -> None:
    good = make_repo().to_dict()
    with pytest.raises(InvalidInput):
        Repo.from_dict({**good, **fields})


def test_query_result_counts_what_was_not_looked_at() -> None:
    assert QueryResult("q", total_count=900, returned=20).not_looked_at == 880
    assert QueryResult("q", total_count=3, returned=20).not_looked_at == 0


class TestPolicy:
    def test_defaults_are_documented_values(self) -> None:
        assert Policy().to_dict() == {
            "policy_version": POLICY_VERSION,
            "big_stars": 2000,
            "traction_stars": 200,
            "active_days": 180,
            "dormant_days": 365,
            "crowd_count": 3,
        }

    @pytest.mark.parametrize(
        "fields",
        [
            {"traction_stars": 0},
            {"big_stars": 100, "traction_stars": 200},
            {"active_days": 0},
            {"active_days": 400, "dormant_days": 365},
            {"crowd_count": 0},
        ],
    )
    def test_inconsistent_thresholds_are_rejected(self, fields: dict[str, int]) -> None:
        with pytest.raises(InvalidInput):
            Policy(**fields)
