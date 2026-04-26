"""WebSocket bridge: Twilio Media Streams ↔ Gemini Live audio session."""
from __future__ import annotations

import asyncio
import base64
import json
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np
from fastapi import WebSocket
from google import genai
from google.genai import types

from app.agent.session import (
    AudioRecorder,
    TranscriptLogger,
    _build_audio_config,
    _env_flag,
    _receive_voice_loop,
    merge_audio_recordings,
    new_session_id,
    send_live_text,
)
from app.audio.ambient import AmbientLoopMixer
from app.config import ambient_office_config
from app.agent.tools import ClaimToolHandlers, SessionFinished
from app.claims.claim_state import ClaimState
from app.claims.playbook_engine import PlaybookEngine
from app.phone.audio import (
    resample_24k_to_8k,
    resample_8k_to_16k,
    ulaw_decode,
    ulaw_encode,
)

_FLUSH = object()  # barge-in sentinel, mirrors FLUSH from audio/output.py
_AMBIENT_FRAME_SECONDS = 0.10
_AMBIENT_FRAME_SAMPLES_24K = int(24000 * _AMBIENT_FRAME_SECONDS)
_PLAYBACK_TAIL_SECONDS = 0.10
_PRE_GREETING_DELAY_SECONDS = 1


def _build_ambient_mixer() -> AmbientLoopMixer | None:
    config = ambient_office_config()
    if not config.enabled or config.gain <= 0.0:
        return None
    try:
        return AmbientLoopMixer.from_wav(
            sample_rate=24000,
            gain=config.gain,
            wav_path=config.file_path,
        )
    except Exception as exc:  # pragma: no cover - defensive runtime fallback
        print(f"[twilio] ambient disabled: {exc}", flush=True)
        return None


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
    caller_phone: str | None = None,
) -> None:
    transcription_enabled = _env_flag("VOICE_TRANSCRIPTION", False)
    playbook_engine = PlaybookEngine.from_yaml(playbook_path)
    claim_state = ClaimState(session_id=new_session_id())
    claim_state.save(storage_dir)
    logger = TranscriptLogger(storage_dir, claim_state.session_id)
    recording_started_at = time.monotonic()
    agent_recorder = AudioRecorder(
        storage_dir,
        claim_state.session_id,
        suffix="audio_agent",
        sample_rate=24000,
        start_time=recording_started_at,
    )
    caller_recorder = AudioRecorder(
        storage_dir,
        claim_state.session_id,
        suffix="audio_caller",
        sample_rate=16000,
        start_time=recording_started_at,
    )
    handlers = ClaimToolHandlers(claim_state, playbook_engine, storage_dir)

    print(f"[twilio] session {claim_state.session_id}", flush=True)
    logger.log("session", {"session_id": claim_state.session_id, "mode": "twilio"})

    config = _build_audio_config(playbook_engine, claim_state, caller_phone=caller_phone)
    stream_state = _StreamState()
    gemini_audio_queue: asyncio.Queue = asyncio.Queue()
    speaking_event = asyncio.Event()

    try:
        async with client.aio.live.connect(model=model, config=config) as session:
            # Safety delay so the agent does not greet immediately if Twilio intro audio is skipped.
            await asyncio.sleep(_PRE_GREETING_DELAY_SECONDS)

            # Start receiver/sender tasks. We must wait for Twilio's "start" event
            # (which sets stream_sid) before sending the greeting to Gemini.
            # Otherwise twilio_send drops the greeting audio because stream_sid is None.
            stream_ready = asyncio.Event()
            gemini_receive = asyncio.create_task(
                _receive_voice_loop(
                    session, handlers, logger, gemini_audio_queue, _FLUSH,
                    agent_recorder, transcription_enabled=transcription_enabled, speaking_event=speaking_event,
                )
            )
            twilio_receive = asyncio.create_task(
                _twilio_receive_loop(
                    ws, session, speaking_event, stream_state,
                    on_chunk=caller_recorder.add_chunk,
                    on_stream_ready=stream_ready,
                )
            )
            twilio_send = asyncio.create_task(
                _twilio_send_loop(ws, gemini_audio_queue, speaking_event, stream_state)
            )

            # Block until stream_sid is confirmed so greeting audio reaches the caller.
            await asyncio.wait_for(stream_ready.wait(), timeout=10.0)

            await send_live_text(
                session,
                (
                    "Begin the call now. Open with the EXACT scripted greeting from your "
                    'system instructions ("Hello, this is Lisa from National Insurance '
                    'emergency hotline. What happened?") and wait for the caller\'s response.'
                ),
            )
            logger.log("control", "Lisa opening greeting requested")

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
    finally:
        claim_state.save(storage_dir)
        logger.finalize()
        agent_recorder.stop()
        caller_recorder.stop()
        merge_audio_recordings(
            caller_recorder.audio_path,
            agent_recorder.audio_path,
            storage_dir / f"{claim_state.session_id}_audio.wav",
        )

    logger.log("session", {"event": "ended", "call_sid": stream_state.call_sid})
    print(f"[twilio] session {claim_state.session_id} ended", flush=True)


async def _twilio_receive_loop(
    ws: WebSocket,
    session: Any,
    speaking_event: asyncio.Event,
    state: _StreamState,
    on_chunk: Callable[[bytes], None] | None = None,
    on_stream_ready: asyncio.Event | None = None,
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
            if on_stream_ready is not None:
                on_stream_ready.set()

        elif event == "media":
            payload = base64.b64decode(msg["media"]["payload"])
            pcm_8k = ulaw_decode(payload)
            pcm_16k = resample_8k_to_16k(pcm_8k)
            if on_chunk:
                on_chunk(pcm_16k.tobytes())
            if speaking_event.is_set():
                continue
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
    ambient_mixer = _build_ambient_mixer()
    pending_chunk: object | None = None

    async def _send_pcm_24k(pcm_24k: np.ndarray) -> None:
        pcm_8k = resample_24k_to_8k(pcm_24k)
        payload = base64.b64encode(ulaw_encode(pcm_8k)).decode()
        await ws.send_text(
            json.dumps(
                {"event": "media", "streamSid": state.stream_sid, "media": {"payload": payload}}
            )
        )

    async def _send_ambient_frame() -> None:
        if not state.stream_sid or ambient_mixer is None:
            return
        ambient_only_24k = ambient_mixer.mix(np.zeros(_AMBIENT_FRAME_SAMPLES_24K, dtype=np.int16))
        await _send_pcm_24k(ambient_only_24k)

    async def _keep_ambient_alive_during_tail() -> object | None:
        deadline = time.monotonic() + _PLAYBACK_TAIL_SECONDS
        while audio_queue.empty():
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return None
            if not state.stream_sid or ambient_mixer is None:
                try:
                    return await asyncio.wait_for(audio_queue.get(), timeout=remaining)
                except asyncio.TimeoutError:
                    return None
            await _send_ambient_frame()
        return await audio_queue.get()

    while True:
        if pending_chunk is None:
            try:
                chunk = await asyncio.wait_for(audio_queue.get(), timeout=_AMBIENT_FRAME_SECONDS)
            except asyncio.TimeoutError:
                await _send_ambient_frame()
                continue
        else:
            chunk = pending_chunk
            pending_chunk = None

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
        if ambient_mixer is not None:
            pcm_24k = ambient_mixer.mix(pcm_24k)
        await _send_pcm_24k(pcm_24k)

        if audio_queue.empty():
            pending_chunk = await _keep_ambient_alive_during_tail()
            if pending_chunk is None:
                speaking_event.clear()
