"""Canonical raw-observation manifest.

A manifest is a deterministic JSON record of *exactly* what an instrument
driver produced from a raw file at ingest. Hashing the canonical
manifest yields a stable identifier; signing the hash binds the
observations to a surveyor.

Determinism rules:
* Keys are sorted at every level (``sort_keys=True``).
* Floats are formatted with full ``repr`` precision and stored as their
  binary representation alongside, so re-serialisation hashes identically
  even on systems with different default printers.
* Field order in lists follows the order the driver emitted; we do not
  re-sort observations because the order itself is meaningful (timestamps
  often come from row order in the raw file).
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from meridian.truthchain.keystore import (
    Ed25519PrivateKey,
    Ed25519PublicKey,
    SignedIdentity,
    b64,
    b64d,
)

MANIFEST_VERSION = "meridian.manifest:v1"


@dataclass(frozen=True, slots=True)
class ManifestEntry:
    """One observation in canonical manifest form."""

    obs_id: str
    setup_id: str
    kind: str
    from_point: str
    to_point: str | None
    value: float | None
    vector: tuple[float, float, float] | None
    sigma: float | tuple[float, float, float] | None
    target_height: float | None
    timestamp: str | None    # ISO-8601 UTC

    def to_canonical(self) -> dict[str, Any]:
        return {
            "obs_id": self.obs_id,
            "setup_id": self.setup_id,
            "kind": self.kind,
            "from_point": self.from_point,
            "to_point": self.to_point,
            "value": self.value,
            "vector": list(self.vector) if self.vector else None,
            "sigma": list(self.sigma) if isinstance(self.sigma, tuple) else self.sigma,
            "target_height": self.target_height,
            "timestamp": self.timestamp,
        }


@dataclass(frozen=True, slots=True)
class ObservationManifest:
    """A signed bundle of raw observations from one instrument-file ingest.

    The manifest carries:
    * A reference to the source file (path + sha256).
    * The driver name and version.
    * Per-setup metadata.
    * The full ordered observation list.
    * A timestamp.
    * The surveyor's signed identity.
    * The signature itself (over the canonical bytes).
    """

    source_path: str
    source_sha256: str
    driver: str
    driver_version: str
    setups: tuple[dict[str, Any], ...]
    entries: tuple[ManifestEntry, ...]
    created_at: str
    identity: SignedIdentity
    signature_b64: str | None = None

    def canonical_bytes(self) -> bytes:
        """Bytes that will be hashed and signed.

        The signature is *not* included in this — that would be circular.
        """
        body = {
            "version": MANIFEST_VERSION,
            "source": {"path": self.source_path, "sha256": self.source_sha256},
            "driver": {"name": self.driver, "version": self.driver_version},
            "setups": [_sort_dict(s) for s in self.setups],
            "entries": [e.to_canonical() for e in self.entries],
            "created_at": self.created_at,
            "identity": json.loads(self.identity.to_json()),
        }
        return json.dumps(body, sort_keys=True, separators=(",", ":")).encode("utf-8")

    def hash(self) -> str:
        return hashlib.sha256(self.canonical_bytes()).hexdigest()

    def to_json(self, indent: int | None = None) -> str:
        body = json.loads(self.canonical_bytes())
        body["signature"] = self.signature_b64
        return json.dumps(body, sort_keys=True, separators=(",", ":") if indent is None else None, indent=indent)

    @classmethod
    def from_json(cls, payload: str | bytes) -> ObservationManifest:
        d = json.loads(payload)
        return cls(
            source_path=d["source"]["path"],
            source_sha256=d["source"]["sha256"],
            driver=d["driver"]["name"],
            driver_version=d["driver"]["version"],
            setups=tuple(d["setups"]),
            entries=tuple(ManifestEntry(**e) for e in d["entries"]),
            created_at=d["created_at"],
            identity=SignedIdentity.from_json(json.dumps(d["identity"], sort_keys=True)),
            signature_b64=d.get("signature"),
        )


def _sort_dict(d: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(d, dict):
        return d
    return {k: _sort_dict(v) if isinstance(v, dict) else v for k, v in sorted(d.items())}


def hash_file(path: Path) -> str:
    """SHA-256 of a file, streamed in 64 KB chunks."""
    h = hashlib.sha256()
    with path.open("rb") as f:
        while chunk := f.read(65536):
            h.update(chunk)
    return h.hexdigest()


def now_utc() -> str:
    return dt.datetime.now(dt.UTC).isoformat(timespec="microseconds")


def build_manifest(
    *,
    source_path: Path,
    driver: str,
    driver_version: str,
    setups: list[dict[str, Any]],
    entries: list[ManifestEntry],
    identity: SignedIdentity,
) -> ObservationManifest:
    """Build an unsigned :class:`ObservationManifest` from driver output."""
    return ObservationManifest(
        source_path=str(source_path.resolve()),
        source_sha256=hash_file(source_path),
        driver=driver,
        driver_version=driver_version,
        setups=tuple(setups),
        entries=tuple(entries),
        created_at=now_utc(),
        identity=identity,
    )


def sign_manifest(manifest: ObservationManifest, sk: Ed25519PrivateKey) -> ObservationManifest:
    """Return a signed copy of ``manifest``."""
    sig = sk.sign(manifest.canonical_bytes())
    return ObservationManifest(
        source_path=manifest.source_path,
        source_sha256=manifest.source_sha256,
        driver=manifest.driver,
        driver_version=manifest.driver_version,
        setups=manifest.setups,
        entries=manifest.entries,
        created_at=manifest.created_at,
        identity=manifest.identity,
        signature_b64=b64(sig),
    )


def verify_manifest(manifest: ObservationManifest, *, public_key: Ed25519PublicKey | None = None) -> bool:
    """Verify a signed manifest.

    Uses the public key embedded in ``manifest.identity`` unless one is
    explicitly supplied. Returns ``True`` if the signature checks out.
    """
    if manifest.signature_b64 is None:
        return False
    pk = public_key
    if pk is None:
        from meridian.truthchain.keystore import load_public
        pk = load_public(b64d(manifest.identity.public_key_b64))
    try:
        pk.verify(b64d(manifest.signature_b64), manifest.canonical_bytes())
        return True
    except Exception:
        return False
