"""Signed identities. Public demos are isolated from campus workspaces."""
import base64
import hashlib
import hmac
import json
import os
import secrets
import time
from pathlib import Path

def signing_key():
    key = os.getenv("LABLINK_SECRET")
    if key and len(key) >= 32:
        return key.encode()
    if os.getenv("K_SERVICE"):
        raise RuntimeError("Set LABLINK_SECRET to at least 32 random characters")
    if os.getenv("VERCEL"):
        return secrets.token_bytes(48)
    path = Path(".lablink-key")
    if not path.exists():
        try:
            with path.open("xb") as f:
                f.write(secrets.token_bytes(48))
        except FileExistsError:
            pass
    return path.read_bytes()

def encode(data, key):
    body = base64.urlsafe_b64encode(json.dumps(data, separators=(",", ":")).encode()).decode().rstrip("=")
    sig = hmac.new(key, body.encode(), hashlib.sha256).hexdigest()
    return body + "." + sig

def decode(token, key, purpose):
    try:
        body, sig = token.split(".")
        if not hmac.compare_digest(hmac.new(key, body.encode(), hashlib.sha256).hexdigest(), sig):
            return None
        data = json.loads(base64.urlsafe_b64decode(body + "=" * (-len(body) % 4)))
        if data["purpose"] == purpose and data["exp"] > time.time():
            return data
    except (ValueError, KeyError, TypeError, UnicodeError):
        pass
    return None

