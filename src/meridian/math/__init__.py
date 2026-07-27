"""Numerical kernels for Meridian.

Contracts:

* All functions are pure: same inputs → same outputs, no side effects.
* All hot paths use numpy / scipy. Pure-Python loops are reserved for
  control flow, not for numerics.
* Unless otherwise documented, angles are **radians**, distances are
  **meters**.
* Inputs and outputs are :mod:`meridian.domain` types or numpy arrays;
  never adapter-specific or persistence-specific types.
"""

from __future__ import annotations
