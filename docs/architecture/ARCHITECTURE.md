# Meridian — Architecture

This document is the **single source of truth** for how Meridian is laid out, why, and what the rules are. If you are about to add a feature, a module, or a dependency, read this first.

---

## 1. Goals (in priority order)

1. **Correctness.** Surveying is a profession of liability. A wrong coordinate is a lawsuit. Numerical correctness, geodetic rigor, and audit trails come before convenience.
2. **One canonical data model.** A `Point`, `Parcel`, `Observation`, `Survey` are defined once. Every adapter converts to/from these.
3. **Domain independence.** The core domain knows nothing about files, databases, HTTP, or GUIs. You can run the whole library headless on a CI box or wrap it in a different UI without touching the math.
4. **Replaceable adapters.** Swap SQLite for PostgreSQL/PostGIS, Tesseract for PaddleOCR, ezdxf for ODA, PySide6 for a web frontend — all without changing domain code.
5. **Plugin-first extensibility.** Instrument drivers, exporters, importers, jurisdictions, and AI providers are plugins resolved via Python entry points.
6. **Performance where it matters.** numpy/scipy/PDAL for hot paths. Background jobs for long work. The UI never blocks.

## 2. The Hexagonal Layout

```
                      ┌──────────────────────────┐
                      │    meridian_desktop      │  ← PySide6 GUI (one of many possible UIs)
                      └────────────┬─────────────┘
                                   │
                      ┌────────────▼─────────────┐
                      │     meridian.api         │  ← FastAPI HTTP (used by GUI + future web)
                      └────────────┬─────────────┘
                                   │
                      ┌────────────▼─────────────┐
                      │   meridian.services      │  ← Application services (use-cases)
                      └────────────┬─────────────┘
                                   │
        ┌──────────────────────────┼──────────────────────────┐
        │                          │                          │
┌───────▼────────┐   ┌─────────────▼─────────────┐   ┌───────▼────────┐
│ meridian.ports │   │  meridian.pipelines       │   │ meridian.plugins│
│ (interfaces)   │   │  (domain workflows)       │   │ (entry-points) │
└───────┬────────┘   └─────────────┬─────────────┘   └────────────────┘
        │                          │
        │            ┌─────────────▼─────────────┐
        │            │     meridian.math         │  ← numpy/scipy kernels
        │            └─────────────┬─────────────┘
        │                          │
        │            ┌─────────────▼─────────────┐
        │            │     meridian.domain       │  ← Pure entities, no I/O
        │            └───────────────────────────┘
        │
┌───────▼────────────────────────────────────────────┐
│              meridian.adapters                     │
│   instruments / cad / gis / pointcloud /          │
│   reports / ocr / persistence                      │
└────────────────────────────────────────────────────┘
```

**Dependency rule:** arrows point inward. `domain` imports nothing from anywhere outside `domain` and the standard library + numpy/scipy. `adapters` may import `domain`, `math`, `ports` but never each other. `services` orchestrate `pipelines` and `ports`. UIs talk to `services` (or `api` for HTTP).

## 3. Layer-by-layer

### `meridian.domain` — entities

Pure dataclasses (or `attrs` / `pydantic` if validation is needed). No I/O, no SQLAlchemy, no Qt, no `requests`. Examples:

| Module | Key types |
|---|---|
| `geometry.py` | `Point2D`, `Point3D`, `LineSegment`, `Arc`, `Polygon`, `BBox` |
| `observation.py` | `RawObservation`, `Setup`, `AdjustedObservation`, `ObservationKind` (enum) |
| `network.py` | `ControlPoint`, `ControlNetwork`, `NetworkAdjustment`, `ErrorEllipse` |
| `parcel.py` | `Call` (line/curve), `Boundary`, `Parcel`, `ParcelMetadata` |
| `deed.py` | `Deed`, `Party`, `Encumbrance`, `Recording`, `ChainOfTitle` |
| `pointcloud.py` | `PointCloud`, `Classification`, `TIN`, `Surface`, `Contour` |
| `survey.py` | `Survey`, `SurveyProject` (the **aggregate root**) |
| `crs.py` | `CRS`, `Datum`, `Projection`, `Geoid`, `VerticalDatum` |

**Rule:** if you need to add a field that's only meaningful to one adapter (e.g., a DXF layer name), put it on the **adapter's** representation, not the domain entity.

### `meridian.math` — numerical kernels

Pure functions over numpy arrays and domain dataclasses. No I/O.

- `cogo.py` — inverse, traverse, area (DMD/DPD), intersections.
- `adjustment.py` — least-squares network adjustment (`scipy.sparse.linalg`), free / minimally constrained / constrained modes, error ellipses, chi-square goodness-of-fit, outlier detection (standardized residuals).
- `transforms.py` — datum/projection transforms via `pyproj`. Resolves transformation chains (NAD27→NAD83(2011)→WGS84(G2139)) explicitly so we know which grid file we used.
- `triangulation.py` — Delaunay (`scipy.spatial.Delaunay`), constrained Delaunay (Shewchuk's `triangle` if available), TIN-from-points, contour extraction.
- `statistics.py` — confidence ellipses, residual analysis, blunder detection.

### `meridian.pipelines` — multi-step workflows

Compose math + domain into named workflows. Pure functions, deterministic, each step is independently testable.

- `deed_to_polygon.py` — text → calls → coordinates → closed polygon.
- `traverse_adjust.py` — raw observations → setup reduction → traverse → closure.
- `network_adjust.py` — observation set → design matrix → normal equations → adjusted coordinates + covariance.
- `pointcloud_classify.py` — raw cloud → noise removal → ground classification → TIN → contours.
- `retracement.py` — historical deed + found monuments → reconciled boundary.

### `meridian.ports` — interfaces

`abc.ABC` interfaces or `typing.Protocol` types that define what adapters must provide.

- `repository.py` — `SurveyRepository`, `ParcelRepository`, `PointRepository`, …
- `instrument.py` — `InstrumentDriver` (read raw file → `list[RawObservation]`).
- `exporter.py` — `Exporter` (Survey → bytes / file).
- `importer.py` — `Importer` (bytes / file → Survey or partial entity).
- `ai.py` — `LLMClient`, `OCRClient`, `VisionClient`.

### `meridian.adapters` — concrete I/O

One module per format / external system. Each adapter is responsible for converting **between an external representation and the canonical domain types**. Adapters never call each other.

- `instruments/` — `leica_gsi.py`, `trimble_jxl.py`, `sokkia_sdr.py`, `tds_rw5.py`, `nikon_raw.py`, `rinex.py`, `nmea.py`, `ntrip_client.py`.
- `cad/` — `dxf_writer.py` (ezdxf), `dxf_reader.py`, `landxml_io.py` (lxml + schema), `dwg_bridge.py` (optional ODA).
- `gis/` — `shapefile.py` (fiona/geopandas), `geopackage.py`, `geojson.py`.
- `pointcloud/` — `las_io.py` (laspy), `pdal_pipeline.py` (PDAL), `copc.py`.
- `reports/` — `pdf_writer.py` (ReportLab), `html_writer.py` (Jinja2).
- `ocr/` — `tesseract.py`, `paddle.py`, `ai_vision.py`.
- `persistence/` — SQLAlchemy models, Alembic migrations, repository implementations.

### `meridian.services` — application services

Use-case orchestrators. They translate a single user intent ("import this file", "adjust this network", "export this survey") into a sequence of calls across pipelines + adapters. They are the thing the API and GUI call.

### `meridian.plugins` — plugin loader

Discovers entry points under `meridian.instruments`, `meridian.exporters`, `meridian.importers`, `meridian.jurisdictions`, `meridian.ai_providers`. Each entry point resolves to a class implementing the corresponding port.

### `meridian.jobs` — background work

Long-running tasks (PDAL pipelines on 100M-point clouds, LLM extraction, network adjustment of 5000-observation networks) run in a job queue. The desktop GUI subscribes to job events via a local broker (in-process pub/sub or Redis if multi-user). Never block the UI thread.

### `meridian.api` — FastAPI HTTP

A thin async layer over `meridian.services`. The desktop GUI talks to it via a local in-process transport (no HTTP overhead for single-user). Web/mobile UIs talk to it over real HTTP.

### `meridian.cli` — Typer CLI

Power-user / batch / CI entry point. Calls services directly. Useful for scripting, batch processing, and reproducible builds.

### `meridian_desktop` — PySide6 GUI

A *thin* Qt shell that holds tabs / windows / wizards. **No business logic.** Calls services. The 3D viewer (PyVista) and 2D plan view (PyQtGraph) are the heavy widgets.

## 4. Persistence

**One database. Real migrations. Atomic transactions across all entities.**

- ORM: SQLAlchemy 2.x (typed).
- Migrations: Alembic. Every schema change ships a migration.
- Spatial extension: SpatiaLite on SQLite (default for desktop), PostGIS on PostgreSQL (multi-user / cloud).
- Geometry storage: WKB blobs in spatial columns, plus indexed bounding boxes for fast spatial queries.
- Repository pattern in `adapters/persistence/repositories.py`. Services depend on the abstract `meridian.ports.repository` interfaces, never the concrete SQLAlchemy classes.

## 5. Coordinate reference systems (CRS)

Every coordinate-bearing entity carries a CRS. There is no "implicit" CRS. Conversions go through `meridian.math.transforms`, which builds an explicit `pyproj.Transformer` chain and records which grid files were used.

Supported (out of the box):
- WGS84, NAD83 (multiple realizations), NAD27, ITRF.
- US State Plane (all zones), UTM (all zones).
- NADCON5 grid shifts, HARN.
- Geoid18, Geoid12B, VDatum tidal datums.

## 6. Plugin system

Plugins are ordinary Python packages that declare entry points:

```toml
[project.entry-points."meridian.instruments"]
my_total_station = "my_pkg.driver:MyDriver"
```

`meridian.plugins.discovery` enumerates entry points at startup, validates that each resolves to a class implementing the right port, and registers them. Plugins can also ship Alembic migrations for their own tables (they live in a separate `alembic` branch).

Plugin types:
- `meridian.instruments` — total-station / GNSS drivers.
- `meridian.exporters` / `meridian.importers` — file formats.
- `meridian.jurisdictions` — state-specific certificate templates, filing rules, monumentation standards.
- `meridian.ai_providers` — LLM / vision providers.
- `meridian.workflows` — custom GUI wizards (when registered against the desktop app).

## 7. Concurrency model

- The GUI runs the Qt event loop on the main thread.
- Long jobs run in `meridian.jobs` workers (a `concurrent.futures.ProcessPoolExecutor` for CPU-bound, `asyncio` for I/O-bound).
- The API is async (FastAPI). Adapter calls that are sync (most) are wrapped in `asyncio.to_thread` to avoid blocking the event loop.
- The job queue emits progress events on a `Queue`/WebSocket. The UI subscribes and updates progress bars.

## 8. AI / LLM use

AI is **always optional and always pluggable**. Three port types in `meridian.ports.ai`:
- `LLMClient` — chat-completion style.
- `OCRClient` — image → text.
- `VisionClient` — image + prompt → structured response.

First-party adapters: Ollama (local), OpenAI, Anthropic. AI is used for: deed parsing fallback when regex fails, OCR reconciliation when engines disagree, plat-image extraction. Everything has a deterministic non-AI fallback.

## 9. What we deliberately do **not** do

- **No pure-Python numerical algorithms where a real library exists.** Pure-Python Gauss-Jordan inversion, Bowyer-Watson Delaunay, Shapefile binary writing all live in the previous prototype and will not be ported.
- **No "phase-stacked" optional imports** like the old `try: from core.foo import bar; except ImportError: pass`. If a feature requires a dependency, it lives behind an extras group and the user installs the extras to get the feature.
- **No silent fallbacks.** If pyproj cannot resolve a transformation chain, we raise — we do not silently passthrough coordinates.
- **No file-format-specific data in the domain.** `Parcel.metadata.dxf_layer` does not exist. The DXF adapter chooses the layer.
- **No god-class GUI.** `MainWindow` holds tabs and routes signals. Each tab is its own class in its own file.

## 10. Testing strategy

- **Domain & math:** unit tests with `hypothesis` property-based testing where invariants exist (e.g., area is invariant under rotation; `inverse(forward(p, b, d))` round-trips).
- **Adapters:** test each adapter against a *recorded* input file. Sample files live in `data/samples/`.
- **Pipelines:** integration tests that run end-to-end on canonical fixtures.
- **Numerical correctness:** golden-file tests that pin computed coordinates against trusted references (e.g., NGS adjustment of a real NGS network).
- **Coverage target:** 80%+ overall, 95%+ in `domain/` and `math/`.

## 11. Versioning & release

- Library version is in `pyproject.toml`.
- Database schema version is tracked by Alembic.
- Plugin contract version is declared per port. Breaking changes bump the major version of the port; plugins declare which port version they target.

---

*Read this document once a quarter. If something is no longer true, fix the document or fix the code — but do not let them drift.*
