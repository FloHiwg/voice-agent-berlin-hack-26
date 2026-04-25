# Local Claims Intake Voice Agent Plan

## Goal

Build a fast local MVP for an insurance claims intake agent:

- local microphone input
- local speaker output
- Gemini 3.1 Flash Live for native real-time audio (handles VAD + STT + LLM + TTS in one WebSocket session)
- deterministic claim playbook enforced via function calling
- sub-second perceived latency
- upgrade path to Twilio phone calls, then telli later if needed

---

## Architecture Overview

```text
mic → WebSocket → Gemini 3.1 Flash Live → speaker
                          ↕
              function calls → playbook engine → claim state

Twilio call → Twilio Media Stream WebSocket → Gemini 3.1 Flash Live
                                           ↕
                             function calls → playbook engine → claim state
```

VAD, transcription, and voice synthesis are all handled inside the Live session. No separate libraries needed for any of those three stages.

---

## MVP Acceptance Criteria

A successful e2e demo completes one full claim intake via voice:

1. Agent greets caller and identifies customer (name + policy number)
2. Agent classifies claim type and captures incident details
3. Agent collects damage description and third-party involvement
4. Agent handles at least one correction mid-flow without losing state
5. Agent detects a risk flag and triggers escalation
6. Session state is saved to JSON on disk at the end

No audio hardware? Run with `--text-mode` flag via stdin/stdout — same playbook and function-calling logic, no mic/speaker required.

---

## Prerequisites & Setup

### Python version

Python 3.11+

### Dependencies

```text
google-genai            # Gemini Live API (includes live WebSocket client)
sounddevice             # mic input + speaker output
numpy                   # PCM buffer handling
pydantic                # claim state schemas
pyyaml                  # playbook definition
python-dotenv           # .env loading
twilio                  # outbound calls, TwiML helpers, status callbacks
fastapi/uvicorn         # webhook + Media Streams WebSocket endpoint
```

### Credentials

```env
GEMINI_API_KEY=...
TWILIO_ACCOUNT_SID=...
TWILIO_API_KEY_SID=...
TWILIO_API_KEY_SECRET=...
TWILIO_NUMBER=...
```

No Google Cloud service account needed for the MVP — the Gemini API key covers the Live API.
Twilio should use API key auth for REST calls, with the account SID and purchased Twilio number coming from `.env`.

### Run

```bash
python app/main.py                  # full voice loop
python app/main.py --text-mode      # CLI stdin/stdout, no audio hardware
```

---

## Recommended Stack

| Component | Choice | Notes |
|---|---|---|
| Language | Python 3.11+ | |
| Real-time audio model | `gemini-3.1-flash-live-preview` | VAD + STT + LLM + TTS in one session |
| Audio I/O | `sounddevice` | PCM capture and playback |
| Audio format (in) | 16-bit PCM, 16 kHz, little-endian | required by Live API |
| Audio format (out) | 16-bit PCM, 24 kHz, little-endian | returned by Live API |
| Voice | `Kore` (or `Charon`, `Fenrir`, `Aoede`) | configured in session |
| Playbook | YAML + function calling tools | model calls tools to update state |
| State | local JSON | Pydantic schema |
| Config | `python-dotenv` + `.env` | |
| Phone transport | Twilio Programmable Voice + Media Streams | bridges PSTN audio to Gemini Live |

---

## Phase 1: Session Architecture

Gemini 3.1 Flash Live uses a persistent WebSocket session per call. Audio streams in both directions concurrently. The model handles its own turn detection (built-in VAD) and speaks back directly.

```text
┌─────────────────────────────────────────────────────┐
│  Live Session (WSS, stateful, up to 15 min)         │
│                                                     │
│  mic PCM (16kHz) ──→ send_realtime_input()          │
│                            ↓                        │
│                   Gemini 3.1 Flash Live             │
│                     - VAD (built-in)                │
│                     - speech understanding          │
│                     - reasoning + playbook          │
│                     - function calling              │
│                     - voice synthesis               │
│                            ↓                        │
│  speaker (24kHz) ←── receive() audio chunks        │
│                            ↓                        │
│  claim state  ←── function call payloads           │
└─────────────────────────────────────────────────────┘
```

### Interruption (barge-in)

Built into the Live API. When the user speaks while the model is talking, `response.server_content.interrupted == True` — stop playback and clear the audio queue. No custom logic needed.

### VAD

Configured in session setup, not in application code:

```python
"realtime_input_config": {
    "automatic_activity_detection": {
        "start_of_speech_sensitivity": StartSensitivity.START_SENSITIVITY_LOW,
        "end_of_speech_sensitivity": EndSensitivity.END_SENSITIVITY_LOW,
        "silence_duration_ms": 500,
    }
}
```

---

## Phase 2: Performance Targets

```text
End-of-speech detection (built-in VAD):   300-500ms
Model first audio chunk:                  400-800ms
Total perceived delay:                    < 1.5s
```

No filler audio needed — the session is always warm and the model starts streaming audio within ~400–800ms of end-of-speech detection.

---

## Phase 3: Architecture

```text
app/
  main.py
  twilio/
    webhooks.py       # TwiML voice webhook + call status callbacks
    media_stream.py   # Twilio Media Streams WebSocket bridge
    client.py         # outbound call helper using Twilio API key auth
  audio/
    input.py          # sounddevice mic capture → PCM chunks
    output.py         # PCM chunk playback + barge-in handling
  agent/
    session.py        # Live API WebSocket session lifecycle
    tools.py          # function call handlers (update_claim_state, escalate)
    prompts.py        # system prompt builder (injects playbook + current state)
    schemas.py        # Pydantic models for tool payloads
  claims/
    playbook.yaml     # state machine definition
    playbook_engine.py
    claim_state.py
    validators.py
  storage/
    sessions/
      claim_session.json
  evals/
    test_conversations.yaml
  .env
```

---

## Phase 4: Claim State

Keep a structured Pydantic object from the start.

```json
{
  "claim_type": null,
  "customer": {
    "full_name": null,
    "policy_number": null,
    "date_of_birth": null
  },
  "incident": {
    "date": null,
    "time": null,
    "location": null,
    "description": null
  },
  "damage": {
    "items": [],
    "estimated_value": null,
    "photos_available": null
  },
  "third_parties": {
    "involved": null,
    "details": null
  },
  "safety": {
    "injuries": null,
    "police_report": null,
    "urgent_risk": null
  },
  "documents": {
    "photos": null,
    "receipts": null,
    "police_report": null
  },
  "handoff_required": false,
  "risk_flags": []
}
```

---

## Phase 5: Playbook Design

The playbook YAML defines required fields per state. The playbook engine determines what's missing and what to ask next. This is **injected into the system prompt** at session start and updated via tool call responses.

```yaml
states:
  identify_customer:
    required:
      - customer.full_name
      - customer.policy_number
    next: classify_claim

  classify_claim:
    required:
      - claim_type
      - incident.date
      - incident.location
    next: collect_incident

  collect_incident:
    required:
      - incident.description
      - damage.items
      - third_parties.involved
      - safety.injuries
    next: collect_documents

  collect_documents:
    required:
      - documents.photos
      - documents.receipts
    next: finalize

  finalize:
    required:
      - customer.preferred_contact_method
    next: done

  escalate:
    trigger: handoff_required == true OR urgent_risk == true
    action: notify_human_agent
    next: done
```

---

## Phase 6: Function Calling Tools

Instead of a structured JSON response schema, the model calls Python functions to update state. The Live API invokes these synchronously (sequential tool use only — async/NON_BLOCKING not supported in 3.1 Flash Live).

### Tool: `update_claim_state`

```python
def update_claim_state(claim_update: dict) -> dict:
    """Called by the model after extracting information from the user."""
    state.merge(claim_update)
    missing = playbook_engine.get_missing_fields(state)
    return {
        "status": "updated",
        "missing_fields": missing,
        "current_playbook_state": playbook_engine.current_state(state),
    }
```

### Tool: `escalate`

```python
def escalate(reason: str, risk_flags: list[str]) -> dict:
    """Called when the model detects urgent risk or handoff is needed."""
    state.handoff_required = True
    state.risk_flags.extend(risk_flags)
    save_session(state)
    notify_human_agent(state, reason)
    return {"status": "escalated", "reason": reason}
```

### Tool: `finalize_claim`

```python
def finalize_claim() -> dict:
    """Called when all required fields are collected."""
    save_session(state)
    return {"status": "done", "session_id": state.session_id}
```

The model decides when to call these based on the conversation. The system prompt instructs it to call `update_claim_state` after every user answer.

---

## Phase 7: System Prompt Strategy

The system prompt is built at session start and includes:

1. Agent role and tone instructions
2. Current playbook state and required fields
3. Current claim state (only filled fields, to stay under context limits)
4. Explicit instruction to call `update_claim_state` after each answer
5. Escalation triggers

```python
def build_system_prompt(playbook_state: str, claim_state: dict) -> str:
    missing = playbook_engine.get_missing_fields(claim_state)
    filled = {k: v for k, v in flatten(claim_state).items() if v is not None}
    return f"""
You are a professional insurance claims intake agent. You are calm, clear, and efficient.

Current stage: {playbook_state}
Fields still needed: {missing}
Already collected: {filled}

After each user answer, call update_claim_state with the extracted fields.
If the user reports injuries, urgent risk, or requests human help, call escalate immediately.
When all required fields are collected, call finalize_claim.
Ask only one question at a time. Confirm corrections naturally without repeating back every field.
"""
```

Do not rebuild the session mid-call to update the prompt. Use tool call return values to pass updated state back to the model.

---

## Phase 8: Conversation Loop

Full async pattern using `google-genai` Live client:

```python
import asyncio
import sounddevice as sd
import numpy as np
from google import genai
from google.genai import types
from dotenv import load_dotenv

load_dotenv()
client = genai.Client(api_key=os.environ["GEMINI_API_KEY"])

SAMPLE_RATE_IN  = 16000
SAMPLE_RATE_OUT = 24000
CHUNK_FRAMES    = 1024

async def send_audio(session):
    loop = asyncio.get_event_loop()
    queue = asyncio.Queue()

    def callback(indata, frames, time, status):
        loop.call_soon_threadsafe(queue.put_nowait, bytes(indata))

    with sd.RawInputStream(samplerate=SAMPLE_RATE_IN, channels=1,
                           dtype="int16", blocksize=CHUNK_FRAMES,
                           callback=callback):
        while True:
            chunk = await queue.get()
            await session.send_realtime_input(
                audio=types.Blob(data=chunk, mime_type="audio/pcm;rate=16000")
            )

async def receive_audio(session):
    stream = sd.RawOutputStream(samplerate=SAMPLE_RATE_OUT, channels=1, dtype="int16")
    stream.start()
    async for response in session.receive():
        if response.server_content:
            if response.server_content.interrupted:
                stream.stop()
                stream.start()
                continue
            for part in response.server_content.model_turn.parts:
                if part.inline_data:
                    stream.write(np.frombuffer(part.inline_data.data, dtype="int16"))
        elif response.tool_call:
            await handle_tool_call(session, response.tool_call)

async def handle_tool_call(session, tool_call):
    results = []
    for call in tool_call.function_calls:
        if call.name == "update_claim_state":
            result = update_claim_state(**call.args)
        elif call.name == "escalate":
            result = escalate(**call.args)
        elif call.name == "finalize_claim":
            result = finalize_claim(**call.args)
        else:
            result = {"error": "unknown tool"}
        results.append(types.FunctionResponse(name=call.name, response=result, id=call.id))
    await session.send_tool_response(function_responses=results)

async def run_session():
    config = types.LiveConnectConfig(
        response_modalities=["AUDIO"],
        system_instruction=build_system_prompt(playbook_engine.initial_state, claim_state),
        tools=[update_claim_state_tool, escalate_tool, finalize_claim_tool],
        speech_config=types.SpeechConfig(
            voice_config=types.VoiceConfig(
                prebuilt_voice_config=types.PrebuiltVoiceConfig(voice_name="Kore")
            )
        ),
        realtime_input_config=types.RealtimeInputConfig(
            automatic_activity_detection=types.AutomaticActivityDetection(
                silence_duration_ms=500,
            )
        ),
    )
    async with client.aio.live.connect(
        model="gemini-3.1-flash-live-preview", config=config
    ) as session:
        await asyncio.gather(send_audio(session), receive_audio(session))

asyncio.run(run_session())
```

### Text mode

Replace `send_audio` with an `async` stdin reader and `receive_audio` with a text printer. Add `response_modalities=["TEXT"]` in the session config. Same tool handling, same playbook engine.

---

## Phase 9: Session Limits & Reconnection

- Audio-only sessions: **15 minute maximum**
- On timeout or disconnect: save current claim state to JSON, reconnect, inject saved state into new session prompt
- Log `session_id` and elapsed time per turn for visibility

```python
async def run_with_reconnect():
    while claim_state.status != "done":
        try:
            await run_session()
        except LiveSessionExpiredError:
            log("session expired, reconnecting with saved state")
            # run_session() will rebuild system prompt from current claim_state
```

---

## Phase 10: Latency Logging

Log per-turn timing from the first audio chunk sent to the first audio chunk received:

```python
{
  "turn": 3,
  "first_audio_sent_ms": 0,
  "first_audio_received_ms": 620,
  "tool_call_round_trip_ms": 45,
  "interrupted": false
}
```

Write to `storage/sessions/<session_id>_latency.jsonl`.

---

## Phase 11: Upgrade Path to telli

Replace `sounddevice` with telli WebSocket call events and telli audio streaming. The session management, playbook engine, function call handlers, and claim state stay unchanged. Pass `response_modalities=["AUDIO", "TEXT"]` and forward the text to telli instead of playing PCM locally.

---

## Phase 12: Twilio Phone Integration

Twilio becomes the first real phone transport. Keep the Gemini session, claim state, playbook engine, tools, and prompt builder unchanged; only replace local microphone/speaker I/O with a Twilio Media Streams bridge.

```text
caller phone
   ↕ PSTN
Twilio Programmable Voice
   ↕ Media Streams WebSocket (8kHz μ-law frames)
app/twilio/media_stream.py
   ↕ decode μ-law + resample to 16kHz PCM
Gemini Live session
   ↕ 24kHz PCM response audio
app/twilio/media_stream.py
   ↕ resample to 8kHz + encode μ-law
Twilio Programmable Voice
   ↕
caller phone
```

### Twilio endpoints

Add a small web server for Twilio-facing routes:

- `POST /twilio/voice` returns TwiML that connects the call to the media WebSocket
- `WS /twilio/media` receives `start`, `media`, `mark`, and `stop` events
- `POST /twilio/status` records call lifecycle events for debugging and session cleanup

### Outbound call helper

Use the Twilio REST API for demo call initiation:

```python
client.calls.create(
    to=target_number,
    from_=os.environ["TWILIO_NUMBER"],
    url=f"{public_base_url}/twilio/voice",
    status_callback=f"{public_base_url}/twilio/status",
)
```

### Audio bridge responsibilities

- Decode incoming Twilio `media.payload` from base64 μ-law 8kHz to PCM
- Resample incoming audio to Gemini's expected 16kHz PCM input
- Send PCM chunks into `send_realtime_input()`
- Resample Gemini's 24kHz PCM output to 8kHz, encode μ-law, and send Twilio `media` events back
- On Gemini interruption, clear pending outbound audio and send a Twilio `clear` event
- Persist the Twilio `callSid` alongside the local `session_id`

### Local development

Expose the local web server with a public HTTPS/WSS tunnel during demos. Configure the Twilio voice webhook to point at `/twilio/voice`, or use the outbound call helper with the tunnel base URL.

---

## Recommended Build Order

### Session A — Text loop works end-to-end (hours 1–2)

1. `--text-mode` CLI: stdin input, Live API text session, print responses
2. Wire function calling: `update_claim_state`, `escalate`, `finalize_claim`
3. Add YAML playbook engine and system prompt builder

**Checkpoint:** complete claim intake from terminal with structured state saved to JSON.

### Session B — Voice layer wired in (hours 2–4)

4. Add `sounddevice` mic capture → PCM chunks → `send_realtime_input`
5. Add PCM playback from `receive()` audio chunks
6. Configure VAD sensitivity and barge-in handling

**Checkpoint:** full voice loop works end-to-end with a real mic/speaker. No separate STT or TTS service needed.

### Session C — Polish & resilience (hours 4–5)

7. Add session reconnection on timeout (15-min limit)
8. Add latency logging per turn
9. Add eval conversations in YAML + a replay runner in `--text-mode`

**Checkpoint:** local voice demo is resilient enough to run repeatedly.

### Session D — Twilio phone transport (do this first)

The plan already has it fully spec'd. The work is:
1. `app/twilio/client.py` — Twilio REST client with API key auth + outbound call helper
2. `app/twilio/webhooks.py` — FastAPI app with `POST /twilio/voice` (TwiML) and `POST /twilio/status`
3. `app/twilio/media_stream.py` — the WebSocket bridge: decode μ-law 8kHz → PCM 16kHz → Gemini, and back

The existing `GeminiSession` in `app/agent/session.py` shouldn't need changes — just a new entry point that feeds it from Twilio instead of sounddevice.

**Checkpoint:** complete claim intake over a real phone call.

### Session E — Playbook depth (after Twilio works end-to-end)

Once you have real phone calls you'll immediately feel where the playbook is shallow. The natural next areas:
- Richer stages: witness info, police report follow-up, rental car preference, repair shop selection
- Smarter `FIELD_EXPECTATIONS` — right now it's just descriptions; you could add validation hints or required sub-fields
- A replay runner in `--text-mode` so you can iterate on the playbook YAML without making real calls

**Checkpoint:** Deepened playbook flows with automated testing.

---

## Best Initial Stack

```text
Python 3.11+
google-genai (Live API)          — gemini-3.1-flash-live-preview
sounddevice                      — mic capture + speaker playback (PCM)
Pydantic                         — claim state schema + tool payloads
PyYAML                           — playbook definition
python-dotenv                    — .env / API key loading
twilio                           — Programmable Voice REST client
FastAPI + Uvicorn                — Twilio webhooks and WebSocket bridge
```
