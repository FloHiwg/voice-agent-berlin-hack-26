from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.agent.session import print_exception, run_session
from app.agent.tools import SessionFinished


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Claims intake agent")
    parser.add_argument(
        "--text-mode",
        action="store_true",
        help="Use stdin/stdout instead of mic/speaker (Phase 1 fallback).",
    )
    parser.add_argument(
        "--eval-transcript",
        type=Path,
        default=None,
        help="Replay a conversation file (.txt one turn per line, or .yaml with transcript + expect).",
    )
    parser.add_argument(
        "--eval-assert",
        action="store_true",
        help="After an eval run, assert claim state against expected fields in the YAML file.",
    )
    parser.add_argument(
        "--playbook",
        type=Path,
        default=ROOT / "app" / "claims" / "playbook.yaml",
        help="Path to claims playbook YAML.",
    )
    parser.add_argument(
        "--storage-dir",
        type=Path,
        default=ROOT / "storage" / "sessions",
        help="Directory for session logs and claim JSON.",
    )
    parser.add_argument(
        "--transport",
        choices=["auto", "live", "generate-content"],
        default="auto",
        help="Text transport. auto tries Live first, then falls back to generateContent.",
    )
    parser.add_argument(
        "--twilio-server",
        action="store_true",
        help="Start the FastAPI server for Twilio phone integration.",
    )
    parser.add_argument(
        "--twilio-setup",
        action="store_true",
        help="Point the Twilio number's voice webhook at TWILIO_PUBLIC_URL/twilio/voice.",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=8080,
        help="Port for the Twilio server (default: 8080).",
    )
    return parser.parse_args()


async def async_main(args: argparse.Namespace) -> None:
    # Resolve eval transcript: YAML files carry their own transcript lines
    eval_path = args.eval_transcript
    expected_fields: dict[str, Any] = {}

    if eval_path and eval_path.suffix in {".yaml", ".yml"}:
        import yaml
        data = yaml.safe_load(eval_path.read_text(encoding="utf-8"))
        lines = data.get("transcript", [])
        expected_fields = data.get("expect", {})
        # Write transcript lines to a temp text file for the existing runner
        import tempfile, os
        tmp = tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False, encoding="utf-8")
        tmp.write("\n".join(str(l) for l in lines))
        tmp.close()
        eval_path = Path(tmp.name)

    try:
        claim_state = await run_session(
            text_mode=args.text_mode,
            playbook_path=args.playbook,
            storage_dir=args.storage_dir,
            eval_transcript=eval_path,
            transport=args.transport,
        )
    except SessionFinished as exc:
        print(f"\nSession ended: {exc.reason}")
        return
    except Exception as exc:
        print_exception(exc)
        raise

    if (args.eval_assert or expected_fields) and expected_fields:
        _assert_claim(claim_state, expected_fields)


def _assert_claim(claim_state: Any, expected: dict[str, Any]) -> None:
    print("\n── Eval assertions ──")
    passed = failed = 0
    for field, expected_value in expected.items():
        try:
            actual = claim_state.get_path(field)
        except ValueError:
            actual = None
        ok = _values_match(actual, expected_value)
        status = "PASS" if ok else "FAIL"
        print(f"  {status}  {field}: expected={expected_value!r}  actual={actual!r}")
        if ok:
            passed += 1
        else:
            failed += 1
    print(f"\n{passed} passed, {failed} failed")
    if failed:
        sys.exit(1)


def _values_match(actual: Any, expected: Any) -> bool:
    if isinstance(expected, bool):
        return actual == expected
    if isinstance(expected, str) and isinstance(actual, str):
        return expected.lower() in actual.lower()
    return actual == expected


def _twilio_setup() -> None:
    import os
    from twilio.rest import Client

    public_url = os.environ.get("TWILIO_PUBLIC_URL", "").rstrip("/")
    number = os.environ["TWILIO_NUMBER"]
    if not public_url:
        print("TWILIO_PUBLIC_URL is not set in .env")
        return

    webhook_url = f"{public_url}/twilio/voice"
    status_url = f"{public_url}/twilio/status"

    client = Client(
        os.environ["TWILIO_API_KEY_SID"],
        os.environ["TWILIO_API_KEY_SECRET"],
        account_sid=os.environ["TWILIO_ACCOUNT_SID"],
    )
    incoming = client.incoming_phone_numbers.list(phone_number=number)
    if not incoming:
        print(f"Number {number} not found in this Twilio account.")
        return

    incoming[0].update(
        voice_url=webhook_url,
        voice_method="POST",
        status_callback=status_url,
        status_callback_method="POST",
    )
    print(f"Voice webhook set to {webhook_url}")


def _run_twilio_server(port: int) -> None:
    import uvicorn
    from app.phone.server import app as twilio_app

    print(f"Starting Twilio server on port {port}. Set TWILIO_PUBLIC_URL to your tunnel URL.")
    uvicorn.run(twilio_app, host="0.0.0.0", port=port)


def main() -> None:
    load_dotenv(ROOT / ".env")
    args = parse_args()
    if args.twilio_setup:
        _twilio_setup()
        return
    if args.twilio_server:
        _run_twilio_server(args.port)
        return
    asyncio.run(async_main(args))


if __name__ == "__main__":
    main()
