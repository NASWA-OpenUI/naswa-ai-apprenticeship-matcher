from enum import StrEnum


class MatchTarget(StrEnum):
    """The type of apprenticeship data being matched against."""

    OPPORTUNITIES = "opportunities"
    PROGRAMS = "programs"


MATCH_TARGET = MatchTarget.PROGRAMS