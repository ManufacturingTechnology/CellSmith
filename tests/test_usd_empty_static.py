"""Tier 1: an EMPTY model (Static when every top-level node is an asset or
suppressed) must still be WRITTEN by the composed USD exporter, overwriting any
previous export's content — never raise, never be skipped (a skipped Static
leaves a stale ``static_base.usd`` behind for ``static.usda`` to keep
referencing). See docs/src/AI/Reference/asset-splitting-and-compose.md.
"""

from __future__ import annotations

import pytest
from pxr import Usd, UsdGeom

from src.export.usd_writer import write_model_usd, write_override_wrapper
from src.model.assembly import Assembly
from src.model.component import Component


def _empty_static() -> Assembly:
    """The Stamping1 shape: one shapeless root, everything else pruned away."""
    asm = Assembly()
    asm.add(Component(component_id="c0001", name="Main Assembly"))
    return asm


def _mesh_count(path) -> int:
    stage = Usd.Stage.Open(str(path))
    return sum(1 for p in stage.Traverse() if p.IsA(UsdGeom.Mesh))


def test_empty_model_raises_by_default(tmp_path):
    with pytest.raises(RuntimeError, match="No meshed geometry"):
        write_model_usd(_empty_static(), str(tmp_path / "static_base.usd"))


def test_empty_model_overwrites_stale_content(tmp_path):
    base = tmp_path / "static_base.usd"
    wrapper = tmp_path / "static.usda"
    # A previous export, when Static still had content.
    stale = Usd.Stage.CreateNew(str(base))
    root = UsdGeom.Xform.Define(stale, "/Root")
    UsdGeom.Mesh.Define(stale, "/Root/OldPart")
    stale.SetDefaultPrim(root.GetPrim())
    stale.GetRootLayer().Save()
    del stale
    write_override_wrapper(str(base), str(wrapper))
    assert _mesh_count(wrapper) == 1

    n = write_model_usd(_empty_static(), str(base), allow_empty=True)

    assert n == 0
    stage = Usd.Stage.Open(str(base))
    assert stage.GetDefaultPrim().IsValid()   # the wrapper's reference resolves
    assert _mesh_count(base) == 0
    assert _mesh_count(wrapper) == 0          # stale geometry no longer composed
