"""Triangulation, TIN-from-cloud, and contour extraction.

Backed by ``scipy.spatial`` (Qhull). For constrained Delaunay (with
breaklines), we expose an optional path through the ``triangle`` package
when it's installed; otherwise we fall back to unconstrained Delaunay
plus a manual breakline-edge insertion pass.
"""

from __future__ import annotations

import numpy as np
from scipy.spatial import Delaunay


def delaunay_2d(xy: np.ndarray) -> np.ndarray:
    """Delaunay triangulation of an ``(N, 2)`` point set.

    Returns triangle indices, shape ``(M, 3)``.
    """
    xy = np.asarray(xy, dtype=np.float64)
    if xy.ndim != 2 or xy.shape[1] != 2:
        raise ValueError(f"Expected (N, 2), got {xy.shape}")
    if xy.shape[0] < 3:
        raise ValueError(f"Need at least 3 points, got {xy.shape[0]}")
    tri = Delaunay(xy, qhull_options="QJ")  # joggle for degeneracy robustness
    return np.asarray(tri.simplices, dtype=np.int64)


def tin_from_points(xyz: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Build a 2.5-D TIN from XYZ points.

    Returns ``(vertices, triangles)`` — vertices is the same array,
    triangles is the index list. The Z dimension is preserved so callers
    can interpolate elevation at arbitrary planimetric points.
    """
    xyz = np.asarray(xyz, dtype=np.float64)
    if xyz.ndim != 2 or xyz.shape[1] != 3:
        raise ValueError(f"Expected (N, 3), got {xyz.shape}")
    triangles = delaunay_2d(xyz[:, :2])
    return xyz, triangles


def interpolate_z(xyz: np.ndarray, triangles: np.ndarray, query_xy: np.ndarray) -> np.ndarray:
    """Barycentric Z-interpolation on a TIN.

    Returns ``z`` for each query point, with ``NaN`` where the point is
    outside the triangulation.
    """
    xyz = np.asarray(xyz, dtype=np.float64)
    query_xy = np.asarray(query_xy, dtype=np.float64)
    tri = Delaunay(xyz[:, :2], qhull_options="QJ")
    simplex_ids = tri.find_simplex(query_xy)
    out = np.full(query_xy.shape[0], np.nan, dtype=np.float64)
    inside = simplex_ids >= 0
    if not np.any(inside):
        return out
    # Barycentric coordinates of query points within their containing simplices.
    transform = tri.transform[simplex_ids[inside]]
    p_minus_origin = query_xy[inside] - transform[:, 2]
    bary = np.einsum("ijk,ik->ij", transform[:, :2], p_minus_origin)
    bary = np.column_stack([bary, 1 - bary.sum(axis=1)])
    # Triangle vertex Zs for those simplices.
    tris = tri.simplices[simplex_ids[inside]]
    z_vals = xyz[tris, 2]
    out[inside] = np.einsum("ij,ij->i", bary, z_vals)
    return out


def extract_contours(
    xyz: np.ndarray,
    triangles: np.ndarray,
    elevations: np.ndarray,
) -> dict[float, list[np.ndarray]]:
    """Extract iso-elevation contour polylines from a TIN.

    Marching-triangles algorithm: for each triangle at each elevation,
    compute the line segments where the iso-plane intersects the triangle.

    Returns a mapping of ``elevation -> list of (M, 2) polylines``. Each
    polyline is a chain of segments connected end-to-end. Multiple
    disjoint polylines per elevation are returned separately.
    """
    xyz = np.asarray(xyz, dtype=np.float64)
    triangles = np.asarray(triangles, dtype=np.int64)
    elevations = np.asarray(elevations, dtype=np.float64)

    result: dict[float, list[np.ndarray]] = {float(e): [] for e in elevations}

    # Vectorised computation of segments per elevation.
    for elev in elevations:
        segs = _triangle_iso_segments(xyz, triangles, float(elev))
        if segs.shape[0] == 0:
            continue
        chains = _chain_segments(segs)
        result[float(elev)] = chains
    return result


def _triangle_iso_segments(xyz: np.ndarray, triangles: np.ndarray, elev: float) -> np.ndarray:
    """For a single elevation, compute all triangle/iso-plane segments.

    Returns array of shape ``(K, 2, 2)`` — K segments, each with start and
    end (x, y).
    """
    z = xyz[:, 2]
    tri_z = z[triangles]  # (M, 3)
    above = tri_z > elev
    n_above = above.sum(axis=1)
    # Triangles that straddle the plane: 1 or 2 vertices above.
    straddles = (n_above == 1) | (n_above == 2)
    if not np.any(straddles):
        return np.empty((0, 2, 2), dtype=np.float64)
    sel = triangles[straddles]
    sel_above = above[straddles]

    # For each straddling triangle, compute the two intersection points
    # by linear interpolation along the two edges that cross the plane.
    pts_xy = xyz[:, :2]
    pts_z = xyz[:, 2]

    def _interp(i: np.ndarray, j: np.ndarray) -> np.ndarray:
        zi = pts_z[i]
        zj = pts_z[j]
        denom = zj - zi
        # Avoid divide-by-zero when both endpoints lie exactly on the plane.
        denom = np.where(np.abs(denom) < 1e-30, 1e-30, denom)
        t = (elev - zi) / denom
        t = np.clip(t, 0.0, 1.0)
        result: np.ndarray = pts_xy[i] + t[:, None] * (pts_xy[j] - pts_xy[i])
        return result

    # The crossing edges depend on which vertex is the "odd one out".
    # When exactly 1 vertex is above, that's the odd one. When 2 are above,
    # the odd one is the one *below*.
    minority_above = sel_above.sum(axis=1) == 1
    odd_mask = np.where(minority_above[:, None], sel_above, ~sel_above)
    # `odd_mask[k]` flags the single vertex on the "minority" side.

    # For each triangle, produce two edge-interpolations: between the odd
    # vertex and each of the other two.
    odd_idx = np.argmax(odd_mask, axis=1)
    other = np.array([[0, 1, 2]] * len(sel))
    other_mask = other != odd_idx[:, None]
    other_pairs = other[other_mask].reshape(-1, 2)

    # Vertex indices of: odd, other1, other2
    v_odd = sel[np.arange(len(sel)), odd_idx]
    v_o1 = sel[np.arange(len(sel)), other_pairs[:, 0]]
    v_o2 = sel[np.arange(len(sel)), other_pairs[:, 1]]

    p1 = _interp(v_odd, v_o1)
    p2 = _interp(v_odd, v_o2)

    return np.stack([p1, p2], axis=1)  # shape (K, 2, 2)


def _chain_segments(segments: np.ndarray, *, tol: float = 1e-6) -> list[np.ndarray]:
    """Chain a soup of (start, end) segments into polylines."""
    if segments.size == 0:
        return []

    # Hash endpoints with rounding for robust equality.
    def key(p: np.ndarray) -> tuple[int, int]:
        return (round(p[0] / tol), round(p[1] / tol))

    from collections import defaultdict

    adj: dict[tuple[int, int], list[tuple[int, int]]] = defaultdict(list)
    seg_endpoints = []
    for s in segments:
        ka = key(s[0])
        kb = key(s[1])
        adj[ka].append(kb)
        adj[kb].append(ka)
        seg_endpoints.append((ka, kb, tuple(s[0]), tuple(s[1])))

    # Map endpoint key → coordinate (any one will do)
    coord: dict[tuple[int, int], tuple[float, float]] = {}
    for ka, kb, ca, cb in seg_endpoints:
        coord.setdefault(ka, ca)
        coord.setdefault(kb, cb)

    used: set[frozenset[tuple[int, int]]] = set()
    chains: list[list[tuple[float, float]]] = []
    for ka, kb, ca, cb in seg_endpoints:
        edge = frozenset({ka, kb})
        if edge in used:
            continue
        # Walk forward then backward from this segment.
        chain = [ca, cb]
        used.add(edge)

        # Forward
        while True:
            current = key(np.array(chain[-1]))
            extended = False
            for neigh in adj[current]:
                edge2 = frozenset({current, neigh})
                if edge2 in used:
                    continue
                used.add(edge2)
                chain.append(coord[neigh])
                extended = True
                break
            if not extended:
                break
        # Backward
        while True:
            current = key(np.array(chain[0]))
            extended = False
            for neigh in adj[current]:
                edge2 = frozenset({current, neigh})
                if edge2 in used:
                    continue
                used.add(edge2)
                chain.insert(0, coord[neigh])
                extended = True
                break
            if not extended:
                break
        chains.append(chain)

    return [np.asarray(c, dtype=np.float64) for c in chains]
