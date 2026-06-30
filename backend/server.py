"""
Flask backend serving the vendor invoice dashboard.

Serves:
- Static dashboard (index.html + assets from ../frontend/)
- REST API for invoice data, vendor filtering, uploads, deletes
"""

import logging
import os
from pathlib import Path

from flask import Flask, jsonify, request, send_from_directory, abort, g

from db import init_db, get_db
from pdf_parser import parse_pdf
from ingest import ensure_vendor, store_invoice
from config import DATA_DIR, INVOICE_DIR, DB_PATH
from auth import (
    get_password_hash, verify_password, validate_password_strength,
    create_access_token, create_refresh_token,
    decode_access_token, decode_refresh_token,
    extract_token_from_request, require_auth,
)

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
# Auth API routes (public — no token required)
# ---------------------------------------------------------------------------

@app.route("/api/auth/login", methods=["POST"])
def login():
    """OAuth2-compatible login. Returns JWT access + refresh tokens."""
    data = request.get_json() or {}
    email = data.get("email", "").strip().lower()
    password = data.get("password", "")

    if not email or not password:
        return jsonify({"error": "Email and password required"}), 400

    conn = get_db()
    user = conn.execute(
        "SELECT * FROM users WHERE email = ?", (email,)
    ).fetchone()
    conn.close()

    if not user or not verify_password(password, user["hashed_password"]):
        return jsonify({"error": "Incorrect email or password"}), 401

    if not user["is_active"]:
        return jsonify({"error": "Inactive user"}), 403

    access_token = create_access_token(user["id"])
    refresh_token = create_refresh_token(user["id"])

    return jsonify({
        "access_token": access_token,
        "refresh_token": refresh_token,
        "token_type": "bearer",
        "user": {
            "id": user["id"],
            "email": user["email"],
            "full_name": user["full_name"],
            "is_admin": bool(user["is_admin"]),
        }
    })


@app.route("/api/auth/register", methods=["POST"])
def register():
    """Register a new user. First user becomes admin."""
    data = request.get_json() or {}
    email = data.get("email", "").strip().lower()
    password = data.get("password", "")
    full_name = data.get("full_name", "")

    if not email or not password or not full_name:
        return jsonify({"error": "Email, password, and full name required"}), 400

    err = validate_password_strength(password)
    if err:
        return jsonify({"error": err}), 400

    conn = get_db()
    existing = conn.execute(
        "SELECT 1 FROM users WHERE email = ?", (email,)
    ).fetchone()
    if existing:
        conn.close()
        return jsonify({"error": "Email already registered"}), 400

    # First user becomes admin
    user_count = conn.execute("SELECT COUNT(*) as count FROM users").fetchone()["count"]
    is_admin = 1 if user_count == 0 else 0

    cursor = conn.execute(
        "INSERT INTO users (email, hashed_password, full_name, is_admin) "
        "VALUES (?, ?, ?, ?)",
        (email, get_password_hash(password), full_name, is_admin)
    )
    conn.commit()
    user_id = cursor.lastrowid
    conn.close()

    access_token = create_access_token(user_id)
    refresh_token = create_refresh_token(user_id)

    return jsonify({
        "access_token": access_token,
        "refresh_token": refresh_token,
        "token_type": "bearer",
        "user": {
            "id": user_id,
            "email": email,
            "full_name": full_name,
            "is_admin": bool(is_admin),
        }
    }), 201


@app.route("/api/auth/refresh", methods=["POST"])
def refresh():
    """Exchange a refresh token for a new access + refresh token pair."""
    data = request.get_json() or {}
    refresh_token = data.get("refresh_token", "")

    if not refresh_token:
        return jsonify({"error": "Refresh token required"}), 400

    payload = decode_refresh_token(refresh_token)
    if payload is None:
        return jsonify({"error": "Invalid or expired refresh token"}), 401

    try:
        user_id = int(payload["sub"])
    except (KeyError, ValueError):
        return jsonify({"error": "Invalid token payload"}), 401

    conn = get_db()
    user = conn.execute(
        "SELECT id, is_active FROM users WHERE id = ?", (user_id,)
    ).fetchone()
    conn.close()

    if not user or not user["is_active"]:
        return jsonify({"error": "Invalid or expired refresh token"}), 401

    return jsonify({
        "access_token": create_access_token(user_id),
        "refresh_token": create_refresh_token(user_id),
        "token_type": "bearer",
    })


@app.route("/api/auth/me")
@require_auth
def get_current_user():
    """Get current authenticated user info."""
    conn = get_db()
    user = conn.execute(
        "SELECT id, email, full_name, is_active, is_admin, created_at "
        "FROM users WHERE id = ?",
        (g.current_user_id,)
    ).fetchone()
    conn.close()

    if not user:
        return jsonify({"error": "User not found"}), 404

    return jsonify({
        "id": user["id"],
        "email": user["email"],
        "full_name": user["full_name"],
        "is_active": bool(user["is_active"]),
        "is_admin": bool(user["is_admin"]),
        "created_at": user["created_at"],
    })


@app.route("/api/auth/setup-check")
def setup_check():
    """Check if any users exist. Frontend uses this to show register vs login."""
    conn = get_db()
    count = conn.execute("SELECT COUNT(*) as count FROM users").fetchone()["count"]
    conn.close()
    return jsonify({"has_users": count > 0})


@app.route("/api/health")
def health_check():
    """Lightweight health check for Render."""
    return jsonify({"status": "healthy"})


# ---------------------------------------------------------------------------
# API routes
# ---------------------------------------------------------------------------

@app.route("/api/vendors")
@require_auth
def get_vendors():
    conn = get_db()
    rows = conn.execute(
        "SELECT id, name, email_domain FROM vendors ORDER BY name"
    ).fetchall()
    conn.close()
    return jsonify([dict(r) for r in rows])


@app.route("/api/invoices")
@require_auth
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
@require_auth
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
@require_auth
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
@require_auth
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


@app.route("/api/poll", methods=["POST"])
@require_auth
def trigger_poll():
    """Manually trigger an email poll cycle.

    Query params:
      ?reprocess=true  — clear processed_emails table first so all
                         emails get reprocessed (useful after parser fixes)
    """
    from ingest import run_ingestion
    from db import get_db
    try:
        if request.args.get("reprocess") in ("true", "1", "yes"):
            conn = get_db()
            # Order matters: children first, then parents
            conn.execute("DELETE FROM line_items")
            conn.execute("DELETE FROM customers")
            conn.execute("DELETE FROM invoices")
            conn.execute("DELETE FROM processed_emails")
            conn.execute("DELETE FROM vendors")
            conn.commit()
            conn.close()
            logging.info("Cleared all data for reprocessing")
        count = run_ingestion()
        return jsonify({"success": True, "processed": count})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@app.route("/api/invoices/<invoice_id>", methods=["DELETE"])
@require_auth
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
@require_auth
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


@app.route("/api/invoices/<invoice_id>/raw-text")
@require_auth
def get_raw_text(invoice_id):
    """Return the raw text extracted from the PDF, for debugging parser output."""
    import pymupdf
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
    try:
        doc = pymupdf.open(str(pdf_path))
        full_text = ""
        for page in doc:
            full_text += page.get_text() + "\n"
        doc.close()
        return jsonify({"text": full_text, "page_count": full_text.count("\n---PAGE---\n") + 1})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/invoices/<invoice_id>", methods=["PUT"])
@require_auth
def update_invoice(invoice_id):
    """Update invoice fields, customers, and line items.

    Accepts JSON:
    {
      "invoice": { "billing_period": "...", "new_charges": ..., ... },
      "customers": [{ "id": 1, "name": "...", "account_id": "...", "partner_id": "...", "total": ... }, ...],
      "line_items": [{ "id": 1, "customer_name": "...", "date": "...", "item": "...", "type": "...", "qty": ..., "unit_price": ..., "amount": ... }, ...]
    }
    Any of the three keys may be omitted to skip updating that section.
    """
    data = request.get_json()
    if not data:
        return jsonify({"error": "No data provided"}), 400

    conn = get_db()

    # Verify invoice exists
    inv = conn.execute("SELECT id FROM invoices WHERE id = ?", (invoice_id,)).fetchone()
    if not inv:
        conn.close()
        abort(404)

    # Update invoice fields
    if "invoice" in data:
        inv_data = data["invoice"]
        allowed_fields = {
            "billing_period", "is_credit_memo", "references_invoice",
            "partner_name", "partner_id", "partner_username",
            "previous_balance", "credit_card_surcharges",
            "payment_received", "new_charges", "outstanding_balance"
        }
        sets = []
        values = []
        for field in allowed_fields:
            if field in inv_data:
                val = inv_data[field]
                if field == "is_credit_memo":
                    val = 1 if val else 0
                sets.append(f"{field} = ?")
                values.append(val)
        if sets:
            values.append(invoice_id)
            conn.execute(
                f"UPDATE invoices SET {', '.join(sets)} WHERE id = ?",
                values
            )
            conn.commit()

    # Update customers (replace all if provided)
    if "customers" in data:
        conn.execute("DELETE FROM customers WHERE invoice_id = ?", (invoice_id,))
        for c in data["customers"]:
            conn.execute(
                "INSERT INTO customers (invoice_id, name, account_id, partner_id, total) "
                "VALUES (?, ?, ?, ?, ?)",
                (invoice_id, c.get("name", ""), c.get("account_id", ""),
                 c.get("partner_id", ""), c.get("total", 0))
            )
        conn.commit()

    # Update line items (replace all if provided)
    if "line_items" in data:
        conn.execute("DELETE FROM line_items WHERE invoice_id = ?", (invoice_id,))
        for li in data["line_items"]:
            conn.execute(
                "INSERT INTO line_items "
                "(invoice_id, customer_name, date, item, type, qty, unit_price, amount) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (invoice_id, li.get("customer_name", ""), li.get("date", ""),
                 li.get("item", ""), li.get("type", ""), li.get("qty", 0),
                 li.get("unit_price", 0), li.get("amount", 0))
            )
        conn.commit()

    conn.close()
    logging.info(f"Updated invoice {invoice_id} via PUT")
    return jsonify({"success": True})


if __name__ == "__main__":
    init_db()
    port = int(os.environ.get("PORT", 8080))
    app.run(host="0.0.0.0", port=port, debug=True, use_reloader=False)
