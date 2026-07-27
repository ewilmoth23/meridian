"""End-to-end verification of a TruthChain deliverable.

Given:
* a directory of ``*.manifest.json`` files (signed observation manifests),
* an :class:`AdjustmentChainAttestation`,

verify:
1. Each manifest's signature is valid.
2. Each manifest's hash is among the attestation's leaves.
3. The Merkle root over the manifests' hashes matches the attestation's root.

Optional step (slow, opt-in): re-run the adjustment from the same inputs
and confirm the published σ₀ and adjusted-point coordinates fall within
tolerance. This validates the algorithm pin, not just the inputs.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from meridian.truthchain.manifest import ObservationManifest, verify_manifest
from meridian.truthchain.merkle import (
    AdjustmentChainAttestation,
    verify_attestation,
)


@dataclass(frozen=True, slots=True)
class VerificationReport:
    """Outcome of verifying a deliverable."""

    overall_ok: bool
    manifest_count: int
    manifest_signatures_ok: bool
    merkle_root_ok: bool
    issues: tuple[str, ...]

    def summary(self) -> str:
        if self.overall_ok:
            return f"OK ({self.manifest_count} manifests, signatures + Merkle root verified)"
        return f"FAILED ({len(self.issues)} issues): " + "; ".join(self.issues)


def load_manifests_from_dir(directory: Path, *, glob: str = "*.manifest.json") -> list[ObservationManifest]:
    """Load all manifests in ``directory`` matching ``glob``."""
    manifests: list[ObservationManifest] = []
    for p in sorted(directory.glob(glob)):
        manifests.append(ObservationManifest.from_json(p.read_text(encoding="utf-8")))
    return manifests


def verify_deliverable(
    *,
    attestation: AdjustmentChainAttestation,
    manifests: list[ObservationManifest],
) -> VerificationReport:
    """Run the full TruthChain verification on a list of inputs."""
    issues: list[str] = []

    sigs_ok = True
    for m in manifests:
        if not verify_manifest(m):
            sigs_ok = False
            issues.append(f"Manifest signature invalid: {m.source_path}")

    root_ok = verify_attestation(attestation, manifests)
    if not root_ok:
        issues.append("Merkle root mismatch — manifests do not reproduce the attestation.")

    return VerificationReport(
        overall_ok=sigs_ok and root_ok,
        manifest_count=len(manifests),
        manifest_signatures_ok=sigs_ok,
        merkle_root_ok=root_ok,
        issues=tuple(issues),
    )
