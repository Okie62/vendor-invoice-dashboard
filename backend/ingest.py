"""
Invoice ingestion pipeline.

1. Poll Gmail for unseen emails with PDF attachments
2. Extract vendor name from email metadata
3. Parse PDF or HTML body to extract invoice data
4. Store PDF/HTML to filesystem: data/invoices/{vendor}/{filename}
5. Insert invoice data into SQLite database
6. Mark email as seen
7. Log to processed_emails table
8. Detect new formats and create review queue entries
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
from html_parser import parse_html_invoice
from vendor_extractor import extract_vendor
from format_recognition import (
    compute_fingerprint, register_format, is_recognized_format,
    create_review,
)

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
    """Process a single email: extract vendor, parse attachment or HTML body, store."""

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

    attachments = email_data.get("attachments", [])

    if not attachments:
        # No PDF attachments — try HTML body parsing or store as unparsed
        _process_html_only_email(conn, vendor_id, vendor_name, email_data)
    else:
        # Process each PDF attachment
        _process_pdf_attachments(conn, vendor_id, vendor_name, email_data, attachments)


def _process_html_only_email(conn, vendor_id: int, vendor_name: str, email_data: dict):
    """Process an email with no PDF attachments via HTML body parsing."""
    body_html = email_data.get("body_html", "")
    body_text = email_data.get("body_text", "")

    if not body_html:
        log.warning(f"No HTML body in email {email_data['message_id']} — storing as unparsed.")
        inv_id = _store_html_as_unparsed(conn, vendor_id, email_data, body_text, "no_body")
        _notify_unknown_format(vendor_name, "no_body", email_data, "Email has no HTML body")
        if inv_id:
            create_review(conn, inv_id, vendor_id, "no_body")
        return

    # Save HTML body to filesystem
    safe_vendor = re.sub(r"[^a-zA-Z0-9]+", "_", vendor_name).strip("_")
    html_dir = INVOICE_DIR / safe_vendor
    html_dir.mkdir(parents=True, exist_ok=True)

    # Generate a filename from subject/message_id
    safe_subj = re.sub(r"[^a-zA-Z0-9]+", "_", email_data.get("subject", "receipt"))[:40]
    html_filename = f"{safe_subj}_{datetime.now().strftime('%Y%m%d%H%M%S')}.html"
    html_path = html_dir / html_filename
    html_path.write_text(body_html, encoding="utf-8")
    log.info(f"Saved HTML body: {html_path}")

    # Try to parse the HTML body
    try:
        parsed = parse_html_invoice(body_html, body_text, vendor_name)
    except ValueError as e:
        log.warning(f"Could not parse HTML receipt: {e} — storing as unparsed.")
        inv_id = _store_html_as_unparsed(conn, vendor_id, email_data, str(html_path), body_text)
        _notify_unknown_format(vendor_name, html_filename, email_data, str(e))
        if inv_id:
            create_review(conn, inv_id, vendor_id, "no_parser",
                          extracted_data={"vendor": vendor_name, "filename": html_filename})
        return

    # Store parsed invoice
    store_invoice(
        conn, vendor_id, parsed, str(html_path),
        email_data["message_id"], source="email_html"
    )

    # ---- Format recognition for parsed HTML invoices ----
    fp = compute_fingerprint(body_html + "\n" + body_text)
    reg = register_format(conn, vendor_id, fp, "html_parser")
    if reg["is_new"]:
        log.info("New HTML format fingerprint registered for vendor %s", vendor_name)
        create_review(conn, parsed.invoice_id, vendor_id, "new_format",
                      extracted_data={"vendor": vendor_name, "fingerprint": fp})
    # ----------------------------------------------------

    _send_new_invoice_notification(parsed, vendor_name)
    _send_confirmation_reply(email_data, [parsed], vendor_name)

    # Log to processed_emails
    conn.execute(
        "INSERT OR REPLACE INTO processed_emails "
        "(message_id, vendor_name, filename, processed_at) "
        "VALUES (?, ?, ?, datetime('now'))",
        (email_data["message_id"], vendor_name, html_filename)
    )
    conn.commit()


def _process_pdf_attachments(conn, vendor_id, vendor_name, email_data, attachments):
    """Process email with PDF attachments — parse, store, and detect new formats."""
    parsed_invoices = []  # track for reply
    for att in attachments:
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
            inv_id = store_unparsed_invoice(conn, vendor_id, email_data, str(pdf_path))
            _notify_unknown_format(vendor_name, att["filename"], email_data, str(e))
            if inv_id:
                create_review(conn, inv_id, vendor_id, "no_parser",
                              extracted_data={"vendor": vendor_name, "filename": att["filename"]})
            continue

        # Store in database
        store_invoice(
            conn, vendor_id, parsed, str(pdf_path),
            email_data["message_id"], source="email"
        )
        parsed_invoices.append(parsed)

        # ---- Format recognition for parsed PDF invoices ----
        # Extract raw text for fingerprinting
        import pymupdf
        try:
            doc = pymupdf.open(str(pdf_path))
            raw_text = "\n".join(page.get_text() for page in doc)
            doc.close()
            fp = compute_fingerprint(raw_text)
            reg = register_format(conn, vendor_id, fp, "pdf_parser")
            if reg["is_new"]:
                log.info("New PDF format fingerprint registered for vendor %s", vendor_name)
                create_review(conn, parsed.invoice_id, vendor_id, "new_format",
                              extracted_data={"vendor": vendor_name, "fingerprint": fp})
        except Exception as e:
            log.warning("Format fingerprinting failed for %s: %s", att["filename"], e)
        # ----------------------------------------------------

        _send_new_invoice_notification(parsed, vendor_name)

    # Send confirmation reply
    if parsed_invoices:
        _send_confirmation_reply(email_data, parsed_invoices, vendor_name)

    # Log to processed_emails
    all_filenames = ", ".join(a["filename"] for a in attachments)
    conn.execute(
        "INSERT OR REPLACE INTO processed_emails "
        "(message_id, vendor_name, filename, processed_at) "
        "VALUES (?, ?, ?, datetime('now'))",
        (email_data["message_id"], vendor_name, all_filenames)
    )
    conn.commit()


def _store_html_as_unparsed(conn, vendor_id, email_data, html_path, body_text):
    """Store an unparsed HTML-only receipt (no PDF). Returns invoice_id."""
    inv_id = f"unparsed_{datetime.now().strftime('%Y%m%d%H%M%S')}"
    conn.execute("""
        INSERT INTO invoices
        (id, vendor_id, source, email_message_id, pdf_path, new_charges, outstanding_balance)
        VALUES (?, ?, 'email_unparsed', ?, ?, 0, 0)
    """, (inv_id, vendor_id, email_data["message_id"], html_path))
    conn.commit()
    log.info(f"Stored unparsed HTML invoice {inv_id} (body at {html_path})")
    return inv_id


def _notify_unknown_format(vendor_name, filename, email_data, error_msg=""):
    """Send notification about an unparseable invoice."""
    try:
        from notifier import notify_unknown_format
        notify_unknown_format(
            vendor=vendor_name,
            filename=filename,
            subject=email_data.get("subject", ""),
            from_header=email_data.get("from", ""),
            pdf_path=str(INVOICE_DIR / vendor_name / filename) if filename != "no_body" else "",
            error_msg=error_msg,
        )
    except Exception as ne:
        log.error(f"Failed to send unknown-format notification: {ne}")


def _send_new_invoice_notification(parsed: ParsedInvoice, vendor_name: str):
    """Send notification about a new invoice."""
    try:
        from notifier import notify_new_invoice
        notify_new_invoice(
            parsed.invoice_id, vendor_name,
            parsed.outstanding_balance or parsed.new_charges,
            parsed.billing_period
        )
    except Exception as e:
        log.warning(f"Notification failed: {e}")


def _send_confirmation_reply(email_data, parsed_invoices, vendor_name):
    """Send a confirmation reply email."""
    from email_sender import send_reply, extract_reply_address
    reply_addr = extract_reply_address(email_data.get("from", ""))
    if reply_addr:
        p = parsed_invoices[0]
        send_reply(
            to_addr=reply_addr,
            original_subject=email_data.get("subject", ""),
            invoice_id=p.invoice_id,
            vendor=vendor_name,
            amount=p.outstanding_balance or p.new_charges,
            billing_period=p.billing_period,
            received_date=email_data.get("received_date", ""),
            attachment_count=len(parsed_invoices),
        )
    else:
        log.warning("No reply address found in From header — skipping reply")


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

    # Store PDF path relative to DATA_DIR (#26 — was absolute, broke across environments)
    from config import DATA_DIR
    try:
        rel_pdf_path = str(Path(pdf_path).relative_to(DATA_DIR))
    except ValueError:
        rel_pdf_path = pdf_path  # fallback if not under DATA_DIR

    # Insert or replace invoice (includes invoice_date #9)
    conn.execute("""
        INSERT OR REPLACE INTO invoices
        (id, vendor_id, billing_period, invoice_date, is_credit_memo, references_invoice,
         partner_name, partner_id, partner_username,
         previous_balance, credit_card_surcharges, payment_received,
         new_charges, outstanding_balance, source, email_message_id, pdf_path)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        parsed.invoice_id, vendor_id, parsed.billing_period,
        getattr(parsed, 'invoice_date', ''),
        int(parsed.is_credit_memo), parsed.references_invoice,
        parsed.partner_name, parsed.partner_id, parsed.partner_username,
        parsed.previous_balance, parsed.credit_card_surcharges,
        parsed.payment_received, parsed.new_charges,
        parsed.outstanding_balance, source, email_msg_id, rel_pdf_path
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
    """Store an invoice we couldn't parse (non-Intermedia vendor, etc.).

    Returns the invoice_id that was created.
    """
    inv_id = f"unparsed_{datetime.now().strftime('%Y%m%d%H%M%S')}"
    conn.execute("""
        INSERT INTO invoices
        (id, vendor_id, source, email_message_id, pdf_path, new_charges, outstanding_balance)
        VALUES (?, ?, 'email_unparsed', ?, ?, 0, 0)
    """, (inv_id, vendor_id, email_data["message_id"], pdf_path))
    conn.commit()
    log.info(f"Stored unparsed invoice {inv_id} (PDF at {pdf_path})")
    return inv_id