"""Gradium AI Speech-to-Text service module.

Provides WebSocket streaming integration with Gradium API for post-call transcription.
"""
from __future__ import annotations

import asyncio
import base64
import json
import os
import wave
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import websockets


async def transcribe_audio_file(
    audio_path: Path,
    session_id: str,
    api_key: str,
) -> dict[str, Any]:
    """
    Transcribe an audio file using Gradium's WebSocket streaming API.

    Args:
        audio_path: Path to WAV file (16-bit PCM, 8/16/24kHz)
        session_id: Session identifier for logging
        api_key: Gradium API key

    Returns:
        Structured transcript with segments, timestamps, and metadata

    Raises:
        Exception: On connection, API, or processing errors
    """
    uri = "wss://api.gradium.ai/api/speech/asr"
    headers = {"x-api-key": api_key}

    print(f"[gradium] {session_id}: Starting transcription", flush=True)

    segments: list[dict[str, Any]] = []
    start_time = datetime.now(UTC)

    try:
        async with websockets.connect(uri, extra_headers=headers) as websocket:
            # Step 1: Send setup message
            setup_msg = {
                "type": "setup",
                "model_name": "default",
                "input_format": "wav",
            }
            await websocket.send(json.dumps(setup_msg))
            print(f"[gradium] {session_id}: Sent setup message", flush=True)

            # Step 2: Wait for ready confirmation
            response = await websocket.recv()
            response_data = json.loads(response)
            if response_data.get("type") != "ready":
                raise RuntimeError(f"Expected 'ready' message, got: {response_data}")
            print(f"[gradium] {session_id}: Received ready signal", flush=True)

            # Step 3: Stream audio file
            with wave.open(str(audio_path), "rb") as wav_file:
                sample_rate = wav_file.getframerate()
                n_channels = wav_file.getnchannels()
                n_frames = wav_file.getnframes()
                duration_s = n_frames / sample_rate

                print(
                    f"[gradium] {session_id}: Audio file - {sample_rate}Hz, "
                    f"{n_channels}ch, {duration_s:.1f}s",
                    flush=True,
                )

                # Skip WAV header (44 bytes)
                wav_file.readframes(0)

                # Stream audio in chunks (80ms at 16kHz = 1280 samples = 2560 bytes for 16-bit mono)
                # For stereo 16kHz 16-bit: 80ms = 2560 samples = 5120 bytes
                chunk_size = int(0.08 * sample_rate * n_channels * 2)  # 2 bytes per sample
                chunks_sent = 0

                # Create receive task to collect responses while sending
                async def receive_responses():
                    nonlocal segments
                    while True:
                        try:
                            msg = await websocket.recv()
                            data = json.loads(msg)

                            if data.get("type") == "text":
                                segment = {
                                    "text": data.get("text", ""),
                                    "start_s": data.get("start_s"),
                                    "end_s": None,  # Gradium doesn't provide end_s
                                }
                                segments.append(segment)
                                print(
                                    f"[gradium] {session_id}: "
                                    f"[{segment['start_s']:.1f}s] {segment['text'][:50]}...",
                                    flush=True,
                                )
                            elif data.get("type") == "end_of_stream":
                                print(f"[gradium] {session_id}: Received end_of_stream", flush=True)
                                break
                        except websockets.exceptions.ConnectionClosed:
                            break

                receive_task = asyncio.create_task(receive_responses())

                # Send audio chunks
                while True:
                    audio_data = wav_file.readframes(chunk_size // (n_channels * 2))
                    if not audio_data:
                        break

                    audio_b64 = base64.b64encode(audio_data).decode("utf-8")
                    audio_msg = {
                        "type": "audio",
                        "audio": audio_b64,
                    }
                    await websocket.send(json.dumps(audio_msg))
                    chunks_sent += 1

                    # Small delay to avoid overwhelming the API
                    await asyncio.sleep(0.01)

                print(f"[gradium] {session_id}: Sent {chunks_sent} audio chunks", flush=True)

            # Step 4: Send end of stream
            end_msg = {"type": "end_of_stream"}
            await websocket.send(json.dumps(end_msg))
            print(f"[gradium] {session_id}: Sent end_of_stream", flush=True)

            # Wait for receive task to complete
            await receive_task

    except websockets.exceptions.InvalidStatusCode as e:
        if e.status_code == 401:
            raise RuntimeError("Gradium API authentication failed (401)") from e
        elif e.status_code == 403:
            raise RuntimeError("Gradium API access forbidden (403)") from e
        elif e.status_code == 429:
            raise RuntimeError("Gradium API rate limit exceeded (429)") from e
        else:
            raise RuntimeError(f"Gradium API error ({e.status_code})") from e
    except Exception as e:
        raise RuntimeError(f"Gradium transcription failed: {e}") from e

    end_time = datetime.now(UTC)
    processing_duration = (end_time - start_time).total_seconds()

    # Get audio duration
    with wave.open(str(audio_path), "rb") as wav_file:
        duration_s = wav_file.getnframes() / wav_file.getframerate()

    transcript_data = {
        "session_id": session_id,
        "segments": segments,
        "duration_s": duration_s,
        "created_at": end_time.isoformat(),
        "source": "gradium",
        "processing_time_s": processing_duration,
    }

    print(
        f"[gradium] {session_id}: Transcription complete - "
        f"{len(segments)} segments in {processing_duration:.1f}s",
        flush=True,
    )

    return transcript_data


async def transcribe_session_async(
    session_id: str,
    audio_path: Path,
    storage_dir: Path,
) -> None:
    """
    Background task to transcribe a session's audio using Gradium API.

    This function is fire-and-forget - errors are logged but don't affect
    the session completion. The Gradium transcript enhances the Gemini
    transcript but is not critical path.

    Args:
        session_id: Session identifier
        audio_path: Path to merged audio WAV file
        storage_dir: Directory to save transcript JSON
    """
    api_key = os.getenv("GRADIUM_API_KEY")
    if not api_key:
        print(f"[gradium] {session_id}: GRADIUM_API_KEY not set, skipping", flush=True)
        return

    if not audio_path.exists():
        print(f"[gradium] {session_id}: Audio file not found: {audio_path}", flush=True)
        return

    max_retries = 3
    retry_delays = [1, 2, 4]  # Exponential backoff in seconds

    for attempt in range(max_retries):
        try:
            # Add timeout to prevent hanging indefinitely
            transcript_data = await asyncio.wait_for(
                transcribe_audio_file(audio_path, session_id, api_key),
                timeout=600,  # 10 minutes max
            )

            # Save JSON transcript
            json_path = storage_dir / f"gradium_{session_id}.json"
            json_path.write_text(
                json.dumps(transcript_data, indent=2, ensure_ascii=False),
                encoding="utf-8",
            )
            print(f"[gradium] {session_id}: Saved transcript to {json_path}", flush=True)

            # Optionally save human-readable text version
            txt_path = storage_dir / f"gradium_{session_id}.txt"
            with txt_path.open("w", encoding="utf-8") as f:
                f.write(f"=== Gradium Transcript ===\n")
                f.write(f"Session ID: {session_id}\n")
                f.write(f"Created: {transcript_data['created_at']}\n")
                f.write(f"Duration: {transcript_data['duration_s']:.1f}s\n")
                f.write(f"Segments: {len(transcript_data['segments'])}\n")
                f.write(f"{'='*50}\n\n")

                for seg in transcript_data["segments"]:
                    timestamp = f"[{int(seg['start_s']//60):02d}:{int(seg['start_s']%60):02d}]"
                    f.write(f"{timestamp} {seg['text']}\n")

            print(f"[gradium] {session_id}: Saved text version to {txt_path}", flush=True)
            return  # Success - exit retry loop

        except asyncio.TimeoutError:
            print(
                f"[gradium] {session_id}: Transcription timed out (attempt {attempt + 1}/{max_retries})",
                flush=True,
            )
        except RuntimeError as e:
            error_msg = str(e)
            # Don't retry on auth/permission errors
            if any(code in error_msg for code in ["401", "403"]):
                print(f"[gradium] {session_id}: API auth error: {e}", flush=True)
                return
            # Don't retry on rate limit immediately
            if "429" in error_msg:
                print(f"[gradium] {session_id}: Rate limit exceeded: {e}", flush=True)
                if attempt < max_retries - 1:
                    await asyncio.sleep(retry_delays[attempt] * 2)  # Longer delay for rate limit
                    continue
                return
            print(
                f"[gradium] {session_id}: Error (attempt {attempt + 1}/{max_retries}): {e}",
                flush=True,
            )
        except Exception as e:
            print(
                f"[gradium] {session_id}: Unexpected error (attempt {attempt + 1}/{max_retries}): {e}",
                flush=True,
            )

        # Retry with exponential backoff
        if attempt < max_retries - 1:
            delay = retry_delays[attempt]
            print(f"[gradium] {session_id}: Retrying in {delay}s...", flush=True)
            await asyncio.sleep(delay)

    # All retries exhausted
    print(
        f"[gradium] {session_id}: Failed after {max_retries} attempts, giving up",
        flush=True,
    )
