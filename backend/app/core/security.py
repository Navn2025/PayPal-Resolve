"""Password hashing and verification without HTTP or database dependencies."""

from hashlib import scrypt
import hmac
import secrets


def password_hash(password):
    salt = secrets.token_bytes(16)
    key = scrypt(password.encode(), salt=salt, n=16384, r=8, p=1, dklen=32)
    return salt.hex() + ":" + key.hex()


def password_matches(password, encoded):
    salt, expected = encoded.split(":")
    key = scrypt(
        password.encode(), salt=bytes.fromhex(salt), n=16384, r=8, p=1, dklen=32
    )
    return hmac.compare_digest(key.hex(), expected)
