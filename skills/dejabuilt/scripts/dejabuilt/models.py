"""Data shared by all modules. No behaviour beyond conversion to and from JSON."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

SCHEMA_VERSION = 1
MARKS = ("same", "adjacent", "unrelated")


class InvalidInput(ValueError):  # noqa: N818 - reads better at call sites than InvalidInputError
    """Input from a file or the command line does not have the expected shape."""


@dataclass(frozen=True)
class QueryResult:
    """What one search query returned."""

    query: str
    total_count: int = 0
    returned: int = 0
    incomplete: bool = False
    error: str | None = None

    @property
    def not_looked_at(self) -> int:
        return max(self.total_count - self.returned, 0)

    def to_dict(self) -> dict[str, Any]:
        return {
            "query": self.query,
            "total_count": self.total_count,
            "returned": self.returned,
            "incomplete": self.incomplete,
            "error": self.error,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> QueryResult:
        return cls(
            query=_text(data, "query"),
            total_count=_integer(data, "total_count"),
            returned=_integer(data, "returned"),
            incomplete=bool(data.get("incomplete", False)),
            error=_optional_text(data, "error"),
        )


@dataclass(frozen=True)
class Repo:
    """A repository as GitHub reports it. Text fields are already sanitized."""

    id: int
    full_name: str
    url: str
    description: str = ""
    stars: int = 0
    forks: int = 0
    open_issues: int = 0
    archived: bool = False
    created_at: str | None = None
    pushed_at: str | None = None
    language: str | None = None
    matched_queries: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "full_name": self.full_name,
            "url": self.url,
            "description": self.description,
            "stars": self.stars,
            "forks": self.forks,
            "open_issues": self.open_issues,
            "archived": self.archived,
            "created_at": self.created_at,
            "pushed_at": self.pushed_at,
            "language": self.language,
            "matched_queries": list(self.matched_queries),
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> Repo:
        return cls(
            id=_integer(data, "id"),
            full_name=_text(data, "full_name"),
            url=_text(data, "url"),
            description=str(data.get("description") or ""),
            stars=_integer(data, "stars"),
            forks=_integer(data, "forks"),
            open_issues=_integer(data, "open_issues"),
            archived=bool(data.get("archived", False)),
            created_at=_optional_text(data, "created_at"),
            pushed_at=_optional_text(data, "pushed_at"),
            language=_optional_text(data, "language"),
            matched_queries=tuple(str(q) for q in data.get("matched_queries") or ()),
        )


@dataclass(frozen=True)
class PlatformHint:
    """A platform that is mentioned or shipped, and where that was seen."""

    platform: str
    source: str

    def to_dict(self) -> dict[str, str]:
        return {"platform": self.platform, "source": self.source}

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> PlatformHint:
        return cls(platform=_text(data, "platform"), source=_text(data, "source"))


@dataclass(frozen=True)
class Inspection:
    """What a closer look at one repository found."""

    release_tag: str | None = None
    release_at: str | None = None
    release_is_prerelease: bool = False
    releases_seen: int = 0
    asset_names: tuple[str, ...] = ()
    platforms: tuple[PlatformHint, ...] = ()
    errors: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "release_tag": self.release_tag,
            "release_at": self.release_at,
            "release_is_prerelease": self.release_is_prerelease,
            "releases_seen": self.releases_seen,
            "asset_names": list(self.asset_names),
            "platforms": [hint.to_dict() for hint in self.platforms],
            "errors": list(self.errors),
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> Inspection:
        return cls(
            release_tag=_optional_text(data, "release_tag"),
            release_at=_optional_text(data, "release_at"),
            release_is_prerelease=bool(data.get("release_is_prerelease", False)),
            releases_seen=_integer(data, "releases_seen"),
            asset_names=tuple(str(name) for name in data.get("asset_names") or ()),
            platforms=tuple(PlatformHint.from_dict(h) for h in data.get("platforms") or ()),
            errors=tuple(str(error) for error in data.get("errors") or ()),
        )


@dataclass(frozen=True)
class Candidate:
    """An inspected repository together with the agent's judgement of it."""

    repo: Repo
    inspection: Inspection
    mark: str
    reason: str


@dataclass(frozen=True)
class State:
    """Everything gathered so far. Written by `search`, extended by `inspect`."""

    observed_at: str
    queries: tuple[QueryResult, ...] = ()
    repos: tuple[Repo, ...] = ()
    inspections: Mapping[str, Inspection] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": SCHEMA_VERSION,
            "observed_at": self.observed_at,
            "queries": [query.to_dict() for query in self.queries],
            "repos": [repo.to_dict() for repo in self.repos],
            "inspections": {name: i.to_dict() for name, i in self.inspections.items()},
        }

    @classmethod
    def from_dict(cls, data: Any) -> State:
        if not isinstance(data, Mapping):
            raise InvalidInput("state must be a JSON object")
        version = data.get("schema_version")
        if version != SCHEMA_VERSION:
            raise InvalidInput(f"unsupported schema_version {version!r}; expected {SCHEMA_VERSION}")
        inspections = data.get("inspections", {})
        if not isinstance(inspections, Mapping):
            raise InvalidInput("'inspections' must be an object")
        return cls(
            observed_at=_text(data, "observed_at"),
            queries=tuple(QueryResult.from_dict(q) for q in _objects(data, "queries")),
            repos=tuple(Repo.from_dict(r) for r in _objects(data, "repos")),
            inspections={str(k): Inspection.from_dict(_object(v)) for k, v in inspections.items()},
        )


def _object(value: Any) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise InvalidInput(f"expected an object, got {type(value).__name__}")
    return value


def _objects(data: Mapping[str, Any], key: str) -> list[Mapping[str, Any]]:
    value = data.get(key, [])
    if not isinstance(value, list):
        raise InvalidInput(f"'{key}' must be a list")
    return [_object(item) for item in value]


def _text(data: Mapping[str, Any], key: str) -> str:
    value = data.get(key)
    if not isinstance(value, str) or not value:
        raise InvalidInput(f"'{key}' must be a non-empty string")
    return value


def _optional_text(data: Mapping[str, Any], key: str) -> str | None:
    value = data.get(key)
    if value is None:
        return None
    if not isinstance(value, str):
        raise InvalidInput(f"'{key}' must be a string or null")
    return value


def _integer(data: Mapping[str, Any], key: str) -> int:
    value = data.get(key, 0)
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise InvalidInput(f"'{key}' must be a non-negative integer")
    return value
