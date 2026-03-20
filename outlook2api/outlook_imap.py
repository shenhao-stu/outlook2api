"""Outlook IMAP client for fetching emails with verification code extraction."""

from __future__ import annotations

import email
import imaplib
import re
from email.header import decode_header
from typing import Optional

# Folder name mappings for Outlook
OUTLOOK_FOLDERS = {
    "inbox": ["INBOX"],
    "junk": ["Junk", "Junk Email", "JUNK"],
    "sent": ["Sent", "Sent Items", "SENT"],
    "drafts": ["Drafts", "DRAFTS"],
    "deleted": ["Deleted", "Deleted Items", "Trash", "TRASH"],
    "archive": ["Archive", "ARCHIVE"],
}


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


def _strip_html(html: str) -> str:
    """Strip HTML tags for plain text preview."""
    text = re.sub(r"<(script|style)[^>]*>.*?</\1>", "", html, flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def _has_attachment(part) -> bool:
    """Check if a MIME part is an attachment."""
    try:
        cd = part.get("Content-Disposition", "")
        return cd and ("attachment" in cd.lower() or "inline" in cd.lower())
    except Exception:
        return False


def _extract_verification_code(text: str, html: str = "") -> str:
    """Extract verification code from email body.

    Supports: 4-8 digit OTP, XXX-XXX format, and keyword-based extraction.
    """
    content = f"{text}\n{html}"

    # Look for codes near verification keywords
    keywords = r"(?:验证码|verification|verify|code|OTP|confirm|pin|安全码|授权码)"
    # Pattern: keyword followed by a code within ~50 chars
    m = re.search(keywords + r".{0,50}?\b(\d{4,8})\b", content, re.IGNORECASE)
    if m:
        return m.group(1)
    # Pattern: code followed by keyword
    m = re.search(r"\b(\d{4,8})\b.{0,30}?" + keywords, content, re.IGNORECASE)
    if m:
        return m.group(1)

    # Fallback: standalone 6-digit code
    m = re.search(r"\b(\d{6})\b", content)
    if m:
        return m.group(1)
    # Dash-separated format
    m = re.search(r"\b([A-Z0-9]{3}-[A-Z0-9]{3})\b", content)
    if m:
        return m.group(1)
    return ""


def _extract_verification_link(text: str, html: str = "") -> str:
    """Extract verification/confirmation link from email body."""
    content = f"{text}\n{html}"
    link_keywords = r"(?:verify|confirm|activate|validate|reset|unsubscribe)"
    urls = re.findall(r'https?://[^\s<>"\']+', content)
    for url in urls:
        if re.search(link_keywords, url, re.IGNORECASE):
            return url
    return ""


def _resolve_folder(mail: imaplib.IMAP4_SSL, folder_key: str) -> str:
    """Resolve a folder key to an actual IMAP folder name."""
    candidates = OUTLOOK_FOLDERS.get(folder_key.lower(), [folder_key])
    # Try each candidate
    for name in candidates:
        try:
            status, _ = mail.select(name, readonly=True)
            if status == "OK":
                return name
        except Exception:
            continue
    # Fallback: try the key itself
    return candidates[0] if candidates else folder_key


def list_folders(
    email_addr: str,
    password: str,
    host: str = "outlook.office365.com",
    port: int = 993,
) -> list[dict]:
    """List available IMAP folders for an account."""
    folders = []
    try:
        mail = imaplib.IMAP4_SSL(host, port, timeout=30)
        mail.login(email_addr, password)
        status, folder_data = mail.list()
        if status == "OK":
            for item in folder_data:
                if isinstance(item, bytes):
                    decoded = item.decode("utf-8", errors="replace")
                    # Parse IMAP LIST response: (\\flags) "delimiter" "name"
                    m = re.match(r'\(([^)]*)\)\s+"([^"]+)"\s+"?([^"]+)"?', decoded)
                    if m:
                        flags, delimiter, name = m.groups()
                        name = name.strip('"')
                        folders.append({
                            "name": name,
                            "flags": flags,
                            "delimiter": delimiter,
                        })
        mail.logout()
    except Exception:
        pass
    return folders


def delete_messages_imap(
    email_addr: str,
    password: str,
    message_ids: list[str],
    folder: str = "INBOX",
    host: str = "outlook.office365.com",
    port: int = 993,
) -> dict:
    """Delete messages by IMAP ID. Returns count of deleted messages."""
    deleted = 0
    errors = []
    try:
        mail = imaplib.IMAP4_SSL(host, port, timeout=30)
        mail.login(email_addr, password)
        mail.select(folder)
        for msg_id in message_ids:
            try:
                mail.store(msg_id.encode() if isinstance(msg_id, str) else msg_id, "+FLAGS", "\\Deleted")
                deleted += 1
            except Exception as e:
                errors.append(f"Failed to delete {msg_id}: {e}")
        mail.expunge()
        mail.logout()
    except Exception as e:
        errors.append(f"IMAP error: {e}")
    return {"deleted": deleted, "errors": errors}


def fetch_messages_imap(
    email_addr: str,
    password: str,
    folder: str = "INBOX",
    limit: int = 20,
    host: str = "outlook.office365.com",
    port: int = 993,
    search: str = "",
) -> list[dict]:
    """Connect via IMAP and fetch recent messages.

    Returns list of dicts with keys: id, from, subject, intro, text, html,
    verification_code, verification_link, has_attachments, date, folder.
    """
    messages = []
    try:
        mail = imaplib.IMAP4_SSL(host, port, timeout=30)
        mail.login(email_addr, password)

        # Resolve folder name
        actual_folder = _resolve_folder(mail, folder) if folder != "INBOX" else "INBOX"
        status, _ = mail.select(actual_folder, readonly=True)
        if status != "OK":
            mail.select("INBOX", readonly=True)
            actual_folder = "INBOX"

        # Build search criteria
        search_criteria = "ALL"
        if search:
            search_criteria = f'(OR SUBJECT "{search}" FROM "{search}")'

        _, data = mail.uid("SEARCH", None, search_criteria)
        uids = data[0].split()
        uids = uids[-limit:] if len(uids) > limit else uids

        for uid in reversed(uids):
            try:
                _, msg_data = mail.uid("FETCH", uid, "(RFC822 FLAGS)")
                if not msg_data or not msg_data[0]:
                    continue

                raw = msg_data[0][1]
                # Extract flags
                flags_str = ""
                if len(msg_data) > 1 and msg_data[1]:
                    flags_match = re.search(r"FLAGS \(([^)]*)\)",
                        msg_data[1].decode() if isinstance(msg_data[1], bytes) else str(msg_data[1]))
                    if flags_match:
                        flags_str = flags_match.group(1)

                if isinstance(raw, bytes):
                    msg = email.message_from_bytes(raw)
                else:
                    msg = email.message_from_string(raw.decode("utf-8", errors="replace"))

                subject = _decode_subject(msg.get("Subject", ""))
                from_raw = msg.get("From", "")
                date_str = msg.get("Date", "")
                msg_id_header = msg.get("Message-ID", "")

                # Parse from address
                from_match = re.match(r'"?([^"<]*)"?\s*<?([^>]*)>?', from_raw)
                from_name = from_match.group(1).strip() if from_match else ""
                from_addr = from_match.group(2).strip() if from_match else from_raw

                text = ""
                html = ""
                has_attachments = False

                if msg.is_multipart():
                    for part in msg.walk():
                        if _has_attachment(part):
                            has_attachments = True
                            continue
                        ct = part.get_content_type()
                        payload = part.get_payload(decode=True)
                        if payload is None:
                            continue
                        charset = part.get_content_charset() or "utf-8"
                        decoded = payload.decode(charset, errors="replace")
                        if ct == "text/plain" and not text:
                            text = decoded
                        elif ct == "text/html" and not html:
                            html = decoded
                else:
                    payload = msg.get_payload(decode=True)
                    if payload:
                        charset = msg.get_content_charset() or "utf-8"
                        decoded = payload.decode(charset, errors="replace")
                        if msg.get_content_type() == "text/html":
                            html = decoded
                        else:
                            text = decoded

                # Generate preview
                if text:
                    intro = text[:200].replace("\n", " ").strip()
                elif html:
                    intro = _strip_html(html)[:200]
                else:
                    intro = ""

                verification_code = _extract_verification_code(text, html)
                verification_link = _extract_verification_link(text, html)
                is_read = "\\Seen" in flags_str

                messages.append({
                    "id": uid.decode() if isinstance(uid, bytes) else str(uid),
                    "message_id": msg_id_header,
                    "from": {"address": from_addr, "name": from_name},
                    "subject": subject,
                    "intro": intro,
                    "text": text,
                    "html": [html] if html else [],
                    "date": date_str,
                    "is_read": is_read,
                    "has_attachments": has_attachments,
                    "verification_code": verification_code,
                    "verification_link": verification_link,
                    "folder": actual_folder,
                })
            except Exception:
                continue

        mail.logout()
    except imaplib.IMAP4.error as e:
        raise RuntimeError(f"IMAP authentication failed: {e}") from e
    except Exception as e:
        if "LOGIN" in str(e).upper() or "AUTH" in str(e).upper():
            raise RuntimeError(f"IMAP authentication failed: {e}") from e
        # For other errors, return whatever we collected
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
        mail = imaplib.IMAP4_SSL(host, port, timeout=30)
        mail.login(email_addr, password)
        mail.logout()
        return True
    except Exception:
        return False
