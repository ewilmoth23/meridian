"""Typer-based CLI for Meridian.

All four v0.1 vertical slices are exposed as subcommands so they can be
exercised end-to-end without a GUI:

    meridian deed parse INPUT.txt --out drawing.dxf --report report.pdf
    meridian network adjust NETWORK.json
    meridian traverse run RAWFILE --start 1000,2000 --method compass
    meridian cloud contours INPUT.las --out contours.dxf --interval 1.0
"""

from __future__ import annotations
