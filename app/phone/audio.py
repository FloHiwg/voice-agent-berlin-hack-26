"""G.711 μ-law codec and PCM resampling utilities (numpy, no audioop)."""
from __future__ import annotations

import numpy as np

_BIAS = 132
_CLIP = 32635
_SIGN_BIT = 0x80
_QUANT_MASK = 0x0F
_SEG_MASK = 0x70
_SEG_SHIFT = 4

# 256-entry exponent lookup for encode: indexed by (sample >> 8) after bias.
_EXP_LUT = np.array(
    [0, 0, 1, 1, 2, 2, 2, 2, 3, 3, 3, 3, 3, 3, 3, 3,
     4, 4, 4, 4, 4, 4, 4, 4, 4, 4, 4, 4, 4, 4, 4, 4,
     5, 5, 5, 5, 5, 5, 5, 5, 5, 5, 5, 5, 5, 5, 5, 5,
     5, 5, 5, 5, 5, 5, 5, 5, 5, 5, 5, 5, 5, 5, 5, 5,
     6, 6, 6, 6, 6, 6, 6, 6, 6, 6, 6, 6, 6, 6, 6, 6,
     6, 6, 6, 6, 6, 6, 6, 6, 6, 6, 6, 6, 6, 6, 6, 6,
     6, 6, 6, 6, 6, 6, 6, 6, 6, 6, 6, 6, 6, 6, 6, 6,
     6, 6, 6, 6, 6, 6, 6, 6, 6, 6, 6, 6, 6, 6, 6, 6,
     7, 7, 7, 7, 7, 7, 7, 7, 7, 7, 7, 7, 7, 7, 7, 7,
     7, 7, 7, 7, 7, 7, 7, 7, 7, 7, 7, 7, 7, 7, 7, 7,
     7, 7, 7, 7, 7, 7, 7, 7, 7, 7, 7, 7, 7, 7, 7, 7,
     7, 7, 7, 7, 7, 7, 7, 7, 7, 7, 7, 7, 7, 7, 7, 7,
     7, 7, 7, 7, 7, 7, 7, 7, 7, 7, 7, 7, 7, 7, 7, 7,
     7, 7, 7, 7, 7, 7, 7, 7, 7, 7, 7, 7, 7, 7, 7, 7,
     7, 7, 7, 7, 7, 7, 7, 7, 7, 7, 7, 7, 7, 7, 7, 7,
     7, 7, 7, 7, 7, 7, 7, 7, 7, 7, 7, 7, 7, 7, 7, 7],
    dtype=np.int32,
)


def ulaw_decode(data: bytes) -> np.ndarray:
    """G.711 μ-law bytes → 16-bit PCM (int16 array)."""
    u = (~np.frombuffer(data, dtype=np.uint8)).astype(np.int32) & 0xFF
    sign = u & _SIGN_BIT
    t = ((u & _QUANT_MASK) << 3) + _BIAS
    t = t << ((u & _SEG_MASK) >> _SEG_SHIFT)
    return np.where(sign != 0, _BIAS - t, t - _BIAS).astype(np.int16)


def ulaw_encode(samples: np.ndarray) -> bytes:
    """16-bit PCM (int16 array) → G.711 μ-law bytes."""
    s = samples.astype(np.int32)
    sign = ((s >> 8) & _SIGN_BIT).astype(np.int32)
    s = np.where(sign != 0, -s, s)
    s = np.minimum(s, _CLIP) + _BIAS
    exp = _EXP_LUT[(s >> 8) & 0xFF]
    mantissa = (s >> (exp + 3)) & _QUANT_MASK
    return ((~(sign | (exp << 4) | mantissa)) & 0xFF).astype(np.uint8).tobytes()


def resample_8k_to_16k(pcm: np.ndarray) -> np.ndarray:
    """Upsample 8kHz int16 PCM to 16kHz via linear interpolation."""
    n = len(pcm)
    out = np.empty(n * 2, dtype=np.int16)
    out[0::2] = pcm
    if n > 1:
        mid = ((pcm[:-1].astype(np.int32) + pcm[1:].astype(np.int32)) >> 1).astype(np.int16)
        out[1:-1:2] = mid
    out[-1] = pcm[-1]
    return out


def resample_24k_to_8k(pcm: np.ndarray) -> np.ndarray:
    """Downsample 24kHz int16 PCM to 8kHz by decimation (every 3rd sample)."""
    return np.ascontiguousarray(pcm[::3])
