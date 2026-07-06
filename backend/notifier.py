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


def notify_unknown_format(vendor, filename, subject, from_header, pdf_path, error_msg=""):
    """Send an email alert when an invoice with an unknown format is received.

    This triggers when parse_pdf() can't match the PDF to any known vendor
    parser, so the user knows to teach the system the new format.
    """
    subject_line = f"⚠️ Unknown Invoice Format — {vendor} ({filename})"

    body = (
        f"An invoice was received that the system could not parse.\n\n"
        f"  Vendor:         {vendor or 'Unknown'}\n"
        f"  Filename:       {filename}\n"
        f"  Email Subject:  {subject}\n"
        f"  From:           {from_header}\n"
        f"  Saved PDF:      {pdf_path}\n"
    )
    if error_msg:
        body += f"  Parse Error:    {error_msg}\n"
    body += (
        f"\n"
        f"What happened:\n"
        f"  The PDF was saved to disk, but no parser recognized the format.\n"
        f"  You need to teach the system this new format.\n\n"
        f"Steps:\n"
        f"  1. Download and open the PDF from the path above\n"
        f"  2. Identify the vendor and key fields (invoice #, amounts, dates)\n"
        f"  3. Add a parser function in pdf_parser.py and register it in parse_pdf()\n"
        f"  4. Re-process the email or upload the PDF via the dashboard\n\n"
        f"View all invoices: https://vendor-invoice-dashboard.onrender.com"
    )

    # Always send to the sender of the email (fallback to NOTIFY_EMAIL_TO)
    recipients = set()
    reply_addr = ""
    try:
        import email.utils as _emailutils
        _, addr = _emailutils.parseaddr(from_header)
        if addr and "@" in addr:
            reply_addr = addr
    except Exception:
        pass
    if reply_addr:
        recipients.add(reply_addr)
    if NOTIFY_EMAIL_TO:
        for a in NOTIFY_EMAIL_TO.split(","):
            a = a.strip()
            if a:
                recipients.add(a)

    for addr in recipients:
        try:
            _send_email(addr, subject_line, body)
        except Exception as e:
            log.error(f"Unknown-format notification failed to {addr}: {e}")

    # Telegram notification too
    if TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID:
        try:
            _send_telegram(subject_line + "\n\n" + body)
        except Exception as e:
            log.error(f"Telegram notification failed: {e}")


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
