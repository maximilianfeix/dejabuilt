"""The thresholds behind a verdict.

These are heuristics chosen by judgement. They have not been validated against
outcomes, which is why every report prints the values it used.
"""

from __future__ import annotations

from dataclasses import dataclass

from .models import InvalidInput

POLICY_VERSION = 1


@dataclass(frozen=True)
class Policy:
    big_stars: int = 2000
    """A repo with this many stars that is still maintained owns the idea."""

    traction_stars: int = 200
    """Below this, a repo has not shown that people want it."""

    active_days: int = 180
    """Pushed within this many days: active."""

    dormant_days: int = 365
    """Not pushed for longer than this: dormant."""

    crowd_count: int = 3
    """This many attempts without traction is a pattern, not an open field."""

    def __post_init__(self) -> None:
        if self.traction_stars < 1 or self.big_stars < self.traction_stars:
            raise InvalidInput("thresholds must satisfy 1 <= traction_stars <= big_stars")
        if self.active_days < 1 or self.dormant_days < self.active_days:
            raise InvalidInput("thresholds must satisfy 1 <= active_days <= dormant_days")
        if self.crowd_count < 1:
            raise InvalidInput("crowd_count must be at least 1")

    def to_dict(self) -> dict[str, int]:
        return {
            "policy_version": POLICY_VERSION,
            "big_stars": self.big_stars,
            "traction_stars": self.traction_stars,
            "active_days": self.active_days,
            "dormant_days": self.dormant_days,
            "crowd_count": self.crowd_count,
        }
