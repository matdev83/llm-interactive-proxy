from src.session_manager import SessionManager


def test_session_persistence():
    manager = SessionManager(ttl_seconds=10)
    s1 = manager.get_session(None, "app")
    s1.proxy_state.set_override_model("m")
    s2 = manager.get_session(s1.session_id, "app")
    assert s1.session_id == s2.session_id
    assert s2.proxy_state.override_model == "m"


def test_session_expiry():
    manager = SessionManager(ttl_seconds=0)
    s1 = manager.get_session(None, "app")
    s1_id = s1.session_id
    s2 = manager.get_session(s1_id, "app")
    assert s2.session_id != s1_id

