"""
HTML invoice/receipt parser for vendor invoice dashboard.

Parses HTML invoice emails that arrive without PDF attachments.
Uses BeautifulSoup to extract structured data from HTML tables.

Currently supports:
  - Extra Space Storage HTML receipts (transaction number, date, amount, unit)

Extend by adding functions to VENDOR_HTML_PARSERS and registering parse logic.
"""

import logging
import re
from typing import Optional

from pdf_parser import ParsedInvoice

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Vendor HTML parser registry — add new vendors here
# ---------------------------------------------------------------------------
VENDOR_HTML_PARSERS = {
    "Extra Space Storage": "_parse_extraspace",
    "extraspace": "_parse_extraspace",
}


def parse_html_invoice(html_body: str, plain_text: str, vendor_name: str) -> ParsedInvoice:
    """Parse an HTML body as an invoice, returning a ParsedInvoice.

    Args:
        html_body: Raw HTML content of the email body.
        plain_text: Tag-stripped plain text of the email body.
        vendor_name: The extracted vendor name (for routing to the right parser).

    Returns:
        ParsedInvoice with extracted fields.

    Raises:
        ValueError if the HTML format is unrecognized.
    """
    # Determine which parser to use based on vendor_name
    parser_key = VENDOR_HTML_PARSERS.get(vendor_name) or VENDOR_HTML_PARSERS.get(vendor_name.lower())
    if parser_key:
        parser_func = globals().get(parser_key)
        if parser_func:
            return parser_func(html_body, plain_text)

    # Fall back to content-based detection
    text_lower = (html_body + "\n" + plain_text).lower()

    if "extra space storage" in text_lower or "extraspace" in text_lower:
        return _parse_extraspace(html_body, plain_text)

    raise ValueError(f"Unknown HTML invoice format for vendor '{vendor_name}' — no parser matched")


def _parse_extraspace(html_body: str, plain_text: str) -> ParsedInvoice:
    """Parse an Extra Space Storage HTML receipt.

    The receipt arrives as a forwarded HTML email. Key fields are in a table:
      Transaction Number: 381091629
      Payment Date: 07/09/2026
      Unit: F277
      Payment Total: $186.20
      Next payment due on: 7/24/2026

    The plain text version (tag-stripped) is easier to work with since the
    HTML is complex Outlook-generated formatting.

    Args:
        html_body: Raw HTML (not used directly — we work from plain text).
        plain_text: Tag-stripped plain text version.

    Returns:
        ParsedInvoice with extracted fields.
    """
    text = plain_text

    # --- Receipt / Transaction ID ---
    # The plain text has structure from the email body
    # Transaction Number and values are on adjacent lines in the HTML table
    # Try extracting from the text: look for "Transaction Number:" then a number
    tx_match = re.search(r"Transaction\s*Number[:\s]*(\d+)", text, re.IGNORECASE)
    invoice_id = tx_match.group(1) if tx_match else ""

    # Fallback: look for the transaction number in the raw HTML
    if not invoice_id:
        tx_match = re.search(r"Transaction Number[^<]*?(\d+)", html_body, re.IGNORECASE)
        invoice_id = tx_match.group(1) if tx_match else f"extraspace_{re.sub(r'[^0-9]', '', plain_text)[:8] or 'unknown'}"

    # --- Payment Date ---
    date_match = re.search(r"Payment\s*Date[:\s]*(\d{1,2}/\d{1,2}/\d{4})", text, re.IGNORECASE)
    if not date_match:
        # Look in raw HTML
        date_match = re.search(r"Payment Date[^<]*?(\d{1,2}/\d{1,2}/\d{4})", html_body, re.IGNORECASE)
    invoice_date = date_match.group(1) if date_match else ""

    # --- Next payment / billing ---
    next_pay_match = re.search(r"(?:Next\s*(?:payment|auto)\s*(?:due|payment)(?:\s+on)?[:\s]*)(\d{1,2}/\d{1,2}/\d{4})", text, re.IGNORECASE)
    next_payment_date = next_pay_match.group(1) if next_pay_match else ""

    # Billing period: receipt date to next payment date
    if invoice_date and next_payment_date:
        billing_period = f"{invoice_date} - {next_payment_date}"
    else:
        billing_period = invoice_date or "Unknown"

    # --- Payment Total / Amount ---
    amount_match = re.search(r"Payment\s*Total[:\s]*\$?([\d,.]+)", text, re.IGNORECASE)
    if amount_match:
        amount = float(amount_match.group(1).replace(",", ""))
    else:
        # Look in raw HTML for the bold amount near "Payment Total"
        amount_match = re.search(r"Payment Total[^<]*?\$?([\d,.]+)", html_body, re.IGNORECASE)
        amount = float(amount_match.group(1).replace(",", "")) if amount_match else 0.0

    # --- Unit ---
    unit_match = re.search(r"Unit[:\s]*([A-Za-z0-9]+)", text, re.IGNORECASE)
    unit = unit_match.group(1).strip() if unit_match else ""

    # --- Customer name ---
    customer_match = re.search(r"Hi\s+(.+?),", text, re.IGNORECASE)
    customer_name = customer_match.group(1).strip() if customer_match else ""

    # Build a minimal customer record
    customers = []
    if unit or customer_name:
        customers.append({
            "name": customer_name or "Extra Space Storage Customer",
            "account_id": unit,
            "partner_id": "",
            "total": amount,
        })

    # Build a line item for the payment
    line_items = []
    if amount > 0:
        line_items.append({
            "customer": customer_name or "Extra Space Storage Customer",
            "date": invoice_date,
            "item": f"Storage Unit {unit} - Automatic Payment" if unit else "Storage - Automatic Payment",
            "type": "payment",
            "qty": 1,
            "unit_price": amount,
            "amount": amount,
        })

    return ParsedInvoice(
        invoice_id=invoice_id,
        vendor="Extra Space Storage",
        billing_period=billing_period,
        invoice_date=invoice_date,
        is_credit_memo=False,
        references_invoice=None,
        partner_name="Extra Space Storage",
        partner_id="",
        partner_username="",
        previous_balance=0,
        credit_card_surcharges=0,
        payment_received=amount,
        new_charges=amount,
        outstanding_balance=0,  # paid receipt
        customers=customers,
        line_items=line_items,
    )