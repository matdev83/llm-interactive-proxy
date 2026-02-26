import re
from dataclasses import dataclass


@dataclass
class AngelDecision:
    decision: str
    steering_message: str | None = None

class AngelParserShim:
    _PASS_DECISION_RE = re.compile(
        r"<angels_decision>\s*Pass\s*</angels_decision>", re.IGNORECASE
    )
    _STEER_DECISION_RE = re.compile(
        r"<angels_decision>\s*Steer\s*</angels_decision>", re.IGNORECASE
    )
    _STEERING_MESSAGE_RE = re.compile(
        r"<angels_steering_message>([\s\S]*?)</angels_steering_message>", re.IGNORECASE
    )

    def parse(self, text: str) -> AngelDecision:
        if self._PASS_DECISION_RE.search(text):
            return AngelDecision(decision="pass")
        
        steer_match = self._STEER_DECISION_RE.search(text)
        message_match = self._STEERING_MESSAGE_RE.search(text)

        if steer_match or message_match:
            msg = message_match.group(1).strip() if message_match else "Correction required."
            return AngelDecision(decision="steer", steering_message=msg)
        return AngelDecision(decision="pass")

def test_parser():
    parser = AngelParserShim()
    
    # Test case with thinking tags
    thinking_text = """
    <thinking>
    The user's response is acceptable.
    </thinking>
    <angels_decision>Pass</angels_decision>
    """
    result = parser.parse(thinking_text)
    print(f"Thinking + Pass: {result.decision}")
    assert result.decision == "pass"

    # Test case with thinking + steer
    steer_text = """
    <thinking>I should suggest a correction.</thinking>
    <angels_decision>Steer</angels_decision>
    <angels_steering_message>Please be more concise.</angels_steering_message>
    """
    result = parser.parse(steer_text)
    print(f"Thinking + Steer: {result.decision}, Msg: {result.steering_message}")
    assert result.decision == "steer"
    assert result.steering_message == "Please be more concise."

if __name__ == "__main__":
    test_parser()
    print("Tests passed!")
