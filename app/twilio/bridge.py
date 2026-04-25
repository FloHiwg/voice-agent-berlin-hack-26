"""WebSocket bridge: Twilio Media Streams ↔ Gemini Live audio session."""
from __future__ import annotations

import asyncio
import base64
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np
from fastapi import WebSocket
from google import genai
from google.genai import types

from app.agent.session import (
    TranscriptLogger,
    _build_audio_config,
    _receive_voice_loop,
    new_session_id,
    send_live_text,
)
from app.agent.tools import ClaimToolHandlers, SessionFinished
from app.claims.claim_state import ClaimState
from app.claims.playbook_engine import PlaybookEngine
from app.twilio.audio import (
    resample_24k_to_8k,
    resample_8k_to_16k,
    ulaw_decode,
    ulaw_encode,
)

_FLUSH = object()  # barge-in sentinel, mirrors FLUSH from audio/output.py


@dataclass
class _StreamState:
    stream_sid: str | None = None
    call_sid: str | None = None


async def run_twilio_bridge(
    ws: WebSocket,
    *,
    client: genai.Client,
    model: str,
    playbook_path: Path,
    storage_dir: Path,
) -> None:
    playbook_engine = PlaybookEngine.from_yaml(playbook_path)
    claim_state = ClaimState(session_id=new_session_id())
    claim_state.save(storage_dir)
    logger = TranscriptLogger(storage_dir, claim_state.session_id)
    handlers = ClaimToolHandlers(claim_state, playbook_engine, storage_dir)

    print(f"[twilio] session {claim_state.session_id}", flush=True)
    logger.log("session", {"session_id": claim_state.session_id, "mode": "twilio"})

    config = _build_audio_config(playbook_engine, claim_state)
    stream_state = _StreamState()
    gemini_audio_queue: asyncio.Queue = asyncio.Queue()
    speaking_event = asyncio.Event()

    async with client.aio.live.connect(model=model, config=config) as session:
        await send_live_text(
            session,
            "Begin the claims intake now. Greet the customer and ask for the first required field.",
        )
        logger.log("control", "greeting requested")

        gemini_receive = asyncio.create_task(
            _receive_voice_loop(
                session, handlers, logger, gemini_audio_queue, _FLUSH, speaking_event
            )
        )
        twilio_receive = asyncio.create_task(
            _twilio_receive_loop(ws, session, speaking_event, stream_state)
        )
        twilio_send = asyncio.create_task(
            _twilio_send_loop(ws, gemini_audio_queue, speaking_event, stream_state)
        )

        done, pending = await asyncio.wait(
            {gemini_receive, twilio_receive, twilio_send},
            return_when=asyncio.FIRST_EXCEPTION,
        )
        for task in pending:
            task.cancel()
            try:
                await task
            except (asyncio.CancelledError, Exception):
                pass
        for task in done:
            exc = task.exception()
            if exc is not None and not isinstance(exc, SessionFinished):
                logger.log("session", {"event": "error", "reason": str(exc)})

    claim_state.save(storage_dir)
    logger.log("session", {"event": "ended", "call_sid": stream_state.call_sid})
    print(f"[twilio] session {claim_state.session_id} ended", flush=True)


async def _twilio_receive_loop(
    ws: WebSocket,
    session: Any,
    speaking_event: asyncio.Event,
    state: _StreamState,
) -> None:
    """Read Twilio Media Stream events; forward caller audio to Gemini."""
    async for raw in ws.iter_text():
        msg = json.loads(raw)
        event = msg.get("event")

        if event == "start":
            start = msg["start"]
            state.stream_sid = start["streamSid"]
            state.call_sid = start["callSid"]
            print(f"[twilio] call {state.call_sid} stream {state.stream_sid}", flush=True)

        elif event == "media":
            if speaking_event.is_set():
                # mute caller audio while agent is speaking (mirrors local barge-in suppression)
                continue
            payload = base64.b64decode(msg["media"]["payload"])
            pcm_8k = ulaw_decode(payload)
            pcm_16k = resample_8k_to_16k(pcm_8k)
            await session.send_realtime_input(
                audio=types.Blob(data=pcm_16k.tobytes(), mime_type="audio/pcm;rate=16000")
            )

        elif event == "stop":
            break


async def _twilio_send_loop(
    ws: WebSocket,
    audio_queue: asyncio.Queue,
    speaking_event: asyncio.Event,
    state: _StreamState,
) -> None:
    """Read Gemini audio from queue; resample, encode μ-law, send to Twilio."""
    while True:
        chunk = await audio_queue.get()

        if chunk is _FLUSH:
            while not audio_queue.empty():
                try:
                    audio_queue.get_nowait()
                except asyncio.QueueEmpty:
                    break
            speaking_event.clear()
            if state.stream_sid:
                await ws.send_text(
                    json.dumps({"event": "clear", "streamSid": state.stream_sid})
                )
            continue

        if not state.stream_sid:
            continue

        speaking_event.set()
        pcm_24k = np.frombuffer(chunk, dtype=np.int16)
        pcm_8k = resample_24k_to_8k(pcm_24k)
        payload = base64.b64encode(ulaw_encode(pcm_8k)).decode()
        await ws.send_text(
            json.dumps(
                {"event": "media", "streamSid": state.stream_sid, "media": {"payload": payload}}
            )
        )

        if audio_queue.empty():
            await asyncio.sleep(0.1)
            if audio_queue.empty():
                speaking_event.clear()
