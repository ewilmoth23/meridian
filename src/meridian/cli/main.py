"""Top-level Typer CLI entry point.

Run ``meridian --help`` after installing.
"""

from __future__ import annotations

import math
from pathlib import Path

import typer
from rich.console import Console
from rich.table import Table

from meridian import __version__

app = typer.Typer(
    name="meridian",
    help="Meridian — the modern surveyor's suite. Where every line is true.",
    no_args_is_help=True,
    add_completion=False,
)
deed_app = typer.Typer(name="deed", help="Deed parsing and drawing generation.")
network_app = typer.Typer(name="network", help="Control-network least-squares adjustment.")
traverse_app = typer.Typer(name="traverse", help="Total-station traverse processing.")
cloud_app = typer.Typer(name="cloud", help="Point-cloud classification and surfacing.")
plugins_app = typer.Typer(name="plugins", help="Plugin discovery and listing.")
truthchain_app = typer.Typer(name="truthchain", help="Signed-observation provenance (TruthChain).")
atlas_app = typer.Typer(name="atlas", help="3D globe viewer (Cesium-backed).")
certificate_app = typer.Typer(name="certificate", help="Generate signable survey certificates.")
field_app = typer.Typer(name="field", help="Field-data → CAD-feature pipelines.")
app.add_typer(deed_app)
app.add_typer(network_app)
app.add_typer(traverse_app)
app.add_typer(cloud_app)
app.add_typer(plugins_app)
app.add_typer(truthchain_app)
app.add_typer(atlas_app)
app.add_typer(certificate_app)
app.add_typer(field_app)

console = Console()


@app.callback(invoke_without_command=True)
def _root(
    ctx: typer.Context,
    version: bool = typer.Option(False, "--version", help="Print version and exit."),
) -> None:
    if version:
        typer.echo(f"meridian {__version__}")
        raise typer.Exit()


# ── deed ───────────────────────────────────────────────────────────────────


@deed_app.command("parse")
def deed_parse(
    input_path: Path = typer.Argument(..., exists=True, readable=True, help="Path to a deed text file."),
    out_dxf: Path | None = typer.Option(None, "--out", "-o", help="DXF output path."),
    out_pdf: Path | None = typer.Option(None, "--report", "-r", help="PDF report path."),
    epsg: int = typer.Option(2277, "--epsg", help="CRS EPSG code (default Texas State Plane Central US ft)."),
    start_x: float = typer.Option(0.0, "--start-x", help="POB X coordinate."),
    start_y: float = typer.Option(0.0, "--start-y", help="POB Y coordinate."),
    parcel_name: str = typer.Option("Parcel A", "--name"),
    surveyor: str = typer.Option("", "--surveyor"),
    client: str = typer.Option("", "--client"),
) -> None:
    """Parse a deed text file into a DXF and (optionally) a PDF report."""
    from meridian.domain.crs import CRS
    from meridian.services.deed_service import DeedService

    crs = CRS(epsg=epsg)
    text = input_path.read_text(encoding="utf-8", errors="replace")
    result = DeedService().parse_to_cad(
        text=text,
        crs=crs,
        starting_point=(start_x, start_y),
        parcel_name=parcel_name,
        dxf_path=out_dxf,
        pdf_path=out_pdf,
        surveyor=surveyor,
        client=client,
    )
    table = Table(title=f"Deed parsed: {parcel_name}")
    table.add_column("Field", style="bold")
    table.add_column("Value")
    table.add_row("Calls", str(len(result.parcel.calls)))
    table.add_row("Misclosure (m)", f"{result.misclosure_m:.4f}")
    ratio = "∞" if math.isinf(result.closure_ratio) else f"1:{result.closure_ratio:,.0f}"
    table.add_row("Closure ratio", ratio)
    if out_dxf:
        table.add_row("DXF", str(out_dxf))
    if out_pdf:
        table.add_row("PDF", str(out_pdf))
    console.print(table)


# ── network ────────────────────────────────────────────────────────────────


@network_app.command("adjust")
def network_adjust(
    spec_json: Path = typer.Argument(..., exists=True, readable=True, help="Path to a network spec JSON."),
    epsg: int = typer.Option(2277, "--epsg"),
    out_pdf: Path | None = typer.Option(None, "--report", "-r"),
    constraint_mode: str = typer.Option(
        "auto",
        "--constraint-mode",
        "-c",
        help="auto | minimal | partial | full | free. 'auto' = partial when 2+ pts are fixed else minimal.",
    ),
) -> None:
    """Adjust a control network defined in a small JSON spec.

    Spec format:
    ```
    {"points": [{"id": "P1", "x": 0, "y": 0, "z": 0, "fixed": true}, ...],
     "observations": [{"setup_id": "S1", "kind": "horizontal_distance",
                        "from_point": "P1", "to_point": "P2", "value": 10.0,
                        "sigma": 0.005, "id": "obs1"}, ...],
     "constraint_mode": "partial"  # optional; CLI flag wins if both supplied
    }
    ```
    """
    import json

    from meridian.domain.crs import CRS
    from meridian.domain.geometry import Point3D
    from meridian.domain.network import ConstraintMode, ControlPoint, MonumentType
    from meridian.domain.observation import ObservationKind, RawObservation
    from meridian.services.network_service import NetworkService

    spec = json.loads(spec_json.read_text())
    crs = CRS(epsg=epsg)
    points = [
        ControlPoint(
            id=p["id"],
            a_priori=Point3D(x=p["x"], y=p["y"], z=p.get("z", 0.0), crs=crs, name=p["id"]),
            fixed=bool(p.get("fixed", False)),
            monument=MonumentType(p.get("monument", "undefined")),
        )
        for p in spec["points"]
    ]
    observations = [
        RawObservation(
            id=o["id"],
            setup_id=o["setup_id"],
            kind=ObservationKind(o["kind"]),
            from_point=o["from_point"],
            to_point=o.get("to_point"),
            value=o.get("value"),
            vector=tuple(o["vector"]) if o.get("vector") else None,
            sigma=o.get("sigma"),
        )
        for o in spec["observations"]
    ]

    # Resolve constraint mode: CLI flag wins, then spec, then auto-pick.
    mode_str = constraint_mode if constraint_mode != "auto" else spec.get("constraint_mode", "auto")
    if mode_str == "auto":
        n_fixed = sum(1 for p in points if p.fixed)
        chosen = ConstraintMode.PARTIAL if n_fixed >= 2 else ConstraintMode.MINIMAL
    else:
        chosen = ConstraintMode(mode_str)

    result = NetworkService().adjust_network(
        name=spec.get("name", "network"),
        crs=crs,
        points=points,
        observations=observations,
        constraint_mode=chosen,
        pdf_path=out_pdf,
    )
    table = Table(title="Network adjustment")
    table.add_column("Field", style="bold")
    table.add_column("Value")
    table.add_row("Iterations", str(result.adjustment.iterations))
    table.add_row("Converged", str(result.adjustment.converged))
    table.add_row("σ₀", f"{result.adjustment.sigma0:.6f}")
    table.add_row("χ² passes", str(result.adjustment.chi_square_passed))
    if out_pdf:
        table.add_row("PDF", str(out_pdf))
    console.print(table)
    pts = Table(title="Adjusted points")
    pts.add_column("Point")
    pts.add_column("X")
    pts.add_column("Y")
    pts.add_column("Z")
    for pid, p in result.adjustment.adjusted_points.items():
        pts.add_row(pid, f"{p.x:.4f}", f"{p.y:.4f}", f"{p.z:.4f}")
    console.print(pts)


# ── traverse ───────────────────────────────────────────────────────────────


@traverse_app.command("run")
def traverse_run(
    raw_file: Path = typer.Argument(..., exists=True, readable=True),
    start: str = typer.Option("0,0", "--start", help="POB as 'x,y' in CRS units."),
    method: str = typer.Option("compass", "--method", help="compass | transit | least_squares"),
) -> None:
    """Run a closed traverse from a Leica GSI / Trimble JXL / TDS RW5 file."""
    from meridian.services.traverse_service import TraverseService

    sx, sy = (float(v) for v in start.split(","))
    res = TraverseService().run_from_file(raw_file, starting_point=(sx, sy), method=method)
    table = Table(title=f"Traverse: {raw_file.name}")
    table.add_column("Field", style="bold")
    table.add_column("Value")
    table.add_row("Driver", res.driver)
    table.add_row("Setups", str(res.setups_count))
    table.add_row("Observations", str(res.observations_count))
    table.add_row("Legs", str(res.legs_count))
    table.add_row("Closure (m)", f"{res.result.closure_distance:.4f}")
    ratio = "∞" if math.isinf(res.result.closure_ratio) else f"1:{res.result.closure_ratio:,.0f}"
    table.add_row("Closure ratio", ratio)
    table.add_row("Perimeter (m)", f"{res.result.perimeter:,.3f}")
    table.add_row("Area (m²)", f"{res.result.area:,.3f}")
    table.add_row("Method", res.result.method)
    console.print(table)
    if res.warnings:
        console.print(f"[yellow]{len(res.warnings)} warnings — first: {res.warnings[0]}[/yellow]")


# ── cloud ──────────────────────────────────────────────────────────────────


@cloud_app.command("contours")
def cloud_contours(
    input_path: Path = typer.Argument(..., exists=True, readable=True, help="LAS/LAZ input."),
    out_dxf: Path = typer.Option(..., "--out", "-o", help="DXF output for contours."),
    interval: float = typer.Option(1.0, "--interval", help="Contour interval (CRS units)."),
    index_every: int = typer.Option(5, "--index-every"),
    classified_out: Path | None = typer.Option(None, "--classified-out"),
) -> None:
    """Classify ground in a LAS/LAZ, build a TIN, and write contours to DXF."""
    from meridian.pipelines.pointcloud_classify import PointCloudPipelineOptions
    from meridian.services.pointcloud_service import PointCloudService

    opts = PointCloudPipelineOptions(
        contour_interval_m=interval, contour_index_every=index_every
    )
    res = PointCloudService().classify_to_contours(
        input_path, contour_dxf_path=out_dxf, classified_path=classified_out, options=opts
    )
    table = Table(title=f"Cloud → contours: {input_path.name}")
    table.add_column("Field", style="bold")
    table.add_column("Value")
    table.add_row("Ground points", f"{res.ground_point_count:,}")
    table.add_row("TIN triangles", f"{res.surface.tin.triangle_count:,}")
    table.add_row("Contour intervals", f"{len(res.surface.contours):,}")
    table.add_row("Classified LAS", str(res.classified_path))
    table.add_row("Contour DXF", str(out_dxf))
    console.print(table)


# ── plugins ────────────────────────────────────────────────────────────────


@plugins_app.command("list")
def plugins_list() -> None:
    """Print all discovered plugins."""
    from meridian.plugins.discovery import get_registry

    reg = get_registry()
    for label, group in (
        ("Instruments", reg.instruments),
        ("Importers", reg.importers),
        ("Exporters", reg.exporters),
        ("Jurisdictions", reg.jurisdictions),
        ("AI providers", reg.ai_providers),
    ):
        table = Table(title=label)
        table.add_column("Short id")
        table.add_column("Class")
        table.add_column("Name")
        for short_id, plugin in sorted(group.items()):
            table.add_row(short_id, type(plugin).__name__, getattr(plugin, "name", ""))
        console.print(table)


# ── truthchain ─────────────────────────────────────────────────────────────


@truthchain_app.command("keygen")
def truthchain_keygen(
    name: str = typer.Argument(..., help="Identifier for the new keypair (becomes <name>.pem)."),
    surveyor_name: str = typer.Option(..., "--surveyor"),
    license_state: str = typer.Option("", "--state"),
    license_number: str = typer.Option("", "--license"),
    passphrase: str = typer.Option("", "--passphrase", help="Optional passphrase to encrypt the private key."),
) -> None:
    """Generate an Ed25519 keypair and persist it to the per-user keystore."""
    import datetime as dt

    from meridian.truthchain import (
        SignedIdentity,
        generate_keypair,
        save_keypair,
        serialize_public,
    )
    from meridian.truthchain.keystore import b64

    sk, pk = generate_keypair()
    pp = passphrase.encode("utf-8") if passphrase else None
    path = save_keypair(name, sk, passphrase=pp)
    identity = SignedIdentity(
        surveyor_name=surveyor_name,
        license_state=license_state,
        license_number=license_number,
        public_key_b64=b64(serialize_public(pk)),
        issued_at=dt.datetime.now(dt.UTC).isoformat(timespec="microseconds"),
    )
    sidecar = path.with_suffix(".identity.json")
    sidecar.write_text(identity.to_json(), encoding="utf-8")
    table = Table(title=f"Generated keypair: {name}")
    table.add_column("Field", style="bold")
    table.add_column("Value")
    table.add_row("Private key", str(path))
    table.add_row("Identity", str(sidecar))
    table.add_row("Public key (b64)", identity.public_key_b64)
    console.print(table)


@truthchain_app.command("verify")
def truthchain_verify(
    attestation_path: Path = typer.Argument(..., exists=True, readable=True),
    manifest_dir: Path = typer.Argument(..., exists=True, file_okay=False, dir_okay=True),
) -> None:
    """Verify a deliverable's attestation against its manifests."""
    from meridian.truthchain import (
        AdjustmentChainAttestation,
        load_manifests_from_dir,
        verify_deliverable,
    )

    attestation = AdjustmentChainAttestation.from_json(attestation_path.read_text())
    manifests = load_manifests_from_dir(manifest_dir)
    report = verify_deliverable(attestation=attestation, manifests=manifests)
    color = "green" if report.overall_ok else "red"
    console.print(f"[{color}]{report.summary()}[/{color}]")
    table = Table(title="Verification details")
    table.add_column("Check", style="bold")
    table.add_column("Status")
    table.add_row("Manifests inspected", str(report.manifest_count))
    table.add_row("Signatures valid", "PASS" if report.manifest_signatures_ok else "FAIL")
    table.add_row("Merkle root matches", "PASS" if report.merkle_root_ok else "FAIL")
    console.print(table)
    if report.issues:
        for issue in report.issues:
            console.print(f"[red]✗ {issue}[/red]")
    raise typer.Exit(code=0 if report.overall_ok else 1)


# ── atlas ──────────────────────────────────────────────────────────────────


@atlas_app.command("serve")
def atlas_serve(
    host: str = typer.Option("127.0.0.1", "--host"),
    port: int = typer.Option(8765, "--port"),
    ion_token: str = typer.Option(
        "",
        "--ion-token",
        help="Cesium ion access token. Falls back to MERIDIAN_ION_TOKEN env "
        "or the saved atlas config.",
    ),
    google_maps_key: str = typer.Option("", "--google-maps-key"),
    save: bool = typer.Option(
        False,
        "--save",
        help="Persist any tokens passed on this invocation to the user config "
        "(so future runs don't need them).",
    ),
) -> None:
    """Serve the Atlas 3D globe at http://HOST:PORT/atlas/.

    Press Ctrl-C to stop. Open the URL in a browser to see the globe.
    With no project DB attached, demo mode shows a sample parcel near
    downtown Austin.
    """
    import time

    from meridian.atlas import create_app, launch_tile_service
    from meridian.atlas.config import (
        AtlasConfig,
        load_atlas_config,
        resolve_google_maps_key,
        resolve_ion_token,
        save_atlas_config,
    )

    resolved_ion = resolve_ion_token(ion_token)
    resolved_gmaps = resolve_google_maps_key(google_maps_key)

    if save and (ion_token.strip() or google_maps_key.strip()):
        existing = load_atlas_config()
        new_cfg = AtlasConfig(
            ion_token=resolved_ion or existing.ion_token,
            google_maps_key=resolved_gmaps or existing.google_maps_key,
        )
        path = save_atlas_config(new_cfg)
        console.print(f"[dim]Tokens saved to {path}[/dim]")

    app_inst = create_app(
        cesium_ion_token=resolved_ion,
        google_maps_key=resolved_gmaps,
    )
    handle = launch_tile_service(app_inst, host=host, port=port)
    if resolved_ion:
        console.print("[dim]Cesium Ion token: configured ✓[/dim]")
    else:
        console.print(
            "[yellow]No Cesium Ion token set — falling back to OSM/ESRI imagery.[/yellow]\n"
            "[dim]Run 'meridian atlas configure --ion-token <TOKEN>' to enable Ion (terrain, Bing aerial, geocoder).[/dim]"
        )
    console.print(f"[bold green]Atlas globe live at[/bold green] {handle.viewer_url}")
    console.print("Press Ctrl-C to stop.")
    try:
        while True:
            time.sleep(60)
    except KeyboardInterrupt:
        console.print("\n[yellow]Stopped.[/yellow]")


@atlas_app.command("configure")
def atlas_configure(
    ion_token: str = typer.Option("", "--ion-token", help="Cesium ion access token to persist."),
    google_maps_key: str = typer.Option("", "--google-maps-key", help="Google Maps API key to persist."),
    show: bool = typer.Option(False, "--show", help="Print the current persisted config and exit."),
    clear: bool = typer.Option(False, "--clear", help="Wipe the persisted config and exit."),
) -> None:
    """Persist atlas configuration (Cesium Ion token, Google Maps key)."""
    from meridian.atlas.config import (
        AtlasConfig,
        _config_path,
        load_atlas_config,
        save_atlas_config,
    )

    path = _config_path()

    if clear:
        if path.exists():
            path.unlink()
            console.print(f"[yellow]Cleared {path}[/yellow]")
        else:
            console.print("[dim]No saved config to clear.[/dim]")
        return

    current = load_atlas_config()
    if show:
        console.print(f"[bold]Atlas config:[/bold] {path}")
        console.print(f"  ion_token:       {_mask(current.ion_token)}")
        console.print(f"  google_maps_key: {_mask(current.google_maps_key)}")
        return

    new_cfg = AtlasConfig(
        ion_token=(ion_token.strip() or None) if ion_token else current.ion_token,
        google_maps_key=(google_maps_key.strip() or None) if google_maps_key else current.google_maps_key,
    )
    written = save_atlas_config(new_cfg)
    console.print(f"[green]Saved[/green] {written}")
    console.print(f"  ion_token:       {_mask(new_cfg.ion_token)}")
    console.print(f"  google_maps_key: {_mask(new_cfg.google_maps_key)}")


def _mask(value: str | None) -> str:
    if not value:
        return "[dim](unset)[/dim]"
    if len(value) <= 12:
        return "•" * len(value)
    return f"{value[:6]}…{value[-4:]} ({len(value)} chars)"


# ── certificate ────────────────────────────────────────────────────────────


def _read_legal_description(legal: str | None, legal_file: Path | None) -> str:
    if legal_file is not None:
        return legal_file.read_text(encoding="utf-8").strip()
    if legal is not None:
        return legal
    raise typer.BadParameter("Provide either --legal or --legal-file.")


def _emit_certificate(cert, *, out_html: Path | None, out_text: Path | None) -> None:
    from meridian.jurisdictions.survey_certificate import (
        render_html as _render_html,
    )
    from meridian.jurisdictions.survey_certificate import (
        render_text as _render_text,
    )
    from meridian.jurisdictions.survey_certificate import (
        validate_certificate as _validate,
    )

    issues = _validate(cert)
    for issue in issues:
        color = "red" if issue.severity == "error" else "yellow"
        console.print(f"[{color}]{issue.severity.upper()}[/{color}] {issue.message}")

    if out_html is None and out_text is None:
        # Nothing to write; print text to stdout for piping.
        typer.echo(_render_text(cert))
        return

    if out_html is not None:
        out_html.parent.mkdir(parents=True, exist_ok=True)
        out_html.write_text(_render_html(cert), encoding="utf-8")
        console.print(f"[green]Wrote[/green] {out_html}")
    if out_text is not None:
        out_text.parent.mkdir(parents=True, exist_ok=True)
        out_text.write_text(_render_text(cert), encoding="utf-8")
        console.print(f"[green]Wrote[/green] {out_text}")

    if any(i.severity == "error" for i in issues):
        raise typer.Exit(code=2)


@certificate_app.command("alta")
def certificate_alta(
    surveyor_name: str = typer.Option(..., "--surveyor", help="Surveyor's full name."),
    license_state: str = typer.Option(..., "--license-state", help="2-letter state code where surveyor is licensed."),
    license_number: str = typer.Option(..., "--license-number"),
    project_name: str = typer.Option(..., "--project", help="Project / job name."),
    state: str = typer.Option(..., "--state", help="2-letter state code where the property is located."),
    survey_date: str = typer.Option(..., "--survey-date", help="ISO date the survey was performed (YYYY-MM-DD)."),
    legal: str | None = typer.Option(None, "--legal", help="Legal description text (or use --legal-file)."),
    legal_file: Path | None = typer.Option(None, "--legal-file", exists=True, readable=True),
    table_a: str = typer.Option("", "--table-a", help="Comma-separated Table A keys to certify (e.g. '1,3,4,6a,11')."),
    accuracy: str = typer.Option("urban", "--accuracy", help="ALTA positional accuracy class: urban|suburban|rural|mountain_marsh."),
    issue_date: str | None = typer.Option(None, "--issue-date", help="ISO issue date; defaults to today."),
    out_html: Path | None = typer.Option(None, "--html", help="Write HTML certificate to this path."),
    out_text: Path | None = typer.Option(None, "--text", help="Write plain-text certificate to this path."),
    business_name: str | None = typer.Option(None, "--business"),
) -> None:
    """Generate an ALTA/NSPS 2021 Land Title Survey certificate."""
    from meridian.jurisdictions.survey_certificate import (
        SurveyAccuracyClass,
        SurveyorIdentity,
        SurveyProject,
        build_alta_certificate,
    )

    s = SurveyorIdentity(
        name=surveyor_name,
        license_state=license_state,
        license_number=license_number,
        business_name=business_name,
    )
    p = SurveyProject(
        project_name=project_name,
        legal_description=_read_legal_description(legal, legal_file),
        state=state,
        survey_date=_parse_iso_date(survey_date),
    )
    keys = [k.strip() for k in table_a.split(",") if k.strip()]
    try:
        cls = SurveyAccuracyClass(accuracy)
    except ValueError as exc:
        raise typer.BadParameter(f"Unknown --accuracy: {accuracy!r}") from exc
    cert = build_alta_certificate(
        surveyor=s, project=p, table_a_keys=keys, accuracy_class=cls,
        issue_date=_parse_iso_date(issue_date) if issue_date else None,
    )
    _emit_certificate(cert, out_html=out_html, out_text=out_text)


@certificate_app.command("boundary")
def certificate_boundary(
    surveyor_name: str = typer.Option(..., "--surveyor"),
    license_state: str = typer.Option(..., "--license-state"),
    license_number: str = typer.Option(..., "--license-number"),
    project_name: str = typer.Option(..., "--project"),
    state: str = typer.Option(..., "--state"),
    survey_date: str = typer.Option(..., "--survey-date"),
    legal: str | None = typer.Option(None, "--legal"),
    legal_file: Path | None = typer.Option(None, "--legal-file", exists=True, readable=True),
    issue_date: str | None = typer.Option(None, "--issue-date"),
    out_html: Path | None = typer.Option(None, "--html"),
    out_text: Path | None = typer.Option(None, "--text"),
    business_name: str | None = typer.Option(None, "--business"),
) -> None:
    """Generate a boundary-survey certificate."""
    from meridian.jurisdictions.survey_certificate import (
        SurveyorIdentity,
        SurveyProject,
        build_boundary_certificate,
    )

    s = SurveyorIdentity(
        name=surveyor_name,
        license_state=license_state,
        license_number=license_number,
        business_name=business_name,
    )
    p = SurveyProject(
        project_name=project_name,
        legal_description=_read_legal_description(legal, legal_file),
        state=state,
        survey_date=_parse_iso_date(survey_date),
    )
    cert = build_boundary_certificate(
        surveyor=s, project=p,
        issue_date=_parse_iso_date(issue_date) if issue_date else None,
    )
    _emit_certificate(cert, out_html=out_html, out_text=out_text)


@certificate_app.command("states")
def certificate_states() -> None:
    """List the states with built-in statutory templates."""
    from meridian.jurisdictions.survey_certificate import STATE_TEMPLATES

    table = Table(title="Built-in survey-certificate state templates")
    table.add_column("State", style="bold")
    table.add_column("Name")
    table.add_column("Citation")
    for code in sorted(STATE_TEMPLATES):
        t = STATE_TEMPLATES[code]
        table.add_row(code, t.state_full, t.citation)
    console.print(table)
    console.print(
        "[dim]Other states fall back to a generic template — usable, but the "
        "citation must be filled in by the surveyor before signing.[/dim]"
    )


@certificate_app.command("table-a")
def certificate_table_a() -> None:
    """List ALTA/NSPS 2021 Table A items the generator knows about."""
    from meridian.jurisdictions.survey_certificate import alta_table_a_catalog

    table = Table(title="ALTA/NSPS 2021 Table A catalog")
    table.add_column("Key", style="bold")
    table.add_column("Label")
    table.add_column("Description")
    for item in alta_table_a_catalog():
        table.add_row(item.key, item.short_label, item.description)
    console.print(table)


def _parse_iso_date(value: str):
    import datetime as _dt

    try:
        return _dt.date.fromisoformat(value)
    except ValueError as exc:
        raise typer.BadParameter(f"Expected ISO date YYYY-MM-DD, got {value!r}.") from exc


# ── field codes ────────────────────────────────────────────────────────────


@field_app.command("codes")
def field_codes(
    pnezd: Path = typer.Argument(..., exists=True, readable=True, help="PNEZD file (Point#, Northing, Easting, Z, Code)."),
    epsg: int = typer.Option(2277, "--epsg", help="CRS EPSG code for the coordinates."),
    two_d: bool = typer.Option(False, "--2d", help="Treat the file as 2D (ignore Z)."),
) -> None:
    """Parse a PNEZD field-code file and print the derived CAD features.

    Group consecutive same-code shots into polylines, route each feature to
    the right CAD layer per the standard codebook, and detect curve segments
    via BC/EC markers.
    """
    from meridian.domain.crs import CRS
    from meridian.pipelines.field_codes import build_features, parse_pnezd

    crs = CRS(epsg=epsg)
    text = pnezd.read_text(encoding="utf-8")
    points = parse_pnezd(text, crs=crs, two_d_only=two_d)
    features = build_features(points)

    table = Table(title=f"Features from {pnezd.name} ({len(points)} points → {len(features)} features)")
    table.add_column("Code", style="bold")
    table.add_column("#", justify="right")
    table.add_column("Kind")
    table.add_column("Layer")
    table.add_column("Pts", justify="right")
    table.add_column("Description")
    for f in features:
        fnum = "" if f.feature_number is None else str(f.feature_number)
        table.add_row(f.code, fnum, f.kind.value, f.layer, str(len(f.points)), f.description)
    console.print(table)


@field_app.command("codebook")
def field_codebook() -> None:
    """List the standard codebook (canonical codes + their CAD routing)."""
    from meridian.pipelines.field_codes import STANDARD_CODEBOOK, CodeKind

    table = Table(title="Standard field codebook")
    table.add_column("Code", style="bold")
    table.add_column("Kind")
    table.add_column("Layer")
    table.add_column("Description")
    items = sorted(STANDARD_CODEBOOK.definitions.values(), key=lambda d: (d.kind.value, d.code))
    for defn in items:
        if defn.kind is CodeKind.IGNORE:
            continue
        table.add_row(defn.code, defn.kind.value, defn.layer, defn.description)
    console.print(table)


if __name__ == "__main__":  # pragma: no cover
    app()
