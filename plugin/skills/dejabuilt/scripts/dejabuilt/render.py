"""Build the report and print it as JSON or Markdown. Pure."""

from __future__ import annotations

import json
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Any
from urllib.parse import quote

from .models import SCHEMA_VERSION, Candidate, QueryResult
from .policy import Policy
from .sanitize import clean, markdown
from .verdict import Decision, Verdict, parse_time, repo_state

NOT_CHECKED = (
    "Code hosts other than GitHub (GitLab, Codeberg, Bitbucket).",
    "Closed-source products, app stores and package registries.",
    "Repositories that describe the idea in words none of the queries used.",
    "Private repositories and work that has not been published yet.",
)

HEADLINES = {
    Verdict.TAKEN: "Someone already owns this idea.",
    Verdict.CONTESTED: "Others are working on this and none has won yet.",
    Verdict.ORPHANED: "This was built, people wanted it, and it is no longer maintained.",
    Verdict.LOW_TRACTION: "Several people tried this and none gained traction.",
    Verdict.OPEN: "Nothing that does the same thing was found.",
    Verdict.INCONCLUSIVE: "The search was incomplete, so no claim can be made.",
}

OPEN_WITH_ATTEMPTS = "Only small attempts at this were found."


def headline(decision: Decision) -> str:
    """One sentence for the verdict. OPEN reads differently once something was found."""
    if decision.verdict is Verdict.OPEN and decision.same_count:
        return OPEN_WITH_ATTEMPTS
    return HEADLINES[decision.verdict]


@dataclass(frozen=True)
class Report:
    idea: str
    decision: Decision
    candidates: tuple[Candidate, ...]
    queries: tuple[QueryResult, ...]
    policy: Policy
    observed_at: str
    now: datetime
    uninspected: int = 0


def to_json(report: Report) -> str:
    """The full report as JSON. Markdown is rendered from the same data."""
    return json.dumps(_as_dict(report), indent=2, ensure_ascii=False) + "\n"


def to_markdown(report: Report) -> str:
    """The report as Markdown. Every string from GitHub or the agent is escaped."""
    decision = report.decision
    lines = [
        f"# dejabuilt: {decision.verdict.value}",
        "",
        f"**Idea:** {markdown(clean(report.idea, 300))}",
        "",
        f"**{headline(decision)}**",
        "",
        *[f"- {markdown(reason)}" for reason in decision.reasons],
        "",
    ]
    for mark, title in (("same", "Same idea"), ("adjacent", "Adjacent")):
        rows = [c for c in report.candidates if c.mark == mark]
        if rows:
            lines += [f"## {title} ({len(rows)})", "", *_candidate_table(rows, report), ""]
    if decision.warnings:
        lines += ["## Warnings", "", *[f"- {markdown(w)}" for w in decision.warnings], ""]
    lines += ["## Evidence", "", *_query_table(report.queries), ""]
    if report.uninspected:
        lines += [f"{report.uninspected} repositories were returned but not inspected.", ""]
    lines += ["## Not checked", "", *[f"- {item}" for item in NOT_CHECKED], ""]
    lines += ["## Policy", "", _policy_line(report), ""]
    return "\n".join(lines)


def _candidate_table(rows: Sequence[Candidate], report: Report) -> list[str]:
    table = [
        "| Repository | Stars | Created | Last push | State | Platforms | Latest release | Why |",
        "| --- | ---: | --- | --- | --- | --- | --- | --- |",
    ]
    for candidate in sorted(rows, key=lambda c: (-c.repo.stars, c.repo.full_name.lower())):
        repo, seen = candidate.repo, candidate.inspection
        state = repo_state(repo, report.now, report.policy).value
        platforms = ", ".join(hint.platform for hint in seen.platforms) or "unknown"
        release = _day(seen.release_at) + (" (pre)" if seen.release_is_prerelease else "")
        cells = [
            f"[{markdown(repo.full_name)}](https://github.com/{quote(repo.full_name, safe='/')})",
            f"{repo.stars:,}",
            _day(repo.created_at),
            _day(repo.pushed_at),
            "archived" if repo.archived else state,
            platforms,
            release if seen.release_at else "none",
            markdown(clean(candidate.reason, 160)),
        ]
        table.append("| " + " | ".join(cells) + " |")
    return table


def _query_table(queries: Sequence[QueryResult]) -> list[str]:
    table = ["| Query | Matches | Looked at | Status |", "| --- | ---: | ---: | --- |"]
    for query in queries:
        status = query.error or ("partial (GitHub timed out)" if query.incomplete else "ok")
        cells = [
            markdown(clean(query.query, 120)),
            f"{query.total_count:,}",
            str(query.returned),
            markdown(clean(status, 120)),
        ]
        table.append("| " + " | ".join(cells) + " |")
    return table


def _policy_line(report: Report) -> str:
    p = report.policy
    return (
        f"Policy version {p.to_dict()['policy_version']}: taken at {p.big_stars:,} stars, "
        f"traction at {p.traction_stars:,} stars, active within {p.active_days} days, "
        f"dormant after {p.dormant_days} days, crowd at {p.crowd_count} attempts. "
        f"These thresholds are heuristics. Observed {_day(report.observed_at)}."
    )


def _day(timestamp: str | None) -> str:
    parsed = parse_time(timestamp)
    return parsed.strftime("%Y-%m-%d") if parsed else "unknown"


def _as_dict(report: Report) -> dict[str, Any]:
    decision = report.decision
    return {
        "schema_version": SCHEMA_VERSION,
        "observed_at": report.observed_at,
        "idea": clean(report.idea, 300),
        "verdict": decision.verdict.value,
        "headline": headline(decision),
        "reasons": list(decision.reasons),
        "warnings": list(decision.warnings),
        "leader": decision.leader,
        "same_count": decision.same_count,
        "policy": report.policy.to_dict(),
        "candidates": [
            {
                "repo": c.repo.to_dict(),
                "state": repo_state(c.repo, report.now, report.policy).value,
                "inspection": c.inspection.to_dict(),
                "mark": c.mark,
                "reason": clean(c.reason, 160),
            }
            for c in report.candidates
        ],
        "queries": [q.to_dict() for q in report.queries],
        "uninspected": report.uninspected,
        "not_checked": list(NOT_CHECKED),
    }
