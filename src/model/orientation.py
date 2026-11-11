"""Export orientation / placement math (pure numpy — no OCC / VTK / pxr).

Shared by the USD writer, the STEP writer, and the GUI viewport indicators so the
"which source axis is up + spin about it" choice is computed one way everywhere.

IMPORTANT: never use numpy's ``@`` / ``np.dot`` here. BLAS matmul hard-crashes
(``0xC06D007F``) once VTK *or* pxr DLLs are loaded, and this module runs in both
the GUI (VTK) and the export subprocesses (pxr). All multiplies are elementwise.
"""

from __future__ import annotations

import math
from typing import Optional

import numpy as np

# Per up-direction: the export frame's (ex, ey, ez) expressed in SOURCE axes, with
# ez = the chosen source axis (→ world +Z) and a right-handed (ex, ey).
_BASE_FRAME = {
    "+Z": ((1, 0, 0), (0, 1, 0), (0, 0, 1)),
    "-Z": ((1, 0, 0), (0, -1, 0), (0, 0, -1)),
    "+Y": ((1, 0, 0), (0, 0, -1), (0, 1, 0)),
    "-Y": ((1, 0, 0), (0, 0, 1), (0, -1, 0)),
    "+X": ((0, 0, -1), (0, 1, 0), (1, 0, 0)),
    "-X": ((0, 0, 1), (0, 1, 0), (-1, 0, 0)),
}


def _mat3_mul(a, b) -> np.ndarray:
    """3x3 · 3x3, no BLAS ``@``."""
    return np.array(
        [[a[i][0] * b[0][j] + a[i][1] * b[1][j] + a[i][2] * b[2][j] for j in range(3)]
         for i in range(3)],
        dtype=np.float64,
    )


def _mat3_vec(a, v) -> np.ndarray:
    """3x3 · vec3, no BLAS."""
    return np.array([a[i][0] * v[0] + a[i][1] * v[1] + a[i][2] * v[2] for i in range(3)],
                    dtype=np.float64)


def mat4_mul(a: np.ndarray, b: np.ndarray) -> np.ndarray:
    """4x4 · 4x4, no BLAS."""
    return np.array(
        [[sum(a[i][k] * b[k][j] for k in range(4)) for j in range(4)] for i in range(4)],
        dtype=np.float64,
    )


def mat4_inv_rigid(m: np.ndarray) -> np.ndarray:
    """Inverse of a RIGID 4x4 (rotation + translation): ``[Rᵀ | −Rᵀt]``, no BLAS.

    Used by Restructure to compute a moved node's compensating local placement
    (``local = world_parentⁿᵉʷ⁻¹ · world_old``) so its world position is preserved.
    """
    out = np.eye(4, dtype=np.float64)
    for i in range(3):
        for j in range(3):
            out[i, j] = m[j][i]
    for i in range(3):
        out[i, 3] = -(out[i, 0] * m[0][3] + out[i, 1] * m[1][3] + out[i, 2] * m[2][3])
    return out


def orientation_matrix(up_direction: str = "+Z", z_rotation_deg: int = 0) -> np.ndarray:
    """3x3 rotation mapping SOURCE coords → export coords (chosen axis becomes +Z).

    ``point_export = orientation_matrix() · point_source``. ``up_direction`` ∈
    ±X/±Y/±Z; ``z_rotation_deg`` (0/90/180/270) spins X/Y about the new up.
    """
    r = _BASE_FRAME.get(str(up_direction).upper(), _BASE_FRAME["+Z"])  # rows = export axes
    theta = math.radians(float(z_rotation_deg) % 360.0)
    c, s = math.cos(theta), math.sin(theta)
    rz = ((c, -s, 0.0), (s, c, 0.0), (0.0, 0.0, 1.0))
    return _mat3_mul(rz, r)


def axis_frame_matrix(axis) -> np.ndarray:
    """3x3 rotation whose LOCAL +Z column is ``axis`` (unit-normalized here),
    reached by the MINIMAL rotation from identity — the X/Y columns are the
    least-surprising right-handed completion. No BLAS (Rodrigues, elementwise).

    Used by the custom-origin feature: the picked joint axis becomes the
    component's local +Z. Columns are the local axes expressed in the input
    (parent/world) frame, so ``frame4 = [R | origin]`` maps local → parent.
    """
    a = np.asarray(axis, dtype=np.float64)
    n = math.sqrt(float(a[0] * a[0] + a[1] * a[1] + a[2] * a[2]))
    if n < 1e-12:
        raise ValueError("axis_frame_matrix: zero-length axis")
    ax, ay, az = (float(a[0]) / n, float(a[1]) / n, float(a[2]) / n)
    # rotation axis = z × a = (-ay, ax, 0); cos = az
    c = az
    if c > 1.0 - 1e-12:                      # axis ≈ +Z → identity
        return np.eye(3, dtype=np.float64)
    if c < -1.0 + 1e-12:                     # axis ≈ -Z → 180° about X
        return np.array([[1.0, 0.0, 0.0], [0.0, -1.0, 0.0], [0.0, 0.0, -1.0]],
                        dtype=np.float64)
    kx, ky = -ay, ax                          # rotation axis (unnormalized), z-component 0
    kn = math.sqrt(kx * kx + ky * ky)         # |z × a| = sin(angle) (both unit)
    kx, ky = kx / kn, ky / kn
    s = kn
    one_c = 1.0 - c
    # Rodrigues: R = I + sin·K + (1−cos)·K² with K = cross-matrix of (kx, ky, 0)
    return np.array([
        [c + kx * kx * one_c, kx * ky * one_c, ky * s],
        [kx * ky * one_c, c + ky * ky * one_c, -kx * s],
        [-ky * s, kx * s, c],
    ], dtype=np.float64)


def basis_matrix(xdir, zdir) -> np.ndarray:
    """3x3 rotation whose COLUMNS are a right-handed basis: local +Z = ``zdir``,
    local +X = the part of ``xdir`` orthogonal to Z, +Y = Z × X. Elementwise (no
    BLAS). Used by the custom-origin FULL-basis orientation (a CGB Basis); falls
    back to :func:`axis_frame_matrix` if ``xdir`` is parallel to ``zdir``.
    Columns are the local axes in the parent/world frame, so ``[R | origin]`` maps
    local → parent (same convention as :func:`axis_frame_matrix`)."""
    z = np.asarray(zdir, dtype=np.float64)
    nz = math.sqrt(float(z[0] * z[0] + z[1] * z[1] + z[2] * z[2]))
    if nz < 1e-12:
        raise ValueError("basis_matrix: zero-length zdir")
    z = z / nz
    x = np.asarray(xdir, dtype=np.float64)
    d = float(x[0] * z[0] + x[1] * z[1] + x[2] * z[2])   # elementwise dot
    x = x - z * d                                        # orthogonalize X ⊥ Z
    nx = math.sqrt(float(x[0] * x[0] + x[1] * x[1] + x[2] * x[2]))
    if nx < 1e-12:                                       # xdir ∥ zdir → minimal
        return axis_frame_matrix(z)
    x = x / nx
    y = np.array([z[1] * x[2] - z[2] * x[1],             # Y = Z × X (elementwise)
                  z[2] * x[0] - z[0] * x[2],
                  z[0] * x[1] - z[1] * x[0]], dtype=np.float64)
    return np.array([[x[0], y[0], z[0]],
                     [x[1], y[1], z[1]],
                     [x[2], y[2], z[2]]], dtype=np.float64)


def export_transform(up_direction: str = "+Z", z_rotation_deg: int = 0,
                     scale: float = 1.0, origin: Optional[np.ndarray] = None) -> np.ndarray:
    """4x4 export placement: ``p' = scale · M · (p_source − origin)``.

    ``M`` reorients so ``up_direction`` → +Z (+ the z-rotation). ``scale`` converts
    units (USD mm→m = 0.001; STEP keeps mm = 1.0). ``origin`` (world/source point)
    shifts that point to the export origin — "local origin" export; ``None`` keeps
    the global origin. Column-convention (``p' = Mat · p``).
    """
    m3 = orientation_matrix(up_direction, z_rotation_deg)
    a = float(scale) * m3                                   # scalar * array (no matmul)
    out = np.eye(4, dtype=np.float64)
    out[:3, :3] = a
    if origin is not None:
        out[:3, 3] = -_mat3_vec(a, np.asarray(origin, dtype=np.float64))
    return out


def source_to_main_frame(up_direction: str = "+Z", z_rotation_deg: int = 0,
                         origin=None) -> Optional[np.ndarray]:
    """The root model's Source→Main RIGID frame ``p' = M·(p − origin)`` as a
    4x4, or ``None`` when it is the identity (nothing to bake/convert).

    This is THE frame the Main bake prepends to every free root (orientation +
    Z-origin datum, unit scale) — shared by the bake, the split/origin editors'
    recipe conversion (recipes are stored in the SOURCE frame but picked on the
    BAKED geometry), and asset generation's declared-frame matching.
    """
    ox, oy, oz = ((float(origin[0]), float(origin[1]), float(origin[2]))
                  if origin is not None else (0.0, 0.0, 0.0))
    if up_direction == "+Z" and int(z_rotation_deg) % 360 == 0 \
            and ox == 0.0 and oy == 0.0 and oz == 0.0:
        return None
    return export_transform(up_direction, int(z_rotation_deg), 1.0, (ox, oy, oz))


def frame_point(m4, p) -> tuple:
    """Apply a rigid 4x4 to a POINT (elementwise — no matmul)."""
    x, y, z = float(p[0]), float(p[1]), float(p[2])
    return tuple(float(m4[i][0]) * x + float(m4[i][1]) * y
                 + float(m4[i][2]) * z + float(m4[i][3]) for i in range(3))


def frame_dir(m4, d) -> tuple:
    """Apply a rigid 4x4's ROTATION to a direction (elementwise — no matmul)."""
    x, y, z = float(d[0]), float(d[1]), float(d[2])
    return tuple(float(m4[i][0]) * x + float(m4[i][1]) * y
                 + float(m4[i][2]) * z for i in range(3))


# --- Component-editor Transform math (per-body rigid transform) --------------
# Used by the op-sequence bake to resolve a BodyTransform (Orient then Translate)
# to a rigid 4x4. All elementwise (no BLAS ``@`` — VTK/pxr loaded).

_AXIS_VEC = {"+X": (1.0, 0.0, 0.0), "-X": (-1.0, 0.0, 0.0),
             "+Y": (0.0, 1.0, 0.0), "-Y": (0.0, -1.0, 0.0),
             "+Z": (0.0, 0.0, 1.0), "-Z": (0.0, 0.0, -1.0)}


def axis_target_vec(name: str):
    """A world-axis target string ("+Z"/"-X"…) → unit vector tuple."""
    return _AXIS_VEC[name]


def _norm3(v):
    n = math.sqrt(float(v[0] * v[0] + v[1] * v[1] + v[2] * v[2]))
    return n


def rot_about_axis(axis, angle_rad: float) -> np.ndarray:
    """3x3 Rodrigues rotation about a (unit-normalized) ``axis`` (elementwise)."""
    n = _norm3(axis)
    if n < 1e-12:
        return np.eye(3, dtype=np.float64)
    kx, ky, kz = axis[0] / n, axis[1] / n, axis[2] / n
    c, s = math.cos(angle_rad), math.sin(angle_rad)
    oc = 1.0 - c
    return np.array([
        [c + kx * kx * oc, kx * ky * oc - kz * s, kx * kz * oc + ky * s],
        [ky * kx * oc + kz * s, c + ky * ky * oc, ky * kz * oc - kx * s],
        [kz * kx * oc - ky * s, kz * ky * oc + kx * s, c + kz * kz * oc],
    ], dtype=np.float64)


def euler_matrix(a_deg: float, b_deg: float, c_deg: float) -> np.ndarray:
    """3x3 from intrinsic-free extrinsic Euler angles (deg) about world X, Y, Z:
    ``R = Rz(c) · Ry(b) · Rx(a)`` (elementwise)."""
    rx = rot_about_axis((1.0, 0.0, 0.0), math.radians(float(a_deg)))
    ry = rot_about_axis((0.0, 1.0, 0.0), math.radians(float(b_deg)))
    rz = rot_about_axis((0.0, 0.0, 1.0), math.radians(float(c_deg)))
    return _mat3_mul(rz, _mat3_mul(ry, rx))


def min_rotation(a, b) -> np.ndarray:
    """3x3 minimal rotation sending unit vector ``a`` → unit vector ``b``
    (Rodrigues; handles the (anti)parallel degeneracies). Elementwise."""
    na, nb = _norm3(a), _norm3(b)
    if na < 1e-12 or nb < 1e-12:
        return np.eye(3, dtype=np.float64)
    a = [a[0] / na, a[1] / na, a[2] / na]
    b = [b[0] / nb, b[1] / nb, b[2] / nb]
    d = a[0] * b[0] + a[1] * b[1] + a[2] * b[2]
    d = max(-1.0, min(1.0, d))
    if d > 1.0 - 1e-12:
        return np.eye(3, dtype=np.float64)
    axis = (a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2],
            a[0] * b[1] - a[1] * b[0])
    if _norm3(axis) < 1e-9:                       # antiparallel — any ⊥ axis
        ref = (1.0, 0.0, 0.0) if abs(a[0]) < 0.9 else (0.0, 1.0, 0.0)
        axis = (a[1] * ref[2] - a[2] * ref[1], a[2] * ref[0] - a[0] * ref[2],
                a[0] * ref[1] - a[1] * ref[0])
    return rot_about_axis(axis, math.acos(d))


def align_axes(primary_dir, primary_target, secondary_dir, secondary_target) -> np.ndarray:
    """Dual-axis alignment 3x3: PRIMARY body dir → primary target EXACTLY, then
    rotate about the primary target so the SECONDARY body dir's component ⊥ the
    primary target aligns to the secondary target's ⊥ component (fixes clocking).
    Elementwise (no BLAS)."""
    r1 = min_rotation(primary_dir, primary_target)
    s1 = _mat3_vec(r1, np.asarray(secondary_dir, dtype=np.float64))
    p = np.asarray(primary_target, dtype=np.float64)
    pn = _norm3(p)
    p = p / pn if pn > 1e-12 else p

    def _perp(v):
        dot = float(v[0] * p[0] + v[1] * p[1] + v[2] * p[2])
        return np.array([v[0] - dot * p[0], v[1] - dot * p[1], v[2] - dot * p[2]],
                        dtype=np.float64)

    u = _perp(s1)
    w = _perp(np.asarray(secondary_target, dtype=np.float64))
    un, wn = _norm3(u), _norm3(w)
    if un < 1e-9 or wn < 1e-9:                     # secondary parallel to primary
        return r1
    u, w = u / un, w / wn
    cosang = max(-1.0, min(1.0, float(u[0] * w[0] + u[1] * w[1] + u[2] * w[2])))
    cross = (u[1] * w[2] - u[2] * w[1], u[2] * w[0] - u[0] * w[2],
             u[0] * w[1] - u[1] * w[0])
    sign = 1.0 if (cross[0] * p[0] + cross[1] * p[1] + cross[2] * p[2]) >= 0 else -1.0
    r2 = rot_about_axis(p, sign * math.acos(cosang))
    return _mat3_mul(r2, r1)


def mat4_from_rot(r3) -> np.ndarray:
    out = np.eye(4, dtype=np.float64)
    for i in range(3):
        for j in range(3):
            out[i, j] = r3[i][j]
    return out


def mat4_translate(t) -> np.ndarray:
    out = np.eye(4, dtype=np.float64)
    out[0, 3], out[1, 3], out[2, 3] = float(t[0]), float(t[1]), float(t[2])
    return out


def mat4_orient_about(r3, pivot) -> np.ndarray:
    """4x4 that rotates by ``r3`` about ``pivot``: ``Tr(p)·[R]·Tr(-p)``."""
    negp = (-float(pivot[0]), -float(pivot[1]), -float(pivot[2]))
    return mat4_mul(mat4_translate(pivot),
                    mat4_mul(mat4_from_rot(r3), mat4_translate(negp)))
