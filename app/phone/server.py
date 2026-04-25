"""FastAPI server: TwiML webhook + Twilio Media Streams WebSocket bridge."""
from __future__ import annotations

import json
import os
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any
from urllib.parse import quote

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Request, WebSocket
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles
from google import genai
from google.genai import types

from app.claims.claim_state import ClaimState
from app.claims.playbook_engine import PlaybookEngine

ROOT = Path(__file__).resolve().parents[2]


@asynccontextmanager
async def _lifespan(app: FastAPI):
    load_dotenv(ROOT / ".env")
    _validate_env()
    api_key = os.environ["GEMINI_API_KEY"]
    api_version = os.getenv("GEMINI_API_VERSION", "v1alpha")
    app.state.client = genai.Client(
        api_key=api_key,
        http_options=types.HttpOptions(api_version=api_version),
    )
    app.state.model = os.getenv("GEMINI_MODEL", "gemini-3.1-flash-live-preview")
    app.state.playbook_path = ROOT / "app" / "claims" / "playbook.yaml"
    app.state.storage_dir = ROOT / "storage" / "sessions"
    yield


app = FastAPI(lifespan=_lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[origin.strip() for origin in os.getenv("WEB_UI_CORS_ORIGINS", "*").split(",") if origin.strip()],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Serve static files
static_dir = ROOT / "static"
if static_dir.exists():
    app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")


def _session_file_paths(storage_dir: Path, session_id: str) -> dict[str, Path]:
    return {
        "claim": storage_dir / f"{session_id}_claim.json",
        "events": storage_dir / f"{session_id}.jsonl",
        "transcript": storage_dir / f"{session_id}_transcript.txt",
        "audio": storage_dir / f"{session_id}_audio.wav",
    }


def _available_session_ids(storage_dir: Path) -> set[str]:
    if not storage_dir.exists():
        return set()

    session_ids: set[str] = set()
    for path in storage_dir.glob("*"):
        name = path.name
        if not name.startswith("claim_"):
            continue
        for suffix in ("_claim.json", "_transcript.txt", "_audio.wav", ".jsonl"):
            if name.endswith(suffix):
                session_ids.add(name[: -len(suffix)])
                break
    return session_ids


def _load_claim_state(path: Path) -> ClaimState | None:
    if not path.exists():
        return None
    return ClaimState.model_validate_json(path.read_text(encoding="utf-8"))


def _build_stage_visibility(engine: PlaybookEngine, claim_state: ClaimState) -> list[dict[str, Any]]:
    current_stage = engine.current_stage(claim_state)
    stages: list[dict[str, Any]] = []
    for stage_name in engine.ordered_state_names:
        state = engine.states[stage_name]
        skipped = bool(state.skip_if and engine._eval_skip_if(claim_state, state.skip_if))
        missing = [] if skipped else sorted(engine._missing_for_state(claim_state, state).keys())
        if skipped:
            status = "skipped"
        elif stage_name == current_stage:
            status = "current"
        elif not missing:
            status = "completed"
        else:
            status = "pending"

        stages.append(
            {
                "name": stage_name,
                "status": status,
                "missing_fields": missing,
                "required_fields": sorted(state.required.keys()),
                "skip_if": state.skip_if,
            }
        )
    return stages


def _build_session_summary(storage_dir: Path, playbook_path: Path, session_id: str) -> dict[str, Any]:
    paths = _session_file_paths(storage_dir, session_id)
    claim_state = _load_claim_state(paths["claim"])
    current_stage: str | None = None
    stages: list[dict[str, Any]] | None = None
    if claim_state is not None:
        engine = PlaybookEngine.from_yaml(playbook_path)
        current_stage = engine.current_stage(claim_state)
        stages = _build_stage_visibility(engine, claim_state)

    return {
        "session_id": session_id,
        "created_at": claim_state.created_at if claim_state else None,
        "completed_at": claim_state.completed_at if claim_state else None,
        "current_stage": current_stage,
        "state": claim_state.model_dump(mode="json") if claim_state else None,
        "stages": stages,
        "artifacts": {
            "claim": paths["claim"].exists(),
            "events": paths["events"].exists(),
            "transcript": paths["transcript"].exists(),
            "audio": paths["audio"].exists(),
        },
    }


def _validate_env() -> None:
    required = [
        "GEMINI_API_KEY",
        "TWILIO_ACCOUNT_SID",
        "TWILIO_API_KEY_SID",
        "TWILIO_API_KEY_SECRET",
        "TWILIO_NUMBER",
        "TWILIO_PUBLIC_URL",
    ]
    missing = [k for k in required if not os.getenv(k)]
    if missing:
        raise RuntimeError(f"Missing env vars: {', '.join(missing)}")


@app.get("/")
async def root() -> FileResponse:
    """Serve the web UI."""
    index_path = ROOT / "static" / "index.html"
    if not index_path.exists():
        raise HTTPException(status_code=404, detail="Web UI not found")
    return FileResponse(index_path)


@app.get("/api/sessions")
async def list_sessions() -> dict[str, Any]:
    storage_dir: Path = app.state.storage_dir
    session_ids = sorted(_available_session_ids(storage_dir), reverse=True)
    sessions = [
        _build_session_summary(storage_dir, app.state.playbook_path, session_id)
        for session_id in session_ids
    ]
    return {"sessions": sessions}


@app.get("/api/sessions/{session_id}")
async def get_session(session_id: str) -> dict[str, Any]:
    storage_dir: Path = app.state.storage_dir
    summary = _build_session_summary(storage_dir, app.state.playbook_path, session_id)
    if not any(summary["artifacts"].values()):
        raise HTTPException(status_code=404, detail=f"Session {session_id!r} not found")
    return summary


@app.get("/api/sessions/{session_id}/events")
async def get_session_events(session_id: str) -> dict[str, Any]:
    storage_dir: Path = app.state.storage_dir
    events_path = _session_file_paths(storage_dir, session_id)["events"]
    if not events_path.exists():
        raise HTTPException(status_code=404, detail=f"No events for session {session_id!r}")

    events: list[dict[str, Any]] = []
    for line in events_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        events.append(json.loads(line))
    return {"session_id": session_id, "events": events}


@app.get("/api/sessions/{session_id}/transcript")
async def get_session_transcript(session_id: str) -> dict[str, Any]:
    storage_dir: Path = app.state.storage_dir
    transcript_path = _session_file_paths(storage_dir, session_id)["transcript"]
    if not transcript_path.exists():
        raise HTTPException(status_code=404, detail=f"No transcript for session {session_id!r}")
    return {
        "session_id": session_id,
        "transcript": transcript_path.read_text(encoding="utf-8"),
    }


@app.get("/api/sessions/{session_id}/audio")
async def get_session_audio(session_id: str) -> FileResponse:
    storage_dir: Path = app.state.storage_dir
    audio_path = _session_file_paths(storage_dir, session_id)["audio"]
    if not audio_path.exists():
        raise HTTPException(status_code=404, detail=f"No audio for session {session_id!r}")
    return FileResponse(audio_path, media_type="audio/wav", filename=audio_path.name)


@app.post("/twilio/voice")
async def voice_webhook(request: Request) -> Response:
    """Return TwiML that connects the inbound call to the Media Streams WebSocket."""
    from twilio.twiml.voice_response import VoiceResponse, Connect, Stream  # type: ignore

    form = await request.form()
    caller_number = form.get("From", "")

    public_url = os.environ["TWILIO_PUBLIC_URL"].rstrip("/")
    ws_url = public_url.replace("https://", "wss://").replace("http://", "ws://")

    stream_url = f"{ws_url}/twilio/media"
    if caller_number:
        stream_url += f"?from={quote(str(caller_number))}"

    response = VoiceResponse()
    connect = Connect()
    stream = Stream(url=stream_url)
    connect.append(stream)
    response.append(connect)
    return Response(content=str(response), media_type="application/xml")


@app.websocket("/twilio/media")
async def media_stream(ws: WebSocket) -> None:
    """Handle a Twilio Media Streams WebSocket for one call."""
    from app.phone.bridge import run_twilio_bridge

    caller_phone = ws.query_params.get("from") or None

    await ws.accept()
    await run_twilio_bridge(
        ws,
        client=ws.app.state.client,
        model=ws.app.state.model,
        playbook_path=ws.app.state.playbook_path,
        storage_dir=ws.app.state.storage_dir,
        caller_phone=caller_phone,
    )


@app.post("/twilio/status")
async def status_callback(request: Request) -> Response:
    """Record Twilio call lifecycle events (for debugging)."""
    form = await request.form()
    call_sid = form.get("CallSid", "?")
    status = form.get("CallStatus", "?")
    print(f"[twilio] {call_sid} → {status}", flush=True)
    return Response(status_code=204)
