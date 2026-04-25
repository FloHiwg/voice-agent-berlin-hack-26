import json
from contextlib import contextmanager
from pathlib import Path

from fastapi.testclient import TestClient

from app.phone.server import app


def _write_session_files(storage_dir: Path, session_id: str) -> None:
    claim_payload = {
        "session_id": session_id,
        "claim_type": "auto accident",
        "customer": {
            "full_name": "Alex Rider",
            "policy_number": "POL-123",
            "date_of_birth": "1990-01-02",
            "preferred_contact_method": None,
            "identity_verified": True,
            "is_policyholder": True,
            "caller_name": None,
            "relationship_to_policyholder": None,
        },
        "incident": {
            "date": "2026-04-25",
            "time": None,
            "location": "Main Street",
            "description": None,
        },
        "damage": {
            "items": [],
            "description": None,
            "estimated_value": None,
            "photos_available": None,
        },
        "third_parties": {"involved": None, "details": None, "witness_info": None},
        "safety": {
            "injuries": None,
            "police_report": None,
            "police_report_details": None,
            "urgent_risk": False,
        },
        "documents": {"photos": None, "receipts": None, "police_report": None},
        "services": {
            "rental_car_needed": None,
            "rental_car_preference": None,
            "repair_shop_selected": None,
            "repair_shop_preference": None,
        },
        "handoff_required": False,
        "risk_flags": [],
        "created_at": "2026-04-25T17:00:00+00:00",
        "completed_at": None,
    }
    (storage_dir / f"{session_id}_claim.json").write_text(
        json.dumps(claim_payload), encoding="utf-8"
    )
    (storage_dir / f"{session_id}.jsonl").write_text(
        json.dumps({"role": "user", "content": "hello"}) + "\n", encoding="utf-8"
    )
    (storage_dir / f"{session_id}_transcript.txt").write_text(
        "sample transcript", encoding="utf-8"
    )
    (storage_dir / f"{session_id}_audio.wav").write_bytes(b"RIFF0000WAVE")


@contextmanager
def _build_client(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("GEMINI_API_KEY", "test")
    monkeypatch.setenv("TWILIO_ACCOUNT_SID", "test")
    monkeypatch.setenv("TWILIO_API_KEY_SID", "test")
    monkeypatch.setenv("TWILIO_API_KEY_SECRET", "test")
    monkeypatch.setenv("TWILIO_NUMBER", "+100000000")
    monkeypatch.setenv("TWILIO_PUBLIC_URL", "https://example.com")
    with TestClient(app) as client:
        client.app.state.storage_dir = tmp_path
        client.app.state.playbook_path = Path("app/claims/playbook.yaml")
        yield client


def test_list_and_get_session(monkeypatch, tmp_path: Path) -> None:
    session_id = "claim_20260425_170000_abcd"
    _write_session_files(tmp_path, session_id)

    with _build_client(monkeypatch, tmp_path) as client:
        list_response = client.get("/api/sessions")
        assert list_response.status_code == 200
        payload = list_response.json()
        assert payload["sessions"][0]["session_id"] == session_id
        assert payload["sessions"][0]["current_stage"] == "collect_incident"
        assert payload["sessions"][0]["artifacts"]["audio"] is True

        detail_response = client.get(f"/api/sessions/{session_id}")
        assert detail_response.status_code == 200
        detail = detail_response.json()
        assert detail["state"]["claim_type"] == "auto accident"
        assert detail["stages"]


def test_session_artifact_endpoints(monkeypatch, tmp_path: Path) -> None:
    session_id = "claim_20260425_170000_efgh"
    _write_session_files(tmp_path, session_id)
    with _build_client(monkeypatch, tmp_path) as client:
        events_response = client.get(f"/api/sessions/{session_id}/events")
        assert events_response.status_code == 200
        assert events_response.json()["events"][0]["role"] == "user"

        transcript_response = client.get(f"/api/sessions/{session_id}/transcript")
        assert transcript_response.status_code == 200
        assert transcript_response.json()["transcript"] == "sample transcript"

        audio_response = client.get(f"/api/sessions/{session_id}/audio")
        assert audio_response.status_code == 200
        assert audio_response.headers["content-type"] == "audio/wav"


def test_missing_session_returns_not_found(monkeypatch, tmp_path: Path) -> None:
    with _build_client(monkeypatch, tmp_path) as client:
        response = client.get("/api/sessions/claim_missing")
        assert response.status_code == 404
