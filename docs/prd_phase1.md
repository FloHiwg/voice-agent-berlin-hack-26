# PRD — Phase 1: Text-Mode Claims Intake Agent

## Overview

Build a fully functional claims intake agent that runs in the terminal via stdin/stdout. No microphone or speaker required. The agent uses the Gemini 3.1 Flash Live API in text mode, enforces a YAML playbook via function calling, and saves structured claim state to JSON on completion.

This phase validates the entire intake logic — conversation flow, state machine, data extraction, escalation — before any audio hardware is involved. It is the foundation every later phase builds on without modification.

---

## Goals

- Complete a full claim intake (greeting → identify customer → classify → collect details → finalize) in a single terminal session
- All structured state updates happen through function calls, not prompt parsing
- The playbook is declarative YAML — adding or reordering fields requires no Python changes
- Session state is persisted to disk so it can be inspected, replayed in evals, and restored on reconnect
- The agent handles corrections and out-of-order answers gracefully

## Non-Goals

- No audio I/O (mic, speaker, PCM buffers) — that is Phase 2
- No VAD or barge-in logic
- No latency logging (Phase 3)
- No telli integration
- No policy lookup or real database — claim state is in-memory + JSON only
- No authentication or multi-tenant support

---

## User Stories

**As a claims intake operator running a demo**, I can type my responses in the terminal and watch the agent collect each required field in order, so I can verify the playbook and conversation logic work correctly before going to voice.

**As a developer**, I can run the agent with a pre-written conversation transcript in eval mode, so I can regression-test the playbook engine without manual input.

**As a developer**, I can inspect the saved `claim_session.json` after a run and see every extracted field, so I can verify the model extracted data correctly.

---

## Functional Requirements

### FR-1: Session startup

- On launch, the agent opens a Gemini 3.1 Flash Live session with `response_modalities=["TEXT"]`
- The system prompt is built from the playbook YAML and the initial (empty) claim state
- The agent immediately sends a greeting turn — it does not wait for user input first
- The session ID is printed to stdout and written to the session log directory

### FR-2: Text input / output

- The agent reads user input from stdin line-by-line (blocking `input()` wrapped in async)
- Model text responses are printed to stdout as they stream in, character by character
- Each user turn and model turn is logged to `storage/sessions/<session_id>.jsonl`

### FR-3: Function calling — `update_claim_state`

- After every user answer, the model calls `update_claim_state` with a partial claim dict
- The handler merges the update into the current `ClaimState` Pydantic object
- The handler returns `{ "status": "updated", "missing_fields": [...], "current_stage": "..." }`
- The model uses the return value to decide what to ask next — it does not infer this from conversation history

### FR-4: Function calling — `escalate`

- The model calls `escalate(reason, risk_flags)` when:
  - User reports injuries or immediate physical risk
  - User explicitly requests a human agent
  - `safety.urgent_risk` is set to `true`
- The handler sets `claim_state.handoff_required = True`, appends risk flags, saves state, and prints a clear escalation notice to stdout
- The session ends after escalation

### FR-5: Function calling — `finalize_claim`

- The model calls `finalize_claim()` when all required fields in the current playbook state are filled
- The handler saves the full claim state to `storage/sessions/<session_id>_claim.json`
- The session ends after finalization

### FR-6: Playbook engine

- Reads `claims/playbook.yaml` at startup
- Exposes `get_missing_fields(claim_state) -> list[str]` — dot-notation field paths not yet filled
- Exposes `current_stage(claim_state) -> str` — name of the active playbook state
- Advances automatically: when all required fields for a state are filled, `current_stage` returns the next state
- The escalate state is triggered by `claim_state.handoff_required` or `claim_state.safety.urgent_risk`, regardless of playbook progression

### FR-7: Correction handling

- If the user corrects a previously given answer ("actually my name is Smith, not Jones"), the model calls `update_claim_state` with the corrected value
- The handler overwrites the field — no special correction path needed

### FR-8: Session persistence

- Every `update_claim_state` call writes the full current state to `storage/sessions/<session_id>_claim.json` (overwrite, not append)
- On clean completion (`finalize_claim`) or escalation, a `completed_at` timestamp is added
- The session transcript log (`<session_id>.jsonl`) captures every turn with a timestamp and role

---

## Technical Specification

### Entry point

```
python app/main.py --text-mode
```

`--text-mode` sets `response_modalities=["TEXT"]` and swaps the audio I/O coroutines for stdin/stdout. All other code paths — session management, playbook engine, tool handlers — are identical to the voice mode that comes in Phase 2.

### Gemini Live API — text session pattern

```python
async with client.aio.live.connect(
    model="gemini-3.1-flash-live-preview",
    config=types.LiveConnectConfig(
        response_modalities=["TEXT"],
        system_instruction=build_system_prompt(playbook_engine, claim_state),
        tools=[update_claim_state_tool, escalate_tool, finalize_claim_tool],
    )
) as session:
    await asyncio.gather(send_text_loop(session), receive_loop(session))
```

Text input uses `send_client_content`, not `send_realtime_input` (which is audio-only):

```python
await session.send_client_content(
    turns=types.Content(role="user", parts=[types.Part(text=user_input)])
)
```

### ClaimState schema

Pydantic model with all fields nullable by default. Dot-notation paths (e.g. `customer.full_name`) map to nested model attributes. The playbook engine uses `getattr` traversal to check and update nested fields.

```python
class Customer(BaseModel):
    full_name: str | None = None
    policy_number: str | None = None
    date_of_birth: str | None = None

class ClaimState(BaseModel):
    session_id: str
    claim_type: str | None = None
    customer: Customer = Customer()
    incident: Incident = Incident()
    damage: Damage = Damage()
    third_parties: ThirdParties = ThirdParties()
    safety: Safety = Safety()
    documents: Documents = Documents()
    handoff_required: bool = False
    risk_flags: list[str] = []
    created_at: str
    completed_at: str | None = None
```

### Tool definitions (function declarations sent to Gemini)

```python
update_claim_state_tool = types.FunctionDeclaration(
    name="update_claim_state",
    description="Call after every user answer to record extracted claim fields.",
    parameters=types.Schema(
        type="OBJECT",
        properties={
            "claim_update": types.Schema(
                type="OBJECT",
                description="Partial claim dict with dot-notation keys and extracted values."
            )
        },
        required=["claim_update"]
    )
)

escalate_tool = types.FunctionDeclaration(
    name="escalate",
    description="Call when urgent risk, injury, or human handoff is required.",
    parameters=types.Schema(
        type="OBJECT",
        properties={
            "reason": types.Schema(type="STRING"),
            "risk_flags": types.Schema(type="ARRAY", items=types.Schema(type="STRING"))
        },
        required=["reason", "risk_flags"]
    )
)

finalize_claim_tool = types.FunctionDeclaration(
    name="finalize_claim",
    description="Call when all required fields for the current playbook stage are collected.",
    parameters=types.Schema(type="OBJECT", properties={})
)
```

### System prompt structure

Built once at session start. Injected as `system_instruction` in the session config — not as a user turn. Never rebuilt mid-session; updated state is passed back via tool response return values.

```
You are a professional insurance claims intake agent. Be calm, clear, and efficient.
Ask only one question at a time.

Current stage: {stage}
Fields still needed: {missing_fields}
Already collected: {filled_fields}

Rules:
- Call update_claim_state after every user answer.
- Call escalate immediately if the user reports injuries, urgent risk, or requests human help.
- Call finalize_claim once all required fields are collected.
- Confirm corrections naturally. Do not repeat every collected field back to the user.
```

### File structure for this phase

```
app/
  main.py                  # argparse --text-mode flag, asyncio.run entry point
  agent/
    session.py             # LiveConnectConfig, run_session(), send/receive coroutines
    tools.py               # update_claim_state(), escalate(), finalize_claim() handlers
    prompts.py             # build_system_prompt()
    schemas.py             # tool FunctionDeclaration objects
  claims/
    playbook.yaml          # state machine (identify → classify → collect → finalize)
    playbook_engine.py     # PlaybookEngine class
    claim_state.py         # ClaimState + nested Pydantic models, merge(), save()
storage/
  sessions/                # created at runtime; gitignored
.env
requirements.txt
```

### Storage paths

```
storage/sessions/<session_id>_claim.json      # current claim state (overwritten each update)
storage/sessions/<session_id>.jsonl           # turn-by-turn transcript log
```

`session_id` = `claim_<YYYYMMDD_HHMMSS>_<4-char hex>`.

---

## Acceptance Criteria

| # | Scenario | Pass condition |
|---|---|---|
| AC-1 | Happy path: full intake | Agent collects all required fields across all playbook stages and calls `finalize_claim`. `_claim.json` contains no null required fields. |
| AC-2 | Out-of-order answer | User provides incident date before being asked. Agent calls `update_claim_state` immediately. That field is marked filled and not re-asked. |
| AC-3 | Correction | User corrects their name after it was already collected. Agent calls `update_claim_state` with the corrected value. `_claim.json` reflects the correction. |
| AC-4 | Escalation — injury | User says "I was injured in the accident." Agent calls `escalate` with a non-empty `risk_flags` list. `claim_state.handoff_required` is `true` in saved JSON. Session ends. |
| AC-5 | Escalation — user request | User says "I want to speak to a person." Agent calls `escalate`. Session ends. |
| AC-6 | Persistence | Session is interrupted (Ctrl-C) after two turns. `_claim.json` on disk reflects the two answered fields. |
| AC-7 | Tool-only state updates | The `_claim.json` after a full run matches the fields passed through `update_claim_state` calls exactly — no fields are populated by post-processing the transcript. |
| AC-8 | Playbook advancement | Agent does not ask for fields from a later playbook stage before all required fields of the current stage are confirmed via tool call return. |
| AC-9 | `--text-mode` flag | Running without `--text-mode` (in Phase 1) prints a clear error: "audio mode not yet implemented, use --text-mode". |

---

## Open Questions

| # | Question | Impact |
|---|---|---|
| OQ-1 | Does Gemini 3.1 Flash Live reliably call `update_claim_state` after *every* user answer, or does it batch multiple answers into one call? | If batching is unreliable, the prompt rule may need to be strengthened or tool use made more constrained. |
| OQ-2 | What happens when the user gives a partial answer ("I'm not sure about the date")? Does the model leave the field null in the tool call, or skip the call? | May need explicit handling: model should call `update_claim_state` even with null for uncertain fields. |
| OQ-3 | Is `send_client_content` the correct method for text turns in a Live session, or should we use `send_realtime_input` with a text MIME type? | Needs verification against the `google-genai` SDK; wrong method will cause silent message drops. |
| OQ-4 | Does the Live API support structured/typed function call arguments, or only untyped JSON objects? | Affects how strictly `claim_update` dict can be validated server-side vs. client-side. |
