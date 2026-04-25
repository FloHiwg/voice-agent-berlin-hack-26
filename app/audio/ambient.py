from __future__ import annotations

import wave
from pathlib import Path

import numpy as np


class AmbientLoopMixer:
    """Mixes a looping mono int16 ambience bed into speech audio."""

    def __init__(self, sample_rate: int, gain: float, audio_loop: np.ndarray) -> None:
        self.sample_rate = sample_rate
        self.gain = float(min(max(gain, 0.0), 1.0))
        self.audio_loop = np.ascontiguousarray(audio_loop.astype(np.int16))
        self._cursor = 0

    @classmethod
    def from_wav(cls, *, sample_rate: int, gain: float, wav_path: Path) -> "AmbientLoopMixer":
        with wave.open(str(wav_path), "rb") as wav_file:
            channels = wav_file.getnchannels()
            sampwidth = wav_file.getsampwidth()
            source_rate = wav_file.getframerate()
            frames = wav_file.readframes(wav_file.getnframes())

        if channels < 1:
            raise ValueError(f"ambient wav must have at least one channel, got {channels}")
        if sampwidth != 2:
            raise ValueError(f"ambient wav must be 16-bit PCM, got {sampwidth * 8}-bit")

        loop = np.frombuffer(frames, dtype=np.int16)
        if channels > 1:
            # Accept stereo/multichannel files by downmixing to mono.
            samples = loop.size // channels
            loop = loop[: samples * channels].reshape(samples, channels).mean(axis=1).astype(np.int16)
        if loop.size == 0:
            raise ValueError("ambient wav has no samples")

        if source_rate != sample_rate:
            target_len = int(loop.size * sample_rate / source_rate)
            idx = np.linspace(0, loop.size - 1, target_len)
            loop = np.interp(idx, np.arange(loop.size), loop).astype(np.int16)

        return cls(sample_rate=sample_rate, gain=gain, audio_loop=loop)

    def mix(self, speech: np.ndarray) -> np.ndarray:
        """Return int16 speech mixed with ambience at configured gain."""
        if speech.size == 0 or self.gain <= 0.0:
            return speech

        n = speech.size
        indices = (self._cursor + np.arange(n, dtype=np.int64)) % self.audio_loop.size
        ambient = self.audio_loop[indices]
        self._cursor = int((self._cursor + n) % self.audio_loop.size)

        mixed = speech.astype(np.int32) + (ambient.astype(np.float32) * self.gain).astype(np.int32)
        return np.clip(mixed, -32768, 32767).astype(np.int16)
