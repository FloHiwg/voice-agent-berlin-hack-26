# Getting Started

This guide is a practical runbook for launching the Insurance Claims Intake Voice Agent quickly.

## 1) Prerequisites

- Python `3.13+`
- [`uv`](https://docs.astral.sh/uv/)
- Gemini API key
- (Optional, for phone mode) Twilio account + phone number + ngrok

## 2) Install and Configure

From project root:

```bash
uv sync --extra dev
cp .env.example .env
```

Open `.env` and set at least:

```env
GEMINI_API_KEY=your_key_here
GEMINI_MODEL=gemini-3.1-flash-live-preview
GEMINI_API_VERSION=v1alpha
```

Important: run commands with `uv run python ...` (not plain `python`).

## 3) Run Modes

## A) Text Mode (fastest sanity check)

No microphone or speaker needed.

```bash
uv run python app/main.py --text-mode
```

Optional transport debugging:

```bash
uv run python app/main.py --text-mode --transport live
uv run python app/main.py --text-mode --transport generate-content
```

Replay a prepared transcript:

```bash
uv run python app/main.py --text-mode --eval-transcript path/to/transcript.txt
```

## B) Voice Mode (local mic + speaker)

Add optional voice settings to `.env`:

```env
GEMINI_VOICE=Kore
VAD_SILENCE_MS=800
VAD_START_SENSITIVITY=LOW
VAD_END_SENSITIVITY=LOW
MUTE_MIC_DURING_PLAYBACK=true
AMBIENT_OFFICE_ENABLED=true
AMBIENT_OFFICE_GAIN=0.5
```

Run:

```bash
uv run python app/main.py
```

## C) Phone Mode (Twilio)

Add Twilio settings to `.env`:

```env
TWILIO_ACCOUNT_SID=your_account_sid
TWILIO_API_KEY_SID=your_api_key_sid
TWILIO_API_KEY_SECRET=your_api_key_secret
TWILIO_NUMBER=+1234567890
TWILIO_PUBLIC_URL=https://your-tunnel.ngrok-free.app
```

1. Start tunnel (port `8080`):

```bash
ngrok http 8080
```

2. Put ngrok HTTPS URL into `TWILIO_PUBLIC_URL`.
3. Register webhook on your Twilio number:

```bash
uv run python app/main.py --twilio-setup
```

4. Start Twilio server:

```bash
uv run python app/main.py --twilio-server --port 8080
```

5. Call your Twilio number.

## 4) Verify It Works

- Text mode: model replies in terminal.
- Voice mode: model greets and responds through speakers.
- Twilio mode: inbound call is answered, intro audio plays, then live agent conversation starts.

## 5) Useful Commands

Run all tests:

```bash
uv run pytest
```

Twilio server endpoints:

- `POST /twilio/voice`
- `WS /twilio/media`
- `POST /twilio/status`

Session artifacts are written to `storage/sessions/`.

## 6) Common Pitfalls

- `python-multipart` missing error on Twilio webhooks:
  - Fix by syncing deps: `uv sync`
- ngrok URL changed:
  - Update `TWILIO_PUBLIC_URL`, then rerun `--twilio-setup`
- Using system python instead of project env:
  - Always use `uv run python ...`
