"""Failure fingerprinting: collapse thousands of dead letters into a handful of causes.

A fingerprint is derived from (death reason, origin queue, normalized error signature).
Normalization strips the parts that vary per message (ids, timestamps, addresses) so
that "ValidationError: order 8231 missing field 'amount'" and
"ValidationError: order 9107 missing field 'amount'" group together.
"""
from __future__ import annotations

import hashlib
import json
import re

_UUID = re.compile(r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}")
_HEX = re.compile(r"\b0x[0-9a-fA-F]+\b")
_NUM = re.compile(r"\d+")
_WS = re.compile(r"\s+")

# Header keys (checked in order) where consumers commonly stash the failure reason.
ERROR_HEADER_KEYS = ("x-exception", "x-error", "x-death-reason-detail", "error", "exception")


def normalize(text: str, max_len: int = 120) -> str:
    """Reduce an error string to its stable shape."""
    text = _UUID.sub("<uuid>", text)
    text = _HEX.sub("<hex>", text)
    text = _NUM.sub("#", text)
    text = _WS.sub(" ", text).strip()
    return text[:max_len]


def error_signature(payload: str, headers: dict) -> str:
    """Best-effort extraction of *why* this message failed."""
    for key in ERROR_HEADER_KEYS:
        val = headers.get(key)
        if val:
            return normalize(str(val))
    # Fall back to an error-ish field inside a JSON payload.
    try:
        doc = json.loads(payload)
        if isinstance(doc, dict):
            for key in ("error", "exception", "failure", "reason"):
                if key in doc and doc[key]:
                    return normalize(str(doc[key]))
    except (ValueError, TypeError):
        pass
    # Last resort: the shape of the payload itself.
    return normalize(payload, max_len=80)


def fingerprint(reason: str, origin_queue: str, payload: str, headers: dict) -> tuple[str, str]:
    """Return (stable hash, human label) identifying this failure cause."""
    sig = error_signature(payload, headers)
    key = f"{reason}|{origin_queue}|{sig}"
    digest = hashlib.sha1(key.encode()).hexdigest()[:12]
    label = sig if sig else f"{reason} from {origin_queue}"
    return digest, label
