from naswa_matcher.match_target import MATCH_TARGET, MatchTarget


def test_current_match_target_is_programs():
    assert MATCH_TARGET is MatchTarget.PROGRAMS