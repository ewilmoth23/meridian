"""Plugin discovery and registry.

Plugins are ordinary Python packages that declare entry points under
the ``meridian.*`` groups defined in ``pyproject.toml``:

* ``meridian.instruments``
* ``meridian.exporters``
* ``meridian.importers``
* ``meridian.jurisdictions``
* ``meridian.ai_providers``

At application startup we enumerate each group, instantiate the entry
point's class, validate it implements the corresponding port, and
register it in :class:`PluginRegistry`. Services and the UI then look
up implementations by short id.
"""

from __future__ import annotations

from meridian.plugins.discovery import PluginRegistry, get_registry

__all__ = ["PluginRegistry", "get_registry"]
