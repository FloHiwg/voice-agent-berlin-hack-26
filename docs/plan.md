# Claims Intake Voice Agent — Plan

## Goal

An insurance claims intake agent that collects structured claim data via voice,
runs deterministically from a YAML playbook, and works across three transports:
terminal (text), local mic/speaker (voice), and inbound phone calls (Twilio).

---

## Architecture

```text
mic / stdin / Twilio PSTN
        ↓
    audio bridge (app/phone/) or direct PCM (app/agent/)
        ↓
Gemini 3.1 Flash Live — VAD + STT + LLM + TTS, single WebSocket session
        ↓  ↑  function calls
  playbook engine (app/claims/playbook_engine.py)
        ↓
  claim state (app/claims/claim_state.py) — Pydantic, saved to JSON
```

VAD, transcription, and voice synthesis are handled inside the Gemini Live session.
No separate STT/TTS libraries needed.

---

## What Is Built

### Session A — Text mode (complete)
- `--text-mode` CLI: stdin input, Live API text session, stdout responses
- Function calling: `update_claim_state`, `escalate`, `finalize_claim`
- YAML playbook engine + system prompt builder
- Claim state saved to `storage/sessions/<id>_claim.json`

### Session B — Voice layer (complete)
- `sounddevice` mic capture → 16kHz PCM → `send_realtime_input`
- PCM playback at 24kHz from `receive()` audio chunks
- Barge-in: clears audio queue on `interrupted` signal

### Session D — Twilio phone transport (complete)
- `app/phone/server.py` — FastAPI with `POST /twilio/voice` (TwiML) and `WS /twilio/media`
- `app/phone/bridge.py` — bridges Twilio Media Streams ↔ Gemini Live session
- `app/phone/audio.py` — G.711 μ-law codec (numpy, Python 3.13-safe), 8kHz↔16kHz/24kHz resampling
- `--twilio-setup` registers the voice webhook via Twilio REST API
- `--twilio-server --port 8080` starts the FastAPI server

### Phase 3 — Playbook depth (complete)
- Identity OR logic: policy number alone, OR full name + date of birth
- `verify_caller` stage: checks whether caller is the policyholder; collects caller name + relationship if not
- Conditional stages via `skip_if` in playbook YAML: `verify_caller`, `third_party_details`, `witness`, `police_details`, `rental_preference`, `repair_preference`
- Expanded `FIELD_EXPECTATIONS` and identity rules injected into system prompt
- Eval runner: `--eval-transcript <file.yaml> --eval-assert` replays a YAML transcript and asserts final claim state
- Three eval scenarios: `evals/happy_path.yaml`, `evals/third_party_caller.yaml`, `evals/escalation.yaml`

---

## Playbook Stages

```
identify_customer → verify_caller* → classify_claim → collect_incident
    → third_party_details* → witness* → police_details* → collect_damage
    → settlement → rental_preference* → repair_preference* → collect_documents
    → finalize
```

`*` = conditional stage with `skip_if`

---

## How Agent Instructions Work

| Layer | File | Purpose |
|---|---|---|
| Playbook YAML | `app/claims/playbook.yaml` | Stage order and required fields per stage |
| Field expectations | `app/agent/prompts.py` `FIELD_EXPECTATIONS` | Per-field filling rules given to the model |
| System prompt rules | `app/agent/prompts.py` `build_system_prompt()` | Behavioral rules, identity OR logic, escalation |

---

## Run Commands

```bash
# Text mode (no audio hardware needed)
uv run python app/main.py --text-mode

# Voice mode (mic + speaker)
uv run python app/main.py

# Phone mode (Twilio)
ngrok http 8080                                          # start tunnel
uv run python app/main.py --twilio-setup                 # register webhook (once per tunnel URL)
uv run python app/main.py --twilio-server --port 8080    # start server

# Eval runner
uv run python app/main.py --text-mode --eval-transcript evals/happy_path.yaml --eval-assert
uv run python app/main.py --text-mode --eval-transcript evals/third_party_caller.yaml --eval-assert
uv run python app/main.py --text-mode --eval-transcript evals/escalation.yaml --eval-assert
```

Always use `uv run python` — the conda base env is active and would shadow the project venv.

---

## Credentials (`.env`)

```env
GEMINI_API_KEY=...
TWILIO_ACCOUNT_SID=...
TWILIO_API_KEY_SID=...
TWILIO_API_KEY_SECRET=...
TWILIO_NUMBER=...
TWILIO_PUBLIC_URL=https://your-tunnel.ngrok-free.app
```

---

## Stack

| Component | Choice |
|---|---|
| Model | `gemini-3.1-flash-live-preview` |
| Audio I/O (local) | `sounddevice` |
| Audio I/O (phone) | Twilio Media Streams + numpy G.711 codec |
| Phone transport | Twilio Programmable Voice |
| Server | FastAPI + Uvicorn |
| State schema | Pydantic |
| Playbook | YAML |
| Config | `python-dotenv` |

---

## What Is Left

See `TODO.md`.
