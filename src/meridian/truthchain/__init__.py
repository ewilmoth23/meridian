"""TruthChain — signed observation provenance (v0.7 in roadmap, v1 lands here).

A cryptographically verifiable chain from instrument → adjustment →
deliverable. Built on Ed25519 keypairs (per-surveyor + per-firm) and a
Merkle tree over observation manifests.

Status: planning stub for v0.7.

Components (to be implemented):

* ``keystore.py`` — Ed25519 keypair management. Per-surveyor private key
  protected by passphrase + OS keychain (via :mod:`keyring` or
  platform-specific KMS). Per-firm root key for cross-signing.
* ``manifest.py`` — defines the canonical raw-observation manifest format
  (sorted, deterministic, hash-stable) for each instrument driver.
* ``signing.py`` — extends the instrument-driver contract with a
  :meth:`sign_manifest` step at ingest, recording the signature alongside
  the observations in the project DB.
* ``merkle.py`` — Merkle root over the sorted manifest hashes that go
  into a network adjustment, plus the algorithm version pin.
* ``galileo_osnma.py`` — preserves the Galileo OSNMA-signed satellite
  messages from supported receivers (operational since 24 July 2025).
* ``verify.py`` — given a deliverable's verification URL, fetches the
  manifest, replays the adjustment, and confirms bit-for-bit.
* ``embed_qr.py`` — embeds a verification QR code into the PDF report
  and a verification URL attribute into DXF metadata.

Why this is a moat:
* No total-station or GNSS receiver vendor signs raw observation files
  at the device level today.
* Galileo OSNMA proves the constellation-level pattern is viable.
* Surveyors face litigation routinely; "show your work" is now
  cryptographically answerable.
* Insurance carriers and the litigation Bar are the natural early
  adopters.

Compatibility:
* Old projects without TruthChain still work; the chain is opt-in per
  project. Deliverables are marked "TruthChain verified" or not.
"""

from __future__ import annotations

from meridian.truthchain.embed_qr import (
    VerificationStamp,
    embed_stamp_into_pdf,
    make_qr_png,
    make_stamp,
)
from meridian.truthchain.keystore import (
    SignedIdentity,
    generate_keypair,
    keystore_dir,
    load_keypair,
    save_keypair,
    serialize_public,
)
from meridian.truthchain.manifest import (
    ManifestEntry,
    ObservationManifest,
    build_manifest,
    hash_file,
    sign_manifest,
    verify_manifest,
)
from meridian.truthchain.merkle import (
    AdjustmentChainAttestation,
    build_attestation,
    verify_attestation,
)
from meridian.truthchain.verify import (
    VerificationReport,
    load_manifests_from_dir,
    verify_deliverable,
)

__all__ = [
    "AdjustmentChainAttestation",
    "ManifestEntry",
    "ObservationManifest",
    "SignedIdentity",
    "VerificationReport",
    "VerificationStamp",
    "build_attestation",
    "build_manifest",
    "embed_stamp_into_pdf",
    "generate_keypair",
    "hash_file",
    "keystore_dir",
    "load_keypair",
    "load_manifests_from_dir",
    "make_qr_png",
    "make_stamp",
    "save_keypair",
    "serialize_public",
    "sign_manifest",
    "verify_attestation",
    "verify_deliverable",
    "verify_manifest",
]
