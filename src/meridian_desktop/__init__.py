"""Meridian desktop — PySide6 shell.

The desktop app is a *thin* Qt wrapper around the same services + CLI
the rest of Meridian uses. There is no business logic here. Each tab /
window owns a layout and routes user actions to a service.
"""

from __future__ import annotations
