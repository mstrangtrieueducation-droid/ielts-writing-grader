import pytest
from src.gemini_service import GeminiService

def test_paid_generation_is_blocked_before_network_by_default(monkeypatch):
    monkeypatch.delenv('GEMINI_GENERATION_ENABLED',raising=False)
    service=GeminiService.__new__(GeminiService)
    # No client is configured: this must fail on the guard, before any network access.
    with pytest.raises(ValueError,match='no grading API request sent'):
        service.structured('model','prompt',None)
