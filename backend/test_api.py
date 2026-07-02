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
