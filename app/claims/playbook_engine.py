from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from app.claims.claim_state import ClaimState, is_filled


@dataclass(frozen=True)
class PlaybookState:
    name: str
    required: dict[str, str | None]
    next: str | None


class PlaybookEngine:
    def __init__(self, states: dict[str, PlaybookState]) -> None:
        self.states = states
        self.ordered_state_names = [
            name for name in states if name not in {"escalate", "done"}
        ]

    @classmethod
    def from_yaml(cls, path: Path) -> "PlaybookEngine":
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
        states: dict[str, PlaybookState] = {}
        for name, config in raw["states"].items():
            reqs: dict[str, str | None] = {}
            for item in config.get("required", []):
                if isinstance(item, dict):
                    for k, v in item.items():
                        reqs[k] = v
                else:
                    reqs[item] = None

            states[name] = PlaybookState(
                name=name,
                required=reqs,
                next=config.get("next"),
            )
        return cls(states)

    def current_stage(self, claim_state: ClaimState) -> str:
        if claim_state.handoff_required or claim_state.safety.urgent_risk is True:
            return "escalate"

        stage_name = self.ordered_state_names[0]
        seen: set[str] = set()
        while stage_name not in seen:
            seen.add(stage_name)
            state = self.states[stage_name]
            if self._missing_for_state(claim_state, state):
                return stage_name
            if not state.next or state.next == "done":
                return "done"
            stage_name = state.next
        raise ValueError("Playbook contains a cycle")

    def get_missing_fields(self, claim_state: ClaimState) -> dict[str, str | None]:
        stage = self.current_stage(claim_state)
        if stage in {"done", "escalate"}:
            return {}
        return self._missing_for_state(claim_state, self.states[stage])

    def all_required_fields(self) -> list[str]:
        fields: list[str] = []
        for state_name in self.ordered_state_names:
            fields.extend(self.states[state_name].required.keys())
        return fields

    def _missing_for_state(
        self, claim_state: ClaimState, state: PlaybookState
    ) -> dict[str, str | None]:
        missing: dict[str, str | None] = {}
        for field_path, hint in state.required.items():
            value: Any = claim_state.get_path(field_path)
            if not is_filled(value):
                missing[field_path] = hint
        return missing
