from __future__ import annotations

from google.genai import types


def _schema_type(name: str):
    return getattr(types.Type, name, name)


update_claim_state_tool = types.FunctionDeclaration(
    name="update_claim_state",
    description="Call after every user answer to record extracted claim fields.",
    parameters=types.Schema(
        type=_schema_type("OBJECT"),
        properties={
            "claim_update": types.Schema(
                type=_schema_type("OBJECT"),
                description="Partial claim dict with dot-notation keys and extracted values.",
            )
        },
        required=["claim_update"],
    ),
)

escalate_tool = types.FunctionDeclaration(
    name="escalate",
    description="Call when urgent risk, injury, or human handoff is required.",
    parameters=types.Schema(
        type=_schema_type("OBJECT"),
        properties={
            "reason": types.Schema(type=_schema_type("STRING")),
            "risk_flags": types.Schema(
                type=_schema_type("ARRAY"), items=types.Schema(type=_schema_type("STRING"))
            ),
        },
        required=["reason", "risk_flags"],
    ),
)

finalize_claim_tool = types.FunctionDeclaration(
    name="finalize_claim",
    description="Call when all required fields for the current playbook stage are collected.",
    parameters=types.Schema(type=_schema_type("OBJECT"), properties={}),
)

retrieve_case_data_tool = types.FunctionDeclaration(
    name="retrieve_case_data",
    description="Retrieve existing case data from the insurance database using phone number or claim ID. Use at the start of a session to load customer information.",
    parameters=types.Schema(
        type=_schema_type("OBJECT"),
        properties={
            "phone_number": types.Schema(
                type=_schema_type("STRING"),
                description="Phone number in E.164 format (e.g., +49301234567). Optional if claim_id provided.",
            ),
            "claim_id": types.Schema(
                type=_schema_type("STRING"),
                description="Claim ID (e.g., CLM-2024-001). Optional if phone_number provided.",
            ),
        },
    ),
)

update_case_status_tool = types.FunctionDeclaration(
    name="update_case_status",
    description="Update the status of the claim based on caller input or case progress. Valid statuses: pending_details, documentation_required, assessment_in_progress, approved, rejected, settled, closed, under_review.",
    parameters=types.Schema(
        type=_schema_type("OBJECT"),
        properties={
            "new_status": types.Schema(
                type=_schema_type("STRING"),
                description="The new status to set for the case. Must be one of the valid status values.",
            ),
        },
        required=["new_status"],
    ),
)

tools = [
    types.Tool(
        function_declarations=[
            retrieve_case_data_tool,
            update_case_status_tool,
            update_claim_state_tool,
            escalate_tool,
            finalize_claim_tool,
        ]
    )
]
