#!/usr/bin/env python3
"""
Reprocess already-seen emails by fetching them via IMAP (by sequence ID) and
running them through the ingest pipeline.

Usage:
  python reprocess_seen.py 181 183

This will:
  1. Fetch the specified email sequence IDs from Gmail (using BODY.PEEK so
     flags stay untouched — emails are already Seen).
  2. Run each email through process_email() which saves the HTML/PDF to disk,
     parses it, and inserts into the DB.
  3. Skip already-processed emails (dedup by message_id).

The script reads GMAIL_ADDRESS and GMAIL_APP_PASSWORD from the project .env,
or falls back to the Render env-var format.

Alternative approach (simpler, no script needed):
  - Mark the emails as Unread in Gmail web UI -> the poller will pick them up
    after the fix deploys to Render. Because the fix now includes attachment-less
    emails in the fetch, once marked Unread the poller will process them.
"""

import email
import email.header
import email.utils
import imaplib
import logging
import os
import re
import sys
import time
from pathlib import Path

# Add backend to path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))

logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s"
)
log = logging.getLogger(__name__)

# Load .env if present
dotenv_path = Path(__file__).resolve().parent.parent / ".env"
if dotenv_path.exists():
    with open(dotenv_path) as f:
        for line in f:
            line = line.strip()
            if line and "=" in line and not line.startswith("#"):
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip())


def _decode_header(value):
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


def _get_plain_text(msg):
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


def _get_html_body(msg):
    for part in msg.walk():
        if part.get_content_disposition() == "attachment":
            continue
        ct = part.get_content_type()
        if ct == "text/html":
            payload = part.get_payload(decode=True)
            if payload:
                chars = part.get_content_charset() or "utf-8"
                return payload.decode(chars, errors="replace")
    return ""


def _extract_attachments(msg):
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


def _format_date(date_header):
    if not date_header:
        return ""
    try:
        dt = email.utils.parsedate_to_datetime(date_header)
        return dt.strftime("%b %d, %Y, %I:%M %p %Z").strip()
    except Exception:
        return date_header


def main():
    if len(sys.argv) < 2:
        print(f"Usage: {sys.argv[0]} <imap_seq_id> [imap_seq_id ...]")
        print(f"  e.g.: {sys.argv[0]} 181 183")
        sys.exit(1)

    seq_ids = [int(a) for a in sys.argv[1:]]

    addr = os.environ.get("GMAIL_ADDRESS") or "receipts.oktechsol@gmail.com"
    pwd = os.environ.get("GMAIL_APP_PASSWORD")

    if not pwd:
        # Try reading from environment directly
        pwd = None
        for env_key in ("GMAIL_APP_PASSWORD", "GMAIL_PASSWORD"):
            val = os.environ.get(env_key)
            if val:
                pwd = val
                break

    if not pwd:
        print("ERROR: GMAIL_APP_PASSWORD not found. Set it in .env or export it.")
        print("  export GMAIL_APP_PASSWORD='your-password'")
        sys.exit(1)

    print(f"Connecting to Gmail as {addr}...")
    imap = imaplib.IMAP4_SSL("imap.gmail.com")
    imap.login(addr, pwd)
    imap.select("INBOX")

    # Import ingest AFTER path setup
    from ingest import process_email
    from db import get_db, init_db

    init_db()
    conn = get_db()

    for seq_id in seq_ids:
        print(f"\n{'='*60}")
        print(f"Fetching message sequence {seq_id}...")
        _, raw_data = imap.fetch(str(seq_id), "BODY.PEEK[]")
        if not raw_data or raw_data[0] is None:
            print(f"  No data for seq {seq_id}")
            continue
        raw_response = raw_data[0]
        if not isinstance(raw_response, tuple):
            print(f"  Unexpected response for seq {seq_id}")
            continue

        msg = email.message_from_bytes(raw_response[1])
        subject = _decode_header(msg.get("Subject", ""))
        from_h = _decode_header(msg.get("From", ""))
        date_h = msg.get("Date", "")
        message_id = (msg.get("Message-ID") or f"reprocess_{seq_id}").strip()
        body_text = _get_plain_text(msg)
        body_html = _get_html_body(msg)
        attachments = _extract_attachments(msg)

        email_data = {
            "imap_id": str(seq_id).encode(),
            "message_id": message_id or f"reprocess_{seq_id}",
            "subject": subject,
            "from": from_h,
            "received_date": _format_date(date_h),
            "body_text": body_text,
            "body_html": body_html,
            "attachments": attachments,
        }

        print(f"  Subject: {subject}")
        print(f"  From: {from_h}")
        print(f"  Attachments: {len(attachments)} PDF(s)")
        print(f"  Has HTML body: {bool(body_html)}")

        try:
            process_email(conn, email_data)
            print(f"  -> Processed successfully")
        except Exception as e:
            print(f"  -> Error: {e}")
            import traceback
            traceback.print_exc()

    imap.logout()
    conn.close()
    print(f"\nDone. Processed {len(seq_ids)} email(s).")


if __name__ == "__main__":
    main()