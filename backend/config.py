"""
Central configuration for the Vendor Invoice Dashboard.
"""

import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).parent.parent / ".env")

# Paths — use RENDER_PROJECT_DIR env var if on Render, otherwise local.
# On Render, RENDER_PROJECT_DIR is typically "/opt/render/project/src".
# The persistent disk is mounted at /opt/render/project/src/data.
# IMPORTANT: We must resolve to an absolute path so that changing the
# working directory (e.g. gunicorn --chdir backend) doesn't break paths.
_render_dir = os.environ.get("RENDER_PROJECT_DIR", "")
if _render_dir and Path(_render_dir).is_absolute():
    BASE_DIR = Path(_render_dir)
elif _render_dir:
    # Render sets RENDER_PROJECT_DIR="project" (relative).
    # The real project root is /opt/render/project/src.
    # Hardcode this so paths resolve correctly regardless of cwd.
    _render_root = Path("/opt/render/project/src")
    if _render_root.exists():
        BASE_DIR = _render_root
    else:
        BASE_DIR = Path(_render_dir).resolve()
else:
    BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"
INVOICE_DIR = DATA_DIR / "invoices"
DB_PATH = DATA_DIR / "db" / "invoices.db"

# Gmail credentials
GMAIL_ADDRESS = os.getenv("GMAIL_ADDRESS", "")
GMAIL_APP_PASSWORD = os.getenv("GMAIL_APP_PASSWORD", "")

# Auth — JWT + bcrypt (adapted from ar_agent architecture)
SECRET_KEY = os.getenv("SECRET_KEY", "dev-secret-key-change-in-production")
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = int(os.getenv("ACCESS_TOKEN_EXPIRE_MINUTES", "30"))
REFRESH_TOKEN_EXPIRE_DAYS = int(os.getenv("REFRESH_TOKEN_EXPIRE_DAYS", "7"))

# Polling interval (seconds)
POLL_INTERVAL = 300

# Vendor aliases
VENDOR_ALIASES = {
    "intermedia":    "Intermedia",
    "amazon":        "Amazon",
    "amazonaws":     "Amazon AWS",
    "apple":         "Apple",
    "google":        "Google",
    "microsoft":     "Microsoft",
    "paypal":        "PayPal",
    "stripe":        "Stripe",
    "shopify":       "Shopify",
    "intuit":        "QuickBooks",
    "turbotax":      "TurboTax",
    "dropbox":       "Dropbox",
    "zoom":          "Zoom",
    "slack":         "Slack",
    "godaddy":       "GoDaddy",
    "namecheap":     "Namecheap",
    "digitalocean":  "DigitalOcean",
    "github":        "GitHub",
    "notion":        "Notion",
    "squarespace":   "Squarespace",
    "wix":           "Wix",
    "canva":         "Canva",
    "adobe":         "Adobe",
    "barracuda":     "Barracuda",
    "flyover":       "Flyover Software",
    "btabs":         "Flyover Software",
    "extraspace":    "Extra Space Storage",
    "compassmining": "Compass Mining",
}

# Noise subdomain prefixes to strip
NOISE_SUBDOMAINS = {
    "billing", "noreply", "no-reply", "mail", "email", "notifications",
    "notify", "support", "help", "info", "news", "newsletter", "alerts",
    "receipts", "invoices", "orders", "payments", "accounts",
}
