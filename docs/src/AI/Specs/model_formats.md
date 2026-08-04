# 3D Model Formats — What CellSmith's Libraries Can Read and Write

> ## 🛑 STATUS: INACTIVE — WORK IN PROGRESS. NOT A BUILD REQUEST.
>
> **Nothing in this file is scheduled or approved. No agent should treat any ⚪ row, gap, option, or suggestion here as work to start.** This is a **capability inventory** — a survey of what the already-installed libraries *could* do, what each format can carry, and what we persist today — written to inform future decisions, not to specify one. The ✅ rows describe behavior that already exists; everything else is background.
>
> **One exception, and only in the "is it ready" sense:** the [Actionable Now](#actionable-now) list at the end collects small, low-risk fixes that need no further research. Even those require an explicit go-ahead from the user before touching `src/`.
>
> If you arrived here while implementing something, the default safe use of this file is **reading it**. Adding a format, adding a dependency, or "fixing" the ⚠ gaps is not authorized by this document.

Two inventories for spec development, plus pointers to two sections that moved into the user docs. **(1) File Formats** — every 3D geometry format reachable from the libraries already installed in `CellSmithEnv` (OpenCASCADE via `pythonocc-core`, `trimesh`, `usd-core`/`pxr`, `pyvista`/VTK), with per-format import/export status: **wired in the app** vs **library-capable but not wired** vs **advertised-but-broken**. **(2) File Format Capabilities** — what each format can physically carry (B-rep vs tessellation, color granularity, hierarchy, units, kinematics…), one row per capability-distinct variant, plus the deltas where our code uses less than the format allows. Then the **Actionable Now** list. **Moved to `docs/src/Misc/`:** the novice-facing model taxonomy (`intro-model-structure.md` — read it for the vocabulary the tables assume) and the on-disk cache map (`legacy-cellsmith-model-format.md`). Claims were probed empirically against the installed env (see *Probe Basis*); anything unverified is marked **❓ NEEDS RESEARCH** rather than guessed. Scope is limited to formats an open-source library can actually handle — writing our own reader/writer for a closed format is out of scope, so proprietary formats with no free implementation are excluded entirely. Read when deciding which formats to support, when a user asks "can it open X", when learning the model vocabulary, when adding a reader/writer, or when designing a successor to the cache format. Verify against `src/io_step/`, `src/io_mesh/`, `src/export/`, `src/model/scene_config.py`; may lag.

> **⚠ THIS FILE'S HOME AND GENRE ARE ALSO UNDECIDED — REVISIT.** It is parked in `Specs/` for now, but it is not really design intent. Open questions are collected in [Unresolved — Genre, Name, Audience](#unresolved--genre-name-audience) at the bottom. Because the genre isn't settled, this file is **not yet listed** in `docs/src/AI/index.md`'s index or the `CLAUDE.md` tier-1 map; add it there once the decision is made.

---

## Legend

| Mark | Meaning |
|---|---|
| ✅ | **Wired today** — reachable from the running app (menu, dialog, or CLI worker). |
| ⚪ | **Library-capable, not wired** — the installed dependency can do it; CellSmith has no code path. |
| ⚠ | **Advertised but broken** — the app offers it, but it fails in this env (missing optional dependency). |
| ❌ | **Not supported by an installed library** — would require adding a free/open-source dependency. |

"Import" = becomes a CellSmith `Assembly` (tree + geometry + colors). "Export" = written out as a deliverable. Formats marked ⚪/❌ are listed so the cost of a *hypothetical* future request is visible — **they are not a backlog and nothing here is a commitment.**

## Library Roles

| Library | Version in env | Role for formats |
|---|---|---|
| `pythonocc-core` (OCCT) | 7.9.3 `novtk` (pythonocc 7.9.0) | **The B-rep engine — priority #1.** STEP read/write; a large unused data-exchange surface (IGES, BREP, and the `RWMesh` CAF mesh readers/writers). |
| `trimesh` | 4.12.2 | Triangle-mesh import for the additive mesh path (`src/io_mesh/mesh_reader.py`). Worker-process only. |
| `usd-core` (`pxr`) | USD 0.26.5 | USD read (mesh import) + all USD authoring (subtree, per-asset, composed). Worker-process only. |
| `pyvista` / VTK | 0.48.4 / VTK 9.6.2 | The viewport. Its readers/writers are **not** used for model I/O — listed only because they exist. |
| CellSmith's own writers | — | `src/export/obj_writer.py` (Wavefront OBJ + MTL, pure numpy), `src/export/usd_writer.py` (pxr), `src/io_step/writer.py` + `compose_step.py` (OCC STEP). |

## File Formats

Ordered by class, then by how load-bearing the format is here.

| Format | Extensions | Class | Library (load / save) | Import | Export | What it is |
|---|---|---|---|---|---|---|
| **STEP** (AP203 / AP214 / AP242) | `.step`, `.stp` | Exact B-rep + assembly | OCC `STEPCAFControl_Reader` / `STEPCAFControl_Writer` (writes AP214 `AUTOMOTIVE_DESIGN`) | ✅ | ✅ | The ISO 10303 neutral CAD exchange format and **the center of this application**. Carries exact analytic surfaces, an assembly tree with instancing, part names, and per-part/per-face colors — everything the rigging workflow needs. The only import that yields real B-rep (so the only one where analytic edge/arc/face snapping, adjustable re-tessellation, and STEP re-export are available). Export has a *faithful* path (transfers the baked XCAF doc: colors + names + hierarchy + instancing preserved) and a *rebuild* path (used when suppression / color override / local-origin shift apply; loses authored names + instancing). |
| **IGES** | `.igs`, `.iges` | Surfaces / legacy B-rep | OCC `IGESCAFControl_Reader` / `IGESCAFControl_Writer` | ⚪ | ⚪ | Pre-STEP neutral surface exchange (1980s). Reads as loose surfaces/curves with weak or absent assembly and solid semantics — routinely needs sewing/healing to become a solid. No reason to add unless a supplier only ships IGES. |
| **OCCT BREP** | `.brep` (ASCII), binary variant | Exact B-rep, OCC-native | OCC `breptools.Read/Write` (ASCII) · `bintools` (binary) | ⚪ | ⚪ | OpenCASCADE's own dump of a `TopoDS_Shape`. Lossless and fast for exact geometry, but carries **no** names, colors, or assembly structure, and only OCC-based tools read it. Useful as a debug/interop artifact, not as a deliverable. |
| **Binary XCAF document** | `.xbf` | B-rep + full XCAF doc | OCC `binxcafdrivers` + `TDocStd_Application`, format `"BinXCAF"` (`src/io_step/cache.py`) | ✅ *(internal)* | ✅ *(internal)* | Not an interchange format — **CellSmith's own STEP cache**. One `.xbf` per pipeline stage (`geometry-source.xbf`, `geometry-main.xbf`, per-asset variants) storing shapes + labels + names + colors so a re-open skips the multi-minute STEP parse. Listed here so it isn't mistaken for a user-facing format; the mesh path substitutes a `structure-{stage}.json` instead. |
| **Wavefront OBJ** (+ `.mtl`) | `.obj`, `.mtl` | Triangle mesh | **load:** `trimesh` (wired) · OCC `RWObj_CafReader` ⚪ — **save:** `src/export/obj_writer.py` (own numpy writer, wired) · `trimesh` ⚪ · OCC `RWObj_CafWriter` ⚪ · VTK `Plotter.export_obj` ⚪ | ✅ | ✅ | The lowest-common-denominator mesh format: ASCII vertices/faces, `o`/`g` groups for parts, optional sibling `.mtl` for per-material diffuse color. No units, no up-axis, no transforms — everything is baked into the coordinates. Import keeps the `o`/`g` groups as leaves; export writes one `o` group per meshed leaf plus a color-deduped `.mtl`. `.mtl` is optional on import (materialless OBJ → grey). |
| **USD** — ASCII / crate / auto | `.usda`, `.usdc`, `.usd` | Scene graph (mesh) | `pxr` `Usd.Stage.Open` / `Usd.Stage.CreateNew` (extension picks ASCII vs crate) | ✅ | ✅ | Pixar's Universal Scene Description — **the rigged-asset output format** and Isaac Sim's native scene format. Composable (references / payloads / sublayers / overrides), typed schemas (`UsdGeom.Mesh`, `UsdPhysics` joints), `metersPerUnit` + `upAxis` metadata, per-face `displayColor`. Import reads the mesh hierarchy (world transforms, n-gon fan triangulation, `displayColor`/`GeomSubset` colors). Export covers subtree, per-asset `{slug}_base.usd` + create-once `{slug}.usda` override wrapper, and the composed `main.usda`. |
| **USDZ** | `.usdz` | Zipped USD package | **load:** `pxr` `Usd.Stage.Open` — **save:** `UsdUtils.CreateNewUsdzPackage` ⚪ | ✅ | ⚪ | An uncompressed zip bundling a USD layer with its textures — the single-file delivery form of USD. Accepted on import (`USD_EXTENSIONS` includes it; pxr opens packages transparently), though the headless fixtures only cover `.usd`. **Export would need the packaging API on purpose:** `Stage.CreateNew("x.usdz")` is refused by `SdfLayer::_CreateNew` (probe-verified) — you author a `.usdc` and then package it. A package is read-only, so the base/override two-layer scheme would not survive as-is. |
| **STL** | `.stl` (binary + ASCII) | Triangle mesh | **load:** `trimesh` (wired) · OCC `StlAPI_Reader` / `rwstl` ⚪ — **save:** `trimesh` ⚪ · OCC `StlAPI_Writer` ⚪ · `pyvista` `.save()` ⚪ | ✅ | ⚪ | The 3D-printing lingua franca: a bare unstructured triangle soup. **No colors, no names, no hierarchy, no units** — one file is one anonymous blob, so a whole assembly imports as a single body (`decompose` can split it into connected components). Fine as a quick geometry sanity check; useless for rigging metadata. |
| **PLY** | `.ply` | Triangle mesh / point cloud | **load:** `trimesh` (wired) — **save:** `trimesh` ⚪ · OCC `RWPly_CafWriter` ⚪ · `pyvista` `.save()` ⚪ | ✅ | ⚪ | Stanford polygon format, ASCII or binary, with arbitrary per-vertex/per-face properties — so it *can* carry vertex colors and normals. Common in scanning/photogrammetry output. No assembly structure. Note OCCT has a PLY **writer** but no PLY reader. |
| **glTF 2.0** | `.gltf` (+ `.bin`), `.glb` | Scene graph (mesh) | **load:** `trimesh` (wired) · OCC `RWGltf_CafReader` ⚪ — **save:** `trimesh` ⚪ · OCC `RWGltf_CafWriter` ⚪ · VTK `Plotter.export_gltf` ⚪ | ✅ | ⚪ | The "JPEG of 3D": a runtime/web delivery format with a real node hierarchy, transforms, PBR materials, and optional animation. `.glb` is the single-file binary form. Well-supported and compact, but a *delivery* format — lossy vs CAD (tessellated, PBR-material colors) and not what Isaac Sim wants for rigged assets. Draco-compressed glTF is **not** readable here (no Draco backend installed). |
| **OFF** | `.off` | Triangle mesh | `trimesh` (load wired) / `trimesh` ⚪ | ✅ | ⚪ | Geomview's minimal ASCII "Object File Format" — counts followed by vertices and faces. Academic/mesh-processing provenance; no materials, no structure. Rides along in the mesh path at zero cost. |
| **3MF** | `.3mf` | Mesh + scene (zip/XML) | `trimesh` | ⚠ | ⚠ | The modern manufacturing-oriented replacement for STL: a zipped XML package with units, a build/object hierarchy, transforms, colors, and materials. **Declared in `io_mesh.formats.TRIMESH_EXTENSIONS` and advertised in the Open dialog, but it fails in this env** — trimesh's 3MF loader/exporter needs `networkx`, which is not installed (probe-verified: `ModuleNotFoundError: No module named 'networkx'`; the loader is registered as an `ExceptionWrapper`, so it is absent from `trimesh.available_formats()`). See [Known Gaps](#known-gaps--advertised-but-broken). |
| **COLLADA** | `.dae`, `.zae` | Scene graph (XML) | `trimesh` | ⚠ | ⚠ | Khronos' older XML interchange format — full node hierarchy, transforms, materials; verbose and largely superseded by glTF/USD. **Declared in `TRIMESH_EXTENSIONS` but fails in this env**: trimesh raises `ImportError: missing 'pip install pycollada'`. Even with `pycollada`, trimesh's DAE support is mesh-export only (`Scene.export('.dae')` → `unsupported export format`). |
| **VRML / X3D-classic** | `.wrl` | Tessellated scene | **load:** OCC `VrmlData_Scene` ⚪ — **save:** OCC `VrmlAPI_Writer` ⚪ · VTK `Plotter.export_vrml` ⚪ | ⚪ | ⚪ | 1990s web-3D scene format; text scene graph with per-shape material colors. Historically relevant because old CAD exporters and early URDF/Gazebo pipelines emitted it. Superseded — mentioned only because OCCT ships both directions. |
| **XYZ** | `.xyz` | Point cloud | `trimesh` (point clouds only) | ⚪ | ⚪ | Plain text coordinate triples, optionally with color. Not a surface — CellSmith has no point-cloud model type, so importing one would need a new component kind; export refuses anything that isn't a `PointCloud`. |
| **Other trimesh-registered** | `.3dxml`, `.xaml`, `.ctm`, `.zae`, `.binvox` | Mesh / voxel | `trimesh` — registered, **inert** here | ❌ *(this env)* | ❌ | trimesh has loaders for these but they are `ExceptionWrapper` stubs in `CellSmithEnv` (unmet optional deps: `lxml` for the XML-based ones, etc.). `.3dxml` is the only one notable in principle — a zipped-XML tessellated scene *with* assembly structure, emitted by some CAD exporters — but it would need `lxml` and remains unvalidated here. |
| **VTK native** | `.vtk`, `.vtp`, `.vtu`, `.vtm`, `.vts`, `.vtr`, `.vti`, `.vtkhdf` + ~60 scientific/medical readers (`.exo`, `.cgns`, `.foam`, `.nii`, `.dcm`, …) | Scientific viz meshes / volumes | `pyvista` readers ⚪ / `DataSet.save()` ⚪ | ⚪ | ⚪ | VTK's own dataset formats (plus its long tail of CFD/FEA/medical importers). They carry point/cell data arrays, not CAD semantics — no B-rep, no assembly, no part names. Present purely because the viewport uses VTK; irrelevant to the CAD→Isaac workflow. |
| **Viewport snapshots** | `.html`, `.vtksz` | Interactive scene dump | VTK `Plotter.export_html` / `export_vtksz` ⚪ | ❌ | ⚪ | Not model formats: a serialized copy of *the current render* (geometry + camera + colors) for viewing in a browser or vtk.js. Plausible for sharing a review snapshot; useless as a pipeline asset. |

## What's Actually Wired Today

- **Import — 1 B-rep + 6 mesh formats.** STEP/STP via OCC (the default, full-capability path) and OBJ / STL / PLY / glTF / GLB / OFF via trimesh + USD/USDA/USDC/USDZ via pxr, dispatched by extension in `main_window.load_file` → `load_step` vs `load_mesh` (predicate: `io_mesh.formats.is_mesh_path`). Mesh imports set `shape=None`, so `assembly_has_brep` is False and the B-rep-only features gate off with a reason tooltip.
- **Export — 3 formats.** STEP (AP214, B-rep only — refused for mesh scenes), USD, and OBJ; each available both as *subtree* export (right-click a node) and *composed whole-scene* export, run in a subprocess CLI (`export_step` / `usd_cli` / `obj_cli` / `compose_cli`).
- The asymmetry is deliberate: import breadth is cheap (trimesh rides along), while every export format is a maintained contract (units, colors, transform baking, joints).

## Known Gaps — Advertised but Broken

`.3mf` and `.dae` are in `io_mesh.formats.TRIMESH_EXTENSIONS`, so they appear in the Open dialog's "CAD & mesh files" filter, but **loading either raises in `CellSmithEnv`**: trimesh's 3MF path needs `networkx` and its COLLADA path needs `pycollada`; neither is in `packaging/environment.yml`. Probed directly — both loaders are registered as `ExceptionWrapper` and excluded from `trimesh.available_formats()` (live loaders: `obj`, `stl`, `stl_ascii`, `ply`, `off`, `gltf`, `glb`, `xyz`).

Two candidate resolutions — **recorded, NOT scheduled; do not apply either without an explicit request:**

1. **Make them work** — add `networkx` (3MF) and `pycollada` (COLLADA) to `packaging/environment.yml`'s pip block. Both are pure-Python wheels, so no build risk; cost is two more bundled deps in the PyInstaller onedir.
2. **Stop advertising them** — drop `.3mf` / `.dae` from `TRIMESH_EXTENSIONS` until a fixture exists, so the dialog only offers formats with a green headless test.

The state to be aware of either way: choosing a `.3mf` or `.dae` in the Open dialog raises.

## Unused Capability Worth Knowing About

**OCCT's `RWMesh` CAF family can import meshes into XCAF directly** — `RWObj_CafReader` (OBJ) and `RWGltf_CafReader` (glTF/GLB) build a real `TDocStd_Document` with names, hierarchy, transforms, and materials, and `RWObj_CafWriter` / `RWGltf_CafWriter` / `RWPly_CafWriter` / `StlAPI_Writer` write back out. That would let OBJ/glTF import reuse the existing XCAF cache, tree, and color sidecar instead of the parallel numpy/JSON mesh backend.

It is **not** a recommendation. The mesh path exists precisely so mesh support cannot touch the STEP/OCC code paths (⭐ HARD PRIORITY), and an OCC-based mesh reader would reintroduce that coupling; it also still produces `shape`s that are only tessellations, so it wouldn't unlock any analytic B-rep feature. Recorded so the option isn't rediscovered from scratch. The genuinely useful piece is the **writer** side: OCC's glTF/PLY writers are a near-free way to add export formats if anyone ever asks, since the XCAF doc is already in hand.

## Scope Boundary — Formats Excluded From This Document

**Only formats that a free/open-source library can handle are in scope.** Writing a reader or writer for a closed format is out of scope for this project, so proprietary formats with no free implementation (native CAD part/assembly files, licensed kernel formats, and vendor visualization formats in that category) are **deliberately not catalogued here** — they are not a gap, a TODO, or a candidate. If a supplier only ships such a file, the answer is upstream: have it re-exported as STEP.

For completeness, three formats *do* have free implementations but no installed library, so they sit at ❌ rather than being excluded. Listed to explain their absence from the table — **not as suggestions**:

- **Alembic `.abc`** — VFX/animation cache. Needs the Alembic USD plugin, which the `usd-core` wheel does not ship.
- **IFC `.ifc`** — building/BIM; would need `ifcopenshell`.
- **Draco-compressed glTF** — needs the Draco codec; plain glTF/GLB already works.

`.dxf` deserves one clarification: `trimesh` loads it, but **2D paths only** — there is no 3D-solid DXF path here, and OCCT's DXF/DWG support is a commercial add-on (excluded per the rule above).

## Intro to Model Structure — Moved

The novice-facing taxonomy (topology vs geometry, B-rep vs NURBS and adjacent representations, general B-rep vs OpenCASCADE-specific naming, the product pool / occurrence model, the mesh ladder, the two worlds side by side, and the structural glossary) now lives in the **user docs**:

- [`docs/src/AI/Scratch/intro-model-structure.md`](../Scratch/intro-model-structure.md)

It is mkdocs-formatted (admonitions, mermaid diagrams, definition lists) and picked up automatically by the `include_dir_to_nav` plugin. `Misc/` is a temporary placeholder until the user docs are organised. **Read that page for the vocabulary the tables below assume.**

## File Format Capabilities

**What each format can physically carry**, and therefore what it can and can't be used for. This is **format-centric** — it describes the file specification, *not* what CellSmith currently reads or writes from it. Where our code uses less than the format allows, that's collected in [CellSmith Implementation Deltas](#cellsmith-implementation-deltas) below, so the two questions never get tangled.

**Every variant or sub-format that differs in capability gets its own row** — STEP per application protocol, AP242 split by whether B-rep is present, IGES before/after 5.3, and each encoding variant (ASCII vs binary vs packaged) of BREP, XCAF, STL, PLY, glTF, and COLLADA. Cells are always written out in full; no row refers to another.

**USD is deliberately kept as ONE row** covering `.usda` / `.usdc` / `.usd` / `.usdz`: its four extensions differ only in *encoding and packaging*, not in what the format can carry, so the encoding differences are stated inside the cells instead of fragmenting the row.

**Capability marks:** ✔ carried by the format · ✖ not representable · ◑ partial or conditional (see note) · **❓ NEEDS RESEARCH** — not verified in this env, treat as unknown.

Split into two tables over the **same rows in the same order** (one 15-column table is unreadable in a terminal).

### Geometry and Appearance

| Format | B-Rep | Mesh Polygons | Normals | UV / Textures | Color Granularity | Materials | Coordinate Precision |
|---|---|---|---|---|---|---|---|
| **STEP AP203 e1** | ✔ exact NURBS + analytic surfaces, solids | ✖ no tessellation in the schema | n/a — surfaces are analytic, normals are evaluated | ✖ | ✖ none — geometry and structure only | ✖ | float64 in ASCII text |
| **STEP AP203 e2** | ✔ exact NURBS + analytic surfaces, solids | ✖ no tessellation in the schema | n/a — surfaces are analytic, normals are evaluated | ✖ | ◑ presentation/color was added in edition 2, so per-body and per-face styling is expressible — **❓ whether our style-recovery path resolves e2 styles the way it resolves AP214's** | ✖ | float64 in ASCII text |
| **STEP AP214** (CD / DIS / IS) | ✔ exact NURBS + analytic surfaces, solids | ✖ no tessellation in the schema | n/a — surfaces are analytic, normals are evaluated | ✖ | ✔ **per-body AND per-face** (`STYLED_ITEM` → solid or `ADVANCED_FACE`; testA1 carries 112k face styles over a 175-color palette) | ◑ material entities exist; CAD exporters rarely populate them — **❓** | float64 in ASCII text |
| **STEP AP242 — B-rep present** | ✔ exact NURBS + analytic surfaces, solids | ◑ a tessellated shell may be present *alongside* the B-rep | n/a for the B-rep; tessellated face sets may carry optional per-vertex normals | ✖ | ✔ per-body AND per-face, same `STYLED_ITEM` mechanism as AP214 | ◑ material entities exist, plus GD&T/PMI as a first-class schema (`SetGDTMode` / `SetDimTolMode`) | float64 in ASCII text |
| **STEP AP242 — tessellated only** | ✖ **none — this is a mesh wearing a STEP extension** | ✔ triangulated face sets (flat, plus strip/fan complex forms) | ◑ optional per-vertex normals in the face set — **❓ whether OCC surfaces them** | ✖ | ◑ styling applies to the tessellated items — **❓ unexercised, no fixture** | ◑ same material/PMI entities are legal | float64 in ASCII text |
| **IGES ≤ 5.2** | ◑ surfaces and curves only — no solid entity, so results need sewing/healing to become a solid | ✖ | n/a — surfaces are analytic | ✖ | ◑ per-entity color number (small fixed palette) or a color-definition entity; OCC's `IGESCAFControl` exposes `SetColorMode`/`SetNameMode`/`SetLayerMode` both directions | ✖ | float64 in fixed-column ASCII |
| **IGES 5.3** | ◑ adds the Manifold Solid B-Rep Object (entity 186), so true solids are expressible — **❓ unexercised here** | ✖ | n/a — surfaces are analytic | ✖ | ◑ per-entity color number or color-definition entity; same OCC CAF modes as above | ✖ | float64 in fixed-column ASCII |
| **OCCT BREP — ASCII** (`.brep`) | ✔ exact, OCC's native shape dump | ◑ stores triangulations if the shape carries them | n/a — surfaces are analytic | ✖ | ✖ | ✖ | float64 in ASCII text (2,565 bytes for a box, probe-measured) |
| **OCCT BREP — binary** (`BinTools`) | ✔ exact, OCC's native shape dump | ◑ stores triangulations if the shape carries them | n/a — surfaces are analytic | ✖ | ✖ | ✖ | float64 binary (4,494 bytes for the *same* box — binary is not automatically smaller) |
| **XCAF `BinXCAF`** (`.xbf` — our cache) | ✔ exact, plus the whole document around it | ◑ stores triangulations if present | n/a — surfaces are analytic | ✖ | ◑ per-body and per-face color slots exist, **but the STEP presentation layer does not survive into it** — the reason the color sidecar exists | ◑ material + vis-material tools exist | float64 binary (`BINFILE` magic, probe-verified round-trip) |
| **XCAF `XmlXCAF`** (`.xml`) | ✔ exact, plus the whole document around it | ◑ stores triangulations if present | n/a — surfaces are analytic | ✖ | ◑ per-body and per-face color slots exist; the same presentation-layer gap applies | ◑ material + vis-material tools exist | float64 in XML text (probe-verified round-trip with color preserved) |
| **Wavefront OBJ** (+ `.mtl`) | ✖ | ✔ n-gon faces | ✔ `vn` records | ✔ `vt` records + `.mtl` `map_Kd` textures | ✔ effectively per-face — a `usemtl` run applies to every face that follows it | ◑ Phong-era (`Kd`/`Ks`/`Ns`), not PBR | ASCII text, arbitrary digit count |
| **USD** (`.usda` ASCII · `.usdc` crate · `.usd` auto · `.usdz` package) | ◑ analytic **primitives** only (`Cube`/`Cylinder`/`Sphere`/`Cone`/`Capsule`) — no general B-rep | ✔ n-gon faces, plus true subdivision surfaces | ✔ optional `normals` attribute | ✔ UV primvars + `UsdShade` textures (bundled inside a `.usdz`) | ✔ **the richest here**: `displayColor` at `constant` / `uniform` (per-face) / `vertex` / `faceVarying` | ✔ `UsdShade`, PBR, MaterialX | **float32 points** (`GfVec3f`) — a real constraint on large coordinates. Encoding follows the extension: `.usda` is text, `.usdc` is the binary crate, **`.usd` writes crate by default** (probe-verified `PXR-USDC` header), `.usdz` is an uncompressed zip |
| **STL — ASCII** | ✖ | ✔ **triangles only** | ◑ a per-facet normal is written and is routinely zero or wrong | ✖ | ✖ | ✖ | ASCII decimal text |
| **STL — binary** | ✖ | ✔ **triangles only** | ◑ a per-facet normal is written and is routinely zero or wrong | ✖ | ◑ the 2-byte per-facet attribute field is abused for color by some tools, under **mutually incompatible non-standard conventions** — **❓** | ✖ | **float32** |
| **PLY — ASCII** | ✖ | ✔ n-gon faces | ✔ optional per-vertex normal properties | ◑ only as custom `s`/`t` properties | ✔ per-vertex and/or per-face color properties | ✖ no material system at all | as declared per property (float32 or float64) |
| **PLY — binary** (LE or BE) | ✖ | ✔ n-gon faces | ✔ optional per-vertex normal properties | ◑ only as custom `s`/`t` properties | ✔ per-vertex and/or per-face color properties | ✖ no material system at all | as declared per property (float32 or float64) |
| **glTF 2.0 separate** (`.gltf` + `.bin`) | ✖ | ✔ triangles in practice (other primitive modes exist in the spec) | ✔ normal accessor | ✔ UV accessors + external or embedded textures | ◑ per-vertex `COLOR_0` ✔; per-face ✖ — you split geometry into one primitive per material | ✔ PBR metallic-roughness | **float32** |
| **glTF 2.0 binary** (`.glb`) | ✖ | ✔ triangles in practice (other primitive modes exist in the spec) | ✔ normal accessor | ✔ UV accessors + textures embedded in the container | ◑ per-vertex `COLOR_0` ✔; per-face ✖ — you split geometry into one primitive per material | ✔ PBR metallic-roughness | **float32** |
| **OFF** | ✖ | ✔ n-gon faces | ✖ | ✖ | ◑ the colored-OFF variant allows trailing per-face RGB columns — **❓ whether trimesh preserves them** | ✖ | ASCII text |
| **3MF** | ✖ | ✔ triangles only | ✖ — the consumer computes them | ◑ `texture2d` extension | ✔ per-triangle `colorgroup` plus per-object color | ✔ `basematerials` | ASCII XML in a zip · **❓ whole row unvalidated — the loader is dead in this env** |
| **COLLADA** (`.dae`) | ✖ | ✔ n-gon via `polylist` | ✔ normal inputs | ✔ UV inputs + textures | ◑ per-primitive material ✔; per-vertex color via inputs — **❓** | ✔ Phong / Blinn / Lambert | ASCII XML · **❓ unvalidated here** |
| **COLLADA zipped** (`.zae`) | ✖ | ✔ n-gon via `polylist` | ✔ normal inputs | ✔ UV inputs + textures, bundled in the archive | ◑ per-primitive material ✔; per-vertex color via inputs — **❓** | ✔ Phong / Blinn / Lambert | ASCII XML inside a zip · **❓ unvalidated here** |
| **VRML 1.0** (`.wrl`) | ✖ | ✔ n-gon `IndexedFaceSet` | ✔ `Normal` node | ◑ `Texture2` node | ◑ `Material` per shape, per-face/per-vertex via `MaterialBinding` — **❓ OCC's reader targets VRML 2.0** | ◑ Phong-era | ASCII text |
| **VRML 2.0 / VRML97** (`.wrl`) | ✖ | ✔ n-gon `IndexedFaceSet` | ✔ `Normal` node | ✔ `ImageTexture` + `TextureCoordinate` | ✔ per-shape `Material` plus per-vertex or per-face `Color` node | ◑ Phong-era | ASCII text |

### Structure and Semantics

| Format | Assembly Hierarchy | Instancing / Reuse | Names + Metadata | Units | Up-Axis | Kinematics / Joints | Encoding | Sidecar Files | Composition / Layering |
|---|---|---|---|---|---|---|---|---|---|
| **STEP AP203 e1** | ✔ product structure with nested placements | ✔ shared product definitions referenced many times | ✔ product + instance names | ✔ explicit unit context (mm typical from SolidWorks) | ✖ no convention in the file | ✖ | ASCII Part 21 | none — single file | ✖ |
| **STEP AP203 e2** | ✔ product structure with nested placements | ✔ shared product definitions referenced many times | ✔ product + instance names | ✔ explicit unit context (mm typical from SolidWorks) | ✖ no convention in the file | ✖ | ASCII Part 21 | none — single file | ✖ |
| **STEP AP214** (CD / DIS / IS) | ✔ product structure with nested placements | ✔ shared product definitions referenced many times | ✔ product + instance names | ✔ explicit unit context (mm typical from SolidWorks) | ✖ no convention in the file | ✖ | ASCII Part 21 | none — single file | ✖ |
| **STEP AP242 — B-rep present** | ✔ product structure with nested placements | ✔ shared product definitions referenced many times | ✔ product + instance names, plus PMI/GD&T annotation | ✔ explicit unit context | ✖ no convention in the file | ◑ **a kinematics schema exists** — `StepKinematics` + `RWStepKinematics` are in this binding, but there is **no `XCAFKinematics`**, so no document-level tool reads or authors mechanisms. **❓ NEEDS RESEARCH — practically unreachable without hand-walking raw entities** | ASCII Part 21 | none — single file | ✖ |
| **STEP AP242 — tessellated only** | ✔ product structure with nested placements | ✔ shared product definitions referenced many times | ✔ product + instance names, plus PMI/GD&T annotation | ✔ explicit unit context | ✖ no convention in the file | ◑ the same kinematics schema is legal and equally unreachable — **❓** | ASCII Part 21 | none — single file | ✖ |
| **IGES ≤ 5.2** | ◑ weak — subfigures only, no real assembly semantics | ◑ subfigure instances | ◑ entity-level names via the CAF reader | ✔ global section declares units | ✖ no convention in the file | ✖ | ASCII, fixed 80-column records | none — single file | ✖ |
| **IGES 5.3** | ◑ weak — subfigures only, no real assembly semantics | ◑ subfigure instances | ◑ entity-level names via the CAF reader | ✔ global section declares units | ✖ no convention in the file | ✖ | ASCII, fixed 80-column records | none — single file | ✖ |
| **OCCT BREP — ASCII** | ✖ one shape; nesting only via `TopoDS_Compound` | ◑ shared `TShape`s inside the one shape | ✖ no names anywhere | ✖ **unitless numbers** | ✖ | ✖ | ASCII text | none | ✖ |
| **OCCT BREP — binary** | ✖ one shape; nesting only via `TopoDS_Compound` | ◑ shared `TShape`s inside the one shape | ✖ no names anywhere | ✖ **unitless numbers** | ✖ | ✖ | binary | none | ✖ |
| **XCAF `BinXCAF`** (`.xbf`) | ✔ full product/instance tree | ✔ product-level, exactly as STEP | ✔ names + arbitrary typed attributes on any label | ◑ `GetLengthUnit` / `SetLengthUnit` | ✖ | ✖ | binary | ✔ our color sidecar, by necessity | ✖ |
| **XCAF `XmlXCAF`** (`.xml`) | ✔ full product/instance tree | ✔ product-level, exactly as STEP | ✔ names + arbitrary typed attributes on any label | ◑ `GetLengthUnit` / `SetLengthUnit` | ✖ | ✖ | XML text | ✔ would need the same color sidecar | ✖ |
| **Wavefront OBJ** (+ `.mtl`) | ◑ **flat `o`/`g` groups only** — no nesting, no per-part transform | ✖ geometry is duplicated per placement | ✔ group names | ✖ | ✖ | ✖ | ASCII text | ✔ `.mtl` + texture files | ✖ |
| **USD** (`.usda` · `.usdc` · `.usd` · `.usdz`) | ✔ prims in an `Xform` hierarchy | ✔ references, `instanceable`, `PointInstancer` | ✔ names + typed metadata/attributes on any prim | ✔ `metersPerUnit` | ✔ `upAxis` | ✔ **`UsdPhysics` joints — the only format here that carries our rig** | text (`.usda`), binary crate (`.usdc`/`.usd`), or an uncompressed zip package (`.usdz`) | ✔ referenced / payloaded layers, bundled inside a `.usdz` | ✔ sublayers, references, payloads, overrides, variants — **the only real composition system here**. A `.usdz` package is read-only, so no override layer can sit on top of it |
| **STL — ASCII** | ✖ | ✖ | ◑ one `solid` name for the whole file | ✖ | ✖ | ✖ | ASCII text | none | ✖ |
| **STL — binary** | ✖ | ✖ | ✖ only an 80-byte free-text header | ✖ | ✖ | ✖ | binary | none | ✖ |
| **PLY — ASCII** | ✖ | ✖ | ✖ comments only | ✖ | ✖ | ✖ | ASCII text | none | ✖ |
| **PLY — binary** | ✖ | ✖ | ✖ comments only | ✖ | ✖ | ✖ | binary (declared endianness) | none | ✖ |
| **glTF 2.0 separate** (`.gltf` + `.bin`) | ✔ node hierarchy with per-node transforms | ✔ mesh reuse by node reference; `EXT_mesh_gpu_instancing` | ✔ node/mesh names + `extras` | ✔ **meters, fixed by spec** | ✔ **Y-up, fixed by spec** | ◑ skinning + animation, but no joint types or limits | JSON + external binary buffer | ✔ `.bin` + texture files | ✖ |
| **glTF 2.0 binary** (`.glb`) | ✔ node hierarchy with per-node transforms | ✔ mesh reuse by node reference; `EXT_mesh_gpu_instancing` | ✔ node/mesh names + `extras` | ✔ **meters, fixed by spec** | ✔ **Y-up, fixed by spec** | ◑ skinning + animation, but no joint types or limits | single binary container | ✔ buffers + textures embedded | ✖ |
| **OFF** | ✖ | ✖ | ✖ | ✖ | ✖ | ✖ | ASCII text | none | ✖ |
| **3MF** | ✔ build items + components with transforms | ✔ components reference shared objects | ✔ object names + metadata entries | ✔ **explicit unit attribute** | ◑ Z-up build-platform convention, not a declared axis | ✖ | XML in a zip | ✔ bundled in the package | ✖ |
| **COLLADA** (`.dae`) | ✔ nodes with transforms | ✔ `instance_geometry` / `instance_node` | ✔ ids + names throughout | ✔ `asset/unit` | ✔ **`asset/up_axis`** | ◑ a kinematics extension exists — **❓** | ASCII XML | ✔ texture files | ✖ |
| **COLLADA zipped** (`.zae`) | ✔ nodes with transforms | ✔ `instance_geometry` / `instance_node` | ✔ ids + names throughout | ✔ `asset/unit` | ✔ **`asset/up_axis`** | ◑ a kinematics extension exists — **❓** | ASCII XML in a zip | ✔ bundled in the archive | ✖ |
| **VRML 1.0** (`.wrl`) | ✔ `Separator` node graph | ✔ `DEF` / `USE` | ◑ `DEF` names only | ✖ no unit declaration | ◑ Y-up by convention | ✖ | ASCII text | ✔ texture files | ✖ |
| **VRML 2.0 / VRML97** (`.wrl`) | ✔ `Transform` node graph | ✔ `DEF` / `USE` | ◑ `DEF` names only | ✖ meters by convention only | ◑ Y-up by convention | ✖ | ASCII text | ✔ texture files | ✖ |

### What the Capability Matrix Implies

- **Only STEP gives us B-rep** — and only when B-rep is actually in the file. AP203/AP214 always carry it; **AP242 may carry B-rep, tessellation, or both**, so "it's a STEP file" is not the same as "it has B-rep" (see the dual-mode requirement below). B-rep is what analytic snapping, adjustable re-tessellation, and exact re-export depend on. Everything else in this table is a tessellation, permanently.
- **AP242 needs dual-mode import (intended behavior).** A STEP file must be brought in as **B-rep when B-rep is present** — strongly preferred, and we generate our own mesh from it at whatever quality the user picks — and as a **mesh model when only tessellation is present**, taking the file's triangles as-is and gating the analytic features off exactly as any mesh import does. The distinguishing test has to be *"does this shape have analytic faces"*, not *"is this a STEP file"* or *"is `shape` non-None"*. Today the capability predicate is the latter (`assembly_has_brep` = `any(c.shape is not None)`), which is why the AP242 tessellated-only case is flagged in the deltas table.
- **Only USD carries a rig.** Joints, units, up-axis, composition, and per-face color all live in one format — which is why it is the export target and not merely one option among several.
- **Color granularity is the sharpest discriminator on import.** STEP/USD/OBJ/PLY/3MF can express more than one color per part; STL and OFF cannot express any. A model that arrives as STL has thrown away appearance before we ever see it.
- **Hierarchy is the second discriminator.** STEP, USD, glTF, 3MF, and COLLADA carry a real tree with transforms; OBJ carries a flat group list; STL and PLY carry nothing. Since grouping components into links is the core human task, a flat or absent tree makes a file dramatically less useful regardless of geometric fidelity.
- **Nothing but USD and AP242 has any notion of kinematics**, and AP242's is effectively out of reach in this binding (❓ above). There is no route to importing an existing joint definition today.

### CellSmith Implementation Deltas

Where our reader/writer deliberately or incidentally uses **less** than the format allows. Recorded as current state — **not as a work list.**

| Area | Format allows | CellSmith does | Note |
|---|---|---|---|
| OBJ export color | per-face via `usemtl` runs | **one `usemtl` per leaf part** (colors deduped across parts) | Asymmetric with import, which *does* read per-triangle material colors. A multi-colored part exports flattened. |
| OBJ export attributes | `vn` normals, `vt` UVs | vertices + triangles + `usemtl` only | Consumers recompute normals; flat/faceted shading is expected. |
| USD export normals | authored `normals` primvar | not authored | Renderer-computed. |
| USD `subdivisionScheme` | explicit token; **schema default is `catmullClark`** | not set → inherits the default | Latent: at refinement level 0 nothing subdivides, so it usually never bites. **❓ NEEDS RESEARCH — confirm Isaac/usdview don't smooth our meshes when refinement is enabled.** |
| USD precision | float32 points | mm→m scale baked into points (`export_scale` 0.001) | Not a workaround for f32 so much as an Isaac requirement, but it also keeps magnitudes small enough that f32 is comfortable. |
| STEP export schema | AP203, AP214CD/DIS/IS, AP242DIS are all accepted values | writes **AP214IS** | `writer.py`'s `Interface_Static.SetCVal("write.step.schema", "AP214")` returns **False** — plain `"AP214"` is not a valid value (probe-verified). Output is AP214IS regardless, because that is OCC's default, so behavior is correct by accident rather than by the call. |
| AP242 tessellated import | B-rep and/or tessellation, independently | `read.step.tessellated` defaults to `On`; the loader routes purely on **file extension** (`is_step_path` → STEP/OCC path, `is_mesh_path` → mesh path), and the B-rep capability predicate is `any(c.shape is not None)` | **The intended behavior is dual-mode: B-rep when present, mesh when not** (see the point above). A tessellation-only AP242 file takes the STEP path by extension and **may still yield OCC `shape`s carrying only triangulations — which would make `assembly_has_brep` report True for a model with no analytic surfaces**, silently enabling analytic snapping, quality re-tessellation, and STEP re-export on data that can't support them. **❓ NEEDS RESEARCH** — no AP242 tessellated-only fixture exists; every STEP file in hand is AP214-style with real B-rep. A face-count/surface-type test is the likely predicate, but the failure mode has to be observed before it can be designed against. |
| Mesh per-face color persistence | per-face color | read on import, **no per-face color OVERRIDE persistence** | Known deferred item in `mesh-import.md` (needs a config schema for per-face overrides). |
| PLY / OFF vertex colors | per-vertex and per-face | `visual.face_colors` is read, and trimesh derives face colors from vertex colors | **❓** — plausible but no fixture; the validated color paths are OBJ materials and USD `displayColor`. |

## Legacy CellSmith Model Format — Moved

The on-disk cache map (layout, every file's contents and key, the two backends sharing one layout, staleness + the four version tokens, and the eight observations for a future format) now lives in the **user docs**:

- [`docs/src/AI/Scratch/legacy-cellsmith-model-format.md`](../Scratch/legacy-cellsmith-model-format.md)

Named *Legacy* to keep it distinct from a successor design, and **on hold** pending the taxonomy work. `Misc/` is a temporary placeholder until the user docs are organised.

## Actionable Now

**The exception to this document's INACTIVE status** — but only in the sense that these are *ready*, not that they are *approved*. Everything here is a small, low-risk change that could be rolled into `src/` today to prevent a bug or a silent wrong behavior. None of them needs research first, none changes a design, and none is a new feature. Ordered by risk prevented per line changed.

Still requires the user's go-ahead, and all of it is in files another agent currently owns.

| # | Where | Change | Why now |
|---|---|---|---|
| 1 | `src/io_mesh/formats.py` (+ `packaging/environment.yml`) | `.3mf` and `.dae` are in `TRIMESH_EXTENSIONS` and advertised in the Open dialog, but both loaders are dead. **Either** add `networkx` + `pycollada` to the pip block, **or** remove the two extensions. | **The only live user-facing bug found.** Selecting a `.3mf` or `.dae` today raises. Both fixes are one line; both are strictly better than the status quo. |
| 2 | `src/export/usd_writer.py` | Author `subdivisionScheme = "none"` on every `UsdGeom.Mesh`. | The USD schema default is `catmullClark`. Our meshes are tessellations, never subdivision cages, so `none` is simply what we mean. Setting it removes the latent smoothing risk **without** waiting on the Isaac refinement research. One line per mesh-authoring site. |
| 3 | `src/io_step/writer.py` (~line 84) | `Interface_Static.SetCVal("write.step.schema", "AP214")` → `"AP214IS"`, and check the return value. | Probe-verified: plain `"AP214"` is **rejected** (returns `False`). Output is AP214 today only because that is OCC's default, so the code's stated intent isn't actually being enforced — and it would break silently if a future OCCT changed the default. Accepted values: `AP203`, `AP214CD`, `AP214DIS`, `AP214IS`, `AP242DIS`. |
| 4 | `src/gui/main_window.py` `_export_subtree` (or the export CLIs) | Reject or normalize a `.usdz` output path with a clear message. | The USD save dialog includes `All files (*)`, so a user can type `foo.usdz`; `Stage.CreateNew` on `.usdz` raises a raw pxr `ErrorException` (probe-verified). A one-line guard turns a confusing traceback into "USDZ export isn't supported — save as .usd/.usda". |
| 5 | `src/io_step/reader.py` | Log a warning when a STEP leaf's shape contains **zero faces** (i.e. it carries only a triangulation). | This is the *actionable half* of the AP242 tessellated-only research item: it doesn't attempt to fix the capability predicate, it just makes the situation **visible the first time it occurs** instead of silently mis-gating analytic features. Cheap, no behavior change. |
| 6 | `docs/src/AI/Reference/mesh-import.md` | Add the dependency caveat to the supported-extension list (`+PLY/GLTF/GLB/3MF/DAE/OFF`). | Docs-only. The list currently reads as fully supported, which is how the `.3mf`/`.dae` gap stayed invisible. Keeps the next reader from re-deriving it. |

Deliberately **not** on this list, because each is a design decision or needs research rather than a fix: per-face OBJ export color, the `assembly_has_brep` predicate change for tessellated AP242, USD normals authoring, USDZ export support, and every ⚪ format in the matrix.

## Probe Basis

Every ✅/⚪/⚠/❌ above was checked against the installed `CellSmithEnv` rather than inferred from documentation, via throwaway probes (`conda run -n CellSmithEnv`) that: enumerated the OCC data-exchange modules and classes actually present in the `novtk` build; dumped `trimesh`'s loader registries plus `mesh_formats()`/`available_formats()` and round-tripped a box through every candidate extension; enumerated `Sdf.FileFormat.FindAllFileFormatExtensions()` and tried `Stage.CreateNew` + `Stage.Open` per USD extension (this is how the `.usdz` write refusal and the `UsdUtils` workaround were established); and listed `pyvista`'s `CLASS_READERS` and `Plotter.export_*`. The probes were scratchpad-only — nothing in the repo was modified. Re-run them after any dependency change: an added or removed optional dep silently moves formats between ⚪ / ⚠ / ✅.

For the capability matrix, the STEP-specific claims were probed the same way: constructing a `STEPCAFControl_Writer`/`Reader` first (the `Interface_Static` parameters do not exist until then — probing cold returns empty strings and every `SetCVal` fails), then enumerating accepted `write.step.schema` values, reading the tessellated/product/unit/codepage defaults, and checking which XCAF tools and `Step*`/`RWStep*` modules the `novtk` build actually exposes. Also probed for the variant rows: both XCAF storage formats round-tripped a colored box (`BinXCAF` → `BINFILE` magic, `XmlXCAF` → XML text, colors preserved through save/close/reopen); `breptools.Write` vs `bintools.Write` byte sizes on the same box (2,565 ASCII vs 4,494 binary); the encoding pxr actually writes per USD extension (`.usd` and `.usdc` → `PXR-USDC` crate, `.usda` → `#usda 1.0` text); and the `IGESCAFControl` reader/writer mode setters (`ColorMode`/`NameMode`/`LayerMode` exist in both directions). Capability claims with **no** probe behind them — 3MF, COLLADA, VRML 1.0, OFF color, AP203 e2 styling, AP242 tessellated-only behavior — carry a **❓** rather than a mark. The `.xbf` / sidecar / npz / stamp contents in the CellSmith Model Format section were read from `src/io_step/cache.py`, `src/io_mesh/mesh_cache.py`, `src/gui/mesh_ops.py`, `src/gui/edge_pick.py`, and `src/model/scene_config.py` — not probed against a live cache dir, so field names track those modules and will drift if they do.

## Unresolved — Genre, Name, Audience

Deferred by the user; decide before wiring this file into the doc index. These are questions **about this document**, not about the app — none of them is implementation work.

1. **Genre.** Candidates: (a) `Reference/` — it mostly describes what the code does now and would then be gardened alongside `mesh-import.md`/`export.md`; (b) stay in `Specs/` — defensible only if it becomes the *contract* for which formats CellSmith commits to supporting; (c) **user-facing docs** — a "supported file formats" page for the app/README, which would mean dropping the library internals, the ⚪ column, and the probe section.
2. **Split? — PARTLY RESOLVED.** Two sections have already moved into the user docs (`docs/src/AI/Scratch/intro-model-structure.md`, `docs/src/AI/Scratch/legacy-cellsmith-model-format.md`), which settles the "our own structure vs external formats" half. Still open for what remains: the ✅ rows (what the app does) and the ⚪/❌ rows (what the libraries could do) serve different readers, so a user-facing "supported formats" table plus a `Reference/` capability matrix is still a plausible end state.
2b. **Table width — RESOLVED.** Keep the two tables (Geometry/Appearance, Structure/Semantics) split; a single 15-column table is unreadable in a terminal.
2c. **Variant granularity — RESOLVED for USD.** Capability-distinct variants get their own rows, but **USD stays one row** across `.usda`/`.usdc`/`.usd`/`.usdz` — those differ only in encoding and packaging, not capability. Still open: whether the **File Formats** table (which keeps `USD` and `USDZ` as two rows, because their *export* status genuinely differs) should be re-aligned with the capability tables' row set.
3. **Name.** `model_formats.md` (current), `file-formats.md`, `supported-formats.md`, `format-support-matrix.md`, `io-formats.md`. Note the rest of `docs/src/AI/` uses kebab-case (`mesh-import.md`, `scene-config-and-orientation.md`); `model_formats.md` is the odd one out, and only `construction_geometry_builder_definitions.md` in `Specs/` shares the snake_case style.
4. **Overlap.** `Reference/export.md` owns export mechanics and `Reference/mesh-import.md` owns the mesh path. This file must stay a *matrix* and not restate either, or it becomes a third place to update on every I/O change.
5. **Ownership on dependency change.** If this stays in `docs/src/AI/`, the "living documentation" rule should name it explicitly: touching `packaging/environment.yml`'s geometry deps or `io_mesh.formats` extension tuples means re-running the probes and updating this table in the same turn.
