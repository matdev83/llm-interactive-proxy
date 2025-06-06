from src.agents import detect_agent, wrap_proxy_message


def test_detect_agent_cline():
    prompt = "You are Cline, use tools with XML-style tags"
    assert detect_agent(prompt) == "cline"


def test_detect_agent_roocode():
    prompt = "You are Roo, follow RooCode rules"
    assert detect_agent(prompt) == "roocode"


def test_detect_agent_aider():
    prompt = "Please use the V4A diff format.*** Begin Patch"
    assert detect_agent(prompt) == "aider"


def test_wrap_proxy_message_cline():
    out = wrap_proxy_message("cline", "hi")
    assert out.startswith("[Proxy Result]\n\n")


def test_wrap_proxy_message_aider():
    out = wrap_proxy_message("aider", "line1\nline2")
    assert out.splitlines()[0] == "*** Begin Patch"
    assert out.splitlines()[-1] == "*** End Patch"
