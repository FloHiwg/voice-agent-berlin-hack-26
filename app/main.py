from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

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
        help="Optional plaintext file with one user turn per line.",
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
        "--call",
        metavar="PHONE_NUMBER",
        default=None,
        help="Dial a number via Twilio (requires TWILIO_PUBLIC_URL in .env).",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=8080,
        help="Port for the Twilio server (default: 8080).",
    )
    return parser.parse_args()


async def async_main() -> None:
    load_dotenv(ROOT / ".env")
    args = parse_args()

    if args.twilio_server:
        _run_twilio_server(args.port)
        return

    if args.call:
        _make_call(args.call)
        return

    try:
        await run_session(
            text_mode=args.text_mode,
            playbook_path=args.playbook,
            storage_dir=args.storage_dir,
            eval_transcript=args.eval_transcript,
            transport=args.transport,
        )
    except SessionFinished as exc:
        print(f"\nSession ended: {exc.reason}")
    except Exception as exc:
        print_exception(exc)
        raise


def _run_twilio_server(port: int) -> None:
    import uvicorn
    from app.twilio.server import app as twilio_app

    print(f"Starting Twilio server on port {port}. Set TWILIO_PUBLIC_URL to your tunnel URL.")
    uvicorn.run(twilio_app, host="0.0.0.0", port=port)


def _make_call(to: str) -> None:
    from app.twilio.client import make_outbound_call

    public_url = __import__("os").getenv("TWILIO_PUBLIC_URL", "")
    if not public_url:
        print("TWILIO_PUBLIC_URL is required for outbound calls.")
        return
    call_sid = make_outbound_call(to, public_url)
    print(f"Call initiated: {call_sid}")


def main() -> None:
    asyncio.run(async_main())


if __name__ == "__main__":
    main()
