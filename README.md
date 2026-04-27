# Lisa — Insurance Claims Voice Agent

> **Big Berlin Hack · April 25–26, 2026**
> Challenge by [Inca](https://www.get-inca.com) · Track prize: AirPod Pros

---

## The Challenge

Inca's "Human Test": build a phone-based voice agent that handles inbound insurance claim calls and convinces the callers they are speaking to a human. The jury *are* the callers — each juror calls the number, plays a claimant reporting an accident, then casts a blind vote: **human or AI**. To win, the agent needs more than 50% human votes and must produce complete, high-quality call documentation.

---

## What We Built

**Lisa** — a real-time voice agent that answers inbound calls, conducts a full structured motor insurance claims intake, and sounds human enough to cross the 50% threshold. Built in roughly 24 hours.

![Web UI showing active session and extracted claim data](assets/screenshots/web-ui.png)

**Example call recording:**

[`claim_20260426_111930_1f7c_audio.wav`](assets/claim_20260426_111930_1f7c_audio.wav)

---

## Approach

### Real-time voice with Gemini Live

The core conversation runs on Gemini 3.1 Flash Live — Google's real-time multimodal API that handles speech-to-text, reasoning, and text-to-speech within a single low-latency session. This gave us full-duplex voice with barge-in support and VAD out of the box, without stitching together separate ASR and TTS services.

### Keeping response time human-like

Structured data extraction (turning the conversation into a claim record) is handled by a separate Gemini 3.0 Flash call. Rather than blocking the live session while waiting for that extraction, we offload it to a background thread. The agent's voice response goes out immediately; the claim state updates asynchronously. This keeps perceived latency in the human range even when extraction takes a moment.

### Sounding human

- Ambient office background noise mixed under the agent's speech
- Natural voice (Gemini's "Kore" voice, tuned VAD sensitivity)
- A declarative YAML playbook drives the intake flow via function calling — the agent never sounds like it's reading a form

### Structured output

After the call, every session writes a full transcript, a structured JSON claim record, and the raw audio to disk. A FastAPI backend exposes these via a REST API; a web UI built with Lovable renders the session data live.

---

## Tech Stack

| Layer | Technology |
|---|---|
| Voice AI | Gemini 3.1 Flash Live (real-time STT + LLM + TTS) |
| Data extraction | Gemini 3.0 Flash |
| Telephony | Twilio Programmable Voice + Media Streams |
| Backend | FastAPI · Python 3.13 |
| Frontend | Lovable |
| Audio bridge | WebSocket · G.711 μ-law codec · numpy |

---

## Architecture

```
Incoming call (Twilio)
       │
       ▼
  FastAPI server
  /twilio/voice  ──► TwiML: connect to WebSocket
  /twilio/media  ──► WebSocket bridge
       │
       ▼
  Gemini Live session          ← real-time voice conversation
       │
       ├── function call: update_claim_state
       │        └── background thread: Gemini Flash extraction ← async, non-blocking
       │
       └── function call: finalize_claim
                └── writes transcript + claim JSON + audio to storage/
```

---

## Team

- Mattheu Classen
- Florian Gutendorf Heiwig

---

## Quick Start

Requires Python 3.13+ and [`uv`](https://docs.astral.sh/uv/).

```bash
git clone <repo-url>
cd voice-project
uv sync --extra dev
cp .env.example .env   # fill in GEMINI_API_KEY at minimum
```

**Run in text mode** (no mic/phone needed, good for a first test):

```bash
uv run python app/main.py --text-mode
```

**Run with a real phone call** (Twilio + ngrok):

```bash
ngrok http 8080                                    # copy HTTPS URL → TWILIO_PUBLIC_URL in .env
uv run python app/main.py --twilio-setup           # register webhook
uv run python app/main.py --twilio-server --port 8080
```

→ Full setup, all modes, and environment variables: [docs/GETTING_STARTED.md](docs/GETTING_STARTED.md)

---

## Attributions

- Ambient office audio: *The Office* by Iwan Gabovitch — [CC BY 3.0](https://creativecommons.org/licenses/by/3.0/)
- Beep sound: Sound Effect by freesound_community via [Pixabay](https://pixabay.com)
