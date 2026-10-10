from __future__ import annotations

import itertools

import pytest

from dejabuilt.models import Inspection, InvalidInput, QueryResult
from dejabuilt.policy import Policy
from dejabuilt.verdict import RepoState, Verdict, decide, evidence_gaps, repo_state
from tests.helpers import NOW, make_candidate, make_repo, ok_query

POLICY = Policy()


class TestRepoState:
    @pytest.mark.parametrize(
        ("days", "expected"),
        [
            (0, RepoState.ACTIVE),
            (180, RepoState.ACTIVE),
            (180.01, RepoState.STALE),
            (365, RepoState.STALE),
            (365.01, RepoState.DORMANT),
            (2000, RepoState.DORMANT),
        ],
    )
    def test_boundaries(self, days: float, expected: RepoState) -> None:
        assert repo_state(make_repo(pushed_days_ago=days), NOW, POLICY) is expected

    def test_archived_is_dormant_even_when_pushed_yesterday(self) -> None:
        repo = make_repo(pushed_days_ago=1, archived=True)
        assert repo_state(repo, NOW, POLICY) is RepoState.DORMANT

    def test_missing_push_date_counts_as_active(self) -> None:
        assert repo_state(make_repo(pushed_days_ago=None), NOW, POLICY) is RepoState.ACTIVE

    def test_push_date_in_the_future_counts_as_active(self) -> None:
        assert repo_state(make_repo(pushed_days_ago=-2), NOW, POLICY) is RepoState.ACTIVE

    def test_unparseable_push_date_counts_as_active(self) -> None:
        repo = make_repo()
        broken = type(repo)(**{**repo.__dict__, "pushed_at": "yesterday"})
        assert repo_state(broken, NOW, POLICY) is RepoState.ACTIVE


class TestDecide:
    def test_no_candidates_is_open(self) -> None:
        assert decide([], [], NOW, POLICY).verdict is Verdict.OPEN

    @pytest.mark.parametrize(
        ("stars", "expected"),
        [
            (199, Verdict.OPEN),
            (200, Verdict.CONTESTED),
            (1999, Verdict.CONTESTED),
            (2000, Verdict.TAKEN),
        ],
    )
    def test_star_boundaries_for_one_active_repo(self, stars: int, expected: Verdict) -> None:
        decision = decide([make_candidate(stars=stars)], [], NOW, POLICY)
        assert decision.verdict is expected

    def test_stale_leader_still_takes_the_idea(self) -> None:
        decision = decide([make_candidate(stars=3000, pushed_days_ago=250)], [], NOW, POLICY)
        assert decision.verdict is Verdict.TAKEN
        assert any("stale" in reason for reason in decision.reasons)

    def test_dormant_repo_with_traction_is_orphaned(self) -> None:
        decision = decide([make_candidate(stars=1000, pushed_days_ago=400)], [], NOW, POLICY)
        assert decision.verdict is Verdict.ORPHANED

    def test_archived_giant_pushed_yesterday_is_orphaned_not_taken(self) -> None:
        candidate = make_candidate(stars=50_000, pushed_days_ago=1, archived=True)
        assert decide([candidate], [], NOW, POLICY).verdict is Verdict.ORPHANED

    def test_active_competitor_beats_archived_giant(self) -> None:
        candidates = [
            make_candidate("old/giant", stars=5000, archived=True),
            make_candidate("new/contender", stars=300),
        ]
        decision = decide(candidates, [], NOW, POLICY)
        assert decision.verdict is Verdict.CONTESTED
        assert decision.leader == "new/contender"

    def test_dormant_repo_below_traction_does_not_count_as_orphaned(self) -> None:
        decision = decide([make_candidate(stars=150, pushed_days_ago=900)], [], NOW, POLICY)
        assert decision.verdict is Verdict.OPEN

    def test_three_attempts_without_traction(self) -> None:
        candidates = [make_candidate(f"a/{n}", stars=20 * n) for n in range(1, 4)]
        decision = decide(candidates, [], NOW, POLICY)
        assert decision.verdict is Verdict.LOW_TRACTION
        assert decision.same_count == 3

    def test_two_attempts_without_traction_is_open(self) -> None:
        candidates = [make_candidate(f"a/{n}", stars=20) for n in range(2)]
        assert decide(candidates, [], NOW, POLICY).verdict is Verdict.OPEN

    def test_adjacent_and_unrelated_do_not_drive_the_verdict(self) -> None:
        candidates = [
            make_candidate("big/adjacent", mark="adjacent", stars=90_000),
            make_candidate("big/unrelated", mark="unrelated", stars=90_000),
        ]
        decision = decide(candidates, [], NOW, POLICY)
        assert decision.verdict is Verdict.OPEN
        assert decision.same_count == 0

    def test_leader_is_the_most_starred_live_repo(self) -> None:
        candidates = [make_candidate("a/small", stars=300), make_candidate("a/large", stars=900)]
        assert decide(candidates, [], NOW, POLICY).leader == "a/large"

    def test_missing_push_date_adds_a_warning(self) -> None:
        decision = decide([make_candidate(pushed_days_ago=None)], [], NOW, POLICY)
        assert any("push date" in warning for warning in decision.warnings)

    def test_unknown_mark_is_rejected(self) -> None:
        with pytest.raises(InvalidInput):
            decide([make_candidate(mark="maybe")], [], NOW, POLICY)

    def test_custom_policy_moves_the_line(self) -> None:
        policy = Policy(big_stars=500, traction_stars=50)
        assert decide([make_candidate(stars=600)], [], NOW, policy).verdict is Verdict.TAKEN


class TestIncompleteEvidence:
    GAP = ("query 'x' failed: rate_limit",)

    @pytest.mark.parametrize("count", [0, 1, 2, 3, 6])
    def test_absence_based_verdicts_become_inconclusive(self, count: int) -> None:
        candidates = [make_candidate(f"a/{n}", stars=5) for n in range(count)]
        decision = decide(candidates, self.GAP, NOW, POLICY)
        assert decision.verdict is Verdict.INCONCLUSIVE
        assert self.GAP[0] in decision.warnings

    @pytest.mark.parametrize(
        ("candidate", "expected"),
        [
            (make_candidate(stars=5000), Verdict.TAKEN),
            (make_candidate(stars=500), Verdict.CONTESTED),
            (make_candidate(stars=500, archived=True), Verdict.ORPHANED),
        ],
    )
    def test_verdicts_resting_on_a_finding_stand(
        self, candidate: object, expected: Verdict
    ) -> None:
        decision = decide([candidate], self.GAP, NOW, POLICY)  # type: ignore[list-item]
        assert decision.verdict is expected
        assert self.GAP[0] in decision.warnings


class TestEvidenceGaps:
    def test_complete_evidence_has_no_gaps(self) -> None:
        assert evidence_gaps([ok_query()], [make_candidate()]) == ()

    def test_failed_query_is_a_gap(self) -> None:
        gaps = evidence_gaps([QueryResult(query="x", error="rate_limit")], [])
        assert gaps == ("query 'x' failed: rate_limit",)

    def test_api_incomplete_flag_is_a_gap(self) -> None:
        gaps = evidence_gaps(
            [QueryResult(query="x", total_count=3, returned=3, incomplete=True)], []
        )
        assert len(gaps) == 1
        assert "timed out" in gaps[0]

    def test_results_beyond_the_limit_are_not_a_gap(self) -> None:
        assert evidence_gaps([ok_query(total=900, returned=20)], []) == ()

    def test_failed_inspection_of_a_same_candidate_is_a_gap(self) -> None:
        candidate = make_candidate(inspection=Inspection(errors=("releases: server",)))
        assert evidence_gaps([], [candidate]) == ("someone/thing: releases: server",)

    def test_failed_inspection_of_an_unrelated_candidate_is_ignored(self) -> None:
        candidate = make_candidate(mark="unrelated", inspection=Inspection(errors=("x",)))
        assert evidence_gaps([], [candidate]) == ()


def _shape_groups() -> list[tuple[tuple[int, float, bool], ...]]:
    stars = [0, 199, 200, 1999, 2000, 50_000]
    ages = [1.0, 250.0, 500.0]
    shapes = list(itertools.product(stars, ages, [False, True]))
    singles = [(shape,) for shape in shapes]
    pairs = list(itertools.product(shapes, repeat=2))
    triples = [(a, b, c) for a, b, c in zip(shapes, shapes[1:], shapes[2:], strict=False)]
    return [*singles, *pairs, *triples]


def test_every_input_gets_exactly_one_verdict() -> None:
    """Sweep states, star counts, candidate counts and evidence: nothing falls through."""
    seen: set[Verdict] = set()
    for group in _shape_groups():
        candidates = [
            make_candidate(f"a/{i}", stars=stars, pushed_days_ago=age, archived=archived)
            for i, (stars, age, archived) in enumerate(group)
        ]
        for gaps in ((), ("gap",)):
            decision = decide(candidates, gaps, NOW, POLICY)
            assert isinstance(decision.verdict, Verdict)
            assert decision.reasons
            seen.add(decision.verdict)
    assert seen == set(Verdict)
