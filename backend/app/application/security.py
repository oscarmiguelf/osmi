import hashlib
import os
import secrets
import time
import uuid

import bcrypt
import jwt
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError

JWT_SECRET = os.environ["JWT_SECRET"]
# A short or sample secret lets anyone forge sessions (HS256): refuse to start instead
if len(JWT_SECRET) < 32 or "change-me" in JWT_SECRET:
    raise RuntimeError("JWT_SECRET must be a random string of at least 32 characters (e.g. openssl rand -hex 32)")
ACCESS_TOKEN_TTL = 900

_ph = PasswordHasher()  # Argon2id
# Verified against for unknown/locked users so response time doesn't reveal whether the account exists.
DUMMY_HASH = _ph.hash(secrets.token_hex(16))


COMMON_PASSWORDS = {
    "password", "password1", "12345678", "123456789", "1234567890", "qwerty123", "qwertyuiop", "11111111",
    "iloveyou", "admin123", "administrator", "welcome1", "contraseña", "contrasena", "abc12345", "00000000",
    "passw0rd", "letmein1", "sunshine", "princess",
}


def password_problems(password: str, email: str) -> list[str]:
    """The one password policy (create, reset and change). Returns the rules that failed, empty if it's fine."""
    problems = []
    if len(password) < 8:
        problems.append("min_length")
    if len(password) > 128:
        problems.append("max_length")
    if password.strip().lower() == email.strip().lower():
        problems.append("same_as_email")
    if password.lower() in COMMON_PASSWORDS:
        problems.append("too_common")
    return problems


def hash_password(password: str) -> str:
    return _ph.hash(password)


def temporary_password() -> str:
    """Readable one-time password for a new user (no 0/O or 1/l/I to misread when dictating it)."""
    alphabet = "abcdefghjkmnpqrstuvwxyzABCDEFGHJKLMNPQRSTUVWXYZ23456789"
    return "".join(secrets.choice(alphabet) for _ in range(12))


def verify_password(password: str, password_hash: str) -> bool:
    try:
        if password_hash.startswith("$argon2"):
            return _ph.verify(password_hash, password)
        # Seed admin is hashed in SQL with bcrypt ($2a$12$...).
        return bcrypt.checkpw(password.encode(), password_hash.encode())
    except (VerificationError, InvalidHashError, ValueError):
        return False


def create_access_token(user_id) -> str:
    now = int(time.time())
    claims = {"sub": str(user_id), "iat": now, "exp": now + ACCESS_TOKEN_TTL, "jti": uuid.uuid4().hex}
    return jwt.encode(claims, JWT_SECRET, algorithm="HS256")


def decode_access_token(token: str) -> uuid.UUID | None:
    try:
        claims = jwt.decode(token, JWT_SECRET, algorithms=["HS256"],
                            options={"require": ["sub", "iat", "exp", "jti"]})
        return uuid.UUID(claims["sub"])
    except (jwt.PyJWTError, ValueError):
        return None


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def new_refresh_token() -> tuple[str, str]:
    token = secrets.token_urlsafe(32)
    return token, hash_token(token)
