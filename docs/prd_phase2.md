# PRD — Phase 2: Voice Layer (Microphone + Speaker)

## Overview

Add real-time audio I/O to the claims intake agent built in Phase 1. The agent speaks and listens through the local microphone and speaker using Gemini 3.1 Flash Live in audio mode. All session management, playbook logic, tool handlers, and state persistence from Phase 1 remain unchanged — only the I/O layer swaps from stdin/stdout to PCM audio streams.

This phase produces a fully working voice demo: the operator picks up the phone (metaphorically), speaks naturally, and the agent conducts the complete intake — VAD, barge-in, and voice synthesis all handled by the Live API with no additional libraries.

---

## Goals

- Full end-to-end voice intake: mic → Gemini Live → speaker, with the same playbook and function calling as Phase 1
- Sub-second perceived latency from end of speech to first agent audio
- Barge-in: user can speak while the agent is talking and the agent stops immediately
- Session reconnects automatically on the 15-minute Live API timeout without losing claim state
- Running without `--text-mode` starts voice mode; `--text-mode` still works unchanged

## Non-Goals

- No telli or telephony integration — that is Phase 3
- No latency logging or metrics — that is Phase 3
- No eval runner changes — Phase 1 eval replay stays text-only
- No cloud deployment or multi-tenant support
- No noise cancellation or audio pre-processing beyond what sounddevice provides

---

## User Stories

**As a demo operator**, I can speak to the agent through my laptop microphone and hear its responses through my speakers, so I can show a realistic claims intake without typing.

**As a developer**, I can run `python app/main.py` (no flags) and have the voice session start immediately, so the default experience is the final product, not the test harness.

**As a developer**, if the Live session hits its 15-minute limit mid-intake, the agent reconnects transparently and continues from the last saved claim state, so a long intake never fails silently.

---

## Functional Requirements

### FR-1: Voice session startup

- Running `python app/main.py` (no `--text-mode` flag) starts an audio session
- `response_modalities=["AUDIO"]` is set in the LiveConnectConfig
- A `SpeechConfig` with voice `Kore` is included in the session config
- The agent sends an initial greeting turn immediately on connect (same trigger as text mode: a control turn requesting greeting + first question)
- The session ID is printed to stdout on startup

### FR-2: Microphone capture

- `sounddevice.RawInputStream` captures PCM at 16 kHz, 16-bit, mono
- Audio chunks of 1024 frames are pushed into an `asyncio.Queue` via a `callback`
- A `send_audio` coroutine drains the queue and calls `session.send_realtime_input(audio=Blob(data=chunk, mime_type="audio/pcm;rate=16000"))`
- Capture runs continuously for the duration of the session; no push-to-talk

### FR-3: Speaker playback

- A `receive_audio` coroutine reads from `live_session.receive()`
- Audio parts (`inline_data.data`) are written to a `sounddevice.RawOutputStream` at 24 kHz, 16-bit, mono
- Playback is append-only while the model is speaking; no buffering or resampling

### FR-4: Barge-in handling

- When `response.server_content.interrupted == True`, the output stream is stopped and restarted (flushing any queued audio)
- No custom VAD logic; the Live API's built-in detection handles turn boundaries
- The mic capture coroutine is never paused — it streams continuously regardless of whether the agent is speaking

### FR-5: VAD configuration

- `RealtimeInputConfig.automatic_activity_detection` is set in the session config:
  - `silence_duration_ms: 800` (slightly longer than plan.md default to reduce false end-of-speech on insurance terminology)
  - `start_of_speech_sensitivity: START_SENSITIVITY_LOW`
  - `end_of_speech_sensitivity: END_SENSITIVITY_LOW`
- These values are tunable via environment variables (`VAD_SILENCE_MS`, `VAD_START_SENSITIVITY`, `VAD_END_SENSITIVITY`) so demo tuning doesn't require code changes

### FR-6: Tool call handling in audio mode

- The `receive_audio` coroutine handles both audio parts and tool calls in the same receive loop
- When a tool call arrives, audio playback is not paused — the tool handler runs inline and the response is sent before the next audio chunk arrives
- Tool dispatch reuses `ClaimToolHandlers.dispatch()` from Phase 1 unchanged

### FR-7: Session reconnection

- If `live_session.receive()` raises a timeout or disconnect error, `run_session` catches it, logs the event, and reconnects
- On reconnect, a new Live session is opened with the system prompt rebuilt from the current (saved) `ClaimState`
- A control turn is injected: `"Reconnecting after session timeout. Current claim state: {summary}. Continue the intake from where we left off."`
- Reconnection attempts up to 3 times with a 2-second delay between attempts; on the 3rd failure the session ends with a `SessionFinished("reconnect_failed")` error
- The `completed_at` field is not written until `finalize_claim` or `escalate` is called — an interrupted reconnect is visible in the claim JSON as a missing `completed_at`

### FR-8: Graceful shutdown

- Ctrl-C stops mic capture and speaker playback cleanly before exiting
- The current claim state is saved to disk before the process exits (even if the session is mid-intake)

---

## Technical Specification

### Entry point

```
python app/main.py              # voice mode (default)
python app/main.py --text-mode  # text mode (Phase 1, unchanged)
```

`run_session()` in `session.py` branches on `text_mode`: voice mode calls `run_voice_session()`, text mode calls the existing `run_live_text_session()` / `run_generate_content_text_session()`.

### New modules

```
app/
  audio/
    __init__.py
    input.py     # mic capture: sounddevice RawInputStream → asyncio.Queue → send_realtime_input
    output.py    # PCM playback: sounddevice RawOutputStream + barge-in flush
```

### Gemini Live — audio session pattern

```python
config = types.LiveConnectConfig(
    response_modalities=["AUDIO"],
    system_instruction=build_system_prompt(playbook_engine, claim_state),
    tools=tools,
    speech_config=types.SpeechConfig(
        voice_config=types.VoiceConfig(
            prebuilt_voice_config=types.PrebuiltVoiceConfig(voice_name="Kore")
        )
    ),
    realtime_input_config=types.RealtimeInputConfig(
        automatic_activity_detection=types.AutomaticActivityDetection(
            silence_duration_ms=int(os.getenv("VAD_SILENCE_MS", "800")),
        )
    ),
)

async with client.aio.live.connect(model=model, config=config) as session:
    await asyncio.gather(send_audio(session), receive_audio(session, handlers, logger))
```

### Audio input coroutine

```python
async def send_audio(session):
    loop = asyncio.get_event_loop()
    queue: asyncio.Queue[bytes] = asyncio.Queue()

    def callback(indata, frames, time, status):
        loop.call_soon_threadsafe(queue.put_nowait, bytes(indata))

    with sd.RawInputStream(samplerate=16000, channels=1, dtype="int16",
                           blocksize=1024, callback=callback):
        while True:
            chunk = await queue.get()
            await session.send_realtime_input(
                audio=types.Blob(data=chunk, mime_type="audio/pcm;rate=16000")
            )
```

### Audio output and receive coroutine

```python
async def receive_audio(session, handlers, logger):
    stream = sd.RawOutputStream(samplerate=24000, channels=1, dtype="int16")
    stream.start()
    async for response in session.receive():
        if response.server_content:
            if response.server_content.interrupted:
                stream.stop()
                stream.start()
                continue
            for part in (response.server_content.model_turn or types.ModelTurn()).parts or []:
                if part.inline_data:
                    stream.write(np.frombuffer(part.inline_data.data, dtype="int16"))
        elif response.tool_call:
            await handle_tool_call(session, response.tool_call, handlers, logger)
```

### Reconnection wrapper

```python
MAX_RECONNECT_ATTEMPTS = 3

async def run_voice_session(*, client, model, playbook_engine, claim_state, storage_dir, logger):
    for attempt in range(MAX_RECONNECT_ATTEMPTS):
        try:
            config = build_audio_config(playbook_engine, claim_state)
            async with client.aio.live.connect(model=model, config=config) as session:
                handlers = ClaimToolHandlers(claim_state, playbook_engine, storage_dir)
                greeting = "Begin the claims intake now. Greet the customer."
                if attempt > 0:
                    greeting = f"Reconnecting after session timeout. Current claim state: {claim_state.summary()}. Continue the intake."
                await send_control_turn(session, greeting)
                await asyncio.gather(send_audio(session), receive_audio(session, handlers, logger))
                return  # clean exit
        except (LiveSessionExpiredError, DisconnectError) as exc:
            logger.log("session", {"event": "reconnect", "attempt": attempt + 1, "reason": str(exc)})
            claim_state.save(storage_dir)
            if attempt < MAX_RECONNECT_ATTEMPTS - 1:
                await asyncio.sleep(2)
    raise SessionFinished("reconnect_failed")
```

### Dependencies added

```
sounddevice    # mic capture + speaker playback
numpy          # PCM buffer handling (np.frombuffer)
```

Both are added to `pyproject.toml`. `sounddevice` requires `libportaudio` on macOS (available via `brew install portaudio`).

### Environment variables

| Variable | Default | Purpose |
|---|---|---|
| `GEMINI_VOICE` | `Kore` | Live API voice name |
| `VAD_SILENCE_MS` | `800` | Silence duration before end-of-speech |
| `VAD_START_SENSITIVITY` | `LOW` | Start-of-speech sensitivity |
| `VAD_END_SENSITIVITY` | `LOW` | End-of-speech sensitivity |

### File structure additions (delta from Phase 1)

```
app/
  audio/
    __init__.py
    input.py        # send_audio() coroutine
    output.py       # receive_audio() coroutine + barge-in flush
  agent/
    session.py      # run_voice_session() added; run_session() branches on text_mode
```

No changes to `claims/`, `agent/tools.py`, `agent/prompts.py`, or `agent/schemas.py`.

---

## Acceptance Criteria

| # | Scenario | Pass condition |
|---|---|---|
| AC-1 | Voice happy path | Running `python app/main.py` with a real mic/speaker completes a full intake (greeting → all required fields → `finalize_claim`). `_claim.json` on disk contains no null required fields. |
| AC-2 | Agent speaks first | On connect, the agent greets the caller within 2 seconds before any user speech. |
| AC-3 | Barge-in | User speaks while agent is talking. Agent stops within 500ms (Live API interrupted flag). Agent audio queue is cleared. No audio overlap or corruption. |
| AC-4 | VAD end-of-speech | After the user finishes speaking and is silent for ~800ms, the agent begins responding. No accidental mid-sentence cut-offs during a test sentence with a natural 300ms internal pause. |
| AC-5 | Escalation via voice | User says aloud "I was injured." Agent calls `escalate`, speaks an escalation message, and the session ends cleanly. `claim_state.handoff_required == true` in saved JSON. |
| AC-6 | Text mode unchanged | `python app/main.py --text-mode` behaves identically to Phase 1. All Phase 1 acceptance criteria still pass. |
| AC-7 | Reconnection | Simulate a `LiveSessionExpiredError` (or wait for 15-min timeout in a long test). Agent reconnects, injects saved state into the new session prompt, and continues asking for missing fields without restarting the intake from scratch. |
| AC-8 | Reconnect failure | Three consecutive reconnect failures raise `SessionFinished("reconnect_failed")` and print a clear error. `_claim.json` on disk reflects state at the point of failure. |
| AC-9 | Ctrl-C shutdown | Ctrl-C during an active session stops mic/speaker cleanly and writes the current (partial) claim state to disk before exit. |
| AC-10 | VAD env override | Setting `VAD_SILENCE_MS=1500` in `.env` changes the silence threshold without code changes. |

---

## Open Questions

| # | Question | Impact |
|---|---|---|
| OQ-1 | Does the Live API return audio parts and tool calls in separate responses, or can they appear in the same response object? | Determines whether the receive loop needs to check both `server_content` and `tool_call` in every response, or can branch exclusively. |
| OQ-2 | What is the actual typical latency from end-of-speech detection to first audio chunk returned? Is 800ms `silence_duration_ms` too conservative for a natural conversation pace? | May need to reduce to 500ms or make it configurable per demo environment. |
| OQ-3 | Does `sounddevice.RawOutputStream.write()` block if the buffer is full? If so, it will stall the receive loop and delay tool call handling. | May need to move playback to a separate thread or use non-blocking write with a discard-on-overflow strategy. |
| OQ-4 | On macOS 15, does `sounddevice` require microphone permission to be pre-granted, or does it trigger the OS permission dialog on first run? | If the dialog is async (user must click Allow), the first few seconds of audio may be dropped. May need a startup check. |
| OQ-5 | Is `LiveSessionExpiredError` the correct exception class name in the `google-genai` SDK, or does the SDK expose a different error for the 15-minute timeout? | Reconnection logic depends on catching the right exception type. |
