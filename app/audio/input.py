from __future__ import annotations

import asyncio
from collections.abc import Callable
from typing import Any

import sounddevice as sd
from google.genai import types

_SAMPLE_RATE = 16000
_CHUNK_FRAMES = 1024


async def send_audio(
    session: Any,
    suppress_when: asyncio.Event | None = None,
    on_chunk: Callable[[bytes], None] | None = None,
) -> None:
    loop = asyncio.get_event_loop()
    queue: asyncio.Queue[bytes] = asyncio.Queue()

    def _callback(indata, frames, time, status):
        loop.call_soon_threadsafe(queue.put_nowait, bytes(indata))

    with sd.RawInputStream(
        samplerate=_SAMPLE_RATE,
        channels=1,
        dtype="int16",
        blocksize=_CHUNK_FRAMES,
        callback=_callback,
    ):
        while True:
            chunk = await queue.get()
            if on_chunk:
                on_chunk(chunk)
            if suppress_when and suppress_when.is_set():
                continue
            await session.send_realtime_input(
                audio=types.Blob(data=chunk, mime_type="audio/pcm;rate=16000")
            )
