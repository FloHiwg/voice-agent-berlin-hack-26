from __future__ import annotations

import asyncio
import json
import os
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

from google import genai
from google.genai import types
from google.genai import errors

from app.agent.prompts import build_system_prompt
from app.agent.schemas import tools
from app.agent.tools import ClaimToolHandlers, SessionFinished
from app.claims.claim_state import ClaimState
from app.claims.playbook_engine import PlaybookEngine

_MAX_RECONNECT_ATTEMPTS = 3


def _env_flag(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def new_session_id() -> str:
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    return f"claim_{stamp}_{uuid4().hex[:4]}"


class AudioRecorder:
    """Records audio streams to WAV file for voice sessions."""

    def __init__(self, storage_dir: Path, session_id: str, sample_rate: int = 24000) -> None:
        storage_dir.mkdir(parents=True, exist_ok=True)
        self.audio_path = storage_dir / f"{session_id}_audio.wav"
        self.sample_rate = sample_rate
        self.audio_chunks: list[bytes] = []
        self.recording = True

    def add_chunk(self, audio_data: bytes) -> None:
        """Add audio chunk to recording buffer."""
        if self.recording:
            self.audio_chunks.append(audio_data)

    def save(self) -> None:
        """Save recorded audio to WAV file."""
        if not self.audio_chunks:
            return

        try:
            import wave
            import numpy as np

            # Combine all chunks
            audio_bytes = b"".join(self.audio_chunks)

            # Convert to numpy array (assuming 16-bit PCM)
            audio_array = np.frombuffer(audio_bytes, dtype=np.int16)

            # Save as WAV
            with wave.open(str(self.audio_path), "wb") as wav_file:
                wav_file.setnchannels(1)  # Mono
                wav_file.setsampwidth(2)  # 16-bit
                wav_file.setframerate(self.sample_rate)
                wav_file.writeframes(audio_array.tobytes())

            print(f"\nAudio recording saved: {self.audio_path}", flush=True)
        except Exception as e:
            print(f"\nWarning: Failed to save audio recording: {e}", flush=True)

    def stop(self) -> None:
        """Stop recording and save."""
        self.recording = False
        self.save()


class TranscriptLogger:
    def __init__(self, storage_dir: Path, session_id: str) -> None:
        storage_dir.mkdir(parents=True, exist_ok=True)
        self.jsonl_path = storage_dir / f"{session_id}.jsonl"
        self.transcript_path = storage_dir / f"{session_id}_transcript.txt"
        self.session_start_time = datetime.now(UTC)

        # Initialize transcript file with header
        with self.transcript_path.open("w", encoding="utf-8") as f:
            f.write(f"=== Call Transcript ===\n")
            f.write(f"Session ID: {session_id}\n")
            f.write(f"Started: {self.session_start_time.isoformat()}\n")
            f.write(f"{'='*50}\n\n")

    def log(self, role: str, content: Any) -> None:
        timestamp = datetime.now(UTC)

        # Log to JSONL (existing format)
        record = {
            "timestamp": timestamp.isoformat(),
            "role": role,
            "content": content,
        }
        with self.jsonl_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, sort_keys=True) + "\n")

        # Log to human-readable transcript
        self._log_transcript(role, content, timestamp)

    def _log_transcript(self, role: str, content: Any, timestamp: datetime) -> None:
        """Write human-readable transcript entry."""
        with self.transcript_path.open("a", encoding="utf-8") as f:
            elapsed = (timestamp - self.session_start_time).total_seconds()
            time_str = f"[{int(elapsed//60):02d}:{int(elapsed%60):02d}]"

            if role == "user":
                f.write(f"{time_str} USER: {content}\n\n")
            elif role == "model":
                f.write(f"{time_str} AGENT: {content}\n\n")
            elif role == "tool_call":
                tool_name = content.get("name", "unknown")
                f.write(f"{time_str} [TOOL CALL: {tool_name}]\n")
            elif role == "tool_response":
                f.write(f"{time_str} [TOOL RESPONSE]\n")
            elif role == "control":
                f.write(f"{time_str} [SYSTEM: {content}]\n\n")
            elif role == "session":
                event = content.get("event", content)
                f.write(f"{time_str} [SESSION: {event}]\n\n")

    def finalize(self) -> None:
        """Write session end marker to transcript."""
        with self.transcript_path.open("a", encoding="utf-8") as f:
            end_time = datetime.now(UTC)
            duration = (end_time - self.session_start_time).total_seconds()
            f.write(f"\n{'='*50}\n")
            f.write(f"Session ended: {end_time.isoformat()}\n")
            f.write(f"Total duration: {int(duration//60)}m {int(duration%60)}s\n")
            f.write(f"{'='*50}\n")


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

async def run_session(
    *,
    text_mode: bool,
    playbook_path: Path,
    storage_dir: Path,
    eval_transcript: Path | None = None,
    transport: str = "auto",
) -> ClaimState:
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        raise RuntimeError("GEMINI_API_KEY is missing. Add it to .env or your shell.")

    api_version = os.getenv("GEMINI_API_VERSION", "v1alpha")
    client = genai.Client(
        api_key=api_key,
        http_options=types.HttpOptions(api_version=api_version),
    )
    model = os.getenv("GEMINI_MODEL", "gemini-3.1-flash-live-preview")

    if text_mode:
        return await _run_text_session(
            client=client,
            model=model,
            playbook_path=playbook_path,
            storage_dir=storage_dir,
            eval_transcript=eval_transcript,
            transport=transport,
        )

    return await _run_voice_session(
        client=client,
        model=model,
        playbook_path=playbook_path,
        storage_dir=storage_dir,
    )


# ---------------------------------------------------------------------------
# Voice mode (Phase 2)
# ---------------------------------------------------------------------------

def _build_audio_config(playbook_engine: PlaybookEngine, claim_state: ClaimState) -> types.LiveConnectConfig:
    voice_name = os.getenv("GEMINI_VOICE", "Kore")
    silence_ms = int(os.getenv("VAD_SILENCE_MS", "800"))

    # Map env-var string ("LOW", "HIGH") to SDK enum; fall back to LOW.
    def _start_sensitivity():
        name = os.getenv("VAD_START_SENSITIVITY", "LOW").upper()
        return getattr(types.StartSensitivity, f"START_SENSITIVITY_{name}", types.StartSensitivity.START_SENSITIVITY_LOW)

    def _end_sensitivity():
        name = os.getenv("VAD_END_SENSITIVITY", "LOW").upper()
        return getattr(types.EndSensitivity, f"END_SENSITIVITY_{name}", types.EndSensitivity.END_SENSITIVITY_LOW)

    return types.LiveConnectConfig(
        response_modalities=["AUDIO"],
        system_instruction=build_system_prompt(playbook_engine, claim_state, voice_mode=True),
        tools=tools,
        speech_config=types.SpeechConfig(
            voice_config=types.VoiceConfig(
                prebuilt_voice_config=types.PrebuiltVoiceConfig(voice_name=voice_name)
            )
        ),
        realtime_input_config=types.RealtimeInputConfig(
            automatic_activity_detection=types.AutomaticActivityDetection(
                start_of_speech_sensitivity=_start_sensitivity(),
                end_of_speech_sensitivity=_end_sensitivity(),
                silence_duration_ms=silence_ms,
            )
        ),
    )


async def _run_voice_session(
    *,
    client: genai.Client,
    model: str,
    playbook_path: Path,
    storage_dir: Path,
) -> ClaimState:
    from app.audio.input import send_audio
    from app.audio.output import play_audio, FLUSH

    playbook_engine = PlaybookEngine.from_yaml(playbook_path)
    claim_state = ClaimState(session_id=new_session_id())
    claim_state.save(storage_dir)
    logger = TranscriptLogger(storage_dir, claim_state.session_id)
    audio_recorder = AudioRecorder(storage_dir, claim_state.session_id)

    print(f"Session ID: {claim_state.session_id}", flush=True)
    logger.log("session", {"session_id": claim_state.session_id, "mode": "voice"})

    for attempt in range(_MAX_RECONNECT_ATTEMPTS):
        config = _build_audio_config(playbook_engine, claim_state)
        handlers = ClaimToolHandlers(claim_state, playbook_engine, storage_dir)

        try:
            async with client.aio.live.connect(model=model, config=config) as session:
                audio_queue: asyncio.Queue = asyncio.Queue()
                speaking_event = (
                    asyncio.Event()
                    if _env_flag("MUTE_MIC_DURING_PLAYBACK", True)
                    else None
                )

                receive_task = asyncio.create_task(
                    _receive_voice_loop(
                        session,
                        handlers,
                        logger,
                        audio_queue,
                        FLUSH,
                        audio_recorder,
                        speaking_event=speaking_event,
                    )
                )
                play_task = asyncio.create_task(play_audio(audio_queue, speaking_event))
                send_task = asyncio.create_task(send_audio(session, speaking_event))

                if attempt == 0:
                    greeting = "Begin the claims intake now. Greet the customer and ask for the first required field."
                else:
                    greeting = (
                        f"Reconnecting after session timeout. {claim_state.summary()}. "
                        "Continue the intake from where we left off."
                    )
                await send_live_text(session, greeting)
                logger.log("control", greeting)

                done, pending = await asyncio.wait(
                    {receive_task, play_task, send_task},
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
                    if isinstance(exc, SessionFinished):
                        raise exc
                    elif exc is not None:
                        raise exc
                return claim_state

        except SessionFinished as exc:
            if exc.reason != "session_ended":
                raise
            claim_state.save(storage_dir)
            logger.log(
                "session",
                {
                    "event": "disconnect",
                    "attempt": attempt + 1,
                    "reason": exc.reason,
                },
            )
            if attempt < _MAX_RECONNECT_ATTEMPTS - 1:
                print(
                    "\nLive session ended before the claim was completed. "
                    f"Reconnecting ({attempt + 2}/{_MAX_RECONNECT_ATTEMPTS})...",
                    flush=True,
                )
                await asyncio.sleep(2)
            else:
                raise SessionFinished("reconnect_failed") from exc
        except Exception as exc:
            claim_state.save(storage_dir)
            logger.log("session", {"event": "disconnect", "attempt": attempt + 1, "reason": str(exc)})
            if _is_policy_violation(exc):
                print_exception(exc)
                raise SessionFinished("live_policy_violation") from exc
            if attempt < _MAX_RECONNECT_ATTEMPTS - 1:
                print(
                    f"\nConnection lost ({exc}). "
                    f"Reconnecting ({attempt + 2}/{_MAX_RECONNECT_ATTEMPTS})...",
                    flush=True,
                )
                await asyncio.sleep(2)
            else:
                raise SessionFinished("reconnect_failed") from exc

    # Finalize recordings
    logger.finalize()
    audio_recorder.stop()
    return claim_state


async def _receive_voice_loop(
    session: Any,
    handlers: ClaimToolHandlers,
    logger: TranscriptLogger,
    audio_queue: asyncio.Queue,
    flush_sentinel: object,
    audio_recorder: AudioRecorder,
    speaking_event: asyncio.Event | None = None,
) -> None:
    while True:
        received_response = False
        async for response in session.receive():
            received_response = True
            server_content = getattr(response, "server_content", None)
            if server_content:
                if getattr(server_content, "interrupted", False):
                    logger.log("session", {"event": "interrupted"})
                    if speaking_event:
                        speaking_event.clear()
                    await audio_queue.put(flush_sentinel)
                    continue
                model_turn = getattr(server_content, "model_turn", None)
                for part in getattr(model_turn, "parts", []) or []:
                    inline_data = getattr(part, "inline_data", None)
                    if inline_data and getattr(inline_data, "data", None):
                        # Record audio chunk
                        audio_recorder.add_chunk(inline_data.data)
                        if speaking_event:
                            speaking_event.set()
                        await audio_queue.put(inline_data.data)

            tool_call = getattr(response, "tool_call", None)
            if tool_call:
                for call in getattr(tool_call, "function_calls", []) or []:
                    name = getattr(call, "name", "")
                    args = dict(getattr(call, "args", {}) or {})
                    call_id = getattr(call, "id", None)
                    logger.log("tool_call", {"name": name, "args": args})
                    result = handlers.dispatch(name, args)
                    logger.log("tool_response", {"name": name, "result": result})
                    await _send_tool_response(session, name, result, call_id)
                    if handlers.finished_reason:
                        raise SessionFinished(handlers.finished_reason)
        if not received_response:
            await asyncio.sleep(0.05)


# ---------------------------------------------------------------------------
# Text mode (Phase 1) — unchanged
# ---------------------------------------------------------------------------

async def _run_text_session(
    *,
    client: genai.Client,
    model: str,
    playbook_path: Path,
    storage_dir: Path,
    eval_transcript: Path | None,
    transport: str,
) -> ClaimState:
    playbook_engine = PlaybookEngine.from_yaml(playbook_path)
    claim_state = ClaimState(session_id=new_session_id())
    claim_state.save(storage_dir)
    logger = TranscriptLogger(storage_dir, claim_state.session_id)
    handlers = ClaimToolHandlers(claim_state, playbook_engine, storage_dir)

    print(f"Session ID: {claim_state.session_id}", flush=True)
    logger.log("session", {"session_id": claim_state.session_id})

    config = types.LiveConnectConfig(
        response_modalities=["TEXT"],
        system_instruction=build_system_prompt(playbook_engine, claim_state),
        tools=tools,
    )

    if transport in {"auto", "live"}:
        try:
            await run_live_text_session(
                client=client,
                model=model,
                config=config,
                handlers=handlers,
                logger=logger,
                eval_transcript=eval_transcript,
            )
            logger.finalize()
            return claim_state
        except errors.APIError as exc:
            if transport == "live":
                raise
            print_exception(exc)
            print(
                "\nFalling back to Gemini generateContent text transport.\n",
                flush=True,
            )

    await run_generate_content_text_session(
        client=client,
        handlers=handlers,
        logger=logger,
        playbook_engine=playbook_engine,
        claim_state=claim_state,
        eval_transcript=eval_transcript,
    )

    logger.finalize()
    return claim_state


async def run_live_text_session(
    *,
    client: genai.Client,
    model: str,
    config: types.LiveConnectConfig,
    handlers: ClaimToolHandlers,
    logger: TranscriptLogger,
    eval_transcript: Path | None,
) -> None:
    async with client.aio.live.connect(model=model, config=config) as live_session:
        await send_user_turn(
            live_session,
            "Begin the claims intake now. Greet the customer and ask for the first required field.",
        )
        logger.log(
            "control",
            "Requested initial greeting and first claims intake question.",
        )
        receive_task = asyncio.create_task(receive_loop(live_session, handlers, logger))
        send_task = asyncio.create_task(
            send_text_loop(live_session, logger, eval_transcript)
        )
        done, pending = await asyncio.wait(
            {receive_task, send_task},
            return_when=asyncio.FIRST_EXCEPTION,
        )
        for task in pending:
            task.cancel()
        for task in done:
            exc = task.exception()
            if isinstance(exc, SessionFinished):
                pass
            elif exc is not None:
                raise exc


async def run_generate_content_text_session(
    *,
    client: genai.Client,
    handlers: ClaimToolHandlers,
    logger: TranscriptLogger,
    playbook_engine: PlaybookEngine,
    claim_state: ClaimState,
    eval_transcript: Path | None,
) -> None:
    model = os.getenv("GEMINI_TEXT_MODEL", "gemini-2.5-flash")
    history: list[types.Content] = []
    config = types.GenerateContentConfig(
        system_instruction=build_system_prompt(playbook_engine, claim_state),
        tools=tools,
    )

    await generate_content_turn(
        client,
        model,
        config,
        history,
        handlers,
        logger,
        "Begin the claims intake now. Greet the customer and ask for the first required field.",
        "control",
    )

    if eval_transcript:
        lines = [
            line.strip()
            for line in eval_transcript.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
        for user_input in lines:
            print(f"\nYou: {user_input}", flush=True)
            await generate_content_turn(
                client, model, config, history, handlers, logger, user_input, "user"
            )
            if handlers.finished_reason:
                raise SessionFinished(handlers.finished_reason)
        return

    while True:
        user_input = await asyncio.to_thread(input, "\nYou: ")
        if user_input.strip().lower() in {"exit", "quit"}:
            raise SessionFinished("user_exit")
        await generate_content_turn(
            client, model, config, history, handlers, logger, user_input, "user"
        )
        if handlers.finished_reason:
            raise SessionFinished(handlers.finished_reason)


async def generate_content_turn(
    client: genai.Client,
    model: str,
    config: types.GenerateContentConfig,
    history: list[types.Content],
    handlers: ClaimToolHandlers,
    logger: TranscriptLogger,
    text: str,
    role: str,
) -> None:
    user_content = types.Content(role="user", parts=[types.Part(text=text)])
    history.append(user_content)
    logger.log(role, text)

    while True:
        response = await client.aio.models.generate_content(
            model=model,
            contents=history,
            config=config,
        )
        model_content = response.candidates[0].content
        history.append(model_content)

        text_parts = [
            part.text for part in model_content.parts or [] if getattr(part, "text", None)
        ]
        if text_parts:
            model_text = "".join(text_parts)
            logger.log("model", model_text)
            for char in model_text:
                print(char, end="", flush=True)
            print(flush=True)

        function_calls = response.function_calls or []
        if not function_calls:
            return

        response_parts: list[types.Part] = []
        for function_call in function_calls:
            args = dict(function_call.args or {})
            logger.log("tool_call", {"name": function_call.name, "args": args})
            result = handlers.dispatch(function_call.name, args)
            logger.log(
                "tool_response",
                {"name": function_call.name, "result": result},
            )
            response_parts.append(
                types.Part.from_function_response(
                    name=function_call.name,
                    response=result,
                )
            )
        history.append(types.Content(role="tool", parts=response_parts))
        if handlers.finished_reason:
            raise SessionFinished(handlers.finished_reason)


async def send_text_loop(
    live_session: Any,
    logger: TranscriptLogger,
    eval_transcript: Path | None = None,
) -> None:
    if eval_transcript:
        lines = [
            line.strip()
            for line in eval_transcript.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
        for user_input in lines:
            print(f"\nYou: {user_input}", flush=True)
            await send_user_turn(live_session, user_input)
            logger.log("user", user_input)
        return

    while True:
        user_input = await asyncio.to_thread(input, "\nYou: ")
        if user_input.strip().lower() in {"exit", "quit"}:
            raise SessionFinished("user_exit")
        await send_user_turn(live_session, user_input)
        logger.log("user", user_input)


async def send_user_turn(live_session: Any, user_input: str) -> None:
    await send_live_text(live_session, user_input)


async def send_live_text(live_session: Any, text: str) -> None:
    await live_session.send_realtime_input(text=text)


async def receive_loop(
    live_session: Any,
    handlers: ClaimToolHandlers,
    logger: TranscriptLogger,
) -> None:
    model_buffer: list[str] = []
    while True:
        received_response = False
        async for response in live_session.receive():
            received_response = True
            text = extract_text(response)
            if text:
                model_buffer.append(text)
                print(text, end="", flush=True)

            for call in extract_function_calls(response):
                if model_buffer:
                    logger.log("model", "".join(model_buffer))
                    model_buffer.clear()
                logger.log("tool_call", {"name": call["name"], "args": call["args"]})
                result = handlers.dispatch(call["name"], call["args"])
                logger.log("tool_response", {"name": call["name"], "result": result})
                await _send_tool_response(live_session, call["name"], result, call.get("id"))
                if handlers.finished_reason:
                    raise SessionFinished(handlers.finished_reason)
        if not received_response:
            await asyncio.sleep(0.05)


def extract_text(response: Any) -> str:
    text = getattr(response, "text", None)
    if text:
        return text

    server_content = getattr(response, "server_content", None)
    model_turn = getattr(server_content, "model_turn", None)
    parts = getattr(model_turn, "parts", []) if model_turn else []
    chunks: list[str] = []
    for part in parts:
        part_text = getattr(part, "text", None)
        if part_text:
            chunks.append(part_text)
    return "".join(chunks)


def extract_function_calls(response: Any) -> list[dict[str, Any]]:
    calls: list[dict[str, Any]] = []
    tool_call = getattr(response, "tool_call", None)
    function_calls = getattr(tool_call, "function_calls", []) if tool_call else []
    for function_call in function_calls:
        calls.append(
            {
                "id": getattr(function_call, "id", None),
                "name": getattr(function_call, "name", ""),
                "args": dict(getattr(function_call, "args", {}) or {}),
            }
        )
    return calls


async def _send_tool_response(
    live_session: Any,
    name: str,
    result: dict[str, Any],
    call_id: str | None,
) -> None:
    response = types.FunctionResponse(
        name=name,
        response=result,
        id=call_id,
    )
    await live_session.send_tool_response(function_responses=[response])


def print_exception(exc: Exception) -> None:
    print(f"\nError: {exc}", file=sys.stderr, flush=True)
    if exc.__class__.__name__ == "APIError" and "1011" in str(exc):
        print(
            "Hint: Gemini Live closed during setup. Check that GEMINI_MODEL is a "
            "Live-capable text model, for example gemini-3.1-flash-live-preview.",
            file=sys.stderr,
            flush=True,
        )
    if exc.__class__.__name__ == "APIError" and "1008" in str(exc):
        print(
            "Hint: Gemini Live rejected the setup. Check GEMINI_API_VERSION and "
            "GEMINI_MODEL; the default text-mode pair is v1alpha with "
            "gemini-3.1-flash-live-preview.",
            file=sys.stderr,
            flush=True,
        )
    if _is_policy_violation(exc):
        print(
            "Hint: Gemini Live closed the websocket with policy violation 1008. "
            "For Gemini 3.1 Live, text turns must be sent with send_realtime_input; "
            "send_client_content is only for initial history seeding when configured. "
            "If this still fails, verify Live API access for your API key and model.",
            file=sys.stderr,
            flush=True,
        )


def _is_policy_violation(exc: Exception) -> bool:
    message = str(exc)
    return "1008" in message or "policy violation" in message.lower()
