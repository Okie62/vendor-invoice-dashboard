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
    extract_token_from_request, require_auth, require_admin,
)
from format_recognition import (
    get_review_list, get_review_by_id, extract_raw_text_from_document,
    create_review,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s"
)

app = Flask(__name__, static_folder="../frontend", static_url_path="")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _resolve_pdf_path(stored_path):
    """Resolve a PDF path that may be relative to DATA_DIR (#26).

    Old invoices stored absolute paths; new ones store relative to DATA_DIR.
    This handles both cases.
    """
    if not stored_path:
        return None
    p = Path(stored_path)
    if p.is_absolute() and p.exists():
        return p
    # Try resolving relative to DATA_DIR
    from config import DATA_DIR
    rel = DATA_DIR / stored_path
    if rel.exists():
        return rel
    # Last resort: return the original path
    return p


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

    access_token = create_access_token(user["id"], email=user["email"])
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

    access_token = create_access_token(user_id, email=email)
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


@app.route("/api/diagnostic")
@require_auth
def diagnostic():
    """Diagnostic endpoint showing DB paths and counts."""
    import sys
    from config import BASE_DIR, DATA_DIR, DB_PATH

    db_exists = DB_PATH.exists()
    db_size = DB_PATH.stat().st_size if db_exists else 0

    conn = get_db()
    table_count = conn.execute(
        "SELECT count(*) as c FROM sqlite_master WHERE type='table'"
    ).fetchone()["c"]
    invoice_count = 0
    user_count = 0
    try:
        invoice_count = conn.execute("SELECT count(*) as c FROM invoices").fetchone()["c"]
    except Exception:
        pass
    try:
        user_count = conn.execute("SELECT count(*) as c FROM users").fetchone()["c"]
    except Exception:
        pass
    conn.close()

    return jsonify({
        "base_dir": str(BASE_DIR),
        "data_dir": str(DATA_DIR),
        "db_path": str(DB_PATH),
        "db_exists": db_exists,
        "db_size_bytes": db_size,
        "render_project_dir": os.environ.get("RENDER_PROJECT_DIR", "NOT SET"),
        "python_version": sys.version,
        "table_count": table_count,
        "invoice_count": invoice_count,
        "user_count": user_count,
        "disk_mount_check": Path("/opt/render/project/src/data").exists(),
    })


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
    """Get invoices with optional vendor and date filtering (#7).

    Query params:
      vendor — filter by vendor name
      start  — billing_period >= start (ISO date or 'Mon DD, YYYY')
      end    — billing_period <= end
      search — search invoice_id or billing_period (#29)
    """
    conn = get_db()
    vendor = request.args.get("vendor")
    start_date = request.args.get("start")
    end_date = request.args.get("end")
    search = request.args.get("search", "").strip()

    query = (
        "SELECT i.*, v.name as vendor_name FROM invoices i "
        "JOIN vendors v ON i.vendor_id = v.id WHERE 1=1"
    )
    params = []
    if vendor:
        query += " AND v.name = ?"
        params.append(vendor)
    if start_date:
        query += " AND i.created_at >= ?"
        params.append(start_date)
    if end_date:
        query += " AND i.created_at <= ?"
        params.append(end_date)
    if search:
        query += " AND (i.id LIKE ? OR i.billing_period LIKE ?)"
        params.extend([f"%{search}%", f"%{search}%"])
    query += " ORDER BY i.created_at DESC"

    rows = conn.execute(query, params).fetchall()
    conn.close()
    return jsonify([dict(r) for r in rows])


@app.route("/api/invoices/bulk")
@require_auth
def get_invoices_bulk():
    """Bulk endpoint returning invoices with customers and line items (#2).

    Replaces the N+1 pattern of calling /api/invoices/{id} in a loop.
    Supports the same vendor/start/end/search filters as /api/invoices.
    """
    conn = get_db()
    vendor = request.args.get("vendor")
    start_date = request.args.get("start")
    end_date = request.args.get("end")
    search = request.args.get("search", "").strip()

    query = (
        "SELECT i.*, v.name as vendor_name FROM invoices i "
        "JOIN vendors v ON i.vendor_id = v.id WHERE 1=1"
    )
    params = []
    if vendor:
        query += " AND v.name = ?"
        params.append(vendor)
    if start_date:
        query += " AND i.created_at >= ?"
        params.append(start_date)
    if end_date:
        query += " AND i.created_at <= ?"
        params.append(end_date)
    if search:
        query += " AND (i.id LIKE ? OR i.billing_period LIKE ?)"
        params.extend([f"%{search}%", f"%{search}%"])
    query += " ORDER BY i.created_at DESC"

    rows = conn.execute(query, params).fetchall()
    if not rows:
        conn.close()
        return jsonify({"invoices": []})

    inv_ids = [r["id"] for r in rows]

    # Fetch all customers for these invoices in one query
    placeholders = ",".join("?" * len(inv_ids))
    customers = conn.execute(
        f"SELECT * FROM customers WHERE invoice_id IN ({placeholders})",
        inv_ids
    ).fetchall()

    # Fetch all line items in one query
    line_items = conn.execute(
        f"SELECT * FROM line_items WHERE invoice_id IN ({placeholders})",
        inv_ids
    ).fetchall()

    conn.close()

    # Group by invoice_id
    cust_map = {}
    for c in customers:
        cust_map.setdefault(c["invoice_id"], []).append(dict(c))
    li_map = {}
    for li in line_items:
        li_map.setdefault(li["invoice_id"], []).append(dict(li))

    result = []
    for r in rows:
        inv = dict(r)
        inv_id = inv["id"]
        result.append({
            "id": inv_id,
            "vendor": inv.get("vendor_name", ""),
            "billing_period": inv.get("billing_period", ""),
            "invoice_date": inv.get("invoice_date", ""),
            "is_credit_memo": bool(inv.get("is_credit_memo", 0)),
            "references_invoice": inv.get("references_invoice"),
            "partner_name": inv.get("partner_name", ""),
            "partner_id": inv.get("partner_id", ""),
            "partner_username": inv.get("partner_username", ""),
            "summary": {
                "previous_balance": inv.get("previous_balance", 0),
                "credit_card_surcharges": inv.get("credit_card_surcharges", 0),
                "payment_received": inv.get("payment_received", 0),
                "new_charges": inv.get("new_charges", 0),
                "outstanding_balance": inv.get("outstanding_balance", 0),
            },
            "customers": cust_map.get(inv_id, []),
            "line_items": li_map.get(inv_id, []),
        })

    return jsonify({"invoices": result})


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
    """Aggregated summary across all or filtered invoices.

    Supports vendor and date filtering (#7).
    Returns CC surcharges in summary (#16).
    """
    conn = get_db()
    vendor = request.args.get("vendor")
    start_date = request.args.get("start")
    end_date = request.args.get("end")

    where = "WHERE 1=1"
    params = []
    if vendor:
        where += " AND v.name = ?"
        params.append(vendor)
    if start_date:
        where += " AND i.created_at >= ?"
        params.append(start_date)
    if end_date:
        where += " AND i.created_at <= ?"
        params.append(end_date)

    row = conn.execute(
        f"SELECT SUM(i.previous_balance) as prev, "
        f"SUM(i.credit_card_surcharges) as cc, "
        f"SUM(i.payment_received) as pay, "
        f"SUM(i.new_charges) as new, "
        f"SUM(i.outstanding_balance) as outstanding, "
        f"COUNT(*) as count "
        f"FROM invoices i JOIN vendors v ON i.vendor_id = v.id {where}",
        params
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
        pdf = _resolve_pdf_path(inv["pdf_path"])
        if pdf and pdf.exists():
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
    pdf_path = _resolve_pdf_path(inv["pdf_path"])
    if not pdf_path or not pdf_path.exists():
        abort(404)
    return send_from_directory(
        str(pdf_path.parent), pdf_path.name, as_attachment=True
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
    pdf_path = _resolve_pdf_path(inv["pdf_path"])
    if not pdf_path or not pdf_path.exists():
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
            "billing_period", "invoice_date", "is_credit_memo", "references_invoice",
            "partner_name", "partner_id", "partner_username",
            "previous_balance", "credit_card_surcharges",
            "payment_received", "new_charges", "outstanding_balance"
        }
        sets = []
        values = []
        changes = {}
        for field in allowed_fields:
            if field in inv_data:
                val = inv_data[field]
                if field == "is_credit_memo":
                    val = 1 if val else 0
                sets.append(f"{field} = ?")
                values.append(val)
                changes[field] = val
        if sets:
            values.append(invoice_id)
            conn.execute(
                f"UPDATE invoices SET {', '.join(sets)} WHERE id = ?",
                values
            )
            conn.commit()
            # Audit log (#20)
            from db import log_audit
            user_email = ""
            if hasattr(g, 'current_user_email'):
                user_email = g.current_user_email or ""
            log_audit(conn, invoice_id, g.current_user_id, user_email,
                      "update_invoice", changes)

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


# ---------------------------------------------------------------------------
# CSV Export (#8)
# ---------------------------------------------------------------------------

@app.route("/api/export/invoices")
@require_auth
def export_invoices_csv():
    """Export invoices as CSV."""
    import csv
    import io
    conn = get_db()
    vendor = request.args.get("vendor")
    if vendor:
        rows = conn.execute(
            "SELECT i.id, v.name as vendor, i.billing_period, i.invoice_date, "
            "i.is_credit_memo, i.previous_balance, i.credit_card_surcharges, "
            "i.payment_received, i.new_charges, i.outstanding_balance, i.created_at "
            "FROM invoices i JOIN vendors v ON i.vendor_id = v.id "
            "WHERE v.name = ? ORDER BY i.created_at DESC",
            (vendor,)
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT i.id, v.name as vendor, i.billing_period, i.invoice_date, "
            "i.is_credit_memo, i.previous_balance, i.credit_card_surcharges, "
            "i.payment_received, i.new_charges, i.outstanding_balance, i.created_at "
            "FROM invoices i JOIN vendors v ON i.vendor_id = v.id "
            "ORDER BY i.created_at DESC"
        ).fetchall()
    conn.close()

    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(["Invoice ID", "Vendor", "Billing Period", "Invoice Date",
                     "Credit Memo", "Previous Balance", "CC Surcharges",
                     "Payment Received", "New Charges", "Outstanding Balance",
                     "Created At"])
    for r in rows:
        writer.writerow(list(r))
    buf.seek(0)
    from flask import Response
    return Response(
        buf.getvalue(),
        mimetype="text/csv",
        headers={"Content-Disposition": "attachment; filename=invoices.csv"}
    )


@app.route("/api/export/customers")
@require_auth
def export_customers_csv():
    """Export customers as CSV."""
    import csv
    import io
    conn = get_db()
    rows = conn.execute(
        "SELECT c.name, c.account_id, c.partner_id, c.total, i.id as invoice_id, "
        "v.name as vendor FROM customers c "
        "JOIN invoices i ON c.invoice_id = i.id "
        "JOIN vendors v ON i.vendor_id = v.id "
        "ORDER BY c.name"
    ).fetchall()
    conn.close()

    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(["Customer", "Account ID", "Partner Ref", "Total", "Invoice ID", "Vendor"])
    for r in rows:
        writer.writerow(list(r))
    buf.seek(0)
    from flask import Response
    return Response(
        buf.getvalue(),
        mimetype="text/csv",
        headers={"Content-Disposition": "attachment; filename=customers.csv"}
    )


@app.route("/api/export/line-items")
@require_auth
def export_line_items_csv():
    """Export line items as CSV."""
    import csv
    import io
    conn = get_db()
    rows = conn.execute(
        "SELECT li.customer_name, li.date, li.item, li.type, li.qty, "
        "li.unit_price, li.amount, li.invoice_id, v.name as vendor "
        "FROM line_items li "
        "JOIN invoices i ON li.invoice_id = i.id "
        "JOIN vendors v ON i.vendor_id = v.id "
        "ORDER BY li.date DESC"
    ).fetchall()
    conn.close()

    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(["Customer", "Date", "Item", "Type", "Qty", "Unit Price",
                     "Amount", "Invoice ID", "Vendor"])
    for r in rows:
        writer.writerow(list(r))
    buf.seek(0)
    from flask import Response
    return Response(
        buf.getvalue(),
        mimetype="text/csv",
        headers={"Content-Disposition": "attachment; filename=line_items.csv"}
    )


# ---------------------------------------------------------------------------
# Reprocess single invoice (#15)
# ---------------------------------------------------------------------------

@app.route("/api/invoices/<invoice_id>/reprocess", methods=["POST"])
@require_auth
def reprocess_single_invoice(invoice_id):
    """Re-parse a single invoice's PDF and update its data (#15).

    Unlike ?reprocess=true which wipes everything, this only re-parses
    the PDF for the specified invoice and updates its DB record.
    """
    conn = get_db()
    inv = conn.execute(
        "SELECT pdf_path FROM invoices WHERE id = ?", (invoice_id,)
    ).fetchone()
    if not inv:
        conn.close()
        abort(404)

    pdf_path = _resolve_pdf_path(inv["pdf_path"])
    if not pdf_path or not pdf_path.exists():
        conn.close()
        return jsonify({"error": "PDF file not found"}), 404

    try:
        parsed = parse_pdf(str(pdf_path))
    except ValueError as e:
        conn.close()
        return jsonify({"error": str(e)}), 422

    # Get vendor_id from existing invoice
    vendor_row = conn.execute(
        "SELECT vendor_id FROM invoices WHERE id = ?", (invoice_id,)
    ).fetchone()
    vendor_id = vendor_row["vendor_id"]

    store_invoice(conn, vendor_id, parsed, str(pdf_path), "", source="reprocess")
    conn.close()

    return jsonify({"success": True, "invoice_id": parsed.invoice_id})


# ---------------------------------------------------------------------------
# Vendor management (#19)
# ---------------------------------------------------------------------------

@app.route("/api/vendors/<int:vendor_id>", methods=["PUT"])
@require_auth
def update_vendor(vendor_id):
    """Update a vendor's name or email_domain (#19)."""
    data = request.get_json() or {}
    conn = get_db()
    existing = conn.execute(
        "SELECT id FROM vendors WHERE id = ?", (vendor_id,)
    ).fetchone()
    if not existing:
        conn.close()
        abort(404)

    sets = []
    values = []
    for field in ("name", "email_domain"):
        if field in data:
            sets.append(f"{field} = ?")
            values.append(data[field])
    if sets:
        values.append(vendor_id)
        conn.execute(
            f"UPDATE vendors SET {', '.join(sets)} WHERE id = ?",
            values
        )
        conn.commit()
    conn.close()
    return jsonify({"success": True})


@app.route("/api/vendors/<int:vendor_id>", methods=["DELETE"])
@require_auth
def delete_vendor(vendor_id):
    """Delete a vendor if it has no invoices (#19)."""
    conn = get_db()
    count = conn.execute(
        "SELECT COUNT(*) as c FROM invoices WHERE vendor_id = ?", (vendor_id,)
    ).fetchone()["c"]
    if count > 0:
        conn.close()
        return jsonify({"error": f"Cannot delete vendor with {count} invoice(s)"}), 400
    conn.execute("DELETE FROM vendors WHERE id = ?", (vendor_id,))
    conn.commit()
    conn.close()
    return jsonify({"success": True})


# ---------------------------------------------------------------------------
# Audit log (#20)
# ---------------------------------------------------------------------------

@app.route("/api/invoices/<invoice_id>/audit")
@require_auth
def get_audit_log(invoice_id):
    """Get audit log entries for an invoice (#20)."""
    conn = get_db()
    rows = conn.execute(
        "SELECT * FROM audit_log WHERE invoice_id = ? ORDER BY created_at DESC",
        (invoice_id,)
    ).fetchall()
    conn.close()
    return jsonify([dict(r) for r in rows])


# ---------------------------------------------------------------------------
# Data retention / archive (#25)
# ---------------------------------------------------------------------------

@app.route("/api/archive", methods=["POST"])
@require_auth
def archive_old_invoices():
    """Archive invoices older than a specified age (#25).

    Query params:
      older_than_days — default 730 (2 years)
    Moves old invoices to an archive directory and removes from active DB.
    """
    import shutil
    older_than = int(request.args.get("older_than_days", "730"))
    conn = get_db()
    rows = conn.execute(
        "SELECT id, pdf_path FROM invoices "
        "WHERE created_at < datetime('now', ?) "
        "ORDER BY created_at ASC",
        (f"-{older_than} days",)
    ).fetchall()

    archive_dir = DATA_DIR / "archive"
    archive_dir.mkdir(parents=True, exist_ok=True)

    archived = 0
    for r in rows:
        pdf_path = _resolve_pdf_path(r["pdf_path"])
        if pdf_path and pdf_path.exists():
            shutil.move(str(pdf_path), str(archive_dir / pdf_path.name))
        conn.execute("DELETE FROM invoices WHERE id = ?", (r["id"],))
        archived += 1
    conn.commit()
    conn.close()
    return jsonify({"success": True, "archived": archived})


# ---------------------------------------------------------------------------
# Format review queue API
# ---------------------------------------------------------------------------

@app.route("/api/reviews")
@require_auth
def list_reviews():
    """GET /api/reviews?status=pending — list reviews with invoice + vendor info."""
    status_filter = request.args.get("status")
    conn = get_db()
    reviews = get_review_list(conn, status_filter)
    conn.close()
    return jsonify(reviews)


@app.route("/api/reviews/<int:review_id>")
@require_auth
def get_review(review_id):
    """GET /api/reviews/<id> — full detail including raw text extraction."""
    conn = get_db()
    review = get_review_by_id(conn, review_id)
    conn.close()
    if not review:
        abort(404)

    # Type narrowing for the checker
    detail: dict = review  # type: ignore[assignment]

    # Extract raw text from the stored document
    raw_text = ""
    if detail.get("pdf_path"):
        raw_text = extract_raw_text_from_document(detail["pdf_path"])

    return jsonify({
        "review": detail,
        "raw_text": raw_text,
    })


@app.route("/api/reviews/<int:review_id>", methods=["PATCH"])
@require_admin
def patch_review(review_id):
    """PATCH /api/reviews/<id> — update status/notes (admin only)."""
    data = request.get_json() or {}
    conn = get_db()

    existing = conn.execute(
        "SELECT id FROM format_reviews WHERE id = ?", (review_id,)
    ).fetchone()
    if not existing:
        conn.close()
        abort(404)

    sets = []
    values = []
    for field in ("status", "notes"):
        if field in data:
            sets.append(f"{field} = ?")
            values.append(data[field])

    if sets:
        values.append(review_id)
        conn.execute(
            f"UPDATE format_reviews SET {', '.join(sets)} WHERE id = ?",
            values
        )
        conn.commit()

    conn.close()
    return jsonify({"success": True})


@app.route("/api/reviews/<int:review_id>/extract", methods=["POST"])
@require_admin
def extract_and_verify(review_id):
    """POST /api/reviews/<id>/extract — apply corrected field values to the
    linked invoice, audit-log it, and set review status=verified (admin only).

    Body: {field_overrides: {invoice_id, invoice_date, billing_period,
          new_charges, outstanding_balance, ...}}
    """
    data = request.get_json() or {}
    field_overrides = data.get("field_overrides", {})

    conn = get_db()

    review = conn.execute(
        "SELECT * FROM format_reviews WHERE id = ?", (review_id,)
    ).fetchone()
    if not review:
        conn.close()
        abort(404)

    invoice_id = review["invoice_id"]

    # Update the linked invoice with corrected values
    allowed_fields = {
        "invoice_id", "invoice_date", "billing_period",
        "is_credit_memo", "references_invoice",
        "partner_name", "partner_id", "partner_username",
        "previous_balance", "credit_card_surcharges",
        "payment_received", "new_charges", "outstanding_balance",
    }
    invoice_sets = []
    invoice_values = []
    changes = {}
    for field in allowed_fields:
        if field in field_overrides:
            val = field_overrides[field]
            if field == "is_credit_memo":
                val = 1 if val else 0
            if field == "invoice_id" and val != invoice_id:
                # Changing the invoice PK — FK constraints prevent a simple
                # UPDATE on the PK.  Instead: create the new row, repoint
                # children, then delete the old row.
                new_invoice_id = str(val)
                # Copy the existing invoice row to the new id
                conn.execute(
                    "INSERT OR IGNORE INTO invoices "
                    "(id, vendor_id, billing_period, invoice_date, is_credit_memo, "
                    " references_invoice, partner_name, partner_id, partner_username, "
                    " previous_balance, credit_card_surcharges, payment_received, "
                    " new_charges, outstanding_balance, source, email_message_id, pdf_path) "
                    "SELECT ?, vendor_id, billing_period, invoice_date, is_credit_memo, "
                    " references_invoice, partner_name, partner_id, partner_username, "
                    " previous_balance, credit_card_surcharges, payment_received, "
                    " new_charges, outstanding_balance, source, email_message_id, pdf_path "
                    "FROM invoices WHERE id = ?",
                    (new_invoice_id, invoice_id)
                )
                # Repoint child tables
                conn.execute(
                    "UPDATE customers SET invoice_id = ? WHERE invoice_id = ?",
                    (new_invoice_id, invoice_id)
                )
                conn.execute(
                    "UPDATE line_items SET invoice_id = ? WHERE invoice_id = ?",
                    (new_invoice_id, invoice_id)
                )
                # Repoint the review itself
                conn.execute(
                    "UPDATE format_reviews SET invoice_id = ? WHERE id = ?",
                    (new_invoice_id, review_id)
                )
                # Delete the old invoice row
                conn.execute(
                    "DELETE FROM invoices WHERE id = ?", (invoice_id,)
                )
                invoice_id = new_invoice_id
                changes[field] = new_invoice_id
                continue
            invoice_sets.append(f"{field} = ?")
            invoice_values.append(val)
            changes[field] = val

    if invoice_sets:
        invoice_values.append(invoice_id)
        conn.execute(
            f"UPDATE invoices SET {', '.join(invoice_sets)} WHERE id = ?",
            invoice_values
        )

    # Audit log
    from db import log_audit
    user_email = getattr(g, 'current_user_email', '') or ''
    log_audit(conn, invoice_id, g.current_user_id, user_email,
              "review_extract", changes)

    # Set review to verified
    conn.execute(
        "UPDATE format_reviews SET status = 'verified', "
        "reviewed_by = ?, reviewed_at = datetime('now') "
        "WHERE id = ?",
        (g.current_user_id, review_id)
    )
    conn.commit()
    conn.close()

    return jsonify({"success": True, "invoice_id": invoice_id})


@app.route("/api/formats")
@require_auth
def list_formats():
    """GET /api/formats — list registered formats per vendor."""
    conn = get_db()
    rows = conn.execute(
        "SELECT f.*, v.name as vendor_name "
        "FROM invoice_formats f "
        "JOIN vendors v ON f.vendor_id = v.id "
        "ORDER BY v.name, f.last_seen DESC"
    ).fetchall()
    conn.close()
    return jsonify([dict(r) for r in rows])


if __name__ == "__main__":
    init_db()
    port = int(os.environ.get("PORT", 8080))
    app.run(host="0.0.0.0", port=port, debug=True, use_reloader=False)
