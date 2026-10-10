"""Check that the skill folder and the plugin manifests are well formed.

Run from the repository root: `python tools/check_skill.py`. Exits 1 with one
line per problem. Used by CI; kept free of dependencies so it runs anywhere.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

MAX_DESCRIPTION = 1024
MAX_NAME = 64
_NAME = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")
_SCRIPT_REFERENCE = re.compile(r"scripts/[A-Za-z0-9_./-]+\.py")


def parse_frontmatter(text: str) -> dict[str, str]:
    """Read the `key: value` block between the leading `---` lines.

    Supports the folded form (`key: >-` followed by indented lines), which is all
    this repository uses. It is not a YAML parser.
    """
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        raise ValueError("SKILL.md must start with a '---' line")
    try:
        end = lines.index("---", 1)
    except ValueError:
        raise ValueError("SKILL.md frontmatter is not closed with '---'") from None
    fields: dict[str, str] = {}
    key = ""
    for line in lines[1:end]:
        if line.startswith((" ", "\t")) and key:
            fields[key] = f"{fields[key]} {line.strip()}".strip()
        elif ":" in line:
            key, _, value = line.partition(":")
            key = key.strip()
            value = value.strip()
            fields[key] = "" if value in (">", ">-", "|", "|-") else value.strip("\"'")
    return fields


def check_skill(skill_dir: Path) -> list[str]:
    problems: list[str] = []
    skill_file = skill_dir / "SKILL.md"
    if not skill_file.is_file():
        return [f"{skill_file}: missing"]
    text = skill_file.read_text(encoding="utf-8")
    try:
        fields = parse_frontmatter(text)
    except ValueError as error:
        return [f"{skill_file}: {error}"]

    name = fields.get("name", "")
    if not _NAME.match(name) or len(name) > MAX_NAME:
        problems.append(f"{skill_file}: name must be lowercase words joined by hyphens")
    if name != skill_dir.name:
        problems.append(f"{skill_file}: name {name!r} does not match folder {skill_dir.name!r}")
    description = fields.get("description", "")
    if not description:
        problems.append(f"{skill_file}: description is missing")
    elif len(description) > MAX_DESCRIPTION:
        problems.append(f"{skill_file}: description is longer than {MAX_DESCRIPTION} characters")
    for reference in sorted(set(_SCRIPT_REFERENCE.findall(text))):
        if not (skill_dir / reference).is_file():
            problems.append(f"{skill_file}: refers to {reference}, which does not exist")
    return problems


def check_manifests(root: Path, skill_name: str) -> list[str]:
    problems: list[str] = []
    loaded: dict[str, dict[str, object]] = {}
    for name in ("plugin.json", "marketplace.json"):
        path = root / ".claude-plugin" / name
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except OSError:
            problems.append(f"{path}: missing")
            continue
        except json.JSONDecodeError as error:
            problems.append(f"{path}: not valid JSON ({error.msg}, line {error.lineno})")
            continue
        if not isinstance(data, dict):
            problems.append(f"{path}: must be a JSON object")
            continue
        loaded[name] = data

    plugin = loaded.get("plugin.json", {})
    if plugin and plugin.get("name") != skill_name:
        problems.append("plugin.json: name does not match the skill name")
    if plugin and not re.fullmatch(r"\d+\.\d+\.\d+", str(plugin.get("version", ""))):
        problems.append("plugin.json: version must look like 1.2.3")
    market = loaded.get("marketplace.json", {})
    plugins = market.get("plugins") if market else None
    if market and not (isinstance(plugins, list) and plugins):
        problems.append("marketplace.json: needs a non-empty 'plugins' list")
    return problems


def main(root: Path | None = None) -> int:
    root = root or Path(__file__).resolve().parent.parent
    skills = sorted(path for path in (root / "skills").iterdir() if path.is_dir())
    problems = [problem for skill in skills for problem in check_skill(skill)]
    if not skills:
        problems.append("skills/: no skill folders found")
    for skill in skills[:1]:
        problems.extend(check_manifests(root, skill.name))
    for problem in problems:
        print(problem, file=sys.stderr)
    if not problems:
        print(f"ok: {len(skills)} skill(s), manifests valid")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
