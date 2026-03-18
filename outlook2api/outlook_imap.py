"""Outlook IMAP client for fetching emails with verification code extraction."""

from __future__ import annotations

import email
import imaplib
import re
from email.header import decode_header
from typing import Optional


def _decode_subject(header_val: str) -> str:
    """Decode email subject from RFC 2047 encoding."""
    if not header_val:
        return ""
    parts = decode_header(header_val)
    result = []
    for part, charset in parts:
        if isinstance(part, bytes):
            result.append(part.decode(charset or "utf-8", errors="replace"))
        else:
            result.append(str(part))
    return "".join(result)


def _extract_verification_code(text: str, html: str = "") -> str:
    """Extract 6-digit OTP or XXX-XXX format from email body."""
    content = f"{text}\n{html}"
    m = re.search(r"\b(\d{6})\b", content)
    if m:
        return m.group(1)
    m = re.search(r"\b([A-Z0-9]{3}-[A-Z0-9]{3})\b", content)
    if m:
        return m.group(1)
    return ""


def fetch_messages_imap(
    email_addr: str,
    password: str,
    folder: str = "INBOX",
    limit: int = 20,
    host: str = "outlook.office365.com",
    port: int = 993,
) -> list[dict]:
    """Connect via IMAP and fetch recent messages.

    Returns list of dicts with keys: id, from, subject, intro, text, html, verification_code.
    """
    messages = []
    try:
        mail = imaplib.IMAP4_SSL(host, port)
        mail.login(email_addr, password)
        mail.select(folder)
        _, data = mail.search(None, "ALL")
        ids = data[0].split()
        ids = ids[-limit:] if len(ids) > limit else ids

        for i, msg_id in enumerate(reversed(ids)):
            try:
                _, msg_data = mail.fetch(msg_id, "(RFC822)")
                if not msg_data:
                    continue
                raw = msg_data[0][1]
                if isinstance(raw, bytes):
                    msg = email.message_from_bytes(raw)
                else:
                    msg = email.message_from_string(raw.decode("utf-8", errors="replace"))

                subject = _decode_subject(msg.get("Subject", ""))
                from_addr = msg.get("From", "")

                text = ""
                html = ""
                if msg.is_multipart():
                    for part in msg.walk():
                        ct = part.get_content_type()
                        payload = part.get_payload(decode=True)
                        if payload is None:
                            continue
                        charset = part.get_content_charset() or "utf-8"
                        decoded = payload.decode(charset, errors="replace")
                        if ct == "text/plain":
                            text += decoded
                        elif ct == "text/html":
                            html += decoded
                else:
                    payload = msg.get_payload(decode=True)
                    if payload:
                        charset = msg.get_content_charset() or "utf-8"
                        decoded = payload.decode(charset, errors="replace")
                        if msg.get_content_type() == "text/html":
                            html = decoded
                        else:
                            text = decoded

                intro = (text or html)[:200].replace("\n", " ")
                verification_code = _extract_verification_code(text, html)

                messages.append({
                    "id": msg_id.decode() if isinstance(msg_id, bytes) else str(msg_id),
                    "from": {"address": from_addr, "name": ""},
                    "subject": subject,
                    "intro": intro,
                    "text": text,
                    "html": [html],
                    "verification_code": verification_code,
                })
            except Exception:
                continue

        mail.logout()
    except Exception:
        pass
    return messages


def validate_login(
    email_addr: str,
    password: str,
    host: str = "outlook.office365.com",
    port: int = 993,
) -> bool:
    """Verify that email+password can login to Outlook IMAP."""
    try:
        mail = imaplib.IMAP4_SSL(host, port)
        mail.login(email_addr, password)
        mail.logout()
        return True
    except Exception:
        return False
