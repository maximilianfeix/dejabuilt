from __future__ import annotations

import io
import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import pytest

from dejabuilt.cli import EXIT_FAILED, EXIT_INVALID, EXIT_OK, EXIT_PARTIAL, Deps, main
from dejabuilt.github import Client, Response
from tests.helpers import NOW, TOKEN, FakeTransport, Seq, api_repo, json_response, make_client


class Run:
    """Runs the CLI against a fake GitHub and keeps what it printed."""

    def __init__(self, routes: Mapping[str, Any] | None = None, token: str | None = TOKEN) -> None:
        self.client, self.transport, _ = make_client(routes, token=token)
        self.out = io.StringIO()
        self.err = io.StringIO()

    def __call__(self, *argv: str | Path) -> int:
        deps = Deps(
            env={},
            make_client=lambda env: self.client,
            now=lambda: NOW,
            stdout=self.out,
            stderr=self.err,
        )
        return main([str(arg) for arg in argv], deps)


def found(*items: dict[str, Any], total: int | None = None) -> dict[str, Any]:
    return {"total_count": len(items) if total is None else total, "items": list(items)}


ROUTES: dict[str, Any] = {
    "/search/repositories": found(
        api_repo("big/leader", repo_id=1, stars=5000),
        api_repo("small/try", repo_id=2, stars=12),
        api_repo("other/tool", repo_id=3, stars=800),
    ),
    "/repos/big/leader/releases": [
        {"tag_name": "v2", "published_at": "2026-10-08T00:00:00Z", "assets": [{"name": "x.exe"}]}
    ],
    "/repos/big/leader/readme": Response(200, {}, b"# Leader\n## Linux\n"),
    "/repos/small/try/releases": [],
    "/repos/other/tool/releases": [],
}


def write_marks(path: Path, marks: dict[str, tuple[str, str]], idea: str = "An idea") -> Path:
    body = {"idea": idea, "marks": {k: {"mark": m, "reason": r} for k, (m, r) in marks.items()}}
    path.write_text(json.dumps(body), encoding="utf-8")
    return path


def prepared_state(tmp_path: Path, routes: Mapping[str, Any] = ROUTES) -> Path:
    state = tmp_path / "state.json"
    assert Run(routes)("search", "-q", "alpha", "--out", state) == EXIT_OK
    assert Run(routes)("inspect", "--from", state) == EXIT_OK
    return state


class TestSearchCommand:
    def test_prints_state_json_to_stdout(self) -> None:
        run = Run(ROUTES)
        assert run("search", "-q", "alpha", "-q", "beta") == EXIT_OK
        state = json.loads(run.out.getvalue())
        assert state["schema_version"] == 1
        assert state["observed_at"] == "2026-10-10T12:00:00Z"
        assert [r["full_name"] for r in state["repos"]] == ["big/leader", "other/tool", "small/try"]
        assert "3 repositories from 2/2 queries" in run.err.getvalue()

    def test_writes_to_a_file_in_a_new_directory(self, tmp_path: Path) -> None:
        target = tmp_path / "new dir" / "stäte.json"
        run = Run(ROUTES)
        assert run("search", "-q", "alpha", "--out", target) == EXIT_OK
        assert run.out.getvalue() == ""
        assert json.loads(target.read_text(encoding="utf-8"))["repos"]

    def test_partial_failure_exits_3_and_keeps_results(self) -> None:
        routes = {
            "/search/repositories": Seq(ROUTES["/search/repositories"], json_response({}, 422))
        }
        run = Run(routes)
        assert run("search", "-q", "good", "-q", "bad") == EXIT_PARTIAL
        assert len(json.loads(run.out.getvalue())["repos"]) == 3
        assert "query failed: 'bad'" in run.err.getvalue()

    def test_total_failure_exits_4(self) -> None:
        run = Run({"/search/repositories": json_response({}, 401)})
        assert run("search", "-q", "alpha") == EXIT_FAILED
        assert json.loads(run.out.getvalue())["repos"] == []

    def test_unauthenticated_run_says_so(self) -> None:
        run = Run(ROUTES, token=None)
        run("search", "-q", "alpha")
        assert "unauthenticated" in run.err.getvalue()

    @pytest.mark.parametrize(
        "argv",
        [
            ["search"],
            ["search", "-q", "  "],
            ["search", "-q", "a", "--limit", "0"],
            ["search", "-q", "a", "--limit", "many"],
            ["nonsense"],
            [],
        ],
    )
    def test_invalid_usage_exits_2(self, argv: list[str]) -> None:
        assert Run(ROUTES)(*argv) == EXIT_INVALID

    def test_version_exits_0(self) -> None:
        assert Run()("--version") == EXIT_OK


class TestInspectCommand:
    def test_inspects_the_top_repositories_and_updates_the_file(self, tmp_path: Path) -> None:
        state = tmp_path / "state.json"
        Run(ROUTES)("search", "-q", "alpha", "--out", state)
        run = Run(ROUTES)
        assert run("inspect", "--from", state, "--top", "2") == EXIT_OK
        data = json.loads(state.read_text(encoding="utf-8"))
        assert sorted(data["inspections"]) == ["big/leader", "other/tool"]
        platforms = data["inspections"]["big/leader"]["platforms"]
        assert [p["platform"] for p in platforms] == ["windows", "linux"]

    def test_extra_repo_is_fetched_added_and_inspected(self, tmp_path: Path) -> None:
        state = tmp_path / "state.json"
        Run(ROUTES)("search", "-q", "alpha", "--out", state)
        routes = {
            **ROUTES,
            "/repos/new/one": api_repo("new/one", repo_id=50, stars=7),
            "/repos/new/one/releases": [],
        }
        out = tmp_path / "out.json"
        code = Run(routes)(
            "inspect", "--from", state, "--top", "0", "--repo", "new/one", "--out", out
        )
        assert code == EXIT_OK
        data = json.loads(out.read_text(encoding="utf-8"))
        assert "new/one" in data["inspections"]
        assert "new/one" in [r["full_name"] for r in data["repos"]]
        assert "inspections" in json.loads(state.read_text(encoding="utf-8"))

    def test_inspection_problem_exits_3_and_is_recorded(self, tmp_path: Path) -> None:
        state = tmp_path / "state.json"
        Run(ROUTES)("search", "-q", "alpha", "--out", state)
        routes = {**ROUTES, "/repos/big/leader/releases": json_response({}, 500)}
        run = Run(routes)
        assert run("inspect", "--from", state) == EXIT_PARTIAL
        data = json.loads(state.read_text(encoding="utf-8"))
        assert data["inspections"]["big/leader"]["errors"]
        assert "big/leader" in run.err.getvalue()

    def test_extra_repo_that_cannot_be_fetched_is_remembered(self, tmp_path: Path) -> None:
        state = tmp_path / "state.json"
        Run(ROUTES)("search", "-q", "alpha", "--out", state)
        run = Run(ROUTES)
        assert run("inspect", "--from", state, "--top", "0", "--repo", "gone/repo") == EXIT_FAILED
        assert "gone/repo: not_found" in run.err.getvalue()
        saved = json.loads(state.read_text(encoding="utf-8"))
        assert saved["fetch_errors"] == {"gone/repo": "not_found: not found"}

    def test_unloadable_repo_makes_an_absence_verdict_inconclusive(self, tmp_path: Path) -> None:
        routes = {"/search/repositories": found(), "/repos/known/rival": json_response({}, 500)}
        state = tmp_path / "state.json"
        Run(routes)("search", "-q", "alpha", "--out", state)
        Run(routes)("inspect", "--from", state, "--repo", "known/rival")
        marks = write_marks(tmp_path / "marks.json", {})
        run = Run()
        assert run("verdict", "--from", state, "--marks", marks) == EXIT_PARTIAL
        assert run.out.getvalue().startswith("# dejabuilt: INCONCLUSIVE")
        assert "known/rival" in run.out.getvalue()

    def test_error_is_cleared_once_the_repo_loads(self, tmp_path: Path) -> None:
        state = tmp_path / "state.json"
        Run({"/search/repositories": found()})("search", "-q", "alpha", "--out", state)
        Run()("inspect", "--from", state, "--repo", "late/repo")
        assert json.loads(state.read_text(encoding="utf-8"))["fetch_errors"]
        routes = {
            "/repos/late/repo": api_repo("late/repo", repo_id=9),
            "/repos/late/repo/releases": [],
        }
        assert Run(routes)("inspect", "--from", state, "--repo", "late/repo") == EXIT_OK
        saved = json.loads(state.read_text(encoding="utf-8"))
        assert saved["fetch_errors"] == {}
        assert "late/repo" in saved["inspections"]

    def test_repo_named_twice_is_inspected_once(self, tmp_path: Path) -> None:
        state = tmp_path / "state.json"
        Run(ROUTES)("search", "-q", "alpha", "--out", state)
        run = Run(ROUTES)
        run("inspect", "--from", state, "--top", "0", "--repo", "small/try", "--repo", "small/try")
        assert "inspected 1 repositories" in run.err.getvalue()

    @pytest.mark.parametrize("extra", [["--top", "31"], ["--top", "-1"], ["--repo", "not a repo"]])
    def test_invalid_arguments_exit_2(self, tmp_path: Path, extra: list[str]) -> None:
        state = tmp_path / "state.json"
        Run(ROUTES)("search", "-q", "alpha", "--out", state)
        assert Run(ROUTES)("inspect", "--from", state, *extra) == EXIT_INVALID

    @pytest.mark.parametrize("content", ["", "{", "[]", '{"schema_version": 7}'])
    def test_unreadable_state_exits_2(self, tmp_path: Path, content: str) -> None:
        state = tmp_path / "state.json"
        state.write_text(content, encoding="utf-8")
        run = Run(ROUTES)
        assert run("inspect", "--from", state) == EXIT_INVALID
        assert "invalid input" in run.err.getvalue()

    def test_missing_state_file_exits_2(self, tmp_path: Path) -> None:
        assert Run(ROUTES)("inspect", "--from", tmp_path / "nope.json") == EXIT_INVALID


MARKS = {
    "big/leader": ("same", "does exactly this"),
    "small/try": ("same", "an early attempt"),
    "other/tool": ("adjacent", "solves a neighbouring problem"),
}


class TestVerdictCommand:
    def test_markdown_report(self, tmp_path: Path) -> None:
        state = prepared_state(tmp_path)
        marks = write_marks(tmp_path / "marks.json", MARKS)
        run = Run()
        assert run("verdict", "--from", state, "--marks", marks) == EXIT_OK
        text = run.out.getvalue()
        assert text.startswith("# dejabuilt: TAKEN")
        assert "big/leader" in text
        assert run.transport.calls == []

    def test_json_report_to_file(self, tmp_path: Path) -> None:
        state = prepared_state(tmp_path)
        marks = write_marks(tmp_path / "marks.json", MARKS)
        out = tmp_path / "report.json"
        code = Run()("verdict", "--from", state, "--marks", marks, "--format", "json", "--out", out)
        assert code == EXIT_OK
        data = json.loads(out.read_text(encoding="utf-8"))
        assert (data["verdict"], data["leader"], data["same_count"]) == ("TAKEN", "big/leader", 2)

    def test_policy_override_changes_the_verdict(self, tmp_path: Path) -> None:
        state = prepared_state(tmp_path)
        marks = write_marks(tmp_path / "marks.json", MARKS)
        run = Run()
        run("verdict", "--from", state, "--marks", marks, "--big-stars", "9000")
        assert run.out.getvalue().startswith("# dejabuilt: CONTESTED")

    def test_inconclusive_exits_3(self, tmp_path: Path) -> None:
        routes = {**ROUTES, "/search/repositories": Seq(found(), json_response({}, 422))}
        state = tmp_path / "state.json"
        Run(routes)("search", "-q", "good", "-q", "bad", "--out", state)
        marks = write_marks(tmp_path / "marks.json", {})
        run = Run()
        assert run("verdict", "--from", state, "--marks", marks) == EXIT_PARTIAL
        assert run.out.getvalue().startswith("# dejabuilt: INCONCLUSIVE")

    @pytest.mark.parametrize(
        ("marks", "message"),
        [
            ({"big/leader": ("same", "x")}, "every inspected repository needs a mark"),
            ({**MARKS, "never/seen": ("same", "x")}, "were not inspected"),
        ],
    )
    def test_marks_must_cover_exactly_the_inspected_repositories(
        self, tmp_path: Path, marks: dict[str, tuple[str, str]], message: str
    ) -> None:
        state = prepared_state(tmp_path)
        path = write_marks(tmp_path / "marks.json", marks)
        run = Run()
        assert run("verdict", "--from", state, "--marks", path) == EXIT_INVALID
        assert message in run.err.getvalue()

    @pytest.mark.parametrize(
        "body",
        [
            [],
            {"marks": {}},
            {"idea": "  ", "marks": {}},
            {"idea": "x"},
            {"idea": "x", "marks": []},
            {"idea": "x", "marks": {"big/leader": "same"}},
            {"idea": "x", "marks": {"big/leader": {"mark": "maybe", "reason": "r"}}},
            {"idea": "x", "marks": {"big/leader": {"mark": "same", "reason": " "}}},
            {"idea": "x", "marks": {"big/leader": {"mark": "same"}}},
        ],
    )
    def test_malformed_marks_file_exits_2(self, tmp_path: Path, body: Any) -> None:
        state = prepared_state(tmp_path)
        path = tmp_path / "marks.json"
        path.write_text(json.dumps(body), encoding="utf-8")
        assert Run()("verdict", "--from", state, "--marks", path) == EXIT_INVALID

    def test_invalid_policy_override_exits_2(self, tmp_path: Path) -> None:
        state = prepared_state(tmp_path)
        marks = write_marks(tmp_path / "marks.json", MARKS)
        code = Run()("verdict", "--from", state, "--marks", marks, "--traction-stars", "0")
        assert code == EXIT_INVALID

    def test_state_with_inspection_but_no_repository_is_rejected(self, tmp_path: Path) -> None:
        state = prepared_state(tmp_path)
        data = json.loads(state.read_text(encoding="utf-8"))
        data["repos"] = [r for r in data["repos"] if r["full_name"] != "small/try"]
        state.write_text(json.dumps(data), encoding="utf-8")
        marks = write_marks(tmp_path / "marks.json", MARKS)
        assert Run()("verdict", "--from", state, "--marks", marks) == EXIT_INVALID


def test_default_dependencies_build_a_real_client() -> None:
    deps = Deps(env={"GH_TOKEN": "abc"})
    client = deps.make_client(deps.env)
    assert isinstance(client, Client)
    assert client.authenticated is True
    assert deps.now().tzinfo is not None


def test_fake_transport_answers_unknown_paths_with_404() -> None:
    assert FakeTransport()("https://api.github.com/x", {}, 1.0).status == 404
