"""Turn judged candidates into one verdict. Pure: no I/O, no clock, no network."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum

from .models import MARKS, Candidate, InvalidInput, QueryResult, Repo
from .policy import Policy


class RepoState(str, Enum):
    ACTIVE = "active"
    STALE = "stale"
    DORMANT = "dormant"


class Verdict(str, Enum):
    TAKEN = "TAKEN"
    CONTESTED = "CONTESTED"
    ORPHANED = "ORPHANED"
    LOW_TRACTION = "LOW_TRACTION"
    OPEN = "OPEN"
    INCONCLUSIVE = "INCONCLUSIVE"


ABSENCE_BASED = frozenset({Verdict.LOW_TRACTION, Verdict.OPEN})
"""Verdicts that rest on not finding something, so they need complete evidence."""


@dataclass(frozen=True)
class Decision:
    verdict: Verdict
    reasons: tuple[str, ...]
    warnings: tuple[str, ...]
    leader: str | None
    same_count: int


def parse_time(value: str | None) -> datetime | None:
    """Parse a GitHub timestamp. Returns None when it is missing or malformed."""
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def repo_state(repo: Repo, now: datetime, policy: Policy) -> RepoState:
    """Classify a repository by how recently it was pushed to.

    Push recency is a proxy for maintenance, not proof of it.
    """
    if repo.archived:
        return RepoState.DORMANT
    pushed = parse_time(repo.pushed_at)
    if pushed is None:
        return RepoState.ACTIVE
    age_days = (now - pushed).total_seconds() / 86_400
    if age_days <= policy.active_days:
        return RepoState.ACTIVE
    if age_days <= policy.dormant_days:
        return RepoState.STALE
    return RepoState.DORMANT


def evidence_gaps(
    queries: Sequence[QueryResult],
    candidates: Sequence[Candidate],
    fetch_errors: Mapping[str, str] | None = None,
) -> tuple[str, ...]:
    """List what is missing from the evidence, in words fit for the report."""
    gaps: list[str] = []
    for name, error in (fetch_errors or {}).items():
        gaps.append(f"{name} was asked for by name and could not be loaded: {error}")
    for query in queries:
        if query.error:
            gaps.append(f"query '{query.query}' failed: {query.error}")
        elif query.incomplete:
            gaps.append(f"query '{query.query}' timed out on GitHub's side; results are partial")
    for candidate in candidates:
        if candidate.mark == "same":
            gaps.extend(f"{candidate.repo.full_name}: {e}" for e in candidate.inspection.errors)
    return tuple(gaps)


def decide(
    candidates: Sequence[Candidate],
    gaps: Sequence[str],
    now: datetime,
    policy: Policy,
) -> Decision:
    """Apply the verdict policy. Every input yields exactly one verdict."""
    for candidate in candidates:
        if candidate.mark not in MARKS:
            raise InvalidInput(f"unknown mark {candidate.mark!r} for {candidate.repo.full_name}")

    same = [c.repo for c in candidates if c.mark == "same"]
    states = {repo.full_name: repo_state(repo, now, policy) for repo in same}
    live = _most_starred([r for r in same if states[r.full_name] is not RepoState.DORMANT])
    dormant = _most_starred([r for r in same if states[r.full_name] is RepoState.DORMANT])

    verdict, leader, reasons = _classify(same, live, dormant, states, policy)
    warnings = list(gaps)
    warnings.extend(
        f"{repo.full_name} has no usable push date; it was counted as active"
        for repo in same
        if not repo.archived and parse_time(repo.pushed_at) is None
    )
    if gaps and verdict in ABSENCE_BASED:
        reasons = [
            f"The evidence is incomplete, so '{verdict.value}' cannot be claimed.",
            "Fix the gaps listed under warnings and run the check again.",
        ]
        verdict = Verdict.INCONCLUSIVE

    return Decision(
        verdict=verdict,
        reasons=tuple(reasons),
        warnings=tuple(warnings),
        leader=leader.full_name if leader else None,
        same_count=len(same),
    )


def _most_starred(repos: Sequence[Repo]) -> Repo | None:
    return max(repos, key=lambda repo: (repo.stars, repo.full_name), default=None)


def _classify(
    same: Sequence[Repo],
    live: Repo | None,
    dormant: Repo | None,
    states: dict[str, RepoState],
    policy: Policy,
) -> tuple[Verdict, Repo | None, list[str]]:
    if live and live.stars >= policy.traction_stars:
        big = live.stars >= policy.big_stars
        reasons = [
            f"{live.full_name} has {live.stars:,} stars and is {states[live.full_name].value}."
        ]
        if states[live.full_name] is RepoState.STALE:
            reasons.append(
                f"It is stale: no push for more than {policy.active_days} days. "
                "It may be slowing down."
            )
        reasons.append(
            "It owns this idea today. Building the same thing means competing with it."
            if big
            else f"It has traction but fewer than {policy.big_stars:,} stars. Nobody has won yet."
        )
        return (Verdict.TAKEN if big else Verdict.CONTESTED), live, reasons

    if dormant and dormant.stars >= policy.traction_stars:
        why = "archived" if dormant.archived else f"not pushed for over {policy.dormant_days} days"
        return (
            Verdict.ORPHANED,
            dormant,
            [
                f"{dormant.full_name} has {dormant.stars:,} stars but is {why}.",
                "People wanted this, and nobody is maintaining it.",
            ],
        )

    best = _most_starred(same)
    if len(same) >= policy.crowd_count:
        top = f"{best.stars:,}" if best else "0"
        return (
            Verdict.LOW_TRACTION,
            best,
            [
                f"{len(same)} repositories attempt this; the most starred has {top} stars.",
                f"None has reached {policy.traction_stars} stars. That can mean weak demand or "
                "weak execution; the numbers cannot tell which.",
            ],
        )

    found = "No repository" if not same else f"Only {len(same)}"
    return (
        Verdict.OPEN,
        best,
        [
            f"{found} doing the same thing was found, none with {policy.traction_stars} stars.",
            "This is not proof that nothing exists: only the listed queries were run.",
        ],
    )
