"""Export a subtree of components to a STEP file, preserving colors.

- **Unfiltered** (nothing suppressed): one ``STEPCAFControl_Writer.Transfer(root_label)``
  from the source XCAF doc — preserves colors/names/hierarchy/instancing exactly
  as authored (verified in SolidWorks + Isaac). Only ONE Transfer per writer is
  safe in this binding.
- **Filtered** (some suppressed): build a fresh doc of only the surviving,
  world-positioned solids (+ their component colors) and Transfer that doc once.
  This EXCLUDES the suppressed geometry correctly.

  KNOWN LIMITATION (see .claude/docs/reference/occ-vtk-gotchas.md): the filtered/rebuilt-doc path's colors may not
  all display in SolidWorks (flat products vs. the source's authoring). The
  RemoveComponent-on-a-doc-copy alternative does NOT work — it fails to exclude and
  breaks instancing (verified: 619→554 instead of 564). Needs a proper fix:
  reconstruct a filtered ASSEMBLY (products + instancing + colors) rather than flat.

Output is AP214 (AUTOMOTIVE_DESIGN). OCC-only; kept out of the GUI layer.
"""

from __future__ import annotations

import logging

from OCC.Core.BRepBuilderAPI import BRepBuilderAPI_Transform
from OCC.Core.gp import gp_Trsf
from OCC.Core.IFSelect import IFSelect_RetDone
from OCC.Core.Interface import Interface_Static
from OCC.Core.Quantity import Quantity_Color, Quantity_TOC_RGB
from OCC.Core.STEPCAFControl import STEPCAFControl_Writer
from OCC.Core.STEPControl import STEPControl_AsIs
from OCC.Core.TDocStd import TDocStd_Document
from OCC.Core.TopAbs import TopAbs_FACE
from OCC.Core.TopExp import TopExp_Explorer
from OCC.Core.XCAFDoc import XCAFDoc_ColorSurf, XCAFDoc_DocumentTool

from ..model.orientation import mat4_mul

log = logging.getLogger(__name__)


def _to_trsf(matrix) -> gp_Trsf:
    m = matrix
    trsf = gp_Trsf()
    trsf.SetValues(
        float(m[0, 0]), float(m[0, 1]), float(m[0, 2]), float(m[0, 3]),
        float(m[1, 0]), float(m[1, 1]), float(m[1, 2]), float(m[1, 3]),
        float(m[2, 0]), float(m[2, 1]), float(m[2, 2]), float(m[2, 3]),
    )
    return trsf


def export_subtree_step(assembly, root_id: str, out_path: str, suppressed=None,
                        pre_transform=None, recolor: bool = False,
                        layers: bool = True) -> int:
    """Write the subtree rooted at ``root_id`` to ``out_path`` (AP214, with colors).

    Components suppressed — or under a suppressed node — are excluded. When a
    ``pre_transform`` (4x4, applied on top of each component's world placement, e.g.
    export orientation + local-origin shift) is given, or ``recolor`` is set (colors,
    incl. overrides, must come from ``Component.color``), the export uses the
    rebuilt-doc path so those take effect. Otherwise a single faithful
    ``Transfer(root_label)`` preserves the source authoring (colors/names/hierarchy/
    instancing) exactly. Returns the number of shape-bearing components written.

    ``layers`` MUST be False when the assembly came from a GENERATED (static/asset)
    ``.xbf``: those docs went through our own STEP round-trip, and transferring
    their layer section hard-crashes ``STEPCAFControl_Writer`` (0xC0000005 —
    uncatchable). The original source doc exports fine with layers on (verified),
    so the default stays True there. Nothing in this pipeline consumes layers.
    """
    root = assembly.get(root_id)
    if root is None:
        raise RuntimeError(f"Unknown component: {root_id}")

    suppressed = set(suppressed or ())
    subtree = set(assembly.descendants(root_id, include_self=True))
    if root_id in suppressed:
        raise RuntimeError("The exported node itself is suppressed — nothing to export.")
    excluded: set[str] = set()
    for s in suppressed:
        if s in subtree:
            excluded.update(assembly.descendants(s, include_self=True))

    Interface_Static.SetCVal("write.step.schema", "AP214")  # AUTOMOTIVE_DESIGN
    writer = STEPCAFControl_Writer()
    writer.SetColorMode(True)
    writer.SetNameMode(True)
    writer.SetLayerMode(layers)

    faithful = not excluded and pre_transform is None and not recolor
    if faithful:
        label = root.source_label
        if label is None or label.IsNull():
            raise RuntimeError("No source label to export from; re-open the file and retry.")
        if not writer.Transfer(label, STEPControl_AsIs):
            raise RuntimeError(f"STEP transfer failed for subtree {root_id}")
        n = sum(1 for c in assembly.components if c.component_id in subtree and c.shape is not None)
    else:
        n = _transfer_filtered_doc(assembly, subtree, excluded, writer, pre_transform)

    status = writer.Write(out_path)
    if status != IFSelect_RetDone:
        raise RuntimeError(f"STEP write failed (status={status}): {out_path}")
    log.info("Exported subtree %s (%d solids, %d excluded, faithful=%s) to %s",
             root_id, n, len(excluded), faithful, out_path)
    return n


def _transfer_filtered_doc(assembly, subtree: set, excluded: set, writer, pre_transform=None) -> int:
    """Build a fresh doc of surviving solids (+colors), placed via
    ``pre_transform · world_transform``; Transfer it once."""
    doc = TDocStd_Document("BinXCAF")
    shape_tool = XCAFDoc_DocumentTool.ShapeTool(doc.Main())
    color_tool = XCAFDoc_DocumentTool.ColorTool(doc.Main())

    added = 0
    for c in assembly.components:
        if not (c.component_id in subtree and c.component_id not in excluded and c.shape is not None):
            continue
        placement = c.transform
        if placement is not None and pre_transform is not None:
            placement = mat4_mul(pre_transform, placement)
        master = c.shape
        shape = master
        xform = None
        try:
            if placement is not None:
                xform = BRepBuilderAPI_Transform(master, _to_trsf(placement), True)
                shape = xform.Shape()
        except Exception as exc:  # noqa: BLE001
            log.warning("Transform for %s failed (%s); exporting untransformed.", c.component_id, exc)
            shape, xform = master, None
        label = shape_tool.AddShape(shape, False, True)
        if c.color is not None:
            qc = Quantity_Color(float(c.color[0]), float(c.color[1]), float(c.color[2]), Quantity_TOC_RGB)
            color_tool.SetColor(label, qc, XCAFDoc_ColorSurf)
            color_tool.SetColor(shape, qc, XCAFDoc_ColorSurf)
        # Per-FACE colors (multi-colored parts): map each styled master face to its
        # counterpart on the added (possibly transformed) shape and color it, so the
        # STEP writer emits per-face styles — matching the viewport/USD.
        if c.face_colors:
            exp = TopExp_Explorer(master, TopAbs_FACE)
            idx = -1
            while exp.More():
                idx += 1
                rgb = c.face_colors.get(idx)
                if rgb is not None:
                    mf = exp.Current()
                    face = xform.ModifiedShape(mf) if xform is not None else mf
                    qc = Quantity_Color(float(rgb[0]), float(rgb[1]), float(rgb[2]), Quantity_TOC_RGB)
                    color_tool.SetColor(face, qc, XCAFDoc_ColorSurf)
                exp.Next()
        added += 1

    if added == 0:
        raise RuntimeError("Everything in this subtree is suppressed — nothing to export.")
    if not writer.Transfer(doc, STEPControl_AsIs):
        raise RuntimeError("STEP transfer failed for the filtered document.")
    return added
