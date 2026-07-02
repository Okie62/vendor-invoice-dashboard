# Vendor Invoice Dashboard

Automated vendor invoice processing for Oklahoma Technology Solutions.
Polls a dedicated Gmail inbox for invoice PDFs, parses them (Intermedia, Barracuda),
stores in SQLite, and serves a web dashboard with filtering, charts, and editing.

## Architecture

```
Gmail Inbox → IMAP Poller (every 5 min) → PDF Parser → SQLite DB
                                                        ↓
                                          Flask API ← Dashboard (HTML/JS)
```

### Backend (Python/Flask)
- **runner.py** — Entry point for gunicorn; starts Flask + background poller thread
- **server.py** — Flask app with REST API + static file serving
- **ingest.py** — Email-to-DB pipeline: poll IMAP, parse PDF, store
- **pdf_parser.py** — PDF text extraction + parsing for Intermedia/Barracuda invoices
- **email_poller.py** — IMAP connection with retry, unseen email fetching
- **email_sender.py** — SMTP auto-reply confirmation emails
- **vendor_extractor.py** — Vendor name extraction from email metadata
- **db.py** — SQLite schema, migrations, audit logging
- **auth.py** — JWT + bcrypt authentication
- **config.py** — Central config (paths, env vars, vendor aliases)

### Frontend (HTML/CSS/JS)
- **index.html** — Single-page dashboard with Chart.js, PDF.js, inline editing
- **login.html** — Login/registration page

### Database Schema
- `vendors` — Vendor records (auto-created from email)
- `invoices` — Invoice headers with summary amounts
- `customers` — Per-invoice customer blocks
- `line_items` — Individual charge line items
- `processed_emails` — Dedup table for IMAP messages
- `users` — Auth users (first user = admin)
- `audit_log` — Edit history for invoices
- `vendor_aliases` — DB-backed vendor alias overrides
- `schema_migrations` — Migration version tracking

## Setup

### Prerequisites
- Python 3.9+
- A Gmail account with an App Password (for IMAP/SMTP)

### Local Development
```bash
cd vendor-invoice-dashboard
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# Configure environment
cp .env.example .env
# Edit .env with your Gmail address and app password

# Run
cd backend
python runner.py
# Dashboard at http://localhost:8080
```

### Environment Variables
| Variable | Description | Default |
|----------|-------------|---------|
| `GMAIL_ADDRESS` | Gmail inbox for invoice emails | (required) |
| `GMAIL_APP_PASSWORD` | Gmail app password | (required) |
| `SECRET_KEY` | JWT signing secret | `dev-secret-key-change-in-production` |
| `ACCESS_TOKEN_EXPIRE_MINUTES` | JWT access token TTL | `30` |
| `REFRESH_TOKEN_EXPIRE_DAYS` | JWT refresh token TTL | `7` |
| `RENDER_PROJECT_DIR` | Base dir override (Render) | (auto) |
| `PORT` | HTTP port | `8080` |

### Deployment (Render)
The app is configured for Render via `render.yaml`:
- Web service running gunicorn
- 5GB persistent disk at `/opt/render/project/src/data`
- Auto-deploys from GitHub `main` branch

```bash
# Manual deploy trigger
curl -X POST "$RENDER_API_KEY@api.render.com/v1/services/srv-d904blbeo5us73bqv950/deploys"
```

## API Reference

### Auth (public)
- `POST /api/auth/register` — Register (first user becomes admin)
- `POST /api/auth/login` — Login, returns JWT tokens
- `POST /api/auth/refresh` — Refresh access token
- `GET /api/auth/setup-check` — Check if any users exist
- `GET /api/auth/me` — Current user info

### Invoices
- `GET /api/invoices` — List (filter: vendor, start, end, search)
- `GET /api/invoices/bulk` — List with customers + line items in one call
- `GET /api/invoices/<id>` — Single invoice with details
- `PUT /api/invoices/<id>` — Update invoice, customers, line items
- `DELETE /api/invoices/<id>` — Delete invoice + PDF
- `GET /api/invoices/<id>/pdf` — Download PDF
- `GET /api/invoices/<id>/raw-text` — Raw PDF text for debugging
- `POST /api/invoices/<id>/reprocess` — Re-parse PDF for single invoice
- `GET /api/invoices/<id>/audit` — Audit log for invoice edits

### Other
- `GET /api/health` — Health check (Render)
- `GET /api/vendors` — List vendors
- `PUT /api/vendors/<id>` — Update vendor
- `DELETE /api/vendors/<id>` — Delete vendor (if no invoices)
- `GET /api/summary` — Aggregated summary (filter: vendor, start, end)
- `POST /api/upload` — Upload PDF invoice
- `POST /api/poll` — Trigger email poll (?reprocess=true to wipe + reprocess all)
- `GET /api/export/invoices` — CSV export
- `GET /api/export/customers` — CSV export
- `GET /api/export/line-items` — CSV export
- `POST /api/archive` — Archive old invoices (?older_than_days=730)

## Testing
```bash
cd backend
python -m pytest test_*.py -v
```

## Tech Stack
- **Backend**: Flask 3.x, gunicorn, SQLite, PyJWT, bcrypt, pymupdf, filelock
- **Frontend**: Vanilla HTML/CSS/JS, Chart.js, PDF.js
- **Infra**: Render (web service + persistent disk), Gmail (IMAP/SMTP)
