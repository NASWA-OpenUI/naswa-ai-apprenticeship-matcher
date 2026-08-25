import json
import time
from collections.abc import Callable
from dataclasses import dataclass, field

from naswa_matcher.match_target import MatchTarget

RANKING_CACHE_VERSION = "rank-cache-v3"

Clock = Callable[[], float]


@dataclass
class RankingCacheEntry:
    """Cached completed ranking for one target and normalized profile."""

    ranked: list[dict] = field(default_factory=list)
    completed_items: int = 0
    total_items: int = 0
    completed_units: int = 0
    total_units: int = 0
    elapsed_seconds: int = 0
    created_at: float = field(default_factory=time.time)
    is_complete: bool = False


def _normalized_profile_for_cache(
    profile: dict,
    target: MatchTarget,
) -> dict:
    """Return the profile fields that can affect ranking for this target."""

    def clean_list(values) -> list[str]:
        if not isinstance(values, list):
            return []

        cleaned = []

        for value in values:
            text = str(value).strip()

            if text:
                cleaned.append(text)

        return cleaned

    def clean_string(value) -> str | None:
        if value is None:
            return None

        text = str(value).strip()
        return text or None

    normalized = {
        "likes": clean_list(profile.get("likes", [])),
        "dislikes": clean_list(profile.get("dislikes", [])),
    }

    if target is MatchTarget.OPPORTUNITIES:
        normalized["transportation"] = clean_string(profile.get("transportation"))

    return normalized


@dataclass
class RankingCache:
    """Store completed rankings by target and normalized profile."""

    max_age_seconds: int
    version: str = RANKING_CACHE_VERSION
    entries: dict[str, RankingCacheEntry] = field(default_factory=dict)
    clock: Clock = field(
        default=time.time,
        repr=False,
        compare=False,
    )

    def key_for(self, profile: dict, target: MatchTarget) -> str:
        """Build a deterministic cache key for a ranking target and profile."""
        return json.dumps(
            {
                "version": self.version,
                "target": target.value,
                "profile": _normalized_profile_for_cache(profile, target),
            },
            sort_keys=True,
            separators=(",", ":"),
        )

    def get(
        self,
        profile: dict,
        target: MatchTarget,
    ) -> RankingCacheEntry | None:
        """Return a complete, unexpired ranking for a target and profile."""
        key = self.key_for(profile, target)
        entry = self.entries.get(key)

        if entry is None:
            return None

        if self.clock() - entry.created_at > self.max_age_seconds:
            del self.entries[key]
            return None

        if not entry.is_complete:
            return None

        return entry

    def put(
        self,
        profile: dict,
        target: MatchTarget,
        entry: RankingCacheEntry,
    ) -> None:
        """Store a ranking under its target and normalized profile key."""
        self.entries[self.key_for(profile, target)] = entry

    def clear(self) -> None:
        """Remove every cached ranking."""
        self.entries.clear()
