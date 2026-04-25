from __future__ import annotations

from pathlib import Path
from typing import Any

from app.claims.case_database import (
    format_case_response,
    format_status_update_response,
    retrieve_case_by_claim_id,
    retrieve_case_by_phone,
    validate_status,
)
from app.claims.claim_state import ClaimState
from app.claims.playbook_engine import PlaybookEngine


class SessionFinished(Exception):
    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


class ClaimToolHandlers:
    def __init__(
        self,
        claim_state: ClaimState,
        playbook_engine: PlaybookEngine,
        storage_dir: Path,
    ) -> None:
        self.claim_state = claim_state
        self.playbook_engine = playbook_engine
        self.storage_dir = storage_dir
        self.finished_reason: str | None = None

    def update_claim_state(self, claim_update: dict[str, Any]) -> dict[str, Any]:
        invalid_fields = self.claim_state.merge_update(claim_update)
        self.claim_state.save(self.storage_dir)
        result = self._status("updated")
        if invalid_fields:
            result["ignored_fields"] = invalid_fields
            result["status"] = "updated_with_ignored_fields"
        return result

    def escalate(self, reason: str, risk_flags: list[str]) -> dict[str, Any]:
        self.claim_state.handoff_required = True
        for flag in risk_flags:
            if flag not in self.claim_state.risk_flags:
                self.claim_state.risk_flags.append(flag)
        self.claim_state.mark_completed()
        self.claim_state.save(self.storage_dir)
        print(
            "\nESCALATION: A human claims specialist is required."
            f"\nReason: {reason}\n",
            flush=True,
        )
        self.finished_reason = "escalated"
        return self._status("escalated")

    def finalize_claim(self) -> dict[str, Any]:
        missing = self.playbook_engine.get_missing_fields(self.claim_state)
        if missing:
            return self._status("missing_required_fields")
        self.claim_state.mark_completed()
        self.claim_state.save(self.storage_dir)
        self.finished_reason = "finalized"
        return self._status("finalized")

    def retrieve_case_data(
        self, phone_number: str | None = None, claim_id: str | None = None
    ) -> dict[str, Any]:
        """Retrieve case data and populate claim state with retrieved information."""
        case_data = None
        if phone_number:
            case_data = retrieve_case_by_phone(phone_number)
        elif claim_id:
            case_data = retrieve_case_by_claim_id(claim_id)

        if case_data is None:
            return format_case_response(None)

        # Populate claim state with retrieved data
        case_update = {
            "claim_type": case_data.get("claim_type"),
            "status": case_data.get("status"),
            "customer.full_name": case_data.get("claimant_full_name"),
            "customer.policy_number": case_data.get("claimant_policy_number"),
            "customer.date_of_birth": case_data.get("claimant_date_of_birth"),
            "incident.date": case_data.get("incident_date"),
            "incident.time": case_data.get("incident_time"),
            "incident.location": case_data.get("incident_location"),
            "incident.description": case_data.get("incident_description"),
            "third_parties.involved": case_data.get("third_party_involved"),
            "third_parties.details": case_data.get("third_party_details"),
        }

        # Update state, ignoring None values
        invalid_fields = self.claim_state.merge_update(case_update)
        self.claim_state.save(self.storage_dir)

        response = format_case_response(case_data)
        if invalid_fields:
            response["ignored_fields"] = invalid_fields
        return response

    def update_case_status(self, new_status: str) -> dict[str, Any]:
        """Update the case status based on caller input.

        Args:
            new_status: The new status value to set

        Returns:
            Response dict with update result
        """
        is_valid = validate_status(new_status)
        old_status = self.claim_state.status

        if is_valid:
            self.claim_state.status = new_status.lower()
            self.claim_state.save(self.storage_dir)

        return format_status_update_response(new_status, old_status, is_valid)

    def dispatch(self, name: str, args: dict[str, Any]) -> dict[str, Any]:
        if name == "retrieve_case_data":
            return self.retrieve_case_data(
                phone_number=args.get("phone_number"),
                claim_id=args.get("claim_id"),
            )
        if name == "update_case_status":
            return self.update_case_status(new_status=args.get("new_status", ""))
        if name == "update_claim_state":
            return self.update_claim_state(args.get("claim_update", {}))
        if name == "escalate":
            return self.escalate(
                reason=args.get("reason", "Escalation requested"),
                risk_flags=list(args.get("risk_flags", [])),
            )
        if name == "finalize_claim":
            return self.finalize_claim()
        return {"status": "unknown_tool", "tool_name": name}

    def _status(self, status: str) -> dict[str, Any]:
        return {
            "status": status,
            "missing_fields": self.playbook_engine.get_missing_fields(self.claim_state),
            "current_stage": self.playbook_engine.current_stage(self.claim_state),
        }
