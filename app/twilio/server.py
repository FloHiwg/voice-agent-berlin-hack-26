"""FastAPI server: TwiML webhook + Twilio Media Streams WebSocket bridge."""
from __future__ import annotations

import os
from contextlib import asynccontextmanager
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI, Request, WebSocket
from fastapi.responses import Response
from google import genai
from google.genai import types

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


@app.post("/twilio/voice")
async def voice_webhook(request: Request) -> Response:
    """Return TwiML that connects the inbound call to the Media Streams WebSocket."""
    from twilio.twiml.voice_response import VoiceResponse, Connect, Stream  # type: ignore

    public_url = os.environ["TWILIO_PUBLIC_URL"].rstrip("/")
    ws_url = public_url.replace("https://", "wss://").replace("http://", "ws://")

    response = VoiceResponse()
    connect = Connect()
    stream = Stream(url=f"{ws_url}/twilio/media")
    connect.append(stream)
    response.append(connect)
    return Response(content=str(response), media_type="application/xml")


@app.websocket("/twilio/media")
async def media_stream(ws: WebSocket) -> None:
    """Handle a Twilio Media Streams WebSocket for one call."""
    from app.twilio.bridge import run_twilio_bridge

    await ws.accept()
    await run_twilio_bridge(
        ws,
        client=ws.app.state.client,
        model=ws.app.state.model,
        playbook_path=ws.app.state.playbook_path,
        storage_dir=ws.app.state.storage_dir,
    )


@app.post("/twilio/status")
async def status_callback(request: Request) -> Response:
    """Record Twilio call lifecycle events (for debugging)."""
    form = await request.form()
    call_sid = form.get("CallSid", "?")
    status = form.get("CallStatus", "?")
    print(f"[twilio] {call_sid} → {status}", flush=True)
    return Response(status_code=204)
