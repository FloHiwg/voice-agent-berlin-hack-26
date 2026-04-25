"""Tests for the retrieve_case_data tool implementation."""
import tempfile
from pathlib import Path

import pytest

from app.agent.tools import ClaimToolHandlers
from app.claims.case_database import (
    retrieve_case_by_claim_id,
    retrieve_case_by_phone,
    format_case_response,
)
from app.claims.claim_state import ClaimState
from app.claims.playbook_engine import PlaybookEngine


@pytest.fixture
def playbook_engine():
    """Load the playbook for testing."""
    playbook_path = Path("app/claims/playbook.yaml")
    return PlaybookEngine.from_yaml(playbook_path)


def test_retrieve_case_by_phone():
    """Test retrieving case data by phone number."""
    case = retrieve_case_by_phone("+49301234567")
    assert case is not None
    assert case["case_id"] == "CLM-2024-001"
    assert case["claimant_full_name"] == "Anna Mueller"
    assert case["claim_type"] == "car_accident"


def test_retrieve_case_by_claim_id():
    """Test retrieving case data by claim ID."""
    case = retrieve_case_by_claim_id("CLM-2024-001")
    assert case is not None
    assert case["claimant_full_name"] == "Anna Mueller"
    assert case["claim_type"] == "car_accident"


def test_retrieve_nonexistent_case():
    """Test retrieving a case that doesn't exist."""
    case = retrieve_case_by_phone("+49999999999")
    assert case is None


def test_format_case_response_found():
    """Test formatting response for found case."""
    case = retrieve_case_by_phone("+49301234567")
    response = format_case_response(case)

    assert response["status"] == "found"
    assert response["case_id"] == "CLM-2024-001"
    assert response["claim_type"] == "car_accident"
    assert response["claimant_name"] == "Anna Mueller"


def test_format_case_response_not_found():
    """Test formatting response for not found case."""
    response = format_case_response(None)

    assert response["status"] == "not_found"
    assert "message" in response


def test_retrieve_case_data_tool_populates_state(playbook_engine):
    """Test that retrieve_case_data tool populates claim state."""
    with tempfile.TemporaryDirectory() as tmpdir:
        storage_dir = Path(tmpdir)

        claim_state = ClaimState(session_id="test_retrieve")
        handlers = ClaimToolHandlers(claim_state, playbook_engine, storage_dir)

        # Call the tool
        result = handlers.retrieve_case_data(phone_number="+49301234567")

        assert result["status"] == "found"
        assert result["case_id"] == "CLM-2024-001"

        # Verify state was populated
        assert claim_state.customer.full_name == "Anna Mueller"
        assert claim_state.customer.policy_number == "POL-2023-4567"
        assert claim_state.claim_type == "car_accident"
        assert claim_state.incident.date == "2024-04-20"
        assert claim_state.incident.location == "Berlin, Kreuzberg"
        assert claim_state.third_parties.involved is True


def test_retrieve_case_data_tool_via_dispatch(playbook_engine):
    """Test that retrieve_case_data tool works via dispatch."""
    with tempfile.TemporaryDirectory() as tmpdir:
        storage_dir = Path(tmpdir)

        claim_state = ClaimState(session_id="test_dispatch")
        handlers = ClaimToolHandlers(claim_state, playbook_engine, storage_dir)

        # Call via dispatch (how it's used in production)
        result = handlers.dispatch(
            "retrieve_case_data",
            {"phone_number": "+49307654321"}
        )

        assert result["status"] == "found"
        assert result["case_id"] == "CLM-2024-002"

        # Verify state was populated with second test case
        assert claim_state.customer.full_name == "Marcus Weber"
        assert claim_state.claim_type == "home_damage"


def test_update_case_status_valid(playbook_engine):
    """Test updating case status with a valid status value."""
    with tempfile.TemporaryDirectory() as tmpdir:
        storage_dir = Path(tmpdir)

        claim_state = ClaimState(session_id="test_status")
        handlers = ClaimToolHandlers(claim_state, playbook_engine, storage_dir)

        result = handlers.update_case_status("assessment_in_progress")

        assert result["status"] == "updated"
        assert result["new_status"] == "assessment_in_progress"
        assert result["previous_status"] is None
        assert claim_state.status == "assessment_in_progress"


def test_update_case_status_invalid(playbook_engine):
    """Test updating case status with an invalid status value."""
    with tempfile.TemporaryDirectory() as tmpdir:
        storage_dir = Path(tmpdir)

        claim_state = ClaimState(session_id="test_invalid_status")
        handlers = ClaimToolHandlers(claim_state, playbook_engine, storage_dir)

        result = handlers.update_case_status("invalid_status_xyz")

        assert result["status"] == "invalid_status"
        assert "not a valid status" in result["message"]
        assert "valid_statuses" in result
        assert claim_state.status is None  # Status should not be updated


def test_update_case_status_via_dispatch(playbook_engine):
    """Test updating case status via dispatch."""
    with tempfile.TemporaryDirectory() as tmpdir:
        storage_dir = Path(tmpdir)

        claim_state = ClaimState(session_id="test_dispatch_status")
        claim_state.status = "pending_details"
        handlers = ClaimToolHandlers(claim_state, playbook_engine, storage_dir)

        result = handlers.dispatch(
            "update_case_status",
            {"new_status": "documentation_required"}
        )

        assert result["status"] == "updated"
        assert result["previous_status"] == "pending_details"
        assert result["new_status"] == "documentation_required"
        assert claim_state.status == "documentation_required"


def test_update_case_status_case_insensitive(playbook_engine):
    """Test that status updates are case-insensitive."""
    with tempfile.TemporaryDirectory() as tmpdir:
        storage_dir = Path(tmpdir)

        claim_state = ClaimState(session_id="test_case_insensitive")
        handlers = ClaimToolHandlers(claim_state, playbook_engine, storage_dir)

        result = handlers.update_case_status("APPROVED")

        assert result["status"] == "updated"
        assert claim_state.status == "approved"  # Stored in lowercase
