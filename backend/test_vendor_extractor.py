"""
Tests for vendor extraction logic (backlog #18).
"""
import sys
import os
import pytest

sys.path.insert(0, os.path.dirname(__file__))

from vendor_extractor import extract_vendor


class TestExtractVendor:
    def test_forwarded_header_name(self):
        vendor, conf = extract_vendor(
            "Invoice from Intermedia",
            "From: Intermedia <billing@intermedia.com>\n\n",
            "forwarded@ gmail.com"
        )
        assert vendor == "Intermedia"
        assert conf is True

    def test_from_domain_alias(self):
        vendor, conf = extract_vendor(
            "Your invoice",
            "",
            "billing@amazon.com"
        )
        assert vendor == "Amazon"
        assert conf is True

    def test_subject_heuristic(self):
        vendor, conf = extract_vendor(
            "Apple invoice for June",
            "",
            "noreply@gmail.com"
        )
        assert vendor == "Apple"

    def test_fallback_unknown(self):
        vendor, conf = extract_vendor("", "", "")
        assert vendor == "Unknown"
        assert conf is False

    def test_noise_subdomain_stripped(self):
        vendor, conf = extract_vendor(
            "Receipt",
            "",
            "billing@stripe.com"
        )
        assert vendor == "Stripe"

    def test_gmail_not_vendor(self):
        vendor, conf = extract_vendor(
            "Invoice",
            "",
            "user@gmail.com"
        )
        # Should not return "Gmail" as vendor
        assert vendor != "Gmail"
