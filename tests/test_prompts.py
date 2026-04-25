from pathlib import Path

from app.agent.prompts import build_system_prompt
from app.claims.claim_state import ClaimState
from app.claims.playbook_engine import PlaybookEngine


def test_prompt_describes_expected_full_name_value() -> None:
    engine = PlaybookEngine.from_yaml(Path("app/claims/playbook.yaml"))
    prompt = build_system_prompt(engine, ClaimState(session_id="claim_test"))

    assert "Expected values by field" in prompt
    assert "customer.full_name" in prompt
    assert "complete first and last name" in prompt
    assert "only a first name" in prompt
    assert "ask for the last name" in prompt
