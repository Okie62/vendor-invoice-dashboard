"""
Vendor name extraction from forwarded receipt/invoice emails.

Priority chain (stops at first confident result):
  1. Display name from the forwarded-message header block
  2. Registrable domain from the sender's email address (via tldextract)
     -> strip noise subdomains -> apply VENDOR_ALIASES
  3. Subject-line regex heuristic
  4. Fallback: raw domain part, title-cased (flagged as unconfirmed)

Ported from email-attachment-filer/vendor_extractor.py — no changes needed.
"""

import logging
import re

import tldextract

from config import NOISE_SUBDOMAINS, VENDOR_ALIASES

log = logging.getLogger(__name__)

_FWD_FROM_RE = re.compile(
    r"(?:^|\n)From:\s*"
    r"(?P<name>[^<\n]+?)\s*<(?P<email>[^>]+)>"
    r"|(?:^|\n)From:\s*(?P<bare_email>[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,})",
    re.MULTILINE,
)

_SUBJECT_RE = re.compile(
    r"(?:(?:from|by)\s+([A-Z][A-Za-z0-9\s&'.]+?)(?:\s*[-–|,]|\s*$))"
    r"|^([A-Z][A-Za-z0-9\s&'.]+?)\s+(?:invoice|receipt|statement|order|bill)",
    re.IGNORECASE,
)


def _domain_to_vendor(email_addr: str) -> tuple[str, bool]:
    ext = tldextract.extract(email_addr)
    domain_part = ext.domain.lower()

    subdomain = ext.subdomain.lower()
    subdomain_parts = [p for p in subdomain.split(".") if p and p not in NOISE_SUBDOMAINS]

    alias = VENDOR_ALIASES.get(domain_part)
    if alias:
        return alias, True

    if domain_part in NOISE_SUBDOMAINS:
        return domain_part.title(), False

    return domain_part.title(), True


def extract_vendor(subject: str, body_text: str, from_header: str) -> tuple[str, bool]:
    """
    Return (vendor_name, is_confident).
    """

    # 1. Forwarded-message header block
    match = _FWD_FROM_RE.search(body_text)
    if match:
        name = (match.group("name") or "").strip()
        email_addr = (match.group("email") or match.group("bare_email") or "").strip()

        if name and len(name) > 1 and not name.startswith("=?"):
            name = re.sub(r'["\',;]+$', "", name).strip()
            name_lower = name.lower()
            for key, alias in VENDOR_ALIASES.items():
                if key in name_lower:
                    log.debug("Vendor from fwd display name alias: %s -> %s", name, alias)
                    return alias, True
            log.debug("Vendor from fwd display name: %s", name)
            return name, True

        if email_addr:
            vendor, confident = _domain_to_vendor(email_addr)
            log.debug("Vendor from fwd email domain: %s -> %s", email_addr, vendor)
            return vendor, confident

    # 2. Top-level From header domain
    from_email_match = re.search(r"<([^>]+)>|(\S+@\S+)", from_header)
    if from_email_match:
        addr = (from_email_match.group(1) or from_email_match.group(2) or "").strip()
        ext = tldextract.extract(addr)
        if ext.domain and ext.domain.lower() not in {"gmail", "yahoo", "hotmail", "outlook", "icloud", "me"}:
            vendor, confident = _domain_to_vendor(addr)
            log.debug("Vendor from top-level From domain: %s -> %s", addr, vendor)
            return vendor, confident

    # 3. Subject-line heuristic
    smatch = _SUBJECT_RE.search(subject)
    if smatch:
        name = (smatch.group(1) or smatch.group(2) or "").strip()
        if name:
            name_lower = name.lower()
            for key, alias in VENDOR_ALIASES.items():
                if key in name_lower:
                    log.debug("Vendor from subject alias: %s -> %s", name, alias)
                    return alias, True
            log.debug("Vendor from subject: %s", name)
            return name, False

    # 4. Fallback
    any_email = re.search(r"[\w._%+\-]+@([\w.\-]+\.[a-zA-Z]{2,})", body_text)
    if any_email:
        vendor, _ = _domain_to_vendor(any_email.group(0))
        log.debug("Vendor from body fallback email: %s", vendor)
        return vendor, False

    log.debug("Vendor extraction failed entirely; using 'Unknown'")
    return "Unknown", False


def get_vendor_aliases(conn):
    """Load vendor aliases from DB, falling back to config defaults (#22).

    DB aliases override the hardcoded VENDOR_ALIASES from config.py.
    """
    aliases = dict(VENDOR_ALIASES)  # start with config defaults
    try:
        rows = conn.execute(
            "SELECT domain_key, display_name FROM vendor_aliases"
        ).fetchall()
        for r in rows:
            aliases[r["domain_key"]] = r["display_name"]
    except Exception:
        pass  # table might not exist yet
    return aliases
