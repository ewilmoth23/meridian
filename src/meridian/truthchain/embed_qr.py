"""Embed verification QR codes / URLs into deliverables.

A TruthChain-verified PDF/DXF carries:

1. A short verification URL (e.g. ``https://verify.meridian.surv/v/<id>``
   or a self-hosted alternative) — useful for printed deliverables.
2. A QR code rendering that URL — placed in the title block.
3. A JSON sidecar embedded as a non-printing text annotation in the PDF
   carrying the full attestation + signed manifest references.

The QR rendering uses :mod:`qrcode` with PIL backend. The PDF embedding
uses :mod:`reportlab` (already a project dependency).
"""

from __future__ import annotations

import io
import json
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from meridian.truthchain.merkle import AdjustmentChainAttestation


@dataclass(frozen=True, slots=True)
class VerificationStamp:
    """All the bits a deliverable embeds for downstream verification."""

    verification_url: str
    attestation_json: str
    qr_png_bytes: bytes


def make_qr_png(payload: str, *, box_size: int = 8, border: int = 2) -> bytes:
    """Render ``payload`` as a PNG QR code and return the bytes.

    Uses error-correction level Q (~25%) so a logo overlay or partial
    smudge doesn't prevent scanning.
    """
    try:
        import qrcode
        from qrcode.constants import ERROR_CORRECT_Q
    except ImportError as e:  # pragma: no cover
        raise RuntimeError(
            "qrcode is required. Install with: pip install qrcode[pil]"
        ) from e
    qr = qrcode.QRCode(
        version=None,
        error_correction=ERROR_CORRECT_Q,
        box_size=box_size,
        border=border,
    )
    qr.add_data(payload)
    qr.make(fit=True)
    img = qr.make_image(fill_color="black", back_color="white")
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def make_stamp(
    attestation: AdjustmentChainAttestation,
    *,
    base_url: str = "https://verify.meridian.surv/v/",
) -> VerificationStamp:
    """Produce a :class:`VerificationStamp` for a given attestation.

    The verification URL embeds the merkle root so a verifier can ask the
    repository ``base_url + <root>`` for the manifests, replay, and
    confirm. If you self-host, point ``base_url`` at your own service.
    """
    url = f"{base_url}{attestation.merkle_root}"
    qr = make_qr_png(url)
    return VerificationStamp(
        verification_url=url,
        attestation_json=attestation.to_json(),
        qr_png_bytes=qr,
    )


def embed_stamp_into_pdf(stamp: VerificationStamp, pdf_path: Path) -> None:
    """Append a "TruthChain Verification" page to an existing PDF.

    Idempotent-ish: re-running with the same stamp adds another page.
    For a one-shot pipeline this is fine; the caller decides.
    """
    try:
        from pypdf import PdfReader, PdfWriter
        from reportlab.lib.pagesizes import letter
        from reportlab.lib.units import inch
        from reportlab.pdfgen import canvas
    except ImportError as e:  # pragma: no cover
        raise RuntimeError(
            "embed_stamp_into_pdf requires pypdf and reportlab. "
            "Install with: pip install pypdf reportlab"
        ) from e
    if not pdf_path.exists():
        raise FileNotFoundError(pdf_path)

    # Build the verification page in-memory.
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=letter)
    c.setTitle("TruthChain Verification")

    # Title block
    c.setFont("Helvetica-Bold", 18)
    c.drawString(1 * inch, 10 * inch, "TruthChain Verification")
    c.setFont("Helvetica", 10)
    c.drawString(
        1 * inch,
        9.7 * inch,
        "This page anchors the deliverable to a verifiable observation chain.",
    )

    # QR code
    from reportlab.lib.utils import ImageReader

    qr_img = ImageReader(io.BytesIO(stamp.qr_png_bytes))
    c.drawImage(qr_img, 1 * inch, 6.5 * inch, width=2.8 * inch, height=2.8 * inch)

    # Verification URL
    c.setFont("Helvetica-Bold", 11)
    c.drawString(4.2 * inch, 9.0 * inch, "Verification URL:")
    c.setFont("Courier", 9)
    c.drawString(4.2 * inch, 8.7 * inch, stamp.verification_url)

    # Attestation summary
    attest = json.loads(stamp.attestation_json)
    c.setFont("Helvetica-Bold", 11)
    c.drawString(4.2 * inch, 8.2 * inch, "Adjustment attestation")
    c.setFont("Helvetica", 9)
    rows = [
        f"Algorithm:      {attest['algorithm_version']}",
        f"Manifests in:   {len(attest['manifest_hashes'])}",
        f"Merkle root:    {attest['merkle_root'][:16]}…{attest['merkle_root'][-16:]}",
        f"σ0 (posterior): {attest['sigma0']:.6f}",
        f"Chi-square:     {'PASS' if attest['chi_square_passed'] else 'FAIL'}",
        f"Adjusted pts:   {len(attest['point_index'])}",
    ]
    for i, row in enumerate(rows):
        c.drawString(4.2 * inch, (7.9 - 0.2 * i) * inch, row)

    # Footer
    c.setFont("Helvetica-Oblique", 8)
    c.drawString(
        1 * inch,
        0.5 * inch,
        "TruthChain — Meridian. Replay-verify by fetching the attestation JSON above.",
    )

    c.showPage()
    c.save()
    buf.seek(0)

    # Append to the existing PDF.
    reader = PdfReader(str(pdf_path))
    writer = PdfWriter()
    for page in reader.pages:
        writer.add_page(page)
    writer.append_pages_from_reader(PdfReader(buf))
    # Embed the attestation JSON as PDF metadata + a file attachment.
    writer.add_attachment("truthchain_attestation.json", stamp.attestation_json.encode("utf-8"))
    metadata = dict(reader.metadata or {})
    metadata.setdefault("/TruthChainURL", stamp.verification_url)
    writer.add_metadata(metadata)
    with open(pdf_path, "wb") as f:
        writer.write(f)
