from __future__ import annotations

import json

from app.claims.claim_state import ClaimState
from app.claims.playbook_engine import PlaybookEngine


VOICE_SESSION_EXAMPLE_SCRIPT = """\
# Voice Agent Script: Motor Claim Intake

**Scenario:** Simple rear-end collision | Policyholder: Mark | Agent: Sarah (Empathetic/Supportive)

---

### Stage 1: Greeting & Identification
**AGENT:** Good morning, thank you for calling National Insurance. This is Sarah speaking. How can I help you today?

*[Mark explains he was in an accident]*

**AGENT:** I am so sorry to hear that, but I’m glad you reached out. Before we go any further, are you in a safe location away from traffic?

*[Mark confirms he is on the shoulder/safe]*

**AGENT:** That is the most important thing. Let’s get this documented so we can take care of you. Could you please provide your policy number or license plate?

---

### Stage 2: Accident Circumstances
*[Mark provides policy 88291-MK]*

**AGENT:** Thank you, Mr. Stevens. To start, what time did this occur, and exactly where on the highway are you located?

*[Mark specifies Highway 10, Northbound, 2:15 PM]*

**AGENT:** I have that. And what were the conditions like—was it raining, or was visibility an issue?

*[Mark mentions clear day/bright sun]*

**AGENT:** Could you describe the accident for me in your own words?

---

### Stage 3: Driver & Liability Indicators
*[Mark describes being hit from behind at a red light]*

**AGENT:** That sounds like a clear rear-end collision. Were you the one driving at the time?

*[Mark confirms he was driving alone]*

**AGENT:** Just for the record, were there any alcohol, drugs, or health limitations involved on your end?

---

### Stage 4: Other Party & Authorities
*[Mark says no]*

**AGENT:** Did you manage to get the information from the other driver?

*[Mark provides Jane Doe's details and her admission of phone distraction]*

**AGENT:** That is very helpful for the claim. Did the police attend the scene or provide a case number?

---

### Stage 5: Damage Assessment
*[Mark says no police were called]*

**AGENT:** I’m relieved no one was hurt. Regarding your vehicle, where is the damage located, and is it still drivable?

*[Mark mentions rear bumper/trunk damage, drivable]*

**AGENT:** And was there any pre-existing damage in that area before today?

---

### Stage 6: Settlement & Preferences
*[Mark says no pre-existing damage]*

**AGENT:** We’ll make sure to get that fixed. Since your trunk won't close, would you like us to arrange a rental car for you?

*[Mark agrees]*

**AGENT:** Excellent. We have a preferred repair shop nearby that can help. Would you like to use them to streamline the process?

*[Mark agrees]*

**AGENT:** Perfect. I've noted your preference for email communication. I'll send you a link now to upload photos of the scene. Do you have any other questions for me, Mark?

*[Mark says no]*

**AGENT:** You're very welcome. Take care getting home.

"""


FIELD_EXPECTATIONS = {
    "customer.full_name": "Policyholder's complete first and last name. If the caller gives only a first name, ask for the last name before updating this field.",
    "customer.policy_number": "Full policy number, claim number, or license plate if the caller does not know the policy number.",
    "customer.date_of_birth": "Policyholder date of birth with day, month, and year when possible.",
    "claim_type": "Short claim category such as auto accident, property damage, theft, injury, or weather damage.",
    "incident.date": "Date the incident happened. Ask a follow-up if the caller gives only a vague date.",
    "incident.location": "Specific incident location, including street, city, highway, or landmark when available.",
    "incident.time": "Time or approximate time of the incident.",
    "incident.description": "Brief factual description of what happened.",
    "damage.items": "One or more damaged or affected items as a list.",
    "third_parties.involved": "Boolean yes/no for whether another person, driver, vehicle, business, or property owner was involved.",
    "safety.injuries": "Boolean yes/no or short injury detail. Escalate immediately when injuries are reported.",
    "safety.urgent_risk": "Boolean yes/no for immediate danger, unsafe location, fire, medical risk, or other urgent safety concern.",
    "damage.description": "Specific description of visible damage or loss.",
    "damage.estimated_value": "Estimated repair cost, replacement value, or 'unknown' only after the caller says they do not know.",
    "damage.photos_available": "Boolean yes/no for whether photos are available.",
    "documents.photos": "Boolean yes/no for whether the caller can provide photos.",
    "documents.receipts": "Boolean yes/no for whether receipts or proof of purchase are available.",
    "documents.police_report": "Boolean yes/no for whether a police report exists.",
}


def build_system_prompt(
    playbook_engine: PlaybookEngine,
    claim_state: ClaimState,
    *,
    voice_mode: bool = False,
) -> str:
    stage = playbook_engine.current_stage(claim_state)
    missing_fields = playbook_engine.get_missing_fields(claim_state)
    filled_fields = claim_state.filled_fields()
    expected_values = {
        field: FIELD_EXPECTATIONS[field]
        for field in playbook_engine.all_required_fields()
        if field in FIELD_EXPECTATIONS
    }

    if voice_mode:
        has_prior = bool(filled_fields)
        if has_prior:
            start_rule = "You are resuming an interrupted intake. Review 'Already collected' and continue with the first missing field."
        else:
            start_rule = "Greet the caller immediately when the session starts, without waiting for them to speak first."
    else:
        start_rule = "Start by greeting the customer and asking for the first missing field."

    return f"""You are a professional insurance claims intake agent. Be calm, clear, and efficient.
Ask only one question at a time.

Current stage: {stage}
Fields still needed: {json.dumps(missing_fields)}
Already collected: {json.dumps(filled_fields, sort_keys=True)}
All playbook fields, in order: {json.dumps(playbook_engine.all_required_fields())}
Expected values by field: {json.dumps(expected_values, sort_keys=True)}

Rules:
- {start_rule}
- Call update_claim_state after every user answer with only fields supported by the playbook or claim schema.
- Use dot-notation keys when calling update_claim_state, for example customer.full_name.
- Use the tool response's missing_fields and current_stage to decide the next question.
- Only update a field when the caller gave enough information to satisfy its expected value. If an answer is partial, ask a targeted follow-up instead of filling the field.
- Call escalate immediately if the user reports injuries, urgent risk, or requests human help.
- Call finalize_claim once current_stage is done or once all missing_fields are collected.
- Confirm corrections naturally. Do not repeat every collected field back to the user.
- Do not invent unknown field values. Ask a follow-up when an answer is ambiguous.

Example script:
{VOICE_SESSION_EXAMPLE_SCRIPT}
"""
