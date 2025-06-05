from src.session import SessionManager


def test_session_manager_default_interactive():
    mgr = SessionManager(default_interactive_mode=True)
    session = mgr.get_session("x")
    assert session.proxy_state.interactive_mode is True


def test_session_manager_default_non_interactive():
    mgr = SessionManager()
    session = mgr.get_session("y")
    assert session.proxy_state.interactive_mode is False

