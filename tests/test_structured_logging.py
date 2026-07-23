import hashlib

from naswa_matcher.structured_logging import visitor_id_from_session_id


def test_visitor_id_from_session_id_is_deterministic():
    session_id = "a" * 43

    first = visitor_id_from_session_id(session_id)
    second = visitor_id_from_session_id(session_id)

    assert first == second


def test_visitor_id_from_session_id_differs_for_different_sessions():
    first = visitor_id_from_session_id("a" * 43)
    second = visitor_id_from_session_id("b" * 43)

    assert first != second


def test_visitor_id_from_session_id_uses_sha256():
    session_id = "a" * 43

    expected = hashlib.sha256(session_id.encode("utf-8")).hexdigest()

    assert visitor_id_from_session_id(session_id) == expected
