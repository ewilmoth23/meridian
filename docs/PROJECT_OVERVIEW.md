# Meridian

> **Where every line is true.**

Meridian is a modern, opinionated, professional-grade surveying suite built for the way surveyors actually work today: total stations, GNSS receivers, drones, and lidar — feeding into rigorous coordinate geometry, least-squares network adjustment, deed reconciliation, and CAD/GIS deliverables.

It is the spiritual successor to the *Ultimate Deed Reader / Deed2DXF Pro* prototype (v1.6.0), rebuilt from the ground up around a single canonical data model, real geodetic math (numpy/scipy/pyproj), real point-cloud processing (PDAL/laspy), and a strict hexagonal architecture so the engine, the adapters, and the UI evolve independently.

## What Meridian does

| Capability | What it covers |
|---|---|
| **Field-to-finish** | Total-station raw data (Leica GSI, Trimble JXL/JOB, Sokkia SDR, TDS RW5, Nikon RAW) → COGO traverse → least-squares network adjustment → CAD deliverables. |
| **GNSS post-processing** | RINEX import, baseline processing, NTRIP correction streams, RTK/PPK fixing, network adjustment with covariance matrices. |
| **Lidar / point cloud** | LAS/LAZ ingest at billions-of-points scale (PDAL pipelines), ground classification, TIN-from-cloud, contour extraction, breakline support, COPC for cloud-optimized streaming. |
| **Deed & legal description** | Metes-and-bounds parser (regex + LLM consensus), PLSS, exception/less-and-except clauses, chain of title, title-commitment ingest, deed comparison, adverse-possession analysis. |
| **Boundary surveying** | Boundary evidence weighting, monument retracement, gap/overlap detection, parcel fabric (topology), legal-description standardization, jurisdiction-aware certificates. |
| **CAD / GIS interoperability** | DXF (ezdxf, R2018+), LandXML round-trip (lxml), Shapefile, GeoPackage, GeoJSON, KML — all consuming and producing the same canonical Survey model. |
| **Geodetic transformations** | NAD27↔NAD83↔WGS84 via NADCON5, HARN, GEOID18, VDatum (pyproj + grid files). State Plane and UTM with proper zone selection. |
| **Reports** | True PDF (ReportLab) with embedded fonts, signed/sealed certificate templates, jurisdiction-specific deliverables, closure reports, network adjustment reports with error ellipses. |

## Why Meridian (and not Carlson / TBC / Civil 3D)?

- **Open, scriptable, plugin-first.** Every instrument driver, exporter, jurisdiction template, and pipeline step is a plugin. Add a new total-station format by dropping in a Python package.
- **Local-first AI.** Optional Ollama / OpenAI / Anthropic for deed parsing, plat reading, OCR reconciliation. No mandatory cloud.
- **Real math, not pure-Python theater.** `scipy.linalg` for least-squares adjustment, `scipy.spatial.Delaunay` for triangulation, `pyproj` for transforms, `PDAL` for point clouds. Numerically sound by default.
- **One canonical data model.** A `Point`, `Parcel`, `Observation`, and `Survey` are defined once and used everywhere. Every adapter converts between an external format and these.
- **Hexagonal architecture.** The domain core has zero I/O. You can swap the database, the desktop UI, or the file format without touching the math.

## Status

`v0.1` — foundation phase. The architecture, data model, persistence layer, and four end-to-end vertical slices are landing now. See [docs/roadmap/ROADMAP.md](docs/roadmap/ROADMAP.md) for the multi-phase plan.

## Quick start

```bash
# Editable install with all extras
python -m pip install -e ".[all]"

# Run the test suite
pytest

# Open the desktop app
meridian-desktop

# Or run the CLI
meridian --help
```

## Project layout

```
src/meridian/                # The library
├── domain/                  # Canonical entities (no I/O)
├── math/                    # Pure numerical kernels
├── pipelines/               # Multi-step domain workflows
├── ports/                   # Abstract interfaces
├── adapters/                # Concrete I/O (instruments/CAD/GIS/clouds/reports/persistence)
├── services/                # Application services
├── plugins/                 # Plugin discovery and loading
├── jobs/                    # Background job queue
├── api/                     # FastAPI HTTP API
└── cli/                     # Typer CLI
src/meridian_desktop/        # PySide6 GUI
tests/                       # Mirrors src/ structure
docs/                        # Sphinx + Markdown
plugins/                     # First-party plugin packs
data/                        # Reference grids, sample inputs
```

See [docs/architecture/ARCHITECTURE.md](docs/architecture/ARCHITECTURE.md) for the full design.

## License

Proprietary. © 2026 Meridian Project. All rights reserved.
