"""Hierarchy-preserving COMPOSED STEP export: all generated models re-assembled
into one scene, each occurrence placed at its pose from the root Main walk.

Construction (probe-verified pieces; the P-E2 synthetic probe validated the
graft primitives, and the real-fixture test drove the final design): the
compose doc's assembly structure is built EXPLICITLY from each model's walked
tree — ``AddShape(master, makeAssembly=False)`` per unique LEAF product,
``NewShape`` per unique ASSEMBLY product (deduped by ``product_entry`` so
instancing is preserved), and ``AddComponent(parent, child, relative_loc)``
mirroring the walk (relative = parent_world⁻¹·child_world, elementwise). We do
NOT use ``AddShape(root_compound, makeAssembly=True)``: it decomposes by shape
TOPOLOGY, which on real SolidWorks exports is deeper than the product tree
(nested compounds inside leaf products) — found on the e2e fixture.

Names go on every product AND instance label (unnamed instances export junk
``"=>"`` product names); base colors on the leaf products; per-FACE colors via
``AddSubShape(product_label, face)`` + ``SetColor(label)`` (coloring the bare
face shape does NOT stick — probe finding). Each occurrence is one
``AddComponent(scene_root, root_product, loc(W_occ))`` — N occurrences of one
prototype reference ONE grafted product. ONE ``Transfer(doc)`` (the known-safe
single-Transfer discipline), colors+names on, **layers OFF**.

Doc lifetime: the grafted TShapes belong to the source docs — every source
``Assembly`` must stay alive until ``Write`` returns (the caller holds them;
the compose CLI runs in its own subprocess so nothing lingers).

Qt-free; OCC only. Used by ``src/export/compose_cli.py``.
"""

from __future__ import annotations

import logging
from typing import List, Sequence, Tuple

log = logging.getLogger(__name__)


def _sanitize(name: str) -> str:
    return (name or "").strip() or "Scene"


def export_composed_step(entries: Sequence[Tuple], out_path: str,
                         scene_name: str = "Scene") -> int:
    """Compose ``entries = [(assembly, [(occurrence_name, world_4x4)])]`` —
    optionally 3-tuples with a per-model EXCLUDED cid set (suppressed
    subtrees; note exclusion is product-level, so a node excluded inside an
    instanced sub-assembly leaves every instance) — into one STEP. Returns the
    number of shape-bearing components written (counting every occurrence).
    Every ``assembly`` (and its ``.doc``) must stay referenced by the caller
    until this returns.
    """
    import numpy as np
    from OCC.Core.IFSelect import IFSelect_RetDone
    from OCC.Core.Interface import Interface_Static
    from OCC.Core.Quantity import Quantity_Color, Quantity_TOC_RGB
    from OCC.Core.STEPCAFControl import STEPCAFControl_Writer
    from OCC.Core.STEPControl import STEPControl_AsIs
    from OCC.Core.TDataStd import TDataStd_Name
    from OCC.Core.TDocStd import TDocStd_Document
    from OCC.Core.TopAbs import TopAbs_COMPOUND, TopAbs_COMPSOLID, TopAbs_FACE
    from OCC.Core.TopExp import TopExp_Explorer
    from OCC.Core.XCAFDoc import XCAFDoc_ColorSurf, XCAFDoc_DocumentTool

    from ..model.orientation import mat4_inv_rigid, mat4_mul
    from .restructure_build import _loc_from_matrix4

    def rgb(c):
        return Quantity_Color(float(c[0]), float(c[1]), float(c[2]),
                              Quantity_TOC_RGB)

    doc = TDocStd_Document("BinXCAF")
    st = XCAFDoc_DocumentTool.ShapeTool(doc.Main())
    ct = XCAFDoc_DocumentTool.ColorTool(doc.Main())
    scene_root = st.NewShape()
    TDataStd_Name.Set(scene_root, _sanitize(scene_name))

    written = 0
    for entry in entries:
        assembly, occurrences = entry[0], entry[1]
        excluded = set(entry[2]) if len(entry) > 2 and entry[2] else set()
        n_shapes = sum(1 for c in assembly.components
                       if c.shape is not None
                       and c.component_id not in excluded)
        prod_labels: dict = {}  # model product key -> compose product label

        def key_of(comp) -> str:
            return comp.product_entry or comp.label_entry or comp.component_id

        def build_product(comp):
            """Compose-doc product for ``comp``'s master — created ONCE per
            unique source product (instancing preserved); an assembly product
            gets its children attached on first creation only."""
            key = key_of(comp)
            lbl = prod_labels.get(key)
            if lbl is not None:
                return lbl
            if comp.shape is not None:  # LEAF (a compound stays ONE product)
                lbl = st.AddShape(comp.shape, False)
                if comp.color is not None:
                    ct.SetColor(lbl, rgb(comp.color), XCAFDoc_ColorSurf)
                # A COMPOUND leaf's product color does NOT survive the STEP
                # round trip (the writer styles its sub-solids; the reparse
                # style map keys on the master compound — fixture finding), so
                # style EVERY face: explicit face colors, base for the rest.
                # Simple solids recover via the instance color — faces only
                # where explicitly styled.
                fill = comp.color if comp.shape.ShapeType() in (
                    TopAbs_COMPOUND, TopAbs_COMPSOLID) else None
                if comp.face_colors or fill is not None:
                    exp = TopExp_Explorer(comp.shape, TopAbs_FACE)
                    idx = -1
                    while exp.More():
                        idx += 1
                        col = (comp.face_colors or {}).get(idx, fill)
                        if col is not None:
                            sub_lbl = st.AddSubShape(lbl, exp.Current())
                            if sub_lbl is not None and not sub_lbl.IsNull():
                                ct.SetColor(sub_lbl, rgb(col),
                                            XCAFDoc_ColorSurf)
                        exp.Next()
            else:  # ASSEMBLY node
                lbl = st.NewShape()
            TDataStd_Name.Set(lbl, comp.name)
            prod_labels[key] = lbl
            if comp.shape is None:
                w_inv = mat4_inv_rigid(comp.transform)
                for child in assembly.children_of(comp.component_id):
                    if child.component_id in excluded:
                        continue
                    ch_lbl = build_product(child)
                    rel = np.asarray(
                        mat4_mul(w_inv, child.transform), dtype=float)
                    inst = st.AddComponent(lbl, ch_lbl,
                                           _loc_from_matrix4(rel))
                    TDataStd_Name.Set(inst, child.name)
            return lbl

        roots = [c for c in assembly.components if c.parent_id is None]
        for root in roots:
            # Roots are authored at identity in generated models (design
            # frame); a non-identity root location would double-apply under
            # W_occ — fold it in instead.
            prod = build_product(root)
            root_w = np.asarray(root.transform, dtype=float)
            for occ_name, world4 in occurrences:
                m4 = np.asarray(mat4_mul(np.asarray(world4, dtype=float),
                                         root_w), dtype=float)
                inst = st.AddComponent(scene_root, prod, _loc_from_matrix4(m4))
                TDataStd_Name.Set(inst, occ_name if len(roots) == 1
                                  else f"{occ_name}/{root.name}")
        written += n_shapes * len(occurrences)

    st.UpdateAssemblies()
    Interface_Static.SetCVal("write.step.schema", "AP214")
    writer = STEPCAFControl_Writer()
    writer.SetColorMode(True)
    writer.SetNameMode(True)
    writer.SetLayerMode(False)  # baked-stage convention (see the crash matrix)
    if not writer.Transfer(doc, STEPControl_AsIs):
        raise RuntimeError("Composed STEP transfer failed.")
    if writer.Write(out_path) != IFSelect_RetDone:
        raise RuntimeError(f"Composed STEP write failed: {out_path}")
    log.info("Composed STEP: %d shape-bearing components -> %s",
             written, out_path)
    return written
