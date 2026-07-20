# Vendor Invoice Dashboard — Backlog

*Generated: 2026-06-29 · State refreshed: 2026-07-20*

## 📌 Current State (2026-07-20)

**Repository:** Feature branch `fix/gmail-seen-lookback`, synchronized with GitHub through commit `fb77dd4` before this handoff update. Production remains on `main` at `ec4039d`; the Gmail lookback fix has not been merged or deployed.

**Live in production:**
- Kyle.ai-style React/Vite/Tailwind dashboard with authentication and admin user management
- A/P workflow (`received → needs_review → approved → scheduled → paid`), aging dashboard, vendor drill-down, and bulk status updates
- Auth-gated PDF/HTML invoice viewer and processed-email log with parse-status filters
- Gmail polling for PDF and HTML invoices, format recognition/review queue, duplicate-poller protection, relative document paths, migrations, health check, and automated receipt replies
- Historical mailbox backfill completed: 184 emails processed, producing 194 invoice records across 49 vendors

### Gmail ingestion incident and confirmed root cause

- On 2026-07-20, an invoice reached the receipts mailbox but was already marked `Seen` before the production AP_Agent poller ran. Production searched only `UNSEEN`, so it skipped the invoice.
- The competing consumer was confirmed as `Okie62/email-attachment-filer`, running on Jay's MacBook Air as launch agent `com.emailfiler` every 300 seconds.
- Launchd showed 252 runs and a successful last exit (`0`). The legacy code searches `UNSEEN`, fetches full messages with IMAP `RFC822` (which changes shared read state), and explicitly applies `\\Seen` after processing.
- The launch agent was unloaded on the MacBook Air and its plist renamed with a `.disabled` suffix. Verification with `launchctl print gui/$(id -u)/com.emailfiler` returned `Could not find service`, confirming it is no longer scheduled.
- A synced Google Drive copy of the legacy filer still contains an app-password environment and Google OAuth credentials. Do not delete or revoke them until AP_Agent is verified in production and it is confirmed whether the old app password is shared with AP_Agent. Then retire the legacy credentials and remove sensitive credential files from the synced folder.

### Fix ready on `fix/gmail-seen-lookback`

- Poll a bounded seven-day Gmail window instead of treating the mutable `Seen` flag as a work queue.
- Fetch with `BODY.PEEK[]` to avoid changing message read state during inspection.
- Check the durable `processed_emails.message_id` ledger before ingestion and record completion only after successful processing.
- Generate a stable SHA-256-derived identifier when an RFC Message-ID header is absent.
- Preserve the existing `fetch_unseen_emails` entry point as a compatibility alias.
- Added regression coverage for recent seen messages, PEEK fetching, fallback identifiers, and duplicate skipping.
- Validation completed: 108 backend tests passed, Python compilation and diff checks passed, Gitleaks found no secrets, and a read-only real-mailbox check confirmed the previously missed PDF invoice is selected by the new lookback.

### Resume/deployment checklist

1. Review and approve `fix/gmail-seen-lookback`; fast-forward it to `main` only after approval. Render auto-deploys `main`.
2. Monitor the Render deployment and poller logs without exposing message contents or credentials.
3. Confirm the previously missed invoice is ingested exactly once, then send a fresh test invoice and verify it appears once in the dashboard.
4. Confirm `com.emailfiler` remains absent on the MacBook Air after login/reboot.
5. Determine whether the legacy Gmail app password is distinct from AP_Agent's Render credential. Rotate/revoke the legacy app password and OAuth token only after that check.
6. Remove legacy credentials from the synchronized Google Drive folder and archive or delete the disabled launch-agent plist after the verification window.
7. Continue the pre-existing data cleanup and parser backlog below.

**Additional next work:**
- Rotate any independently exposed AP_Agent Gmail credential and update Render safely.
- Clean historical vendor attribution (forwarded messages assigned to the receipts mailbox; stray leading quotes in vendor names).
- Build parsers for the highest-volume unparsed formats: Google, Anthropic, Pronto Marketing, Slack, Textmagic, and Stripe.
- Triage/dismiss historical review-queue noise and correct old invoice payment statuses so outstanding A/P is meaningful.

**Important:** The original backlog below is historical and substantially stale; many early security, reliability, UI, and test-suite items are already implemented. Verify each item against current code before starting it.

## 🔴 High Priority

| # | Task | Description |
|---|------|-------------|
| 1 | **Add authentication** | Dashboard is completely open — anyone with the URL can view, edit, and delete invoices. Add at minimum basic-auth or session login. |
| 2 | **Fix N+1 API calls on page load** | `loadData()` fetches `/api/invoices/{id}` in a loop for every invoice. Add a bulk endpoint or include customers/line_items in the main `/api/invoices` response. |
| 3 | **Add `.gitignore`** | No `.gitignore` exists — `data/` (DB, PDFs), `.env`, and `__pycache__/` risk being committed. |
| 4 | **Fix XSS in table rendering** | `renderCustomers()` and `renderLineItems()` inject user-controlled strings (customer names, item names) via `innerHTML` without escaping. The `esc()` helper exists but isn't used in these paths. |
| 5 | **Add health check endpoint** | Render health checks hit `/` which returns full HTML. Add a lightweight `/api/health` returning `200 OK`. |
| 6 | **Send email reply on new invoice receipt** | When a new invoice email is processed, auto-reply to the sender confirming receipt (e.g., "Invoice received and processed — Invoice #XXX"). |

## 🟠 Medium Priority

| # | Task | Description |
|---|------|-------------|
| 7 | **Add date/billing-period filtering** | Currently can only filter by vendor and customer. Add date range or billing period filter to the filter bar and API queries. |
| 8 | **Add CSV/Excel export** | No way to export invoices, customers, or line items. Add export buttons for each table. |
| 9 | **Populate `invoice_date` field** | The column exists in the schema but parsers never set it. Both Intermedia and Barracuda parsers should extract and store the invoice date. |
| 10 | **Add monthly trend chart** | Charts are bar (top customers) and doughnut (categories). Add a time-series line chart showing charges over months. |
| 11 | **Add pagination** | All invoices + details loaded at once. Will degrade as volume grows. Paginate the invoice list and line items table. |
| 12 | **Guard against duplicate poller threads** | If gunicorn spawns multiple workers, each starts its own poller thread — potential race conditions on IMAP and DB writes. Use a file lock or env guard. |
| 13 | **Add `.env.example`** | No template for environment variables. Document `GMAIL_ADDRESS` and `GMAIL_APP_PASSWORD`. |
| 14 | **Add README** | No documentation at all. Add setup, local dev, deployment, and architecture overview. |
| 15 | **Add reprocess single invoice** | Can only reprocess ALL emails (`?reprocess=true` wipes everything). Add ability to reprocess a single email/invoice. |
| 16 | **Show CC surcharges in summary** | Summary cards show previous balance, payment, new charges, outstanding — but not credit card surcharges, which are parsed and stored. |
| 17 | **Fix processed_emails logging for multiple attachments** | `ingest.py` line 111 only logs the first attachment filename: `email_data["attachments"][0]["filename"]`. Should log all. |

## 🟡 Low Priority

| # | Task | Description |
|---|------|-------------|
| 18 | **Add test suite** | Zero tests. Start with parser tests (Intermedia/Barracuda sample PDFs) and API endpoint tests. |
| 19 | **Add vendor management UI** | Vendors are auto-created from email and can't be edited, merged, or deleted from the UI. Add a vendor management page. |
| 20 | **Add audit log for edits** | Invoice edits via PUT endpoint aren't tracked. Add an audit trail (who changed what, when). |
| 21 | **Add notification on new invoices** | No alerting when new invoices arrive. Could add email notification or Telegram bot integration. |
| 22 | **Make vendor aliases configurable** | `VENDOR_ALIASES` is hardcoded in `config.py`. Move to DB or a config file editable from the UI. |
| 23 | **Add IMAP retry logic** | If IMAP connection fails, it just logs and waits 5 min. Add exponential backoff retry within the poll cycle. |
| 24 | **Remove dead code: `poll.py`** | Standalone poller is redundant with `runner.py`'s background thread. Either document its use case or remove it. |
| 25 | **Add data retention / archive** | Invoices accumulate forever. Add archiving for old invoices (e.g., > 2 years). |
| 26 | **Store PDF paths as relative** | `pdf_path` is stored as absolute. If the disk mount path changes (e.g., local vs Render), paths break. Store relative to `DATA_DIR`. |
| 27 | **Add budget/threshold alerts** | Set spending thresholds per vendor or customer, trigger alerts when exceeded. |
| 28 | **Improve mobile responsiveness** | Layout uses fixed widths in several places (`max-width:200px`, `min-width:250px`). Test and fix on mobile. |
| 29 | **Add search across invoices** | Can search customers and line items, but not invoices by ID, period, or vendor. |
| 30 | **Add DB migration system** | Schema uses `CREATE TABLE IF NOT EXISTS` — no way to add columns or migrate. Add a simple migration system (e.g., Alembic or versioned SQL scripts). |
| 31 | **Self-host PDF.js** | PDF.js loaded from CDN — could break if CDN changes or goes down. Bundle locally. |

## Summary

31 backlog items — 6 high priority, 11 medium, 14 low.

The biggest immediate risks are:
- **No auth** (public dashboard)
- **N+1 API calls** (slow page load)
- **Missing `.gitignore`** (risk of committing sensitive data)
- **XSS in table rendering** (user-controlled strings injected without escaping)
