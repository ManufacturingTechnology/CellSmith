"""Read a STEP file into an :class:`~src.model.assembly.Assembly`.

Uses ``STEPCAFControl_Reader`` + XCAF so we recover the *labeled assembly/product
structure* (component names + hierarchy + transforms), not just raw geometry.
Falls back to synthesised labels when names are missing/useless so the user can
still group components.

This module (with tessellate.py) is the only place that imports OpenCASCADE.
"""

from __future__ import annotations

import logging
import os
from typing import Optional

import numpy as np

from OCC.Core.BRepBndLib import brepbndlib
from OCC.Core.Bnd import Bnd_Box
from OCC.Core.IFSelect import IFSelect_RetDone
from OCC.Core.Quantity import Quantity_Color, Quantity_TOC_RGB
from OCC.Core.STEPCAFControl import STEPCAFControl_Reader
from OCC.Core.STEPConstruct import STEPConstruct_Styles
from OCC.Core.StepVisual import StepVisual_ColourRgb
from OCC.Core.TransferBRep import transferbrep
from OCC.Core.TCollection import TCollection_AsciiString
from OCC.Core.TDF import TDF_Label, TDF_LabelSequence, TDF_Tool
from OCC.Core.TDocStd import TDocStd_Document
from OCC.Core.TopAbs import (
    TopAbs_COMPOUND, TopAbs_COMPSOLID, TopAbs_FACE, TopAbs_SHELL, TopAbs_SOLID,
)
from OCC.Core.TopExp import TopExp_Explorer
from OCC.Core.TopLoc import TopLoc_Location
from OCC.Core.TopTools import TopTools_IndexedMapOfShape
from OCC.Core.XCAFDoc import XCAFDoc_ColorGen, XCAFDoc_ColorSurf, XCAFDoc_DocumentTool

from ..model.assembly import Assembly
from ..model.component import Component
from .tessellate import tessellate_shape

log = logging.getLogger(__name__)


def _label_name(label: TDF_Label) -> Optional[str]:
    """Return the label's name via pythonocc's convenience accessor, or None.

    (Direct ``FindAttribute(TDataStd_Name...)`` needs a handle out-param that this
    binding doesn't accept, so use the SWIG-added ``GetLabelName`` helper.)
    """
    try:
        name = label.GetLabelName()
    except Exception:  # noqa: BLE001 - missing/odd name attr shouldn't abort the walk
        return None
    return name if name and name.strip() else None


def _label_entry(label: TDF_Label) -> str:
    """TDF entry string — the stable label identity (see Component.label_entry).

    Concrete ``TCollection_AsciiString`` out-param propagates in this binding
    (same pattern as ``assets_build._entry``).
    """
    s = TCollection_AsciiString()
    TDF_Tool.Entry(label, s)
    return s.ToCString()


def _trsf_to_matrix(location: TopLoc_Location) -> np.ndarray:
    """Convert an OCC location into a 4x4 row-major numpy matrix."""
    trsf = location.Transformation()
    m = np.eye(4)
    for r in range(3):
        for c in range(3):
            m[r, c] = trsf.Value(r + 1, c + 1)
        m[r, 3] = trsf.Value(r + 1, 4)
    return m


def _is_useless_name(name: Optional[str]) -> bool:
    """True if a name is missing or a generic auto-generated placeholder."""
    if not name or not name.strip():
        return True
    stripped = name.strip().lower()
    # SolidWorks/OCC dumps like "Solid1", "Solid 23", "COMPOUND", "Body1".
    for prefix in ("solid", "body", "compound", "part", "shape"):
        rest = stripped.replace(prefix, "", 1).strip()
        if stripped.startswith(prefix) and (rest == "" or rest.isdigit()):
            return True
    return False


def _live(x) -> bool:
    """True if an OCC handle/object is present (tolerates non-Handle returns)."""
    if x is None:
        return False
    try:
        return not x.IsNull()
    except AttributeError:
        return True  # concrete STEP entity (not a Handle) -> present


def _colour_to_rgb(colour):
    """StepVisual_Colour -> (r, g, b) in 0..1, or None."""
    if not _live(colour):
        return None
    qc = Quantity_Color()
    try:
        if STEPConstruct_Styles.DecodeColor(colour, qc):
            return (qc.Red(), qc.Green(), qc.Blue())
    except Exception:  # noqa: BLE001
        pass
    rgb = StepVisual_ColourRgb.DownCast(colour)
    if _live(rgb):
        return (rgb.Red(), rgb.Green(), rgb.Blue())
    return None


def _decode_style_color(styled):
    """Walk a StyledItem's presentation chain to its surface fill color (0..1 RGB).

    Return-value accessors only (the ``GetColors`` convenience uses handle
    out-params that don't propagate in this binding).
    """
    for i in range(1, styled.NbStyles() + 1):
        psa = styled.StylesValue(i)                       # PresentationStyleAssignment
        for j in range(1, psa.NbStyles() + 1):
            sel = psa.StylesValue(j)                      # PresentationStyleSelect
            try:
                ssu = sel.SurfaceStyleUsage()
            except Exception:  # noqa: BLE001 - not a surface style
                continue
            if not _live(ssu):
                continue
            side = ssu.Style()                            # SurfaceSideStyle
            if not _live(side):
                continue
            for k in range(1, side.NbStyles() + 1):
                elem = side.StylesValue(k)                # SurfaceStyleElementSelect
                try:
                    fa = elem.SurfaceStyleFillArea()
                except Exception:  # noqa: BLE001
                    continue
                if not _live(fa):
                    continue
                fas = fa.FillArea()                       # FillAreaStyle
                if not _live(fas):
                    continue
                for m in range(1, fas.NbFillStyles() + 1):
                    fsel = fas.FillStylesValue(m)         # FillStyleSelect
                    try:
                        fac = fsel.FillAreaStyleColour()
                    except Exception:  # noqa: BLE001
                        continue
                    if not _live(fac):
                        continue
                    rgb = _colour_to_rgb(fac.FillColour())
                    if rgb:
                        return rgb
    return None


def _iter_style_colors(reader):
    """Yield ``(shape, rgb)`` for every decodable styled item in the STEP.

    The presentation (StepVisual) layer is only reachable from the live STEP
    reader's work session — NOT from a loaded ``.xbf`` — so this runs at parse
    time only. ``shape`` is the transferred OCC shape the style is attached to
    (a solid/compound for a part appearance, a face for a per-face override).
    """
    try:
        ws = reader.Reader().WS()
        tp = ws.TransferReader().TransientProcess()
        styles = STEPConstruct_Styles(ws)
        if not styles.LoadStyles():
            return
    except Exception as exc:  # noqa: BLE001
        log.warning("Low-level style color extraction unavailable: %s", exc)
        return

    for i in range(1, styles.NbStyles() + 1):
        styled = styles.Style(i)
        rgb = _decode_style_color(styled)
        if rgb is None:
            continue
        try:
            shape = transferbrep.ShapeResult(tp, styled.Item())
        except Exception:  # noqa: BLE001
            continue
        if shape is None or shape.IsNull():
            continue
        yield shape, rgb


def _inject_style_colors(reader, doc) -> int:
    """Recover colors via the style reader and set them on solids in ``doc``.

    Used when the CAF color reader failed. Sets instance colors on the shapes so
    display (GetInstanceColor), the .xbf cache, and STEP export all get them.
    Returns the number of solids colored.
    """
    color_tool = XCAFDoc_DocumentTool.ColorTool(doc.Main())
    injected = 0
    for shape, rgb in _iter_style_colors(reader):
        qc = Quantity_Color(float(rgb[0]), float(rgb[1]), float(rgb[2]), Quantity_TOC_RGB)
        try:
            color_tool.SetColor(shape, qc, XCAFDoc_ColorSurf)
            injected += 1
        except Exception:  # noqa: BLE001
            continue
    return injected


def _build_style_color_maps(reader):
    """Two shape→RGB maps from ONE pass over the style layer.

    - ``part_colors``: top-level shapes (SOLID / COMPOUND / COMPSOLID / SHELL) → the
      part's BASE appearance. SHELL is included so open-shell (sheet) bodies get a
      base color too. Used for the single representative color per component.
    - ``face_colors``: individual FACEs → their per-face color. SolidWorks emits
      per-face styling (decals, text, colored patches) as thousands of face-level
      styled items; these let the renderer paint each face its own color instead of
      collapsing the part to one color.

    Both are ``(IndexedMapOfShape, [rgb])`` (first style wins per shape) or ``None``.
    Returns ``(part_colors, face_colors)``.
    """
    part_map, part_rgbs = TopTools_IndexedMapOfShape(), []
    face_map, face_rgbs = TopTools_IndexedMapOfShape(), []
    try:
        for shape, rgb in _iter_style_colors(reader):
            st = shape.ShapeType()
            if st in (TopAbs_COMPOUND, TopAbs_COMPSOLID, TopAbs_SOLID, TopAbs_SHELL):
                idx = part_map.Add(shape)
                if idx > len(part_rgbs):
                    part_rgbs.append(rgb)
            elif st == TopAbs_FACE:
                idx = face_map.Add(shape)
                if idx > len(face_rgbs):
                    face_rgbs.append(rgb)
    except Exception as exc:  # noqa: BLE001 - never let color recovery abort a parse
        log.warning("Style color maps unavailable: %s", exc)
    part_colors = (part_map, part_rgbs) if part_rgbs else None
    face_colors = (face_map, face_rgbs) if face_rgbs else None
    log.info("Recovered %d part-colors and %d per-face colors from the style layer.",
             len(part_rgbs), len(face_rgbs))
    return part_colors, face_colors


def _part_color(part_colors, master_shape):
    """Look up the part-appearance RGB for ``master_shape``, or ``None``."""
    if part_colors is None or master_shape is None or master_shape.IsNull():
        return None
    smap, rgbs = part_colors
    idx = smap.FindIndex(master_shape)
    if idx > 0:
        return rgbs[idx - 1]
    return None


def _face_colors_for(face_colors, master_shape):
    """Sparse ``{face_index: rgb}`` for a leaf's styled faces, or ``None``.

    Face index is the 0-based ``TopExp_Explorer`` enumeration order over
    ``master_shape`` — the SAME order tessellation uses — so the render layer can
    map each triangle's source face to its color.
    """
    if face_colors is None or master_shape is None or master_shape.IsNull():
        return None
    smap, rgbs = face_colors
    out: dict = {}
    idx = -1
    exp = TopExp_Explorer(master_shape, TopAbs_FACE)
    while exp.More():
        idx += 1
        i = smap.FindIndex(exp.Current())
        if i > 0:
            out[idx] = rgbs[i - 1]
        exp.Next()
    return out or None


def _dominant_color(face_colors_map):
    """Most frequent color among a leaf's per-face colors (base for unstyled faces)."""
    if not face_colors_map:
        return None
    counts: dict = {}
    for rgb in face_colors_map.values():
        key = tuple(round(c * 255) for c in rgb)
        counts[key] = counts.get(key, 0) + 1
    best = max(counts, key=counts.get)
    return (best[0] / 255.0, best[1] / 255.0, best[2] / 255.0)


def _transfer(path: str, with_colors: bool):
    """Read + transfer ``path`` into a fresh XCAF document.

    Returns ``(doc, colors_ok)``. On the OCCT "Color out" bug (only when
    ``with_colors``) returns ``(None, False)`` so the caller can retry color-free.
    A fresh reader/doc per attempt avoids reusing partially-populated state.
    """
    reader = STEPCAFControl_Reader()
    reader.SetNameMode(True)
    reader.SetColorMode(with_colors)
    reader.SetLayerMode(False)

    status = reader.ReadFile(path)
    if status != IFSelect_RetDone:
        raise RuntimeError(f"Failed to read STEP file (status={status}): {path}")

    # Plain string (NOT TCollection_*, and no XCAFApp/InitDocument) — the other
    # patterns hard-crash this pythonocc build during document construction. The
    # "BinXCAF" format label lets the doc be written straight to the .xbf cache.
    doc = TDocStd_Document("BinXCAF")
    try:
        if not reader.Transfer(doc):
            raise RuntimeError(f"Failed to transfer STEP data into XCAF document: {path}")
    except (IndexError, RuntimeError) as exc:
        # OCC raises Standard_OutOfRange ("Color out") as IndexError here.
        if with_colors:
            log.warning("Color read failed (%s); retrying without colors.", exc)
            return reader, None, False
        raise
    return reader, doc, with_colors


def _doc_from_step(path: str):
    """Transfer a STEP file into an XCAF doc, with color fallback + recovery.

    Some SolidWorks STEP files trip an OCCT bug (Standard_OutOfRange "Color out")
    in the CAF color reader. We fall back to a color-free transfer and then
    recover colors via the lower-level style reader, injecting them into the
    document's color tool so display, cache, and export all pick them up.

    Returns ``(doc, colors_ok, part_colors, face_colors)``: ``part_colors`` maps
    master shapes to their base part color (preferred over per-instance overrides),
    and ``face_colors`` maps individual faces to per-face colors for multi-colored
    parts. Either is ``None`` when the style layer is unavailable.
    """
    reader, doc, colors_ok = _transfer(path, with_colors=True)
    if doc is None:
        reader, doc, colors_ok = _transfer(path, with_colors=False)
        injected = _inject_style_colors(reader, doc)
        colors_ok = injected > 0
        if injected:
            log.info("Recovered %d styled colors via the low-level style reader.", injected)
    part_colors, face_colors = _build_style_color_maps(reader)
    return doc, colors_ok, part_colors, face_colors


def _build_assembly(doc, colors_ok: bool, path: str, tessellate: bool, part_colors=None,
                    face_colors=None) -> Assembly:
    """Walk an XCAF document into an :class:`Assembly` (shared by parse + cache).

    ``part_colors``/``face_colors`` (from :func:`_build_style_color_maps`, parse-time
    only) give the leaf's base color and its per-face colors respectively.
    """
    shape_tool = XCAFDoc_DocumentTool.ShapeTool(doc.Main())
    color_tool = XCAFDoc_DocumentTool.ColorTool(doc.Main()) if colors_ok else None

    assembly = Assembly(source_path=path)
    assembly.doc = doc  # keep the doc alive so source_label refs stay valid
    counter = {"n": 0}

    free_shapes = TDF_LabelSequence()
    shape_tool.GetFreeShapes(free_shapes)
    # Labels from Value(i) are references INTO the sequence — park it on the
    # assembly so the roots' source_labels can't dangle (see Assembly._label_seqs).
    assembly._label_seqs.append(free_shapes)

    identity = TopLoc_Location()
    for i in range(1, free_shapes.Length() + 1):
        _walk(free_shapes.Value(i), None, identity, shape_tool, color_tool, assembly,
              counter, tessellate, part_colors, face_colors)

    if len(assembly) == 0:
        raise RuntimeError(f"No components found in: {path}")

    n_unnamed = len(assembly.unnamed)
    if n_unnamed:
        log.warning(
            "%d/%d components had missing/generic names; used fallback labels.",
            n_unnamed,
            len(assembly),
        )
    if not colors_ok:
        log.warning("Colors unavailable for this file; components render neutral grey.")

    return assembly


def read_step(path: str, tessellate: bool = True) -> Assembly:
    """Parse a STEP file directly into an :class:`Assembly` (no cache)."""
    if not os.path.isfile(path):
        raise FileNotFoundError(f"STEP file not found: {path}")
    doc, colors_ok, part_colors, face_colors = _doc_from_step(path)
    return _build_assembly(doc, colors_ok, path, tessellate, part_colors, face_colors)


def load_model(path: str, tessellate: bool = False, use_cache: bool = True,
               variant: str | None = None, stage: str | None = None) -> Assembly:
    """Load a model stage of ``path``, using the sibling ``.xbf`` caches.

    ``(variant, stage)`` names the geometry: variant = the model's cache dir
    (``ROOT_VARIANT``/"static"/"asset-{slug}"), stage = ``"source"`` (the
    model's input) or ``"main"`` (after its own edits/transform — what the GUI
    displays). Defaults to the root model's SOURCE stage.

    Only the root SOURCE stage is ever parsed from the STEP (first open, slow,
    writes the cache; later opens read it in seconds). EVERY other stage is an
    explicit artifact of a bake/generation — a missing/stale one raises
    ``FileNotFoundError`` instead of being silently recreated.
    """
    if not os.path.isfile(path):
        raise FileNotFoundError(f"File not found: {path}")

    # Imported here so a headless/OCC-only context can still use read_step.
    from . import cache

    if variant is None:
        variant = cache.ROOT_VARIANT
    if stage is None:
        stage = cache.STAGE_SOURCE

    if not (variant == cache.ROOT_VARIANT and stage == cache.STAGE_SOURCE):
        if not cache.cache_is_fresh(path, variant, stage):
            raise FileNotFoundError(
                f"Model cache '{variant}/{stage}' is missing or stale for {path} — "
                "rebuild/regenerate it first.")
        doc = cache.load_cache(path, variant, stage)
        assembly = _build_assembly(doc, True, path, tessellate)
        n = cache.load_color_sidecar(assembly, path, variant, stage)
        log.info("Loaded %d components from cache %s (%d sidecar colors)",
                 len(assembly), cache.cache_path_for(path, variant, stage), n)
        return assembly

    src = (cache.ROOT_VARIANT, cache.STAGE_SOURCE)
    if use_cache and cache.cache_is_fresh(path, *src):
        try:
            doc = cache.load_cache(path, *src)
            assembly = _build_assembly(doc, True, path, tessellate)
            # Reapply the part-appearance colors resolved at parse time (the STEP
            # style layer isn't in the .xbf, so they'd otherwise revert to the CAF
            # per-instance colors).
            n = cache.load_color_sidecar(assembly, path, *src)
            log.info("Loaded %d components from cache %s (%d sidecar colors)",
                     len(assembly), cache.cache_path_for(path, *src), n)
            return assembly
        except Exception as exc:  # noqa: BLE001 - corrupt/stale cache -> reparse
            log.warning("Cache load failed (%s); reparsing STEP.", exc)

    doc, colors_ok, part_colors, face_colors = _doc_from_step(path)
    assembly = _build_assembly(doc, colors_ok, path, tessellate, part_colors, face_colors)
    if use_cache:
        try:
            cache.save_cache(doc, path, *src)
            cache.save_color_sidecar(assembly, path, *src)
        except Exception as exc:  # noqa: BLE001 - cache write is best-effort
            log.warning("Could not write cache for %s: %s", path, exc)
    return assembly


def _walk(label, parent_id, parent_loc, shape_tool, color_tool, assembly, counter, tessellate,
          part_colors=None, face_colors=None) -> None:
    """Recursively add ``label`` and its descendants to ``assembly``.

    ``parent_loc`` is the accumulated world location of the parent assembly. We
    multiply it by each label's own location so leaf geometry ends up in world
    coordinates (OCC's ``GetShape`` only positions relative to the immediate
    parent, so nested parts need the full chain). Referenced shapes resolve to
    their master definition (local geometry + master name).
    """
    ref_label = TDF_Label()
    prototype = None
    if shape_tool.IsReference(label) and shape_tool.GetReferredShape(label, ref_label):
        # Prefer the REFERRED (product/master) name — that's the real part name
        # SolidWorks/Isaac show. The instance label is often a generic "NAUO#"
        # occurrence id, so use it only as a fallback. The referred name is also the
        # PROTOTYPE (master) this node instantiates — captured for review.
        name = _label_name(ref_label) or _label_name(label)
        source_label = ref_label
        prototype = _label_name(ref_label)
        product_entry = _label_entry(ref_label)
    else:
        name = _label_name(label)
        source_label = label
        product_entry = None  # own entry; filled below once computed
    # Stable identity strings for Restructure (see Component docstrings): the
    # instance entry detects multi-instanced subtrees (same label walked twice);
    # the product entry detects shared products used as move targets.
    label_entry = _label_entry(label)
    if product_entry is None:
        product_entry = label_entry

    counter["n"] += 1
    cid = f"c{counter['n']:04d}"

    raw_name = name
    fallback = _is_useless_name(raw_name)
    display_name = (raw_name.strip() if raw_name and raw_name.strip() else "") or f"Component {counter['n']}"

    # Accumulate world location: parent chain * this label's own location.
    world_loc = parent_loc.Multiplied(shape_tool.GetLocation(label))
    transform = _trsf_to_matrix(world_loc)

    if shape_tool.IsAssembly(source_label):
        # Grouping node: no geometry of its own, recurse into components.
        component = Component(
            component_id=cid,
            name=display_name,
            shape=None,
            transform=transform,
            parent_id=parent_id,
            name_is_fallback=fallback,
            source_label=label,
            prototype=prototype,
            label_entry=label_entry,
            product_entry=product_entry,
        )
        assembly.add(component)

        children = TDF_LabelSequence()
        shape_tool.GetComponents(source_label, children)
        # Children's labels reference INTO this sequence — park it on the assembly
        # so their source_labels stay valid after this frame returns (test1: 12k of
        # 20k labels dangled to NULL otherwise; see Assembly._label_seqs).
        assembly._label_seqs.append(children)
        for i in range(1, children.Length() + 1):
            _walk(children.Value(i), cid, world_loc, shape_tool, color_tool, assembly,
                  counter, tessellate, part_colors, face_colors)
        return

    # Leaf component. Use MASTER-local geometry (source_label) and position it via
    # the accumulated ``transform``; the located instance shape is used only for
    # per-instance color lookup.
    shape = shape_tool.GetShape(source_label)
    located_shape = shape_tool.GetShape(label)
    # Prefer the master part-appearance color (what SolidWorks/Isaac display) over
    # the CAF per-instance color, which is often a whole-part appearance OVERRIDE on
    # a recoloured occurrence. Fall back to the instance color when the part has no
    # top-level style (e.g. only inherited/face colors).
    per_face = _face_colors_for(face_colors, shape)
    color = _part_color(part_colors, shape)
    if color is None:
        # No top-level style: use the dominant per-face color (so open-shell/sheet
        # bodies aren't grey), else fall back to the CAF per-instance color.
        color = _dominant_color(per_face) or _read_color(color_tool, located_shape, label, ref_label)
    component = Component(
        component_id=cid,
        name=display_name,
        shape=shape,
        transform=transform,
        parent_id=parent_id,
        name_is_fallback=fallback,
        color=color,
        face_colors=per_face,
        source_label=label,
        prototype=prototype,
        label_entry=label_entry,
        product_entry=product_entry,
    )

    if fallback and shape is not None:
        # Geometry-derived hint so the user has something to grab onto.
        component.name = f"{display_name} {_bbox_hint(shape)}"

    if tessellate and shape is not None:
        try:
            verts, faces, tri_faces = tessellate_shape(shape)
            component.vertices = verts
            component.faces = faces
            component.tri_faces = tri_faces
            if len(verts) == 0:
                log.warning("Component %s (%s) tessellated to 0 triangles.", cid, display_name)
        except Exception as exc:  # noqa: BLE001 - fail loud per-component, keep loading
            log.error("Tessellation failed for %s (%s): %s", cid, display_name, exc)

    assembly.add(component)


def _read_color(color_tool, shape, label, ref_label):
    """Best-effort per-component RGB (0..1) from the XCAF color tool.

    Returns ``None`` when colors weren't read (color_tool is None) or none is
    assigned. Tries the per-instance color first (how SolidWorks usually assigns
    it), then the surface/generic color on the instance and referred labels.
    """
    if color_tool is None:
        return None
    c = Quantity_Color(0.5, 0.5, 0.5, Quantity_TOC_RGB)

    def _ok(fn, *args) -> bool:
        # Overload resolution can vary between binding builds; never let a color
        # probe abort the whole walk (esp. on colorless files loaded from cache).
        try:
            return bool(fn(*args, c))
        except Exception:  # noqa: BLE001
            return False

    for ctype in (XCAFDoc_ColorSurf, XCAFDoc_ColorGen):
        if shape is not None and _ok(color_tool.GetInstanceColor, shape, ctype):
            return (c.Red(), c.Green(), c.Blue())
    for lab in (label, ref_label):
        if lab is None or lab.IsNull():
            continue
        for ctype in (XCAFDoc_ColorSurf, XCAFDoc_ColorGen):
            if _ok(color_tool.GetColor, lab, ctype):
                return (c.Red(), c.Green(), c.Blue())
    return None


def _bbox_hint(shape) -> str:
    """A short geometry-derived tag (bbox centroid) for fallback labeling."""
    box = Bnd_Box()
    brepbndlib.Add(shape, box)
    if box.IsVoid():
        return "@?"
    xmin, ymin, zmin, xmax, ymax, zmax = box.Get()
    cx, cy, cz = (xmin + xmax) / 2, (ymin + ymax) / 2, (zmin + zmax) / 2
    return f"@({cx:.0f},{cy:.0f},{cz:.0f})"
