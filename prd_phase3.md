# PRD — Phase 3: Playbook Depth & Eval Runner

## Overview

Deepen the claims playbook so a real phone call feels complete, and add a replay runner so playbook changes can be tested without making live calls. The Twilio transport, Gemini session, and tool dispatch from Phases 1–2 remain unchanged — this phase is entirely about the intake quality and developer iteration speed.

---

## Goals

- Playbook covers the full motor claim intake: customer ID, incident, third parties, witnesses, damage, settlement preferences (rental car, repair shop), and document checklist
- Per-field hints in the playbook YAML give the agent enough context to know when an answer is complete
- Replay runner lets a developer run a saved transcript through the agent in `--text-mode` and see the resulting claim state, without a mic or phone
- At least three eval transcripts covering: happy path, escalation, mid-flow correction

## Non-Goals

- No UI or dashboard
- No integration with external claims systems
- No multi-claim-type support beyond motor (fire, theft etc. are future phases)

---

## Functional Requirements

### FR-1: Extended playbook stages

Update `playbook.yaml` to add stages for:

- **witness** — `third_parties.witness_info` (only asked if `third_parties.involved == true`)
- **police** — `safety.police_report`, `safety.police_report_details` (only if police attended)
- **settlement** — `services.rental_car_needed`, `services.repair_shop_selected` and their preferences
- **documents** — existing photos/receipts fields, plus `documents.police_report`

Each required field entry may carry an inline hint string that the prompt builder injects into `Expected values by field`.

### FR-2: Updated FIELD_EXPECTATIONS

Add entries to `FIELD_EXPECTATIONS` in `prompts.py` for every new field so the agent knows what constitutes a complete answer before filling the field.

### FR-3: Replay runner

`uv run python app/main.py --eval-transcript <file>` already feeds lines from a file into the text session. This phase adds:

- An `evals/` directory with at least three YAML transcripts:
  - `happy_path.yaml` — full intake, no complications
  - `escalation.yaml` — caller reports injury mid-flow
  - `correction.yaml` — caller corrects a previously given field
- Each transcript includes the expected final `ClaimState` fields for assertion
- A `--eval-assert` flag that compares the session's final claim state against the expected fields and prints PASS / FAIL per field

### FR-4: Conditional stage logic

The playbook engine skips stages whose precondition fields are not met (e.g. skip witness stage if `third_parties.involved == false`). Add an optional `skip_if` key to playbook stage config:

```yaml
witness:
  skip_if: third_parties.involved == false
  required:
    - third_parties.witness_info
  next: police
```

---

## Acceptance Criteria

| # | Scenario | Pass condition |
|---|---|---|
| AC-1 | Happy path replay | `--eval-transcript evals/happy_path.yaml --eval-assert` exits 0 with all required fields PASS |
| AC-2 | Escalation replay | `escalation.yaml` triggers `escalate` tool call; `handoff_required == true` in saved JSON |
| AC-3 | Correction replay | Agent accepts a field correction and overwrites the old value; final state reflects the corrected value |
| AC-4 | Witness skip | When `third_parties.involved == false`, the witness stage is skipped and `third_parties.witness_info` is not asked |
| AC-5 | Rental car flow | When damage prevents driving, agent asks about rental car need and preference before moving to documents |
| AC-6 | Phone unchanged | A live Twilio call still completes a full intake end-to-end with no regressions |
