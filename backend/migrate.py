"""
One-time migration: import the hardcoded invoices from the old dashboard's
invoices.js into the SQLite database.

Usage:
    python3 migrate.py --js ~/Projects/intermedia-dashboard/invoices.js
"""

import argparse
import json
import re
import sys
from pathlib import Path

from db import init_db, get_db
from ingest import ensure_vendor, store_invoice
from pdf_parser import ParsedInvoice


def migrate_from_js(js_path: str):
    """Parse invoices.js and import all invoices into the DB."""
    content = Path(js_path).read_text()

    # Extract the array content between [ and ];
    match = re.search(r"const INVOICES\s*=\s*\[(.+)\];", content, re.DOTALL)
    if not match:
        print("ERROR: Could not find INVOICES array in file.")
        sys.exit(1)

    js_array = "[" + match.group(1) + "]"
    # Convert JS object syntax to JSON: quote unquoted keys
    js_array = re.sub(r"(\w+):", r'"\1":', js_array)
    # Remove trailing commas before ] and }
    js_array = re.sub(r",\s*([}\]])", r"\1", js_array)

    invoices = json.loads(js_array)

    init_db()
    conn = get_db()

    for inv_data in invoices:
        vendor_name = inv_data.get("vendor", "Unknown")
        vendor_id = ensure_vendor(conn, vendor_name, "")

        summary = inv_data.get("summary", {})
        parsed = ParsedInvoice(
            invoice_id=inv_data["id"],
            vendor=vendor_name,
            billing_period=inv_data.get("billing_period", "Unknown"),
            is_credit_memo=inv_data.get("is_credit_memo", False),
            references_invoice=inv_data.get("references_invoice"),
            partner_name=inv_data.get("partner_name", ""),
            partner_id=inv_data.get("partner_id", ""),
            partner_username=inv_data.get("partner_username", ""),
            previous_balance=summary.get("previous_balance", 0),
            credit_card_surcharges=summary.get("credit_card_surcharges", 0),
            payment_received=summary.get("payment_received", 0),
            new_charges=summary.get("new_charges", 0),
            outstanding_balance=summary.get("outstanding_balance", 0),
            customers=inv_data.get("customers", []),
            line_items=inv_data.get("line_items", []),
        )

        store_invoice(conn, vendor_id, parsed, "", "", source="imported")

    conn.close()
    print(f"Migrated {len(invoices)} invoices from {js_path}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Migrate invoices.js to SQLite")
    parser.add_argument("--js", required=True, help="Path to invoices.js file")
    args = parser.parse_args()
    migrate_from_js(args.js)
