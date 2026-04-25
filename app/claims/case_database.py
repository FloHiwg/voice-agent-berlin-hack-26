"""Mock insurance case database for tool calling."""
from __future__ import annotations

from typing import Any

# Valid status values for a claim
VALID_STATUSES = {
    "pending_details",
    "documentation_required",
    "assessment_in_progress",
    "approved",
    "rejected",
    "settled",
    "closed",
    "under_review",
}


# Mock database of cases indexed by phone number and claim ID
CASE_DATABASE = {
    "+49301234567": {
        "case_id": "CLM-2024-001",
        "claim_type": "car_accident",
        "claimant_full_name": "Anna Mueller",
        "claimant_policy_number": "POL-2023-4567",
        "claimant_date_of_birth": "1985-06-15",
        "incident_date": "2024-04-20",
        "incident_time": "14:30",
        "incident_location": "Berlin, Kreuzberg",
        "incident_description": "Collision at traffic light intersection",
        "third_party_involved": True,
        "third_party_details": "Blue sedan, license plate B-XY 123",
        "status": "pending_details",
    },
    "+49307654321": {
        "case_id": "CLM-2024-002",
        "claim_type": "home_damage",
        "claimant_full_name": "Marcus Weber",
        "claimant_policy_number": "POL-2023-8901",
        "claimant_date_of_birth": "1978-03-22",
        "incident_date": "2024-04-18",
        "incident_time": "22:45",
        "incident_location": "Hamburg, Altstadt",
        "incident_description": "Water damage from burst pipe",
        "status": "documentation_required",
    },
}


def retrieve_case_by_phone(phone_number: str) -> dict[str, Any] | None:
    """Retrieve case data by phone number.

    Args:
        phone_number: Phone number in E.164 format (e.g., +49301234567)

    Returns:
        Case data dictionary or None if not found
    """
    return CASE_DATABASE.get(phone_number)


def retrieve_case_by_claim_id(claim_id: str) -> dict[str, Any] | None:
    """Retrieve case data by claim ID.

    Args:
        claim_id: Claim ID (e.g., CLM-2024-001)

    Returns:
        Case data dictionary or None if not found
    """
    for case in CASE_DATABASE.values():
        if case.get("case_id") == claim_id:
            return case
    return None


def format_case_response(case_data: dict[str, Any] | None) -> dict[str, Any]:
    """Format case data for agent response.

    Args:
        case_data: Raw case data from database

    Returns:
        Formatted response with status and case info
    """
    if case_data is None:
        return {
            "status": "not_found",
            "message": "No case found for the provided phone number or claim ID",
        }

    return {
        "status": "found",
        "case_id": case_data.get("case_id"),
        "claim_type": case_data.get("claim_type"),
        "claimant_name": case_data.get("claimant_full_name"),
        "policy_number": case_data.get("claimant_policy_number"),
        "incident_date": case_data.get("incident_date"),
        "incident_location": case_data.get("incident_location"),
        "incident_description": case_data.get("incident_description"),
        "current_status": case_data.get("status"),
    }


def validate_status(status: str) -> bool:
    """Validate if a status is in the allowed set.

    Args:
        status: Status value to validate

    Returns:
        True if valid, False otherwise
    """
    return status.lower() in VALID_STATUSES


def get_valid_statuses() -> set[str]:
    """Get the set of valid status values.

    Returns:
        Set of valid status strings
    """
    return VALID_STATUSES.copy()


def format_status_update_response(
    new_status: str, old_status: str | None, is_valid: bool
) -> dict[str, Any]:
    """Format status update response for agent.

    Args:
        new_status: The new status being set
        old_status: The previous status (if any)
        is_valid: Whether the status is valid

    Returns:
        Formatted response
    """
    if not is_valid:
        return {
            "status": "invalid_status",
            "message": f"'{new_status}' is not a valid status.",
            "valid_statuses": sorted(list(VALID_STATUSES)),
        }

    return {
        "status": "updated",
        "previous_status": old_status,
        "new_status": new_status,
        "message": f"Case status updated to '{new_status}'",
    }
