"""Fit Primitives — mesh subprocess worker (F1, mesh path).

Least-squares fit of a plane / cylinder / sphere over a triangle patch. Uses
``numpy.linalg`` (SVD / eigh / lstsq), which HARD-CRASHES (``0xC06D007F``) once VTK
or pxr DLLs are loaded — so this **only ever runs in a subprocess** (dispatched via
``src.main --worker fit_primitives_worker <workdir>``), NEVER in the GUI process.

I/O (a workdir):
  in.json  : {"want": "auto"|"plane"|"cylinder"|"sphere"}
  in.npz   : v (float64 [N,3] world verts), t (int [M,3] triangle indices)
  out.json : {"ok": bool, "kind": ..., "origin": [x,y,z], "direction": [x,y,z],
              "center": [...], "radius": r, "apex": [...], "residual": r}

Qt-FREE; imports numpy only.
"""

from __future__ import annotations

import json
import os
import sys
from typing import Optional

import numpy as np


def _unit(v):
    n = float(np.sqrt(np.dot(v, v)))
    return v / n if n > 1e-12 else v


def _tri_normals(v, t):
    a = v[t[:, 0]]
    b = v[t[:, 1]]
    c = v[t[:, 2]]
    n = np.cross(b - a, c - a)
    ln = np.linalg.norm(n, axis=1)
    keep = ln > 1e-12
    n = n[keep] / ln[keep, None]
    cen = (a[keep] + b[keep] + c[keep]) / 3.0
    area = 0.5 * ln[keep]
    return n, cen, area


def _fit_plane(v):
    c = v.mean(axis=0)
    u, s, vt = np.linalg.svd(v - c, full_matrices=False)
    normal = vt[-1]
    resid = float(abs((v - c) @ normal).mean())
    return {"ok": True, "kind": "plane", "origin": c.tolist(),
            "direction": _unit(normal).tolist(), "normal": _unit(normal).tolist(),
            "residual": resid}


def _fit_sphere(v):
    # algebraic: minimize |p-c|^2 - r^2  ->  A[cx,cy,cz,d] = b
    A = np.hstack([2.0 * v, np.ones((len(v), 1))])
    b = (v ** 2).sum(axis=1)
    x, *_ = np.linalg.lstsq(A, b, rcond=None)
    c = x[:3]
    r = float(np.sqrt(max(0.0, x[3] + float(np.dot(c, c)))))
    resid = float(abs(np.linalg.norm(v - c, axis=1) - r).mean())
    return {"ok": True, "kind": "sphere", "center": c.tolist(),
            "origin": c.tolist(), "radius": r, "residual": resid}


def _fit_cylinder(v, t):
    # axis = the direction ⊥ all surface normals = smallest eigenvector of Σ n nᵀ
    n, cen, area = _tri_normals(v, t)
    if len(n) < 2:
        return {"ok": False, "kind": "cylinder"}
    cov = (n[:, :, None] * n[:, None, :] * area[:, None, None]).sum(axis=0)
    w, vecs = np.linalg.eigh(cov)
    axis = _unit(vecs[:, 0])                      # least-aligned with the normals
    # project verts onto the plane ⊥ axis, fit a 2D circle (algebraic)
    e1 = _unit(np.cross(axis, [1.0, 0, 0] if abs(axis[0]) < 0.9 else [0, 1.0, 0]))
    e2 = _unit(np.cross(axis, e1))
    pu = (v - v.mean(axis=0)) @ e1
    pv = (v - v.mean(axis=0)) @ e2
    A = np.hstack([2.0 * pu[:, None], 2.0 * pv[:, None], np.ones((len(v), 1))])
    bb = pu ** 2 + pv ** 2
    x, *_ = np.linalg.lstsq(A, bb, rcond=None)
    cu, cv = x[0], x[1]
    r = float(np.sqrt(max(0.0, x[2] + cu * cu + cv * cv)))
    center = v.mean(axis=0) + cu * e1 + cv * e2   # a point on the axis
    resid = float(abs(np.sqrt((pu - cu) ** 2 + (pv - cv) ** 2) - r).mean())
    return {"ok": True, "kind": "cylinder", "origin": center.tolist(),
            "direction": axis.tolist(), "radius": r, "residual": resid}


def _auto(v, t):
    fits = [_fit_plane(v), _fit_sphere(v)]
    cyl = _fit_cylinder(v, t)
    if cyl.get("ok"):
        fits.append(cyl)
    # pick the lowest residual (relative to model scale)
    return min(fits, key=lambda f: f.get("residual", 1e18))


def main(argv) -> int:
    if not argv:
        print("fit_primitives_worker: missing workdir", file=sys.stderr)
        return 2
    workdir = argv[0]
    try:
        with open(os.path.join(workdir, "in.json"), encoding="utf-8") as f:
            req = json.load(f)
        npz = np.load(os.path.join(workdir, "in.npz"))
        v = np.asarray(npz["v"], dtype=np.float64).reshape(-1, 3)
        t = np.asarray(npz["t"], dtype=np.int64).reshape(-1, 3)
        # Optional world transform: the GUI passes LOCAL verts + a 4x4 (row-major)
        # so no BLAS matmul runs in the VTK process; the worker (subprocess) applies
        # it here (BLAS is safe — no VTK/pxr loaded).
        m4 = req.get("m4")
        if m4 is not None:
            M = np.asarray(m4, dtype=np.float64).reshape(4, 4)
            v = v @ M[:3, :3].T + M[:3, 3]
        want = req.get("want", "auto")
        if want == "plane":
            out = _fit_plane(v)
        elif want == "sphere":
            out = _fit_sphere(v)
        elif want == "cylinder":
            out = _fit_cylinder(v, t)
        else:
            out = _auto(v, t)
    except Exception as e:  # noqa: BLE001
        out = {"ok": False, "error": repr(e)}
    with open(os.path.join(workdir, "out.json"), "w", encoding="utf-8") as f:
        json.dump(out, f)
    return 0 if out.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
