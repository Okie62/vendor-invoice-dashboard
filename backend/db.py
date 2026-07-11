"""
SQLite database for vendor invoice tracking.

Tables: vendors, invoices, customers, line_items, processed_emails,
        users, audit_log, vendor_aliases
"""

import sqlite3
import logging
from config import DATA_DIR

log = logging.getLogger(__name__)

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
    processed_at TEXT DEFAULT (datetime('now')),
    subject TEXT,
    from_header TEXT,
    received_date TEXT,
    attachment_count INTEGER,
    parse_status TEXT
);

CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    email TEXT NOT NULL UNIQUE,
    hashed_password TEXT NOT NULL,
    full_name TEXT NOT NULL,
    is_active INTEGER DEFAULT 1 NOT NULL,
    is_admin INTEGER DEFAULT 0 NOT NULL,
    created_at TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS audit_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    invoice_id TEXT NOT NULL,
    user_id INTEGER,
    user_email TEXT,
    action TEXT NOT NULL,
    changes TEXT,
    created_at TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS vendor_aliases (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    domain_key TEXT NOT NULL UNIQUE,
    display_name TEXT NOT NULL,
    created_at TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS schema_migrations (
    version INTEGER PRIMARY KEY,
    applied_at TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS invoice_formats (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    vendor_id INTEGER NOT NULL REFERENCES vendors(id),
    format_fingerprint TEXT NOT NULL,
    parser_name TEXT NOT NULL DEFAULT '',
    first_seen TEXT DEFAULT (datetime('now')),
    last_seen TEXT DEFAULT (datetime('now')),
    sample_count INTEGER DEFAULT 1,
    status TEXT DEFAULT 'recognized'
        CHECK(status IN ('recognized', 'new', 'deprecated'))
);

CREATE TABLE IF NOT EXISTS format_reviews (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    invoice_id TEXT NOT NULL REFERENCES invoices(id),
    vendor_id INTEGER NOT NULL REFERENCES vendors(id),
    detected_at TEXT DEFAULT (datetime('now')),
    status TEXT DEFAULT 'pending'
        CHECK(status IN ('pending', 'in_review', 'parsed', 'verified', 'dismissed')),
    notes TEXT,
    extracted_data TEXT,
    detection_reason TEXT,
    reviewed_by INTEGER REFERENCES users(id),
    reviewed_at TEXT
);
"""


# -----------------------------------------------------------------------
# Migration system (#30) — versioned, forward-only SQL migrations
# -----------------------------------------------------------------------

MIGRATIONS = [
    # v1: add invoice_date column to invoices (if not present from CREATE TABLE)
    #     This is a no-op if the column already exists from the schema above.
    "ALTER TABLE invoices ADD COLUMN invoice_date TEXT",

    # v2: add filename column to processed_emails for multi-attachment logging (#17)
    #     The column already exists in the original schema, so this is a no-op
    #     for new DBs. For existing DBs it was already there too.

    # v3: create invoice_formats table for format fingerprint registry
    "CREATE TABLE IF NOT EXISTS invoice_formats ("
    "id INTEGER PRIMARY KEY AUTOINCREMENT, "
    "vendor_id INTEGER NOT NULL REFERENCES vendors(id), "
    "format_fingerprint TEXT NOT NULL, "
    "parser_name TEXT NOT NULL DEFAULT '', "
    "first_seen TEXT DEFAULT (datetime('now')), "
    "last_seen TEXT DEFAULT (datetime('now')), "
    "sample_count INTEGER DEFAULT 1, "
    "status TEXT DEFAULT 'recognized' "
    "CHECK(status IN ('recognized', 'new', 'deprecated')))",

    # v4: create format_reviews table for review queue
    "CREATE TABLE IF NOT EXISTS format_reviews ("
    "id INTEGER PRIMARY KEY AUTOINCREMENT, "
    "invoice_id TEXT NOT NULL REFERENCES invoices(id), "
    "vendor_id INTEGER NOT NULL REFERENCES vendors(id), "
    "detected_at TEXT DEFAULT (datetime('now')), "
    "status TEXT DEFAULT 'pending' "
    "CHECK(status IN ('pending', 'in_review', 'parsed', 'verified', 'dismissed')), "
    "notes TEXT, "
    "extracted_data TEXT, "
    "detection_reason TEXT, "
    "reviewed_by INTEGER REFERENCES users(id), "
    "reviewed_at TEXT)",

    # v5: add status column for A/P invoice lifecycle
    "ALTER TABLE invoices ADD COLUMN status TEXT NOT NULL DEFAULT 'received' "
    "CHECK(status IN ('received', 'needs_review', 'approved', 'scheduled', 'paid'))",

    # v6: add due_date column for A/P aging
    "ALTER TABLE invoices ADD COLUMN due_date TEXT",

    # v7: derive sensible defaults for existing rows
    "UPDATE invoices SET status = 'paid' WHERE outstanding_balance = 0 AND status = 'received'",

    "UPDATE invoices SET status = 'needs_review' WHERE source = 'email_unparsed' AND status = 'received'",

    # v8–v12: enrich processed_emails for Email Log page
    "ALTER TABLE processed_emails ADD COLUMN subject TEXT",
    "ALTER TABLE processed_emails ADD COLUMN from_header TEXT",
    "ALTER TABLE processed_emails ADD COLUMN received_date TEXT",
    "ALTER TABLE processed_emails ADD COLUMN attachment_count INTEGER",
    "ALTER TABLE processed_emails ADD COLUMN parse_status TEXT",
]


def get_db():
    """Return a sqlite3 connection with row factory."""
    conn = sqlite3.connect(str(DB_PATH), timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def _get_schema_version(conn):
    """Get the current schema version, or 0 if no migrations applied."""
    try:
        row = conn.execute(
            "SELECT MAX(version) as v FROM schema_migrations"
        ).fetchone()
        return row["v"] if row and row["v"] else 0
    except sqlite3.OperationalError:
        # schema_migrations table doesn't exist yet
        return 0


def _run_migrations(conn):
    """Apply pending migrations forward-only."""
    # Ensure schema_migrations table exists
    conn.execute("""
        CREATE TABLE IF NOT EXISTS schema_migrations (
            version INTEGER PRIMARY KEY,
            applied_at TEXT DEFAULT (datetime('now'))
        )
    """)
    conn.commit()

    current = _get_schema_version(conn)
    for i, sql in enumerate(MIGRATIONS, start=1):
        if i <= current:
            continue
        try:
            conn.execute(sql)
            conn.execute(
                "INSERT INTO schema_migrations (version) VALUES (?)",
                (i,)
            )
            conn.commit()
            log.info(f"Applied migration v{i}")
        except sqlite3.OperationalError as e:
            # Column already exists — mark as applied and continue
            if "duplicate column" in str(e).lower():
                conn.execute(
                    "INSERT OR IGNORE INTO schema_migrations (version) VALUES (?)",
                    (i,)
                )
                conn.commit()
                log.debug(f"Migration v{i} skipped (column exists)")
            else:
                log.warning(f"Migration v{i} failed: {e}")
                conn.rollback()


def init_db():
    """Create all tables if they don't exist and run migrations."""
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = get_db()
    conn.executescript(SCHEMA_SQL)
    conn.commit()
    _run_migrations(conn)
    conn.close()


def log_audit(conn, invoice_id, user_id, user_email, action, changes=None):
    """Insert an audit log entry (#20)."""
    import json
    conn.execute(
        "INSERT INTO audit_log (invoice_id, user_id, user_email, action, changes) "
        "VALUES (?, ?, ?, ?, ?)",
        (invoice_id, user_id, user_email, action,
         json.dumps(changes) if changes else None)
    )
    conn.commit()
