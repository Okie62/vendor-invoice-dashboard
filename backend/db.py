"""
SQLite database for vendor invoice tracking.

Tables: vendors, invoices, customers, line_items, processed_emails
"""

import sqlite3
from config import DATA_DIR

DB_PATH = DATA_DIR / "db" / "invoices.db"

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS vendors (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE,
    email_domain TEXT,
    default_partner_name TEXT,
    default_partner_id TEXT,
    created_at TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS invoices (
    id TEXT PRIMARY KEY,
    vendor_id INTEGER NOT NULL REFERENCES vendors(id),
    billing_period TEXT,
    invoice_date TEXT,
    is_credit_memo INTEGER DEFAULT 0,
    references_invoice TEXT,
    partner_name TEXT,
    partner_id TEXT,
    partner_username TEXT,
    previous_balance REAL DEFAULT 0,
    credit_card_surcharges REAL DEFAULT 0,
    payment_received REAL DEFAULT 0,
    new_charges REAL DEFAULT 0,
    outstanding_balance REAL DEFAULT 0,
    source TEXT DEFAULT 'manual',
    email_message_id TEXT,
    pdf_path TEXT,
    created_at TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS customers (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    invoice_id TEXT NOT NULL REFERENCES invoices(id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    account_id TEXT,
    partner_id TEXT,
    total REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS line_items (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    invoice_id TEXT NOT NULL REFERENCES invoices(id) ON DELETE CASCADE,
    customer_name TEXT,
    date TEXT,
    item TEXT NOT NULL,
    type TEXT,
    qty INTEGER,
    unit_price REAL,
    amount REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS processed_emails (
    message_id TEXT PRIMARY KEY,
    received_at TEXT,
    vendor_name TEXT,
    invoice_id TEXT,
    filename TEXT,
    processed_at TEXT DEFAULT (datetime('now'))
);
"""


def get_db():
    """Return a sqlite3 connection with row factory."""
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db():
    """Create all tables if they don't exist."""
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = get_db()
    conn.executescript(SCHEMA_SQL)
    conn.close()
