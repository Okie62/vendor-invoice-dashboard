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
    invoice_date: str = ""
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

    text_lower = full_text.lower()

    if "barracuda" in text_lower:
        return _parse_barracuda(full_text)
    if "intermedia" in text_lower or "OKTechSol" in full_text:
        return _parse_intermedia(full_text)
    if "flyover software" in text_lower or "btabs" in text_lower:
        return _parse_flyover(full_text)
    if "contractor services" in text_lower and "jennifer determan" in text_lower:
        return _parse_contractor(full_text)
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
        date_match = re.search(r"date\s*of\s*issue\s*\n?\s*(\w+\s+\d{1,2},\s+\d{4})", full_text, re.IGNORECASE)
        billing_period = date_match.group(1) if date_match else "Unknown"
    else:
        billing_period = "Unknown"

    # Extract invoice date (#9 — column existed but was never populated)
    inv_date_match = re.search(
        r"(?:invoice|credit\s*memo)\s*(?:date|issued)\s*[:\n]\s*"
        r"((?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\s+\d{1,2},\s+\d{4})",
        full_text, re.IGNORECASE
    )
    if not inv_date_match:
        # Fallback: first date in the document near the top
        inv_date_match = re.search(
            r"((?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\s+\d{1,2},\s+\d{4})",
            full_text
        )
    invoice_date = inv_date_match.group(1) if inv_date_match else ""

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
        invoice_date=invoice_date,
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
        invoice_date=invoice_date,
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


def _parse_flyover(full_text: str) -> ParsedInvoice:
    """Parse a Flyover Software / BTABS invoice.

    Format:
      INVOICE
      Flyover Software
      12220 N MacArthur Blvd Ste F150
      Oklahoma City, OK 73162
      jay@btabs.com
      +1 (405) 229-9700
      Bill to / Ship to sections
      Invoice no.: 250541
      Terms: Net 30
      Invoice date: 05/31/2026
      Due date: 06/30/2026
      Line items table: # / Product or service / Description / Qty / Rate / Amount
      Total / Payment / Balance due
    """
    lines = [l.strip() for l in full_text.split("\n") if l.strip()]

    # Invoice ID
    inv_match = re.search(r"Invoice no\.?\s*:?\s*(\d+)", full_text, re.IGNORECASE)
    invoice_id = inv_match.group(1) if inv_match else "unknown"

    # Dates
    date_match = re.search(r"Invoice date\s*:?\s*(\d{1,2}/\d{1,2}/\d{4})", full_text, re.IGNORECASE)
    invoice_date = date_match.group(1) if date_match else ""

    due_match = re.search(r"Due date\s*:?\s*(\d{1,2}/\d{1,2}/\d{4})", full_text, re.IGNORECASE)
    due_date = due_match.group(1) if due_match else ""

    # Billing period = invoice date to due date (or just invoice date)
    if invoice_date and due_date:
        billing_period = f"{invoice_date} - {due_date}"
    else:
        billing_period = invoice_date or "Unknown"

    # Summary amounts
    def _extract_amount(pattern):
        m = re.search(pattern, full_text, re.IGNORECASE)
        if m:
            return float(m.group(1).replace(",", ""))
        return 0.0

    total = _extract_amount(r"Total\s*\n?\s*\$([\d,.]+)")
    payment = _extract_amount(r"Payment\s*\n?\s*-?\$([\d,.]+)")
    balance_due = _extract_amount(r"Balance due\s*\n?\s*\$([\d,.]+)")

    # Bill To — extract customer name (line after "Bill to")
    customer_name = ""
    bill_to_idx = None
    for i, line in enumerate(lines):
        if line.lower() == "bill to":
            # Next non-empty line that isn't "Billing Department" is the customer
            for j in range(i + 1, min(i + 4, len(lines))):
                candidate = lines[j].strip()
                if candidate.lower() == "billing department":
                    continue
                if candidate.lower() == "ship to":
                    break
                customer_name = candidate
                break
            bill_to_idx = i
            break

    # Parse line items: table with # / Product / Description / Qty / Rate / Amount
    # The table appears after the header row containing "Product or service"
    line_items = []
    customers = []

    # Find the start of the line items table
    table_start = None
    for i, line in enumerate(lines):
        if "product or service" in line.lower():
            table_start = i + 1
            break

    if table_start is not None:
        i = table_start
        while i < len(lines):
            line = lines[i]

            # Stop when we hit the total/summary section
            if line.lower() in ("total", "payment", "balance due", "ways to pay", "paid in full"):
                break

            # Line item pattern: "# / Product / Description / Qty / Rate / Amount"
            # In the PDF text these appear as separate lines:
            #   1.
            #   BTABS Users
            #   Monthly charge for active BTABS users
            #   52
            #   $10.00
            #   $520.00
            if re.match(r"^\d+\.$", line):
                # Read the next 5 lines: product, description, qty, rate, amount
                if i + 5 < len(lines) + 1:
                    product = lines[i + 1].strip() if i + 1 < len(lines) else ""
                    description = lines[i + 2].strip() if i + 2 < len(lines) else ""

                    # Qty must be a plain integer
                    qty_str = lines[i + 3].strip() if i + 3 < len(lines) else ""
                    if not re.match(r"^\d+$", qty_str):
                        i += 1
                        continue

                    rate_str = lines[i + 4].strip() if i + 4 < len(lines) else ""
                    amount_str = lines[i + 5].strip() if i + 5 < len(lines) else ""

                    # Rate and amount must contain $
                    if "$" not in rate_str or "$" not in amount_str:
                        i += 1
                        continue

                    try:
                        qty = int(qty_str)
                        rate = float(rate_str.replace("$", "").replace(",", "").strip("()"))
                        amount = float(amount_str.replace("$", "").replace(",", "").strip("()"))

                        if amount_str.startswith("("):
                            amount = -amount

                        li_item = f"{product} ({description})" if description else product
                        line_items.append({
                            "customer": customer_name or "Flyover Software",
                            "date": invoice_date,
                            "item": li_item,
                            "type": "service",
                            "qty": qty,
                            "unit_price": rate,
                            "amount": amount,
                        })
                        i += 6
                        continue
                    except (ValueError, IndexError):
                        pass

            i += 1

    # Create customer block
    if customer_name or line_items:
        customers.append({
            "name": customer_name or "Flyover Software",
            "account_id": "",
            "partner_id": "",
            "total": total,
        })

    return ParsedInvoice(
        invoice_id=invoice_id,
        vendor="Flyover Software",
        billing_period=billing_period,
        invoice_date=invoice_date,
        is_credit_memo=False,
        references_invoice=None,
        partner_name="Flyover Software",
        partner_id="",
        partner_username="",
        previous_balance=0,
        credit_card_surcharges=0,
        payment_received=payment,
        new_charges=total,
        outstanding_balance=balance_due,
        customers=customers,
        line_items=line_items,
    )


def _parse_contractor(full_text: str) -> ParsedInvoice:
    """Parse a Jennifer Determan contractor services invoice.

    Format:
      Invoice # 247
      Date: 06/16/26  Billing Period: 06/01/26 – 06/15/26
      Bill To / For sections
      Jay Wade / Contractor Services
      12220 N. MacArthur Blvd., Oklahoma City, OK 73162
      405-229-9700
      Amount
      Services - 80 hours
      $2,106.71
      Services Dates: 06/01/26 - 06/05/26, 06/08/26 – 06/12/26 and 06/15/26
      Customer Service, Office Management and Billing
      Item Description
      Jennifer Determan
      3024 Regency Ct, Oklahoma City, OK, 73120
      405-833-5366
      --- page 2 ---
      Subtotal / Tax Rate / Other Costs / Total Cost
      $2,106.71
      $2,106.71
    """
    lines = [l.strip() for l in full_text.split("\n") if l.strip()]

    # Invoice ID
    inv_match = re.search(r"Invoice\s*#\s*(\d+)", full_text, re.IGNORECASE)
    invoice_id = inv_match.group(1) if inv_match else "unknown"

    # Date and Billing Period from the header line
    date_match = re.search(r"Date:\s*(\d{1,2}/\d{1,2}/\d{2,4})", full_text, re.IGNORECASE)
    invoice_date = date_match.group(1) if date_match else ""

    period_match = re.search(
        r"Billing Period:\s*(\d{1,2}/\d{1,2}/\d{2,4})\s*[–-]\s*(\d{1,2}/\d{1,2}/\d{2,4})",
        full_text, re.IGNORECASE
    )
    if period_match:
        billing_period = f"{period_match.group(1)} - {period_match.group(2)}"
    else:
        billing_period = invoice_date or "Unknown"

    # Extract amount — the main dollar amount on the invoice
    # "Services - 80 hours" followed by "$2,106.71"
    amount_match = re.search(r"Services\s*-\s*(\d+)\s*hours\s*\n\s*\$([\d,.]+)", full_text, re.IGNORECASE)
    if amount_match:
        hours = int(amount_match.group(1))
        total_amount = float(amount_match.group(2).replace(",", ""))
    else:
        # Fallback: find "Total Cost" followed by amount
        total_match = re.search(r"Total Cost\s*\n?\s*\$([\d,.]+)", full_text, re.IGNORECASE)
        total_amount = float(total_match.group(1).replace(",", "")) if total_match else 0.0
        hours = 0

    # Subtotal and tax
    subtotal_match = re.search(r"Subtotal\s*\n?\s*\$([\d,.]+)", full_text, re.IGNORECASE)
    subtotal = float(subtotal_match.group(1).replace(",", "")) if subtotal_match else total_amount

    tax_match = re.search(r"Tax Rate\s*\n?\s*\$?([\d,.]+)%?", full_text, re.IGNORECASE)
    tax = float(tax_match.group(1).replace(",", "")) if tax_match else 0.0

    other_costs_match = re.search(r"Other Costs\s*\n?\s*\$([\d,.]+)", full_text, re.IGNORECASE)
    other_costs = float(other_costs_match.group(1).replace(",", "")) if other_costs_match else 0.0

    # Services dates
    dates_match = re.search(r"Services Dates:\s*([^\n]+)", full_text, re.IGNORECASE)
    services_dates = dates_match.group(1).strip() if dates_match else ""

    # Description of services
    desc_match = re.search(r"Customer Service,?\s*([^\n]+)", full_text, re.IGNORECASE)
    description = desc_match.group(1).strip() if desc_match else "Contractor Services"

    # Contractor name and address (Item Description section)
    contractor_name = "Jennifer Determan"
    contractor_addr = ""
    contractor_phone = ""
    for i, line in enumerate(lines):
        if "item description" in line.lower():
            # Next line is the contractor name
            if i + 1 < len(lines):
                contractor_name = lines[i + 1].strip()
            if i + 2 < len(lines):
                contractor_addr = lines[i + 2].strip()
            if i + 3 < len(lines):
                contractor_phone = lines[i + 3].strip()
            break

    # Bill To — skip label lines like "For"
    bill_to_name = ""
    for i, line in enumerate(lines):
        if line.lower() == "bill to":
            # Skip label lines ("For", etc.) and take the first real name
            for j in range(i + 1, min(i + 4, len(lines))):
                candidate = lines[j].strip()
                if candidate.lower() in ("for", "ship to", ""):
                    continue
                bill_to_name = candidate
                break
            break

    # Build line item
    line_items = []
    if total_amount > 0:
        item_desc = f"Services - {hours} hours" if hours else "Contractor Services"
        if services_dates:
            item_desc += f" (Dates: {services_dates})"
        line_items.append({
            "customer": bill_to_name or "OKTechSol",
            "date": invoice_date,
            "item": item_desc,
            "type": "service",
            "qty": hours if hours else 1,
            "unit_price": round(total_amount / hours, 2) if hours else total_amount,
            "amount": total_amount,
        })

    # Customer block
    customers = []
    if bill_to_name or line_items:
        customers.append({
            "name": bill_to_name or "OKTechSol",
            "account_id": "",
            "partner_id": "",
            "total": total_amount,
        })

    return ParsedInvoice(
        invoice_id=invoice_id,
        vendor="Jennifer Determan",
        billing_period=billing_period,
        invoice_date=invoice_date,
        is_credit_memo=False,
        references_invoice=None,
        partner_name=contractor_name,
        partner_id="",
        partner_username="",
        previous_balance=0,
        credit_card_surcharges=0,
        payment_received=0,
        new_charges=total_amount,
        outstanding_balance=total_amount,
        customers=customers,
        line_items=line_items,
    )
