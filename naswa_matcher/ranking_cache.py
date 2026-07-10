import json
import time
from collections.abc import Callable
from dataclasses import dataclass, field, replace

from naswa_matcher.location_matching import should_use_location_matching

RANKING_CACHE_VERSION = "rank-cache-v1"

Clock = Callable[[], float]


@dataclass
class RankingCacheEntry:
    """Cached ranked opportunities for one normalized profile."""

    profile: dict
    ranked: list[dict] = field(default_factory=list)
    completed_jobs: int = 0
    total_jobs: int = 0
    completed_openings: int = 0
    total_openings: int = 0
    elapsed_seconds: int = 0
    created_at: float = field(default_factory=time.time)
    is_complete: bool = False


def _normalized_profile_for_cache(profile: dict) -> dict:
    """Return a stable, compact profile shape for ranking-cache keys."""

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

    return {
        "likes": clean_list(profile.get("likes", [])),
        "dislikes": clean_list(profile.get("dislikes", [])),
        "location": clean_string(profile.get("location")),
        "transportation": clean_string(profile.get("transportation")),
        "use_location_matching": should_use_location_matching(profile),
    }


@dataclass
class RankingCache:
    """Store completed opportunity rankings by normalized profile."""

    max_age_seconds: int
    version: str = RANKING_CACHE_VERSION
    entries: dict[str, RankingCacheEntry] = field(default_factory=dict)
    clock: Clock = field(
        default=time.time,
        repr=False,
        compare=False,
    )

    def key_for(self, profile: dict) -> str:
        """Build a deterministic cache key for a ranking profile."""
        return json.dumps(
            {
                "version": self.version,
                "profile": _normalized_profile_for_cache(profile),
            },
            sort_keys=True,
            separators=(",", ":"),
        )

    def get(self, profile: dict) -> RankingCacheEntry | None:
        """Return a complete, unexpired ranking for a profile."""
        key = self.key_for(profile)
        entry = self.entries.get(key)

        if entry is None:
            return None

        if self.clock() - entry.created_at > self.max_age_seconds:
            del self.entries[key]
            return None

        if not entry.is_complete:
            return None

        return entry

    def put(self, profile: dict, entry: RankingCacheEntry) -> None:
        """Store a ranking under the normalized profile key."""
        normalized_entry = replace(
            entry,
            profile=_normalized_profile_for_cache(profile),
        )

        self.entries[self.key_for(profile)] = normalized_entry

    def clear(self) -> None:
        """Remove every cached ranking."""
        self.entries.clear()
