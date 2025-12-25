from src.connectors.gemini_base.models import TierScore

def test_tier_score_comparison():
    score1 = TierScore(is_paid=1, context_tokens=1000, is_default=0)
    score2 = TierScore(is_paid=1, context_tokens=2000, is_default=0)
    score3 = TierScore(is_paid=0, context_tokens=5000, is_default=1)
    
    assert score2 > score1
    assert score1 > score3
    assert max([score1, score2, score3]) == score2

def test_tier_score_equality():
    score1 = TierScore(is_paid=1, context_tokens=1000, is_default=0)
    score2 = TierScore(is_paid=1, context_tokens=1000, is_default=0)
    
    assert score1 == score2
