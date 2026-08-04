"""CGB Filter predicates (the doc's *Filter* column) — the live constraint a
construction applies to its remaining slots once earlier slots are filled (e.g.
after one flat face, only *parallel* flat faces are selectable for the second).

Each predicate takes the already-bound slot entities + a candidate entity and
returns True when the candidate is allowed. The controller composes the active
recipe's ``filters`` into one ``SlotEntity -> bool`` via :func:`slot_predicate`,
wraps it as ``SelectionItem -> bool`` (through ``item_to_entity``), and pushes it to
the Selection Filter (``set_owned_candidate_filter``) so a rejected candidate is not
selectable / snappable / highlighted.

Elementwise-only (no ``@``/``np.dot``/``np.linalg`` — GUI process). Predicates are
lenient: if a needed field is missing they return True (never over-reject).
"""

from __future__ import annotations

import math
from typing import Callable, List

import numpy as np


def _pt(e):
    p = e.point if getattr(e, "point", None) is not None else getattr(e, "origin", None)
    return None if p is None else np.asarray(p, dtype=np.float64)


def _dir(e):
    d = getattr(e, "direction", None)
    if d is None:
        return None
    d = np.asarray(d, dtype=np.float64)
    n = math.sqrt(float(d[0]*d[0] + d[1]*d[1] + d[2]*d[2]))
    return None if n < 1e-12 else d / n


def _normal(e):
    n = getattr(e, "normal", None)
    if n is None:
        return None
    n = np.asarray(n, dtype=np.float64)
    ln = math.sqrt(float(n[0]*n[0] + n[1]*n[1] + n[2]*n[2]))
    return None if ln < 1e-12 else n / ln


def _cross_mag(a, b) -> float:
    c = np.cross(a, b)
    return math.sqrt(float(c[0]*c[0] + c[1]*c[1] + c[2]*c[2]))


def _dist(a, b) -> float:
    d = a - b
    return math.sqrt(float(d[0]*d[0] + d[1]*d[1] + d[2]*d[2]))


# --- predicates: (bound, cand, tol) -> allowed? --------------------------- #

def f_distinct(bound, cand, tol):
    p = _pt(cand)
    if p is None:
        return True
    for b in bound:
        bp = _pt(b)
        if bp is not None and _dist(p, bp) <= tol:
            return False
    return True


def f_not_parallel(bound, cand, tol):
    cd = _dir(cand)
    if cd is None or not bound:
        return True
    bd = _dir(bound[0])
    if bd is None:
        return True
    return _cross_mag(cd, bd) > 1e-4


def f_parallel(bound, cand, tol):
    cn = _normal(cand)
    if cn is None or not bound:
        return True
    bn = _normal(bound[0])
    if bn is None:
        return True
    return _cross_mag(cn, bn) <= 1e-3


def _off_line(pt, line_pt, line_dir, tol):
    if pt is None or line_pt is None or line_dir is None:
        return True
    w = pt - line_pt
    proj = w - line_dir * float(w[0]*line_dir[0] + w[1]*line_dir[1] + w[2]*line_dir[2])
    return math.sqrt(float(proj[0]**2 + proj[1]**2 + proj[2]**2)) > tol


def f_off_line(bound, cand, tol):
    if not bound:
        return True
    return _off_line(_pt(cand), _pt(bound[0]), _dir(bound[0]), tol)


f_off_axis = f_off_line   # same test (a slot's origin+direction)


def f_non_collinear(bound, cand, tol):
    if len(bound) < 2:
        return True
    a, b = _pt(bound[0]), _pt(bound[1])
    c = _pt(cand)
    if a is None or b is None or c is None:
        return True
    ab = b - a
    n = math.sqrt(float(ab[0]**2 + ab[1]**2 + ab[2]**2))
    if n < 1e-12:
        return True
    return _off_line(c, a, ab / n, tol)


FILTERS = {
    "distinct": f_distinct,
    "not_parallel": f_not_parallel,
    "parallel": f_parallel,
    "off_line": f_off_line,
    "off_axis": f_off_axis,
    "non_collinear": f_non_collinear,
}


def slot_predicate(names, bound: List, scale: float = 1.0) -> Callable:
    """Compose the named filters into one ``SlotEntity -> bool`` for the next pick,
    given the already-bound slot entities. Empty ``names`` → always True."""
    tol = max(1e-6, float(scale) * 1e-3)
    preds = [FILTERS[n] for n in names if n in FILTERS]

    def _ok(cand) -> bool:
        if cand is None:
            return True
        return all(p(bound, cand, tol) for p in preds)
    return _ok
