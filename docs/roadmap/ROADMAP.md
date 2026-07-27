# Meridian — Roadmap

A multi-phase plan from `v0.1` (foundation) to `v1.0` (production-ready professional surveying suite).

## Differentiation Map (the named features that set Meridian apart)

Each entry here is a *first-of-kind or rare-in-the-market* capability validated against a 2026 competitor scan (Carlson, Trimble, Leica, Topcon, Bentley iTwin, Autodesk, Esri, MicroSurvey, Bunting Labs, Pix4D, DroneDeploy, Hexagon, Propy).

| Codename | Phase | One-line claim | Status in the market |
|---|---|---|---|
| **Atlas** | v0.5 | Live two-way 3D globe over the canonical Survey model — no KML export ever | Only Bentley iTwin/Cesium does true round-trip; everyone else exports lossy KML. |
| **DeedLM** | v0.4 | Domain-specific transformer fine-tuned on US deed corpora; runs locally via Ollama | No published cadastral foundation model exists in 2026. Bunting Labs uses general LLMs. |
| **Pulse** | v0.4 | Conversational AI co-pilot over project DB / parser / retracement / compliance, via MCP tool servers | Civil 3D 2026 has "My Insights"; OpenSite+ has generative grading. No conversational survey assistant exists. |
| **Echo** | v0.6 | Drone mission planner that reasons about survey-grade outputs (GCP density, sun angle, atmosphere) | Pix4D / DJI / Wingtra plan flights; none reason about closure-grade outputs. |
| **Confluence** | v0.6 | Multi-source observation fusion (TS + GNSS + LiDAR + InSAR + photogrammetry tie points) with proper covariances | Trimble / Leica fuse TS + GNSS only. Heterogeneous fusion is research-rich, vendor-thin. |
| **TruthChain** | v0.7 | Cryptographically signed observation chain from instrument → adjustment → deliverable; embedded verification QR in PDF/DXF | No instrument vendor signs raw observation files. Galileo OSNMA (live since 24 July 2025) is the only signed civil GNSS today. |
| **CoStake** | v0.8 | Google-Docs-style real-time concurrent editing of survey data via geometry-aware CRDTs | Active research literature; zero shipping production tools. |
| **Anchor** | v0.9 | Open-source AR field stakeout that consumes any RTK rover and writes back into the canonical Survey | Already has shipping competitors (Pix4DCatch + viDoc, Lefixea LRTK). We claim "open + integrated", not "first". |
| **Survey ↔ BIM** | v0.7 | Round-trip with IFC 4.3 alignments — Meridian is the survey-of-record source, design-intent flows back as overlay | Existing tools push BIM → DT one way; nobody writes survey-authoritative changes back. |

Sequencing rationale: DeedLM + Pulse before Atlas because they multiply the value of every later phase; Atlas before drone/fusion because the visualization is the demo that closes deals; TruthChain before CoStake because provenance underpins multi-user trust.



## v0.1 — Foundation + 4 vertical slices  *(current)*

The smallest thing that proves the architecture works end-to-end. Four independent vertical slices, each exercising the full hexagonal stack (domain → math → pipeline → adapter → service → UI/CLI).

**Foundation deliverables:**
- [x] `pyproject.toml` with full dependency map and entry points.
- [x] Architecture document (`docs/architecture/ARCHITECTURE.md`).
- [ ] Canonical domain model: `Point`, `Parcel`, `Observation`, `Survey`, `CRS`, `PointCloud`.
- [ ] Math layer: COGO, least-squares, transforms, triangulation, statistics.
- [ ] Persistence layer: SQLAlchemy + Alembic + SpatiaLite.
- [ ] Plugin system: entry-point discovery, port validation.
- [ ] Background-job framework with progress events.
- [ ] FastAPI service layer.
- [ ] PySide6 desktop shell with dock-able panels and tab routing.
- [ ] Typer CLI with the four slice commands.
- [ ] CI: GitHub Actions running tests, ruff, mypy on push.

**Slice 1 — Deed → Polygon → DXF + PDF report**
Salvages the deed parser from the prototype, ports to the new domain model, exercises CAD and report adapters.

- [ ] `pipelines.deed_to_polygon` (regex + LLM fallback, no longer 4 parsers).
- [ ] `adapters.cad.dxf_writer` (ezdxf, R2018+, real layers/blocks).
- [ ] `adapters.reports.pdf_writer` (ReportLab boundary report).
- [ ] CLI: `meridian deed parse <path> --out drawing.dxf --report report.pdf`.
- [ ] Desktop: deed-import wizard, preview, export.
- [ ] Tests: 50+ property-based + golden-file.

**Slice 2 — RINEX GNSS → Network adjustment with covariance**
Replaces the prototype's broken pure-Python adjustment with `scipy.linalg`.

- [ ] `adapters.instruments.rinex` (RINEX 3.x observation + nav).
- [ ] `pipelines.network_adjust` (free, minimally constrained, fully constrained modes; iterative reweighted LS).
- [ ] `math.adjustment` (sparse normal equations, Cholesky factorization, error ellipses, chi-square, blunder detection).
- [ ] `adapters.reports.pdf_writer` adjustment report (residuals table, ellipse plots).
- [ ] CLI: `meridian network adjust <project>`.
- [ ] Tests: golden-file vs published NGS adjustment.

**Slice 3 — Total-station raw → COGO traverse → closure**
The slice the existing prototype completely lacks. Surveyor field-day workflow.

- [ ] `adapters.instruments.leica_gsi` (GSI-8/16 reader).
- [ ] `adapters.instruments.trimble_jxl` (Trimble JobXML).
- [ ] `adapters.instruments.tds_rw5` (TDS RW5 / Carlson).
- [ ] `pipelines.traverse_adjust` (atmospheric/curvature/refraction reduction, Compass/Crandall/least-squares adjustment).
- [ ] `adapters.reports.pdf_writer` traverse closure report.
- [ ] CLI: `meridian traverse import <file> && meridian traverse adjust <project>`.
- [ ] Tests: round-trip a recorded Leica + Trimble file.

**Slice 4 — LAS/LAZ → ground classification → TIN → contours → DXF/3D viewer**
Demonstrates the lidar-first capability.

- [ ] `adapters.pointcloud.las_io` (laspy 2.x, LAZ via lazrs).
- [ ] `adapters.pointcloud.pdal_pipeline` (PDAL JSON pipelines for filter/classify/output).
- [ ] `pipelines.pointcloud_classify` (SMRF/PMF ground filter via PDAL, breakline-aware TIN).
- [ ] `math.triangulation` (TIN from classified ground, contour extraction at user step).
- [ ] `meridian_desktop.widgets.viewer_3d` (PyVista, point-cloud visualization, classification toggling, TIN/contour overlay).
- [ ] CLI: `meridian cloud classify <las> --out classified.laz && meridian cloud contour <classified.laz> --interval 1ft --out contours.dxf`.
- [ ] Tests: PDAL pipeline reproducibility on a sample 1M-point dataset.

**Acceptance:** all four CLI commands work end-to-end on real sample data, the desktop GUI can run each slice, the test suite passes with 80%+ coverage.

---

## v0.2 — Core surveying breadth

Once the foundation is stable, fan out across the domain. Most of these can be ported from the prototype if rewritten against the new domain model.

- COGO calculator UI (inverse, traverse, intersections, area).
- Curve-table generator (DXF table entity, HTML, CSV).
- Closure-analysis report (multiple adjustment methods compared, DMD/DPD area).
- Coordinate-transform UI (drag-and-drop CRS picker; 40+ State Plane / UTM zones).
- Layer config / style presets for DXF (ALTA/NSPS, Civil 3D, NCS).
- Sheet layout (title block, scale bar, north arrow, legend, ANSI/ARCH/ISO sizes).
- Boundary evidence analyzer (port from prototype + numpy-based weighted averaging).
- PLSS parser (port from prototype, share `Point` / `Polygon` types).
- Title commitment parser.
- Deed comparison engine.
- Exception-tract / less-and-except parser.
- Chain-of-title visualization (Graphviz + interactive HTML).
- Multi-format import: SHP, GeoPackage, KML, GeoJSON, DXF read, GPX, WKT.
- Multi-format export: above plus LandXML round-trip.

## v0.3 — Geodetic & adjustment depth

- NADCON5 / HARN grid shifts (download manager + cache).
- GEOID18 vertical transforms.
- VDatum tidal datums.
- Constrained adjustment with weighted observations (different stddev per kind).
- Outlier detection with publishable test statistics (tau test, F test, Pope's test).
- Error ellipses on every adjusted point in DXF / PDF.
- StarNET file import/export for interop with the existing professional tool.

## v0.4 — Field workflow, RTK, and the AI co-pilot

- NTRIP client (BKG/UNAVCO/state caster directories).
- Live RTK feed display in the desktop app, with **Galileo OSNMA verification** when the receiver supports it (operational since 24 July 2025).
- Bluetooth/serial total-station live capture.
- Field-codes / feature-coded auto-CAD generation.
- "Field-to-finish" wizard: import raw → adjust → CAD ready in three clicks.
- **DeedLM** — a domain-specific transformer fine-tuned on US deed corpora (BLM/GLO + county-clerk public dumps + LoC historical + synthetic adversarial). Default fallback when the regex parser fails. Local-first via Ollama. **No published model of this kind exists in 2026** — direct moat against Bunting Labs.
- **Pulse** — a docked AI co-pilot panel exposing tool access to the project DB, deed parser, retracement engine, compliance engine, and field-note dictation, via MCP tool servers over the same services the desktop UI calls. Local Ollama default; OpenAI/Anthropic/Gemini optional.

## v0.5 — Atlas 3D globe + Lidar & photogrammetry

### Atlas — integrated 3D globe (the differentiator)

The market gap: outside Bentley's iTwin/Cesium ecosystem (which is enterprise-priced), no surveying tool ships a live, two-way 3D globe. Carlson, Trimble, Leica, Topcon, MicroSurvey all require a KML/KMZ export to show clients where a parcel sits on the planet. Esri has a globe but their COGO/deed parsing is weak. Atlas closes that gap for the working surveyor.

**Stack:**
- **CesiumJS** (Apache 2.0) embedded via **QtWebEngine + QWebChannel** in the desktop app — canonical 2026 pattern.
- **3D Tiles 1.1** (OGC Community Standard) for parcels, networks, and large LiDAR; track 2.0 from draft.
- **COPC** for single-site LiDAR (HTTP range-requests, no tiling step needed).
- **USGS 3DEP** for US terrain (1 m coverage ~80%+ of CONUS, free via AWS Open Data); self-hosted quantized-mesh.
- **Cesium ion** key as optional upgrade for Cesium World Terrain + Bing / Maxar imagery.
- **Google Photorealistic 3D Tiles** as optional layer (user supplies Maps Platform key — ToS forbid offline caching).
- **Local FastAPI tile service** that streams 3D Tiles / GeoJSON / COPC straight from the canonical Survey/Parcel/PointCloud types — no KML export step, no lossy intermediate format.
- Two-way binding: edit a call in the CAD view → globe re-tiles; click a parcel on the globe → CAD pans to it.

### Lidar & photogrammetry depth

- COPC read/write for streaming massive datasets.
- Entwine indexing for desktop streaming of 100M+ point datasets.
- Ground/non-ground classification UI with editable ROIs.
- Breakline definition and constrained Delaunay (Shewchuk's `triangle`).
- DEM / DTM / DSM raster generation (rasterio).
- Cut/fill volumetrics with average end area + composite methods.
- Cross-sections and profiles.
- Photogrammetry: OpenSfM / COLMAP wrapper; orthomosaic + DEM output.
- **3D Gaussian Splatting** as a *visualization* layer only — confirmed mid-2026 accuracy is 3–8 cm cloud-to-cloud, not survey-grade. We surface splats in Atlas; we do not source coordinates from them.

## v0.6 — Plat & subdivision + Echo (drone autonomy) + Confluence (sensor fusion)

### Plat & subdivision

- Subdivision plat ingest (lot/block/easement, road centerlines).
- Subdivision design tool: lot layout, frontage rules, setback validation.
- Easement analyzer (parallel offset, conflicts, encumbered area).
- Parcel fabric (topologically-shared edges; adjust one, all neighbors update).
- Tract index / title plant (FTS5 search, chain reconstruction).

### Echo — survey-aware drone mission planner

Pix4D Capture, DJI Pilot 2, and Wingtra Hub plan flights but do not reason about survey-grade outputs. Echo accepts a parcel boundary + accuracy target ("planimetric ±0.05 ft, vertical ±0.10 ft") and produces:

- A DJI / Wingtra / Skydio mission file with terrain following.
- A required-GCP placement plan based on the planimetric target.
- A "fly date" that meets sun-angle (avoid bare-earth shadow corruption) and atmospheric criteria.
- FAA LAANC airspace check.
- Overlap tuned for the post-processing pipeline (SfM dense, 3DGS, or hybrid).

### Confluence — multi-source observation fusion

Trimble Business Center and Leica Infinity adjust GNSS + total-station observations together; nobody productizes a fusion engine that ingests heterogeneous sources with proper covariances. Confluence is that engine, accepting:

- Total-station observations (TS).
- GNSS vectors and absolute fixes.
- LiDAR-derived ground points with per-point uncertainty from the classifier.
- InSAR ground-motion vectors (where applicable).
- Photogrammetric tie points with covariance from the bundle adjustment.
- AR-anchored field marks (when Anchor lands in v0.9).

Implemented as an extension to `meridian.pipelines.network_adjust` with a richer Jacobian and per-source weighting.

## v0.7 — Compliance, certification, deliverables + TruthChain + BIM round-trip

### Compliance, certification, deliverables

- Survey-certificate generator (ALTA/NSPS 2021 Table A items, 50-state statutory language).
- Regulatory compliance audit (jurisdiction-specific recording / plat / monumentation rules).
- Adverse-possession analyzer.
- Mineral-rights / water-rights / riparian-boundary engines.
- Eminent-domain / condemnation appraisal.
- Historical-deed digitization (era-aware OCR + handwriting model).
- FEMA NFHL flood-zone determination.

### TruthChain — signed observation provenance

No total-station or GNSS receiver vendor signs raw observation files at the device level today; no surveying software preserves a verifiable chain from instrument → adjustment → deliverable. TruthChain is that chain.

- At ingest, the instrument driver stamps a per-surveyor Ed25519 signature over the raw-observation manifest.
- The least-squares adjustment carries a Merkle root over its inputs and the algorithm version.
- For Galileo-OSNMA-equipped GNSS receivers, the original signed satellite messages are preserved alongside.
- The PDF report and DXF embed a verification QR / URL: any third party can replay the adjustment and confirm bit-for-bit.
- Insurance carriers and the litigation Bar are the natural first audience.

### Survey ↔ BIM round-trip via IFC 4.3

IFC 4.3 (2024) added alignment / infrastructure entities. Autodesk Tandem, Bentley iTwin, and Trimble Connect push BIM → DT but **do not** write surveyor-authoritative changes back. Meridian becomes the survey-of-record source and writes back into the IFC alignment; in the other direction, design-intent footprints from the architect overlay the parcel as an "intent" layer for as-built reconciliation.

## v0.8 — Multi-user, collaboration, and CoStake

- PostgreSQL/PostGIS backend with Alembic migrations.
- Real RBAC: project / parcel / call-level granular permissions.
- Audit log (immutable, hash-chained — pairs with TruthChain).
- Review workflow with multi-reviewer approval.
- Spatial annotations (pin / area / line / text).
- Activity feed and notifications.
- Optional cloud-sync (WebDAV/S3/SFTP/Nextcloud).

### CoStake — Google-Docs-style real-time co-editing

No production surveying / GIS / CAD tool ships true CRDT-based concurrent editing. The literature (ISPRS Archives XLVIII-4-W13-2025; MDPI IJGI 14(12) 468) is mature enough to productize. Two surveyors edit the same project; each sees the other's cursor, edits, and saves in <100 ms; conflict-free on calls, parcels, observations, and adjustments thanks to geometry-aware CRDTs (Yjs-based for the foundation, custom geometry-CRDTs for the boundary topology).

## v0.9 — Web, mobile, and Anchor (AR field stakeout)

- React + Vite web frontend reading the same FastAPI backend.
- Three.js 3D viewer for boundary + point cloud preview in browser.
- PWA for field crews (offline-capable, syncs when reconnected).
- Optional native mobile via Tauri or Flutter (deferred decision).

### Anchor — AR field stakeout

This space already has shipping competitors (Pix4DCatch + viDoc RTK rover, Lefixea LRTK on iPad, Trimble SiteVision). We don't claim "first" here; we claim **open and integrated**:

- Open-source ARKit reference implementation that consumes any RTK rover via NTRIP.
- Reads stake-out coordinates from the canonical Survey model — no separate "stakeout file."
- Writes recovered monument positions back into the same Survey, signed by TruthChain.
- Free for licensed Meridian users.

## v1.0 — Production polish

- Installer packages (Windows MSI / macOS DMG / Linux AppImage / Flatpak / Homebrew).
- Auto-updater (signed releases, SHA256 verification, channel-based).
- Sphinx + MkDocs published documentation.
- Plugin marketplace + signed plugins.
- Localization (English first; Spanish/French targeted).
- Telemetry (opt-in only, fully self-hosted).
- Stripe-based licensing if commercial; open-core model TBD.

---

## Non-goals (for now)

- DGN (Bentley) round-trip — wait until v1.x; ODA SDK is C-only.
- Native true-DWG (versus DXF) — wait for ODA bridge or `libredwg` maturity.
- BIM / IFC integration — defer to v1.x.
- ML-trained deed parsing — use LLM consensus for now; bespoke models are a v2 effort.
- Blockchain / "deed NFT" — speculative; not in plan.

## Carry-overs from the *Ultimate Deed Reader / Deed2DXF Pro v1.6.0* prototype

These prototype modules contain genuinely useful logic that will be **ported** (not copy-pasted) to Meridian once the domain model is in place. We rewrite each one against the canonical types and add property-based tests as we go.

| Prototype module | Lines | Status |
|---|---|---|
| `core/parser_regex.py` | 86 | Port to `pipelines.deed_to_polygon` (slice 1). |
| `core/ai_parser.py` | 1384 | Port to `pipelines.deed_to_polygon` LLM fallback (slice 1). |
| `core/cogo.py` | 1563 | Replace with `math.cogo` (numpy). Reuse test cases. |
| `core/closure_report.py` | 1394 | Port to `adapters.reports.pdf_writer.closure_report`. |
| `core/plat_vision.py` | 980 | Port to `adapters.ocr.ai_vision` (vision LLM). |
| `core/plss_parser.py` | 1542 | Port to `pipelines.plss_to_polygon` (v0.2). |
| `core/title_commitment.py` | 1799 | Port to `adapters.legal.title_commitment` (v0.2). |
| `core/deed_comparison.py` | 1776 | Port to `pipelines.deed_compare` (v0.2). |
| `core/control_network.py` | 1958 | Replace entirely with `pipelines.network_adjust` (slice 2). Pure-Python LS is unfit. |
| `core/parcel_fabric.py` | 2089 | Port to `pipelines.parcel_fabric` + persistence layer (v0.6). |
| `core/topo_3d.py` | 1305 | Replace with PDAL + `scipy.spatial` (slice 4). |
| `core/historical_ocr.py` | 1501 | Port to `adapters.ocr.historical` (v0.7). |
| `core/regulatory_compliance.py` | 1453 | Port to `adapters.compliance.*` (v0.7). |

The remaining 60+ modules are either (a) thin wrappers we don't need now, (b) duplicated logic that gets consolidated, or (c) deferred to later phases.
