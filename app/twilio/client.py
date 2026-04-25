"""Twilio REST client using API key auth and outbound call helper."""
from __future__ import annotations

import os

from twilio.rest import Client


def get_client() -> Client:
    return Client(
        os.environ["TWILIO_API_KEY_SID"],
        os.environ["TWILIO_API_KEY_SECRET"],
        account_sid=os.environ["TWILIO_ACCOUNT_SID"],
    )


def make_outbound_call(to: str, public_base_url: str) -> str:
    """Initiate a call to *to* and return the Twilio callSid."""
    client = get_client()
    base = public_base_url.rstrip("/")
    call = client.calls.create(
        to=to,
        from_=os.environ["TWILIO_NUMBER"],
        url=f"{base}/twilio/voice",
        status_callback=f"{base}/twilio/status",
        status_callback_method="POST",
    )
    return call.sid
