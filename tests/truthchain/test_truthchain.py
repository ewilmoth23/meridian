"""End-to-end TruthChain tests: keygen → sign → Merkle → verify."""

from __future__ import annotations

import datetime as dt
from pathlib import Path

from meridian.truthchain import (
    AdjustmentChainAttestation,
    ManifestEntry,
    ObservationManifest,
    SignedIdentity,
    build_attestation,
    build_manifest,
    generate_keypair,
    sign_manifest,
    verify_attestation,
    verify_deliverable,
    verify_manifest,
)
from meridian.truthchain.keystore import (
    b64,
    load_private,
    save_keypair,
    serialize_private,
    serialize_public,
)
from meridian.truthchain.merkle import merkle_root_of_hashes


def _identity_from(pk_b64: str) -> SignedIdentity:
    return SignedIdentity(
        surveyor_name="J. Surveyor",
        license_state="TX",
        license_number="12345",
        public_key_b64=pk_b64,
        issued_at=dt.datetime(2026, 5, 2, tzinfo=dt.UTC).isoformat(),
    )


def _make_signed(tmp: Path, public_key_b64: str, sk, *, source_name: str = "raw.gsi") -> ObservationManifest:
    src = tmp / source_name
    src.write_text("FAKE GSI CONTENT\n", encoding="ascii")
    entries = [
        ManifestEntry(
            obs_id=f"O-{i}",
            setup_id="S1",
            kind="horizontal_distance",
            from_point="P1",
            to_point=f"P{i+2}",
            value=10.0 + i,
            vector=None,
            sigma=0.005,
            target_height=1.5,
            timestamp=None,
        )
        for i in range(3)
    ]
    manifest = build_manifest(
        source_path=src,
        driver="leica_gsi",
        driver_version="0.1.0",
        setups=[{"id": "S1", "occupied": "P1"}],
        entries=entries,
        identity=_identity_from(public_key_b64),
    )
    return sign_manifest(manifest, sk)


def test_keypair_roundtrip(tmp_path):
    sk, pk = generate_keypair()
    raw_pub = serialize_public(pk)
    assert len(raw_pub) == 32

    pem = serialize_private(sk)
    sk2 = load_private(pem)
    assert b64(serialize_public(sk2.public_key())) == b64(raw_pub)

    path = save_keypair("test", sk, directory=tmp_path)
    assert path.exists()
    pem2 = path.read_bytes()
    assert pem2 == pem


def test_signed_manifest_verifies(tmp_path):
    sk, pk = generate_keypair()
    pub_b64 = b64(serialize_public(pk))
    m = _make_signed(tmp_path, pub_b64, sk)
    assert m.signature_b64 is not None
    assert verify_manifest(m) is True


def test_tampered_manifest_fails_verification(tmp_path):
    sk, pk = generate_keypair()
    pub_b64 = b64(serialize_public(pk))
    m = _make_signed(tmp_path, pub_b64, sk)

    # Forge an entry change without re-signing.
    forged_entries = list(m.entries)
    forged_entries[0] = ManifestEntry(
        obs_id=forged_entries[0].obs_id,
        setup_id=forged_entries[0].setup_id,
        kind=forged_entries[0].kind,
        from_point=forged_entries[0].from_point,
        to_point=forged_entries[0].to_point,
        value=999.0,                 # tamper!
        vector=forged_entries[0].vector,
        sigma=forged_entries[0].sigma,
        target_height=forged_entries[0].target_height,
        timestamp=forged_entries[0].timestamp,
    )
    forged = ObservationManifest(
        source_path=m.source_path,
        source_sha256=m.source_sha256,
        driver=m.driver,
        driver_version=m.driver_version,
        setups=m.setups,
        entries=tuple(forged_entries),
        created_at=m.created_at,
        identity=m.identity,
        signature_b64=m.signature_b64,   # old signature!
    )
    assert verify_manifest(forged) is False


def test_manifest_json_roundtrip(tmp_path):
    sk, pk = generate_keypair()
    pub_b64 = b64(serialize_public(pk))
    m = _make_signed(tmp_path, pub_b64, sk)
    payload = m.to_json()
    m2 = ObservationManifest.from_json(payload)
    assert m2.canonical_bytes() == m.canonical_bytes()
    assert verify_manifest(m2) is True


def test_merkle_root_simple_pair():
    import hashlib
    a = hashlib.sha256(b"a").digest()
    b = hashlib.sha256(b"b").digest()
    expected = hashlib.sha256(a + b).digest()
    assert merkle_root_of_hashes([a, b]) == expected


def test_merkle_root_single_leaf():
    import hashlib
    a = hashlib.sha256(b"single").digest()
    assert merkle_root_of_hashes([a]) == a


def test_merkle_root_odd_count_pads_last():
    import hashlib
    a = hashlib.sha256(b"a").digest()
    b = hashlib.sha256(b"b").digest()
    c = hashlib.sha256(b"c").digest()
    # Layer 1: pad → [a,b,c,c] → [hash(ab), hash(cc)]
    # Layer 2: → [hash(hash(ab) + hash(cc))]
    ab = hashlib.sha256(a + b).digest()
    cc = hashlib.sha256(c + c).digest()
    expected = hashlib.sha256(ab + cc).digest()
    assert merkle_root_of_hashes([a, b, c]) == expected


def test_attestation_build_and_verify(tmp_path):
    sk, pk = generate_keypair()
    pub_b64 = b64(serialize_public(pk))
    m1 = _make_signed(tmp_path, pub_b64, sk, source_name="a.gsi")
    m2 = _make_signed(tmp_path, pub_b64, sk, source_name="b.gsi")
    m3 = _make_signed(tmp_path, pub_b64, sk, source_name="c.gsi")
    attestation = build_attestation(
        [m1, m2, m3],
        algorithm_version="meridian.adjustment:0.1.0",
        sigma0=0.987,
        chi_square_passed=True,
        point_index=("P1", "P2", "P3"),
    )
    assert len(attestation.manifest_hashes) == 3
    assert verify_attestation(attestation, [m1, m2, m3]) is True
    # Re-ordering manifests changes the root (order is meaningful for replay).
    assert verify_attestation(attestation, [m1, m3, m2]) is False


def test_full_deliverable_verify(tmp_path):
    sk, pk = generate_keypair()
    pub_b64 = b64(serialize_public(pk))
    m1 = _make_signed(tmp_path, pub_b64, sk, source_name="a.gsi")
    m2 = _make_signed(tmp_path, pub_b64, sk, source_name="b.gsi")
    attestation = build_attestation(
        [m1, m2],
        algorithm_version="meridian.adjustment:0.1.0",
        sigma0=1.001,
        chi_square_passed=True,
        point_index=("P1", "P2"),
    )
    report = verify_deliverable(attestation=attestation, manifests=[m1, m2])
    assert report.overall_ok is True
    assert report.manifest_count == 2
    assert report.manifest_signatures_ok is True
    assert report.merkle_root_ok is True
    assert report.issues == ()


def test_attestation_json_roundtrip():
    a = AdjustmentChainAttestation(
        algorithm_version="meridian.adjustment:0.1.0",
        manifest_hashes=("aa" * 32, "bb" * 32),
        merkle_root="cc" * 32,
        sigma0=0.5,
        chi_square_passed=True,
        point_index=("P1", "P2"),
        notes="hello",
    )
    b = AdjustmentChainAttestation.from_json(a.to_json())
    assert a == b


def test_qr_png_renders():
    from meridian.truthchain.embed_qr import make_qr_png

    png = make_qr_png("https://verify.meridian.surv/v/abc")
    assert png[:8] == b"\x89PNG\r\n\x1a\n"
    assert len(png) > 100
