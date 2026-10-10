"""Command line: `search`, then `inspect`, then `verdict`.

Each step reads and writes one JSON state file, so the agent only has to write
the queries and, for the last step, its relevance marks.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, TextIO

from . import __version__
from .github import Client, GitHubError, discover_token
from .inspection import fetch_repo, inspect_repo, validate_full_name
from .models import MARKS, Candidate, Inspection, InvalidInput, Repo, State
from .policy import Policy
from .render import Report, to_json, to_markdown
from .search import search
from .verdict import Verdict, decide, evidence_gaps

EXIT_OK = 0
EXIT_INVALID = 2
EXIT_PARTIAL = 3
EXIT_FAILED = 4

MAX_TOP = 30


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _default_client(env: Mapping[str, str]) -> Client:
    return Client(token=discover_token(env))


@dataclass
class Deps:
    """Everything the CLI takes from the outside world, replaceable in tests."""

    env: Mapping[str, str] = field(default_factory=lambda: dict(os.environ))
    make_client: Callable[[Mapping[str, str]], Client] = _default_client
    now: Callable[[], datetime] = _utc_now
    stdout: TextIO = field(default_factory=lambda: sys.stdout)
    stderr: TextIO = field(default_factory=lambda: sys.stderr)


def main(argv: Sequence[str] | None = None, deps: Deps | None = None) -> int:
    deps = deps or Deps()
    parser = _parser()
    try:
        args = parser.parse_args(argv)
    except SystemExit as stop:
        return EXIT_OK if stop.code == 0 else EXIT_INVALID
    try:
        return int(args.handler(args, deps))
    except InvalidInput as error:
        print(f"dejabuilt: invalid input: {error}", file=deps.stderr)
        return EXIT_INVALID
    except GitHubError as error:
        print(f"dejabuilt: {error}", file=deps.stderr)
        return EXIT_FAILED


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="dejabuilt", description="Check GitHub before you build.")
    parser.add_argument("--version", action="version", version=f"dejabuilt {__version__}")
    commands = parser.add_subparsers(dest="command", required=True)

    find = commands.add_parser("search", help="run search queries and merge the results")
    find.add_argument("-q", "--query", action="append", default=[], help="GitHub search string")
    find.add_argument("--limit", type=int, default=20, help="results per query (default 20)")
    find.add_argument("--out", type=Path, help="write the state file here instead of stdout")
    find.set_defaults(handler=_search)

    look = commands.add_parser("inspect", help="read releases and README headings")
    look.add_argument("--from", dest="source", type=Path, required=True, help="state file")
    look.add_argument("--top", type=int, default=8, help="inspect this many by stars (default 8)")
    look.add_argument("--repo", action="append", default=[], help="also inspect owner/name")
    look.add_argument("--out", type=Path, help="write here (default: update the state file)")
    look.set_defaults(handler=_inspect)

    judge = commands.add_parser("verdict", help="apply the verdict policy to marked candidates")
    judge.add_argument("--from", dest="source", type=Path, required=True, help="state file")
    judge.add_argument("--marks", type=Path, required=True, help="JSON file with idea and marks")
    judge.add_argument("--format", choices=("md", "json"), default="md")
    judge.add_argument("--out", type=Path, help="write the report here instead of stdout")
    judge.add_argument("--big-stars", type=int, default=Policy.big_stars)
    judge.add_argument("--traction-stars", type=int, default=Policy.traction_stars)
    judge.set_defaults(handler=_verdict)
    return parser


def _search(args: argparse.Namespace, deps: Deps) -> int:
    client = deps.make_client(deps.env)
    queries, repos = search(client, args.query, args.limit)
    state = State(observed_at=_stamp(deps.now()), queries=queries, repos=repos)
    _emit(json.dumps(state.to_dict(), indent=2, ensure_ascii=False) + "\n", args.out, deps)
    failed = [q for q in queries if q.error]
    summary = f"{len(repos)} repositories from {len(queries) - len(failed)}/{len(queries)} queries"
    if not client.authenticated:
        summary += " (unauthenticated: low rate limits)"
    print(f"dejabuilt: {summary}", file=deps.stderr)
    for query in failed:
        print(f"dejabuilt: query failed: {query.query!r}: {query.error}", file=deps.stderr)
    if len(failed) == len(queries):
        return EXIT_FAILED
    return EXIT_PARTIAL if failed or any(q.incomplete for q in queries) else EXIT_OK


def _inspect(args: argparse.Namespace, deps: Deps) -> int:
    if not 0 <= args.top <= MAX_TOP:
        raise InvalidInput(f"--top must be between 0 and {MAX_TOP}")
    state = _read_state(args.source)
    client = deps.make_client(deps.env)
    repos = {repo.full_name.lower(): repo for repo in state.repos}
    problems: list[str] = []

    for name in (validate_full_name(name) for name in args.repo):
        if name.lower() not in repos:
            try:
                repos[name.lower()] = fetch_repo(client, name)
            except GitHubError as error:
                problems.append(f"{name}: {error}")

    wanted = [repos[name.lower()] for name in args.repo if name.lower() in repos]
    wanted += [repo for repo in state.repos[: args.top] if repo not in wanted]
    inspections = dict(state.inspections)
    for repo in wanted:
        inspections[repo.full_name] = inspect_repo(client, repo.full_name)
        problems.extend(f"{repo.full_name}: {e}" for e in inspections[repo.full_name].errors)

    known = {repo.id for repo in state.repos}
    added = tuple(repo for repo in repos.values() if repo.id not in known)
    updated = replace(state, repos=(*state.repos, *added), inspections=inspections)
    text = json.dumps(updated.to_dict(), indent=2, ensure_ascii=False) + "\n"
    _emit(text, args.out or args.source, deps)
    print(f"dejabuilt: inspected {len(wanted)} repositories", file=deps.stderr)
    for problem in problems:
        print(f"dejabuilt: {problem}", file=deps.stderr)
    if problems and not wanted:
        return EXIT_FAILED
    return EXIT_PARTIAL if problems else EXIT_OK


def _verdict(args: argparse.Namespace, deps: Deps) -> int:
    state = _read_state(args.source)
    idea, marks = _read_marks(args.marks)
    policy = Policy(big_stars=args.big_stars, traction_stars=args.traction_stars)
    candidates = _candidates(state, marks)
    now = deps.now()
    decision = decide(candidates, evidence_gaps(state.queries, candidates), now, policy)
    report = Report(
        idea=idea,
        decision=decision,
        candidates=candidates,
        queries=state.queries,
        policy=policy,
        observed_at=state.observed_at,
        now=now,
        uninspected=len(state.repos) - len(state.inspections),
    )
    _emit(to_json(report) if args.format == "json" else to_markdown(report), args.out, deps)
    return EXIT_PARTIAL if decision.verdict is Verdict.INCONCLUSIVE else EXIT_OK


def _candidates(state: State, marks: Mapping[str, tuple[str, str]]) -> tuple[Candidate, ...]:
    """Pair every inspected repository with its mark. Nothing may be left unjudged."""
    repos: dict[str, Repo] = {repo.full_name: repo for repo in state.repos}
    inspected: dict[str, Inspection] = dict(state.inspections)
    unknown = sorted(set(marks) - set(inspected))
    if unknown:
        raise InvalidInput(f"marks for repositories that were not inspected: {', '.join(unknown)}")
    missing = sorted(set(inspected) - set(marks))
    if missing:
        raise InvalidInput(
            f"every inspected repository needs a mark; missing: {', '.join(missing)}"
        )
    orphaned = sorted(set(inspected) - set(repos))
    if orphaned:
        raise InvalidInput(f"state file lists inspections without a repository: {orphaned[0]}")
    return tuple(
        Candidate(repo=repos[name], inspection=inspected[name], mark=mark, reason=reason)
        for name, (mark, reason) in marks.items()
    )


def _read_marks(path: Path) -> tuple[str, dict[str, tuple[str, str]]]:
    data = _read_json(path)
    if not isinstance(data, Mapping):
        raise InvalidInput("marks file must be a JSON object")
    idea = data.get("idea")
    if not isinstance(idea, str) or not idea.strip():
        raise InvalidInput("marks file needs a non-empty 'idea'")
    raw = data.get("marks")
    if not isinstance(raw, Mapping):
        raise InvalidInput("marks file needs a 'marks' object")
    marks: dict[str, tuple[str, str]] = {}
    for name, entry in raw.items():
        if not isinstance(entry, Mapping):
            raise InvalidInput(f"mark for {name} must be an object with 'mark' and 'reason'")
        mark, reason = entry.get("mark"), entry.get("reason")
        if mark not in MARKS:
            raise InvalidInput(f"mark for {name} must be one of {', '.join(MARKS)}")
        if not isinstance(reason, str) or not reason.strip():
            raise InvalidInput(f"mark for {name} needs a one-line 'reason'")
        marks[str(name)] = (str(mark), reason.strip())
    return idea.strip(), marks


def _read_state(path: Path) -> State:
    return State.from_dict(_read_json(path))


def _read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except OSError as error:
        raise InvalidInput(
            f"cannot read {path}: {error.strerror or type(error).__name__}"
        ) from None
    except (UnicodeDecodeError, json.JSONDecodeError):
        raise InvalidInput(f"{path} is not valid UTF-8 JSON") from None


def _emit(text: str, out: Path | None, deps: Deps) -> None:
    if out is None:
        deps.stdout.write(text)
        return
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", encoding="utf-8", newline="\n") as handle:
        handle.write(text)


def _stamp(moment: datetime) -> str:
    return moment.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
