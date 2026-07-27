"""Concrete I/O adapters.

Hard rule: adapters import from ``meridian.domain``, ``meridian.math``,
and ``meridian.ports`` only. They do not import from other adapter
subpackages or from ``meridian.services``.
"""

from __future__ import annotations
