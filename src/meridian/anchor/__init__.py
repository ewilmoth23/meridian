"""Anchor — open-source AR field stakeout (v0.9).

The space already has shipping competitors (Pix4DCatch + viDoc RTK rover,
Lefixea LRTK on iPad, Trimble SiteVision). Anchor is the open and
integrated alternative:

* Open-source ARKit / ARCore reference implementation.
* Consumes any RTK rover via NTRIP.
* Reads stake-out coordinates from the canonical
  :class:`~meridian.domain.survey.Survey` model — no separate stakeout file.
* Writes recovered monument positions back into the same Survey, signed
  by :mod:`meridian.truthchain`.
* Free for licensed Meridian users.

Status: planning stub for v0.9.
"""

from __future__ import annotations
