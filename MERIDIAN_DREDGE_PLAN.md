# Meridian Dredge — Product Plan

> **Companion to:** `HANDOFF.md` (the Meridian core surveying suite plan).
> **Status:** Pre-build planning. Nothing here is implemented yet.
> **Owner:** Ethan Wilmoth — practicing licensed surveyor (NC), former Weeks Marine, ran $100M+ dredge project P&Ls. Subject-matter expert for this product.
> **Type:** Separate product. Built **on top of** Meridian core, not inside it.
> **Engine:** Unreal Engine 5 + Cesium for Unreal.
> **Tagline (working):** *Where every dig is true.*

---

## 0. Why this is a separate document

The Meridian core surveying suite (`HANDOFF.md`) has already been scoped, architected, and partially built. Folding a real-time dredge simulation engine into that codebase would (a) drag the surveying product's release date by 12–18 months, (b) introduce a C++/Blueprint codebase to a Python project, and (c) confuse the buyer — surveyors and contractors are different customers buying through different procurement processes.

So **Meridian Dredge is its own program.** It consumes Meridian's canonical project model (parcels, surfaces, point clouds, design templates, sonar surveys, vertical/horizontal datums) but ships as a separate Windows/Linux application built in Unreal Engine 5. The two products talk to each other via a local bridge (shared project files + a localhost WebSocket for live state). A surveying customer can buy Meridian without Dredge. A dredging customer can buy Dredge — but it's much more useful with Meridian feeding it the data, so the natural sales motion is "Meridian first, Dredge attached."

When this document and `HANDOFF.md` reference each other, this one wins for dredge-specific decisions and `HANDOFF.md` wins for Meridian-core decisions.

---

## 1. The vision in one paragraph

A dredging contractor opens Meridian Dredge on the project superintendent's laptop, drops in the project's CAD design template (Hypack `.tin`, AutoCAD corridor, LandXML alignment, IFC channel), the most recent pre-dredge survey, the dredge's equipment spec, and the soil report. The application opens a photoreal 3D scene — actual seafloor from the survey, actual channel design overlaid in transparent blue, actual dredge model rigged with operating physics (cutter, ladder, spuds, pump, discharge), and actual project-area imagery from Cesium ion. The superintendent runs the project forward at 60×, 600×, or 3600× wall-clock time and watches the predicted production cut the channel out of the seafloor over an estimated 27 days. The forecast is calibrated against soil + dredge class + cycle conditions + weather windows; the uncertainty band is honest. As the real project runs, the operator drops in daily survey updates and the model re-runs, narrowing or widening the forecast against actual progress. Crew can be trained on the simulator off-hours using the same project's data. USACE and the contractor get a single defensible production model that says "we are 73% done, on schedule, with 90% confidence."

That's the pitch. It is not unrealistic. Every component of it exists as published research or shipping product; nobody has glued them together against real project data. That's the opening.

---

## 2. Market case

### 2.1 Who pays, and why

The dredging market in the US is roughly **$6–8 B/year of services** (USACE + private), part of the global **~$12 B/year**. The IT spend is small but growing fast for three reasons that all show up in 2026:

1. **USACE digital-deliverables mandate.** The 2024 update to EM 1110-2-1003 requires defensible digital production records for every federal dredge project. Hypack DREDGEPACK exports satisfy the letter of the rule but not the spirit; USACE district engineers want better.
2. **BIL + IRA dredging dollars.** Roughly $17 B is flowing into ports + waterways infrastructure through 2030. Contractors are bidding on more work than they have engineers to plan, which means a tool that automates planning has tailwind.
3. **IADC standardization push.** The International Association of Dredging Companies is pushing a standardized production-reporting schema that nobody has implemented in commercial software yet.

### 2.2 First customer — Weeks Marine (commercial, not design-partner)

The owner ran $100M+ dredge project P&Ls at Weeks. He is the subject-matter expert and does not need Weeks for requirements discovery. **Weeks is the first paying customer, not a free pilot.** That's a deliberate posture:

- **Pre-build (now):** owner writes the failure-mode-driven requirements (Section 12) from his own project experience. No discovery calls required to build v0.1 of the product.
- **v0.1–v0.2 (visualization layer):** ship Layer 1 inside Meridian core (no Unreal yet). This becomes the door-opener at Weeks and elsewhere — but it's not the sales motion, it's a credibility signal.
- **v0.3 (engineering subsystem):** owner calibrates the production-rate model against three Weeks projects he personally ran. Calibration is the proprietary moat — the model is more accurate than competitors' because it's been tuned against real Atlantic + Gulf dredge work, not generic Delft-school textbook cases.
- **v0.4 (forecast mode):** sold to Weeks at commercial pricing. Owner's existing relationships shorten the sales cycle, but the deal is real money for real value. Reference rights are negotiated, not given away.
- **v0.5 (reconciliation mode + commercial expansion):** with a paying Weeks deployment as the reference, expand to USACE districts and other contractors.

The shift from "design partner" to "first paying customer" matters because (a) it forces the product to be commercial-grade from v0.4, not a polished prototype; (b) it preserves price discipline — if the first customer didn't pay, the second customer wouldn't either; (c) it respects the owner's standing inside Weeks — he's not going back as a vendor begging for a pilot, he's going back as a former colleague selling a tool that solves a problem they have.

### 2.3 Competitive landscape (be honest about it)

| Tool                          | What it does                                                              | What it doesn't                                              |
|---                            |---                                                                         |---                                                            |
| **Hypack DREDGEPACK**         | Real-time production tracking on the dredge bridge; 30+ years of inertia | Not a sim; 2D-plus-depth UI; tied to Hypack data model       |
| **Royal IHC CSD-Sim**         | Photoreal CSD operator training simulator; sold to training centers       | Closed system; doesn't ingest project data; €€€€€            |
| **Damen Dredge Simulator**    | Damen-vessel-specific operator training                                   | OEM-specific; training-only                                  |
| **NAUTIS by VSTEP**           | Maritime pilot training including some dredge variants                    | Pilot/captain training, not production planning              |
| **CM Labs Vortex**            | Generic heavy-equipment sim, configurable for dredges                     | Generic — no built-in dredge engineering, no project bathymetry |
| **Trimble Marine Construction** | Fleet management for dredges                                            | Logistics, not engineering or simulation                     |
| **Maptek Vulcan / Deswik**    | Mining production planning, can be coerced into dredging                  | Mining-first, weak on water + survey integration             |

**The unmet need** isn't "another dredge sim." It's **a sim grounded in the project's own bathymetry, design templates, soil reports, and dredge specs, that produces production forecasts a contractor's CFO and a USACE district engineer will both sign off on.** Nobody sells that.

---

## 3. Product structure — three layers, three milestones

Last conversation with the owner separated three layers. The plan respects that separation because the layers have different difficulty curves, different customers, and different revenue.

### Layer 1 — Design Surface vs. Survey Visualization
**Lives in:** Meridian core (browser UI, CesiumJS). **Not** Meridian Dredge.

This is the cheap layer that makes Meridian core demo-able to dredging customers without a single line of Unreal. A surveyor or PE imports a design template (Hypack TIN, LandXML alignment + cross-sections, AutoCAD corridor, IFC channel), imports the latest bathymetry, and gets:

- Difference-surface raster showing high-spots / low-spots vs. design.
- 3D mesh of the design template draped over the seafloor, with cut/fill volumetrics.
- Section-cut tool extending the existing Atlas terrain-profile widget.
- Simple "% complete by volume" metric against a reference pre-dredge survey.

This is added to **Meridian core's Phase E (`HANDOFF.md` v0.6 hydrographic phase)** and ships when hydro ships. **No Unreal needed.** It's the demo that opens the door at every dredge contractor.

### Layer 2 — Photoreal Dredge Cycle Simulation
**Lives in:** Meridian Dredge (UE5 + Cesium for Unreal). **The headline.**

This is the photoreal simulation. CSD swings, cutter cuts, spuds advance, slurry transports through the line, material exits the discharge. Realistic enough that a Weeks dredge master watches it and says "yeah, that's about right" — that's the bar. Photoreal enough that USACE shows it in stakeholder meetings — that's the bonus.

Engineering inside the visual, **prioritized by what actually breaks budgets** (owner's $100M+ project experience, see Section 12):

1. **Weather + downtime model.** Historical weather priors per geography + season, hurricane-prep posture for Atlantic/Gulf, fog/sea-state thresholds by dredge class, billable-vs-at-risk distinction. **This is first because weather eats Atlantic and Gulf jobs.**
2. **Soil characterization with explicit uncertainty.** Boring logs are sparse and frequently wrong; the model carries probabilistic soil classes with covariance, not a single "expected" value. Miedema's *Delft Sand, Clay & Rock Cutting* equations drive production rate as a function of soil class, cutter geometry, RPM, swing speed, ladder angle. Soil uncertainty propagates into forecast uncertainty — that's the honest CFO number.
3. **Equipment reliability + maintenance cycles.** Pump failure distributions, cutter-tooth wear, pipeline breach probability, scheduled vs. unscheduled downtime. Reliability data is the product's third moat after weather and soil.
4. **Discharge / material handling.** Slurry-pump model (Wilson + Addie & Sellgren) for discharge volumetric throughput as a function of solids concentration, pipe diameter, pump curve. Booster pump placement, pipeline length, beach-discharge management, hopper turnaround. Modeled in detail because pipe-side bottlenecks routinely cap production below cutter-side capacity.

Plus the structural pieces that make the visual work:

- Rigid-body dynamics for the dredge structure (Chaos physics in UE5).
- Spud-walking / anchor-pull positioning model.
- Niagara particles for slurry, sediment plume, dredge wake.
- UE5 Water plugin for ocean surface; FluidNinja or similar for cheap fluid effects close to the cutter.

The sim runs at a fixed time-step (50 Hz physics, 60 Hz render) and supports time-acceleration (1×, 60×, 600×, 3600×) so a 27-day project can be watched in 30 minutes. It runs **deterministically given the same inputs and seed** — that's a hard requirement for the forecasting use case.

### Layer 2.5 — Glassbox-class situational awareness (the project-manager pane)

A persistent globe view for the project manager / superintendent that shows everything happening in and around the operation, in real time. This sits *next to* the photoreal dredge sim, not inside it — a project office wants both a "what's happening right now across my whole operation" display and the "drive into a specific dredge cycle" view.

What's on the pane:

- **Multi-vessel spread tracking.** Every AIS-broadcasting unit in the spread (the cutter dredge, attendant tugs, booster pump barge, discharge crew boat, survey boat, pilot boats, attending USCG vessels). Tracked in real time. Roles and relationships modeled — "this tug is attending this dredge," "this survey boat is working ahead of the cut." Uses the new `Fleet` aggregate from Meridian core.
- **External AIS contacts.** All vessels approaching the project geography. Filtered by AIS class (class A commercial vs. class B small craft), vessel type, and projected closest-point-of-approach (CPA) to the operation. Vessels on collision course with the spread or the safety zone get prioritized alerting.
- **USCG safety zone enforcement.** The federally-published exclusion zone around active dredge gear (typically 500 yd for cutter, larger for active pipeline) rendered as a 3D volume on the globe. Any AIS contact entering or projected to enter triggers an alert to the dredge master and the project office. Failure to enforce is a USCG enforcement action against the contractor; doing this well is real value.
- **Weather feeds.** NOAA marine forecast (6-hour resolution), NDBC buoy real-time wind/wave/temp, NHC tropical-cyclone tracks during storm season. Dredge master sees the same view as the office. Hurricane-prep posture is triggered from this pane.
- **Tide and current.** NOAA CO-OPS API for water level + predicted tide + currents at the nearest gauge. Live overlay on the globe and as numbers in a sidebar.
- **Federal and state overlays.** USACE Section 408 coordination notices, FEMA NFHL flood zones, federal channel boundaries, NOAA dredged-material disposal sites, regulated obstructions, environmental closures (turtle / fish / mammal windows). All available as ArcGIS REST endpoints; pulled in as live layers.
- **USCG Notice to Mariners + Local Notice to Mariners.** Parsed from the weekly USCG district bulletins (currently distributed as PDFs — there's a reason this is unsolved). Channel closures, dredging operations elsewhere, hazardous obstacles, marine events.
- **Pilot-operations awareness.** For projects in major ports (NY/NJ, Charleston, Savannah, Houston, Mobile, Tampa), integration with port pilot association schedules where exposed via API. When a pilot is bringing a vessel through the project's geography, the pane surfaces it.
- **Environmental observation log.** Marine mammal observers, turbidity readings, daily DMRs (Discharge Monitoring Reports). Increasingly mandated; integrate with field-tablet input.

This pane is built on the same `meridian.realtime` event-streaming substrate as the rest of the system. It runs in a browser tab, *not* in Unreal — for situational awareness the browser is faster, more familiar, and runs on any laptop in the office. The photoreal sim (Layer 2) is the Unreal app the user opens when they want to dive deep on a cycle.

### AIS sourcing — pluggable with free default

The AIS adapter is **pluggable** (`meridian.realtime.ais.<provider>`). v1 ships with:

- **AISHub** as the free default — community-aggregated terrestrial AIS, ~40nm coastal coverage, free with rate limits. Sufficient for inland and near-coastal projects.
- **MarineTraffic free tier** as a backup free source.
- **Spire Maritime / Orbcomm / exactEarth** as paid satellite-AIS providers, customer-configured. v1 doesn't bundle these; the customer brings their own subscription. We add bundled satellite AIS to a Meridian Dredge license tier once a customer asks for it (and pays for it).

AIVDM/AIVDO sentence parsing via `pyais`. Server-side bbox + vessel-type + age filters before any data hits the client. Cesium Entity clustering on the client above a zoom-level threshold.

### Layer 3 — Forecast / Train / Reconcile
**Lives in:** Meridian Dredge (the same UE5 app, plus a sidecar Python service).

This is what justifies the price tag. Three modes that all use the same simulation engine:

- **Forecast mode.** Run the sim 1,000 times with Monte Carlo over uncertain inputs (soil variability, weather windows, equipment downtime distribution). Output: completion-date probability curve, volume probability curve, dollar-cost probability curve. Calibrated against the contractor's historical actuals — every Weeks job we have data on becomes a calibration point for the model. This is *the* CFO and PM tool.
- **Training mode.** Stripped-down version that an operator can fly. Same dredge, same project, but the operator drives the cutter, swings the ladder, manages the spuds. Performance scored against the deterministic forecast.
- **Reconciliation mode.** Take the dredge's actual GPS + sensor logs (most CSDs run a NMEA log + production-monitoring system) and replay them against the forecast. Highlight where the actual diverged from the predicted. Produce the USACE-defensible production report at the end of the project. *This is the EM 1110-2-1003 deliverable.*

---

## 4. Architecture

```
┌────────────────────────────────────────────────────────────────────┐
│                         Meridian Dredge                            │
│                  (Unreal Engine 5, C++/Blueprint)                  │
│                                                                    │
│   ┌──────────────────┐  ┌──────────────────┐  ┌────────────────┐  │
│   │ Cesium for       │  │ Dredge Actor     │  │ Sim Director   │  │
│   │ Unreal           │  │ (CSD/TSHD/BHD/   │  │ (Forecast,     │  │
│   │ - terrain        │  │  Hopper)         │  │  Training,     │  │
│   │ - imagery        │  │ - rigging        │  │  Reconcile     │  │
│   │ - 3D Tiles       │  │ - physics        │  │  modes)        │  │
│   │ - bathymetry     │  │ - hydraulics     │  │                │  │
│   └──────────────────┘  └──────────────────┘  └────────────────┘  │
│                                  │                                 │
│   ┌──────────────────────────────▼─────────────────────────────┐   │
│   │  Engineering Subsystem (C++)                               │   │
│   │  - Miedema soil-cutting model                              │   │
│   │  - Wilson/Addie+Sellgren slurry hydraulics                 │   │
│   │  - Production-rate calculator                              │   │
│   │  - TPU/uncertainty propagation                             │   │
│   │  - Time-step Monte Carlo driver                            │   │
│   └──────────────────────────────┬─────────────────────────────┘   │
└──────────────────────────────────┼─────────────────────────────────┘
                                   │
                                   │ JSON over local WebSocket / shared project files
                                   │
┌──────────────────────────────────▼─────────────────────────────────┐
│                  Meridian Core (Python, FastAPI)                   │
│                                                                    │
│  - Canonical Survey/PointCloud/Surface/Parcel/Network model        │
│  - Hydrographic processing (Phase E in HANDOFF.md)                 │
│  - Design-template ingest (LandXML, IFC, DXF, Hypack TIN)          │
│  - Bathymetric surface generation (CUBE, IDW, Kriging)             │
│  - Project DB (SpatiaLite single-user / PostGIS multi-user)        │
└────────────────────────────────────────────────────────────────────┘
```

### 4.1 Why UE5 + Cesium for Unreal

- **Cesium for Unreal** is mature (1.0 GA in 2021, used by Bentley iTwin, Epic Twinmotion, Unity-equivalent doesn't exist at the same fidelity). Drag-and-drop terrain + 3D Tiles + imagery from the same Cesium ion account that Meridian core uses.
- **Chaos physics** (UE5 native) handles rigid bodies + constraint solving for the dredge mechanics without a third-party physics engine.
- **Niagara** is the most mature particle system for slurry / sediment plume / dredge wake.
- **Water Plugin** + Single Layer Water shader give a credible ocean surface; LakeWaters / ocean tooling continues to mature.
- **Pixel Streaming** is built in — when we want to demo the sim to a USACE meeting from the CFO's iPad, it runs on a workstation back at the office and streams.
- **Royalty model** (5% above $1M revenue per product per year) is acceptable for a vertical B2B product with hundreds-of-thousands-per-seat ASP.

### 4.2 Why a separate executable, not embedded

UE5 cannot meaningfully embed inside a Python process. It's a multi-gigabyte runtime with its own process model. We embrace that — Meridian Dredge is its own `.exe` / `.app` that the user launches. The two products communicate via:

- **Project files.** Meridian core writes a `.meridian` project bundle (ZIP of SQLite + GeoTIFF tiles + LandXML + glTF templates). Meridian Dredge opens it directly. This is the canonical "give me the project" path.
- **Local WebSocket.** When both apps are running side-by-side, they handshake on `localhost:<port>` and stream live updates (e.g., the user edits a template in Meridian core and the change propagates to the running Dredge sim).
- **Shared TruthChain manifest.** Both apps sign their outputs with the same Ed25519 key from `meridian.truthchain.keystore`. A reconciliation report from Dredge cross-references the input bathymetry's manifest from Meridian.

### 4.3 Why deterministic

Forecasting is the killer feature. Forecasting requires the same inputs to produce the same output. UE5 game engines are *not* deterministic by default — frame-rate-coupled physics, multithreaded scheduling, and GPU non-determinism all leak in. We solve this by running the engineering subsystem on a **fixed-step physics tick decoupled from rendering**, with all RNG seeded explicitly. The visual is a presentation layer over a deterministic core. This is a standard pattern in racing-sim and military-sim development; it is not novel but it has to be designed in from day one.

---

## 5. Engineering domain depth — owner is the expert

The simulation is only as good as the dredging engineering inside it. **The owner is that expert.** He ran $100M+ dredge project P&Ls at Weeks Marine. The published academic literature is the framework; the owner's project experience is the calibration data. That's the differentiator no competitor can replicate.

### Reference literature (framework, not authority)

The published model gives you the equations. Real project data gives you the constants. The owner brings the constants.

- **Miedema** — *Delft Sand, Clay and Rock Cutting Model* (Delft TU, open access). Canonical equation set for production rate by soil class.
- **Vlasblom lectures** (Delft TU, public). Worked examples for CSD/TSHD production calculation.
- **Bray, Bates & Land 1992** — *Dredging: A Handbook for Engineers* (Wiley). The handbook reference.
- **Randall 2004** — Texas A&M Dredging Engineering. American canonical.
- **Wilson, Addie, Sellgren & Clift** — *Slurry Transport Using Centrifugal Pumps* (Springer). Pump curve + pipe friction + solids concentration.
- **IADC / CEDA** — production-reporting standards (in development).
- **USACE EM 1110-2-1003** — *Hydrographic Surveying* + the in-development production-deliverable extension.
- **Hypack DREDGEPACK output schema** — for interoperability.

### Calibration data (the actual moat)

Three Weeks projects the owner ran end-to-end provide the initial calibration set. For each project we need (and the owner has access to or can reconstruct):

- Pre- and post-dredge bathymetric surveys.
- The CAD design template.
- The geotechnical / boring data the project planned against.
- The actual production logs (DREDGEPACK output if available, daily reports if not).
- The actual weather records (NOAA + on-site).
- The actual equipment downtime log.
- The actual dollar P&L (used to validate the cost model, not exposed in the product).

Three projects is enough to fit the model parameters; we add more as the product encounters new geographies and dredge classes.

### Soil characterization input

Meridian Dredge does **not** generate soil characterization — it consumes it. Sources:

- **Vibracore + CPT logs** (geotechnical survey, AGS4 or operator-entered).
- **Sub-bottom profiler** (acoustic — JSF/Edgetech format — already on Meridian core's Phase E parser list).
- **Acoustic seabed classification** from multibeam backscatter (Hypack and CARIS do this; Meridian core's hydro module should do it too).
- **Operator-entered estimates** as fallback for jobs without good geotech.

The user provides characterization; the model consumes it. Hard line.

---

## 6. Phased build plan

The Dredge phasing runs *behind* Meridian core but starts early enough that it's not all delayed to 2030.

| Dredge phase | Calendar | Depends on Meridian core | Deliverable |
|---           |---       |---                       |---          |
| **D-0: Owner writes the requirements doc** | Now → 30 days | Nothing | The owner converts his $100M+ project experience into a written requirements doc covering: failure modes (Section 12), priority order, dredge-class scope (start CSD), data formats, calibration project list. Replaces "discovery calls." |
| **D-1: Layer 1 in Meridian core** | Coincides with Meridian Phase E (hydro) | Phase E hydro processing | Design-surface-vs-survey visualization in browser. **No UE5.** Door-opener and credibility signal at Weeks and elsewhere. |
| **D-2: UE5 prototype + Glassbox pane** | Months 6–12 | Layer 1 demo-able | Bare UE5 app with Cesium for Unreal terrain, one CSD model rigged in Blueprint, project bathymetry ingest from Meridian core, no engineering subsystem yet. **Plus** the Glassbox-class situational-awareness pane in the browser (multi-vessel spread tracking from AISHub, NOAA weather, NOAA CO-OPS tide, federal/state overlays). Two demos that together close the room. |
| **D-3: Engineering subsystem + calibration** | Months 12–24 | D-2 + owner pulls Weeks calibration data | Weather/downtime model, Miedema cutting model, Wilson slurry model, equipment reliability, deterministic fixed-step physics, production-rate calculator. **Calibrated against 3 historical Weeks projects the owner personally ran** — the proprietary moat. |
| **D-4: Forecast mode + first paid Weeks deployment** | Months 18–30 | D-3 | Monte Carlo driver, calibrated uncertainty bands, CFO-facing forecast report. **Sold to Weeks at commercial pricing.** Reference rights negotiated, not given away. |
| **D-5: Reconciliation mode + commercial expansion** | Months 24–36 | D-4 + Hypack/Trimble production-log adapter | Replay actual GPS + sensor logs against forecast; produce USACE-defensible production-deliverable report. Weeks deployment in production; expand to USACE districts and other contractors. |
| **D-6: Training mode** | Months 30–42 | D-5 | Operator-driven control of the dredge; performance scoring; multi-trainee networked sessions. Sold separately to training centers. |
| **D-7: Multi-dredge classes** | Months 36–48 | D-3 | Add TSHD, hopper, BHD, suction-only models. CSD was first because it's the most common in US East Coast / Gulf and Weeks runs them. |
| **D-8: Pixel streaming + commercial release** | Months 42–54 | All of the above | Polished release; pricing model; OEM partnerships. |

Note the calendar is honest. If you build Dredge "in the most efficient way possible" with serious engineering velocity and good Weeks input, **first commercial revenue is ~2.5 years out from start.** That's normal for B2B vertical-software with a real engineering core. Do not let anyone tell you it's six months.

---

## 7. Pricing model (working hypothesis, not final)

This is here so the build prioritization knows the eventual revenue shape:

- **Forecast/Reconciliation seat:** $24,000 / seat / year. Office tool for project engineers and PMs. Comparable to Hypack ($8K/seat) but bundles a real sim.
- **Training-center license:** $120,000 / year per concurrent-trainee station. Comparable to NAUTIS (~$200K) and IHC CSD-Sim (~$400K).
- **OEM bundling deal:** royalty-based, structured per-vessel, against a specific dredge-class implementation. IHC / Damen / Ellicott are the candidates.
- **USACE district subscription:** $60K / year / district. There are 38 USACE districts; coverage of even 10 is meaningful revenue.

A target of 50 forecast seats + 5 training centers + 1 OEM deal is a $2-3M/yr business at maturity, which justifies the team to build it. Weeks alone is plausibly 5–10 forecast seats + a training-center license if the product hits.

---

## 8. Open questions that need answers before D-2 starts

The ones from `HANDOFF.md` Section 7 still apply where they overlap. Dredge-specific (most are owner-decisions, not external research):

1. **CSD only for v1, or include TSHD/BHD?** Owner-decision based on Weeks fleet composition. Recommend CSD-only for v1 — Weeks runs CSDs for Atlantic / Gulf USACE work, and that's the calibration set. TSHD and BHD added per customer demand once the engine is proven.
2. **In-house engineering subsystem vs. wrap MB-System / Vortex / commercial physics SDK?** Recommend in-house from the published equations + owner's calibration data. Vortex is the right shape but its equations aren't tuned to dredging the way ours will be. The calibration is the moat — wrapping someone else's physics gives that away.
3. **Pixel Streaming for client demos in v1, or wait?** Recommend including in D-2 prototype because the demo *is* the sales motion. A surveyor walking into Weeks's NJ HQ with a laptop and a live sim is a different conversation than one who has to hand them an installer.
4. **Soil characterization ingest — what formats?** Owner-decision. AGS4 geotechnical data exchange? CPT digital logs (.cpt)? Sub-bottom imagery from JSF? Owner-entered estimates as fallback? Recommend all of them eventually; D-3 priority depends on what the calibration projects actually have digitized. Owner answers from his project file inventory.
5. **Royalty handling.** UE 5% royalty above $1M per-product-per-year is acceptable. Structure pricing through Licensee-tier negotiation rather than vanilla seat licenses to keep the royalty math clean.
6. **IP / company structure.** Meridian core and Meridian Dredge are different products and probably want different commercial structure (Meridian core could go open-core; Meridian Dredge stays proprietary because the calibrated engineering subsystem is the moat). Owner consults counsel before D-2.
7. **First-customer pricing.** The product is sold to Weeks at commercial pricing (not pilot pricing). Owner sets that price based on what the forecast feature is worth on a $100M+ project — recommend pricing it as a percentage of project value (e.g., 0.05% of TIC) rather than per-seat for the early commercial deals, with seat-licensing as the standardized model later.

---

## 9. Risks (be honest)

- **Engineering quality risk.** If the production-rate output isn't credible, Weeks won't pay for it and the whole product is dead. Mitigation: owner is the dredge engineer of record. Calibrate against three projects he personally ran before D-4 ships. Recruit a second domain expert as the calibration set expands beyond his direct experience.
- **Schedule risk.** UE5 + a full engineering subsystem + multiple dredge classes is genuinely 3-4 years of focused work. Mitigation: customer-funded development from D-3 onward — Weeks contract pays for the engineer who calibrates the model.
- **Market timing risk.** USACE deliverables mandate could shift; BIL/IRA dollars could throttle. Mitigation: design for general dredging-industry buyer, not USACE-only.
- **Cesium / Epic dependency risk.** Both are healthy companies but we're betting on their continued maintenance. Mitigation: architect Cesium for Unreal as a swappable terrain provider so a hypothetical migration to a different geospatial-in-Unreal layer is contained to one module.
- **Hypack / Trimble interoperability risk.** If they make their data formats hostile, the reconciliation feature suffers. Mitigation: own the data ourselves — Meridian core's **Phase J** (`HANDOFF.md`) replaces Hypack on the dredge bridge so we eventually consume our own data, not theirs.
- **OT / cyber risk.** Once Meridian Dredge talks to dredge sensors over the vessel network, it's an OT system exposed to NMEA 2000 / OneNet / Ethernet network risks. USCG 33 CFR Subchapter H cyber regs (NPRM 2025, expected effective ~2027) are coming. Mitigation: design with OT/IT segmentation, signed updates, and audit logging from the first vessel-side feature.
- **AIS data scaling cost.** Spire Maritime for full Atlantic + Gulf coverage is real money. Mitigation: ship free AISHub by default; bundle paid only when a customer requests offshore coverage and pays the premium.

---

## 10. First 90 days

The owner already has the customer relationship and the domain expertise. The first-90-days work is therefore **converting that into written, durable assets a software team can build against** — not collecting it from third parties.

1. **Write the failure-mode-prioritized requirements doc.** Section 12 of this plan is the skeleton; the owner fills it in from his project experience. ~2 weeks of focused writing.
2. **Pull calibration data from three Weeks projects.** Pre/post bathymetry, design template, geotech, production logs, weather records, downtime log, P&L. Get owner clearance to use the data (or anonymized versions). ~2 weeks of data archaeology + permissions.
3. **Author the dredge-class scope decision.** v0.1 is CSD-only. Owner writes a short doc explaining why, what TSHD/BHD adds, and the Weeks fleet composition that the priority is calibrated against.
4. **Stand up the UE5 + Cesium for Unreal "Hello World."** Empty scene with terrain + bathymetry from one of the calibration projects. Goal is to confirm the toolchain works end-to-end before serious investment. ~1 week with a competent UE5 dev.
5. **Prototype Layer 1 in Meridian core** (this is in-scope for `HANDOFF.md` Phase E; bump it forward in the queue). Demo-able by end of 90 days.
6. **Pricing + commercial structure decision.** Owner consults counsel on (a) Meridian core open-core vs proprietary, (b) Meridian Dredge proprietary, (c) the right entity to license to Weeks under, (d) IP separation between the two products.
7. **Recruit / contract decision.** UE5 development requires C++/Blueprint expertise the owner doesn't have. Decision: hire a UE5 engineer as employee #1, or contract through a UE5 studio for D-2 + D-3, or learn it personally. Each has different cost, control, and IP implications.

By day 90, the requirements doc + the calibration data + the toolchain prototype + Layer 1 demo + the commercial structure exist. That's the launch pad for D-2.

---

## 11. Failure-mode priority — the spine of the product

The owner's $100M+ project experience produced a ranked list of what actually breaks dredge project budgets. **The product is built in this order because that's the order the customer's pain is in.** This supersedes the "soil first because it's most engineering-y" instinct that academic dredging textbooks would default to.

### Priority 1 — Weather + downtime (Atlantic + Gulf jobs especially)

The biggest budget killer on East-Coast and Gulf dredge projects is weather. Sea state, hurricane prep, fog, lightning, and unanticipated heavy-weather posture days. The model has to:

- Carry **historical weather priors per geography + season** as a first-class input. NOAA buoy data, hurricane-track climatology, fog-frequency maps. Not a generic Beaufort-scale assumption.
- Distinguish **billable downtime vs. at-risk downtime** in the forecast — contractually, who eats the day matters. The CFO report needs to break the forecast into "weather days the contract pays for" vs. "weather days that come out of margin."
- Model **hurricane-prep posture** — pulling pipe, releasing anchors, getting the dredge to safe harbor. That's typically 36–72 hours of zero production per hurricane warning. The probability of triggering it during the project window is computable from NHC climatology.
- Flag **seasonal restrictions** — turtle windows, fish spawning, beach-nourishment season — that hard-cap when dredging can happen.

This is the single most important feature in the product. Without it, the forecast is decorative.

### Priority 2 — Soil surprises + uncertainty propagation

Boring logs are sparse and frequently wrong. The actual seabed is often harder, softer, or more variable than what the project planned against. The model has to:

- Carry **probabilistic soil characterization** — each region of the cut volume has a distribution over soil class, not a single value.
- Propagate that uncertainty through the production model so the forecast comes out as a distribution, not a point estimate.
- Update the soil prior **as the dredge actually cuts** — the first week of production tells you a lot about whether the boring logs were right.
- Flag specific surprise types the owner has personally encountered: cobble layers below sand, undocumented debris (cables, anchors, abandoned pipe), clay lenses that gum up the cutter, hardpan refusal.

### Priority 3 — Equipment / pipeline failures

Mechanical reliability is real and modelable from manufacturer + maintenance records. The model needs:

- **Reliability priors per dredge class + age + maintenance history** for major systems (main pump, booster pumps, cutter motor, swing winches, spuds, ladder hydraulics).
- **Pipeline failure probability** as a function of length, age, soil abrasiveness, and slurry density.
- **Cutter-tooth wear** as a function of cumulative material removed and abrasiveness.
- **Maintenance-cycle simulator** — scheduled service days vs. unscheduled.

### Priority 3.5 — Regulatory + environmental compliance (the things that stop a project, not slow it)

These don't show production-rate impact in the model — they show as **hard stops**: turtle deflector dragheads on TSHDs, marine mammal observation requirements, turbidity monitoring thresholds, daily DMR (Discharge Monitoring Report) reporting, USACE coordination notices, environmental seasonal windows. Missing one of these doesn't slow the dredge; it shuts it down. The model has to:

- Track regulatory obligations as scheduled events tied to the project window (turtle window for SE coast March-November, North Atlantic right whale slow-zones, etc.).
- Surface them in the Glassbox pane and the forecast model as binary go/no-go gates.
- Generate the contractor's required deliverables (DMRs, observation logs, turbidity readings) so the contractor isn't paying a separate compliance team to keep up.

This is "boring software" but it's revenue-protecting for the contractor and a real differentiator vs. tools that ignore it.

### Priority 4 — Discharge / material handling

The post-cutter side of the operation. Production is capped by whichever is slower — what the cutter can remove or what the pipe can carry. The model has to:

- Implement the **slurry hydraulics** correctly (Wilson + Addie & Sellgren are the references). Pump curves, pipe friction, deposition velocity, solids concentration.
- Model **booster pump placement** as an optimization variable for long discharge runs.
- Model **beach discharge management** for nourishment projects (where the placement geometry, not the cut, is the critical path).
- Model **hopper turnaround** for TSHD work (when that dredge class is added).

### How priority drives feature sequencing

D-3 (engineering subsystem) implements these in priority order. Weather + downtime ships first because that's the feature that sells the product. Soil uncertainty ships second because it's what makes the forecast credible. Equipment reliability ships third. Material handling ships fourth and rounds out the model. **Each priority adds calibrated value; none of them gets shipped half-done.**

---

## 12. Sources

- IADC website + 2025 conference proceedings (production-reporting standards in development).
- USACE EM 1110-2-1003 + 2024 update tracker.
- Hypack DREDGEPACK product documentation (publicly available).
- Royal IHC CSD-Sim product page; IHC training-center capability statements.
- Cesium for Unreal documentation + Cesium ion pricing 2026.
- Epic Games UE5 EULA + royalty terms 2026.
- Miedema, *Delft Sand, Clay and Rock Cutting Model* (TU Delft, open access).
- Bray, Bates & Land, *Dredging: A Handbook for Engineers* (2nd ed., Wiley).
- Randall, *Dredging Engineering* coursework (Texas A&M).
- Vlasblom CSD/TSHD lecture series (TU Delft, public).
- Wilson, Addie, Sellgren & Clift, *Slurry Transport Using Centrifugal Pumps* (Springer).
- Owner background (Weeks Marine alumnus, currently practicing licensed surveyor in NC).
- Owner conversation, 2026-05-07 (this session).
