from naswa_matcher.match_target import DEFAULT_MATCH_TARGET, MatchTarget


def test_current_match_target_is_programs():
    assert DEFAULT_MATCH_TARGET is MatchTarget.PROGRAMS
