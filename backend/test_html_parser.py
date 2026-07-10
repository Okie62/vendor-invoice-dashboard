"""
Tests for the HTML invoice parser (backlog #18).

Tests Extra Space Storage HTML receipt parsing with a sample that
mimics the structure of real forwarded HTML receipts.
"""
import sys
import os
import pytest

sys.path.insert(0, os.path.dirname(__file__))

from pdf_parser import ParsedInvoice
from html_parser import parse_html_invoice, _parse_extraspace


# ---------------------------------------------------------------------------
# Sample: Extra Space Storage HTML receipt (tag-stripped plain text)
# extracted from the real email seq 183 in the monitored mailbox.
# Personal info (full account numbers, addresses) redacted.
# ---------------------------------------------------------------------------

EXTRASPACE_PLAINTEXT_SAMPLE = """\

From: Extra Space Storage <extraspace@email.extraspace.com>
Reply-To: "noreply@email.extraspace.com" <noreply@email.extraspace.com>
Date: Friday, July 10, 2026 at 12:47 PM
To: Jay Wade <jay@OKTechSol.com>
Subject: Your receipt from Extra Space Storage

YOUR RECEIPT Hi Jay lamar, Your automatic payment has been processed. Your next automatic payment will be processed on 7/24/2026. You can visit your My Account portal to see transaction details. VIEW


Caution: External (extraspace@email.extraspace.com)
Sensitive Content



[EXTRA SPACE STORAGE]




 YOUR RECEIPT



 Hi Jay lamar,

 Your automatic payment has been processed. Your next automatic payment will be processed on 7/24/2026. You can visit your My Account portal to see transaction details.

 Transaction Number: 381091629
 Payment Date: 07/09/2026
 Unit: F277
 Payment Total: $186.20

 Next payment due on: 7/24/2026

""".lstrip("\n")

# A minimal HTML sample that mimics the key receipt structure
EXTRASPACE_HTML_SAMPLE = """\
<html><body>
<div>
<div>
<p>YOUR RECEIPT Hi Jay lamar, Your automatic payment has been processed.</p>
</div>
<table>
<tr><td><strong>Transaction Number:</strong></td><td>381091629</td></tr>
<tr><td><strong>Payment Date:</strong></td><td>07/09/2026</td></tr>
<tr><td><strong>Unit:</strong></td><td>F277</td></tr>
<tr><td><strong>Payment Total:</strong></td><td><strong>$186.20</strong></td></tr>
<tr><td>Next payment due on:</td><td>7/24/2026</td></tr>
</table>
</div>
</body></html>
"""


class TestExtraSpaceParser:
    def test_parses_invoice_id_from_plaintext(self):
        result = _parse_extraspace(EXTRASPACE_HTML_SAMPLE, EXTRASPACE_PLAINTEXT_SAMPLE)
        assert result.invoice_id == "381091629"

    def test_parses_vendor(self):
        result = _parse_extraspace(EXTRASPACE_HTML_SAMPLE, EXTRASPACE_PLAINTEXT_SAMPLE)
        assert result.vendor == "Extra Space Storage"

    def test_parses_invoice_date(self):
        result = _parse_extraspace(EXTRASPACE_HTML_SAMPLE, EXTRASPACE_PLAINTEXT_SAMPLE)
        assert result.invoice_date == "07/09/2026"

    def test_parses_billing_period(self):
        result = _parse_extraspace(EXTRASPACE_HTML_SAMPLE, EXTRASPACE_PLAINTEXT_SAMPLE)
        assert "07/09/2026" in result.billing_period
        assert "7/24/2026" in result.billing_period

    def test_parses_amount(self):
        result = _parse_extraspace(EXTRASPACE_HTML_SAMPLE, EXTRASPACE_PLAINTEXT_SAMPLE)
        assert result.new_charges == 186.20
        assert result.outstanding_balance == 0  # paid in full

    def test_parses_payment_received(self):
        result = _parse_extraspace(EXTRASPACE_HTML_SAMPLE, EXTRASPACE_PLAINTEXT_SAMPLE)
        assert result.payment_received == 186.20

    def test_parses_customer_name(self):
        result = _parse_extraspace(EXTRASPACE_HTML_SAMPLE, EXTRASPACE_PLAINTEXT_SAMPLE)
        assert "Jay" in result.customers[0]["name"]

    def test_parses_unit_as_account(self):
        result = _parse_extraspace(EXTRASPACE_HTML_SAMPLE, EXTRASPACE_PLAINTEXT_SAMPLE)
        assert result.customers[0]["account_id"] == "F277"

    def test_parses_line_items(self):
        result = _parse_extraspace(EXTRASPACE_HTML_SAMPLE, EXTRASPACE_PLAINTEXT_SAMPLE)
        assert len(result.line_items) >= 1
        li = result.line_items[0]
        assert "F277" in li["item"]
        assert li["amount"] == 186.20
        assert li["type"] == "payment"

    def test_not_credit_memo(self):
        result = _parse_extraspace(EXTRASPACE_HTML_SAMPLE, EXTRASPACE_PLAINTEXT_SAMPLE)
        assert result.is_credit_memo is False


class TestParseHtmlInvoiceDispatch:
    def test_routes_by_vendor_name(self):
        result = parse_html_invoice(EXTRASPACE_HTML_SAMPLE, EXTRASPACE_PLAINTEXT_SAMPLE, "Extra Space Storage")
        assert result.vendor == "Extra Space Storage"
        assert result.invoice_id == "381091629"

    def test_routes_by_vendor_alias(self):
        result = parse_html_invoice(EXTRASPACE_HTML_SAMPLE, EXTRASPACE_PLAINTEXT_SAMPLE, "extraspace")
        assert result.vendor == "Extra Space Storage"

    def test_routes_by_content_detection(self):
        """Should detect Extra Space Storage from the content even if vendor is empty."""
        result = parse_html_invoice(EXTRASPACE_HTML_SAMPLE, EXTRASPACE_PLAINTEXT_SAMPLE, "Unknown")
        assert result.vendor == "Extra Space Storage"

    def test_raises_value_error_for_unknown_vendor(self):
        """Should raise ValueError when no parser matches."""
        unknown_html = "<html><body>Some random content</body></html>"
        unknown_text = "This is not an invoice"
        with pytest.raises(ValueError, match="Unknown HTML invoice format"):
            parse_html_invoice(unknown_html, unknown_text, "Nonexistent Corp")

# --- Regression: real forwarded email uses a COLUMNAR table layout ---
# Outlook flattens the receipt table to all labels first, then all values:
REAL_COLUMNAR_TEXT = """
Hi Jay lamar,
Thank you, Your Extra Space Storage Team
YOUR RECEIPT
Transaction Number: Payment Date: Unit: Payment Total: Next payment due on:
381091629 07/09/2026 F277 $186.20 7/24/2026
YOUR FACILITY Address 5802 NW 164th St Edmond, OK 73013
"""


class TestColumnarLayout:
    def test_columnar_transaction_number(self):
        p = parse_html_invoice("", REAL_COLUMNAR_TEXT, "Extra Space Storage")
        assert p.invoice_id == "381091629"

    def test_columnar_amount(self):
        p = parse_html_invoice("", REAL_COLUMNAR_TEXT, "Extra Space Storage")
        assert p.new_charges == 186.20
        assert p.payment_received == 186.20

    def test_columnar_date_and_period(self):
        p = parse_html_invoice("", REAL_COLUMNAR_TEXT, "Extra Space Storage")
        assert p.invoice_date == "07/09/2026"
        assert p.billing_period == "07/09/2026 - 7/24/2026"

    def test_columnar_unit(self):
        p = parse_html_invoice("", REAL_COLUMNAR_TEXT, "Extra Space Storage")
        assert p.customers[0]["account_id"] == "F277"
