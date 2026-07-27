"""Merkle root over the inputs to a network adjustment.

Given a list of :class:`ObservationManifest` (one per ingest into the
project) and an algorithm-version pin, build a Merkle tree whose root
identifies the *exact* set of inputs that produced an adjustment. Embed
the root in the deliverable; anyone with the manifests + the same
algorithm version can replay and confirm bit-for-bit.

Notes
-----
* Leaves are SHA-256 hashes of canonical manifest bytes (see
  :func:`meridian.truthchain.manifest.ObservationManifest.canonical_bytes`).
* Internal nodes hash the *concatenation* of children, not a delimiter.
  This matches the Bitcoin / Certificate-Transparency convention.
* Odd numbers of leaves are padded by duplicating the last leaf — the
  same convention CT uses to avoid collision tricks.

"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable, Sequence
from dataclasses import dataclass

from meridian.truthchain.manifest import ObservationManifest

ALGORITHM_VERSION_PREFIX = "meridian.adjustment:"


def _sha(data: bytes) -> bytes:
    return hashlib.sha256(data).digest()


def _hex(data: bytes) -> str:
    return data.hex()


def _hash_pair(left: bytes, right: bytes) -> bytes:
    return _sha(left + right)


def merkle_root_of_hashes(hashes: Sequence[bytes]) -> bytes:
    """Compute the Merkle root over a sequence of leaf hashes."""
    if not hashes:
        raise ValueError("Cannot build a Merkle tree over zero leaves.")
    layer = list(hashes)
    while len(layer) > 1:
        if len(layer) % 2 == 1:
            layer = [*layer, layer[-1]]
        layer = [_hash_pair(layer[i], layer[i + 1]) for i in range(0, len(layer), 2)]
    return layer[0]


@dataclass(frozen=True, slots=True)
class AdjustmentChainAttestation:
    """The root of a chain — embedded into deliverables.

    Carries everything a verifier needs to (a) re-fetch the inputs and
    (b) re-run the adjustment.
    """

    algorithm_version: str           # e.g. "meridian.adjustment:0.1.0"
    manifest_hashes: tuple[str, ...] # hex sha-256 of each input manifest
    merkle_root: str                 # hex sha-256
    sigma0: float
    chi_square_passed: bool
    point_index: tuple[str, ...]
    notes: str | None = None

    def to_json(self) -> str:
        return json.dumps(
            {
                "algorithm_version": self.algorithm_version,
                "manifest_hashes": list(self.manifest_hashes),
                "merkle_root": self.merkle_root,
                "sigma0": self.sigma0,
                "chi_square_passed": self.chi_square_passed,
                "point_index": list(self.point_index),
                "notes": self.notes,
            },
            sort_keys=True,
            separators=(",", ":"),
        )

    @classmethod
    def from_json(cls, payload: str | bytes) -> AdjustmentChainAttestation:
        d = json.loads(payload)
        return cls(
            algorithm_version=d["algorithm_version"],
            manifest_hashes=tuple(d["manifest_hashes"]),
            merkle_root=d["merkle_root"],
            sigma0=d["sigma0"],
            chi_square_passed=d["chi_square_passed"],
            point_index=tuple(d["point_index"]),
            notes=d.get("notes"),
        )


def build_attestation(
    manifests: Iterable[ObservationManifest],
    *,
    algorithm_version: str,
    sigma0: float,
    chi_square_passed: bool,
    point_index: Sequence[str],
    notes: str | None = None,
) -> AdjustmentChainAttestation:
    """Build a verifiable attestation from a list of input manifests."""
    leaves: list[bytes] = []
    hex_hashes: list[str] = []
    for m in manifests:
        h = _sha(m.canonical_bytes())
        leaves.append(h)
        hex_hashes.append(_hex(h))
    if not leaves:
        raise ValueError("Cannot build an attestation over zero manifests.")
    root = merkle_root_of_hashes(leaves)
    return AdjustmentChainAttestation(
        algorithm_version=algorithm_version,
        manifest_hashes=tuple(hex_hashes),
        merkle_root=_hex(root),
        sigma0=sigma0,
        chi_square_passed=chi_square_passed,
        point_index=tuple(point_index),
        notes=notes,
    )


def verify_attestation(
    attestation: AdjustmentChainAttestation,
    manifests: Iterable[ObservationManifest],
) -> bool:
    """Verify that the supplied manifests reproduce the attestation root."""
    leaves = [_sha(m.canonical_bytes()) for m in manifests]
    if not leaves:
        return False
    root_hex = _hex(merkle_root_of_hashes(leaves))
    return root_hex == attestation.merkle_root
