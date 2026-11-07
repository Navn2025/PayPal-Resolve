"""Fixtures for the local Google code and JWKS mocks, with ephemeral keys."""

from datetime import datetime, timedelta, timezone
import json
from uuid import uuid4

from cryptography.hazmat.primitives.asymmetric import rsa
import jwt


def register_google_code(
    http, authorize, *, email="buyer@gmail.com", invalid_signature=False, **claims
):
    now = datetime.now(timezone.utc)
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    kid, code = uuid4().hex, uuid4().hex
    public = json.loads(jwt.algorithms.RSAAlgorithm.to_jwk(key.public_key()))
    public.update(kid=kid, alg="RS256", use="sig")
    values = {
        "iss": "https://accounts.google.com",
        "aud": "simulation-google-client",
        "sub": "synthetic-customer",
        "email": email,
        "email_verified": True,
        "iat": now,
        "exp": now + timedelta(minutes=5),
        "nonce": authorize["nonce"],
        **claims,
    }
    signer = (
        rsa.generate_private_key(public_exponent=65537, key_size=2048)
        if invalid_signature
        else key
    )
    token = jwt.encode(values, signer, algorithm="RS256", headers={"kid": kid})
    http.post(
        "https://www.googleapis.com/__resolve_fixture/jwk", json=public
    ).raise_for_status()
    http.post(
        "https://oauth2.googleapis.com/__resolve_fixture/authorize",
        json={
            "code": code,
            "id_token": token,
            "challenge": authorize["code_challenge"],
            "redirect": authorize["redirect_uri"],
        },
    ).raise_for_status()
    return code
