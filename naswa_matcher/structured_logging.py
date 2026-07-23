import hashlib


def visitor_id_from_session_id(session_id: str) -> str:
    """Return a stable, non-reversible logging ID for a browser session."""
    return hashlib.sha256(session_id.encode("utf-8")).hexdigest()
