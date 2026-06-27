"""
Flask backend serving the vendor invoice dashboard.

Serves:
- Static dashboard (index.html + assets from ../frontend/)
- REST API for invoice data, vendor filtering, uploads, deletes
"""

import logging
import os
from pathlib import Path

from flask import Flask, jsonify, request, send_from_directory, abort

from db import init_db, get_db
from pdf_parser import parse_pdf
from ingest import ensure_vendor, store_invoice
from config import DATA_DIR, INVOICE_DIR, DB_PATH

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s"
)

app = Flask(__name__, static_folder="../frontend", static_url_path="")

# Initialize database on startup (works with gunicorn, not just __main__)
DATA_DIR.mkdir(parents=True, exist_ok=True)
INVOICE_DIR.mkdir(parents=True, exist_ok=True)
DB_PATH.parent.mkdir(parents=True, exist_ok=True)
init_db()


# ---------------------------------------------------------------------------
# Static routes
# ---------------------------------------------------------------------------

@app.route("/")
def index():
    return send_from_directory(app.static_folder, "index.html")


# ---------------------------------------------------------------------------
# API routes
# ---------------------------------------------------------------------------

@app.route("/api/vendors")
def get_vendors():
    conn = get_db()
    rows = conn.execute(
        "SELECT id, name, email_domain FROM vendors ORDER BY name"
    ).fetchall()
    conn.close()
    return jsonify([dict(r) for r in rows])


@app.route("/api/invoices")
def get_invoices():
    conn = get_db()
    vendor = request.args.get("vendor")
    if vendor:
        rows = conn.execute(
            "SELECT i.*, v.name as vendor_name FROM invoices i "
            "JOIN vendors v ON i.vendor_id = v.id "
            "WHERE v.name = ? ORDER BY i.created_at DESC",
            (vendor,)
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT i.*, v.name as vendor_name FROM invoices i "
            "JOIN vendors v ON i.vendor_id = v.id "
            "ORDER BY i.created_at DESC"
        ).fetchall()
    conn.close()
    return jsonify([dict(r) for r in rows])


@app.route("/api/invoices/<invoice_id>")
def get_invoice(invoice_id):
    conn = get_db()
    inv = conn.execute(
        "SELECT i.*, v.name as vendor_name FROM invoices i "
        "JOIN vendors v ON i.vendor_id = v.id WHERE i.id = ?",
        (invoice_id,)
    ).fetchone()
    if not inv:
        conn.close()
        abort(404)
    customers = conn.execute(
        "SELECT * FROM customers WHERE invoice_id = ?", (invoice_id,)
    ).fetchall()
    line_items = conn.execute(
        "SELECT * FROM line_items WHERE invoice_id = ?", (invoice_id,)
    ).fetchall()
    conn.close()
    return jsonify({
        "invoice": dict(inv),
        "customers": [dict(c) for c in customers],
        "line_items": [dict(li) for li in line_items]
    })


@app.route("/api/summary")
def get_summary():
    """Aggregated summary across all or filtered invoices."""
    conn = get_db()
    vendor = request.args.get("vendor")
    if vendor:
        row = conn.execute(
            "SELECT SUM(previous_balance) as prev, "
            "SUM(credit_card_surcharges) as cc, "
            "SUM(payment_received) as pay, "
            "SUM(new_charges) as new, "
            "SUM(outstanding_balance) as outstanding, "
            "COUNT(*) as count "
            "FROM invoices i JOIN vendors v ON i.vendor_id = v.id "
            "WHERE v.name = ?",
            (vendor,)
        ).fetchone()
    else:
        row = conn.execute(
            "SELECT SUM(previous_balance) as prev, "
            "SUM(credit_card_surcharges) as cc, "
            "SUM(payment_received) as pay, "
            "SUM(new_charges) as new, "
            "SUM(outstanding_balance) as outstanding, "
            "COUNT(*) as count FROM invoices"
        ).fetchone()
    conn.close()
    return jsonify(dict(row) if row else {})


@app.route("/api/upload", methods=["POST"])
def upload_pdf():
    if "file" not in request.files:
        return jsonify({"error": "No file provided"}), 400
    file = request.files["file"]
    if not file.filename.lower().endswith(".pdf"):
        return jsonify({"error": "Only PDF files supported"}), 400

    vendor_name = request.form.get("vendor", "Unknown")
    pdf_dir = INVOICE_DIR / vendor_name
    pdf_dir.mkdir(parents=True, exist_ok=True)
    pdf_path = pdf_dir / file.filename
    file.save(str(pdf_path))

    try:
        parsed = parse_pdf(str(pdf_path))
    except ValueError as e:
        return jsonify({"error": str(e)}), 422

    conn = get_db()
    vendor_id = ensure_vendor(conn, parsed.vendor, "")
    store_invoice(conn, vendor_id, parsed, str(pdf_path), "", source="upload")
    conn.close()

    return jsonify({"success": True, "invoice_id": parsed.invoice_id}), 201


@app.route("/api/invoices/<invoice_id>", methods=["DELETE"])
def delete_invoice(invoice_id):
    conn = get_db()
    inv = conn.execute(
        "SELECT pdf_path FROM invoices WHERE id = ?", (invoice_id,)
    ).fetchone()
    if not inv:
        conn.close()
        abort(404)
    conn.execute("DELETE FROM invoices WHERE id = ?", (invoice_id,))
    conn.commit()
    conn.close()
    # Delete the PDF file if it exists
    if inv["pdf_path"]:
        pdf = Path(inv["pdf_path"])
        if pdf.exists():
            pdf.unlink()
    return jsonify({"success": True})


@app.route("/api/invoices/<invoice_id>/pdf")
def download_pdf(invoice_id):
    conn = get_db()
    inv = conn.execute(
        "SELECT pdf_path FROM invoices WHERE id = ?", (invoice_id,)
    ).fetchone()
    conn.close()
    if not inv or not inv["pdf_path"]:
        abort(404)
    pdf_path = Path(inv["pdf_path"])
    if not pdf_path.exists():
        abort(404)
    return send_from_directory(
        pdf_path.parent, pdf_path.name, as_attachment=True
    )


if __name__ == "__main__":
    init_db()
    port = int(os.environ.get("PORT", 8080))
    app.run(host="0.0.0.0", port=port, debug=True, use_reloader=False)
