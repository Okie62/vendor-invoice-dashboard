"""
Notification module for new invoice arrivals (#21).

Supports email notifications (via existing SMTP) and Telegram bot integration.
Configured via environment variables:
  NOTIFY_EMAIL_TO — comma-separated email addresses
  TELEGRAM_BOT_TOKEN — Telegram bot token
  TELEGRAM_CHAT_ID — Telegram chat/channel ID
"""
import logging
import os
import smtplib
from email.mime.text import MIMEText

from config import GMAIL_ADDRESS, GMAIL_APP_PASSWORD

log = logging.getLogger(__name__)

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")
NOTIFY_EMAIL_TO = os.getenv("NOTIFY_EMAIL_TO", "")


def notify_new_invoice(invoice_id, vendor, amount, billing_period):
    """Send notifications about a new invoice arrival (#21)."""
    subject = f"New Invoice: {vendor} — #{invoice_id}"
    body = (
        f"A new invoice has been processed:\n\n"
        f"  Invoice ID:    {invoice_id}\n"
        f"  Vendor:        {vendor}\n"
        f"  Billing Period:{billing_period}\n"
        f"  Amount:        ${amount:,.2f}\n\n"
        f"View it on the dashboard."
    )

    # Email notification
    if NOTIFY_EMAIL_TO:
        for addr in NOTIFY_EMAIL_TO.split(","):
            addr = addr.strip()
            if addr:
                try:
                    _send_email(addr, subject, body)
                except Exception as e:
                    log.error(f"Email notification failed to {addr}: {e}")

    # Telegram notification
    if TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID:
        try:
            _send_telegram(subject + "\n\n" + body)
        except Exception as e:
            log.error(f"Telegram notification failed: {e}")


def _send_email(to_addr, subject, body):
    """Send an email notification."""
    if not GMAIL_ADDRESS or not GMAIL_APP_PASSWORD:
        return
    msg = MIMEText(body, "plain", "utf-8")
    msg["Subject"] = subject
    msg["From"] = f"Vendor Invoice Dashboard <{GMAIL_ADDRESS}>"
    msg["To"] = to_addr
    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as smtp:
        smtp.login(GMAIL_ADDRESS, GMAIL_APP_PASSWORD)
        smtp.sendmail(GMAIL_ADDRESS, [to_addr], msg.as_string())
    log.info(f"Notification email sent to {to_addr}")


def _send_telegram(text):
    """Send a Telegram message via bot API."""
    import urllib.request
    import urllib.parse
    import json

    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    data = urllib.parse.urlencode({
        "chat_id": TELEGRAM_CHAT_ID,
        "text": text,
        "parse_mode": "HTML",
    }).encode()
    req = urllib.request.Request(url, data=data)
    resp = urllib.request.urlopen(req, timeout=10)
    result = json.loads(resp.read())
    if result.get("ok"):
        log.info("Telegram notification sent")
    else:
        log.error(f"Telegram API error: {result}")
