from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


def utc_now_iso() -> str:
    return datetime.now(UTC).isoformat()


class Customer(BaseModel):
    full_name: str | None = None
    policy_number: str | None = None
    date_of_birth: str | None = None
    preferred_contact_method: str | None = None


class Incident(BaseModel):
    date: str | None = None
    time: str | None = None
    location: str | None = None
    description: str | None = None


class Damage(BaseModel):
    items: list[str] = Field(default_factory=list)
    description: str | None = None
    estimated_value: str | int | float | None = None
    photos_available: bool | None = None


class ThirdParties(BaseModel):
    involved: bool | None = None
    details: str | None = None


class Safety(BaseModel):
    injuries: bool | str | None = None
    police_report: bool | None = None
    urgent_risk: bool | None = None


class Documents(BaseModel):
    photos: bool | None = None
    receipts: bool | None = None
    police_report: bool | None = None


class ClaimState(BaseModel):
    model_config = ConfigDict(validate_assignment=True)

    session_id: str
    claim_type: str | None = None
    customer: Customer = Field(default_factory=Customer)
    incident: Incident = Field(default_factory=Incident)
    damage: Damage = Field(default_factory=Damage)
    third_parties: ThirdParties = Field(default_factory=ThirdParties)
    safety: Safety = Field(default_factory=Safety)
    documents: Documents = Field(default_factory=Documents)
    handoff_required: bool = False
    risk_flags: list[str] = Field(default_factory=list)
    created_at: str = Field(default_factory=utc_now_iso)
    completed_at: str | None = None

    def merge_update(self, update: dict[str, Any]) -> list[str]:
        invalid_fields: list[str] = []
        for key, value in update.items():
            if value is None:
                continue
            if isinstance(value, dict) and "." not in key:
                for nested_key, nested_value in flatten_dict(value, key).items():
                    try:
                        self.set_path(nested_key, nested_value)
                    except ValueError:
                        invalid_fields.append(nested_key)
            else:
                try:
                    self.set_path(key, value)
                except ValueError:
                    invalid_fields.append(key)
        return invalid_fields

    def set_path(self, path: str, value: Any) -> None:
        target: Any = self
        parts = path.split(".")
        for part in parts[:-1]:
            if not hasattr(target, part):
                raise ValueError(f"Unknown claim field: {path}")
            target = getattr(target, part)

        leaf = parts[-1]
        if not hasattr(target, leaf):
            raise ValueError(f"Unknown claim field: {path}")
        if path == "damage.items" and isinstance(value, str):
            value = [item.strip() for item in value.split(",") if item.strip()]
        setattr(target, leaf, value)

    def get_path(self, path: str) -> Any:
        target: Any = self
        for part in path.split("."):
            if not hasattr(target, part):
                raise ValueError(f"Unknown claim field: {path}")
            target = getattr(target, part)
        return target

    def mark_completed(self) -> None:
        self.completed_at = utc_now_iso()

    def save(self, storage_dir: Path) -> Path:
        storage_dir.mkdir(parents=True, exist_ok=True)
        path = storage_dir / f"{self.session_id}_claim.json"
        path.write_text(
            json.dumps(self.model_dump(mode="json"), indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        return path

    _METADATA_FIELDS = {"session_id", "created_at", "completed_at", "handoff_required", "risk_flags"}

    def summary(self) -> str:
        filled = {
            k: v for k, v in self.filled_fields().items()
            if k.split(".")[0] not in self._METADATA_FIELDS
        }
        if not filled:
            return "No fields collected yet"
        parts = [f"{k}={v!r}" for k, v in sorted(filled.items())]
        return "Collected so far: " + ", ".join(parts)

    def filled_fields(self) -> dict[str, Any]:
        flat = flatten_dict(self.model_dump(mode="json"))
        return {key: value for key, value in flat.items() if is_filled(value)}


def flatten_dict(data: dict[str, Any], prefix: str = "") -> dict[str, Any]:
    items: dict[str, Any] = {}
    for key, value in data.items():
        path = f"{prefix}.{key}" if prefix else key
        if isinstance(value, dict):
            items.update(flatten_dict(value, path))
        else:
            items[path] = value
    return items


def is_filled(value: Any) -> bool:
    if value is None:
        return False
    if isinstance(value, str):
        return bool(value.strip())
    if isinstance(value, list):
        return len(value) > 0
    return True
