from __future__ import annotations

import asyncio
from typing import Any

import sounddevice as sd
from google.genai import types

_SAMPLE_RATE = 16000
_CHUNK_FRAMES = 1024


async def send_audio(session: Any) -> None:
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
            await session.send_realtime_input(
                audio=types.Blob(data=chunk, mime_type="audio/pcm;rate=16000")
            )
