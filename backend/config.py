"""
Central configuration for the Vendor Invoice Dashboard.
"""

import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).parent.parent / ".env")

# Paths — use RENDER env var if on Render, otherwise local
BASE_DIR = Path(os.environ.get("RENDER_PROJECT_DIR", Path(__file__).parent.parent))
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
}

# Noise subdomain prefixes to strip
NOISE_SUBDOMAINS = {
    "billing", "noreply", "no-reply", "mail", "email", "notifications",
    "notify", "support", "help", "info", "news", "newsletter", "alerts",
    "receipts", "invoices", "orders", "payments", "accounts",
}
