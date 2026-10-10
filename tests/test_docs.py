"""The documents must describe the policy the code applies."""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from dejabuilt.models import State
from dejabuilt.policy import Policy
from dejabuilt.verdict import Verdict

ROOT = Path(__file__).resolve().parent.parent
EXAMPLE = ROOT / "docs" / "examples" / "windows-agent-companion"
DOCUMENTS = ["README.md", "plugin/README.md", "plugin/skills/dejabuilt/SKILL.md", "docs/DESIGN.md"]


def read(relative: str) -> str:
    return (ROOT / relative).read_text(encoding="utf-8")


@pytest.mark.parametrize("document", DOCUMENTS)
def test_every_verdict_is_documented(document: str) -> None:
    text = read(document)
    for verdict in Verdict:
        assert f"`{verdict.value}`" in text, f"{document} does not mention {verdict.value}"


@pytest.mark.parametrize("document", DOCUMENTS)
def test_documented_thresholds_match_the_policy(document: str) -> None:
    text = read(document)
    policy = Policy()
    assert f"{policy.big_stars:,} stars" in text
    assert f"{policy.traction_stars} stars" in text
    assert str(policy.dormant_days) in text or "last year" in text


def test_relative_links_in_the_readme_resolve() -> None:
    targets = re.findall(r"\]\((?!https?://|#)([^)#]+)", read("README.md"))
    targets += re.findall(r'(?:src|srcset)="(?!https?://)([^"]+)"', read("README.md"))
    assert targets
    for target in targets:
        assert (ROOT / target).exists(), f"README links to missing file {target}"


def test_example_files_are_consistent() -> None:
    state = State.from_dict(json.loads((EXAMPLE / "state.json").read_text(encoding="utf-8")))
    marks = json.loads((EXAMPLE / "marks.json").read_text(encoding="utf-8"))["marks"]
    assert set(marks) == set(state.inspections)
    report = (EXAMPLE / "report.md").read_text(encoding="utf-8")
    assert report.startswith("# dejabuilt: TAKEN")
    assert "Louis-CFM/coucou" in report


def test_readme_quotes_the_example_report() -> None:
    report = (EXAMPLE / "report.md").read_text(encoding="utf-8")
    leader_row = next(
        line for line in report.splitlines() if line.startswith("| [Louis-CFM/coucou]")
    )
    assert f"> {leader_row}" in read("README.md")
