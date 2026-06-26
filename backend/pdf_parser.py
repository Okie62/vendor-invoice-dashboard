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
