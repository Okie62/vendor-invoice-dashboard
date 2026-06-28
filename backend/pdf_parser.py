"""
Universal PDF invoice parser.

Extracts: invoice ID, billing period, summary amounts, customer blocks,
line items (monthly, service charges, credits, taxes), and credit memo details.

Works with:
- Regular Intermedia invoices (multi-page, 23+ customers, 100+ line items)
- Intermedia credit memos (single-page, negative amounts)
- Extensible to other vendors via the VENDOR_PARSERS dict
"""

import re
import logging
from dataclasses import dataclass, field
from typing import Optional

import pymupdf

log = logging.getLogger(__name__)


@dataclass
class ParsedInvoice:
    invoice_id: str
    vendor: str
    billing_period: str
    is_credit_memo: bool = False
    references_invoice: Optional[str] = None
    partner_name: str = ""
    partner_id: str = ""
    partner_username: str = ""
    previous_balance: float = 0
    credit_card_surcharges: float = 0
    payment_received: float = 0
    new_charges: float = 0
    outstanding_balance: float = 0
    customers: list = field(default_factory=list)
    line_items: list = field(default_factory=list)


def parse_pdf(file_path: str) -> ParsedInvoice:
    """Parse a PDF invoice and return a ParsedInvoice."""
    doc = pymupdf.open(file_path)
    full_text = ""
    for page in doc:
        full_text += page.get_text() + "\n"
    doc.close()

    if "barracuda" in full_text.lower():
        return _parse_barracuda(full_text)
    if "intermedia" in full_text.lower() or "OKTechSol" in full_text:
        return _parse_intermedia(full_text)
    raise ValueError("Unknown invoice format — no parser matched")


def _parse_intermedia(full_text: str) -> ParsedInvoice:
    """Parse an Intermedia invoice or credit memo."""
    lines = full_text.split("\n")
    is_credit_memo = bool(re.search(r"credit\s*memo", full_text, re.IGNORECASE))

    # Extract invoice/credit memo number
    inv_match = re.search(r"(?:invoice|credit\s*memo)\s*#?\s*(\d{5,})", full_text, re.IGNORECASE)
    invoice_id = inv_match.group(1) if inv_match else "unknown"

    # Extract billing period
    period_match = re.search(
        r"((?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\s+\d{1,2},\s+\d{4})"
        r"\s*-\s*"
        r"((?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\s+\d{1,2},\s+\d{4})",
        full_text,
    )
    if period_match:
        billing_period = f"{period_match.group(1)} - {period_match.group(2)}"
    elif is_credit_memo:
        date_match = re.search(r"date\s*of\s*issue\s*\n?\s*(\w+\s+\d{1,2},\s*\d{4})", full_text, re.IGNORECASE)
        billing_period = date_match.group(1) if date_match else "Unknown"
    else:
        billing_period = "Unknown"

    # Extract summary amounts
    def _extract_amount(pattern):
        m = re.search(pattern, full_text, re.IGNORECASE)
        if m:
            return float(m.group(1).replace(",", ""))
        return 0.0

    prev_balance = _extract_amount(r"Balance Forward[^$]*\$([\d,.]+)")
    cc_surcharges = _extract_amount(r"Credit Card surcharges[^$]*\$([\d,.]+)")
    payment = _extract_amount(r"Payment received[^$]*\(?\$?([\d,.]+)\)?")
    new_charges = _extract_amount(r"New charges[^$]*\$([\d,.]+)")
    outstanding = _extract_amount(r"Total outstanding balance[^$]*\$([\d,.]+)")

    # For credit memos
    ref_match = re.search(r"for\s*Invoice\s*#?\s*(\d{5,})", full_text, re.IGNORECASE)
    references_invoice = ref_match.group(1) if ref_match else None

    # Parse customers and line items (sequential walk)
    customers = []
    line_items = []
    cur_cust = None
    cur_acct = None
    cur_pid = None
    cur_type = "monthly"

    i = 0
    while i < len(lines):
        line = lines[i].strip()

        # Customer header: "CustomerName (AccountID, PartnerID)"
        cm = re.match(r"(.+?)\s+\(([\w-]+),\s*(\d+)\)$", line)
        if cm:
            cur_cust = cm.group(1).strip()
            cur_acct = cm.group(2)
            cur_pid = cm.group(3)
            if i + 1 < len(lines) and lines[i + 1].strip().startswith("$"):
                total_str = lines[i + 1].strip().replace("$", "").replace(",", "").strip("()")
                try:
                    total = float(total_str)
                    customers.append({
                        "name": cur_cust, "account_id": cur_acct,
                        "partner_id": cur_pid, "total": total
                    })
                    i += 2
                    continue
                except ValueError:
                    pass
            i += 1
            continue

        if line == "Monthly charges":
            cur_type = "monthly"; i += 1; continue
        if line.startswith("Service charges"):
            cur_type = "service_charge"; i += 1; continue
        if line == "Credits":
            cur_type = "credit"; i += 1; continue
        if line == "Taxes":
            cur_type = "tax"; i += 1; continue

        # Date-based line item: Date / Item / Qty / UnitPrice / Amount
        dm = re.match(
            r"((?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\s+\d{1,2},\s+\d{4})$",
            line,
        )
        if dm and cur_cust:
            date = dm.group(1)
            if i + 4 < len(lines):
                item = lines[i + 1].strip()
                try:
                    qty = int(lines[i + 2].strip().replace(",", ""))
                except ValueError:
                    i += 1; continue
                up_line = lines[i + 3].strip()
                am_line = lines[i + 4].strip()
                if "$" not in up_line and "(" not in up_line:
                    i += 1; continue
                if "$" not in am_line and "(" not in am_line:
                    i += 1; continue
                up = float(up_line.replace("$", "").replace(",", "").strip("()"))
                am = float(am_line.replace("$", "").replace(",", "").strip("()"))
                if am_line.startswith("("):
                    am = -am
                if up_line.startswith("("):
                    up = -up
                iname = item
                if cur_type == "tax" and i + 5 < len(lines) and "level" in lines[i + 5]:
                    iname = f"{item} ({lines[i + 5].strip()})"
                line_items.append({
                    "customer": cur_cust, "date": date, "item": iname,
                    "type": cur_type, "qty": qty, "unit_price": up, "amount": am
                })
                i += 5
                continue

        # Tax line item (no date/qty): "E-911" / "State/Province level" / "$1.31"
        if cur_type == "tax" and cur_cust:
            if (i + 2 < len(lines)
                    and "level" in lines[i + 1].strip()
                    and lines[i + 2].strip().startswith("$")):
                tax_name = line
                tax_level = lines[i + 1].strip()
                am_str = lines[i + 2].strip().replace("$", "").replace(",", "").strip("()")
                am = float(am_str)
                if lines[i + 2].strip().startswith("("):
                    am = -am
                line_items.append({
                    "customer": cur_cust, "date": billing_period.split(" - ")[0],
                    "item": f"{tax_name} ({tax_level})", "type": "tax",
                    "qty": 1, "unit_price": am, "amount": am
                })
                i += 3
                continue

        i += 1

    return ParsedInvoice(
        invoice_id=invoice_id,
        vendor="Intermedia",
        billing_period=billing_period,
        is_credit_memo=is_credit_memo,
        references_invoice=references_invoice,
        partner_name="Oklahoma Technology Solutions",
        partner_id="36024",
        partner_username="OKTechSol",
        previous_balance=prev_balance,
        credit_card_surcharges=cc_surcharges,
        payment_received=payment,
        new_charges=new_charges,
        outstanding_balance=outstanding,
        customers=customers,
        line_items=line_items,
    )


def _parse_barracuda(full_text: str) -> ParsedInvoice:
    """Parse a Barracuda Networks invoice.

    Format: PDF text with sections like:
      Invoice #INV26514789
      Date: 4/29/2026
      Bill To: Jay Wade / Oklahoma Technology Solutions
      Item Description / End User / Quantity / Rate / Price
      [product blocks with end users, seat counts, rates]
      Subtotal / Tax Total / Total / Amount Paid / Amount Due
      Start Date / End Date / Terms / Due Date
    """
    lines = [l.strip() for l in full_text.split("\n") if l.strip()]

    # Invoice ID: "#INV26514789" or "INV26514789" at top
    inv_match = re.search(r"#?(INV\d+)", full_text)
    invoice_id = inv_match.group(1) if inv_match else "unknown"

    # Date: appears after invoice number, e.g. "4/29/2026"
    date_match = re.search(r"#?INV\d+\s*\n\s*(\d{1,2}/\d{1,2}/\d{4})", full_text)
    invoice_date = date_match.group(1) if date_match else ""

    # Billing period from Start Date / End Date
    start_match = re.search(r"Start Date\s*\n\s*End Date\s*\n\s*Terms\s*\n\s*Due Date\s*\n\s*(\d{1,2}/\d{1,2}/\d{4})\s*\n\s*(\d{1,2}/\d{1,2}/\d{4})", full_text)
    if start_match:
        billing_period = f"{start_match.group(1)} - {start_match.group(2)}"
    else:
        billing_period = invoice_date or "Unknown"

    # Summary amounts
    def _extract_amount(pattern):
        m = re.search(pattern, full_text, re.IGNORECASE)
        if m:
            return float(m.group(1).replace(",", ""))
        return 0.0

    new_charges = _extract_amount(r"Subtotal\s*\n?\s*\$([\d,.]+)")
    tax = _extract_amount(r"Tax\s*Total\s*\n?\s*\$([\d,.]+)")
    total = _extract_amount(r"(?:^|\n)\s*Total\s*\n?\s*\$([\d,.]+)")
    payment = _extract_amount(r"Amount\s*Paid\s*\n?\s*\$([\d,.]+)")
    outstanding = _extract_amount(r"Amount\s*Due\s*\n?\s*\$([\d,.]+)")

    # Parse line items: product blocks with end users
    # Pattern: [Product Name] / [End User (account)] / S/N: xxx / N Seat(s) / [purchased] / $rate / $price
    customers = []
    line_items = []
    cur_product = ""
    cur_end_user = ""
    cur_account = ""
    cur_serial = ""
    cur_seats = 0

    i = 0
    while i < len(lines):
        line = lines[i]

        # Product header: "Barracuda Total Email Protection MSP" or "Advanced Email Protection Plan MSP"
        if "MSP" in line and ("Protection" in line or "Barracuda" in line):
            cur_product = line
            i += 1
            continue

        # End user line: "OKTechSol - Internal (ots_ts)" etc.
        eu_match = re.match(r"(.+?)\s*\(([\w-]+)\)$", line)
        if eu_match and i + 1 < len(lines) and lines[i + 1].startswith("S/N:"):
            cur_end_user = eu_match.group(1).strip()
            cur_account = eu_match.group(2)
            cur_serial = lines[i + 1].replace("S/N:", "").strip()
            i += 2
            continue

        # Seat count: "1 Seat(s)" or "761 Seat(s)"
        seat_match = re.match(r"(\d+)\s*Seat\(s\)", line)
        if seat_match:
            cur_seats = int(seat_match.group(1))
            i += 1
            continue

        # Price line: "$6,560.00" after rate
        # Check if this is a purchased quantity followed by rate and price
        # Pattern: [purchased_qty] / $rate / $price
        if (re.match(r"^\d+$", line) and i + 2 < len(lines)
                and "$" in lines[i + 1] and "$" in lines[i + 2]):
            purchased = int(line)
            rate_str = lines[i + 1].replace("$", "").replace(",", "").strip("()")
            price_str = lines[i + 2].replace("$", "").replace(",", "").strip("()")
            try:
                rate = float(rate_str)
                price = float(price_str)
                line_items.append({
                    "customer": cur_end_user or cur_product,
                    "date": billing_period.split(" - ")[0] if " - " in billing_period else invoice_date,
                    "item": f"{cur_product} (purchased: {purchased}, S/N: {cur_serial})",
                    "type": "service",
                    "qty": cur_seats,
                    "unit_price": rate,
                    "amount": price,
                })
                customers.append({
                    "name": cur_end_user or cur_product,
                    "account_id": cur_account,
                    "partner_id": cur_serial,
                    "total": price,
                })
                i += 3
                continue
            except ValueError:
                pass

        # Overdue section: "Overage Seat(s): N" / N / $rate / $price
        overage_match = re.match(r"Overage Seat\(s\):\s*(\d+)", line)
        if overage_match:
            overage_seats = int(overage_match.group(1))
            if i + 3 < len(lines) and re.match(r"^\d+$", lines[i + 1]):
                rate_str = lines[i + 2].replace("$", "").replace(",", "").strip("()") if "$" in lines[i + 2] else "0"
                price_str = lines[i + 3].replace("$", "").replace(",", "").strip("()") if "$" in lines[i + 3] else "0"
                try:
                    rate = float(rate_str)
                    price = float(price_str)
                    line_items.append({
                        "customer": cur_end_user or cur_product,
                        "date": billing_period.split(" - ")[0] if " - " in billing_period else invoice_date,
                        "item": f"{cur_product} Overage (seats: {overage_seats})",
                        "type": "overage",
                        "qty": overage_seats,
                        "unit_price": rate,
                        "amount": price,
                    })
                    i += 4
                    continue
                except ValueError:
                    pass

        i += 1

    # Username: "ots1" appears near the end
    username_match = re.search(r"Username\s*\n\s*PO#?\s*\n\s*(\S+)", full_text)

    return ParsedInvoice(
        invoice_id=invoice_id,
        vendor="Barracuda",
        billing_period=billing_period,
        is_credit_memo=False,
        references_invoice=None,
        partner_name="Oklahoma Technology Solutions",
        partner_id="",
        partner_username=username_match.group(1) if username_match else "",
        previous_balance=0,
        credit_card_surcharges=0,
        payment_received=payment,
        new_charges=total,
        outstanding_balance=outstanding,
        customers=customers,
        line_items=line_items,
    )
