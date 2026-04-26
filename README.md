# Insurance Claims Intake Voice Agent

A real-time insurance claims intake agent powered by Gemini 3.1 Flash Live. The agent conducts a full structured motor claim intake via voice — over a local mic/speaker or a real phone call via Twilio — following a declarative YAML playbook enforced through function calling.

Three run modes:
- **Text** — terminal only, no audio hardware required
- **Voice** — local microphone and speaker via Gemini Live audio
- **Phone** — inbound calls via Twilio Media Streams

---

## Requirements

- Python 3.13+
- `uv`
- Gemini API key

> **Note:** Always use `uv run python` rather than bare `python`. The conda base environment shadows the project venv otherwise.

---

## Setup

```bash
uv sync --extra dev
cp .env.example .env
```

Fill in `.env` — see the relevant section below for which variables each mode needs.

---

## Mode 1: Text

Terminal-only. No microphone or speaker needed. Uses Gemini Live in text mode with the same playbook and function-calling logic as voice mode.

### Environment

```env
GEMINI_API_KEY=your_key_here
GEMINI_MODEL=gemini-3.1-flash-live-preview
GEMINI_TEXT_MODEL=gemini-2.5-flash
GEMINI_API_VERSION=v1alpha
```

### Run

```bash
uv run python app/main.py --text-mode
```

By default (`--transport auto`) the agent tries Gemini Live first, then falls back to the standard `GEMINI_TEXT_MODEL` if Live rejects the session. Force a specific transport when debugging:

```bash
uv run python app/main.py --text-mode --transport live
uv run python app/main.py --text-mode --transport generate-content
```

### Replay a transcript

Feed a prepared conversation file (one user turn per line) to test the playbook without typing:

```bash
uv run python app/main.py --text-mode --eval-transcript path/to/transcript.txt
```

---

## Mode 2: Voice (local mic/speaker)

Full duplex voice via local microphone and speaker. VAD, barge-in, STT, and TTS are all handled inside the Gemini Live session — no additional libraries needed.

### Environment

Same as Text mode, plus optional VAD tuning:

```env
GEMINI_API_KEY=your_key_here
GEMINI_MODEL=gemini-3.1-flash-live-preview
GEMINI_API_VERSION=v1alpha
GEMINI_VOICE=Kore

# VAD tuning (optional)
VAD_SILENCE_MS=800
VAD_START_SENSITIVITY=LOW
VAD_END_SENSITIVITY=LOW

# Set to false when using headphones or echo cancellation
MUTE_MIC_DURING_PLAYBACK=true

# Ambient office background bed (optional)
AMBIENT_OFFICE_ENABLED=true
AMBIENT_OFFICE_GAIN=0.5
# Optional override; defaults to bundled loop in app/audio/assets/
AMBIENT_OFFICE_FILE=
```

Ambient office noise is mixed under agent speech during local playback and Twilio outbound playback. If the loop file is missing or invalid, the app logs a warning and continues without ambient noise.
Sound attribution: The Office by Iwan Gabovitch under CC-BY 3.0 License.
Beep Sound: Sound Effect by freesound_community from Pixabay

### Run

```bash
uv run python app/main.py
```

The agent greets the caller immediately and conducts the full intake. The session ID is printed on start. Ctrl-C saves current state and exits cleanly.

---

## Mode 3: Phone (Twilio)

Inbound phone calls via Twilio Programmable Voice and Media Streams. The Gemini session is unchanged — only the audio I/O layer swaps from sounddevice to a Twilio WebSocket bridge.

### Environment

```env
GEMINI_API_KEY=your_key_here
GEMINI_MODEL=gemini-3.1-flash-live-preview
GEMINI_API_VERSION=v1alpha

TWILIO_ACCOUNT_SID=your_account_sid
TWILIO_API_KEY_SID=your_api_key_sid
TWILIO_API_KEY_SECRET=your_api_key_secret
TWILIO_NUMBER=+1234567890
TWILIO_PUBLIC_URL=https://your-tunnel.ngrok-free.app
```

### First-time setup

1. **Start a public tunnel** (re-run whenever the ngrok URL changes):

   ```bash
   ngrok http 8080
   ```

   Copy the HTTPS URL into `TWILIO_PUBLIC_URL` in `.env`.

2. **Register the webhook** with your Twilio number:

   ```bash
   uv run python app/main.py --twilio-setup
   ```

   This reads `TWILIO_NUMBER` and `TWILIO_PUBLIC_URL` from `.env` and sets the voice webhook via the Twilio REST API. Re-run whenever the tunnel URL changes.

### Run

```bash
uv run python app/main.py --twilio-server --port 8080
```

The server listens on `POST /twilio/voice` (TwiML), `WS /twilio/media` (audio bridge), and `POST /twilio/status` (lifecycle logging). Call your Twilio number — the agent answers immediately.

### Web UI data API

The same FastAPI server also exposes session data for a web UI:

- `GET /api/sessions` — list sessions with available artifacts, claim state, and stage visibility
- `GET /api/sessions/{session_id}` — full details for one session
- `GET /api/sessions/{session_id}/events` — parsed JSONL event log
- `GET /api/sessions/{session_id}/transcript` — transcript text
- `GET /api/sessions/{session_id}/audio` — recorded WAV file

Optional CORS configuration:

```env
WEB_UI_CORS_ORIGINS=*  # or comma-separated origins, e.g. https://my-ui.example.com
```

---

## Storage

Each session writes two files:

```text
storage/sessions/<session_id>.jsonl        # transcript + tool events
storage/sessions/<session_id>_claim.json   # structured claim state (updated after each tool call)
storage/sessions/<session_id>_transcript.txt # human-readable transcript
storage/sessions/<session_id>_audio.wav      # recorded call audio (voice sessions)
```

---

## Project Layout

```text
app/
  main.py                 # CLI entry point
  agent/
    prompts.py            # system prompt builder + FIELD_EXPECTATIONS
    schemas.py            # tool payload schemas
    session.py            # Gemini Live session lifecycle + reconnection
    tools.py              # update_claim_state, escalate, finalize_claim handlers
  audio/
    input.py              # sounddevice mic capture
    output.py             # sounddevice speaker playback + barge-in flush
  claims/
    claim_state.py        # Pydantic claim state schema
    playbook.yaml         # stage machine: required fields per stage
    playbook_engine.py    # stage resolution + missing field logic
  phone/
    server.py             # FastAPI: /twilio/voice, /twilio/media, /twilio/status
    bridge.py             # Twilio Media Streams ↔ Gemini Live bridge
    audio.py              # G.711 μ-law codec + PCM resampling (numpy)
tests/
  test_prompts.py
```

---

## Tests

```bash
uv run pytest
```
