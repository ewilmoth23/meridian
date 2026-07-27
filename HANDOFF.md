# Meridian — Claude Code Handoff

> **Owner:** Ethan Wilmoth — practicing licensed surveyor (NC).
> **Project state at handoff:** v0.1.0 — foundation released, 122 source files, ~14,000 LOC, 110 passing tests.
> **Codename:** Meridian. Tagline: *Where every line is true.*
> **Goal:** One software that replaces AutoCAD Civil 3D + Trimble Business Center + Hypack + Carlson Survey + a deed-parser + a 3D globe — for the office surveyor, on the East Coast and Gulf states first, with everything running local-and-self-hosted.

---

## 0. How to read this document

You — the Claude Code agent reading this — are taking over an existing, well-architected Python project. Do **not** rewrite it. Extend it. The hexagonal architecture (`docs/architecture/ARCHITECTURE.md`) and the multi-phase roadmap (`docs/roadmap/ROADMAP.md`) are correct and canonical; this handoff layers in **decisions the owner has now made** that supersede or refine the v0.1 docs.

Read order:

1. This document (decisions + scope).
2. `MERIDIAN_DREDGE_PLAN.md` (the **separate** UE5 + Cesium-for-Unreal dredging product that consumes Meridian's project model — read it for context, but Claude Code does **not** build it as part of Meridian core).
3. `README.md` (one-page elevator pitch).
4. `docs/architecture/ARCHITECTURE.md` (the rules).
5. `docs/roadmap/ROADMAP.md` (the long plan).
6. `CHANGELOG.md` (what v0.1 actually shipped).

When this document and the older docs disagree, **this document wins** and the older doc gets updated to match.

---

## 1. The vision in one paragraph

Meridian is the modern surveyor's office suite. A licensed surveyor opens a single program, drops in raw field files (total-station raw data, GNSS RINEX, lidar LAS/LAZ, sonar XTF/HSX/.kmall, drone imagery), and works through their entire deliverable workflow — adjustment, classification, surface generation, deed reconciliation, retracement, plat preparation, sealed PDF, DXF/LandXML/Shapefile/GeoPackage handoff — inside a single, fast, local web UI built around a live 3D globe. No KML export step. No "open this in AutoCAD." No "process this in Hypack first." One canonical data model. One UI. One deliverables pipeline.

---

## 2. Owner decisions (THE NEW BASELINE)

These are the decisions the owner made at handoff time. They lock in what was previously TBD in the roadmap.

### 2.1 UI — web SPA on a local FastAPI backend

- **The UI runs in a browser**, not as a native PySide6 application.
- It is served by a **FastAPI backend that runs locally on the surveyor's machine** (`uvicorn` on `127.0.0.1`). Heavy compute (numpy/scipy/PDAL/pyproj/least-squares/laspy) stays in Python, in-process — there is no web tax for compute.
- The existing `src/meridian/atlas/static/index.html` (7,162 lines, CesiumJS, dark "futuristic floating-window" theme, drawing/measuring/CoGo/traverse/volume tools already wired) **is** the UI shell. Build everything else around it.
- The existing PySide6 desktop shell (`src/meridian_desktop/app.py`) is demoted to "launcher / single-user installer wrapper" and ultimately replaced by a **Tauri** desktop wrapper (Rust, ~10 MB) that boots the local FastAPI server, opens a windowed Chromium view of `http://127.0.0.1:<port>/atlas/`, and gives the user a native app icon. **Do not invest in PySide6 widgets.** Anything currently in `meridian_desktop/widgets/` (none yet) or `meridian_desktop/windows/` (none yet) should be ported to web components instead.
- Distribution end state: an installable native app (Windows MSI, macOS DMG, Linux AppImage) that is just the Tauri shell + a bundled Python runtime + the Meridian package + Cesium static assets. No external Python install required for end users.

**Rationale (for the record):** CesiumJS is the best 3D globe and runs only in a browser. The existing 7k-line viewer is a serious investment that already matches Glassbox-style UX. Civil 3D / TBC are native because they predate browser 3D, not because native is right today. Web UI gives us cross-platform, single-codebase, embeddable-in-clients-without-install, and zero pain integrating with Cesium / Three.js / Mapbox / Deck.gl. We pay nothing for it because heavy compute stays in Python.

### 2.2 Office software for v1.0 — file-in, file-out (vessel-resident comes after)

- For v1.0, Meridian is **office software**. It does not connect to live total stations, live GNSS rovers, NTRIP casters, or Bluetooth devices.
- All field hardware is reached via the **files exported from the field** (Leica GSI, Trimble JXL/JOB, Sokkia SDR, TDS RW5, Nikon RAW, RINEX `.obs`/`.nav`, LAS/LAZ, XTF, HSX, .all/.kmall, .s7k, JSF, NMEA logs).
- **Drop** the `field` extras group (`pyserial`, `pynmea2` *as a hardware driver*) from `pyproject.toml`. Keep `pynmea2` only as a *file-format* parser if useful.
- **Drop** anything in the v1.0 roadmap that talks about "live RTK," "live total-station capture," "Bluetooth," "field crews," "AR field stakeout (Anchor)" *as runtime requirements for v1.0*. They come back in **Phase J (post-v1.0, vessel-resident Meridian)** described in Section 4 — Meridian *will* eventually replace Hypack on the survey boat and DREDGEPACK on the dredge bridge, but that's a separate scope expansion that ships once the office product has paying customers funding it.
- Drone work is **mission planning + imagery ingest**: we generate flight plans (Echo) that the user uploads to DJI/Wingtra/Skydio software, and we ingest the resulting imagery + tie points + camera trajectories into the same pipelines.

### 2.3 Hydrographic processing is a v1 first-class capability

This is the largest scope addition over the v0.1 roadmap. **Meridian processes hydrographic data**. Collection (real-time sonar logging) is out. Processing is in, all of it:

- **Single-beam echosounder** — XYZ + tide CSV ingest, tide correction (NOAA tide gauges via local cache file or user-supplied), sound-velocity correction, gross-error filter, surface generation (TIN / IDW / Kriging), contour at user-defined intervals, DXF/LandXML/CSV export.
- **Multibeam** — XTF, Hypack HSX, Kongsberg `.all`/`.kmall`, Reson `.s7k` parsers; sound-velocity correction (CTD/SVP profile import); patch test (roll/pitch/yaw/timing); TPU calculation; CUBE / CUBE+ surface generation (we wrap MB-System or implement the published algorithms — pick at implementation time); BAG (Bathymetric Attributed Grid) export; dynamic / static draft handling.
- **Side-scan sonar** — XTF / JSF read, slant-range correction, mosaic generation, target picking, target-list export.
- **Nautical-chart deliverables** — S-57 ENC export, BAG export, NOAA-compliant deliverable bundles. Required for clients who are NOAA / USACE / port authorities / state coastal agencies.

This becomes a new top-level package: `src/meridian/hydro/` (parallel to `src/meridian/atlas/`), with corresponding `adapters/sonar/`, `pipelines/hydro_*`, and a `Hydro` workspace tab in the UI.

### 2.4 Jurisdictional coverage — East Coast + Gulf, Maine to Mexico

Phase-1 first-class jurisdictions (deed dialect, certificate template, monumentation rules, filing format, vertical/horizontal datum defaults, sample data):

```
ME, NH, MA, RI, CT, NY, NJ, DE, MD, DC, VA, NC, SC, GA, FL, AL, MS, LA, TX
```

That is **19 jurisdictions** including DC. Texas is partially covered already (vara unit, Spanish/Mexican land grants).

After v1.0 ships: PLSS Midwest / Mountain / West, then California / Pacific. The DeedLM corpus already has scaffolding for PLSS aliquot dialect — keep it but it's not first-class until v1.1+.

Each first-class jurisdiction needs:
- A jurisdiction module under `src/meridian/jurisdictions/<state>.py` (`survey_certificate.py` already exists as a generic — split per-state).
- A test fixture deed for each state under `data/samples/deeds/<state>/`.
- A certificate template (PDF) under `src/meridian/adapters/reports/templates/<state>/`.
- An entry in `meridian.jurisdictions` entry-points.

### 2.5 AI — local-first Ollama, cloud LLMs optional

- **Default**: Local Ollama. The `DeedLM` fine-tune (Mistral 7B / Llama 3.1 8B / Phi-3 with LoRA, already scaffolded in `src/meridian/ai/deedlm/`) ships as the canonical deed-parsing model. `Pulse` (the conversational MCP co-pilot, already scaffolded in `src/meridian/ai/pulse/`) talks to local Ollama by default.
- **Optional**: OpenAI / Anthropic / Gemini behind a runtime user setting. Never required. Never the default. Keys are user-supplied at first use. Document in the user guide.
- **No telemetry.** No usage tracking. No "phone home." Ever.

### 2.6 Cloud / paid services — Cesium ion free tier; everything else on-prem

- **Cesium ion free tier** is the default world terrain + base imagery provider. Free up to 5 GB / month. Each end user gets their own ion account; the app prompts them to paste a token on first run, or runs against USGS 3DEP terrain only if they decline.
- **Google Photorealistic 3D Tiles** stays as an *optional* layer (already wired in code). Off by default. The user supplies a Maps Platform key when they want it.
- **No other cloud.** No AWS/GCP/Azure deployment, no Anthropic/OpenAI API keys baked in, no S3 buckets, no Postgres-as-a-service.
- **Local data sources** that we ship cached: USGS 3DEP terrain index (CONUS), NOAA tide-station catalog, NOAA charted soundings index, NOAA bathymetry archive index, FEMA NFHL flood-zone index, NGS control-point database snapshot.

### 2.7 Multi-user collaboration — defer to v0.8

- v1.0 of the product ships **single-user**. One PLS owns one project at a time on one machine.
- The CoStake CRDT scaffolding (`src/meridian/costake/`, already in v0.1) **stays in the codebase** but is not enabled in the shipping product until v0.8.
- v0.8 turns it on along with PostgreSQL/PostGIS migration support, RBAC, audit log. Plan stays as in `docs/roadmap/ROADMAP.md`.

### 2.8 What's getting cut from the v0.1 roadmap

- "Live RTK / NTRIP / OSNMA verification at runtime" — gone. We *parse* RINEX with OSNMA-aware logic if the file has signed messages, but we don't run a live NTRIP client.
- "Bluetooth/serial total-station live capture" — gone.
- "AR field stakeout (Anchor)" as a v0.9 deliverable of the desktop product — moved to a separate future companion mobile app, not part of the office suite.
- Anything in the v0.1 roadmap referenced as "field hardware" / "live capture" — drop.
- "Native PySide6 GUI" — replaced by web SPA + Tauri shell. The PySide6 work in v0.1 is fine as it is (a launcher button) and stays as a developer convenience.

### 2.9 What's getting added that wasn't in the v0.1 roadmap

- **Hydrographic processing** as a top-level package and v0.6 phase (replacing the lighter "drone autonomy + sensor fusion" headline of v0.6).
- **Tauri desktop shell** replacing PySide6 — new v0.9 deliverable.
- **State-by-state jurisdictional rollout** for 19 East Coast / Gulf states — new through-line across v0.4 → v1.0.
- **Hypack-and-DREDGEPACK office-equivalent feature parity** as a marketing claim — call out explicitly in `README.md`. The headline target is *replace Hypack's office side, 10,000× more modern UI, then replace the vessel side after v1.0*.
- **Design-surface-vs-survey visualization** added inside Phase E (hydro). See Section 2.10.
- **GPU acceleration** as a v0.5+ requirement for real-time-ish multibeam processing, side-scan mosaics, and large lidar. CuPy as the numpy-compatible CUDA layer; PyTorch only if/when ML lands (target detection, classification). See Section 2.11.
- **S-100 series first, S-57 as legacy compatibility** in Phase E. NOAA migration is well underway by 2026; new deliverables go out as S-101 (ENC), S-102 (bathy grid), S-104 (water levels), S-111 (currents). S-57 stays for legacy clients. See Section 2.12.
- **Acoustic seabed classification from multibeam backscatter** in Phase E — turns the depth survey into a bottom-type map, both as a deliverable and as input to Meridian Dredge's soil model.
- **Side-scan automated target detection** in Phase E — CNN-based target picker trained on USACE/NOAA target libraries.
- **Full vertical-datum coverage** — MLLW, MHW, NAVD88, MSL, chart datum, and conversions. GEOID18 + VDatum already in scope; expand to make all of these first-class.
- **Raw-data archival workflow** in Phase E — Project / Line / Day / Vessel archival mirroring Hypack conventions, so a surveyor can drag a `.HSX` from any year onto Meridian and have it open with full provenance.
- **Fleet / Operation aggregate** — new domain type added in Phase E so a multi-vessel dredge or survey spread can be modelled as one unit. Used by Meridian Dredge.
- **NOAA CO-OPS real-time water-level + current ingest** — pulled straight from the public API for tide reduction and live monitoring during hydro processing.
- **Future Phase J — vessel-resident Meridian (post-v1.0)** — eventual Hypack replacement on the survey boat and DREDGEPACK replacement on the dredge bridge. See Section 4 Phase J.

### 2.10 Design-surface-vs-survey (the dredge / construction door-opener)

A small but high-leverage feature added to Meridian core's Phase E. Imports a design template (Hypack `.tin`, AutoCAD corridor, LandXML alignment + cross-sections, IFC channel) and renders it on the existing Atlas globe against the latest bathymetry / lidar surface. Outputs:

- A difference-surface raster showing high-spots / low-spots vs. design.
- A 3D mesh of the design template draped over the seabed / ground, with cut/fill volumetrics.
- A section-cut tool extending the existing `terrain profile` widget in `index.html` to handle design overlays.
- A simple "% complete by volume" metric against a reference pre-construction survey.

This is **Layer 1** of a planned but separate product, **Meridian Dredge** — see the companion document `MERIDIAN_DREDGE_PLAN.md` for the full plan and the larger UE5 + Cesium-for-Unreal program. Inside Meridian core, this single feature is what opens the door at dredge contractors and civil engineering firms. **No Unreal Engine in Meridian core** — the heavyweight simulation product is a separate executable that consumes Meridian's project files.

Architectural impact on Meridian core: nothing structural. Adds a `meridian.adapters.cad.design_surface` module + `meridian.pipelines.surface_diff` + a small UI tab. Stays in browser. Stays in Phase E.

### 2.11 GPU acceleration commitment

CPU-only numpy/scipy is fine for the four v0.1 slices but becomes the bottleneck the moment the user opens a 100M+-point lidar tile, a multibeam swath at native resolution, or a side-scan mosaic at survey scale. Phase D commits Meridian to a **pluggable GPU path**:

- **CuPy** as the drop-in numpy replacement for CUDA. Code paths stay numpy-shaped; CuPy resolves at runtime when a GPU is available.
- **Rapids cuDF** for large-table operations.
- **PyTorch** only when ML lands (target detection, seabed classification, deed extraction at scale).
- **Pluggable** — when no GPU is available, fall back to numpy/scipy/PDAL on CPU. No hard dependency.
- Detection at startup; a UI indicator showing whether GPU is engaged for the active workflow.

GPU acceleration is *not* a requirement for v0.2 / v0.3 / v0.4 — those phases stay CPU. It becomes mandatory for v0.5 (Atlas hardening with 100M+ point clouds) and Phase E (real-time-ish hydro processing).

### 2.12 S-100 series first, S-57 as legacy

NOAA's hydrographic-deliverable migration to the IHO S-100 standard is well into deployment by 2026. New deliverables to NOAA, NOAA contractors, and the international charting community go out as **S-101 ENC** (replaces S-57), **S-102 bathymetric grid**, **S-104 water-level information**, **S-111 surface currents**. S-57 ENC stays in scope for legacy clients but is no longer the headline. The hydro adapter package gains an `s100/` submodule alongside `s57.py`.

### 2.13 Real-time event-streaming substrate — design now, build later

The current architecture is batch / pipeline-oriented. That's correct for v0.2 → v0.7. But Phase E (live water-level / tide ingest, AIS-aware hydrographic survey planning, dredge-spread coordination) and Phase J (vessel-resident Meridian) both need an *event-streaming* substrate where sensors and external feeds publish events to a bus and pipelines subscribe. The architecture document acknowledges this addition explicitly so we don't paint ourselves into a corner; actual implementation is deferred to whichever phase first needs it.

Substrate choice: **Redis Streams** (embeddable, single-binary, no operations burden) for the single-machine office product; **NATS JetStream** as the upgrade path for multi-machine fleet ops centers in v1.x+. Domain types stay shared between batch and streaming; the streaming layer is `meridian.realtime.*` with adapters that publish to and subscribe from the bus.

---

## 3. Architecture (unchanged from v0.1, summarized for orientation)

```
┌──────────────────────────────────────────────────────────────────┐
│   Tauri shell (Rust, ~10 MB) — user double-clicks the app icon  │  ← v0.9
│   - Spawns local FastAPI server on 127.0.0.1                     │
│   - Opens windowed Chromium view of /atlas/                      │
└──────────────────────────────────┬───────────────────────────────┘
                                   │
┌──────────────────────────────────▼───────────────────────────────┐
│   Web SPA — src/meridian/atlas/static/index.html (CesiumJS)      │  ← exists today
│   + per-workflow web components (deed, traverse, network,        │
│     pointcloud, hydro, plat, retracement, deliverables)          │
└──────────────────────────────────┬───────────────────────────────┘
                                   │ HTTP / WebSocket (localhost)
┌──────────────────────────────────▼───────────────────────────────┐
│   meridian.api  (FastAPI, async) ── src/meridian/api/             │
└──────────────────────────────────┬───────────────────────────────┘
                                   │
┌──────────────────────────────────▼───────────────────────────────┐
│   meridian.services (use-cases) ── src/meridian/services/         │
│   ── meridian.pipelines (workflows) ── src/meridian/pipelines/    │
└──────────────────────────────────┬───────────────────────────────┘
                                   │
┌─────────────────┬────────────────┴────────────────┬──────────────┐
│ meridian.ports  │ meridian.math (numpy/scipy)     │ meridian.    │
│ (interfaces)    │ ── src/meridian/math/           │ plugins      │
└─────────────────┴─────────────────┬───────────────┴──────────────┘
                                    │
                ┌───────────────────▼────────────────────┐
                │ meridian.domain (pure entities, no I/O) │
                └─────────────────────────────────────────┘
                                    │
┌───────────────────────────────────▼─────────────────────────────┐
│ meridian.adapters/ — instruments, cad, gis, pointcloud, sonar,  │
│   reports, ocr, persistence (SQLAlchemy + Alembic + SpatiaLite) │
└─────────────────────────────────────────────────────────────────┘
```

**The dependency rule still holds:** `domain` knows nothing. `adapters` know `domain`/`math`/`ports`. `services` orchestrate. UI talks through `api`. Anything new added by Claude Code follows this rule or it doesn't get merged.

---

## 4. Phased build plan

The v0.1 roadmap (`docs/roadmap/ROADMAP.md`) gave us 9 versions (v0.1 → v1.0). Here is the **adjusted plan** with the decisions above folded in. Each phase has an acceptance test the owner will run before signing off.

### Phase A — v0.2: Polish v0.1, finish the four slices, web UI replaces the PySide6 buttons
**Why first:** the foundation is there but the web UI doesn't yet expose the four slices end-to-end. Make the existing slices demo-able through the browser.

- [ ] Wire each of the four v0.1 slices into a workflow tab in `atlas/static/index.html`:
  - "Deed → DXF" — paste deed text or upload `.txt`/`.docx`/`.pdf`, see polygon on the globe, export DXF + PDF.
  - "Network adjust" — upload RINEX `.obs`/`.nav`, configure constraints, run, see error ellipses on the globe + PDF report.
  - "Total-station traverse" — upload `.gsi`/`.jxl`/`.rw5`/`.sdr`/`.raw`, run COGO + closure, see traverse on globe + PDF closure report.
  - "Cloud → contours" — upload `.las`/`.laz`, classify, build TIN, generate contours, export DXF.
- [ ] Each tab is a Lit / Vue / Svelte / vanilla-JS web component (pick **vanilla JS + small reusable helpers** unless we already have build tooling — keep the dependency surface tiny and let the existing `index.html` style win).
- [ ] All four workflows complete in <30 s on the canonical sample inputs in `data/samples/`.
- [ ] CLI commands continue to work unchanged.
- [ ] Test coverage stays ≥80% overall, ≥95% in `domain` and `math`.

**Acceptance:** open the browser, click each of the four tabs, run each workflow on the sample data shipped in `data/samples/`, the output files appear in a chosen output folder.

### Phase B — v0.3: Core surveying breadth (mostly porting from the prototype)
**Why next:** widen the surveying capability to cover what a typical East-Coast / Gulf boundary surveyor does day-to-day.

Carry the v0.1-roadmap v0.2 list across (already detailed in `docs/roadmap/ROADMAP.md` section "v0.2 — Core surveying breadth"). All apply, **except** "field-codes / feature-coded auto-CAD" stays the way it is (file-based, no live capture).

Add:
- [ ] DXF style presets for **NCS** and **state-specific** (NC, FL, TX) layer templates.
- [ ] PLSS parser stays in scope but stays not first-class.
- [ ] Sheet layout supports ANSI A→D and ARCH C→E paper sizes natively.

**Acceptance:** a real boundary survey project (deed text + a few traverse legs + control network) runs end-to-end through the web UI and produces sealed PDF + DXF + LandXML + Shapefile + GeoPackage + GeoJSON + KML simultaneously. All outputs round-trip back through the importers without coordinate drift.

### Phase C — v0.4: Geodetic & adjustment depth + first-class jurisdictions
**Why next:** the East-Coast / Gulf jurisdictions need their state-specific deeds, certificates, datums, and grid shifts to actually be deliverables.

- [ ] NADCON5 / HARN grid shifts with on-disk grid cache (downloader + checksum).
- [ ] GEOID18, GEOID12B; VDatum tidal datums for coastal work (this is hydrographic prerequisite too).
- [ ] StarNET file import / export.
- [ ] Constrained adjustment with weighted observations (kind-specific σ).
- [ ] Outlier detection with publishable test statistics (tau, F, Pope's).
- [ ] DeedLM corpus + fine-tune driver runs on the 19 state corpus (`src/meridian/ai/deedlm/corpus_builder.py` already scaffolded — extend the synthetic generator with NC / coastal / Gulf dialects).
- [ ] Per-state `jurisdictions/<state>.py` for **all 19 states**, each with the certificate template, statutory language, monumentation defaults, vertical/horizontal datum defaults, deed dialect grammar.
- [ ] Per-state sample deeds in `data/samples/deeds/<state>/`.
- [ ] Pulse co-pilot is functional inside the web UI as a docked side panel.

**Acceptance:** load a representative deed from each of the 19 states, run it through DeedLM (when regex falls back), get a polygon, get a sealed PDF certificate that uses **that state's** statutory language with **that state's** PE/PLS seal block.

### Phase D — v0.5: Atlas hardening + Lidar/photogrammetry depth + Civil 3D parity workflows
**Why next:** the globe and the lidar pipeline are the visual differentiators. They have to be solid.

- [ ] Atlas: COPC streaming for >100M point clouds, Entwine indexing as fallback.
- [ ] Atlas: 3D Tiles 1.1 export of every `Survey` / `Parcel` / `Network` / `PointCloud`.
- [ ] Atlas: full edit/redo/undo on parcels with CRDT-backed local op log (CoStake plumbing — not networked yet).
- [ ] Atlas: imagery layer manager with WMS/XYZ/MapTiler/USGS imagery sources.
- [ ] Lidar: ground/non-ground classification UI with editable ROIs.
- [ ] Lidar: breakline definition + constrained Delaunay (Shewchuk's `triangle`).
- [ ] DEM/DTM/DSM raster generation via `rasterio`.
- [ ] Cut/fill volumetrics (avg-end-area + composite + grid).
- [ ] Cross-sections + profiles tool.
- [ ] Photogrammetry wrapper around OpenSfM or COLMAP. Orthomosaic + DEM output.
- [ ] **Civil 3D parity workflows** (compete with C3D Survey + Surface + Profile workspaces): alignment / corridor design at a basic level, surface comparison, surface volume, daylighting.

**Acceptance:** run a 100M-point lidar survey end-to-end (classify → ground → TIN → contours → DXF + 3D Tiles in the globe), under one minute on a recent workstation. Open a Civil 3D LandXML alignment from a real client project, edit it, write it back; C3D opens it without complaint.

### Phase E — v0.6: Hydrographic processing (Hypack parity) + Echo + Confluence
**This is the new headline phase.** The "one software for everything" claim depends on this landing well.

Hydrographic processing — see Section 2.3. Concretely:

- [ ] `src/meridian/hydro/` package:
  - `tide.py` — NOAA tide-station ingest, harmonic prediction, observed-tide ingest, applied-tide correction.
  - `svp.py` — sound-velocity profile ingest (CTD, MVP), refraction.
  - `patch_test.py` — roll/pitch/yaw/timing patch-test wizard with paired-line reciprocal analysis.
  - `tpu.py` — total propagated uncertainty (Hare's model).
  - `cube.py` — CUBE / CUBE+ surface generation (wrap MB-System if it's installed; otherwise implement from the published Calder & Mayer 2003 + Calder 2017 papers).
  - `mosaic.py` — side-scan slant-range correction + georeferenced mosaic (`rasterio`).
  - `target_picker.py` — UI-driven side-scan target identification with bookmark export.
- [ ] `src/meridian/adapters/sonar/` package:
  - `xtf.py` — XTF read/write.
  - `hsx.py` — Hypack HSX read.
  - `kongsberg.py` — `.all` and `.kmall` read.
  - `reson.py` — `.s7k` read.
  - `jsf.py` — Edgetech JSF read.
  - `s100/` submodule — **S-101 ENC**, **S-102 bathy**, **S-104 water levels**, **S-111 currents** (the IHO S-100 series).
  - `s57.py` — legacy IHO S-57 ENC read/write (`fiona` has S-57 driver via OGR).
  - `bag.py` — BAG (Bathymetric Attributed Grid) read/write (`gdal`/`hdf5`).
- [ ] `src/meridian/adapters/external/` (new package — read-only public-data adapters):
  - `noaa_coops.py` — NOAA CO-OPS API for real-time water levels, predicted tide, currents.
  - `noaa_ndbc.py` — NDBC buoy real-time wind/wave/temp readings.
  - `noaa_marine_forecast.py` — NWS marine forecast.
  - `usace_gauges.py` — USACE inland water-level / lock-and-dam stations.
- [ ] **Acoustic seabed classification** (`pipelines/seabed_classify.py`) — multibeam backscatter → bottom-type map, both as a Meridian deliverable and as input to Meridian Dredge's soil model.
- [ ] **Side-scan automated target detection** — CNN-based picker trained on USACE/NOAA target libraries; deferred to Phase F if no GPU available in Phase E.
- [ ] **Full vertical-datum coverage**: GEOID18, VDatum, MLLW, MHW, NAVD88, MSL, chart datum, and the conversions between them. Surveyors will judge us on getting these right.
- [ ] **Raw-data archival workflow** — `Project / Line / Day / Vessel` archival mirroring Hypack conventions; full provenance from raw `.HSX` / `.kmall` / `.xtf` to deliverable, replayable end-to-end.
- [ ] **Heave-tide reduction in addition to GPS-tide** — both reduction methods supported. Inland and shallow-water work uses observed-tide + heave; offshore uses RTK + ellipsoidal + geoid.
- [ ] **Fleet / Operation aggregate** — new `Fleet` domain type so a multi-vessel dredge or survey spread can be modeled as one unit. Used by Meridian Dredge.
- [ ] `src/meridian/pipelines/`:
  - `singlebeam_to_surface.py`
  - `multibeam_to_surface.py`
  - `sidescan_to_mosaic.py`
- [ ] Hydro workspace tab in `atlas/static/index.html` — full hydrographic processing in the same UI as boundary work.
- [ ] **Design-surface-vs-survey** (Section 2.10): adapter `meridian.adapters.cad.design_surface` for Hypack `.tin` / LandXML alignment + cross-sections / AutoCAD corridor / IFC channel; pipeline `meridian.pipelines.surface_diff` for difference-surface generation; UI tab for design overlay + cut/fill + section cut + % complete. The door-opener for the dredge / construction segment.
- [ ] Acceptance test: ingest a real multibeam survey (`.kmall` from a Kongsberg EM2040), run patch test, build CUBE surface, export S-57 ENC and BAG. Compare to the same dataset processed in CARIS / Qimera / Hypack — coordinate differences within stated TPU.

Echo (drone planner) — already scaffolded; finish UI integration for mission upload to DJI Pilot 2 / Wingtra Hub formats.

Confluence (sensor fusion) — already scaffolded; finalize Jacobians + per-source σ priors for TS + GNSS + lidar + photogrammetry + InSAR. Add a fusion-aware report.

**Acceptance:** ingest a real multibeam dataset, a real lidar dataset, a real total-station + GNSS network for the same project, fuse all three through `meridian.pipelines.network_adjust` + `meridian.confluence.fusion` + `meridian.hydro.cube.surface`, get a single coherent surface and a sealed deliverable.

### Phase F — v0.7: Compliance, certification, deliverables + TruthChain + BIM round-trip + Plat & subdivision
**Why next:** the "I am the surveyor of record" claim has to be cryptographic.

- All v0.1-roadmap v0.7 items apply unchanged.
- Plat & subdivision tools (lot/block, easement, parcel fabric topology) move here from the v0.6 list.
- TruthChain already has v1 in `src/meridian/truthchain/`. Integrate it into every output (PDF metadata, DXF, S-57, BAG).
- IFC 4.3 round-trip already has v1 in `src/meridian/bim_bridge/`. Harden it.

**Acceptance:** publish a sealed PDF certificate with a verification QR code. A reviewer scans the QR, downloads the manifest, and the Merkle proof verifies bit-for-bit against the underlying observations. The same project's IFC export opens cleanly in Revit and Bentley OpenSite without coordinate drift.

### Phase G — v0.8: Multi-user, PostgreSQL, CoStake live
- All v0.1-roadmap v0.8 items apply unchanged.
- CoStake CRDT scaffolding (already in `src/meridian/costake/`) goes live with WebSocket relay.
- Database swappable from SpatiaLite (default, single-user) to PostGIS (multi-user) via Alembic + the existing repository ports.

**Acceptance:** two surveyors on different machines edit the same project simultaneously and converge.

### Phase H — v0.9: Tauri shell + native distribution + web/cloud frontend (no SaaS)
- Tauri wrapper bundles Python + Meridian + Cesium static assets into Windows MSI / macOS DMG / Linux AppImage.
- Auto-updater (signed releases, SHA256, channel-based).
- Optional standalone web frontend at `meridian.run` (or wherever) that the office user *self-hosts* and crews / clients hit over LAN/VPN. **No multi-tenant SaaS.**

**Acceptance:** double-click the installer, get a working app icon, launch it, see the app, no Python install required, auto-updates work.

### Phase I — v1.0: Production polish
- Sphinx + MkDocs documentation site, published to a static host.
- 50-state coverage in jurisdictions (PLSS midwest/west, California, Pacific) on top of the East-Coast/Gulf foundation.
- Plugin marketplace + signed third-party plugins.
- Localization (English / Spanish for Texas / Spanish for the Gulf).
- Optional opt-in self-hosted telemetry for crash reports.

**Acceptance:** licensed surveyors install Meridian, complete a real project end-to-end without a single CSR ticket, and the deliverables are accepted by the relevant county recorder, NOAA, USACE, or DOT.

### Phase J — v1.x: Vessel-resident Meridian (post-v1.0; the actual Hypack replacement on the boat)
**Why this exists:** the v1.0 product replaces Hypack's *office* side. Hypack's other half lives on the survey boat and the dredge bridge. v1.x is where Meridian eats that too. **This is its own phase, gated on v1.0 paying customers funding the work** — do not start until office product has revenue.

What ships in Phase J:

- [ ] **Real-time multibeam acquisition** — UDP/TCP streams from Kongsberg/Reson/R2Sonic/Norbit/Teledyne. Time-disciplined to PPS from a GNSS clock. Sub-millisecond time-tagging across positioning + motion + heading + sound velocity + multibeam. The replacement for Hypack's vessel side.
- [ ] **Sub-millisecond time synchronization** — `meridian.realtime.timesync` discipline against GPS PPS; required for survey-grade results.
- [ ] **Helmsman / coxswain UI** — the real-time line-running display: planned line, vessel position, cross-track error, depth profile, turn warning, line list. What the surveyor on the boat actually drives by.
- [ ] **Dredge-bridge production tracker** — the actual replacement for Hypack DREDGEPACK. Real-time cutter position, swing log, production rate, channel coverage map, deviation from plan. Talks to Meridian Dredge's engineering subsystem for live forecast updates.
- [ ] **Position quality engine** — DGPS/RTK/PPK/PPP fix monitoring with age-of-corrections, PDOP/HDOP/VDOP, satellite-constellation health, RAIM. UI indicators visible at all times.
- [ ] **Real-time motion-compensated bathymetry** — heave/pitch/roll correction from POS/MV / Applanix-class INS, real-time, with sound-velocity refraction and ray-tracing.
- [ ] **Real-time CUBE / TPU surface** — bathymetric surface built as data comes in, with uncertainty propagated forward; operator gets accept/reject feedback per swath.
- [ ] **Vessel-network OT/IT cyber posture** — design with NMEA 2000 / OneNet / Ethernet network segmentation; signed updates; conformance with USCG 33 CFR Subchapter H cyber regs (in NPRM as of 2025, expected effective ~2027).
- [ ] **Live RTK / NTRIP reintegration** — comes back at this phase. So does live total-station / GNSS rover / Bluetooth where relevant.

**Acceptance:** Meridian replaces Hypack on a real Weeks Marine survey vessel for one full week of line acquisition, with the surveyor never touching Hypack. Output round-trips into the same office product the contractor's PMs use. Then Meridian replaces DREDGEPACK on a real CSD for one full week of production, with the dredge master never touching DREDGEPACK.

This is the phase that delivers the "10,000× better than Hypack" claim end-to-end. v1.0 alone is "Hypack's office, modernized." v1.x is "Hypack, replaced."

---

## 5. The eight named differentiators (status carry-over)

Decisions don't change. v0.1 already shipped a v1 spike of each. They mature on the schedule already in `docs/roadmap/ROADMAP.md`:

| Codename       | Phase | What it is | v0.1 status |
|---             |---    |---         |---          |
| **Atlas**      | v0.5  | Live two-way 3D globe over the canonical Survey model | v1 spike landed (`src/meridian/atlas/`) — needs hardening |
| **DeedLM**     | v0.4  | Domain-specific LLM fine-tuned on US deed corpora      | Scaffolding (`src/meridian/ai/deedlm/`) — needs corpus + fine-tune |
| **Pulse**      | v0.4  | Conversational MCP co-pilot                            | Scaffolding (`src/meridian/ai/pulse/`) — needs UI + more tools |
| **Echo**       | v0.6  | Drone mission planner, survey-grade-output-aware       | Scaffolding (`src/meridian/echo/`) — needs UI + DJI/Wingtra export |
| **Confluence** | v0.6  | Multi-source observation fusion                         | Scaffolding (`src/meridian/confluence/`) — needs full Jacobians |
| **TruthChain** | v0.7  | Signed observation provenance, embedded verification QR | v1 landed (`src/meridian/truthchain/`) — integrate into every output |
| **CoStake**    | v0.8  | Google-Docs-style real-time co-edit via geometry CRDTs | Scaffolding (`src/meridian/costake/`) — wire up WebSocket + UI |
| **BIM bridge** | v0.7  | IFC 4.3 alignment round-trip                            | v1 landed (`src/meridian/bim_bridge/`) — harden |

All eight stay. None are cut.

---

## 6. Build approach for the Claude Code agent

The owner wants the **full plan laid out** (this document) and Claude Code to build it in **the most efficient and intelligent way possible**, with check-ins at phase boundaries.

### 6.1 Working agreement

1. **Read** the architecture doc, roadmap doc, and this handoff before touching code.
2. **Don't rewrite.** The hexagonal architecture and the existing 122 source files are correct. Extend them.
3. **One canonical data model.** Every new feature reads/writes `meridian.domain` types. Adapter-specific data lives on the adapter side.
4. **Write tests as you go.** Property-based with `hypothesis` for math; golden-file for adapters; integration for pipelines. Keep coverage at ≥80% overall, ≥95% in `domain`/`math`.
5. **Plugins, not patches.** New jurisdictions, new instrument formats, new exporters — all go in via Python entry-points (`meridian.instruments`, `meridian.exporters`, etc.).
6. **No silent fallbacks.** If a transform / parse / classify can't run, raise. Don't pretend.
7. **No cloud dependencies snuck in.** Every cloud feature has a local fallback or is opt-in via an explicit user setting.
8. **Update docs as you change behavior.** This handoff, `ARCHITECTURE.md`, and `ROADMAP.md` should never lie to the next reader.

### 6.2 Phase-boundary check-ins

After each phase completes (A–I, above), Claude Code should:

1. Run `make check` (lint + typecheck + test) and verify it passes.
2. Update `CHANGELOG.md` with the phase's deliverables, line counts, test counts, and any deviations from this handoff.
3. Update this handoff document with anything that turned out differently than anticipated.
4. Stop and write a one-paragraph "phase X complete" note for the owner to review before starting phase X+1.

### 6.3 Sequencing intelligence

The phases are ordered for compounding value:

- **A polishes the foundation.** Without A, every later phase is built on shaky demo-readiness.
- **B doubles the surveying breadth** without needing new science. Prototype-port work, parallelizable.
- **C unlocks the East-Coast/Gulf claim.** No claim, no first customer.
- **D makes the lidar/photogrammetry visually differentiating** and adds the Civil 3D feature parity that wins office switchers.
- **E is the headline.** Hydrographic parity is what nobody else has. Don't ship without it.
- **F is the legal moat.** TruthChain + IFC + plat compliance is what insurers and the Bar care about.
- **G is the multi-user upgrade.** Ship single-user first, switch in v0.8.
- **H is distribution.** Without Tauri the product is "a Python project," not "an app."
- **I is the polish that makes it a product, not a project.**

### 6.4 Don't do these things

- **Don't write a new GUI framework.** The existing CesiumJS-based `index.html` is the UI. Build against it.
- **Don't add SaaS dependencies.** Nothing in v1 calls home to anyone's server.
- **Don't pure-Python a math algorithm if `scipy`/`numpy`/`pyproj`/PDAL/`gdal` already does it correctly.** This was a chronic problem in the prototype.
- **Don't add features the owner didn't ask for.** Multi-user co-edit before v0.8, AR before v1.x, native mobile before v1.x, blockchain anything ever.
- **Don't break round-tripping.** Every export format has an importer that recovers the same canonical model.

---

## 7. Open questions Claude Code should escalate, not guess

These came up during planning and don't have a final answer. When Claude Code hits one of them, it should ask the owner before deciding:

1. **CUBE vs CUBE+ vs MB-System wrap.** When the multibeam surface algorithm is implemented in Phase E, do we wrap MB-System (BSD-licensed, mature, C-based — adds a build dep) or implement CUBE+ from the 2017 paper (more work, no native dep, possibly slower)? Ask the owner.
2. **DeedLM base model selection.** Mistral 7B vs Llama 3.1 8B vs Phi-3 — model choice depends on Ollama license terms in 2026 and the owner's hardware. Confirm at fine-tune time.
3. **Cesium ion fallback.** When the user declines an ion token, is the bare USGS 3DEP terrain enough for client-facing demos, or do we need a cached MapTiler base? Ask the owner before Phase D ships.
4. **CARIS / Qimera comparison data.** Phase E's acceptance test compares to commercial hydro packages. Does the owner have access to a side-by-side dataset, or do we use a published NOAA reference dataset? Confirm at the start of Phase E.
5. **Surveyor seal handling.** PDF certificates with PLS seal images — the owner is a licensed NC PLS, so we have one real seal to test against. For other states' templates, do we ship placeholder seals and require the user to swap in their own, or do we leave the seal blank and rely on the user's signing software? Confirm at Phase C.
6. **Tauri vs Electron vs raw browser.** Tauri is the recommended choice (Rust core, ~10 MB, single binary). If at Phase H Tauri turns out to have a blocker on macOS / Linux at that point in time, fall back to Electron. Don't try to maintain both.

---

## 8. What's already done — your inheritance

This is what v0.1 actually contains, by area, so Claude Code knows what to extend rather than re-build. (Source: `CHANGELOG.md` v0.1.0 plus a directory walk.)

### 8.1 Architecture & infra
- Hexagonal layout under `src/meridian/` (domain → math → pipelines → ports → adapters → services → api / cli).
- `pyproject.toml` with full dependency map, optional extras, plugin entry points.
- SQLAlchemy 2.x + Alembic + SpatiaLite persistence.
- Plugin discovery via Python entry points.
- CI (GitHub Actions, ruff + mypy + pytest matrix on Ubuntu/macOS/Windows × 3.11/3.12).

### 8.2 Domain & math
- `Point2D`, `Point3D`, `LineSegment`, `Arc`, `Polygon`, `Parcel`, `Survey`, `SurveyProject`, `RawObservation`, `ControlNetwork`, `NetworkAdjustment`, `PointCloud`, `Surface`, `Contour`.
- COGO (`numpy`), least-squares network adjustment (`scipy.linalg.cho_factor`), transforms (`pyproj`), Delaunay + contour extraction.

### 8.3 Adapters
- **Instruments:** Leica GSI, Trimble JXL, Sokkia SDR, TDS RW5, Nikon RAW, RINEX, NMEA.
- **CAD:** DXF (R2018+ via ezdxf), LandXML 1.2 round-trip via lxml, sheet layout, layer config, contour DXF.
- **GIS:** Shapefile (fiona), GeoPackage (fiona), GeoJSON, KML.
- **Point cloud:** LAS/LAZ (laspy), PDAL pipeline helpers.
- **Reports:** ReportLab PDF (boundary, closure, curve table).
- **Persistence:** SQLAlchemy models + Alembic migrations + repositories.

### 8.4 Pipelines
- `deed_to_polygon`, `traverse_adjust`, `network_adjust`, `pointcloud_classify`, `field_codes`.

### 8.5 Atlas (the big web UI investment)
- `tile_service.py` — 807-line FastAPI app that streams the canonical Survey model to CesiumJS as GeoJSON and (for point clouds) range-served COPC. Already has demo mode for an unattached project DB.
- `cesium_client.py` — Python-side controller for embedding the viewer in a `QtWebEngineView` (will be replaced by Tauri shell in Phase H but the code stays useful as a dev convenience).
- `static/index.html` — **7,162 lines** of CesiumJS-driven UI: dark "futuristic floating-window" theme, draggable resizable panels, scene-mode toggles (3D / 2D / Plat), measure (distance + bearing, area), draw parcel, drop pin, terrain profile, place 3D model, volume (cut/fill), CoGo, traverse, edit/split/delete, presentations (cinematic camera tours), bookmarks (named camera positions), sun/time slider, imagery layer manager, 3D Terrain & Tilesets manager.
- `edit_session.py`, `presentations.py`, `bookmarks.py`, `geofile_import.py` — back-end state for the viewer.
- `config.py` — loads optional Cesium ion + Google Maps keys.

### 8.6 Differentiator scaffolding
- `src/meridian/ai/deedlm/` — corpus builder, synthetic generator (Texas vara, NE rod-and-pole, PLSS aliquot, modern California), LoRA fine-tune driver, Ollama + HF inference backends.
- `src/meridian/ai/pulse/` — typed tool registry over services, MCP-compatible JSON-RPC dispatcher.
- `src/meridian/echo/` — sun-position algorithm (Reda & Andreas), GCP planner, boustrophedon mission generator.
- `src/meridian/confluence/` — `fuse(...)` extension to network adjustment with per-source σ priors.
- `src/meridian/truthchain/` — Ed25519 keystore, deterministic manifests, Merkle root, QR-stamped PDF, verify CLI.
- `src/meridian/bim_bridge/` — IFC 4.3 alignment export via ifcopenshell + STEP fallback, import via ifcopenshell, intent-vs-asbuilt reconciliation.
- `src/meridian/costake/` — `LWWMap`/`LWWRegister`, `GeometryCRDT` (RGA-style), `PresenceState`, FastAPI WebSocket relay.

### 8.7 Tests
- 110 tests, all passing under Python 3.11 + numpy 2.4 + scipy 1.17, in 1.4 s.
- Property-based (`hypothesis`) tests for COGO, adjustment, triangulation, contour extraction.
- Round-trip tests for GeoJSON, KML, LandXML.
- TruthChain end-to-end (keygen → sign → tamper → Merkle → verify).
- CRDT convergence under concurrent inserts and moves.
- Atlas tile-service smoke tests against `fastapi.testclient`.

### 8.8 Tooling
- `Makefile` with 16 targets — install/install-dev/install-all, test/test-fast/cov, lint/typecheck/format/check, docs, migrate/migration, run-cli/run-desktop, clean.
- `.claude/settings.json` allowlists those targets so Claude Code can run them without permission prompts.

---

## 9. First-week task list for the Claude Code agent

When Claude Code first opens this project, here's what to do, in order:

1. `make install-all` and confirm the tests pass: `make check`.
2. Skim `docs/architecture/ARCHITECTURE.md`, `docs/roadmap/ROADMAP.md`, `CHANGELOG.md`, this handoff. Reconcile anything that disagrees by editing the older docs to match this handoff.
3. Open `src/meridian/atlas/static/index.html` in a browser via `make run-cli` → `meridian atlas serve` (or whatever the run command is; if it doesn't exist, add it). Confirm the demo parcel renders on the globe.
4. Start Phase A (v0.2): wire each of the four v0.1 slices into a tab in the existing web UI. Keep the existing styling. Check in after each slice ships.
5. Update `pyproject.toml`: drop the `field` extras group; add a `hydro` extras group placeholder for Phase E.
6. Update `README.md` to reflect the new positioning ("CAD + Survey + Hydro + 3D globe — one tool, local-first").

Then move into Phase B and continue, milestone by milestone.

---

## 10. Sources

- `README.md`
- `CHANGELOG.md`
- `pyproject.toml`
- `docs/architecture/ARCHITECTURE.md`
- `docs/roadmap/ROADMAP.md`
- `src/meridian/atlas/tile_service.py`
- `src/meridian/atlas/static/index.html`
- `src/meridian_desktop/app.py`
- Owner conversation, 2026-05-07 (this session).
