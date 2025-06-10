from src.session import SessionManager


def test_session_manager_default_interactive():
    mgr = SessionManager(default_interactive_mode=True)
    session = mgr.get_session("x")
    assert session.proxy_state.interactive_mode is True


def test_session_manager_default_non_interactive():
    mgr = SessionManager(default_interactive_mode=False)
    session = mgr.get_session("y")
    assert session.proxy_state.interactive_mode is False


def test_failover_routes_shared_across_sessions():
    mgr = SessionManager(failover_routes={})
    s1 = mgr.get_session("a")
    s2 = mgr.get_session("b")
    s1.proxy_state.create_failover_route("foo", "k")
    s1.proxy_state.append_route_element("foo", "openrouter:model-a")
    assert s2.proxy_state.list_route("foo") == ["openrouter:model-a"]
