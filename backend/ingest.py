"""
Invoice ingestion pipeline.

1. Poll Gmail for unseen emails with PDF attachments
2. Extract vendor name from email metadata
3. Parse PDF to extract invoice data
4. Store PDF to filesystem: data/invoices/{vendor}/{filename}
5. Insert invoice data into SQLite database
6. Mark email as seen
7. Log to processed_emails table
"""

import logging
import re
from datetime import datetime
from pathlib import Path

from config import INVOICE_DIR
from db import get_db, init_db
from email_poller import connect_imap, fetch_unseen_emails, mark_seen
from email_sender import send_reply, extract_reply_address
from pdf_parser import parse_pdf, ParsedInvoice
from vendor_extractor import extract_vendor

log = logging.getLogger(__name__)


def run_ingestion():
    """Main entry point — poll, parse, store. Returns count of processed emails."""
    init_db()
    conn = get_db()

    try:
        imap = connect_imap()
    except Exception as e:
        log.error(f"IMAP connection failed: {e}")
        conn.close()
        return 0

    emails = fetch_unseen_emails(imap)

    if not emails:
        log.info("No new emails with PDF attachments.")
        imap.logout()
        conn.close()
        return 0

    processed = 0
    for email_data in emails:
        try:
            process_email(conn, email_data)
            mark_seen(imap, email_data["imap_id"])
            processed += 1
        except Exception as e:
            log.error(f"Failed to process email {email_data['message_id']}: {e}")

    imap.logout()
    conn.close()
    log.info(f"Processed {processed} email(s).")
    return processed


def process_email(conn, email_data: dict):
    """Process a single email: extract vendor, parse PDF, store."""

    # Check if already processed
    existing = conn.execute(
        "SELECT 1 FROM processed_emails WHERE message_id = ?",
        (email_data["message_id"],)
    ).fetchone()
    if existing:
        log.info(f"Email {email_data['message_id']} already processed — skipping.")
        return

    # Extract vendor from email metadata
    vendor_name, confident = extract_vendor(
        email_data["subject"], email_data.get("body_text", ""), email_data["from"]
    )
    log.info(f"Vendor: {vendor_name} (confident={confident})")

    # Ensure vendor exists in DB
    vendor_id = ensure_vendor(conn, vendor_name, email_data["from"])

    # Process each PDF attachment
    parsed_invoices = []  # track for reply
    for att in email_data["attachments"]:
        # Save PDF to filesystem
        pdf_dir = INVOICE_DIR / vendor_name
        pdf_dir.mkdir(parents=True, exist_ok=True)
        pdf_path = pdf_dir / att["filename"]
        pdf_path.write_bytes(att["bytes"])
        log.info(f"Saved PDF: {pdf_path}")

        # Parse the PDF
        try:
            parsed = parse_pdf(str(pdf_path))
        except ValueError as e:
            log.warning(f"Could not parse {att['filename']}: {e} — storing as unstructured.")
            store_unparsed_invoice(conn, vendor_id, email_data, str(pdf_path))
            continue

        # Store in database
        store_invoice(
            conn, vendor_id, parsed, str(pdf_path),
            email_data["message_id"], source="email"
        )
        parsed_invoices.append(parsed)

    # Send confirmation reply
    if parsed_invoices:
        reply_addr = extract_reply_address(email_data.get("from", ""))
        if reply_addr:
            # Use first parsed invoice for the reply summary
            p = parsed_invoices[0]
            send_reply(
                to_addr=reply_addr,
                original_subject=email_data.get("subject", ""),
                invoice_id=p.invoice_id,
                vendor=vendor_name,
                amount=p.outstanding_balance or p.new_charges,
                billing_period=p.billing_period,
                received_date=email_data.get("received_date", ""),
                attachment_count=len(email_data["attachments"]),
            )
        else:
            log.warning("No reply address found in From header — skipping reply")

    # Log to processed_emails
    conn.execute(
        "INSERT OR REPLACE INTO processed_emails "
        "(message_id, vendor_name, filename, processed_at) "
        "VALUES (?, ?, ?, datetime('now'))",
        (email_data["message_id"], vendor_name, email_data["attachments"][0]["filename"])
    )
    conn.commit()


def ensure_vendor(conn, name: str, from_header: str) -> int:
    """Get or create a vendor record."""
    row = conn.execute("SELECT id FROM vendors WHERE name = ?", (name,)).fetchone()
    if row:
        return row["id"]
    domain_match = re.search(r"@([\w.-]+)", from_header)
    domain = domain_match.group(1) if domain_match else ""
    cursor = conn.execute(
        "INSERT INTO vendors (name, email_domain) VALUES (?, ?)",
        (name, domain)
    )
    conn.commit()
    return cursor.lastrowid


def store_invoice(conn, vendor_id: int, parsed: ParsedInvoice, pdf_path: str,
                  email_msg_id: str, source: str):
    """Insert an invoice and all its customers/line items into the DB."""

    # Insert or replace invoice
    conn.execute("""
        INSERT OR REPLACE INTO invoices
        (id, vendor_id, billing_period, is_credit_memo, references_invoice,
         partner_name, partner_id, partner_username,
         previous_balance, credit_card_surcharges, payment_received,
         new_charges, outstanding_balance, source, email_message_id, pdf_path)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        parsed.invoice_id, vendor_id, parsed.billing_period,
        int(parsed.is_credit_memo), parsed.references_invoice,
        parsed.partner_name, parsed.partner_id, parsed.partner_username,
        parsed.previous_balance, parsed.credit_card_surcharges,
        parsed.payment_received, parsed.new_charges,
        parsed.outstanding_balance, source, email_msg_id, pdf_path
    ))

    # Delete old customers/line_items if re-processing
    conn.execute("DELETE FROM customers WHERE invoice_id = ?", (parsed.invoice_id,))
    conn.execute("DELETE FROM line_items WHERE invoice_id = ?", (parsed.invoice_id,))

    # Insert customers
    for c in parsed.customers:
        conn.execute(
            "INSERT INTO customers (invoice_id, name, account_id, partner_id, total) "
            "VALUES (?, ?, ?, ?, ?)",
            (parsed.invoice_id, c["name"], c["account_id"], c["partner_id"], c["total"])
        )

    # Insert line items
    for li in parsed.line_items:
        conn.execute(
            "INSERT INTO line_items "
            "(invoice_id, customer_name, date, item, type, qty, unit_price, amount) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (parsed.invoice_id, li["customer"], li["date"], li["item"],
             li["type"], li["qty"], li["unit_price"], li["amount"])
        )

    conn.commit()
    log.info(
        f"Stored invoice {parsed.invoice_id}: "
        f"{len(parsed.customers)} customers, {len(parsed.line_items)} line items"
    )


def store_unparsed_invoice(conn, vendor_id: int, email_data: dict, pdf_path: str):
    """Store an invoice we couldn't parse (non-Intermedia vendor, etc.)."""
    inv_id = f"unparsed_{datetime.now().strftime('%Y%m%d%H%M%S')}"
    conn.execute("""
        INSERT INTO invoices
        (id, vendor_id, source, email_message_id, pdf_path, new_charges, outstanding_balance)
        VALUES (?, ?, 'email_unparsed', ?, ?, 0, 0)
    """, (inv_id, vendor_id, email_data["message_id"], pdf_path))
    conn.commit()
    log.info(f"Stored unparsed invoice {inv_id} (PDF at {pdf_path})")
