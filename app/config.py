from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


def _env_flag(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class AmbientOfficeConfig:
    enabled: bool
    gain: float
    file_path: Path


def ambient_office_config() -> AmbientOfficeConfig:
    enabled = _env_flag("AMBIENT_OFFICE_ENABLED", True)

    raw_gain = os.getenv("AMBIENT_OFFICE_GAIN", "0.10").strip()
    try:
        gain = float(raw_gain)
    except ValueError:
        gain = 0.10
    gain = min(max(gain, 0.0), 1.0)

    default_file = Path(__file__).resolve().parent / "audio" / "assets" / "office_ambience_24k_mono.wav"
    configured_file = os.getenv("AMBIENT_OFFICE_FILE")
    file_path = Path(configured_file).expanduser() if configured_file else default_file

    return AmbientOfficeConfig(enabled=enabled, gain=gain, file_path=file_path)
