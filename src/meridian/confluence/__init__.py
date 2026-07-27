"""Confluence — multi-source observation fusion (v0.6).

A graph-based / extended-Kalman fusion engine that ingests heterogeneous
observations with per-source covariances. Extends
:mod:`meridian.pipelines.network_adjust` with:

* Total-station observations (already supported).
* GNSS vectors and absolute fixes (already supported).
* LiDAR-derived ground points with classifier-uncertainty as σ.
* InSAR ground-motion vectors.
* Photogrammetric tie points with bundle-adjustment covariance.
* AR-anchored field marks (when :mod:`meridian.anchor` lands in v0.9).

Status: planning stub for v0.6.

Components (to be implemented):

* ``observation_graph.py`` — generalised factor graph over heterogeneous
  observations.
* ``solvers/`` — Gauss-Newton (default), iterative reweighted LS,
  square-root information filter for very large networks.
* ``covariance/`` — per-source covariance estimators:
    - LiDAR: classifier-uncertainty propagation
    - Photogrammetry: bundle-adjustment posterior
    - InSAR: phase-noise + decorrelation model
* ``benchmarks/`` — golden-file tests against published NGS adjustments
  and synthetic mixed-source datasets.

Why this is a moat:
* Trimble / Leica / MicroSurvey adjust TS + GNSS together. None
  productize a fusion engine for the full sensor stack.
* Research literature (Tandfonline 2025 UAV multi-sensor; Springer
  J. Geodesy 2023 Kalman GNSS+InSAR) is mature enough to productize.
"""

from __future__ import annotations

from meridian.confluence.fusion import (
    FusionConfig,
    FusionInput,
    FusionResult,
    SourceWeight,
    fuse,
)

__all__ = ["FusionConfig", "FusionInput", "FusionResult", "SourceWeight", "fuse"]
