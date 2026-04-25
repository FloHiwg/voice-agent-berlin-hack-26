# PRD: Session Memory State Injection

## Overview
The agent maintains a ClaimState object in session memory that holds all collected field values. On every turn, this state is injected into the system prompt so the agent knows what's been collected, what's missing, and what to ask next.

## Core Concept

**Session Memory State:**
- ClaimState object lives in memory for the entire session
- Contains all 27 playbook fields with current values
- Updated via tool calls after each user response

**Prompt Injection on Every Turn:**
- System prompt is rebuilt on EVERY turn
- Includes: `already_collected` (filled fields with values)
- Includes: `missing_fields` (fields still needed)
- Includes: `current_stage` (playbook stage)
- Agent reads this state before responding

## How It Works

### Every Agent Turn Receives:
```
System Prompt Structure (rebuilt every turn):
├─ Fixed Rules (same every turn)
│   └─ "Ask one question at a time, call update_claim_state after answers..."
│
├─ Current State (CHANGES EVERY TURN)
│   ├─ current_stage: "identify_customer"
│   ├─ missing_fields: ["customer.policy_number", "claim_type", ...]
│   └─ already_collected: {
│       "customer.full_name": "Anna Mueller",
│       "customer.date_of_birth": "1985-06-15",
│       "incident.date": "2024-04-20"
│   }
│
└─ Field Documentation (same every turn)
    └─ FIELD_EXPECTATIONS: Describes how to extract each field
```

### Turn-by-Turn Flow:

**Turn 1: Initial**
```
State in memory: {} (empty)

System Prompt injected with:
  current_stage: "identify_customer"
  missing_fields: ["customer.identity_verified", "customer.is_policyholder"]
  already_collected: {}

Agent: "Hello, thank you for calling. Can I have your name and date of birth?"
```

**Turn 2: User responds**
```
User: "Anna Mueller, born June 15, 1985"

Agent extracts and calls update_claim_state:
  {
    "customer.full_name": "Anna Mueller",
    "customer.date_of_birth": "1985-06-15"
  }

Tool updates state IN MEMORY
State now contains: {
  "customer.full_name": "Anna Mueller",
  "customer.date_of_birth": "1985-06-15"
}
```

**Turn 3: Next response**
```
State in memory: {
  "customer.full_name": "Anna Mueller",
  "customer.date_of_birth": "1985-06-15"
}

System Prompt REBUILT and injected with:
  current_stage: "identify_customer"
  missing_fields: ["customer.policy_number", "customer.is_policyholder"]
  already_collected: {
    "customer.full_name": "Anna Mueller",
    "customer.date_of_birth": "1985-06-15"
  }

Agent: "Thank you Anna. Are you the policyholder or calling on behalf of someone?"
  ^ Uses name from already_collected
  ^ Asks only about missing_fields
```

## State Structure in Memory

```python
class ClaimState:
    session_id: str
    claim_type: str | None = None
    status: str | None = None

    # All nested objects with 27 total fields
    customer: Customer      # 7 fields
    incident: Incident      # 4 fields
    damage: Damage          # 4 fields
    third_parties: ThirdParties  # 3 fields
    safety: Safety          # 4 fields
    documents: Documents    # 3 fields
    services: Services      # 4 fields
```

## Implementation: System Prompt Builder

```python
def build_system_prompt(playbook_engine, claim_state, voice_mode=False):
    # Extract current state from memory
    current_stage = playbook_engine.current_stage(claim_state)
    missing_fields = playbook_engine.get_missing_fields(claim_state)
    filled_fields = claim_state.filled_fields()  # Returns only non-None values

    # Build prompt with injected state
    return f"""
You are a professional insurance claims intake agent.

Current stage: {current_stage}
Fields still needed: {json.dumps(missing_fields)}
Already collected: {json.dumps(filled_fields, sort_keys=True)}

Rules:
- Call update_claim_state after every user answer
- Only ask about fields in 'Fields still needed'
- Never re-ask fields in 'Already collected'
- Use collected values to personalize responses
"""
```

**Key Points:**
- This function is called on EVERY turn
- `claim_state` is the live in-memory object
- `filled_fields()` returns current state snapshot
- `missing_fields` recalculated based on current state

## Implementation: Tool Call Updates State

```python
def update_claim_state(self, claim_update: dict[str, Any]):
    # Update the in-memory ClaimState object
    self.claim_state.merge_update(claim_update)

    # Save to disk for persistence
    self.claim_state.save(self.storage_dir)

    # Return updated state info for next turn
    return {
        "status": "updated",
        "missing_fields": self.playbook_engine.get_missing_fields(self.claim_state),
        "current_stage": self.playbook_engine.current_stage(self.claim_state)
    }
```

**Flow:**
1. Tool receives extracted fields
2. Updates ClaimState object IN MEMORY (self.claim_state)
3. Saves to disk (for recovery)
4. Returns new missing_fields and stage
5. Next turn: system prompt rebuilt with updated state

## Acceptance Criteria

### State Injection
- [ ] System prompt rebuilt on EVERY turn (not just session start)
- [ ] `already_collected` injected with current field values
- [ ] `missing_fields` injected with fields still needed
- [ ] `current_stage` injected with current playbook stage

### State Maintenance
- [ ] ClaimState object persists in memory for entire session
- [ ] Tool calls update the in-memory state object
- [ ] State contains all 27 playbook fields
- [ ] State persisted to disk after each update

### Agent Behavior
- [ ] Agent reads already_collected before responding
- [ ] Agent only asks about missing_fields
- [ ] Agent never re-asks fields in already_collected
- [ ] Agent uses field values to personalize responses (e.g., "Thank you Anna")

### Turn-by-Turn Verification
- [ ] Turn 1: Empty state injected
- [ ] Turn 2: User provides data, tool updates state
- [ ] Turn 3: Updated state injected, agent sees new values
- [ ] Agent behavior changes based on state

## Success Metrics

- **No Re-asking:** Agent never asks about fields in already_collected
- **State Awareness:** Agent uses collected values in responses
- **Intelligent Branching:** Agent skips stages based on state (e.g., third_parties.involved=false)
- **Conversation Continuity:** State flows naturally turn-to-turn

## Notes

- State injection happens on EVERY turn via system prompt rebuild
- Session memory (ClaimState object) is the source of truth
- Persistence to disk is for recovery, not primary mechanism
- Agent has no memory beyond what's injected in the prompt
