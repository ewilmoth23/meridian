"""Multi-step domain workflows.

A pipeline composes :mod:`meridian.math` kernels and
:mod:`meridian.ports` adapter calls into a named, testable workflow.

Pipelines are the *recipe layer*. They are pure-Python orchestrators:
they call into math for the heavy lifting, hand off file-I/O to adapters,
and wire results into domain types.

Public functions in this package take in domain types and return domain
types. They never touch files directly — that's the adapter's job.
"""

from __future__ import annotations
