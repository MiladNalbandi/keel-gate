"""Canonical JSON and the call fingerprint (AC-006, AC-007).

The same logical call must always give the same hash, and any change to the arguments must give a different one.
That is what binds a human approval to exactly one call.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any


def canonical_json(value: Any) -> str:
    """JSON with sorted keys, no extra spaces, and real UTF-8 characters. Raises ValueError for NaN, Infinity, or
    values JSON cannot represent."""
    try:
        return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"value cannot be turned into canonical JSON: {exc}") from exc


def sha256_hex(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def call_hash(tool: str, args: Any) -> str:
    """sha256 of the canonical JSON of {"tool": tool, "args": args}."""
    return sha256_hex(canonical_json({"tool": tool, "args": args}))
