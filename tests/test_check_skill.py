from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from tools.check_skill import (
    check_marketplace,
    check_plugin,
    check_skill,
    main,
    parse_frontmatter,
)

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

MANIFEST: dict[str, Any] = {
    "name": "demo",
    "version": "1.2.3",
    "homepage": "https://example.com",
    "documentationUrl": "https://example.com/docs",
    "supportUrl": "https://example.com/support",
    "privacyPolicyUrl": "https://example.com/privacy",
    "icon": "./icon.svg",
}
MARKET: dict[str, Any] = {"name": "demo", "plugins": [{"name": "demo", "source": "./plugin"}]}
README = "word " * 45


def make_skill(root: Path, text: str = GOOD, name: str = "demo", script: bool = True) -> Path:
    skill = root / "plugin" / "skills" / name
    (skill / "scripts").mkdir(parents=True)
    (skill / "SKILL.md").write_text(text, encoding="utf-8")
    if script:
        (skill / "scripts" / "run.py").write_text("", encoding="utf-8")
    return skill


def make_repo(
    root: Path,
    manifest: Any = MANIFEST,
    market: Any = MARKET,
    readme: str | None = README,
    licence: bool = True,
    icon: bool = True,
) -> Path:
    """A minimal valid repository layout; arguments break one part at a time."""
    make_skill(root)
    plugin = root / "plugin"
    (plugin / ".claude-plugin").mkdir()
    (plugin / ".claude-plugin" / "plugin.json").write_text(json.dumps(manifest), encoding="utf-8")
    (root / ".claude-plugin").mkdir()
    (root / ".claude-plugin" / "marketplace.json").write_text(json.dumps(market), encoding="utf-8")
    if readme is not None:
        (plugin / "README.md").write_text(readme, encoding="utf-8")
    if licence:
        (plugin / "LICENSE").write_text("MIT", encoding="utf-8")
    if icon:
        (plugin / "icon.svg").write_text("<svg/>", encoding="utf-8")
    return plugin


def test_this_repository_passes(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(ROOT) == 0
    assert "ok: 1 skill(s)" in capsys.readouterr().out


def test_minimal_valid_repository_passes(tmp_path: Path) -> None:
    make_repo(tmp_path)
    assert main(tmp_path) == 0


class TestFrontmatter:
    def test_parses_folded_and_quoted_values(self) -> None:
        assert parse_frontmatter(GOOD) == {
            "name": "demo",
            "description": "Does a thing across two lines.",
            "argument-hint": "<idea>",
        }

    @pytest.mark.parametrize("text", ["# no frontmatter", "---\nname: x\n"])
    def test_broken_frontmatter_is_reported(self, tmp_path: Path, text: str) -> None:
        assert len(check_skill(make_skill(tmp_path, text))) == 1


class TestSkill:
    def test_good_skill_has_no_problems(self, tmp_path: Path) -> None:
        assert check_skill(make_skill(tmp_path)) == []

    def test_missing_skill_file(self, tmp_path: Path) -> None:
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
    def test_frontmatter_problems(
        self, tmp_path: Path, change: tuple[str, str], expected: str
    ) -> None:
        problems = check_skill(make_skill(tmp_path, GOOD.replace(*change)))
        assert any(expected in problem for problem in problems)

    def test_reference_to_a_missing_script(self, tmp_path: Path) -> None:
        problems = check_skill(make_skill(tmp_path, script=False))
        assert len(problems) == 1
        assert problems[0].endswith("refers to scripts/run.py, which does not exist")


class TestPlugin:
    def test_valid(self, tmp_path: Path) -> None:
        assert check_plugin(make_repo(tmp_path), "demo") == []

    @pytest.mark.parametrize(
        ("change", "expected"),
        [
            ({"name": "other"}, "name does not match"),
            ({"version": "v1"}, "version must look like"),
            ({"supportUrl": "http://example.com"}, "supportUrl must be an https"),
            ({"documentationUrl": ""}, "documentationUrl must be an https"),
            ({"icon": "icon.svg"}, "icon must be a ./ path"),
            ({"icon": "./../icon.svg"}, "icon must be a ./ path"),
            ({"icon": "./missing.svg"}, "icon must be a ./ path"),
        ],
    )
    def test_manifest_problems(self, tmp_path: Path, change: dict[str, str], expected: str) -> None:
        plugin = make_repo(tmp_path, manifest={**MANIFEST, **change})
        assert any(expected in problem for problem in check_plugin(plugin, "demo"))

    def test_manifest_that_is_not_an_object(self, tmp_path: Path) -> None:
        plugin = make_repo(tmp_path, manifest=["list"])
        assert any("must be a JSON object" in p for p in check_plugin(plugin, "demo"))

    def test_manifest_that_is_not_json(self, tmp_path: Path) -> None:
        plugin = make_repo(tmp_path)
        (plugin / ".claude-plugin" / "plugin.json").write_text("{broken", encoding="utf-8")
        assert any("not valid JSON" in p for p in check_plugin(plugin, "demo"))

    def test_readme_must_exist_and_have_enough_prose(self, tmp_path: Path) -> None:
        plugin = make_repo(tmp_path, readme=None)
        assert any("README.md: missing" in p for p in check_plugin(plugin, "demo"))
        code_only = "```\n" + "word " * 60 + "\n```\nshort"
        (plugin / "README.md").write_text(code_only, encoding="utf-8")
        assert any("at least 40 words" in p for p in check_plugin(plugin, "demo"))

    def test_licence_must_be_in_the_plugin_folder(self, tmp_path: Path) -> None:
        plugin = make_repo(tmp_path, licence=False)
        assert any("LICENSE" in p and "missing" in p for p in check_plugin(plugin, "demo"))


class TestMarketplace:
    def test_valid(self, tmp_path: Path) -> None:
        make_repo(tmp_path)
        assert check_marketplace(tmp_path) == []

    @pytest.mark.parametrize(
        ("market", "expected"),
        [
            ({"plugins": []}, "non-empty 'plugins'"),
            ({"plugins": ["text"]}, "non-empty 'plugins'"),
            ({"plugins": [{"name": "demo", "source": "./"}]}, "source must be './plugin'"),
        ],
    )
    def test_problems(self, tmp_path: Path, market: Any, expected: str) -> None:
        make_repo(tmp_path, market=market)
        assert any(expected in problem for problem in check_marketplace(tmp_path))

    def test_missing_file(self, tmp_path: Path) -> None:
        assert any("missing" in problem for problem in check_marketplace(tmp_path))


def test_main_reports_problems(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    make_repo(tmp_path, manifest={**MANIFEST, "name": "wrong"})
    assert main(tmp_path) == 1
    assert "name does not match" in capsys.readouterr().err


def test_main_without_skills(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    (tmp_path / "plugin" / "skills").mkdir(parents=True)
    assert main(tmp_path) == 1
    assert "no skill folders" in capsys.readouterr().err


def test_main_without_a_plugin_folder(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert main(tmp_path) == 1
    assert "no skill folders" in capsys.readouterr().err
