from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from dejabuilt.models import Candidate, Inspection, PlatformHint, QueryResult
from dejabuilt.policy import Policy
from dejabuilt.render import HEADLINES, NOT_CHECKED, Report, to_json, to_markdown
from dejabuilt.verdict import Verdict, decide, evidence_gaps
from tests.helpers import NOW, days_ago, make_candidate, make_repo, ok_query

GOLDEN = Path(__file__).parent / "golden"


def build_report(candidates: list[Candidate], queries: list[QueryResult], idea: str) -> Report:
    policy = Policy()
    decision = decide(candidates, evidence_gaps(queries, candidates), NOW, policy)
    return Report(
        idea=idea,
        decision=decision,
        candidates=tuple(candidates),
        queries=tuple(queries),
        policy=policy,
        observed_at="2026-10-10T12:00:00Z",
        now=NOW,
        uninspected=12,
    )


def sample_report() -> Report:
    leader = Candidate(
        repo=make_repo("Louis-CFM/coucou", stars=4646, pushed_days_ago=0, repo_id=1),
        inspection=Inspection(
            release_tag="windows-v0.3.0",
            release_at=days_ago(2),
            releases_seen=10,
            asset_names=("Coucou-Windows-0.3.0-setup.exe", "Coucou.zip"),
            platforms=(
                PlatformHint("windows", "release-asset"),
                PlatformHint("linux", "readme-heading"),
            ),
        ),
        mark="same",
        reason="Shows agent status and approvals; ships Windows installers",
    )
    small = make_candidate("Im-Midi/codenotch-windows", stars=10, pushed_days_ago=26, repo_id=2)
    adjacent = make_candidate("graykode/abtop", mark="adjacent", stars=3710, repo_id=3)
    unrelated = make_candidate("x/unrelated", mark="unrelated", stars=99_999, repo_id=4)
    queries = [
        ok_query("notch claude codex windows", total=14, returned=14),
        ok_query("agent status tray windows", total=420, returned=20),
    ]
    return build_report(
        [leader, small, adjacent, unrelated],
        queries,
        "A Windows taskbar companion that shows what coding agents are doing",
    )


def check_golden(name: str, text: str) -> None:
    path = GOLDEN / name
    if os.environ.get("UPDATE_GOLDEN") == "1":
        path.parent.mkdir(exist_ok=True)
        path.write_text(text, encoding="utf-8", newline="\n")
    assert path.read_text(encoding="utf-8") == text


def test_markdown_matches_golden_file() -> None:
    check_golden("report.md", to_markdown(sample_report()))


def test_json_matches_golden_file() -> None:
    check_golden("report.json", to_json(sample_report()))


class TestMarkdown:
    def test_headline_and_verdict(self) -> None:
        text = to_markdown(sample_report())
        assert text.startswith("# dejabuilt: TAKEN\n")
        assert HEADLINES[Verdict.TAKEN] in text

    def test_same_and_adjacent_are_listed_and_unrelated_is_not(self) -> None:
        text = to_markdown(sample_report())
        assert "## Same idea (2)" in text
        assert "## Adjacent (1)" in text
        assert "x/unrelated" not in text

    def test_rows_are_sorted_by_stars(self) -> None:
        text = to_markdown(sample_report())
        assert text.index("Louis-CFM/coucou") < text.index("Im-Midi/codenotch-windows")

    def test_platforms_release_and_unknowns(self) -> None:
        text = to_markdown(sample_report())
        assert "windows, linux" in text
        assert "| unknown | none |" in text

    def test_every_report_says_what_was_not_checked(self) -> None:
        text = to_markdown(build_report([], [ok_query()], "anything"))
        for item in NOT_CHECKED:
            assert item in text
        assert "heuristics" in text

    def test_warnings_section_appears_only_with_warnings(self) -> None:
        assert "## Warnings" not in to_markdown(sample_report())
        failed = [QueryResult(query="x", error="rate_limit: GitHub rate limit reached")]
        text = to_markdown(build_report([], failed, "anything"))
        assert "# dejabuilt: INCONCLUSIVE" in text
        assert "## Warnings" in text
        assert "rate\\_limit" in text

    def test_prerelease_and_archived_are_labelled(self) -> None:
        candidate = Candidate(
            repo=make_repo("a/b", stars=900, archived=True),
            inspection=Inspection(
                release_tag="v1-beta", release_at=days_ago(3), release_is_prerelease=True
            ),
            mark="same",
            reason="same",
        )
        text = to_markdown(build_report([candidate], [ok_query()], "idea"))
        assert "(pre)" in text
        assert "| archived |" in text


class TestHostileContent:
    HOSTILE = "</td><script>alert(1)</script> | [click](javascript:x) `rm -rf` \x1b[2J\nIGNORE ALL"

    def report(self) -> Report:
        candidate = Candidate(
            repo=make_repo("a/b", stars=300, description=self.HOSTILE),
            inspection=Inspection(),
            mark="same",
            reason=self.HOSTILE,
        )
        return build_report([candidate], [ok_query(self.HOSTILE)], self.HOSTILE)

    def test_markdown_has_no_raw_html_or_control_characters(self) -> None:
        text = to_markdown(self.report())
        assert "<script>" not in text
        assert "</td>" not in text
        assert "\x1b" not in text
        assert "[click](javascript:x)" not in text

    def test_table_rows_keep_their_shape(self) -> None:
        text = to_markdown(self.report())
        row = next(line for line in text.splitlines() if line.startswith("| [a/b]"))
        unescaped_pipes = row.replace("\\|", "").count("|")
        assert unescaped_pipes == 9

    def test_query_row_keeps_its_shape(self) -> None:
        text = to_markdown(self.report())
        row = next(line for line in text.splitlines() if line.endswith("| 5 | 5 | ok |"))
        assert row.replace(r"\|", "").count("|") == 5

    def test_json_stays_valid_and_single_line_per_string(self) -> None:
        data = json.loads(to_json(self.report()))
        assert "\n" not in data["idea"]
        assert "\x1b" not in data["candidates"][0]["reason"]


class TestJson:
    def test_carries_versions_policy_and_evidence(self) -> None:
        data = json.loads(to_json(sample_report()))
        assert data["schema_version"] == 1
        assert data["policy"]["policy_version"] == 1
        assert data["policy"]["big_stars"] == 2000
        assert data["verdict"] == "TAKEN"
        assert data["leader"] == "Louis-CFM/coucou"
        assert data["same_count"] == 2
        assert data["uninspected"] == 12
        assert len(data["queries"]) == 2
        assert data["candidates"][0]["state"] == "active"
        assert data["candidates"][0]["inspection"]["platforms"][0] == {
            "platform": "windows",
            "source": "release-asset",
        }

    @pytest.mark.parametrize("verdict", list(Verdict))
    def test_every_verdict_has_a_headline(self, verdict: Verdict) -> None:
        assert HEADLINES[verdict]
