"""Entry-point-based plugin discovery."""

from __future__ import annotations

import logging
import threading
from dataclasses import dataclass, field
from importlib.metadata import EntryPoint, entry_points
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from meridian.ports.exporter import Exporter
    from meridian.ports.importer import Importer
    from meridian.ports.instrument import InstrumentDriver

logger = logging.getLogger(__name__)


GROUP_INSTRUMENTS = "meridian.instruments"
GROUP_EXPORTERS = "meridian.exporters"
GROUP_IMPORTERS = "meridian.importers"
GROUP_JURISDICTIONS = "meridian.jurisdictions"
GROUP_AI_PROVIDERS = "meridian.ai_providers"


@dataclass(slots=True)
class PluginRegistry:
    """In-process registry of resolved plugins."""

    instruments: dict[str, InstrumentDriver] = field(default_factory=dict)
    exporters: dict[str, Exporter] = field(default_factory=dict)
    importers: dict[str, Importer] = field(default_factory=dict)
    jurisdictions: dict[str, object] = field(default_factory=dict)
    ai_providers: dict[str, object] = field(default_factory=dict)

    def driver_for_path(self, path) -> InstrumentDriver | None:
        """First instrument driver whose ``can_read`` matches the path."""
        for drv in self.instruments.values():
            try:
                if drv.can_read(path):
                    return drv
            except Exception as e:
                logger.warning("Driver %s.can_read(%s) raised: %s", drv.short_id, path, e)
        return None


_registry: PluginRegistry | None = None
_lock = threading.Lock()


def get_registry(*, refresh: bool = False) -> PluginRegistry:
    """Return the process-wide :class:`PluginRegistry`, building it on first access."""
    global _registry
    with _lock:
        if _registry is None or refresh:
            _registry = _discover()
        return _registry


def _discover() -> PluginRegistry:
    reg = PluginRegistry()
    _populate(reg.instruments, GROUP_INSTRUMENTS)
    _populate(reg.exporters, GROUP_EXPORTERS)
    _populate(reg.importers, GROUP_IMPORTERS)
    _populate(reg.jurisdictions, GROUP_JURISDICTIONS)
    _populate(reg.ai_providers, GROUP_AI_PROVIDERS)
    return reg


def _populate(target: dict[str, object], group: str) -> None:
    for ep in _entry_points_for_group(group):
        try:
            cls = ep.load()
            instance = cls()
            short_id = getattr(instance, "short_id", None) or ep.name
            target[short_id] = instance
            logger.debug("Registered %s plugin: %s -> %s", group, short_id, type(instance).__name__)
        except Exception as e:
            logger.warning("Failed to load plugin %s from %s: %s", ep.name, group, e)


def _entry_points_for_group(group: str) -> list[EntryPoint]:
    eps = entry_points()
    # Python 3.10+ supports .select(); older returns dict by group.
    if hasattr(eps, "select"):
        return list(eps.select(group=group))
    return list(eps.get(group, []))  # type: ignore[attr-defined]
