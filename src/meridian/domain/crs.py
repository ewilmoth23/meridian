"""Coordinate reference system entities.

Meridian treats CRS as a first-class citizen. **Every** coordinate-bearing
entity carries a CRS. There is no "default" or "implicit" CRS anywhere in
the domain. Conversions between CRSs are performed by
:mod:`meridian.math.transforms`, never silently.

A :class:`CRS` is identified by an EPSG code or a WKT string. We do not
store ``pyproj.CRS`` objects directly on domain entities — adapters that
need them resolve via :func:`CRS.to_pyproj`.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class HorizontalAxis(str, Enum):
    """How horizontal coordinates are stored on a :class:`CRS`."""

    EAST_NORTH = "east_north"  # x = easting / longitude, y = northing / latitude
    LON_LAT = "lon_lat"        # explicit geographic ordering
    LAT_LON = "lat_lon"        # GIS-traditional but rarely correct


class LinearUnit(str, Enum):
    """Linear unit for projected coordinates."""

    METER = "m"
    US_SURVEY_FOOT = "us_ft"
    INTERNATIONAL_FOOT = "ift"

    @property
    def to_meter(self) -> float:
        if self is LinearUnit.METER:
            return 1.0
        if self is LinearUnit.US_SURVEY_FOOT:
            return 1200.0 / 3937.0
        if self is LinearUnit.INTERNATIONAL_FOOT:
            return 0.3048
        raise ValueError(f"Unknown linear unit: {self!r}")  # pragma: no cover


@dataclass(frozen=True, slots=True)
class Datum:
    """A horizontal datum (WGS84, NAD83, NAD27, ITRF*, ...).

    The ``realization`` distinguishes e.g. ``NAD83(2011)`` from ``NAD83(1986)``.
    """

    name: str
    realization: str | None = None
    epsg: int | None = None

    def label(self) -> str:
        return f"{self.name}({self.realization})" if self.realization else self.name


@dataclass(frozen=True, slots=True)
class Projection:
    """A map projection (State Plane zone, UTM zone, custom Lambert, ...)."""

    name: str
    epsg: int | None = None
    proj4: str | None = None
    units: LinearUnit = LinearUnit.METER


@dataclass(frozen=True, slots=True)
class VerticalDatum:
    """A vertical datum (NAVD88, NGVD29, MSL, ellipsoidal, ...)."""

    name: str
    is_ellipsoidal: bool = False
    epsg: int | None = None


@dataclass(frozen=True, slots=True)
class Geoid:
    """A geoid model used to convert ellipsoidal height to orthometric height."""

    name: str
    grid_file: str | None = None  # path or pyproj-known grid name (e.g. 'us_noaa_g2018u0.tif')


@dataclass(frozen=True, slots=True)
class CRS:
    """A complete horizontal + (optionally) vertical coordinate reference system.

    A :class:`CRS` is the *contract* a coordinate carries: knowing the CRS
    is the difference between a point on the Earth and three numbers in a
    spreadsheet. Adapters that need to perform transformations must round-trip
    through :func:`to_pyproj` and use :mod:`meridian.math.transforms`.

    Attributes
    ----------
    epsg
        Preferred identifier when available. ``None`` means use ``wkt``.
    wkt
        OGC WKT-2 string. Always present after construction (synthesized from
        the EPSG code at lookup time if not provided explicitly).
    datum
        Horizontal datum. Carries the realization (e.g. NAD83(2011)).
    projection
        ``None`` for geographic CRSs (lat/lon). Set for projected CRSs.
    vertical
        Optional vertical datum. ``None`` if elevation is not tracked or if
        the CRS is purely horizontal.
    geoid
        Geoid model used when the vertical datum is orthometric and the
        coordinates were derived from ellipsoidal heights.
    horizontal_axis
        How horizontal coords are ordered on entities tied to this CRS.
    units
        Linear unit of horizontal coordinates (for projected CRSs).

    """

    epsg: int | None = None
    wkt: str | None = None
    datum: Datum | None = None
    projection: Projection | None = None
    vertical: VerticalDatum | None = None
    geoid: Geoid | None = None
    horizontal_axis: HorizontalAxis = HorizontalAxis.EAST_NORTH
    units: LinearUnit = LinearUnit.METER
    # Free-form attributes so adapters can stash format-specific tags (e.g.
    # "esri_authority", "well_known_id") without polluting the schema.
    extra: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.epsg is None and self.wkt is None:
            raise ValueError("CRS requires at least one of: epsg, wkt")

    # ── Identity helpers ─────────────────────────────────────────────────────
    def label(self) -> str:
        """Human-readable label for UI and reports."""
        if self.epsg is not None:
            return f"EPSG:{self.epsg}"
        return self.datum.label() if self.datum else "Custom CRS"

    def is_geographic(self) -> bool:
        return self.projection is None

    def is_projected(self) -> bool:
        return self.projection is not None

    def to_pyproj(self) -> Any:
        """Materialise a ``pyproj.CRS`` for use by transformation code.

        Imported lazily so the domain package keeps zero hard dependency on
        pyproj at *import* time (only at use time).
        """
        import pyproj

        if self.epsg is not None:
            return pyproj.CRS.from_epsg(self.epsg)
        return pyproj.CRS.from_wkt(self.wkt)  # type: ignore[arg-type]


# ── Common CRSs ──────────────────────────────────────────────────────────────
# These are used as defaults for samples and convenience. They are *values*,
# not configuration — code that needs a CRS should accept one explicitly,
# never default silently to one of these.

WGS84 = CRS(
    epsg=4326,
    datum=Datum(name="WGS 84", realization="G2139", epsg=6326),
    horizontal_axis=HorizontalAxis.LAT_LON,
    units=LinearUnit.METER,
)
"""Geographic WGS 84 (lat/lon, degrees)."""

NAD83_2011 = CRS(
    epsg=6318,
    datum=Datum(name="NAD83", realization="2011", epsg=6318),
    horizontal_axis=HorizontalAxis.LAT_LON,
    units=LinearUnit.METER,
)
"""Geographic NAD83(2011)."""


def state_plane(zone_epsg: int, *, units: LinearUnit = LinearUnit.US_SURVEY_FOOT) -> CRS:
    """Construct a US State Plane CRS by EPSG code.

    Parameters
    ----------
    zone_epsg
        EPSG of the desired State Plane zone (e.g. ``2277`` for
        Texas Central NAD83(2011) US ft).
    units
        Linear unit reported by the CRS. Note: the *actual* units are
        determined by the EPSG definition; this is metadata only.

    """
    return CRS(
        epsg=zone_epsg,
        datum=Datum(name="NAD83", realization="2011", epsg=6318),
        projection=Projection(name=f"EPSG:{zone_epsg}", epsg=zone_epsg, units=units),
        horizontal_axis=HorizontalAxis.EAST_NORTH,
        units=units,
    )


def utm(zone: int, hemisphere: str = "N", *, datum: str = "NAD83") -> CRS:
    """Construct a UTM CRS for the given zone and hemisphere.

    Examples
    --------
    >>> crs = utm(14, "N")          # UTM 14N NAD83
    >>> crs = utm(33, "N", datum="WGS84")

    """
    if datum.upper() == "WGS84":
        epsg = 32600 + zone if hemisphere.upper() == "N" else 32700 + zone
        d = Datum(name="WGS 84", epsg=6326)
    elif datum.upper() == "NAD83":
        epsg = 26900 + zone  # NAD83 UTM zones 1N..23N (see EPSG registry for full list)
        d = Datum(name="NAD83", epsg=6269)
    else:
        raise ValueError(f"Unsupported UTM datum: {datum!r}")
    return CRS(
        epsg=epsg,
        datum=d,
        projection=Projection(name=f"UTM zone {zone}{hemisphere}", epsg=epsg, units=LinearUnit.METER),
        horizontal_axis=HorizontalAxis.EAST_NORTH,
        units=LinearUnit.METER,
    )
