"""PKCE (RFC 7636) code-verifier / code-challenge generation, S256 only
(ADR-022 §1, §3).

The `code_verifier` is generated per consent flow and held server-side in
the `oauth_pending` store keyed by `state` — it never reaches the browser.
Only the `code_challenge` (the SHA-256 digest, base64url, unpadded) is put
on the provider authorization URL.
"""

from __future__ import annotations

import base64
import hashlib
import secrets
from dataclasses import dataclass

_VERIFIER_BYTES = 64
"""64 random bytes -> an ~86-char base64url string, comfortably inside
RFC 7636's 43..128 character range for a `code_verifier`."""


def _b64url_unpadded(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def challenge_for_verifier(code_verifier: str) -> str:
    """`BASE64URL(SHA256(code_verifier))`, unpadded — the `S256`
    `code_challenge` transformation, RFC 7636 §4.2."""
    digest = hashlib.sha256(code_verifier.encode("ascii")).digest()
    return _b64url_unpadded(digest)


@dataclass(frozen=True, slots=True)
class PkcePair:
    """One consent flow's PKCE material. `verifier` is secret (server-side,
    `oauth_pending`); `challenge` is public (authorization URL)."""

    verifier: str
    challenge: str


def generate_pkce_pair() -> PkcePair:
    """Fresh, cryptographically-random `code_verifier` plus its matching
    `S256` `code_challenge`."""
    verifier = _b64url_unpadded(secrets.token_bytes(_VERIFIER_BYTES))
    return PkcePair(verifier=verifier, challenge=challenge_for_verifier(verifier))


def generate_state() -> str:
    """A 32-byte URL-safe random `state` value (ADR-022 §3) — the CSRF
    defence, single-use, resolved server-side to the `oauth_pending`
    record that carries the matching `code_verifier`."""
    return secrets.token_urlsafe(32)


__all__ = ["PkcePair", "challenge_for_verifier", "generate_pkce_pair", "generate_state"]
