from email.message import EmailMessage
import sqlite3

from email_poller import fetch_recent_emails
import ingest


class FakeImap:
    def __init__(self, raw_message: bytes):
        self.raw_message = raw_message
        self.search_calls = []
        self.fetch_calls = []
        self.selected = None

    def select(self, mailbox):
        self.selected = mailbox
        return "OK", [b""]

    def search(self, charset, *criteria):
        self.search_calls.append((charset, criteria))
        return "OK", [b"17"]

    def fetch(self, imap_id, query):
        self.fetch_calls.append((imap_id, query))
        return "OK", [(b"17 (BODY[] {123}", self.raw_message), b")"]


def make_invoice_email() -> bytes:
    msg = EmailMessage()
    msg["Message-ID"] = "<recent-seen-invoice@example.test>"
    msg["Subject"] = "FW: Vendor invoice"
    msg["From"] = "sender@example.test"
    msg["Date"] = "Mon, 20 Jul 2026 22:10:50 +0000"
    msg.set_content("Please process this invoice.")
    msg.add_attachment(
        b"%PDF-1.4 test",
        maintype="application",
        subtype="pdf",
        filename="invoice.pdf",
    )
    return msg.as_bytes()


def make_invoice_email_without_message_id() -> bytes:
    msg = EmailMessage()
    msg["Subject"] = "FW: Vendor invoice without an RFC Message-ID"
    msg["From"] = "sender@example.test"
    msg.set_content("Please process this invoice.")
    return msg.as_bytes()


def test_recent_poll_uses_since_instead_of_unseen():
    imap = FakeImap(make_invoice_email())

    messages = fetch_recent_emails(imap, lookback_days=3)

    assert len(messages) == 1
    assert imap.selected == "INBOX"
    _, criteria = imap.search_calls[0]
    assert criteria[0] == "SINCE"
    assert "UNSEEN" not in criteria


def test_recent_poll_fetches_with_peek_so_failures_remain_retryable():
    imap = FakeImap(make_invoice_email())

    messages = fetch_recent_emails(imap, lookback_days=3)

    assert imap.fetch_calls == [(b"17", "(BODY.PEEK[])")]
    assert messages[0]["message_id"] == "<recent-seen-invoice@example.test>"
    assert messages[0]["attachments"][0]["filename"] == "invoice.pdf"


def test_recent_poll_rejects_invalid_lookback():
    imap = FakeImap(make_invoice_email())

    try:
        fetch_recent_emails(imap, lookback_days=0)
    except ValueError as exc:
        assert "lookback_days" in str(exc)
    else:
        raise AssertionError("Expected invalid lookback to fail")


def test_recent_poll_generates_stable_dedup_id_when_header_is_missing():
    raw = make_invoice_email_without_message_id()
    first = fetch_recent_emails(FakeImap(raw), lookback_days=3)[0]["message_id"]
    second = fetch_recent_emails(FakeImap(raw), lookback_days=3)[0]["message_id"]

    assert first.startswith("<generated-")
    assert first == second


def test_ingestion_skips_recent_messages_already_in_durable_ledger(monkeypatch):
    conn = sqlite3.connect(":memory:")
    conn.execute("CREATE TABLE processed_emails (message_id TEXT PRIMARY KEY)")
    conn.execute("INSERT INTO processed_emails(message_id) VALUES ('<already@test>')")
    conn.commit()

    class PollConnection:
        def logout(self):
            return None

    processed = []
    marked_seen = []
    messages = [
        {"message_id": "<already@test>", "imap_id": b"1"},
        {"message_id": "<new@test>", "imap_id": b"2"},
    ]

    monkeypatch.setattr(ingest, "init_db", lambda: None)
    monkeypatch.setattr(ingest, "get_db", lambda: conn)
    monkeypatch.setattr(ingest, "connect_imap", PollConnection)
    monkeypatch.setattr(ingest, "fetch_recent_emails", lambda _imap: messages)
    monkeypatch.setattr(
        ingest,
        "process_email",
        lambda _conn, email_data: processed.append(email_data["message_id"]),
    )
    monkeypatch.setattr(
        ingest,
        "mark_seen",
        lambda _imap, imap_id: marked_seen.append(imap_id),
    )

    assert ingest.run_ingestion() == 1
    assert processed == ["<new@test>"]
    assert marked_seen == [b"2"]
