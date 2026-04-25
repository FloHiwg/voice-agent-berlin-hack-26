# PRD: Tool Calling for State Management in Conversation

## Overview
Enable the voice agent to capture and persist user-provided data throughout the call using tool calls. The agent will extract claim-relevant information from each user response and update the conversation state in real-time, ensuring no data is lost and context is maintained across turns.

## Goals
- Capture all relevant claim information provided by the caller during the conversation
- Persist data to state immediately after extraction, not just at call end
- Maintain conversation context by having the agent review already-collected data
- Enable seamless session reconnection by reloading state from previous session
- Provide visibility into what data has been collected at any point in the call

## Core Features

### 1. Real-Time Data Capture
- Agent extracts structured claim fields from unstructured user input
- Tool call made after each user response to record extracted data
- Support for partial information capture (follow-ups allowed)
- Dot-notation keys for nested field updates (e.g., `customer.full_name`, `incident.location`)

### 2. State Persistence
- All captured data written to `ClaimState` model immediately
- State saved to persistent storage after each update (JSON file)
- State survives connection drops and session reconnections
- Clear separation between collected and pending data

### 3. Agent Awareness of State
- System prompt includes current collected fields
- Agent reviews filled fields before asking new questions
- Agent avoids re-asking questions already answered
- Agent can intelligently branch based on what's collected

### 4. Field-Level Control
- Only extract fields supported by active playbook
- Return list of ignored invalid fields for transparency
- Agent instructed to use only expected field names
- Validation of field paths before persistence

### 5. Session State Lifecycle
```
Session Start
  → Load case data from database (if exists)
  → Populate state with pre-filled fields
  → Review already-collected fields in system prompt

During Call
  → Extract data from each user response
  → Call update_claim_state tool with extracted fields
  → Update system prompt context with new state
  → Return missing fields to guide next question

On Disconnect
  → Save state to storage
  → Preserve all collected data
  → Track session attempt history

On Reconnect
  → Reload state from previous session
  → Inform agent of previous progress
  → Resume from next missing field
```

### 6. Data Validation
- Field type validation (string, boolean, number, list)
- Nested object support (e.g., `customer.*`, `incident.*`)
- List normalization (e.g., damage items separated by comma)
- Nullable fields (None values skipped)
- Field path validation against ClaimState schema

## Implementation Requirements

### State Structure
```json
{
  "session_id": "claim_20240425_120000_ab12",
  "claim_type": "car_accident",
  "status": null,
  "customer": {
    "full_name": "Anna Mueller",
    "policy_number": "POL-2023-4567",
    "date_of_birth": "1985-06-15",
    "identity_verified": true,
    "is_policyholder": true,
    ...
  },
  "incident": {
    "date": "2024-04-20",
    "time": "14:30",
    "location": "Berlin, Kreuzberg",
    "description": "Collision at intersection"
  },
  "damage": {
    "items": ["rear bumper", "trunk lid"],
    "description": "Significant damage to rear",
    "estimated_value": 2500
  },
  ...
}
```

### Tool Call Example
```
Agent extracts from user: "My name is Anna Mueller and the accident happened on April 20th at 2:30 PM"

Tool call:
{
  "name": "update_claim_state",
  "args": {
    "claim_update": {
      "customer.full_name": "Anna Mueller",
      "incident.date": "2024-04-20",
      "incident.time": "14:30"
    }
  }
}

Response:
{
  "status": "updated",
  "missing_fields": [
    "customer.policy_number",
    "claim_type",
    "incident.location",
    ...
  ],
  "current_stage": "identify_customer"
}
```

### System Prompt Integration
```
Current stage: identify_customer
Fields still needed: ["customer.policy_number", "customer.date_of_birth", ...]
Already collected: {
  "customer.full_name": "Anna Mueller",
  "incident.date": "2024-04-20",
  "incident.time": "14:30"
}
```

## Acceptance Criteria

### State Capture
- [ ] Agent calls update_claim_state after extracting user data
- [ ] All extracted fields match ClaimState schema
- [ ] Partial information captured without forcing premature completion
- [ ] Invalid field names are rejected and logged

### State Persistence
- [ ] State saved to disk immediately after update
- [ ] State file contains all extracted data in correct format
- [ ] State survives connection interruption and reconnection
- [ ] Previous session state correctly loaded on reconnect

### Agent Awareness
- [ ] System prompt includes current stage and missing fields
- [ ] System prompt includes already-collected field values
- [ ] Agent avoids re-asking previously answered questions
- [ ] Agent uses missing_fields list to guide next question

### Data Integrity
- [ ] Nested field updates work correctly (e.g., `third_parties.involved`)
- [ ] List fields properly formatted (e.g., damage items)
- [ ] Boolean fields captured correctly
- [ ] Null/empty values handled appropriately

### Error Handling
- [ ] Invalid status values rejected with clear error
- [ ] Invalid field paths rejected with field name
- [ ] Tool failures logged with arguments for debugging
- [ ] Agent gracefully handles tool failures

## Success Metrics
- State fully reconstructable from session file
- Agent never re-asks already answered questions
- Tool response time < 100ms per call

## Notes
- State updates are idempotent (updating same field twice = same result)
- Field order doesn't matter (all updates cumulative)
- Agent should extract ALL relevant information from user response in single tool call
- Storage format is JSON for easy inspection and debugging
