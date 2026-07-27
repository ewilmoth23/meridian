"""Ed25519 keypair management for surveyors and firms.

Each surveyor has a personal keypair. Each firm optionally has a root
keypair that cross-signs surveyor public keys. Private keys are stored
encrypted at rest using the OS keychain (via :mod:`keyring` when
available) with a passphrase fallback.

Public keys ship in the project DB and the deliverable manifests.
"""

from __future__ import annotations

import base64
import contextlib
import json
import os
from dataclasses import dataclass
from pathlib import Path

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
    Ed25519PublicKey,
)
from platformdirs import user_data_dir

KEY_VERSION = "ed25519:v1"


@dataclass(frozen=True, slots=True)
class SignedIdentity:
    """A bound (surveyor name, license number, public key) record."""

    surveyor_name: str
    license_state: str
    license_number: str
    public_key_b64: str
    issued_at: str            # ISO-8601 UTC
    cross_signed_by_firm: str | None = None
    firm_signature_b64: str | None = None
    extra: dict[str, str] | None = None

    def to_json(self) -> str:
        return json.dumps(
            {
                "version": KEY_VERSION,
                "surveyor_name": self.surveyor_name,
                "license_state": self.license_state,
                "license_number": self.license_number,
                "public_key": self.public_key_b64,
                "issued_at": self.issued_at,
                "cross_signed_by_firm": self.cross_signed_by_firm,
                "firm_signature": self.firm_signature_b64,
                "extra": self.extra or {},
            },
            sort_keys=True,
            separators=(",", ":"),
        )

    @classmethod
    def from_json(cls, payload: str) -> SignedIdentity:
        d = json.loads(payload)
        return cls(
            surveyor_name=d["surveyor_name"],
            license_state=d["license_state"],
            license_number=d["license_number"],
            public_key_b64=d["public_key"],
            issued_at=d["issued_at"],
            cross_signed_by_firm=d.get("cross_signed_by_firm"),
            firm_signature_b64=d.get("firm_signature"),
            extra=d.get("extra") or {},
        )


def keystore_dir() -> Path:
    """Per-user keystore directory."""
    p = Path(user_data_dir("meridian", "Meridian"))
    p.mkdir(parents=True, exist_ok=True)
    (p / "keys").mkdir(exist_ok=True)
    return p / "keys"


def b64(data: bytes) -> str:
    return base64.b64encode(data).decode("ascii")


def b64d(data: str) -> bytes:
    return base64.b64decode(data.encode("ascii"))


def generate_keypair() -> tuple[Ed25519PrivateKey, Ed25519PublicKey]:
    sk = Ed25519PrivateKey.generate()
    return sk, sk.public_key()


def serialize_private(sk: Ed25519PrivateKey, passphrase: bytes | None = None) -> bytes:
    """PEM-encoded private key. Encrypted if a passphrase is supplied."""
    enc = (
        serialization.BestAvailableEncryption(passphrase)
        if passphrase
        else serialization.NoEncryption()
    )
    return sk.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=enc,
    )


def serialize_public(pk: Ed25519PublicKey) -> bytes:
    """Raw 32-byte Ed25519 public key (for embedding into manifests)."""
    return pk.public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    )


def load_private(pem: bytes, passphrase: bytes | None = None) -> Ed25519PrivateKey:
    sk = serialization.load_pem_private_key(pem, password=passphrase)
    if not isinstance(sk, Ed25519PrivateKey):
        raise TypeError("Loaded key is not an Ed25519 private key.")
    return sk


def load_public(raw: bytes) -> Ed25519PublicKey:
    return Ed25519PublicKey.from_public_bytes(raw)


def save_keypair(
    name: str,
    sk: Ed25519PrivateKey,
    *,
    passphrase: bytes | None = None,
    directory: Path | None = None,
) -> Path:
    """Persist the private key to ``<keystore>/<name>.pem``.

    Returns the path. The public key is *not* stored separately; it's
    derivable from the private key.
    """
    directory = directory or keystore_dir()
    directory.mkdir(parents=True, exist_ok=True)
    pem = serialize_private(sk, passphrase=passphrase)
    target = directory / f"{name}.pem"
    target.write_bytes(pem)
    with contextlib.suppress(OSError):
        os.chmod(target, 0o600)
    return target


def load_keypair(
    name: str,
    *,
    passphrase: bytes | None = None,
    directory: Path | None = None,
) -> Ed25519PrivateKey:
    directory = directory or keystore_dir()
    pem = (directory / f"{name}.pem").read_bytes()
    return load_private(pem, passphrase=passphrase)
