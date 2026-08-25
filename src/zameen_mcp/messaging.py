"""Agent-message DRAFTING for zameen-mcp.

This module composes suggested inquiry texts for a human to send themselves.
It NEVER sends anything anywhere — no network calls, no endpoints, no
side effects beyond returning strings.
"""

from __future__ import annotations

from typing import List, Optional


DEFAULT_QUESTIONS = [
    "Is this property still available?",
    "Can I schedule a visit this week?",
]

_TONES = ("brief", "detailed")


def build_draft(detail: dict,
                *,
                sender_name: str = "",
                questions: Optional[List[str]] = None,
                tone: str = "brief") -> dict:
    """Compose a polite agent inquiry from a parsed listing-detail dict.

    ``detail`` is the output of ``parsers.parse_listing_detail`` /
    ``client.get_listing``. Returns a dict with the draft text and context —
    sending it remains a HUMAN action (WhatsApp/call/email by choice).
    """
    if tone not in _TONES:
        raise ValueError(f"tone must be one of {_TONES}, got {tone!r}")
    qs = list(questions) if questions else DEFAULT_QUESTIONS

    title = (detail.get("title") or "your listing").strip()
    location = (detail.get("location") or "").strip()
    price = (detail.get("price_text") or "").strip()
    url = (detail.get("url") or "").strip()

    greeting = f"Hello, this is {sender_name}. " if sender_name.strip() else "Hello. "

    if tone == "brief":
        lines = [
            greeting.rstrip(),
            f"I'm interested in: {title}" + (f" ({price})" if price else ""),
            *[f"- {q}" for q in qs],
        ]
    else:
        lines = [
            greeting.rstrip(),
            "I came across your property listing and would like to know more.",
            f"Property: {title}",
        ]
        if location:
            lines.append(f"Location: {location}")
        if price:
            lines.append(f"Listed price: {price}")
        lines.append("My questions:")
        lines.extend(f"{i}) {q}" for i, q in enumerate(qs, start=1))
        if url:
            lines.append(f"Listing link: {url}")

    message = "\n".join(line for line in lines if line)

    return {
        "channel_hint": "whatsapp_or_call — send it YOURSELF; this tool never sends",
        "tone": tone,
        "message": message,
        "listing_id": detail.get("listing_id", ""),
        "listing_url": url,
        "questions_used": qs,
    }
