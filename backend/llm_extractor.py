"""
LLM-assisted invoice field extraction via the xAI Grok API.

Takes raw document text (already extracted from PDF/HTML) and returns a
structured JSON dict of invoice fields. Uses raw HTTP (httpx) against the
OpenAI-compatible xAI chat completions endpoint — no SDK.
"""

from __future__ import annotations

import json
import logging
import os
import re
from typing import Any

import httpx

log = logging.getLogger(__name__)

XAI_API_URL = "https://api.x.ai/v1/chat/completions"
DEFAULT_MODEL = "grok-4.5"
FALLBACK_MODEL = "grok-2-1212"
REQUEST_TIMEOUT = 30.0

SYSTEM_PROMPT = """\
You are extracting structured data from a vendor invoice document \
(PDF text or HTML). Return ONLY a JSON object with these exact keys \
(use null for missing fields):
{
  "invoice_id": "string or null",
  "billing_period": "string or null",
  "invoice_date": "YYYY-MM-DD or null",
  "due_date": "YYYY-MM-DD or null",
  "vendor_name": "string or null",
  "previous_balance": number or null,
  "credit_card_surcharges": number or null,
  "payment_received": number or null,
  "new_charges": number or null,
  "outstanding_balance": number or null,
  "customers": [{"name": "", "account_id": "", "partner_id": "", "total": 0}],
  "line_items": [{"customer": "", "date": "", "item": "", "type": "", "qty": 0, "unit_price": 0, "amount": 0}]
}

Rules:
- Return ONLY valid JSON. No markdown fences, no commentary.
- Monetary amounts must be numbers (not strings). Use null when unknown.
- Dates must be YYYY-MM-DD when possible; null if unknown.
- customers and line_items may be empty arrays when not applicable.
- Do not invent values that are not supported by the document text.
"""


class LLMExtractionError(Exception):
    """Raised when the LLM call or response parsing fails."""


class LLMNotConfiguredError(Exception):
    """Raised when XAI_API_KEY is not set."""


def _strip_markdown_fences(content: str) -> str:
    """Remove optional ```json ... ``` wrappers the model may emit."""
    text = content.strip()
    # Full fence match
    fence = re.match(
        r"^```(?:json|JSON)?\s*\n?(.*?)\n?```\s*$",
        text,
        re.DOTALL,
    )
    if fence:
        return fence.group(1).strip()
    # Leading fence without clean trailing fence
    if text.startswith("```"):
        text = re.sub(r"^```(?:json|JSON)?\s*\n?", "", text)
        text = re.sub(r"\n?```\s*$", "", text)
    return text.strip()


def _parse_json_content(content: str) -> dict[str, Any]:
    """Parse model content into a dict, tolerating markdown code fences."""
    if not content or not content.strip():
        raise LLMExtractionError("Empty LLM response content")

    cleaned = _strip_markdown_fences(content)
    try:
        data = json.loads(cleaned)
    except json.JSONDecodeError:
        # Last resort: grab the outermost JSON object
        start = cleaned.find("{")
        end = cleaned.rfind("}")
        if start >= 0 and end > start:
            try:
                data = json.loads(cleaned[start : end + 1])
            except json.JSONDecodeError as e:
                raise LLMExtractionError(
                    f"Failed to parse LLM JSON: {e}"
                ) from e
        else:
            raise LLMExtractionError(
                "LLM response did not contain a JSON object"
            )

    if not isinstance(data, dict):
        raise LLMExtractionError(
            f"LLM response JSON must be an object, got {type(data).__name__}"
        )
    return data


def _call_xai(messages: list[dict[str, str]], api_key: str, model: str) -> str:
    """POST to xAI chat completions and return message content text."""
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": model,
        "messages": messages,
        "temperature": 0,
    }
    try:
        with httpx.Client(timeout=REQUEST_TIMEOUT) as client:
            resp = client.post(XAI_API_URL, headers=headers, json=payload)
    except httpx.TimeoutException as e:
        raise LLMExtractionError(f"xAI API timeout after {REQUEST_TIMEOUT}s") from e
    except httpx.HTTPError as e:
        raise LLMExtractionError(f"xAI API request failed: {e}") from e

    if resp.status_code >= 400:
        # Avoid echoing response bodies that might include request echo
        raise LLMExtractionError(
            f"xAI API returned HTTP {resp.status_code}"
        )

    try:
        body = resp.json()
    except json.JSONDecodeError as e:
        raise LLMExtractionError("xAI API returned non-JSON body") from e

    try:
        content = body["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError) as e:
        raise LLMExtractionError(
            "Unexpected xAI response shape (missing choices[0].message.content)"
        ) from e

    if not isinstance(content, str):
        raise LLMExtractionError("LLM message content is not a string")
    return content


def extract_invoice_fields(raw_text: str, vendor_name: str = "") -> dict[str, Any]:
    """Extract invoice fields from document text via xAI Grok.

    Args:
        raw_text: Plain text already extracted from the invoice PDF/HTML.
        vendor_name: Optional vendor hint from the review record.

    Returns:
        dict with the structured invoice fields.

    Raises:
        LLMNotConfiguredError: if XAI_API_KEY is unset.
        LLMExtractionError: if the API call or JSON parse fails.
    """
    api_key = os.environ.get("XAI_API_KEY", "").strip()
    if not api_key:
        raise LLMNotConfiguredError(
            "LLM extraction not configured — set XAI_API_KEY"
        )

    if not (raw_text or "").strip():
        raise LLMExtractionError("No document text provided")

    vendor_hint = vendor_name.strip() if vendor_name else ""
    user_parts = []
    if vendor_hint:
        user_parts.append(f"Vendor name (from our records): {vendor_hint}")
    user_parts.append("Invoice document text:")
    user_parts.append(raw_text)
    user_message = "\n\n".join(user_parts)

    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": user_message},
    ]

    last_error: Exception | None = None
    for model in (DEFAULT_MODEL, FALLBACK_MODEL):
        try:
            content = _call_xai(messages, api_key, model)
            return _parse_json_content(content)
        except LLMExtractionError as e:
            last_error = e
            log.warning("LLM extraction with model %s failed: %s", model, e)
            if model == FALLBACK_MODEL:
                break
            continue

    raise LLMExtractionError(str(last_error) if last_error else "LLM extraction failed")
