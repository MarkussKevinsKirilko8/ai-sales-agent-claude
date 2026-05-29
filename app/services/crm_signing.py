"""HMAC-SHA256 request signing/verification for the OCTO CRM integration.

Identical recipe in both directions:
    canonical = CANONICAL_JSON(body)
    inner     = SHA256_HEX(canonical)
    signature = HMAC_SHA256_HEX(timestamp + inner, secret)

canonical_json was verified byte-for-byte against the CRM's worked example;
do not "clean up" the escaping — the exact replacements are load-bearing.
"""
import hashlib
import hmac
import json
import time


def _sort_deep(v):
    if isinstance(v, dict):
        return {k: _sort_deep(v[k]) for k in sorted(v)}
    if isinstance(v, list):
        return sorted((_sort_deep(x) for x in v))
    return v


def canonical_json(data) -> str:
    s = json.dumps(_sort_deep(data), separators=(",", ":"), ensure_ascii=True)
    s = s.replace('\\"', '\\u0022')
    s = s.replace('<', '\\u003C').replace('>', '\\u003E')
    s = s.replace("'", '\\u0027').replace('&', '\\u0026')
    return s.replace('/', '\\/')


def _signature(body: dict, secret: str, timestamp: str) -> str:
    inner = hashlib.sha256(canonical_json(body).encode("utf-8")).hexdigest()
    return hmac.new(
        secret.encode("utf-8"),
        (timestamp + inner).encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()


def sign(body: dict, secret: str) -> tuple[str, str]:
    ts = str(int(time.time()))
    return ts, _signature(body, secret, ts)


def verify(body, secret, expected_api_key, got_api_key, timestamp, signature) -> tuple[bool, str]:
    if not (expected_api_key and secret):
        return False, "crm auth not configured"
    if not (got_api_key and timestamp and signature):
        return False, "missing auth headers"
    if not hmac.compare_digest(got_api_key, expected_api_key):
        return False, "invalid api key"
    try:
        ts_int = int(timestamp)
    except (TypeError, ValueError):
        return False, "invalid timestamp"
    if abs(int(time.time()) - ts_int) > 30:
        return False, "expired"
    if not hmac.compare_digest(_signature(body, secret, timestamp), signature):
        return False, "invalid signature"
    return True, ""
