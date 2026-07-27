"""Meridian desktop entry point.

A minimal v0.1 shell with four workflow actions wired to the services.
The full multi-tab layout, dock widgets, and 3D viewer arrive in v0.2.
"""

from __future__ import annotations

import sys
from pathlib import Path


def main() -> int:
    """Launch the desktop app. Importing PySide6 lazily so the library
    install (without the ``desktop`` extra) doesn't error out.
    """
    try:
        from PySide6.QtCore import Qt
        from PySide6.QtWidgets import (
            QApplication,
            QLabel,
            QMainWindow,
            QPushButton,
            QStatusBar,
            QVBoxLayout,
            QWidget,
        )
    except ImportError:
        print(
            "PySide6 is not installed. Install with: pip install 'meridian[desktop]'",
            file=sys.stderr,
        )
        return 2

    app = QApplication.instance() or QApplication(sys.argv)
    win = QMainWindow()
    win.setWindowTitle("Meridian — where every line is true")
    win.resize(1280, 800)

    central = QWidget()
    layout = QVBoxLayout(central)
    layout.setAlignment(Qt.AlignmentFlag.AlignTop)
    layout.setContentsMargins(24, 24, 24, 24)

    title = QLabel("Meridian")
    title.setStyleSheet("font-size: 28px; font-weight: 600;")
    subtitle = QLabel("Where every line is true.")
    subtitle.setStyleSheet("color: #5a6a82; font-size: 14px;")
    layout.addWidget(title)
    layout.addWidget(subtitle)

    layout.addSpacing(16)

    deed_btn = QPushButton("Deed → DXF / PDF")
    network_btn = QPushButton("Adjust Control Network")
    traverse_btn = QPushButton("Run Total-Station Traverse")
    cloud_btn = QPushButton("Classify Point Cloud → Contours")
    for b in (deed_btn, network_btn, traverse_btn, cloud_btn):
        b.setStyleSheet("padding: 12px 18px; font-size: 14px; text-align: left;")
        layout.addWidget(b)

    layout.addStretch(1)
    layout.addWidget(QLabel("v0.1 — desktop shell. Full GUI lands in v0.2."))

    win.setCentralWidget(central)

    # Wire actions -- each shows a file picker and runs the matching service.
    deed_btn.clicked.connect(lambda: _on_deed(win))
    network_btn.clicked.connect(lambda: _on_network(win))
    traverse_btn.clicked.connect(lambda: _on_traverse(win))
    cloud_btn.clicked.connect(lambda: _on_cloud(win))

    status = QStatusBar()
    status.showMessage("Ready.")
    win.setStatusBar(status)

    win.show()
    return app.exec()


def _on_deed(win) -> None:
    from PySide6.QtWidgets import QFileDialog, QMessageBox

    src, _ = QFileDialog.getOpenFileName(win, "Open deed text file", "", "Text (*.txt *.md);;All (*)")
    if not src:
        return
    out_dxf, _ = QFileDialog.getSaveFileName(win, "Save DXF", "", "DXF (*.dxf)")
    if not out_dxf:
        return
    try:
        from meridian.domain.crs import CRS
        from meridian.services.deed_service import DeedService

        text = Path(src).read_text(encoding="utf-8", errors="replace")
        result = DeedService().parse_to_cad(
            text=text,
            crs=CRS(epsg=2277),
            dxf_path=Path(out_dxf),
        )
        QMessageBox.information(
            win,
            "Deed processed",
            f"Calls: {len(result.parcel.calls)}\n"
            f"Misclosure: {result.misclosure_m:.4f} m\n"
            f"DXF: {out_dxf}",
        )
    except Exception as e:
        QMessageBox.critical(win, "Deed parse failed", str(e))


def _on_network(win) -> None:
    from PySide6.QtWidgets import QFileDialog, QMessageBox

    src, _ = QFileDialog.getOpenFileName(win, "Open network spec JSON", "", "JSON (*.json)")
    if not src:
        return
    QMessageBox.information(
        win,
        "Network adjustment",
        "Run via CLI for v0.1: meridian network adjust <spec.json>\n"
        "Full UI for this slice arrives in v0.2.",
    )


def _on_traverse(win) -> None:
    from PySide6.QtWidgets import QFileDialog, QMessageBox

    src, _ = QFileDialog.getOpenFileName(
        win, "Open total-station file", "", "Total station (*.gsi *.jxl *.rw5);;All (*)"
    )
    if not src:
        return
    try:
        from meridian.services.traverse_service import TraverseService

        res = TraverseService().run_from_file(Path(src))
        QMessageBox.information(
            win,
            f"Traverse: {Path(src).name}",
            f"Driver: {res.driver}\n"
            f"Setups: {res.setups_count}, observations: {res.observations_count}, legs: {res.legs_count}\n"
            f"Closure: {res.result.closure_distance:.4f} m",
        )
    except Exception as e:
        QMessageBox.critical(win, "Traverse failed", str(e))


def _on_cloud(win) -> None:
    from PySide6.QtWidgets import QFileDialog, QMessageBox

    src, _ = QFileDialog.getOpenFileName(win, "Open LAS / LAZ", "", "LAS (*.las *.laz)")
    if not src:
        return
    out_dxf, _ = QFileDialog.getSaveFileName(win, "Save contour DXF", "", "DXF (*.dxf)")
    if not out_dxf:
        return
    try:
        from meridian.services.pointcloud_service import PointCloudService

        res = PointCloudService().classify_to_contours(Path(src), contour_dxf_path=Path(out_dxf))
        QMessageBox.information(
            win,
            f"Cloud processed: {Path(src).name}",
            f"Ground points: {res.ground_point_count:,}\n"
            f"Triangles: {res.surface.tin.triangle_count:,}\n"
            f"DXF: {out_dxf}",
        )
    except Exception as e:
        QMessageBox.critical(win, "Point-cloud pipeline failed", str(e))


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
