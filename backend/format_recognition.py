"""
Format fingerprint detection and review queue management.

Two core concerns:
  1. Compute a lightweight, deterministic fingerprint from a document's
     label-level structure — not ML, just a normalized set of key labels.
  2. Manage the format_reviews queue: create reviews when parsers can't
     match a document, or when an existing vendor sends a structurally
     different document that *was* parsed (a "new format" from a known
     vendor).
"""

import json
import logging
import re
from datetime import datetime
from typing import Optional

from db import get_db

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Label keyword sets — these are the structural labels the fingerprint
# function looks for.  Each known parser's document contains a characteristic
# subset; the fingerprint is just their sorted, normalised union.
# ---------------------------------------------------------------------------

_LABEL_KEYWORDS = [
    # Intermedia / generic carrier
    "invoice",
    "credit memo",
    "billing period",
    "balance forward",
    "credit card surcharges",
    "payment received",
    "new charges",
    "total outstanding balance",
    "monthly charges",
    "service charges",
    "credits",
    "taxes",
    "invoice date",
    "date of issue",
    # Barracuda
    "subtotal",
    "tax total",
    "amount paid",
    "amount due",
    "start date",
    "end date",
    "terms",
    "due date",
    "overage seat",
    "seat",
    # Flyover / BTABS
    "invoice no",
    "product or service",
    "description",
    "qty",
    "rate",
    "balance due",
    "paid in full",
    # Contractor
    "total cost",
    "services",
    "other costs",
    # Extra Space Storage
    "transaction number",
    "payment date",
    "unit",
    "payment total",
    "next payment due on",
    # Generic / fallback labels
    "bill to",
    "ship to",
    "reference",
    "po number",
    "customer id",
    "account number",
    "total",
    "previous balance",
]

# Normalised forms (lowercase, stripped) for fast lookup
_LABEL_LOOKUP = {kw.lower().strip(): kw for kw in _LABEL_KEYWORDS}


def compute_fingerprint(text: str) -> str:
    """Compute a deterministic, sorted keyword-set fingerprint from document text.

    The function scans *text* for each known label (both in 'Label:' and
    standalone forms) and returns a sorted, comma-separated string of
    matched keywords that uniquely identifies the document's structural
    "shape".

    Args:
        text: Full extracted text of the document (PDF page text or HTML
              plain-text version).

    Returns:
        Sorted comma-separated fingerprint string, e.g.
        "billing period, invoice, invoice date, new charges, payment received,
         total outstanding balance"
    """
    text_lower = text.lower().strip()
    if not text_lower:
        return "__empty__"

    found = set()  # type: set[str]

    for norm in _LABEL_LOOKUP:
        # Match as word-boundary delimited substring so that "invoice" in
        # "reinvoice" doesn't trigger a false positive (but "invoice" in
        # "invoice #12345" does).
        if re.search(rf"\b{re.escape(norm)}\b", text_lower):
            found.add(norm)

    if not found:
        return "__unknown__"

    sorted_labels: list[str] = sorted(found)
    return ", ".join(sorted_labels)


# ---------------------------------------------------------------------------
# Format registry helpers
# ---------------------------------------------------------------------------

def register_format(conn, vendor_id: int, fingerprint: str,
                    parser_name: str) -> dict:
    """Upsert into invoice_formats and return the record.

    Returns a dict with keys: id, is_new (bool).
    """
    existing = conn.execute(
        "SELECT id, status, sample_count FROM invoice_formats "
        "WHERE vendor_id = ? AND format_fingerprint = ?",
        (vendor_id, fingerprint),
    ).fetchone()

    if existing:
        conn.execute(
            "UPDATE invoice_formats "
            "SET last_seen = datetime('now'), "
            "    sample_count = sample_count + 1 "
            "WHERE id = ?",
            (existing["id"],),
        )
        conn.commit()
        return {"id": existing["id"], "is_new": False,
                "status": existing["status"]}

    cursor = conn.execute(
        "INSERT INTO invoice_formats "
        "(vendor_id, format_fingerprint, parser_name, status) "
        "VALUES (?, ?, ?, 'new')",
        (vendor_id, fingerprint, parser_name),
    )
    conn.commit()
    return {"id": cursor.lastrowid, "is_new": True, "status": "new"}


def is_recognized_format(conn, vendor_id: int, fingerprint: str) -> bool:
    """Return True if this fingerprint is already registered as 'recognized'."""
    row = conn.execute(
        "SELECT 1 FROM invoice_formats "
        "WHERE vendor_id = ? AND format_fingerprint = ? AND status = 'recognized'",
        (vendor_id, fingerprint),
    ).fetchone()
    return row is not None


# ---------------------------------------------------------------------------
# Review queue helpers
# ---------------------------------------------------------------------------

def create_review(conn, invoice_id: str, vendor_id: int,
                  detection_reason: str,
                  extracted_data: Optional[dict] = None) -> int:
    """Insert a format_review record and return its id."""
    cursor = conn.execute(
        "INSERT INTO format_reviews "
        "(invoice_id, vendor_id, status, detection_reason, extracted_data) "
        "VALUES (?, ?, 'pending', ?, ?)",
        (invoice_id, vendor_id, detection_reason,
         json.dumps(extracted_data) if extracted_data else None),
    )
    conn.commit()
    review_id = cursor.lastrowid
    log.info("Created format_review #%s for invoice %s (reason=%s)",
             review_id, invoice_id, detection_reason)
    return review_id


def get_review_list(conn, status_filter: Optional[str] = None) -> list[dict]:
    """Return list of reviews with invoice + vendor info."""
    query = (
        "SELECT fr.*, i.source as invoice_source, "
        "       i.pdf_path, i.email_message_id, "
        "       v.name as vendor_name "
        "FROM format_reviews fr "
        "JOIN invoices i ON fr.invoice_id = i.id "
        "JOIN vendors v ON fr.vendor_id = v.id"
    )
    params = []
    if status_filter:
        query += " WHERE fr.status = ?"
        params.append(status_filter)
    query += " ORDER BY fr.detected_at DESC"
    rows = conn.execute(query, params).fetchall()
    return [_review_row_to_dict(r) for r in rows]


def get_review_by_id(conn, review_id: int) -> Optional[dict]:
    """Return full review detail, optionally including raw text."""
    row = conn.execute(
        "SELECT fr.*, i.source as invoice_source, "
        "       i.pdf_path, i.email_message_id, "
        "       v.name as vendor_name "
        "FROM format_reviews fr "
        "JOIN invoices i ON fr.invoice_id = i.id "
        "JOIN vendors v ON fr.vendor_id = v.id "
        "WHERE fr.id = ?",
        (review_id,),
    ).fetchone()
    if not row:
        return None
    return _review_row_to_dict(row)


def _review_row_to_dict(row) -> dict:
    """Convert a sqlite3.Row to a dict, parsing JSON fields."""
    d = dict(row)
    if d.get("extracted_data"):
        try:
            d["extracted_data"] = json.loads(d["extracted_data"])
        except (json.JSONDecodeError, TypeError):
            pass
    return d


def extract_raw_text_from_document(pdf_path: str) -> str:
    """Extract raw text from a stored PDF or HTML file.

    Returns the extracted text, or empty string on failure.
    """
    from pathlib import Path
    path = Path(pdf_path)
    if not path.exists():
        return ""

    if path.suffix.lower() == ".pdf":
        try:
            import pymupdf
            doc = pymupdf.open(str(path))
            text = "\n".join(page.get_text() for page in doc)
            doc.close()
            return text
        except Exception as e:
            log.warning("Failed to extract text from PDF %s: %s", path, e)
            return ""
    else:
        # Plain text or HTML — read as text
        try:
            return path.read_text(encoding="utf-8")
        except Exception as e:
            log.warning("Failed to read file %s: %s", path, e)
            return ""