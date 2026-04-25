from __future__ import annotations

import asyncio

import numpy as np
import sounddevice as sd

_SAMPLE_RATE = 24000

# Sentinel pushed to the queue by the receive loop on barge-in.
FLUSH = object()


async def play_audio(queue: asyncio.Queue) -> None:
    """Read PCM chunks from *queue* and play them. FLUSH drains pending audio."""
    stream = sd.RawOutputStream(samplerate=_SAMPLE_RATE, channels=1, dtype="int16")
    stream.start()
    try:
        while True:
            chunk = await queue.get()
            if chunk is FLUSH:
                # Drain any audio chunks that arrived before the interrupt signal.
                while not queue.empty():
                    try:
                        queue.get_nowait()
                    except asyncio.QueueEmpty:
                        break
                stream.stop()
                stream.start()
                continue
            await asyncio.to_thread(stream.write, np.frombuffer(chunk, dtype="int16"))
    finally:
        stream.stop()
        stream.close()
