"""Hello-world for the CI-eligible tier.

Everything here must run in a Linux container with no GPU and no display. This
file is the canary: if it fails, the harness itself is broken, not the app.
"""

from __future__ import annotations

import os
import sys

import pytest


def test_hello_ci() -> None:
    """The suite runs at all."""
    assert True


def test_python_is_312() -> None:
    """The env pin is 3.12 (PySide6/pyvista wheels lag on newer)."""
    assert sys.version_info[:2] == (3, 12), f"expected 3.12, got {sys.version_info[:2]}"


def test_core_imports_are_available() -> None:
    """The layers this project is built on import without a display.

    Deliberately does NOT import ``src`` - this tier is about the environment.
    """
    import numpy  # noqa: F401
    import pydantic  # noqa: F401
    from OCC.Core.gp import gp_Pnt  # noqa: F401
    from pxr import Usd  # noqa: F401

    assert gp_Pnt(1.0, 2.0, 3.0).X() == pytest.approx(1.0)


def test_occ_makes_a_solid_with_the_right_volume() -> None:
    """A real (tiny) OCC computation - the Tier-1 shape most probes take."""
    from OCC.Core.BRepGProp import brepgprop
    from OCC.Core.BRepPrimAPI import BRepPrimAPI_MakeBox
    from OCC.Core.GProp import GProp_GProps

    box = BRepPrimAPI_MakeBox(10.0, 20.0, 30.0).Shape()
    props = GProp_GProps()
    brepgprop.VolumeProperties(box, props)
    assert props.Mass() == pytest.approx(6000.0, rel=1e-9)


def test_qt_constructs_offscreen(qapp) -> None:
    """Qt works with no display - the precondition for every visual test."""
    assert qapp.platformName() == "offscreen"


def test_fonts_were_registered(font_families) -> None:
    """The offscreen platform ships zero fonts; conftest must fix that.

    Without this, captured widget text is tofu boxes and no golden image of a
    widget is meaningful.
    """
    assert font_families, (
        "no fonts registered - captured text would render as boxes. "
        "Add a font path for this platform in tests/conftest.py::_FONT_CANDIDATES"
    )


@pytest.mark.gl
def test_offscreen_gl_renders_and_screenshots(artifacts_dir) -> None:
    """VTK renders offscreen and the PNG is non-trivial.

    Marked ``gl``: works headless, but on Linux needs Mesa (``LIBGL_ALWAYS_SOFTWARE=1``)
    and possibly Xvfb. Still CI-eligible - ``gl`` is not ``local_only``.
    """
    import numpy as np
    import pyvista as pv

    pv.OFF_SCREEN = True
    pl = pv.Plotter(off_screen=True, window_size=(200, 150))
    pl.add_mesh(pv.Cube(), color="orange", show_edges=True)
    pl.camera_position = "iso"  # pinned, not left to chance
    out = artifacts_dir / "hello_gl.png"
    pl.screenshot(str(out))
    pl.close()

    assert out.exists(), "no screenshot written"
    from PIL import Image

    arr = np.asarray(Image.open(out).convert("RGB"))
    assert arr.shape == (150, 200, 3)
    # A blank frame is the classic false pass: require real variation.
    assert arr.std() > 5.0, f"frame looks blank (std={arr.std():.2f})"


@pytest.mark.local_only
def test_hello_local_only() -> None:
    """Hello-world for the full-suite-only tier.

    Excluded from ``make test-ci``. Real members of this tier: interactive camera
    behavior, depth-peeling fidelity, hover latency, real-driver GL differences.
    """
    assert os.environ.get("QT_QPA_PLATFORM") == "offscreen"
