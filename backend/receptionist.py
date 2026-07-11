"""
Receptionist webhook — receives take_message tool calls from the Ava
voice agent (xAI Grok Voice Agent Builder) and notifies Jay.

POST /api/receptionist/message
Auth: X-Receptionist-Token header must match RECEPTIONIST_TOKEN env var.

Payload (all fields optional strings unless noted):
{
  "caller_name":   "John Smith",
  "company":       "Acme Corp",
  "callback_number": "405-555-1234",
  "reason":        "Server is down at their office",
  "intent":        "support",          # support|sales|billing|vendor|other
  "urgency":       "normal",           # low|normal|urgent
  "call_id":       "grok-call-id"      # optional, for cross-reference
}

Stores in SQLite (receptionist_messages table) and emails NOTIFY_TO.
"""

import json
import logging
import smtplib
import sqlite3
from datetime import datetime, timezone
from email.mime.text import MIMEText

from config import GMAIL_ADDRESS, GMAIL_APP_PASSWORD, DB_PATH

log = logging.getLogger(__name__)

NOTIFY_TO = "jay@oktechsol.com"

SCHEMA = """
CREATE TABLE IF NOT EXISTS receptionist_messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    received_at TEXT NOT NULL,
    caller_name TEXT,
    company TEXT,
    callback_number TEXT,
    reason TEXT,
    intent TEXT,
    urgency TEXT,
    call_id TEXT,
    raw_payload TEXT
);
"""


def init_receptionist_table():
    conn = sqlite3.connect(DB_PATH)
    try:
        conn.execute(SCHEMA)
        conn.commit()
    finally:
        conn.close()


def store_message(payload: dict) -> int:
    conn = sqlite3.connect(DB_PATH)
    try:
        cur = conn.execute(
            """INSERT INTO receptionist_messages
               (received_at, caller_name, company, callback_number,
                reason, intent, urgency, call_id, raw_payload)
               VALUES (?,?,?,?,?,?,?,?,?)""",
            (
                datetime.now(timezone.utc).isoformat(),
                payload.get("caller_name"),
                payload.get("company"),
                payload.get("callback_number"),
                payload.get("reason"),
                payload.get("intent"),
                payload.get("urgency", "normal"),
                payload.get("call_id"),
                json.dumps(payload),
            ),
        )
        conn.commit()
        return cur.lastrowid or 0
    finally:
        conn.close()


def notify_email(payload: dict, msg_id: int):
    if not GMAIL_ADDRESS or not GMAIL_APP_PASSWORD:
        log.warning("Receptionist: Gmail creds missing, skipping email")
        return
    urgency = (payload.get("urgency") or "normal").lower()
    prefix = "🔴 URGENT — " if urgency == "urgent" else ""
    subject = f"{prefix}📞 Message from {payload.get('caller_name') or 'Unknown caller'}"
    if payload.get("company"):
        subject += f" ({payload['company']})"

    body = (
        f"Ava took a message (#{msg_id}):\n\n"
        f"Caller:    {payload.get('caller_name') or 'Unknown'}\n"
        f"Company:   {payload.get('company') or '-'}\n"
        f"Callback:  {payload.get('callback_number') or '-'}\n"
        f"Intent:    {payload.get('intent') or '-'}\n"
        f"Urgency:   {urgency}\n\n"
        f"Reason:\n{payload.get('reason') or '-'}\n\n"
        f"— OKTechSol AI Receptionist"
    )
    msg = MIMEText(body, "plain", "utf-8")
    msg["Subject"] = subject
    msg["From"] = f"OKTechSol Receptionist <{GMAIL_ADDRESS}>"
    msg["To"] = NOTIFY_TO
    try:
        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as smtp:
            smtp.login(GMAIL_ADDRESS, GMAIL_APP_PASSWORD)
            smtp.sendmail(GMAIL_ADDRESS, [NOTIFY_TO], msg.as_string())
        log.info("Receptionist message #%s emailed to %s", msg_id, NOTIFY_TO)
    except Exception as e:
        log.error("Receptionist email failed: %s", e)
