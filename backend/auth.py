"""
Authentication module — JWT + bcrypt.

Adapted from ar_agent's app/core/security.py + app/api/deps.py for Flask/SQLite.
Provides: password hashing, JWT tokens, and a @require_auth decorator.
"""

import datetime
import functools
import hashlib
import secrets
from typing import Optional

import bcrypt
import jwt
from flask import request, jsonify, g

from config import SECRET_KEY, ALGORITHM, ACCESS_TOKEN_EXPIRE_MINUTES, REFRESH_TOKEN_EXPIRE_DAYS


# -----------------------------------------------------------------------
# Password hashing (bcrypt)
# -----------------------------------------------------------------------

def get_password_hash(password: str) -> str:
    """Hash a password with bcrypt."""
    return bcrypt.hashpw(
        password.encode("utf-8"),
        bcrypt.gensalt(),
    ).decode("utf-8")


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Verify a password against its bcrypt hash."""
    return bcrypt.checkpw(
        plain_password.encode("utf-8"),
        hashed_password.encode("utf-8"),
    )


# -----------------------------------------------------------------------
# JWT tokens
# -----------------------------------------------------------------------

def create_access_token(user_id: int, expires_minutes: Optional[int] = None,
                        email: str = "") -> str:
    """Create a short-lived JWT access token."""
    expire = datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(
        minutes=expires_minutes if expires_minutes is not None else ACCESS_TOKEN_EXPIRE_MINUTES
    )
    payload = {"sub": str(user_id), "exp": expire, "type": "access"}
    if email:
        payload["email"] = email
    return jwt.encode(payload, SECRET_KEY, algorithm=ALGORITHM)


def create_refresh_token(user_id: int, expires_days: Optional[int] = None) -> str:
    """Create a long-lived JWT refresh token."""
    expire = datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(
        days=expires_days if expires_days is not None else REFRESH_TOKEN_EXPIRE_DAYS
    )
    payload = {"sub": str(user_id), "exp": expire, "type": "refresh"}
    return jwt.encode(payload, SECRET_KEY, algorithm=ALGORITHM)


def decode_access_token(token: str) -> Optional[dict]:
    """Decode and validate a JWT access token. Rejects refresh tokens."""
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
    except jwt.PyJWTError:
        return None
    if payload.get("type") != "access":
        return None
    return payload


def decode_refresh_token(token: str) -> Optional[dict]:
    """Decode and validate a JWT refresh token. Rejects access tokens."""
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
    except jwt.PyJWTError:
        return None
    if payload.get("type") != "refresh":
        return None
    return payload


# -----------------------------------------------------------------------
# Single-use purpose tokens (password reset)
# -----------------------------------------------------------------------

def create_purpose_token(user_id: int, purpose: str, expires_hours: int) -> str:
    """Create a short-lived JWT for a specific purpose (e.g. password reset)."""
    expire = datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(hours=expires_hours)
    payload = {"sub": str(user_id), "purpose": purpose, "exp": expire}
    return jwt.encode(payload, SECRET_KEY, algorithm=ALGORITHM)


def decode_purpose_token(token: str, purpose: str) -> Optional[dict]:
    """Decode a purpose token. Returns None if invalid/expired/wrong purpose."""
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
    except jwt.PyJWTError:
        return None
    if payload.get("purpose") != purpose:
        return None
    return payload


# -----------------------------------------------------------------------
# Password validation
# -----------------------------------------------------------------------

_COMMON_PASSWORDS = {
    "password", "password1", "password123", "passw0rd", "p@ssword",
    "12345678", "123456789", "1234567890", "qwerty123", "qwerty1234",
    "letmein", "letmein123", "welcome", "welcome1", "welcome123",
    "admin", "admin123", "administrator", "root", "test1234",
    "iloveyou", "monkey123", "dragon123", "sunshine", "princess",
    "master123", "shadow", "michael", "football", "baseball",
    "abc12345", "abcd1234", "1q2w3e4r", "qazwsx", "qwertyuiop",
    "trustno1", "hello123", "freedom", "whatever", "ninja123",
    "starwars", "computer", "internet", "samsung", "michael1",
}


def validate_password_strength(password: str) -> Optional[str]:
    """Return None if password meets policy, or a user-facing error string.

    Policy (same as ar_agent):
      - At least 8 characters.
      - Contains at least one letter and one number.
      - Not in the common-passwords blacklist (case-insensitive).
    """
    if len(password) < 8:
        return "Password must be at least 8 characters long."
    has_letter = any(c.isalpha() for c in password)
    has_digit = any(c.isdigit() for c in password)
    if not (has_letter and has_digit):
        return "Password must contain at least one letter and one number."
    if password.lower() in _COMMON_PASSWORDS:
        return "That password is too common. Pick something less guessable."
    return None


# -----------------------------------------------------------------------
# Token extraction helper
# -----------------------------------------------------------------------

def extract_token_from_request() -> Optional[str]:
    """Extract Bearer token from Authorization header."""
    auth_header = request.headers.get("Authorization", "")
    if auth_header.startswith("Bearer "):
        return auth_header[7:]
    return None


# -----------------------------------------------------------------------
# @require_auth decorator
# -----------------------------------------------------------------------

def require_auth(f):
    """Decorator that requires a valid JWT access token.

    On success, sets g.current_user_id and g.current_user_email.
    On failure, returns 401 with JSON error.
    """
    @functools.wraps(f)
    def decorated(*args, **kwargs):
        token = extract_token_from_request()
        if not token:
            return jsonify({"error": "Missing authentication token"}), 401

        payload = decode_access_token(token)
        if payload is None:
            return jsonify({"error": "Invalid or expired token"}), 401

        try:
            user_id = int(payload["sub"])
        except (KeyError, ValueError):
            return jsonify({"error": "Invalid token payload"}), 401

        g.current_user_id = user_id
        # Also fetch email for audit logging (#20)
        g.current_user_email = payload.get("email", "")
        return f(*args, **kwargs)

    return decorated
