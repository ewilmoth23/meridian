"""Pulse tool registry.

A "tool" is a Python callable that the LLM can invoke through the MCP
protocol or a direct function-calling interface. Each tool has:

* a stable id (``parse_deed``, ``run_traverse``, ...),
* a JSON-schema spec describing its arguments,
* a Python function that implements it.

Tools wrap the same services the desktop UI calls — so anything Pulse
can do, the GUI can do, and vice versa.

The registry is consumed by:

* :class:`meridian.ai.pulse.server.PulseServer` (MCP server transport).
* The desktop chat panel (direct in-process calls).
* The CLI ``meridian pulse ask`` command (stdin → tool router → LLM).
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

ToolFn = Callable[..., Any]


@dataclass(frozen=True, slots=True)
class ToolSpec:
    """A tool's external description for the LLM."""

    id: str
    description: str
    schema: dict[str, Any]
    fn: ToolFn

    def to_mcp(self) -> dict[str, Any]:
        return {
            "name": self.id,
            "description": self.description,
            "inputSchema": self.schema,
        }


@dataclass(slots=True)
class ToolRegistry:
    tools: dict[str, ToolSpec] = field(default_factory=dict)

    def register(self, tool: ToolSpec) -> None:
        self.tools[tool.id] = tool

    def call(self, tool_id: str, arguments: dict[str, Any]) -> Any:
        if tool_id not in self.tools:
            raise KeyError(f"Unknown tool: {tool_id!r}")
        return self.tools[tool_id].fn(**arguments)

    def list_tools(self) -> list[dict[str, Any]]:
        return [t.to_mcp() for t in self.tools.values()]


# ── Default tool implementations ─────────────────────────────────────────────


def _tool_parse_deed(text: str, epsg: int = 2277, start_x: float = 0.0, start_y: float = 0.0) -> dict[str, Any]:
    from meridian.domain.crs import CRS
    from meridian.services.deed_service import DeedService

    res = DeedService().parse_to_cad(
        text=text,
        crs=CRS(epsg=epsg),
        starting_point=(start_x, start_y),
    )
    boundary = res.parcel.boundary
    return {
        "calls": len(res.parcel.calls),
        "misclosure_m": res.misclosure_m,
        "closure_ratio": None if res.closure_ratio == float("inf") else res.closure_ratio,
        "perimeter_m": boundary.perimeter if boundary else 0.0,
        "area_m2": boundary.polygon.area() if boundary else 0.0,
    }


def _tool_run_traverse(file_path: str, start_x: float = 0.0, start_y: float = 0.0, method: str = "compass") -> dict[str, Any]:
    from meridian.services.traverse_service import TraverseService

    res = TraverseService().run_from_file(
        Path(file_path), starting_point=(start_x, start_y), method=method
    )
    return {
        "driver": res.driver,
        "setups": res.setups_count,
        "observations": res.observations_count,
        "legs": res.legs_count,
        "closure_distance_m": res.result.closure_distance,
        "closure_ratio": (
            None if res.result.closure_ratio == float("inf") else res.result.closure_ratio
        ),
        "perimeter_m": res.result.perimeter,
        "area_m2": res.result.area,
    }


def _tool_classify_cloud(file_path: str, contour_interval_m: float = 1.0) -> dict[str, Any]:
    from meridian.pipelines.pointcloud_classify import PointCloudPipelineOptions
    from meridian.services.pointcloud_service import PointCloudService

    opts = PointCloudPipelineOptions(contour_interval_m=contour_interval_m)
    res = PointCloudService().classify_to_contours(Path(file_path), options=opts)
    return {
        "ground_points": res.ground_point_count,
        "tin_triangles": res.surface.tin.triangle_count,
        "contour_intervals": len(res.surface.contours),
    }


def _tool_list_projects() -> list[dict[str, Any]]:
    """List projects in the active project DB. Returns a placeholder until a
    repository is wired (the registry is created with ``survey_repo=None``).
    """
    return [{"id": "demo", "name": "(no project DB attached — pass survey_repo to the registry)"}]


def _tool_inverse(p1_x: float, p1_y: float, p2_x: float, p2_y: float) -> dict[str, Any]:
    from meridian.math.cogo import inverse

    res = inverse((p1_x, p1_y), (p2_x, p2_y))
    return {"distance_m": res.distance, "bearing_rad": res.bearing}


def _tool_forward(x: float, y: float, bearing_rad: float, distance_m: float) -> dict[str, Any]:
    from meridian.math.cogo import forward

    nx, ny = forward((x, y), bearing_rad, distance_m)
    return {"x": nx, "y": ny}


def _tool_health() -> dict[str, Any]:
    from meridian import __version__

    return {"meridian_version": __version__, "status": "ok"}


# ── Registry builder ─────────────────────────────────────────────────────────


def build_tool_registry(*, repositories: Any | None = None) -> ToolRegistry:
    """Construct the default Pulse tool registry.

    ``repositories`` is reserved for v0.4: a bag holding survey/parcel/cloud
    repositories so tools that talk to the project DB don't have to build
    their own engine.
    """
    reg = ToolRegistry()

    reg.register(
        ToolSpec(
            id="parse_deed",
            description="Parse a metes-and-bounds deed text into a closed boundary; report closure stats.",
            schema={
                "type": "object",
                "properties": {
                    "text": {"type": "string", "description": "Deed text"},
                    "epsg": {"type": "integer", "default": 2277},
                    "start_x": {"type": "number", "default": 0.0},
                    "start_y": {"type": "number", "default": 0.0},
                },
                "required": ["text"],
            },
            fn=_tool_parse_deed,
        )
    )
    reg.register(
        ToolSpec(
            id="run_traverse",
            description="Run a closed traverse from a Leica GSI / Trimble JXL / TDS RW5 / Sokkia SDR / Nikon RAW file.",
            schema={
                "type": "object",
                "properties": {
                    "file_path": {"type": "string"},
                    "start_x": {"type": "number", "default": 0.0},
                    "start_y": {"type": "number", "default": 0.0},
                    "method": {
                        "type": "string",
                        "enum": ["compass", "transit", "least_squares"],
                        "default": "compass",
                    },
                },
                "required": ["file_path"],
            },
            fn=_tool_run_traverse,
        )
    )
    reg.register(
        ToolSpec(
            id="classify_cloud",
            description="Classify ground in a LAS/LAZ file, build a TIN, and report contour count.",
            schema={
                "type": "object",
                "properties": {
                    "file_path": {"type": "string"},
                    "contour_interval_m": {"type": "number", "default": 1.0},
                },
                "required": ["file_path"],
            },
            fn=_tool_classify_cloud,
        )
    )
    reg.register(
        ToolSpec(
            id="list_projects",
            description="List projects in the active project DB.",
            schema={"type": "object", "properties": {}},
            fn=_tool_list_projects,
        )
    )
    reg.register(
        ToolSpec(
            id="inverse",
            description="COGO inverse: distance + bearing between two coordinate points.",
            schema={
                "type": "object",
                "properties": {
                    "p1_x": {"type": "number"},
                    "p1_y": {"type": "number"},
                    "p2_x": {"type": "number"},
                    "p2_y": {"type": "number"},
                },
                "required": ["p1_x", "p1_y", "p2_x", "p2_y"],
            },
            fn=_tool_inverse,
        )
    )
    reg.register(
        ToolSpec(
            id="forward",
            description="COGO forward: project a point along bearing + distance.",
            schema={
                "type": "object",
                "properties": {
                    "x": {"type": "number"},
                    "y": {"type": "number"},
                    "bearing_rad": {"type": "number"},
                    "distance_m": {"type": "number"},
                },
                "required": ["x", "y", "bearing_rad", "distance_m"],
            },
            fn=_tool_forward,
        )
    )
    reg.register(
        ToolSpec(
            id="health",
            description="Liveness check.",
            schema={"type": "object", "properties": {}},
            fn=_tool_health,
        )
    )
    return reg
