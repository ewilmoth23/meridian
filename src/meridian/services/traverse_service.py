"""Traverse service — total-station file → reduced legs → adjusted traverse."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from meridian.pipelines.traverse_adjust import (
    TraverseAdjustResult,
    reduce_setup_observations,
    run_closed_traverse,
)
from meridian.plugins.discovery import get_registry


@dataclass(frozen=True, slots=True)
class TraverseRunResult:
    file: Path
    driver: str
    setups_count: int
    observations_count: int
    legs_count: int
    result: TraverseAdjustResult
    warnings: tuple[str, ...]


class TraverseService:
    """Run a closed traverse from a total-station file."""

    def run_from_file(
        self,
        path: Path,
        *,
        starting_point: tuple[float, float] = (0.0, 0.0),
        method: str = "compass",
    ) -> TraverseRunResult:
        reg = get_registry()
        driver = reg.driver_for_path(path)
        if driver is None:
            raise ValueError(
                f"No registered instrument driver can read {path}. "
                f"Available: {sorted(reg.instruments)}"
            )
        read = driver.read(path)
        legs = reduce_setup_observations(list(read.setups), list(read.observations))
        if not legs:
            raise ValueError(
                f"Driver {driver.short_id} produced no traverse legs from {path}. "
                f"Warnings: {list(read.warnings)}"
            )
        traverse = run_closed_traverse(legs, starting_point, method=method)
        return TraverseRunResult(
            file=path,
            driver=driver.short_id,
            setups_count=len(read.setups),
            observations_count=len(read.observations),
            legs_count=len(legs),
            result=traverse,
            warnings=read.warnings,
        )
