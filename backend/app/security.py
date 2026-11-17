import hashlib
import hmac
import os
import re
import time
from urllib.parse import urlsplit
from uuid import uuid4

COOKIE_NAME = "docwise_visitor"
COOKIE_MAX_AGE = 30 * 24 * 60 * 60
_VISITOR_ID = re.compile(r"^[0-9a-f]{32}$")
_LOCAL_SECRET = "docwise-local-development-secret"


def session_secret() -> str:
    secret = os.getenv("DOCWISE_SESSION_SECRET")
    if secret:
        return secret
    if os.getenv("DOCWISE_ENV", "development").lower() == "production":
        raise RuntimeError("DOCWISE_SESSION_SECRET must be configured in production")
    return _LOCAL_SECRET


def validate_production_settings() -> None:
    if os.getenv("DOCWISE_ENV", "development").lower() != "production":
        return
    secret = session_secret()
    if len(secret) < 32:
        raise RuntimeError("DOCWISE_SESSION_SECRET must contain at least 32 characters")
    origins = [origin.strip() for origin in os.getenv("DOCWISE_CORS_ORIGINS", "").split(",") if origin.strip()]
    if not origins or any(
        "*" in origin or urlsplit(origin).scheme != "https" or not urlsplit(origin).netloc or urlsplit(origin).path
        for origin in origins
    ):
        raise RuntimeError("Set DOCWISE_CORS_ORIGINS to exact HTTPS frontend origins in production")


def _signature(payload: str) -> str:
    return hmac.new(session_secret().encode(), payload.encode(), hashlib.sha256).hexdigest()


def sign_visitor_id(visitor_id: str) -> str:
    if not _VISITOR_ID.fullmatch(visitor_id):
        raise ValueError("Invalid visitor identifier")
    issued_at = str(int(time.time()))
    payload = f"{visitor_id}.{issued_at}"
    return f"{payload}.{_signature(payload)}"


def verify_visitor_cookie(cookie: str | None) -> str | None:
    if not cookie:
        return None
    try:
        visitor_id, issued_at, supplied = cookie.split(".", 2)
        issued = int(issued_at)
    except (ValueError, TypeError):
        return None
    if not _VISITOR_ID.fullmatch(visitor_id) or not issued_at.isdecimal():
        return None
    age = int(time.time()) - issued
    if age < -300 or age > COOKIE_MAX_AGE:
        return None
    payload = f"{visitor_id}.{issued_at}"
    if not hmac.compare_digest(_signature(payload), supplied):
        return None
    return visitor_id


def new_visitor_id() -> str:
    return uuid4().hex


def hash_client_ip(address: str) -> str:
    return hmac.new(session_secret().encode(), address.encode(), hashlib.sha256).hexdigest()
