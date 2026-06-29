"""
SMTP reply sender for confirming invoice receipt.

Sends an HTML + plain-text confirmation email back to the original sender
after a vendor invoice has been successfully processed.

Template adapted from Intuit's "We got your email" auto-reply format,
rebranded for Oklahoma Technology Solutions.
"""

import email.utils
import logging
import re
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

from config import GMAIL_ADDRESS, GMAIL_APP_PASSWORD

log = logging.getLogger(__name__)

# -----------------------------------------------------------------------
# Plain-text version
# -----------------------------------------------------------------------

PLAIN_BODY = """\
We got your email

Oklahoma Technology Solutions has received and processed your invoice.

Subject:  {original_subject}
Date:     {received_date}
Attachments: {attachment_count} file(s)

Invoice Details:
  Invoice ID:      {invoice_id}
  Vendor:          {vendor}
  Billing Period:  {billing_period}
  Amount:          ${amount:,.2f}

Your invoice has been parsed and added to our dashboard. If you believe
this was received in error, please reply to this email.

— Oklahoma Technology Solutions
https://oktechsol.com
"""

# -----------------------------------------------------------------------
# HTML version (OTS-branded, adapted from Intuit's format)
# -----------------------------------------------------------------------

HTML_BODY = """\
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<style>
  body {{ margin: 0; padding: 0; background: #F0F4F6; font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Arial, sans-serif; }}
  .wrapper {{ max-width: 580px; margin: 0 auto; background: #ffffff; }}
  .header {{ background: #1a1d27; padding: 32px 40px; text-align: center; }}
  .header h1 {{ color: #ffffff; font-size: 22px; margin: 0; font-weight: 700; }}
  .header .subtitle {{ color: #8b8f9a; font-size: 14px; margin-top: 6px; }}
  .body {{ padding: 36px 40px; }}
  .body h2 {{ color: #1a1d27; font-size: 20px; margin: 0 0 4px; font-weight: 700; }}
  .body .lead {{ color: #8b8f9a; font-size: 15px; margin: 0 0 28px; }}
  .review-section {{ background: #f8f9fa; border: 1px solid #e2e6ea; border-radius: 8px; padding: 20px 24px; margin-bottom: 28px; }}
  .review-label {{ font-size: 12px; text-transform: uppercase; letter-spacing: 0.5px; color: #8b8f9a; margin-bottom: 2px; }}
  .review-value {{ font-size: 15px; color: #1a1d27; font-weight: 600; margin-bottom: 14px; }}
  .review-value:last-child {{ margin-bottom: 0; }}
  .invoice-section {{ background: #1a1d27; border-radius: 8px; padding: 20px 24px; margin-bottom: 28px; }}
  .invoice-section h3 {{ color: #ffffff; font-size: 14px; text-transform: uppercase; letter-spacing: 0.5px; margin: 0 0 16px; }}
  .invoice-row {{ display: flex; justify-content: space-between; padding: 6px 0; }}
  .invoice-label {{ color: #8b8f9a; font-size: 14px; }}
  .invoice-value {{ color: #ffffff; font-size: 14px; font-weight: 600; }}
  .footer {{ background: #1a1d27; padding: 28px 40px; text-align: center; }}
  .footer a {{ color: #3b82f6; text-decoration: none; }}
  .footer .copyright {{ color: #8b8f9a; font-size: 12px; line-height: 18px; margin: 0; }}
  .footer .reply-note {{ color: #8b8f9a; font-size: 13px; margin-top: 16px; }}
</style>
</head>
<body>
<div class="wrapper">
  <!-- Header -->
  <div class="header">
    <h1>We got your email</h1>
    <div class="subtitle">Oklahoma Technology Solutions</div>
  </div>

  <!-- Body -->
  <div class="body">
    <h2>Your invoice has been received</h2>
    <p class="lead">Our system has automatically processed your message.</p>

    <!-- Original email details -->
    <div class="review-section">
      <div class="review-label">Subject</div>
      <div class="review-value">{original_subject}</div>
      <div class="review-label">Date Received</div>
      <div class="review-value">{received_date}</div>
      <div class="review-label">Attachments</div>
      <div class="review-value">{attachment_count} file(s)</div>
    </div>

    <!-- Invoice details -->
    <div class="invoice-section">
      <h3>Invoice Summary</h3>
      <div class="invoice-row">
        <span class="invoice-label">Invoice ID</span>
        <span class="invoice-value">{invoice_id}</span>
      </div>
      <div class="invoice-row">
        <span class="invoice-label">Vendor</span>
        <span class="invoice-value">{vendor}</span>
      </div>
      <div class="invoice-row">
        <span class="invoice-label">Billing Period</span>
        <span class="invoice-value">{billing_period}</span>
      </div>
      <div class="invoice-row">
        <span class="invoice-label">Amount</span>
        <span class="invoice-value">${amount:,.2f}</span>
      </div>
    </div>
  </div>

  <!-- Footer -->
  <div class="footer">
    <p class="copyright">
      <a href="https://oktechsol.com">Oklahoma Technology Solutions</a><br>
      Partner ID 36024 &middot; https://oktechsol.com
    </p>
    <p class="reply-note">
      This is an automated message. If you believe this was received in error, simply reply to this email.
    </p>
  </div>
</div>
</body>
</html>
"""


def send_reply(
    to_addr: str,
    original_subject: str,
    invoice_id: str,
    vendor: str,
    amount: float,
    billing_period: str,
    received_date: str = "",
    attachment_count: int = 1,
):
    """Send a confirmation reply email (HTML + plain text).

    Args:
        to_addr:          Recipient email address.
        original_subject: Subject of the original invoice email.
        invoice_id:       The parsed invoice ID.
        vendor:           Vendor name.
        amount:           Outstanding balance or new charges.
        billing_period:   Billing period string.
        received_date:    Human-readable date the email was received.
        attachment_count: Number of PDF attachments processed.
    """
    if not GMAIL_ADDRESS or not GMAIL_APP_PASSWORD:
        log.warning("Cannot send reply — Gmail credentials not configured")
        return

    if not to_addr:
        log.warning("Cannot send reply — no recipient address")
        return

    # Build subject
    reply_subject = f"Re: {original_subject}" if original_subject else "Your invoice has been received"

    # Template context
    ctx = dict(
        original_subject=original_subject or "N/A",
        received_date=received_date or "N/A",
        attachment_count=attachment_count,
        invoice_id=invoice_id or "N/A",
        vendor=vendor or "N/A",
        billing_period=billing_period or "N/A",
        amount=amount or 0,
    )

    # Build multipart message
    msg = MIMEMultipart("alternative")
    msg["Subject"] = reply_subject
    msg["From"] = f"Oklahoma Technology Solutions <{GMAIL_ADDRESS}>"
    msg["To"] = to_addr
    msg["Reply-To"] = GMAIL_ADDRESS

    plain = PLAIN_BODY.format(**ctx)
    html = HTML_BODY.format(**ctx)

    msg.attach(MIMEText(plain, "plain", "utf-8"))
    msg.attach(MIMEText(html, "html", "utf-8"))

    try:
        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as smtp:
            smtp.login(GMAIL_ADDRESS, GMAIL_APP_PASSWORD)
            smtp.sendmail(GMAIL_ADDRESS, [to_addr], msg.as_string())
        log.info("Reply sent to %s for invoice %s", to_addr, invoice_id)
    except Exception as e:
        log.error("Failed to send reply to %s: %s", to_addr, e)


def extract_reply_address(from_header: str) -> str:
    """Extract a clean email address from a From header.

    Handles formats like:
        "Name" <email@domain.com>
        Name <email@domain.com>
        email@domain.com
    """
    name, addr = email.utils.parseaddr(from_header)
    if addr:
        return addr

    # Fallback: bare email regex
    m = re.search(r"[\w._%+\-]+@[\w.\-]+\.[a-zA-Z]{2,}", from_header)
    return m.group(0) if m else ""
