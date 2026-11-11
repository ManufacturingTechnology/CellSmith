# pythonocc / OpenCASCADE / VTK gotchas

The hard-won, must-respect rules for pythonocc-core 7.9.3 / OCCT 7.9 and the VTK render path: XCAF doc creation, output-parameter handles, color reading, per-face colors, the **no-BLAS-matmul** ban, STEP export/layer crash matrices, restructure/compose surgery facts, doc/label lifetime traps, and GL teardown. Read before touching any OCC, XCAF-surgery, STEP-export, or VTK-geometry code — several of these cost days to rediscover. Verify against `src/`; may lag.

---

## pythonocc / OpenCASCADE gotchas (HARD-WON — respect these)
This binding (pythonocc-core 7.9.3 / OCCT 7.9) has sharp edges that cost real time:
- **Create XCAF docs as `TDocStd_Document("BinXCAF")` — a plain str.** Using a
  `TCollection_AsciiString`/`ExtendedString` wrapper, or `XCAFApp_Application` +
  `InitDocument`, **hard-crashes** the process (no Python traceback).
- **`TDocStd_Application.SaveAs` REFUSES a document the application never opened** —
  status `(3, '')` plus the stderr line *"this document has not yet been opened by any
  application"*, and no file is written. A doc constructed by hand
  (`TDocStd_Document("BinXCAF")` + `XCAFDoc_DocumentTool.ShapeTool(...).AddShape(...)`) is
  **not** registered with the app; only one that a `STEPCAFControl` reader `Transfer`-ed into,
  or that came from `app.Open`, is. So a probe that wants to exercise the real `.xbf` write
  path must go through `reader._doc_from_step` → `cache.save_cache`, not build its own doc.
  (Note `_doc_from_step` returns **four** values: `(doc, colors_ok, part_colors,
  face_colors)`.) → **CS-150**.
- **Output-parameter handles don't propagate to Python.** `TDocStd_Application.Open`
  *returns* the loaded doc (the passed handle stays empty). `GetColors` and
  `XCAFDoc_ColorTool.GetColor` (**every** overload — 2-arg, 3-arg w/ `Quantity_Color`,
  AND 3-arg w/ `TDF_Label` colour-label out-param) all `TypeError` — do NOT rely on
  them; there is NO way to read a color off a shape *label*. `GetInstanceColor(shape,
  type, Quantity_Color)` (concrete out-param) DOES work. `IsSet(label, type)` works
  (tells you a color exists, but not its value).
- **Colors** (read per-component via `GetInstanceColor`, but mind two traps):
  1. Some files trip an OCCT bug — `Standard_OutOfRange: "Color out"` in
     `STEPCAFControl_Reader::Transfer` with color mode on (all flag combos) — so
     parsing does a **color fallback**: try with colors, on failure retry color-free,
     then recover via the `StepVisual` presentation traversal (`_inject_style_colors`).
  2. **`GetInstanceColor` returns the per-instance appearance, which SolidWorks often
     uses as a whole-part OVERRIDE on a recoloured occurrence — hiding the real part
     color** (e.g. test2 `M-20iD25 axis2`: instance = periwinkle override, but the part
     is yellow; `axis4` has no override so it read correctly). SolidWorks/Isaac display
     the PART appearance. Fix (`reader._build_style_color_maps`/`_part_color`): at parse
     time, walk the `StepVisual` styles (`_iter_style_colors`), keep those whose
     `TransferBRep.ShapeResult` is a top-level **SOLID/COMPOUND/COMPSOLID/SHELL** (= the
     base part color, one per master), and PREFER that over `GetInstanceColor`; fall
     back to the dominant per-face color, then the instance color.
  3. **Per-FACE colors** (multi-colored parts — decals, text, colored patches): SolidWorks
     exports these as thousands of face-level `STYLED_ITEM → ADVANCED_FACE` fill styles
     (test1 has 112k, palette of 175). `_build_style_color_maps` also collects the
     **FACE** styled items into a face→rgb map; `_face_colors_for` maps them onto each
     leaf's faces (by `TopExp` face-enum order) as a sparse `Component.face_colors`
     `{face_index: rgb}`. Tessellation (`tessellate_shape`) returns a per-triangle
     source-face index (`Component.tri_faces`), and `mesh_ops.build_combined` paints each
     triangle its face's color (per-CELL RGBA) — so a black plate with a gray patch and
     yellow/white text renders correctly instead of collapsing to one color. Unstyled
     faces fall back to the base `color`. The style layer is NOT in the `.xbf`, so both
     base + per-face colors are persisted in the **color sidecar** (v4: `{cid: {base,
     faces}}`) and `tri_faces` in the mesh cache (`mesh-v2-*`); the source doc stays
     pristine so the faithful full-copy STEP export is unaffected.
- **No numpy/BLAS matmul in the render path.** `points @ M` triggers a delay-load
  DLL conflict with VTK's DLLs (`0xC06D007F`) once VTK is loaded. Apply transforms
  via VTK's `actor.user_matrix` or **elementwise** numpy (no `@`, no `np.dot`).
  - ⚠️ **THIS BAN IS NOW SUSPECT — it was probably an Intel MKL artifact, and MKL
    is gone (2026-08-04, `CS-141`).** The env's BLAS was switched from Intel oneMKL
    to OpenBLAS for licensing reasons (`licensing.md` R5). After the swap,
    `scratchpad/openblas_env_test.py` runs `a @ a`, `np.dot`, `np.linalg.det`
    **and `pv.Sphere()`** — an explicitly banned call below — in one process that
    has a live `QApplication`, OCC loaded, and VTK/pyvista having already rendered
    offscreen. **All survive**; the full `scratchpad/` sweep and the pytest suite also pass.
    That is consistent with the crash having been MKL's delay-loaded `mkl_rt`
    colliding with VTK's DLLs rather than anything intrinsic to BLAS.
    **Do NOT relax the ban on this evidence alone.** Still unmeasured: a BLAS
    matmul in the real windowed GUI with the full viewport, and one in the
    **frozen** build, whose DLL layout and search order differ from the conda env.
    ⚠️ **`CS-148` does NOT settle this** — the frozen exe launching proves the
    payload starts, not that `points @ M` survives inside it; the ban is still
    respected in code, so nothing in that launch exercised the banned path. Treat
    the ban as in force until someone deliberately runs a matmul in both places;
    the win from removing it is a code-simplicity win, not a correctness one.
  - **This also bans several `pv.*` geometry helpers.** `pv.Sphere` (and other
    geometric objects that self-orient, e.g. `pv.Arrow`/`pv.Cone`) call `rotate_y`
    →`axis_angle_rotation`, which does a BLAS matmul internally → the SAME
    `0xC06D007F` HARD crash (native — a Python `try/except` can NOT catch it).
    Build these via the raw VTK source instead: `viewport_panel._make_sphere` uses
    `vtkSphereSource` (no rotation) + `pv.wrap`. Verified. Prefer `vtk*Source` +
    `pv.wrap`, or hand-built `pv.PolyData` (points/lines, like `_triad_poly`), over
    `pv.<Shape>` constructors anywhere geometry is created after VTK is live.
- **GIL**: OCC C++ calls hold the GIL, so running a parse on a `QThread` does NOT
  keep the UI responsive (progress bar can't even animate). The real fix for
  responsive first-load is a **subprocess** parse (writes the `.xbf`, then the main
  process loads the fast cache). (Pending.)
- Use `label.GetLabelName()` for names — but on a **reference**, prefer the
  REFERRED (product) label's name: the instance label is a generic `NAUO#`, while
  the referred label holds the real part name SolidWorks/Isaac show
  (`reader._walk` already prefers `ref_label`).
- **STEP export filtering is UNSOLVED** (see open bug). Facts learned:
  - `STEPCAFControl_Writer.Transfer(root_label)` once = perfect (colors + names +
    hierarchy + instancing, SolidWorks-verified). Only ONE Transfer per writer.
  - Multiple `Transfer(label)` calls OR `Transfer(TDF_LabelSequence)` **crash**
    (`0xC0000005` access violation).
  - `XCAFDoc_ShapeTool.RemoveComponent`/`RemoveShape` then `Transfer(root)` does
    NOT exclude cleanly — it breaks instancing and INFLATES output (a 619-part
    subtree with a 55-part branch suppressed produced 554 solids, not 564).
    **BUT**: RemoveComponent + orphan-product pruning + `UpdateAssemblies` +
    **`SaveAs`-to-`.xbf` + reload** IS clean (asset splitting's static build), and a
    faithful `Transfer(root)` from that RELOADED doc round-trips exactly (verified:
    1844/1844 solids). The historical breakage was Transfer-ing the just-mutated
    doc with its orphaned products still present.
  - Rebuilding a fresh flat doc (`AddShape`+`SetColor` per surviving solid) EXCLUDES
    correctly but its colors don't all show in SolidWorks (flat products, not the
    source authoring). ← current filtered-export path; acceptable stopgap.
  - Proper fix: reconstruct a filtered ASSEMBLY doc (products + instancing + colors
    mirroring the source), then one `Transfer`.
- **`SetLayerMode` crash matrix for round-tripped docs**: a doc that came from OUR
  OWN exported STEP (write → reparse → `.xbf`) hard-crashes (`0xC0000005`,
  uncatchable) a later `STEPCAFControl_Writer.Transfer` **when layer mode is ON**.
  Verified-stable combination (the ONLY one): write the intermediate STEP **with
  `SetLayerMode(True)`**, then re-export FROM the reparsed doc **with
  `SetLayerMode(False)`**. Writing the intermediate STEP with layers OFF is
  WORSE — the reparsed doc then crashes every later export, layers on or off.
  (Asset generation NO LONGER round-trips through STEP — it's direct `.xbf` label
  surgery — but this matrix stands if a STEP round-trip is ever reintroduced.)
  Generated models still export with `layers=False`
  (`export_subtree_step(..., layers=False)`; `export_cli` passes
  **`layers=(variant == "source")`** — keyed off the VARIANT, not the model id,
  because the base model resolves to the label-surgery `main` variant once a
  restructure is applied) — verified fine on the label-surgery docs; the
  ORIGINAL source doc exports fine with layers on (leave it alone). Nothing in
  this pipeline consumes STEP layers.
- **Restructure surgery facts (Feature A — probe-verified on testB1)**:
  - `NewShape()` + `TDataStd_Name.Set(label, str)` creates a named folder; an
    EMPTY NewShape is a valid `AddComponent` CHILD (becomes `IsAssembly` once it
    gets its own components) and a valid parent. Move = `RemoveComponent(instance
    label)` + `AddComponent(parent_PRODUCT_label, moved_PRODUCT_label, loc)` with
    `loc = world_parentⁿᵉʷ⁻¹ · world_old` (world preserved to ~1e-25).
  - **`AddComponent` APPENDS after existing components; removals don't reorder
    or reuse child tags** — so a rebuilt tree's DFS is predictable in pure Python
    (`restructure.plan_tree` — the planner IS the acceptance test).
  - **`TDF_Tool.Label(doc.GetData(), entry, TDF_Label(), False)` re-resolves an
    entry string to a live label mid-surgery** (concrete out-param propagates).
    A removed instance's entry still resolves (attributes forgotten) — don't use.
  - **`AddComponent` creates an UNNAMED instance label → the STEP writer emits a
    junk `"=>[0:1:1:262]"`-style product name** (invisible in xbf walks — the
    reader prefers the referred product's name). ALWAYS name new instance labels:
    folders get the folder name, moved nodes get their ORIGINAL instance name
    (captured before the Remove) — `restructure_build.apply_structure` does this.
  - **XCAF surgery edits PRODUCT definitions**: a node whose instance label
    occurs >1× in the tree (inside a multi-instanced assembly — 1191/1960 on
    testB1, 12433/19937 on testA1!) can't be moved individually, and a target
    whose product occurs >1× would gain the child in EVERY instance. The planner
    fails loud on both (`InstancingInfo.movable`/`valid_target`); the GUI blocks
    such drags via item flags. Per-ASSET restructure sidesteps this (a pruned
    asset holds ONE instance). Reader now stores per-component `label_entry` +
    `product_entry` strings for this (recomputed every load, no sidecar).
  - SaveAs to the SAME path a doc was opened from is safe (in-place asset
    restructure post-pass). Pure moves orphan nothing — the post-surgery free
    set must EQUAL the original roots (checked, fail loud; no pruning).
- **Cross-doc compose facts (probe-verified; used by `compose_step.py`)**:
  - `TopoDS_Shape`s are doc-independent: shapes taken from one OPEN doc can be
    `AddShape`d into a fresh doc and `st.FindShape(shape)` resolves them there
    (100% hit-rate) — but ONLY for shapes from the reopened/walked doc;
    a pre-save in-memory shape's TShape does NOT match after an xbf round trip.
  - `AddShape(compound, makeAssembly=True)` decomposes RECURSIVELY and shares
    products for instanced subshapes — but by shape TOPOLOGY, which on real
    SolidWorks exports is DEEPER than the XCAF product tree (nested compounds
    inside leaf products; 985 vs 349 nodes on the fixture). To mirror the
    product structure, build it EXPLICITLY: `AddShape(master, False)` per
    unique leaf product + `NewShape` per assembly + `AddComponent(parent,
    child, rel_loc)` (what `compose_step` does).
  - **Per-face colors on a fresh doc need `AddSubShape(product_label, face)` +
    `SetColor(sub_label)`** — `SetColor(face_shape, …)` alone does NOT stick.
  - **A COMPOUND leaf's product-level color does NOT survive a STEP round
    trip** (the writer emits styles on the sub-solids; the reparse style map
    keys on the master compound; simple solids recover via the instance
    color). Fix: style every FACE of a compound leaf (explicit face colors +
    the base color as fill).
  - `XCAFDoc_Editor.Extract/CloneShapeLabel` and `TDF_CopyTool` DO exist in
    this binding (introspection-verified) — unexercised; the explicit builder
    above made them unnecessary.
- **Doc/label lifetime traps** (cost a day — respect these):
  - `TDocStd_Application.SaveAs(doc, path)` **re-binds `doc` to `path` in the OCC
    session** — a later `Open(path)` in the same process returns an EMPTY doc, and
    the doc no longer answers for its ORIGINAL path. Never SaveAs a live source doc
    to "copy" it — copy the `.xbf` FILE (`shutil.copyfile`) and `Open` the copy.
    After intentionally SaveAs-ing (e.g. writing a variant), `app.Close(doc)` before
    anything re-Opens that path (`cache.close_variant_docs`).
  - `TDF_LabelSequence.Value(i)` returns labels **tied to the sequence's
    lifetime** — letting the sequence be GC'd leaves dangling labels (empty entries,
    NULL labels, `RemoveShape` access violations). Keep the sequence referenced
    while using them. **This bit the READER itself**: `_walk` stored
    `source_label`s taken from local `GetFreeShapes`/`GetComponents` sequences —
    on test1, 12401/19937 components ended with NULL labels (faithful exports and
    Generate Assets failed with "No source label"); test2 was small enough that the
    memory happened to survive. FIX: the reader parks every walked sequence on
    `Assembly._label_seqs` (lives as long as the assembly/doc). There is NO
    `TDF_Label` copy constructor in this binding.
  - Label handles go STALE across `RemoveComponent`/`UpdateAssemblies` — capture
    identity as ENTRY STRINGS first: `TDF_Tool.Entry(label, TCollection_AsciiString)`
    (concrete out-param → propagates in this binding; `label.IsEqual` comparison
    across mutations is NOT reliable).
  - Removing components orphans their referenced PRODUCT definitions, which surface
    as new FREE shapes (phantom roots). Prune by diffing `GetFreeShapes` entry
    strings against the pre-mutation set and `RemoveShape(L, True)` the new ones,
    ITERATIVELY (removing an assembly product orphans its children's products;
    converges in a few rounds). Genuinely shared products stay referenced — safe.
  - ⭐ **`UpdateAssemblies()` cannot see a location change on an ASSEMBLY child.**
    The measured rule (`scratchpad/probe_updateassemblies_matrix.py`, 6 cases):
    rewriting a component's `XCAFDoc_Location` refreshes the parent product's cached
    `TNaming_NamedShape` compound **only when that component references a SIMPLE
    SHAPE (a leaf)**. When it references an **assembly**, the change is invisible and
    the parent's compound is never rebuilt. Free-root vs component, multi-instanced
    children, and a location on the root itself make **no** difference. Modification
    *does* propagate upward once something genuinely flags modified — a change to a
    LEAF instance one level down refreshes both its sub-assembly and the root — which
    is why this only ever bit the assembly-child case. Consistent with OCC taking
    `isModified` from the recursive "did the child's CONTENTS change" call on that
    branch and never comparing the location. ⛔ Consequence: **a re-origin leaves the
    product compound stale**, because it is pure child-location surgery and touches no
    stored shape. Live bug: on testB2's `/Body` folder (children = the robot assembly
    + the drone assembly) the compound kept the PRE-re-origin frame **on disk**, in
    `root/main` AND in the pruned `asset-Body/source`; `apply_splits`' merge-then-edit
    branch read it and baked every body displaced by the whole origin frame F
    (~4.6 m + its rotation) while the Component Editor looked correct.
    **Two-part fix, both in place:**
    1. `geometry_edits_build.refresh_assembly_compound(st, product_label)` rebuilds
       the compound from the components' current located shapes and `SetShape`s it —
       verified to fix every failing case. Called by `apply_origins`' assembly branch
       and by `restructure_build._reorigin_assembly_once`, so the artifact is honest.
    2. **Consumers still must not trust it.** The **component walk** (each label's
       `GetLocation`, what `reader._walk` accumulates) is the authority — every other
       layer already uses it, so anything reading the compound silently disagrees with
       the viewport. Product-LOCAL and occurrence-independent (so multi-instance-safe)
       is `inv(assembly.transform) · leaf.transform`; `build_assembly_edit_compound`
       is the shared helper the window AND the bake now call.
    A LEAF's `GetShape(master)` is fine — stored directly, and `apply_origins`
    rewrites it in place with `SetShape`.
  - **`TopTools_IndexedMapOfShape.Add` returns the 1-based index and NO-GROWS on a
    shape already present** (probe-verified: re-adding returns the original index,
    `Size()` unchanged). So **never pair it with a parallel list you append to
    unconditionally** — one duplicate leaves the list one long and shifts every later
    lookup onto the wrong entry. Key by the index `Add` returns
    (`d.setdefault(known.Add(f), value)`), which is what `_split_face_colors` does now.
    Duplicates are real here: two occurrences of one product landing at the same
    location, or a face shared by two solids of a compound leaf.
  - **`brepbndlib.Add(shape, box, useTriangulation=False)` INFLATES wildly** on a
    shape with no triangulation: it bounds each face's underlying (untrimmed,
    possibly near-infinite) SURFACE, not the trimmed face. On testB2 leaves this read
    3× too large and sent a diagnosis down the wrong path for three probes. For a
    measurement you intend to trust, either mesh first
    (`BRepMesh_IncrementalMesh`) or bound the exact **VERTICES**
    (`TopExp_Explorer(shape, TopAbs_VERTEX)` + `BRep_Tool.Pnt`) — see
    `scratchpad/probe_body_vertexbbox.py`. Comparing two frames of the SAME shape is
    exactly where the inflated box lies to you, because it inflates differently once
    the shape is rotated.
- **VTK `extract_feature_edges` holds the GIL** → running it on a `QThread` still
  freezes the UI. SOLVED: extract ONCE per deflection in a **subprocess**
  (`src/gui/edges_build.py`, Qt-free — imports only `mesh_ops` + the OCC reader),
  write the `.edges_*.npz` cache, then the GUI loads it. The combined mesh carries a
  per-point `cid_index`; `extract_feature_edges` preserves point data, so each edge
  line-cell is mapped to its component from an endpoint. Toggling edges = actor
  visibility flip; hiding a component = set that component's edge cells' alpha=0
  (like solids) — never re-extract. (~0.03% of edge cells at touching interfaces get
  welded to one neighbour by VTK's point locator; cosmetically harmless.)

