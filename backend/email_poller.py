from typing import Optional
"""
IMAP inbox polling for vendor invoice emails.

Polls a recent Gmail lookback window — with or without PDF attachments.
Message-ID deduplication in the ingest layer prevents reprocessing. This avoids
losing invoices when another Gmail client marks a message read first.
HTML-only receipts are included so the ingest pipeline can parse them
or store them as unparsed records (never silently dropped).

Adapted from email-attachment-filer/email_handler.py — drops Drive API,
OAuth, confirmation flow, and reply sending.
"""

import email
import email.header
import email.utils
import hashlib
import imaplib
import logging
import re
import time
from datetime import datetime, timedelta, timezone

from config import GMAIL_ADDRESS, GMAIL_APP_PASSWORD

log = logging.getLogger(__name__)


def connect_imap(max_retries=3):
    """Connect to Gmail via IMAP using app password.

    Retries with exponential backoff (#23) — was just logging and giving up.
    """
    if not GMAIL_ADDRESS or not GMAIL_APP_PASSWORD:
        raise RuntimeError(
            "GMAIL_ADDRESS and GMAIL_APP_PASSWORD must be set in .env"
        )
    last_err = None
    for attempt in range(1, max_retries + 1):
        try:
            imap = imaplib.IMAP4_SSL("imap.gmail.com")
            imap.login(GMAIL_ADDRESS, GMAIL_APP_PASSWORD)
            log.debug("IMAP logged in as %s", GMAIL_ADDRESS)
            return imap
        except Exception as e:
            last_err = e
            if attempt < max_retries:
                wait = 2 ** attempt  # 2s, 4s, 8s
                log.warning(
                    "IMAP connection attempt %d/%d failed: %s — retrying in %ds",
                    attempt, max_retries, e, wait
                )
                time.sleep(wait)
    raise RuntimeError(
        f"IMAP connection failed after {max_retries} attempts: {last_err}"
    )


def fetch_recent_emails(imap: imaplib.IMAP4_SSL, lookback_days: int = 7) -> list:
    """
    Fetch messages received in a recent lookback window, regardless of Seen state.

    Returns list of dicts:
      {
        "imap_id":      b"<imap sequence number>",
        "message_id":   "<RFC 2822 Message-ID>",
        "subject":      "<subject>",
        "from":         "<from header>",
        "body_text":    "<plain text body for vendor extraction>",
        "body_html":    "<raw HTML body (empty string if not HTML)>",
        "attachments":  [{"filename": "...", "bytes": b"..."}],  # may be empty
      }
    BODY.PEEK keeps unread messages unread until ingestion succeeds and explicitly
    marks them Seen. The database's processed_emails Message-ID key provides the
    idempotency boundary for messages returned on subsequent polls.
    """
    if lookback_days < 1:
        raise ValueError("lookback_days must be at least 1")

    imap.select("INBOX")
    since = (datetime.now(timezone.utc) - timedelta(days=lookback_days)).strftime(
        "%d-%b-%Y"
    )
    status, data = imap.search(None, "SINCE", since)
    if status != "OK" or not data:
        raise RuntimeError("IMAP recent-message search failed")
    ids = data[0].split()
    if not ids:
        return []

    results = []
    for imap_id in ids:
        _, raw_data = imap.fetch(imap_id, "(BODY.PEEK[])")
        if not raw_data or raw_data[0] is None:
            continue
        raw_response = raw_data[0]
        if not isinstance(raw_response, tuple):
            continue

        msg = email.message_from_bytes(raw_response[1])
        message_id = msg.get("Message-ID", "").strip()
        if not message_id:
            digest = hashlib.sha256(raw_response[1]).hexdigest()
            message_id = f"<generated-{digest}@local>"
        subject = _decode_header(msg.get("Subject", ""))
        from_header = _decode_header(msg.get("From", ""))
        date_header = msg.get("Date", "")
        body_text = _get_plain_text(msg)
        body_html = _get_html_body(msg)
        attachments = _extract_attachments(msg)

        if not attachments:
            # No PDF attachments — include anyway for HTML-only receipts
            # The ingest pipeline will try to parse the body or store as unparsed
            pass

        results.append({
            "imap_id": imap_id,
            "message_id": message_id,
            "subject": subject,
            "from": from_header,
            "received_date": _format_date(date_header),
            "body_text": body_text,
            "body_html": body_html,
            "attachments": attachments,
        })

    log.info("Fetched %d recent email(s) (%d with PDF attachments)",
             len(results), sum(1 for r in results if r["attachments"]))
    return results


def fetch_unseen_emails(imap: imaplib.IMAP4_SSL) -> list:
    """Backward-compatible alias for callers not yet migrated."""
    return fetch_recent_emails(imap)


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


def _get_html_body(msg) -> str:
    """Return the raw HTML body of the email, or empty string."""
    for part in msg.walk():
        if part.get_content_disposition() == "attachment":
            continue
        ct = part.get_content_type()
        if ct == "text/html":
            payload = part.get_payload(decode=True)
            if payload:
                charset = part.get_content_charset() or "utf-8"
                return payload.decode(charset, errors="replace")
    return ""


def _format_date(date_header: str) -> str:
    """Format an RFC 2822 Date header into a human-readable string.

    e.g. 'Sun, 28 Jun 2026 11:25:39 +0000' -> 'Jun 28, 2026, 04:25 AM PDT'
    Falls back to the raw header if parsing fails.
    """
    if not date_header:
        return ""
    try:
        dt = email.utils.parsedate_to_datetime(date_header)
        return dt.strftime("%b %d, %Y, %I:%M %p %Z").strip()
    except Exception:
        return date_header
