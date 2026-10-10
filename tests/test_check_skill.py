from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest
from tools.check_skill import check_manifests, check_skill, main, parse_frontmatter

ROOT = Path(__file__).resolve().parent.parent

GOOD = """---
name: demo
description: >-
  Does a thing
  across two lines.
argument-hint: "<idea>"
---

# demo

Run `scripts/run.py`.
"""


def make_skill(tmp_path: Path, text: str = GOOD, name: str = "demo", script: bool = True) -> Path:
    skill = tmp_path / "skills" / name
    (skill / "scripts").mkdir(parents=True)
    (skill / "SKILL.md").write_text(text, encoding="utf-8")
    if script:
        (skill / "scripts" / "run.py").write_text("", encoding="utf-8")
    return skill


def write_manifests(root: Path, plugin: object, market: object) -> None:
    folder = root / ".claude-plugin"
    folder.mkdir(exist_ok=True)
    (folder / "plugin.json").write_text(json.dumps(plugin), encoding="utf-8")
    (folder / "marketplace.json").write_text(json.dumps(market), encoding="utf-8")


def test_this_repository_passes(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(ROOT) == 0
    assert "ok: 1 skill(s)" in capsys.readouterr().out


def test_parses_folded_and_quoted_values() -> None:
    fields = parse_frontmatter(GOOD)
    assert fields == {
        "name": "demo",
        "description": "Does a thing across two lines.",
        "argument-hint": "<idea>",
    }


@pytest.mark.parametrize("text", ["# no frontmatter", "---\nname: x\n"])
def test_broken_frontmatter_is_reported(tmp_path: Path, text: str) -> None:
    assert len(check_skill(make_skill(tmp_path, text))) == 1


def test_good_skill_has_no_problems(tmp_path: Path) -> None:
    assert check_skill(make_skill(tmp_path)) == []


def test_missing_skill_file(tmp_path: Path) -> None:
    (tmp_path / "empty").mkdir()
    assert "missing" in check_skill(tmp_path / "empty")[0]


@pytest.mark.parametrize(
    ("change", "expected"),
    [
        (("name: demo", "name: Demo_Skill"), "lowercase words"),
        (("name: demo", "name: other"), "does not match folder"),
        (("  Does a thing\n  across two lines.\n", ""), "description is missing"),
        (("Does a thing", "x" * 1100), "longer than 1024"),
    ],
)
def test_frontmatter_problems(tmp_path: Path, change: tuple[str, str], expected: str) -> None:
    problems = check_skill(make_skill(tmp_path, GOOD.replace(*change)))
    assert any(expected in problem for problem in problems)


def test_reference_to_a_missing_script(tmp_path: Path) -> None:
    problems = check_skill(make_skill(tmp_path, script=False))
    assert problems == [
        f"{tmp_path / 'skills' / 'demo' / 'SKILL.md'}: refers to scripts/run.py, "
        "which does not exist"
    ]


PLUGIN = {"name": "demo", "version": "1.2.3"}
MARKET = {"name": "demo", "plugins": [{"name": "demo", "source": "./"}]}


class TestManifests:
    def test_valid(self, tmp_path: Path) -> None:
        write_manifests(tmp_path, PLUGIN, MARKET)
        assert check_manifests(tmp_path, "demo") == []

    @pytest.mark.parametrize(
        ("plugin", "market", "expected"),
        [
            ({"name": "other", "version": "1.2.3"}, MARKET, "name does not match"),
            ({"name": "demo", "version": "v1"}, MARKET, "version must look like"),
            (PLUGIN, {"plugins": []}, "non-empty 'plugins'"),
            (["list"], MARKET, "must be a JSON object"),
        ],
    )
    def test_problems(self, tmp_path: Path, plugin: object, market: object, expected: str) -> None:
        write_manifests(tmp_path, plugin, market)
        assert any(expected in problem for problem in check_manifests(tmp_path, "demo"))

    def test_missing_and_invalid_files(self, tmp_path: Path) -> None:
        folder = tmp_path / ".claude-plugin"
        folder.mkdir()
        (folder / "plugin.json").write_text("{broken", encoding="utf-8")
        problems = check_manifests(tmp_path, "demo")
        assert any("not valid JSON" in problem for problem in problems)
        assert any(
            "marketplace.json: missing" in problem.replace("\\", "/") for problem in problems
        )


def test_main_reports_problems(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    shutil.copytree(ROOT / ".claude-plugin", tmp_path / ".claude-plugin")
    make_skill(tmp_path, GOOD.replace("name: demo", "name: wrong"))
    assert main(tmp_path) == 1
    assert "does not match folder" in capsys.readouterr().err


def test_main_without_skills(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    (tmp_path / "skills").mkdir()
    assert main(tmp_path) == 1
    assert "no skill folders" in capsys.readouterr().err
