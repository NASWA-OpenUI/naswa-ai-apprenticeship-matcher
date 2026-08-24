from enum import StrEnum


class MatchTarget(StrEnum):
    """The type of apprenticeship data being matched against."""

    OPPORTUNITIES = "opportunities"
    PROGRAMS = "programs"


DEFAULT_MATCH_TARGET = MatchTarget.PROGRAMS
