"""
Tests for the Flask API endpoints (backlog #18).

Uses Flask's test client. Tests auth flow, invoice listing,
bulk endpoint, summary, CSV export, and health check.
"""
import sys
import os
import json
import pytest

sys.path.insert(0, os.path.dirname(__file__))

# Use a temp DB path before importing server
os.environ.setdefault("RENDER_PROJECT_DIR", "/tmp/vid_test")

from server import app, init_db
from db import get_db
from auth import get_password_hash

import tempfile
import pathlib

# Set up temp data dir
_tmp = tempfile.mkdtemp(prefix="vid_test_")
os.environ["RENDER_PROJECT_DIR"] = _tmp

# Re-import config with new path
import importlib
import config
importlib.reload(config)
import db as dbmod
dbmod.DB_PATH = pathlib.Path(_tmp) / "db" / "invoices.db"
dbmod.DB_PATH.parent.mkdir(parents=True, exist_ok=True)


@pytest.fixture
def client():
    """Flask test client with a fresh DB."""
    init_db()
    app.config["TESTING"] = True
    with app.test_client() as c:
        yield c


@pytest.fixture
def auth_token(client):
    """Register a user and return access token."""
    # Check if setup needed
    resp = client.get("/api/auth/setup-check")
    data = resp.get_json()
    if data and data.get("has_users"):
        # Login
        resp = client.post("/api/auth/login", json={
            "email": "admin@test.com", "password": "TestPass123!"
        })
    else:
        resp = client.post("/api/auth/register", json={
            "email": "admin@test.com",
            "password": "TestPass123!",
            "full_name": "Admin"
        })
    token = resp.get_json()["access_token"]
    return token


@pytest.fixture
def auth_headers(auth_token):
    return {"Authorization": f"Bearer {auth_token}"}


class TestHealthCheck:
    def test_health(self, client):
        resp = client.get("/api/health")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["status"] == "healthy"


class TestAuth:
    def test_setup_check_empty(self, client):
        resp = client.get("/api/auth/setup-check")
        assert resp.status_code == 200
        assert resp.get_json()["has_users"] is False

    def test_register_first_user_is_admin(self, client):
        resp = client.post("/api/auth/register", json={
            "email": "admin@test.com",
            "password": "TestPass123!",
            "full_name": "Admin"
        })
        assert resp.status_code == 201
        data = resp.get_json()
        assert data["user"]["is_admin"] is True

    def test_register_second_user_not_admin(self, client, auth_token):
        resp = client.post("/api/auth/register", json={
            "email": "user2@test.com",
            "password": "TestPass456!",
            "full_name": "User2"
        })
        assert resp.status_code == 201
        assert resp.get_json()["user"]["is_admin"] is False

    def test_login_success(self, client, auth_token):
        resp = client.post("/api/auth/login", json={
            "email": "admin@test.com",
            "password": "TestPass123!"
        })
        assert resp.status_code == 200
        assert "access_token" in resp.get_json()

    def test_login_wrong_password(self, client, auth_token):
        resp = client.post("/api/auth/login", json={
            "email": "admin@test.com",
            "password": "WrongPassword!"
        })
        assert resp.status_code == 401

    def test_protected_without_token(self, client):
        resp = client.get("/api/invoices")
        assert resp.status_code == 401


class TestInvoices:
    def test_get_invoices_empty(self, client, auth_headers):
        resp = client.get("/api/invoices", headers=auth_headers)
        assert resp.status_code == 200
        assert resp.get_json() == []

    def test_get_bulk_empty(self, client, auth_headers):
        resp = client.get("/api/invoices/bulk", headers=auth_headers)
        assert resp.status_code == 200
        assert resp.get_json() == {"invoices": []}


class TestSummary:
    def test_summary_no_invoices(self, client, auth_headers):
        resp = client.get("/api/summary", headers=auth_headers)
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["count"] == 0


class TestCSVExport:
    def test_export_invoices(self, client, auth_headers):
        resp = client.get("/api/export/invoices", headers=auth_headers)
        assert resp.status_code == 200
        assert "text/csv" in resp.content_type
        assert b"Invoice ID" in resp.data

    def test_export_customers(self, client, auth_headers):
        resp = client.get("/api/export/customers", headers=auth_headers)
        assert resp.status_code == 200
        assert b"Customer" in resp.data

    def test_export_line_items(self, client, auth_headers):
        resp = client.get("/api/export/line-items", headers=auth_headers)
        assert resp.status_code == 200
        assert b"Item" in resp.data


# ---------------------------------------------------------------------------
# Format Recognition Tests
# ---------------------------------------------------------------------------


class TestComputeFingerprint:
    def test_intermedia_fingerprint(self):
        from format_recognition import compute_fingerprint
        text = "Invoice #1234567 Billing Period: Jun 01, 2026 - Jun 30, 2026"
        fp = compute_fingerprint(text)
        assert "billing period" in fp
        assert "invoice" in fp

    def test_barracuda_fingerprint(self):
        from format_recognition import compute_fingerprint
        text = "Invoice #INV26514789 Subtotal $6,560.00 Amount Due $6,560.00"
        fp = compute_fingerprint(text)
        assert "subtotal" in fp
        assert "amount due" in fp
        assert "invoice" in fp

    def test_flyover_fingerprint(self):
        from format_recognition import compute_fingerprint
        text = "Invoice no.: 250541 Invoice date: 05/31/2026 Balance due $0.00"
        fp = compute_fingerprint(text)
        assert "invoice no" in fp
        assert "balance due" in fp

    def test_extraspace_fingerprint(self):
        from format_recognition import compute_fingerprint
        text = "Transaction Number: 381091629 Payment Date: 07/09/2026 Payment Total: $186.20"
        fp = compute_fingerprint(text)
        assert "transaction number" in fp
        assert "payment date" in fp
        assert "payment total" in fp

    def test_empty_text_fingerprint(self):
        from format_recognition import compute_fingerprint
        assert compute_fingerprint("") == "__empty__"

    def test_no_match_fingerprint(self):
        from format_recognition import compute_fingerprint
        fp = compute_fingerprint("quux barzop glorf snizzleflomp wibble")
        assert fp == "__unknown__"

    def test_deterministic_sorting(self):
        from format_recognition import compute_fingerprint
        fp1 = compute_fingerprint("Invoice total balance due new charges")
        fp2 = compute_fingerprint("total new charges balance due invoice")
        assert fp1 == fp2


class TestFormatRegistration:
    def test_register_new_format(self, client, auth_headers):
        from db import get_db
        from format_recognition import compute_fingerprint, register_format

        # First create a vendor via the API
        resp = client.post("/api/upload", headers=auth_headers, data={
            "vendor": "TestVendor",
        })
        # upload needs a file, so let's just add a vendor directly
        conn = get_db()
        cursor = conn.execute(
            "INSERT INTO vendors (name, email_domain) VALUES (?, ?)",
            ("TestVendor", "testvendor.com")
        )
        vendor_id = cursor.lastrowid
        conn.commit()

        fp = compute_fingerprint("Invoice #123 Billing Period Jan")
        reg = register_format(conn, vendor_id, fp, "pdf_parser")
        assert reg["is_new"] is True
        assert reg["status"] == "new"

        # Second register should not be new
        reg2 = register_format(conn, vendor_id, fp, "pdf_parser")
        assert reg2["is_new"] is False
        conn.close()

    def test_register_format_twice_not_new(self, client, auth_headers):
        from db import get_db
        from format_recognition import compute_fingerprint, register_format, is_recognized_format

        conn = get_db()
        cursor = conn.execute(
            "INSERT INTO vendors (name, email_domain) VALUES (?, ?)",
            ("FormatVendor", "fmt.com")
        )
        vendor_id = cursor.lastrowid
        fp = compute_fingerprint("Total new charges payment received")
        register_format(conn, vendor_id, fp, "pdf_parser")

        # After one registration, it's still 'new', not 'recognized'
        assert is_recognized_format(conn, vendor_id, fp) is False

        # Change status to 'recognized' manually
        conn.execute(
            "UPDATE invoice_formats SET status = 'recognized' WHERE vendor_id = ?",
            (vendor_id,)
        )
        conn.commit()
        assert is_recognized_format(conn, vendor_id, fp) is True
        conn.close()


class TestReviewQueueAPI:
    def test_list_reviews_empty(self, client, auth_headers):
        resp = client.get("/api/reviews", headers=auth_headers)
        assert resp.status_code == 200
        assert resp.get_json() == []

    def test_list_reviews_filter_by_status(self, client, auth_headers):
        resp = client.get("/api/reviews?status=pending", headers=auth_headers)
        assert resp.status_code == 200
        assert resp.get_json() == []

    def test_get_review_not_found(self, client, auth_headers):
        resp = client.get("/api/reviews/9999", headers=auth_headers)
        assert resp.status_code == 404

    def test_patch_review_requires_admin(self, client, auth_token):
        headers = {"Authorization": f"Bearer {auth_token}"}
        # First user is admin, so register a non-admin user
        resp = client.post("/api/auth/register", json={
            "email": "nonadmin@test.com",
            "password": "TestPass456!",
            "full_name": "NonAdmin"
        })
        token = resp.get_json()["access_token"]
        nonadmin_headers = {"Authorization": f"Bearer {token}"}

        resp = client.patch("/api/reviews/1", json={"status": "in_review"},
                            headers=nonadmin_headers)
        assert resp.status_code == 403
        assert "Admin access required" in resp.get_json()["error"]

    def test_create_review_and_list(self, client, auth_headers):
        from db import get_db
        from format_recognition import create_review

        conn = get_db()
        cursor = conn.execute(
            "INSERT INTO vendors (name, email_domain) VALUES (?, ?)",
            ("ReviewVendor", "rv.com")
        )
        vendor_id = cursor.lastrowid

        # Create an invoice first
        inv_id = "test_inv_001"
        conn.execute(
            "INSERT INTO invoices (id, vendor_id, source, new_charges, outstanding_balance) "
            "VALUES (?, ?, 'email_unparsed', 0, 0)",
            (inv_id, vendor_id)
        )
        conn.commit()

        # Create a review
        rid = create_review(conn, inv_id, vendor_id, "no_parser",
                            extracted_data={"vendor": "ReviewVendor"})
        conn.close()

        resp = client.get("/api/reviews?status=pending", headers=auth_headers)
        assert resp.status_code == 200
        data = resp.get_json()
        assert len(data) >= 1
        review = data[0]
        assert review["invoice_id"] == inv_id
        assert review["detection_reason"] == "no_parser"
        assert review["vendor_name"] == "ReviewVendor"
        assert review["extracted_data"]["vendor"] == "ReviewVendor"

    def test_extract_and_verify(self, client, auth_headers):
        from db import get_db
        from format_recognition import create_review

        conn = get_db()
        cursor = conn.execute(
            "INSERT INTO vendors (name, email_domain) VALUES (?, ?)",
            ("ExtractVendor", "ext.com")
        )
        vendor_id = cursor.lastrowid

        inv_id = "test_inv_extract"
        conn.execute(
            "INSERT INTO invoices (id, vendor_id, source, new_charges, outstanding_balance) "
            "VALUES (?, ?, 'email_unparsed', 0, 0)",
            (inv_id, vendor_id)
        )
        conn.commit()

        rid = create_review(conn, inv_id, vendor_id, "no_parser")
        conn.close()

        # Extract/verify
        resp = client.post(
            f"/api/reviews/{rid}/extract",
            headers=auth_headers,
            json={
                "field_overrides": {
                    "new_charges": 1500.00,
                    "outstanding_balance": 1500.00,
                    "billing_period": "Jun 2026",
                }
            }
        )
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["success"] is True

        # Verify the invoice was updated
        conn = get_db()
        inv = conn.execute(
            "SELECT * FROM invoices WHERE id = ?", (inv_id,)
        ).fetchone()
        assert inv["new_charges"] == 1500.00
        assert inv["outstanding_balance"] == 1500.00
        assert inv["billing_period"] == "Jun 2026"

        # Verify the review is now verified
        review = conn.execute(
            "SELECT status FROM format_reviews WHERE id = ?", (rid,)
        ).fetchone()
        assert review["status"] == "verified"

        # Verify audit log was created
        audit = conn.execute(
            "SELECT * FROM audit_log WHERE invoice_id = ?", (inv_id,)
        ).fetchall()
        assert len(audit) >= 1
        assert audit[0]["action"] == "review_extract"
        conn.close()

    def test_extract_verify_changes_invoice_id(self, client, auth_headers):
        from db import get_db
        from format_recognition import create_review

        conn = get_db()
        cursor = conn.execute(
            "INSERT INTO vendors (name, email_domain) VALUES (?, ?)",
            ("RenameVendor", "ren.com")
        )
        vendor_id = cursor.lastrowid

        inv_id = "old_inv_id"
        conn.execute(
            "INSERT INTO invoices (id, vendor_id, source, new_charges, outstanding_balance) "
            "VALUES (?, ?, 'email_unparsed', 0, 0)",
            (inv_id, vendor_id)
        )
        conn.commit()

        rid = create_review(conn, inv_id, vendor_id, "no_parser")
        conn.close()

        resp = client.post(
            f"/api/reviews/{rid}/extract",
            headers=auth_headers,
            json={
                "field_overrides": {
                    "invoice_id": "corrected_inv_002",
                    "new_charges": 500.00,
                }
            }
        )
        assert resp.status_code == 200

        # Verify old invoice id is gone, new exists
        conn = get_db()
        old = conn.execute(
            "SELECT 1 FROM invoices WHERE id = ?", ("old_inv_id",)
        ).fetchone()
        assert old is None
        new = conn.execute(
            "SELECT 1 FROM invoices WHERE id = ?", ("corrected_inv_002",)
        ).fetchone()
        assert new is not None
        conn.close()

    def test_auto_extract_no_api_key(self, client, auth_headers, monkeypatch):
        """Returns 503 when XAI_API_KEY is not set."""
        from db import get_db
        from format_recognition import create_review

        monkeypatch.delenv("XAI_API_KEY", raising=False)

        conn = get_db()
        try:
            suffix = "autoext_no_key_xyz"
            cursor = conn.execute(
                "INSERT INTO vendors (name, email_domain) VALUES (?, ?)",
                (f"AutoExtVendor_{suffix}", f"aek-{suffix}.com"),
            )
            vendor_id = cursor.lastrowid
            inv_id = f"test_inv_autoext_nokey_{suffix}"
            conn.execute(
                "INSERT INTO invoices (id, vendor_id, source, new_charges, outstanding_balance) "
                "VALUES (?, ?, 'email_unparsed', 0, 0)",
                (inv_id, vendor_id),
            )
            conn.commit()
            rid = create_review(conn, inv_id, vendor_id, "no_parser")
        finally:
            conn.close()

        resp = client.post(
            f"/api/reviews/{rid}/auto-extract",
            headers=auth_headers,
        )
        assert resp.status_code == 503
        data = resp.get_json()
        assert "XAI_API_KEY" in data.get("error", "")

    def test_auto_extract_no_document_text(self, client, auth_headers, monkeypatch):
        """Returns 400 when review has no usable document text (no pdf_path)."""
        from db import get_db
        from format_recognition import create_review

        # Key must be set so we don't short-circuit on 503
        monkeypatch.setenv("XAI_API_KEY", "test-key-not-real")

        conn = get_db()
        try:
            suffix = "autoext_nodoc_xyz"
            cursor = conn.execute(
                "INSERT INTO vendors (name, email_domain) VALUES (?, ?)",
                (f"AutoExtNoDoc_{suffix}", f"aend-{suffix}.com"),
            )
            vendor_id = cursor.lastrowid
            inv_id = f"test_inv_autoext_nodoc_{suffix}"
            # No pdf_path — extract_raw_text has nothing to read
            conn.execute(
                "INSERT INTO invoices (id, vendor_id, source, new_charges, outstanding_balance) "
                "VALUES (?, ?, 'email_unparsed', 0, 0)",
                (inv_id, vendor_id),
            )
            conn.commit()
            rid = create_review(conn, inv_id, vendor_id, "no_parser")
        finally:
            conn.close()

        resp = client.post(
            f"/api/reviews/{rid}/auto-extract",
            headers=auth_headers,
        )
        assert resp.status_code == 400
        data = resp.get_json()
        assert "No document text" in data.get("error", "")

    def test_auto_extract_success(self, client, auth_headers, monkeypatch):
        """Mocks llm_extractor and returns extracted_fields on success."""
        from db import get_db
        from format_recognition import create_review
        from unittest.mock import patch
        import pathlib
        import config as cfg

        monkeypatch.setenv("XAI_API_KEY", "test-key-not-real")

        sample_fields = {
            "invoice_id": "INV-9001",
            "billing_period": "Jul 2026",
            "invoice_date": "2026-07-01",
            "due_date": "2026-07-31",
            "vendor_name": "AutoExt Success Vendor",
            "previous_balance": 0,
            "credit_card_surcharges": 0,
            "payment_received": 0,
            "new_charges": 250.0,
            "outstanding_balance": 250.0,
            "customers": [],
            "line_items": [],
        }

        conn = get_db()
        try:
            suffix = "autoext_ok_xyz789"
            vendor_name = f"AutoExtOK_{suffix}"
            cursor = conn.execute(
                "INSERT INTO vendors (name, email_domain) VALUES (?, ?)",
                (vendor_name, f"aeok-{suffix}.com"),
            )
            vendor_id = cursor.lastrowid
            inv_id = f"test_inv_autoext_ok_{suffix}"

            # Write a tiny text document so raw_text is non-empty
            inv_dir = pathlib.Path(cfg.DATA_DIR) / "invoices" / vendor_name
            inv_dir.mkdir(parents=True, exist_ok=True)
            doc_path = inv_dir / "sample.txt"
            doc_path.write_text(
                "Invoice INV-9001\nAmount due: $250.00\n",
                encoding="utf-8",
            )
            rel_path = str(doc_path.relative_to(cfg.DATA_DIR))

            conn.execute(
                "INSERT INTO invoices "
                "(id, vendor_id, source, new_charges, outstanding_balance, pdf_path) "
                "VALUES (?, ?, 'email_unparsed', 0, 0, ?)",
                (inv_id, vendor_id, rel_path),
            )
            conn.commit()
            rid = create_review(conn, inv_id, vendor_id, "no_parser")
        finally:
            conn.close()

        with patch(
            "server.extract_invoice_fields",
            return_value=sample_fields,
        ) as mock_extract:
            resp = client.post(
                f"/api/reviews/{rid}/auto-extract",
                headers=auth_headers,
            )
            assert resp.status_code == 200
            data = resp.get_json()
            assert data["success"] is True
            assert data["extracted_fields"]["invoice_id"] == "INV-9001"
            assert data["extracted_fields"]["new_charges"] == 250.0
            mock_extract.assert_called_once()
            # vendor_name from review should be passed through
            args, kwargs = mock_extract.call_args
            assert vendor_name in (args[1] if len(args) > 1 else kwargs.get("vendor_name", ""))

    def test_list_formats(self, client, auth_headers):
        from db import get_db
        from format_recognition import compute_fingerprint, register_format

        conn = get_db()
        cursor = conn.execute(
            "INSERT INTO vendors (name, email_domain) VALUES (?, ?)",
            ("FormatListVendor", "flv.com")
        )
        vendor_id = cursor.lastrowid

        fp = compute_fingerprint("Invoice #X Billing Period Y Total $100")
        register_format(conn, vendor_id, fp, "pdf_parser")
        conn.close()

        resp = client.get("/api/formats", headers=auth_headers)
        assert resp.status_code == 200
        data = resp.get_json()
        assert len(data) >= 1
        fmt = next(f for f in data if f["vendor_name"] == "FormatListVendor")
        assert fmt["format_fingerprint"] == fp
        assert fmt["status"] == "new"


class TestInvoiceStatus:
    """Tests for A/P invoice status lifecycle endpoints."""

    def test_update_status(self, client, auth_headers):
        from db import get_db
        conn = get_db()
        cursor = conn.execute(
            "INSERT INTO vendors (name) VALUES (?)", ("StatusVendor",)
        )
        vendor_id = cursor.lastrowid
        conn.execute(
            "INSERT INTO invoices (id, vendor_id, source, new_charges, outstanding_balance) "
            "VALUES (?, ?, 'manual', 100, 50)",
            ("inv_status_1", vendor_id)
        )
        conn.commit()
        conn.close()

        resp = client.patch(
            "/api/invoices/inv_status_1/status",
            headers=auth_headers,
            json={"status": "approved"}
        )
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["success"] is True
        assert data["changes"]["status"]["to"] == "approved"

        # Verify DB
        conn = get_db()
        inv = conn.execute(
            "SELECT status FROM invoices WHERE id = ?", ("inv_status_1",)
        ).fetchone()
        assert inv["status"] == "approved"
        conn.close()

    def test_update_status_invalid(self, client, auth_headers):
        resp = client.patch(
            "/api/invoices/nonexistent/status",
            headers=auth_headers,
            json={"status": "approved"}
        )
        assert resp.status_code == 404

    def test_update_status_bad_value(self, client, auth_headers):
        from db import get_db
        conn = get_db()
        cursor = conn.execute(
            "INSERT INTO vendors (name) VALUES (?)", ("BadValVendor",)
        )
        vendor_id = cursor.lastrowid
        conn.execute(
            "INSERT INTO invoices (id, vendor_id, source, new_charges, outstanding_balance) "
            "VALUES (?, ?, 'manual', 100, 50)",
            ("inv_bad_status", vendor_id)
        )
        conn.commit()
        conn.close()

        resp = client.patch(
            "/api/invoices/inv_bad_status/status",
            headers=auth_headers,
            json={"status": "invalid_status"}
        )
        assert resp.status_code == 400

    def test_bulk_update_status(self, client, auth_headers):
        from db import get_db
        conn = get_db()
        cursor = conn.execute(
            "INSERT INTO vendors (name) VALUES (?)", ("BulkVendor",)
        )
        vendor_id = cursor.lastrowid
        ids = ["inv_bulk_1", "inv_bulk_2", "inv_bulk_3"]
        for i, inv_id in enumerate(ids):
            conn.execute(
                "INSERT INTO invoices (id, vendor_id, source, new_charges, outstanding_balance) "
                "VALUES (?, ?, 'manual', 100, 50)",
                (inv_id, vendor_id)
            )
        conn.commit()
        conn.close()

        resp = client.patch(
            "/api/invoices/bulk-status",
            headers=auth_headers,
            json={"ids": ids, "status": "approved"}
        )
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["success"] is True
        assert data["updated"] == 3

        # Verify all updated
        conn = get_db()
        for inv_id in ids:
            inv = conn.execute(
                "SELECT status FROM invoices WHERE id = ?", (inv_id,)
            ).fetchone()
            assert inv["status"] == "approved"
        conn.close()

    def test_bulk_status_requires_admin(self, client):
        """Register admin + non-admin to verify admin gate works."""
        # First register the first user (becomes admin automatically)
        resp = client.post("/api/auth/register", json={
            "email": "admin_bulk@test.com",
            "password": "TestPass123!",
            "full_name": "AdminUser"
        })
        assert resp.status_code == 201
        # Now register a second user (NOT admin)
        resp = client.post("/api/auth/register", json={
            "email": "nonadmin_bulk@test.com",
            "password": "TestPass123!",
            "full_name": "NonAdminUser"
        })
        assert resp.status_code == 201, f"Failed to register: {resp.get_json()}"
        data = resp.get_json()
        assert data["user"]["is_admin"] is False, "Second user should not be admin"
        headers = {"Authorization": f"Bearer {data['access_token']}"}

        resp = client.patch(
            "/api/invoices/bulk-status",
            headers=headers,
            json={"ids": ["x"], "status": "paid"}
        )
        assert resp.status_code == 403


class TestVendorDetail:
    """Tests for vendor detail with rollups."""

    def test_vendor_detail_with_rollups(self, client, auth_headers):
        from db import get_db
        conn = get_db()
        cursor = conn.execute(
            "INSERT INTO vendors (name, email_domain) VALUES (?, ?)",
            ("DetailVendor", "detail.com")
        )
        vendor_id = cursor.lastrowid
        conn.execute(
            "INSERT INTO invoices (id, vendor_id, source, new_charges, outstanding_balance, "
            "payment_received, status, due_date) "
            "VALUES (?, ?, 'manual', 1000, 500, 200, 'received', '2026-07-15')",
            ("inv_detail_1", vendor_id)
        )
        conn.execute(
            "INSERT INTO invoices (id, vendor_id, source, new_charges, outstanding_balance, "
            "payment_received, status, due_date) "
            "VALUES (?, ?, 'manual', 2000, 0, 2000, 'paid', '2026-06-01')",
            ("inv_detail_2", vendor_id)
        )
        conn.commit()
        conn.close()

        resp = client.get(f"/api/vendors/{vendor_id}", headers=auth_headers)
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["vendor"]["name"] == "DetailVendor"
        assert data["totals"]["invoice_count"] == 2
        assert data["totals"]["total_new_charges"] == 3000
        assert data["totals"]["total_outstanding"] == 500
        assert len(data["invoices"]) == 2
        assert len(data["formats"]) == 0

    def test_vendor_detail_not_found(self, client, auth_headers):
        resp = client.get("/api/vendors/99999", headers=auth_headers)
        assert resp.status_code == 404


class TestDashboardEndpoint:
    """Tests for the A/P dashboard summary endpoint."""

    def test_dashboard_returns_summary(self, client, auth_headers):
        from db import get_db
        conn = get_db()
        cursor = conn.execute(
            "INSERT INTO vendors (name) VALUES (?)", ("DashVendor_uniq",)
        )
        vendor_id = cursor.lastrowid
        conn.execute(
            "INSERT INTO invoices (id, vendor_id, source, new_charges, outstanding_balance, "
            "status, due_date, created_at) "
            "VALUES (?, ?, 'manual', 1000, 500, 'received', '2026-07-15', '2026-07-10')",
            ("inv_dash_rec", vendor_id)
        )
        conn.execute(
            "INSERT INTO invoices (id, vendor_id, source, new_charges, outstanding_balance, "
            "status, due_date, created_at) "
            "VALUES (?, ?, 'manual', 2000, 0, 'paid', '2026-06-01', '2026-07-11')",
            ("inv_dash_paid", vendor_id)
        )
        conn.commit()
        conn.close()

        resp = client.get("/api/dashboard", headers=auth_headers)
        assert resp.status_code == 200
        data = resp.get_json()
        assert "summary" in data
        assert "aging" in data
        assert "recent_invoices" in data
        assert "monthly_spend" in data
        assert "status_counts" in data


class TestInvoiceFilters:
    """Tests for enhanced invoice filtering."""

    def test_filter_by_status(self, client, auth_headers):
        from db import get_db
        conn = get_db()
        cursor = conn.execute(
            "INSERT INTO vendors (name) VALUES (?)", ("FilterVendor_xyz123",)
        )
        vendor_id = cursor.lastrowid
        conn.execute(
            "INSERT INTO invoices (id, vendor_id, source, new_charges, outstanding_balance, status) "
            "VALUES (?, ?, 'manual', 100, 50, 'received')",
            ("inv_filt_rec_1", vendor_id)
        )
        conn.execute(
            "INSERT INTO invoices (id, vendor_id, source, new_charges, outstanding_balance, status) "
            "VALUES (?, ?, 'manual', 200, 100, 'approved')",
            ("inv_filt_app_1", vendor_id)
        )
        conn.commit()
        conn.close()

        resp = client.get("/api/invoices?status=approved&vendor=FilterVendor_xyz123", headers=auth_headers)
        assert resp.status_code == 200
        data = resp.get_json()
        # At least our approved invoice is in the results
        ids = [d["id"] for d in data]
        assert "inv_filt_app_1" in ids
        assert "inv_filt_rec_1" not in ids

    def test_sort_by_due_date(self, client, auth_headers):
        from db import get_db
        conn = get_db()
        cursor = conn.execute(
            "INSERT INTO vendors (name) VALUES (?)", ("SortVendor_xyz789",)
        )
        vendor_id = cursor.lastrowid
        conn.execute(
            "INSERT INTO invoices (id, vendor_id, source, new_charges, outstanding_balance, "
            "status, due_date) VALUES (?, ?, 'manual', 100, 50, 'received', '2026-08-01')",
            ("inv_sort_aug", vendor_id)
        )
        conn.execute(
            "INSERT INTO invoices (id, vendor_id, source, new_charges, outstanding_balance, "
            "status, due_date) VALUES (?, ?, 'manual', 200, 100, 'received', '2026-07-01')",
            ("inv_sort_jul", vendor_id)
        )
        conn.commit()
        conn.close()

        resp = client.get("/api/invoices?sort_field=due_date&sort_dir=asc&vendor=SortVendor_xyz789", headers=auth_headers)
        assert resp.status_code == 200
        data = resp.get_json()
        # Should be sorted by due_date asc, so inv_sort_jul (2026-07-01) first
        assert len(data) == 2
        assert data[0]["id"] == "inv_sort_jul"
        assert data[1]["id"] == "inv_sort_aug"


class TestEmailsEndpoint:
    """GET /api/emails — auth gate, filters, pagination, new columns."""

    def _seed_emails(self, suffix=""):
        """Seed once per call using unique keys so shared-DB suite stays clean."""
        from db import get_db
        conn = get_db()
        try:
            vendor_name = f"EmailLogVendor_{suffix or 'base'}"
            row = conn.execute(
                "SELECT id FROM vendors WHERE name = ?", (vendor_name,)
            ).fetchone()
            if row:
                vendor_id = row["id"]
            else:
                cursor = conn.execute(
                    "INSERT INTO vendors (name) VALUES (?)",
                    (vendor_name,),
                )
                vendor_id = cursor.lastrowid

            inv_id = f"inv_email_log_{suffix or 'base'}"
            conn.execute(
                "INSERT OR IGNORE INTO invoices (id, vendor_id, source, new_charges, "
                "outstanding_balance, status, pdf_path) "
                "VALUES (?, ?, 'email', 10, 10, 'received', ?)",
                (inv_id, vendor_id, f"invoices/{vendor_name}/a.pdf"),
            )

            # historical skinny row (NULL new columns)
            hist_id = f"<hist@{suffix or 'base'}.test>"
            conn.execute(
                "INSERT OR IGNORE INTO processed_emails "
                "(message_id, vendor_name, filename, processed_at) "
                "VALUES (?, ?, ?, datetime('now', '-2 hours'))",
                (hist_id, "OldVendor", "old.pdf"),
            )

            seeds = [
                (f"<msg-parsed@{suffix or 'base'}.test>", vendor_name, "a.pdf", inv_id,
                 "Invoice A", "a@v.com", "2026-07-10", 1, "parsed"),
                (f"<msg-unparsed@{suffix or 'base'}.test>", vendor_name, "b.pdf", None,
                 "Invoice B", "b@v.com", "2026-07-11", 1, "unparsed"),
                (f"<msg-none@{suffix or 'base'}.test>", vendor_name, None, None,
                 "No Att", "c@v.com", "2026-07-12", 0, "no_attachment"),
                (f"<msg-failed@{suffix or 'base'}.test>", vendor_name, "c.pdf", None,
                 "Failed", "d@v.com", "2026-07-13", 1, "failed"),
            ]
            for mid, vn, fn, iid, subj, frm, rd, ac, ps in seeds:
                conn.execute(
                    "INSERT OR REPLACE INTO processed_emails "
                    "(message_id, vendor_name, filename, invoice_id, processed_at, "
                    " subject, from_header, received_date, attachment_count, parse_status) "
                    "VALUES (?, ?, ?, ?, datetime('now'), ?, ?, ?, ?, ?)",
                    (mid, vn, fn, iid, subj, frm, rd, ac, ps),
                )
            conn.commit()
            return {
                "hist_id": hist_id,
                "parsed_id": seeds[0][0],
                "unparsed_id": seeds[1][0],
                "inv_id": inv_id,
            }
        finally:
            conn.close()

    def test_requires_auth(self, client):
        resp = client.get("/api/emails")
        assert resp.status_code == 401

    def test_list_newest_first(self, client, auth_headers):
        ids = self._seed_emails(suffix="list")
        resp = client.get("/api/emails?limit=100", headers=auth_headers)
        assert resp.status_code == 200
        data = resp.get_json()
        assert "emails" in data
        assert data["total"] >= 5
        assert isinstance(data["emails"], list)
        msgs = {e["message_id"]: e for e in data["emails"]}
        assert ids["hist_id"] in msgs
        hist = msgs[ids["hist_id"]]
        assert hist["parse_status"] in (None, "")
        parsed = msgs[ids["parsed_id"]]
        assert parsed["parse_status"] == "parsed"
        assert parsed["invoice_id"] == ids["inv_id"]
        assert parsed["invoice_status"] == "received"
        assert parsed["subject"] == "Invoice A"

    def test_filter_parse_status(self, client, auth_headers):
        ids = self._seed_emails(suffix="filter")
        resp = client.get(
            "/api/emails?parse_status=unparsed&limit=100",
            headers=auth_headers,
        )
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["total"] >= 1
        assert all(e["parse_status"] == "unparsed" for e in data["emails"])
        assert any(e["message_id"] == ids["unparsed_id"] for e in data["emails"])

    def test_filter_invalid_status(self, client, auth_headers):
        resp = client.get("/api/emails?parse_status=bogus", headers=auth_headers)
        assert resp.status_code == 400

    def test_pagination(self, client, auth_headers):
        self._seed_emails(suffix="page")
        # filter by vendor-ish subject logistic not available; just check page sizes
        resp = client.get("/api/emails?limit=2&offset=0", headers=auth_headers)
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["limit"] == 2
        assert data["offset"] == 0
        assert len(data["emails"]) <= 2
        assert data["total"] >= 2

        resp2 = client.get("/api/emails?limit=2&offset=2", headers=auth_headers)
        assert resp2.status_code == 200
        data2 = resp2.get_json()
        assert len(data2["emails"]) <= 2
        if data["emails"] and data2["emails"]:
            ids1 = {e["message_id"] for e in data["emails"]}
            ids2 = {e["message_id"] for e in data2["emails"]}
            assert ids1.isdisjoint(ids2)


class TestIngestProcessedEmailsColumns:
    """ingest.py must populate the enriched processed_emails columns."""

    def test_html_parsed_sets_parsed_status(self, client, auth_headers, monkeypatch):
        from db import get_db
        from ingest import process_email

        class FakeParsed:
            invoice_id = "html_parsed_001"
            billing_period = "Jul 2026"
            invoice_date = "2026-07-01"
            is_credit_memo = False
            references_invoice = None
            partner_name = ""
            partner_id = ""
            partner_username = ""
            previous_balance = 0
            credit_card_surcharges = 0
            payment_received = 0
            new_charges = 12.5
            outstanding_balance = 12.5
            customers = []
            line_items = []

        import ingest as ingest_mod
        monkeypatch.setattr(ingest_mod, "parse_html_invoice", lambda *a, **k: FakeParsed())
        monkeypatch.setattr(ingest_mod, "extract_vendor", lambda *a, **k: ("FakeHTMLVendor", True))
        monkeypatch.setattr(ingest_mod, "compute_fingerprint", lambda t: "fp")
        monkeypatch.setattr(ingest_mod, "register_format", lambda *a, **k: {"is_new": False})
        monkeypatch.setattr(ingest_mod, "_send_new_invoice_notification", lambda *a, **k: None)
        monkeypatch.setattr(ingest_mod, "_send_confirmation_reply", lambda *a, **k: None)

        conn = get_db()
        try:
            email_data = {
                "message_id": "<ingest-html-parsed@test>",
                "subject": "FW: Your receipt from FakeHTMLVendor",
                "from": "jay@example.com",
                "body_html": "<html><body>Receipt</body></html>",
                "body_text": "Receipt",
                "received_date": "2026-07-10 12:00:00",
                "attachments": [],
            }
            process_email(conn, email_data)
            row = conn.execute(
                "SELECT * FROM processed_emails WHERE message_id = ?",
                (email_data["message_id"],),
            ).fetchone()
        finally:
            conn.close()
        assert row is not None
        assert row["parse_status"] == "parsed"
        assert row["subject"] == email_data["subject"]
        assert row["from_header"] == email_data["from"]
        assert row["received_date"] == email_data["received_date"]
        assert row["attachment_count"] == 0
        assert row["invoice_id"] == "html_parsed_001"

    def test_html_unparsed_sets_no_attachment(self, client, auth_headers, monkeypatch):
        from db import get_db
        from ingest import process_email
        import ingest as ingest_mod

        def boom(*a, **k):
            raise ValueError("unknown format")

        monkeypatch.setattr(ingest_mod, "parse_html_invoice", boom)
        monkeypatch.setattr(ingest_mod, "extract_vendor", lambda *a, **k: ("UnknownVendorHtml", False))
        monkeypatch.setattr(ingest_mod, "_notify_unknown_format", lambda *a, **k: None)
        monkeypatch.setattr(ingest_mod, "create_review", lambda *a, **k: None)

        conn = get_db()
        try:
            email_data = {
                "message_id": "<ingest-html-unparsed@test>",
                "subject": "Random receipt",
                "from": "someone@example.com",
                "body_html": "<html>no known structure</html>",
                "body_text": "no known structure",
                "received_date": "2026-07-11 09:00:00",
                "attachments": [],
            }
            process_email(conn, email_data)
            row = conn.execute(
                "SELECT * FROM processed_emails WHERE message_id = ?",
                (email_data["message_id"],),
            ).fetchone()
        finally:
            conn.close()
        assert row is not None
        assert row["parse_status"] == "no_attachment"
        assert row["attachment_count"] == 0
        assert row["subject"] == "Random receipt"
        assert row["invoice_id"]  # unparsed invoice created

    def test_pdf_unparsed_sets_unparsed(self, client, auth_headers, monkeypatch):
        from db import get_db
        from ingest import process_email
        import ingest as ingest_mod

        def boom(*a, **k):
            raise ValueError("unknown pdf")

        monkeypatch.setattr(ingest_mod, "parse_pdf", boom)
        monkeypatch.setattr(ingest_mod, "extract_vendor", lambda *a, **k: ("PdfUnparsedVendorX", True))
        monkeypatch.setattr(ingest_mod, "_notify_unknown_format", lambda *a, **k: None)
        monkeypatch.setattr(ingest_mod, "create_review", lambda *a, **k: None)

        conn = get_db()
        try:
            email_data = {
                "message_id": "<ingest-pdf-unparsed@test>",
                "subject": "FW: Invoice",
                "from": "vendor@pdf.com",
                "body_html": "",
                "body_text": "",
                "received_date": "2026-07-12",
                "attachments": [{"filename": "mystery.pdf", "bytes": b"%PDF-1.4 fake"}],
            }
            process_email(conn, email_data)
            row = conn.execute(
                "SELECT * FROM processed_emails WHERE message_id = ?",
                (email_data["message_id"],),
            ).fetchone()
        finally:
            conn.close()
        assert row is not None
        assert row["parse_status"] == "unparsed"
        assert row["attachment_count"] == 1
        assert row["filename"] == "mystery.pdf"
