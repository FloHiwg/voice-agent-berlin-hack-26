# PRD — Phase 3: Playbook Depth & Eval Runner

## Overview

Deepen the claims playbook so a real phone call feels complete, and add a replay runner so playbook changes can be tested without making live calls. The Twilio transport, Gemini session, and tool dispatch from Phases 1–2 remain unchanged — this phase is entirely about the intake quality and developer iteration speed.

---

## Goals

- First stage identifies and verifies the caller before any claim data is collected
- Playbook covers the full motor claim intake: customer ID, incident, third parties, witnesses, damage, settlement preferences (rental car, repair shop), and document checklist
- Per-field hints in the playbook YAML give the agent enough context to know when an answer is complete
- Replay runner lets a developer run a saved transcript through the agent in `--text-mode` and see the resulting claim state, without a mic or phone
- At least three eval transcripts covering: happy path, escalation, mid-flow correction

## Non-Goals

- No lookup against a real policy database — identity is accepted as stated by the caller
- No UI or dashboard
- No integration with external claims systems
- No multi-claim-type support beyond motor (fire, theft etc. are future phases)

---

## How agent instructions work

There are three places to control agent behaviour, in order of specificity:

| Layer | Where | Controls |
|---|---|---|
| **Playbook YAML** | `app/claims/playbook.yaml` | Stage order, required fields, skip conditions — *what* to collect and *when* |
| **FIELD_EXPECTATIONS** | `app/agent/prompts.py` | Per-field description of what a complete answer looks like — *how* to fill each field |
| **System prompt rules** | `build_system_prompt()` in `prompts.py` | Behavioural instructions that cut across stages: OR logic, verification checks, escalation triggers |

For the identification stage specifically:
- The **playbook** gates on `customer.identity_verified` (an outcome field) rather than on the specific fields used to verify — this keeps OR logic out of the engine
- **FIELD_EXPECTATIONS** for `customer.identity_verified` describes the two accepted paths
- A **system prompt rule** tells the agent to set `identity_verified = true` only after one path is satisfied, and to check caller identity before proceeding

---

## Functional Requirements

### FR-1: Customer identification stage

The first playbook stage gates on `customer.identity_verified`. The agent must collect enough information to satisfy one of two paths before marking this field:

**Path A — policy number:**
- Collect `customer.policy_number`
- Accepted as sufficient on its own

**Path B — name + date of birth:**
- Collect `customer.full_name` and `customer.date_of_birth`
- Both fields required together; neither alone is sufficient

Once a path is satisfied, the agent sets `customer.identity_verified = true` via `update_claim_state` and moves on. It does not ask for the other path's fields.

**System prompt rule (added to `build_system_prompt`):**
> Set `customer.identity_verified = true` only after the caller has provided either (a) their policy number, or (b) their full name and date of birth. Do not accept a first name alone or a date of birth alone.

**FIELD_EXPECTATIONS entry:**
> `customer.identity_verified`: Set to true once identity is confirmed via policy number alone, or via full name plus date of birth together. Do not fill this field from partial information.

### FR-2: Caller verification

After identification, the agent must confirm that the caller is the policyholder. If they are not, the agent collects the caller's name and their relationship to the policyholder before proceeding.

New fields added to `Customer` in `claim_state.py`:
- `customer.is_policyholder: bool | None`
- `customer.caller_name: str | None` — only filled if `is_policyholder == false`
- `customer.relationship_to_policyholder: str | None` — only filled if `is_policyholder == false`

Playbook `identify_customer` stage required fields:
```yaml
identify_customer:
  required:
    - customer.identity_verified
    - customer.is_policyholder
  next: verify_caller
```

Separate `verify_caller` stage:
```yaml
verify_caller:
  skip_if: customer.is_policyholder == true
  required:
    - customer.caller_name
    - customer.relationship_to_policyholder
  next: classify_claim
```

**System prompt rule:**
> After confirming identity, ask: "Are you the policyholder, or are you calling on their behalf?" If the caller is not the policyholder, collect their name and relationship before continuing.

### FR-3: Extended playbook stages

Update `playbook.yaml` to add stages for:

- **witness** — `third_parties.witness_info` (only asked if `third_parties.involved == true`)
- **police** — `safety.police_report`, `safety.police_report_details` (only if police attended)
- **settlement** — `services.rental_car_needed`, `services.repair_shop_selected` and their preferences
- **documents** — existing photos/receipts fields, plus `documents.police_report`

Each required field entry may carry an inline hint string that the prompt builder injects into `Expected values by field`.

### FR-4: Updated FIELD_EXPECTATIONS

Add entries to `FIELD_EXPECTATIONS` in `prompts.py` for every new field so the agent knows what constitutes a complete answer before filling the field.

### FR-5: Conditional stage logic

The playbook engine skips stages whose precondition is not met. Add an optional `skip_if` key to playbook stage config:

```yaml
witness:
  skip_if: third_parties.involved == false
  required:
    - third_parties.witness_info
  next: police
```

The engine evaluates `skip_if` against the current claim state before entering a stage. Supported operators: `== true`, `== false`, `== null`.

### FR-6: Replay runner

`uv run python app/main.py --eval-transcript <file>` already feeds lines from a file into the text session. This phase adds:

- An `evals/` directory with at least three YAML transcripts:
  - `happy_path.yaml` — policyholder calls, identifies by policy number, full intake
  - `third_party_caller.yaml` — spouse calls on behalf of policyholder, identifies by name+DOB
  - `escalation.yaml` — caller reports injury mid-flow
- Each transcript includes the expected final `ClaimState` fields for assertion
- A `--eval-assert` flag that compares the session's final claim state against the expected fields and prints PASS / FAIL per field

---

## Acceptance Criteria

| # | Scenario | Pass condition |
|---|---|---|
| AC-1 | Identity via policy number | Caller gives policy number only → `identity_verified = true`, name and DOB not asked |
| AC-2 | Identity via name + DOB | Caller gives name and DOB → `identity_verified = true`, policy number not asked |
| AC-3 | Partial identity rejected | Caller gives name only → agent asks for DOB before setting `identity_verified` |
| AC-4 | Third-party caller | `is_policyholder = false` → agent collects `caller_name` and `relationship_to_policyholder` before proceeding |
| AC-5 | Policyholder caller | `is_policyholder = true` → `verify_caller` stage skipped, no relationship question asked |
| AC-6 | Happy path replay | `--eval-transcript evals/happy_path.yaml --eval-assert` exits 0 with all required fields PASS |
| AC-7 | Escalation replay | `escalation.yaml` triggers `escalate` tool call; `handoff_required == true` in saved JSON |
| AC-8 | Witness skip | When `third_parties.involved == false`, witness stage is skipped |
| AC-9 | Rental car flow | When damage prevents driving, agent asks about rental car need and preference before documents |
| AC-10 | Phone unchanged | A live Twilio call still completes a full intake end-to-end with no regressions |
