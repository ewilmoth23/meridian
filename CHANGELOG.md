# Changelog

All notable changes to Meridian land here. Format: [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).
Versioning: [SemVer](https://semver.org/).

## [0.1.0] — 2026-05-02

The foundation release. Hexagonal architecture, four end-to-end vertical
slices, and v1 implementations of the eight named differentiators on the
roadmap (Atlas, DeedLM, Pulse, Echo, Confluence, TruthChain, CoStake,
BIM bridge).

### Architecture

* Hexagonal layout under `src/meridian/`: `domain/` → `math/` →
  `pipelines/` → `ports/` → `adapters/` → `services/` → `api/` / `cli/`.
* One canonical data model: `Point2D`, `Point3D`, `LineSegment`, `Arc`,
  `Polygon`, `Parcel`, `Survey`, `SurveyProject`, `RawObservation`,
  `ControlNetwork`, `NetworkAdjustment`, `PointCloud`, `Surface`, `Contour`.
* One canonical persistence schema (SQLAlchemy 2.x + Alembic + SpatiaLite,
  swappable to PostGIS without code changes).
* Plugin discovery via Python entry points: `meridian.instruments`,
  `meridian.exporters`, `meridian.importers`, `meridian.jurisdictions`,
  `meridian.ai_providers`.

### Foundation slices

* **Slice 1 — Deed → polygon → DXF + PDF.** Regex tokeniser with full
  Texas-vara, rod/pole/perch, chain/link, and modern-feet support.
  ezdxf-based DXF writer (R2018) with proper layers/blocks/linetypes.
  ReportLab boundary report with closure summary and embedded plat SVG.
* **Slice 2 — RINEX → least-squares network adjustment.** Gauss-Newton
  in `scipy.linalg.cho_factor`, free / minimal / partial / full
  constraint modes, Jacobians for 5 observation kinds, 95% error
  ellipses, chi-square test, blunder detection.
* **Slice 3 — Total station → COGO traverse → closure.** Drivers for
  Leica GSI, Trimble JXL, TDS RW5 (Carlson), Sokkia SDR, Nikon RAW;
  RINEX (observation files) and NMEA 0183 readers. Compass / transit
  / least-squares adjustment.
* **Slice 4 — LAS/LAZ → classified ground → TIN → contours → DXF.**
  laspy streaming reader/writer; PDAL-pipeline helpers (SMRF/PMF
  ground classification, voxel thinning, IDW DEM); marching-triangles
  contour extractor.

### Atlas — integrated 3D globe (v0.5 in roadmap, v1 spike landed)

* `meridian.atlas.tile_service` — FastAPI app that streams the
  canonical Survey model to CesiumJS as GeoJSON and (for point clouds)
  range-served COPC.
* `meridian.atlas.cesium_client` — Python-side controller that hosts
  the viewer in a `QtWebEngineView` via `QWebChannel` (lazy-imported so
  the headless library loads without PySide6).
* CesiumJS HTML viewer in `src/meridian/atlas/static/index.html` —
  Apache 2.0, no key required for the runtime; demo-mode shows a
  sample parcel near downtown Austin when no project DB is attached.
* Optional Cesium ion + Google Photorealistic 3D Tiles passthrough.

### TruthChain — signed observation provenance

* Ed25519 keypair management (`cryptography`), per-surveyor PEM
  storage in OS-appropriate user-data dir, optional passphrase.
* Canonical, deterministic observation manifests with embedded surveyor
  identity and Ed25519 signatures.
* Merkle root over input manifests (CT/Bitcoin convention) recorded in
  a `AdjustmentChainAttestation` — replayable verification.
* QR-stamped PDF append page + verification URL embedded as PDF metadata.
* `meridian truthchain keygen` and `meridian truthchain verify` CLI.

### DeedLM — domain LLM scaffolding

* `meridian.ai.deedlm.corpus_builder` — assembles training corpora
  from text-deed directories + synthetic adversarial generation,
  deduplicates, splits train/val/test, and writes JSONL.
* `meridian.ai.deedlm.synthetic` — four jurisdictional dialects
  (Texas vara, NE rod-and-pole, PLSS aliquot, modern California).
* `meridian.ai.deedlm.finetune` — LoRA fine-tune driver for
  Mistral 7B / Llama 3.1 8B / Phi-3, with 4-bit quantisation.
* `meridian.ai.deedlm.inference` — `OllamaDeedLM` and `HFDeedLM`
  backends implementing `meridian.ports.ai.LLMClient`.

### Pulse — conversational AI co-pilot

* `meridian.ai.pulse.tools` — typed tool registry over the existing
  services: `parse_deed`, `run_traverse`, `classify_cloud`,
  `list_projects`, `inverse`, `forward`, `health`.
* `meridian.ai.pulse.server` — minimal MCP-compatible JSON-RPC dispatcher
  with stdio transport. Zero hard dependencies beyond stdlib.

### Echo — drone mission planner

* NOAA solar-position algorithm (Reda & Andreas) and acceptable-window
  search for ortho-grade flights.
* GCP planner with edge-vs-interior weighting, sized to a planimetric
  RMSE target.
* Boustrophedon mission generator with camera-profile-aware GSD,
  overlap, and altitude.

### Confluence — multi-source observation fusion

* `fuse(...)` extends `meridian.pipelines.network_adjust` with
  per-source σ-scaling priors.
* Source adapters: `lidar_ground_points_to_observations`,
  `photogrammetry_tie_points_to_observations`,
  `insar_motion_to_observations`.

### BIM bridge — IFC 4.3 round-trip

* Export survey parcels as `IfcAlignment` entities through
  `ifcopenshell` when available, with a hand-rolled STEP-Physical-File
  writer as fallback.
* Import via `ifcopenshell` (required for that direction).
* `reconcile_intent_vs_asbuilt` produces per-parcel deviation /
  Hausdorff-distance reports.

### CoStake — Google-Docs-style co-editing foundation

* `LWWMap` / `LWWRegister` for non-geometry fields (HLC + actor-id
  tiebreak).
* `GeometryCRDT` with RGA-style insert ordering — concurrent inserts
  at the same anchor converge deterministically across peers.
* `PresenceState` for live cursors / selections.
* `CoStakeRelay` — FastAPI WebSocket relay with hello / op / presence
  / snapshot protocol.

### v0.2 carry-overs landed early

* GeoJSON, KML/KMZ, Shapefile (fiona), GeoPackage (fiona) exporters +
  GeoJSON / Shapefile importers.
* LandXML 1.2 round-trip via lxml — replaces the prototype's
  regex-on-XML reader.

### Tooling

* `.claude/settings.json` with the 16 Makefile targets in the
  permission allowlist.
* `pyproject.toml` ruff config tuned for surveying-domain prose
  (degree symbols, σ/π/Δ/×/² in docstrings are not warnings).
* CI workflow: ruff + mypy + pytest matrix on Ubuntu/macOS/Windows ×
  Python 3.11/3.12.

### Tests

* **110 tests, all passing** under Python 3.11 + numpy 2.4 + scipy 1.17,
  in 1.4 s.
* Property-based + golden tests for COGO, adjustment, triangulation,
  contour extraction.
* Round-trip tests for GeoJSON, KML, LandXML.
* TruthChain end-to-end (keygen → sign → tamper → Merkle → verify).
* CRDT convergence under concurrent inserts and moves.
* Atlas tile-service smoke tests against `fastapi.testclient`.

### Reference doc trail

* `docs/architecture/ARCHITECTURE.md` — single source of truth for the
  hexagonal layout and the rules.
* `docs/roadmap/ROADMAP.md` — multi-phase plan v0.1 → v1.0 with a
  Differentiation Map at the top.

### Stats

* 137 Python files, ~14,000 lines of code (tests included).
* `ruff check src tests` — clean.
* `mypy` strict-mode unchecked in v0.1 (deferred to v0.2).

[0.1.0]: ./
