from typing import Optional
"""
IMAP inbox polling for vendor invoice emails.

Polls a Gmail inbox for unseen emails with PDF attachments,
extracts the attachments, and returns them for processing.

Adapted from email-attachment-filer/email_handler.py — drops Drive API,
OAuth, confirmation flow, and reply sending.
"""

import email
import email.header
import imaplib
import logging
import re

from config import GMAIL_ADDRESS, GMAIL_APP_PASSWORD

log = logging.getLogger(__name__)


def connect_imap() -> imaplib.IMAP4_SSL:
    """Connect to Gmail via IMAP using app password."""
    if not GMAIL_ADDRESS or not GMAIL_APP_PASSWORD:
        raise RuntimeError(
            "GMAIL_ADDRESS and GMAIL_APP_PASSWORD must be set in .env"
        )
    imap = imaplib.IMAP4_SSL("imap.gmail.com")
    imap.login(GMAIL_ADDRESS, GMAIL_APP_PASSWORD)
    log.debug("IMAP logged in as %s", GMAIL_ADDRESS)
    return imap


def fetch_unseen_emails(imap: imaplib.IMAP4_SSL) -> list:
    """
    Fetch all UNSEEN emails with PDF attachments.

    Returns list of dicts:
      {
        "imap_id":      b"<imap sequence number>",
        "message_id":   "<RFC 2822 Message-ID>",
        "subject":      "<subject>",
        "from":         "<from header>",
        "body_text":    "<plain text body for vendor extraction>",
        "attachments":  [{"filename": "...", "bytes": b"..."}],
      }
    """
    imap.select("INBOX")
    _, data = imap.search(None, "UNSEEN")
    ids = data[0].split()
    if not ids:
        return []

    results = []
    for imap_id in ids:
        _, raw_data = imap.fetch(imap_id, "(RFC822)")
        if not raw_data or raw_data[0] is None:
            continue
        raw_response = raw_data[0]
        if not isinstance(raw_response, tuple):
            continue

        msg = email.message_from_bytes(raw_response[1])
        message_id = msg.get("Message-ID", "").strip()
        subject = _decode_header(msg.get("Subject", ""))
        from_header = _decode_header(msg.get("From", ""))
        body_text = _get_plain_text(msg)
        attachments = _extract_attachments(msg)

        if not attachments:
            # No PDF attachments — mark as seen and skip
            imap.store(imap_id, "+FLAGS", "\\Seen")
            continue

        results.append({
            "imap_id": imap_id,
            "message_id": message_id,
            "subject": subject,
            "from": from_header,
            "body_text": body_text,
            "attachments": attachments,
        })

    log.info("Fetched %d unseen email(s) with PDF attachments", len(results))
    return results


def mark_seen(imap: imaplib.IMAP4_SSL, imap_id: bytes) -> None:
    imap.store(imap_id, "+FLAGS", "\\Seen")


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _extract_attachments(msg) -> list:
    """Extract all PDF attachments from an email message."""
    attachments = []
    for part in msg.walk():
        disposition = part.get_content_disposition()
        if disposition and disposition.lower() == "attachment":
            filename = _decode_header(part.get_filename()) or "attachment"
            if not filename.lower().endswith(".pdf"):
                continue
            payload = part.get_payload(decode=True)
            if payload is None:
                continue
            attachments.append({"filename": filename, "bytes": payload})
    return attachments


def _decode_header(value: Optional[str]) -> str:
    if not value:
        return ""
    parts = email.header.decode_header(value)
    decoded = []
    for part, charset in parts:
        if isinstance(part, bytes):
            decoded.append(part.decode(charset or "utf-8", errors="replace"))
        else:
            decoded.append(part)
    return "".join(decoded)


def _get_plain_text(msg) -> str:
    """Return the plain-text body for vendor/forwarded-header extraction."""
    text_body = None
    html_body = None
    for part in msg.walk():
        if part.get_content_disposition() == "attachment":
            continue
        ct = part.get_content_type()
        payload = part.get_payload(decode=True)
        if payload is None:
            continue
        charset = part.get_content_charset() or "utf-8"
        decoded = payload.decode(charset, errors="replace")
        if ct == "text/html":
            html_body = decoded
        elif ct == "text/plain" and text_body is None:
            text_body = decoded

    if text_body:
        return text_body
    if html_body:
        return re.sub(r"<[^>]+>", " ", html_body)
    return ""
