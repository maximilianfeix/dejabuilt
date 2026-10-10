"""Take a closer look at one repository: releases, assets and platform hints.

A one-line description goes stale. Release assets and README headings often show
what a project ships today. The hints found here say that a platform is
mentioned or shipped, not that it works.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping, Sequence
from typing import Any

from .github import Client, GitHubError
from .models import Inspection, InvalidInput, PlatformHint, Repo
from .sanitize import clean
from .search import repo_from_api

RELEASES_TO_READ = 10
MAX_ASSET_NAMES = 40
"""How many asset names are kept for display. Platform hints use all of them."""
README_CHARS = 200_000

FROM_ASSET = "release-asset"
FROM_README = "readme-heading"

_FULL_NAME = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9._-]{0,99})/[A-Za-z0-9._-]{1,100}$")

_ASSET_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("windows", re.compile(r"(?<![a-z])(windows|win(32|64)?|msvc)(?![a-z])|\.(exe|msi)$")),
    ("macos", re.compile(r"(?<![a-z])(macos|darwin|osx|mac)(?![a-z])|\.(dmg|pkg)$")),
    ("linux", re.compile(r"(?<![a-z])linux(?![a-z])|\.(deb|rpm|appimage|flatpak|snap)$")),
    ("android", re.compile(r"(?<![a-z])android(?![a-z])|\.(apk|aab)$")),
    ("ios", re.compile(r"(?<![a-z])ios(?![a-z])|\.ipa$")),
)

_HEADING_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("windows", re.compile(r"\bwindows\b")),
    ("macos", re.compile(r"\b(macos|mac os|os x|mac)\b")),
    ("linux", re.compile(r"\blinux\b")),
    ("android", re.compile(r"\bandroid\b")),
    ("ios", re.compile(r"\b(ios|iphone|ipad)\b")),
)


def validate_full_name(name: str) -> str:
    """Accept only `owner/name` made of the characters GitHub allows.

    The pattern admits no slash beyond the one separator, so the only way to walk
    out of `/repos/owner/name` would be a name of `.` or `..`.
    """
    if not _FULL_NAME.match(name) or name.split("/")[-1] in (".", ".."):
        raise InvalidInput(f"not a repository name of the form owner/name: {name[:60]!r}")
    return name


def fetch_repo(client: Client, full_name: str) -> Repo:
    """Load one repository by name. Raises GitHubError if it cannot be read."""
    payload = client.get_json(f"/repos/{validate_full_name(full_name)}")
    if not isinstance(payload, Mapping) or not payload.get("full_name"):
        raise GitHubError("server", "GitHub returned an unexpected repository object")
    return repo_from_api(payload)


def inspect_repo(client: Client, full_name: str) -> Inspection:
    """Read releases and README headings. Failures are recorded, never raised."""
    validate_full_name(full_name)
    errors: list[str] = []
    releases = _releases(client, full_name, errors)
    headings = _readme_headings(client, full_name, errors)
    asset_names = _asset_names(releases)
    hints = platform_hints(asset_names, headings)
    latest = releases[0] if releases else {}
    return Inspection(
        release_tag=clean(latest.get("tag_name"), 60) or None,
        release_at=clean(latest.get("published_at"), 40) or None,
        release_is_prerelease=bool(latest.get("prerelease")),
        releases_seen=len(releases),
        asset_names=asset_names[:MAX_ASSET_NAMES],
        platforms=hints,
        errors=tuple(errors),
    )


def platform_hints(asset_names: Iterable[str], headings: Iterable[str]) -> tuple[PlatformHint, ...]:
    """Platforms seen in asset names, then in README headings. Assets win a tie."""
    found: dict[str, str] = {}
    for texts, patterns, source in (
        (asset_names, _ASSET_PATTERNS, FROM_ASSET),
        (headings, _HEADING_PATTERNS, FROM_README),
    ):
        lowered = [text.lower() for text in texts]
        for platform, pattern in patterns:
            if platform not in found and any(pattern.search(text) for text in lowered):
                found[platform] = source
    order = [platform for platform, _ in _ASSET_PATTERNS]
    return tuple(PlatformHint(p, found[p]) for p in order if p in found)


def readme_headings(text: str) -> tuple[str, ...]:
    """Markdown heading lines, sanitized. The rest of the README is discarded."""
    lines = (line.strip() for line in text.splitlines())
    return tuple(clean(line.lstrip("#"), 120) for line in lines if line.startswith("#"))


def _releases(client: Client, full_name: str, errors: list[str]) -> list[Mapping[str, Any]]:
    try:
        payload = client.get_json(f"/repos/{full_name}/releases", {"per_page": RELEASES_TO_READ})
    except GitHubError as error:
        errors.append(f"releases could not be read ({error.kind})")
        return []
    if not isinstance(payload, list):
        errors.append("releases could not be read (unexpected answer)")
        return []
    return [r for r in payload if isinstance(r, Mapping) and not r.get("draft")]


def _readme_headings(client: Client, full_name: str, errors: list[str]) -> tuple[str, ...]:
    try:
        return readme_headings(client.get_text(f"/repos/{full_name}/readme", README_CHARS))
    except GitHubError as error:
        if error.kind != "not_found":
            errors.append(f"README could not be read ({error.kind})")
        return ()


def _asset_names(releases: Sequence[Mapping[str, Any]]) -> tuple[str, ...]:
    names: dict[str, None] = {}
    for release in releases:
        for asset in release.get("assets") or ():
            if isinstance(asset, Mapping):
                name = clean(asset.get("name"), 100)
                if name:
                    names.setdefault(name)
    return tuple(names)
