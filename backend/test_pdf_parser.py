"""
Tests for the PDF invoice parser (backlog #18).

Tests Intermedia and Barracuda parsing with sample text snippets
that mimic the structure of real invoice PDFs.
"""
import sys
import os
import pytest

sys.path.insert(0, os.path.dirname(__file__))

from pdf_parser import parse_pdf, ParsedInvoice, _parse_intermedia, _parse_barracuda, _parse_flyover, _parse_contractor


# --- Sample text snippets (mimic real PDF output) ---

INTERMEDIA_SAMPLE = """
Invoice #1234567
Billing Period: Jun 01, 2026 - Jun 30, 2026
Partner: Oklahoma Technology Solutions
Partner ID: 36024
Partner Username: OKTechSol

Balance Forward          $1,234.56
Credit Card surcharges   $12.34
Payment received         $1,000.00
New charges              $2,345.67
Total outstanding balance $2,592.57

Customer A (acct001, 36024)
$100.00

Monthly charges
Jun 01, 2026
Exchange Pro
5
$20.00
$100.00

Customer B (acct002, 36024)
$50.00
"""

BARRACUDA_SAMPLE = """
Invoice #INV26514789
4/29/2026

Bill To: Jay Wade
Oklahoma Technology Solutions

Barracuda Total Email Protection MSP
OKTechSol - Internal (ots_ts)
S/N: A123456
761 Seat(s)
761
$8.62
$6,560.00

Subtotal
$6,560.00
Tax Total
$0.00
Total
$6,560.00
Amount Paid
$0.00
Amount Due
$6,560.00

Start Date
End Date
Terms
Due Date
4/1/2026
6/30/2026
Net 30
5/29/2026

Username
PO#
ots1
"""


class TestIntermediaParser:
    def test_parses_invoice_id(self):
        result = _parse_intermedia(INTERMEDIA_SAMPLE)
        assert result.invoice_id == "1234567"

    def test_parses_vendor(self):
        result = _parse_intermedia(INTERMEDIA_SAMPLE)
        assert result.vendor == "Intermedia"

    def test_parses_billing_period(self):
        result = _parse_intermedia(INTERMEDIA_SAMPLE)
        assert "Jun 01, 2026" in result.billing_period
        assert "Jun 30, 2026" in result.billing_period

    def test_parses_invoice_date(self):
        result = _parse_intermedia(INTERMEDIA_SAMPLE)
        assert result.invoice_date != ""
        assert "2026" in result.invoice_date

    def test_parses_summary_amounts(self):
        result = _parse_intermedia(INTERMEDIA_SAMPLE)
        assert result.previous_balance == 1234.56
        assert result.credit_card_surcharges == 12.34
        assert result.payment_received == 1000.00
        assert result.new_charges == 2345.67
        assert result.outstanding_balance == 2592.57

    def test_parses_customers(self):
        result = _parse_intermedia(INTERMEDIA_SAMPLE)
        assert len(result.customers) >= 1
        assert result.customers[0]["name"] == "Customer A"
        assert result.customers[0]["account_id"] == "acct001"

    def test_parses_line_items(self):
        result = _parse_intermedia(INTERMEDIA_SAMPLE)
        assert len(result.line_items) >= 1
        li = result.line_items[0]
        assert li["customer"] == "Customer A"
        assert "Exchange" in li["item"]
        assert li["qty"] == 5

    def test_not_credit_memo(self):
        result = _parse_intermedia(INTERMEDIA_SAMPLE)
        assert result.is_credit_memo is False


class TestBarracudaParser:
    def test_parses_invoice_id(self):
        result = _parse_barracuda(BARRACUDA_SAMPLE)
        assert result.invoice_id == "INV26514789"

    def test_parses_vendor(self):
        result = _parse_barracuda(BARRACUDA_SAMPLE)
        assert result.vendor == "Barracuda"

    def test_parses_invoice_date(self):
        result = _parse_barracuda(BARRACUDA_SAMPLE)
        assert result.invoice_date == "4/29/2026"

    def test_parses_billing_period(self):
        result = _parse_barracuda(BARRACUDA_SAMPLE)
        assert "4/1/2026" in result.billing_period
        assert "6/30/2026" in result.billing_period

    def test_parses_outstanding(self):
        result = _parse_barracuda(BARRACUDA_SAMPLE)
        assert result.outstanding_balance == 6560.00

    def test_parses_customers(self):
        result = _parse_barracuda(BARRACUDA_SAMPLE)
        assert len(result.customers) >= 1
        assert "OKTechSol" in result.customers[0]["name"]

    def test_parses_line_items(self):
        result = _parse_barracuda(BARRACUDA_SAMPLE)
        assert len(result.line_items) >= 1
        assert "Barracuda" in result.line_items[0]["item"]


class TestParsedInvoiceDataclass:
    def test_defaults(self):
        pi = ParsedInvoice(invoice_id="X", vendor="Test", billing_period="Jan")
        assert pi.is_credit_memo is False
        assert pi.invoice_date == ""
        assert pi.customers == []
        assert pi.line_items == []
        assert pi.previous_balance == 0


FLYOVER_SAMPLE = """
INVOICE
Flyover Software
12220 N MacArthur Blvd Ste F150
Oklahoma City, OK 73162
jay@btabs.com
+1 (405) 229-9700
Bill to
Billing Department
Paluxy Energy Land Services
Ship to
Billing Department
Paluxy Energy Land Services
Invoice details
Invoice no.: 250541
Terms: Net 30
Invoice date: 05/31/2026
Due date: 06/30/2026
#
Product or service
Description
Qty
Rate
Amount
1.
BTABS Users
Monthly charge for active BTABS users
52
$10.00
$520.00
Ways to pay
Total
$520.00
Payment
-$520.00
Balance due
$0.00
Paid in Full
"""


CONTRACTOR_SAMPLE = """
  \nInvoice # 247 \nDate: 06/16/26  Billing Period: 06/01/26 – 06/15/26 \nBill To \nFor \nJay Wade \nContractor Services \n12220 N. MacArthur Blvd., Oklahoma City, OK 73162 \n405-229-9700 \nAmount \nServices - 80 hours \n$2,106.71 \nServices Dates: 06/01/26 - 06/05/26, 06/08/26 – 06/12/26 and 06/15/26  \n        \nCustomer Service, Office Management and Billing \nItem Description \nJennifer Determan \n3024 Regency Ct, Oklahoma City, OK, \n73120\n405-833-5366\n\nSubtotal \nTax Rate \nOther Costs \nTotal Cost \n$2,106.71 \n$2,106.71 \n
"""


class TestFlyoverParser:
    def test_parses_invoice_id(self):
        result = _parse_flyover(FLYOVER_SAMPLE)
        assert result.invoice_id == "250541"

    def test_parses_vendor(self):
        result = _parse_flyover(FLYOVER_SAMPLE)
        assert result.vendor == "Flyover Software"

    def test_parses_invoice_date(self):
        result = _parse_flyover(FLYOVER_SAMPLE)
        assert result.invoice_date == "05/31/2026"

    def test_parses_billing_period(self):
        result = _parse_flyover(FLYOVER_SAMPLE)
        assert "05/31/2026" in result.billing_period
        assert "06/30/2026" in result.billing_period

    def test_parses_total(self):
        result = _parse_flyover(FLYOVER_SAMPLE)
        assert result.new_charges == 520.00

    def test_parses_balance_due(self):
        result = _parse_flyover(FLYOVER_SAMPLE)
        assert result.outstanding_balance == 0.00

    def test_parses_customer(self):
        result = _parse_flyover(FLYOVER_SAMPLE)
        assert len(result.customers) >= 1
        assert "Paluxy" in result.customers[0]["name"]

    def test_parses_line_items(self):
        result = _parse_flyover(FLYOVER_SAMPLE)
        assert len(result.line_items) >= 1
        li = result.line_items[0]
        assert "BTABS" in li["item"]
        assert li["qty"] == 52
        assert li["unit_price"] == 10.00
        assert li["amount"] == 520.00


class TestContractorParser:
    def test_parses_invoice_id(self):
        result = _parse_contractor(CONTRACTOR_SAMPLE)
        assert result.invoice_id == "247"

    def test_parses_vendor(self):
        result = _parse_contractor(CONTRACTOR_SAMPLE)
        assert result.vendor == "Jennifer Determan"

    def test_parses_invoice_date(self):
        result = _parse_contractor(CONTRACTOR_SAMPLE)
        assert result.invoice_date == "06/16/26"

    def test_parses_billing_period(self):
        result = _parse_contractor(CONTRACTOR_SAMPLE)
        assert "06/01/26" in result.billing_period
        assert "06/15/26" in result.billing_period

    def test_parses_amount(self):
        result = _parse_contractor(CONTRACTOR_SAMPLE)
        assert result.new_charges == 2106.71
        assert result.outstanding_balance == 2106.71

    def test_parses_line_items(self):
        result = _parse_contractor(CONTRACTOR_SAMPLE)
        assert len(result.line_items) >= 1
        li = result.line_items[0]
        assert li["qty"] == 80
        assert li["amount"] == 2106.71
        assert "80 hours" in li["item"]

    def test_parses_customer(self):
        result = _parse_contractor(CONTRACTOR_SAMPLE)
        assert len(result.customers) >= 1
        assert "Jay Wade" in result.customers[0]["name"]
