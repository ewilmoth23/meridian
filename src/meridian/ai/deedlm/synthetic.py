"""Synthetic deed generator for adversarial training.

Produces deeds in jurisdictional dialects so the trained model
generalises across:

* **texas_vara** — historical Texas deeds using ``varas`` and Spanish
  surveying conventions.
* **ne_rod_pole** — New England + early-republic deeds using rods, poles,
  perches, chains, links.
* **plss_aliquot** — Public Land Survey System aliquot-part descriptions
  ("the Northwest quarter of the Southeast quarter of Section 14, T2N
  R3E of the 6th P.M.").
* **modern_ca** — California modern deed style: feet, bearings to seconds.

The generator is deterministic given a ``random.Random`` instance, so we
can regenerate the same training set across runs.
"""

from __future__ import annotations

import random


def generate_synthetic_deed(dialect: str, *, rng: random.Random | None = None) -> str:
    """Generate a single synthetic deed in the given dialect."""
    rng = rng or random.Random()
    if dialect == "texas_vara":
        return _texas_vara(rng)
    if dialect == "ne_rod_pole":
        return _ne_rod_pole(rng)
    if dialect == "plss_aliquot":
        return _plss_aliquot(rng)
    if dialect == "modern_ca":
        return _modern_ca(rng)
    raise ValueError(f"Unknown dialect: {dialect!r}")


def _bearing(rng: random.Random) -> str:
    ns = rng.choice(["N", "S"])
    ew = rng.choice(["E", "W"])
    deg = rng.randint(0, 89)
    minutes = rng.randint(0, 59)
    seconds = rng.randint(0, 59)
    return f"{ns} {deg}°{minutes:02d}'{seconds:02d}\" {ew}"


def _texas_vara(rng: random.Random) -> str:
    n = rng.randint(4, 8)
    parts = ["Beginning at a stake on the bank of the creek;"]
    for _ in range(n - 1):
        parts.append(
            f"thence {_bearing(rng)} {rng.randint(50, 800)}.{rng.randint(0, 99):02d} varas to a stone marked X;"
        )
    parts.append(
        f"thence {_bearing(rng)} {rng.randint(50, 800)}.{rng.randint(0, 99):02d} varas to the place of beginning, "
        f"containing {rng.randint(1, 320)} acres more or less."
    )
    return " ".join(parts)


def _ne_rod_pole(rng: random.Random) -> str:
    units = ["rods", "perches", "poles", "chains and " + str(rng.randint(0, 99)) + " links"]
    n = rng.randint(4, 7)
    parts = ["Beginning at a stake and stones at the southeasterly corner of land of the said grantor;"]
    for _ in range(n - 1):
        parts.append(
            f"thence running {_bearing(rng)} {rng.randint(2, 80)} {rng.choice(units)} to a heap of stones;"
        )
    parts.append(
        f"thence {_bearing(rng)} {rng.randint(2, 60)} rods to the place of beginning, "
        f"containing {rng.randint(1, 200)} acres more or less."
    )
    return " ".join(parts)


def _plss_aliquot(rng: random.Random) -> str:
    quarter1 = rng.choice(["Northeast", "Northwest", "Southeast", "Southwest"])
    quarter2 = rng.choice(["Northeast", "Northwest", "Southeast", "Southwest"])
    section = rng.randint(1, 36)
    township = rng.randint(1, 24)
    range_n = rng.randint(1, 24)
    ns = rng.choice(["North", "South"])
    ew = rng.choice(["East", "West"])
    pm = rng.choice([
        "6th Principal Meridian",
        "Indian Meridian",
        "Tallahassee Meridian",
        "Mount Diablo Meridian",
    ])
    return (
        f"The {quarter1} quarter of the {quarter2} quarter of Section {section}, "
        f"Township {township} {ns}, Range {range_n} {ew}, of the {pm}, "
        f"containing 40 acres more or less."
    )


def _modern_ca(rng: random.Random) -> str:
    n = rng.randint(4, 8)
    parts = ["Commencing at the True Point of Beginning, an iron pin set in concrete;"]
    for _ in range(n - 1):
        parts.append(
            f"thence {_bearing(rng)} a distance of {rng.randint(20, 800)}.{rng.randint(0, 99):02d} feet to an iron pin set;"
        )
    parts.append(
        f"thence {_bearing(rng)} a distance of {rng.randint(20, 800)}.{rng.randint(0, 99):02d} feet to the True Point of Beginning."
    )
    return " ".join(parts)
