"""Outlook SMTP client for sending emails."""

from __future__ import annotations

import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

from outlook2api.config import get_config


def send_email(
    from_addr: str,
    password: str,
    to_addr: str,
    subject: str,
    body_text: str = "",
    body_html: str = "",
    cc: str = "",
    in_reply_to: str = "",
    references: str = "",
) -> dict:
    """Send an email via Outlook SMTP with STARTTLS.

    Returns dict with status, from, to, subject on success.
    Raises RuntimeError on failure.
    """
    cfg = get_config()
    smtp_host = cfg.get("smtp_host", "smtp-mail.outlook.com")
    smtp_port = cfg.get("smtp_port", 587)

    msg = MIMEMultipart("alternative")
    msg["From"] = from_addr
    msg["To"] = to_addr
    msg["Subject"] = subject

    if cc:
        msg["Cc"] = cc
    if in_reply_to:
        msg["In-Reply-To"] = in_reply_to
    if references:
        msg["References"] = references

    if body_text:
        msg.attach(MIMEText(body_text, "plain", "utf-8"))
    if body_html:
        msg.attach(MIMEText(body_html, "html", "utf-8"))
    elif body_text:
        # If no HTML provided, send text as the only part
        pass
    else:
        msg.attach(MIMEText("", "plain", "utf-8"))

    try:
        with smtplib.SMTP(smtp_host, smtp_port, timeout=30) as server:
            server.ehlo()
            server.starttls()
            server.ehlo()
            server.login(from_addr, password)
            recipients = [to_addr]
            if cc:
                recipients.extend(a.strip() for a in cc.split(",") if a.strip())
            server.sendmail(from_addr, recipients, msg.as_string())
    except smtplib.SMTPAuthenticationError as e:
        raise RuntimeError(f"SMTP authentication failed: {e}") from e
    except smtplib.SMTPException as e:
        raise RuntimeError(f"SMTP error: {e}") from e
    except Exception as e:
        raise RuntimeError(f"Failed to send email: {e}") from e

    return {"status": "sent", "from": from_addr, "to": to_addr, "subject": subject}
