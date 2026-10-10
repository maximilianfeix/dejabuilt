"""Check that the plugin folder is well formed and self-contained.

Run from the repository root: `python tools/check_skill.py`. Exits 1 with one
line per problem. Used by CI; kept free of dependencies so it runs anywhere.

The plugin folder is what people install, so it has to carry everything it
needs: manifest, README, licence, icon and the skill with its script.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from typing import Any

PLUGIN_DIR = "plugin"
MAX_DESCRIPTION = 1024
MAX_NAME = 64
MIN_README_WORDS = 40
URL_FIELDS = ("homepage", "documentationUrl", "supportUrl", "privacyPolicyUrl")
_NAME = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")
_SCRIPT_REFERENCE = re.compile(r"scripts/[A-Za-z0-9_./-]+\.py")
_CODE_BLOCK = re.compile(r"```.*?```", re.S)


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


def load_json(path: Path, problems: list[str]) -> dict[str, Any] | None:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except OSError:
        problems.append(f"{path}: missing")
        return None
    except json.JSONDecodeError as error:
        problems.append(f"{path}: not valid JSON ({error.msg}, line {error.lineno})")
        return None
    if not isinstance(data, dict):
        problems.append(f"{path}: must be a JSON object")
        return None
    return data


def check_plugin(plugin: Path, skill_name: str) -> list[str]:
    """The plugin folder: manifest fields, icon, README and licence."""
    problems: list[str] = []
    manifest = load_json(plugin / ".claude-plugin" / "plugin.json", problems)
    if manifest is not None:
        if manifest.get("name") != skill_name:
            problems.append("plugin.json: name does not match the skill name")
        if not re.fullmatch(r"\d+\.\d+\.\d+", str(manifest.get("version", ""))):
            problems.append("plugin.json: version must look like 1.2.3")
        for field in URL_FIELDS:
            if not str(manifest.get(field, "")).startswith("https://"):
                problems.append(f"plugin.json: {field} must be an https:// URL")
        icon = str(manifest.get("icon", ""))
        if not icon.startswith("./") or ".." in icon or not (plugin / icon).is_file():
            problems.append("plugin.json: icon must be a ./ path to a file inside the plugin")

    readme = plugin / "README.md"
    if not readme.is_file():
        problems.append(f"{readme}: missing")
    else:
        prose = _CODE_BLOCK.sub(" ", readme.read_text(encoding="utf-8"))
        if len(prose.split()) < MIN_README_WORDS:
            problems.append(f"{readme}: needs at least {MIN_README_WORDS} words outside code")
    if not (plugin / "LICENSE").is_file():
        problems.append(f"{plugin / 'LICENSE'}: missing")
    return problems


def check_marketplace(root: Path) -> list[str]:
    """The marketplace file at the repository root must point at the plugin folder."""
    problems: list[str] = []
    market = load_json(root / ".claude-plugin" / "marketplace.json", problems)
    if market is None:
        return problems
    plugins = market.get("plugins")
    if not (isinstance(plugins, list) and plugins and isinstance(plugins[0], dict)):
        return [*problems, "marketplace.json: needs a non-empty 'plugins' list"]
    if plugins[0].get("source") != f"./{PLUGIN_DIR}":
        problems.append(f"marketplace.json: source must be './{PLUGIN_DIR}'")
    return problems


def main(root: Path | None = None) -> int:
    root = root or Path(__file__).resolve().parent.parent
    plugin = root / PLUGIN_DIR
    skills_dir = plugin / "skills"
    skills = sorted(p for p in skills_dir.iterdir() if p.is_dir()) if skills_dir.is_dir() else []
    problems = [problem for skill in skills for problem in check_skill(skill)]
    if not skills:
        problems.append(f"{skills_dir}: no skill folders found")
    for skill in skills[:1]:
        problems.extend(check_plugin(plugin, skill.name))
    problems.extend(check_marketplace(root))
    for problem in problems:
        print(problem, file=sys.stderr)
    if not problems:
        print(f"ok: {len(skills)} skill(s), plugin folder and marketplace valid")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
