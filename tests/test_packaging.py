"""The skill folder must work on its own, wherever an installer copies it."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from dejabuilt import __version__

ROOT = Path(__file__).resolve().parent.parent
SKILL = ROOT / "skills" / "dejabuilt"


def run(script: Path, *args: str, cwd: Path) -> subprocess.CompletedProcess[str]:
    env = {
        k: v for k, v in os.environ.items() if k not in ("PYTHONPATH", "GH_TOKEN", "GITHUB_TOKEN")
    }
    return subprocess.run(
        [sys.executable, str(script), *args],
        cwd=cwd,
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=60,
        check=False,
    )


@pytest.fixture
def copied_skill(tmp_path: Path) -> Path:
    """The skill folder alone, under a path with spaces and non-ASCII characters."""
    target = tmp_path / "my skills éè 日本" / "dejabuilt"
    shutil.copytree(SKILL, target, ignore=shutil.ignore_patterns("__pycache__"))
    return target


def test_runs_from_an_unrelated_directory(copied_skill: Path, tmp_path: Path) -> None:
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    result = run(copied_skill / "scripts" / "run.py", "--version", cwd=elsewhere)
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == f"dejabuilt {__version__}"


def test_verdict_works_offline_from_the_copy(copied_skill: Path, tmp_path: Path) -> None:
    state = {
        "schema_version": 1,
        "observed_at": "2026-10-10T12:00:00Z",
        "queries": [{"query": "café tracker", "total_count": 1, "returned": 1}],
        "repos": [
            {
                "id": 1,
                "full_name": "a/b",
                "url": "https://github.com/a/b",
                "description": "déjà ✔",
                "stars": 9000,
                "pushed_at": "2100-01-01T00:00:00Z",
            }
        ],
        "inspections": {"a/b": {}},
    }
    marks = {"idea": "Ein Café-Tracker", "marks": {"a/b": {"mark": "same", "reason": "gleich"}}}
    (tmp_path / "state.json").write_text(json.dumps(state), encoding="utf-8")
    (tmp_path / "marks.json").write_text(json.dumps(marks), encoding="utf-8")
    result = run(
        copied_skill / "scripts" / "run.py",
        "verdict",
        "--from",
        "state.json",
        "--marks",
        "marks.json",
        cwd=tmp_path,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.startswith("# dejabuilt: TAKEN")
    assert "Ein Café-Tracker" in result.stdout


def test_invalid_usage_exits_2_without_a_traceback(copied_skill: Path, tmp_path: Path) -> None:
    result = run(copied_skill / "scripts" / "run.py", "verdict", cwd=tmp_path)
    assert result.returncode == 2
    assert "Traceback" not in result.stderr


def test_runtime_uses_only_the_standard_library() -> None:
    allowed = set(sys.stdlib_module_names) | {"dejabuilt", "__future__"}
    for source in (SKILL / "scripts").rglob("*.py"):
        for line in source.read_text(encoding="utf-8").splitlines():
            words = line.split()
            if len(words) >= 2 and words[0] in ("import", "from") and not line.startswith(" "):
                module = words[1].split(".")[0]
                assert module in allowed or module == "", f"{source.name}: {line}"


def test_versions_agree() -> None:
    plugin = json.loads((ROOT / ".claude-plugin" / "plugin.json").read_text(encoding="utf-8"))
    pyproject = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    assert plugin["version"] == __version__
    assert f'version = "{__version__}"' in pyproject
