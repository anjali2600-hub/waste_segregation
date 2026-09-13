"""
Authentication & authorization helpers.

- Passwords are hashed with Werkzeug's PBKDF2 implementation (no external
  crypto dependency needed).
- Sessions are stateless JWTs sent as `Authorization: Bearer <token>`.
- Role checks are enforced on the backend (not just hidden in the UI), per
  the project's security requirements.
"""
from functools import wraps
from datetime import datetime, timezone

import jwt
from flask import request, jsonify, g
from werkzeug.security import generate_password_hash, check_password_hash

import config
from db import get_db, dict_from_row


def hash_password(password: str) -> str:
    return generate_password_hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    return check_password_hash(password_hash, password)


def issue_token(user_row) -> str:
    now = datetime.now(timezone.utc)
    payload = {
        "user_id": user_row["id"],
        "role": user_row["role"],
        "name": user_row["name"],
        "iat": now,
        "exp": now + config.JWT_EXPIRY,
    }
    return jwt.encode(payload, config.JWT_SECRET, algorithm="HS256")


def decode_token(token: str):
    try:
        return jwt.decode(token, config.JWT_SECRET, algorithms=["HS256"])
    except jwt.PyJWTError:
        return None


def _extract_token():
    header = request.headers.get("Authorization", "")
    if header.startswith("Bearer "):
        return header[len("Bearer "):].strip()
    return None


def login_required(fn):
    """Attach the authenticated user (dict) to g.current_user, or 401."""
    @wraps(fn)
    def wrapper(*args, **kwargs):
        token = _extract_token()
        if not token:
            return jsonify(error="Missing authentication token"), 401
        payload = decode_token(token)
        if not payload:
            return jsonify(error="Invalid or expired token"), 401

        db = get_db()
        user = db.execute(
            "SELECT * FROM users WHERE id = ?", (payload["user_id"],)
        ).fetchone()
        if not user:
            return jsonify(error="User no longer exists"), 401

        g.current_user = dict_from_row(user)
        return fn(*args, **kwargs)
    return wrapper


def require_role(*roles):
    """Combine with login_required: restrict endpoint to specific roles."""
    def decorator(fn):
        @wraps(fn)
        @login_required
        def wrapper(*args, **kwargs):
            if g.current_user["role"] not in roles:
                return jsonify(error="Forbidden: insufficient role"), 403
            return fn(*args, **kwargs)
        return wrapper
    return decorator
