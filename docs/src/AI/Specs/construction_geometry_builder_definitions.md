# Construction Geometry Builder — Construction Definitions (design spec)

**Design spec** for the Selection Filter (SF) + Construction Geometry Builder (CGB): the canonical Feature-Exposure Model + the enumerated construction tables — the intended source of truth for what the CGB *should* build. The redesign specified here is **fully implemented**; the as-built lives in `../reference/selection-and-cgb.md`, and future SF/CGB commands are tracked in `../status.md`. Verify against the `cgb_*` modules in `src/`; may lag.

---

## Overview & direction

**What this is.** The **Selection Filter (SF)** and **Construction Geometry Builder
(CGB)** are the shared front-end every command uses to ask the user to pick geometry
— and, when needed, to turn those picks into a reference entity. This document is the
design spec for both, and the roadmap for where they're headed.

**Two ways commands consume them:**
- **Construct** — the CGB turns picks into **one** reference entity. Four are
  enumerated in the construction sections — **Point**, **Axis**, **Plane**,
  **Frame** (origin + orthonormal axes) — and two are *reduced consumptions* of a
  positioned builder: an **Orientation** (a Frame's axes) and a **Direction** (an
  Axis's direction). See *CGB target entities* for the reduction rule.
- **Collect** — the SF returns the **set of picked model entities** (faces / bodies
  / edges) for a command to act on (recolor, group, suppress). No construction.

**Reuse & composition.** Any result can be kept as a **Datum** — shown as a reference
and **chained** into later constructions. The **Feature-Exposure Model** is the
**canonical source** — the compact rule set behind the enumerated construction
tables, which are its generated reference view.

**Where we're headed (phased):**
- **Todo Now** — terminology + the SF/CGB structural pieces: live **Filter**
  narrowing, **Datums**, **Frame**, numeric entry, **Fit Primitives**, **Measure**
  modes, the **command contract**, Collect/Construct.
- **Short-Term** — the first commands on top: **joint / mate inference**, **Unbend
  into an orthogonal pose**.
- **Long-Term** — bulk selection (Select-Similar, loops, marquee), best-fit /
  symmetry constructions, **per-face color override**, constraint relations.

---

## Terminology: Point vs Vertex

**Point** — a bare 3D position (x, y, z). It has **no topological identity** and
belongs to nothing; it is only coordinates. A Point may be *derived* from geometry
— an edge endpoint, an arc center, a face-plane origin, an intersection, a
projection, or a free surface hit — but it remains just a location. **Both the
Selection Filter's (SF) point-picker and every CGB construction deal in Points.**

**Vertex** — a **B-Rep topological vertex** (`TopoDS_Vertex`): a 0-dimensional
cell of the analytic boundary model, where edges terminate and meet. It is exact,
named, and carries **topological identity**. A Vertex **has** a position (a Point),
but **most Points are not Vertices**, and a Vertex exists **only on a B-Rep model**
(STEP) — a tessellation-only model has none.

**Is the end of a Tessellated edge a Vertex or a Point?** A **Point**. It is a
mesh node (a triangle corner / polyline endpoint). A tessellation has *no
topology*, so there is no `TopoDS_Vertex` to reference — only coordinates. Only a
pick that references the analytic model — the **Edge** snap on a B-Rep edge —
yields an actual **Vertex**.

> **Naming convention.** The 0-D entity is **Point** in both the SF and the CGB.
> **Vertex** is reserved for the `End` snap on a B-Rep edge.
>
> **Implementation note.** DONE — the code uses `SelectMode.POINT`,
> `ConstructedEntity.kind == "point"`, and `PointSnapMode` (`EDGE/TESS/FREE`). The
> rename was byte-neutral (no persisted config/`.xbf`/stamp value encoded the old
> tokens).

---

## CGB target entities

The CGB builds these reference entities. Four are **enumerated** below
(Point/Axis/Plane/**Frame**); two are **reduced consumptions** of a positioned
builder (Direction/Orientation) and reuse those same enumerations.

**⭐ The reduction rule (one pattern, applied twice).** A positioned builder may be
consumed for only part of itself. There is **no separate builder** for the reduced
form — the CGB runs the SAME construction and the consumer ignores the rest:

| Builder | Reduced consumption |
|---|---|
| **Axis** = origin + direction | **Direction** = the direction only |
| **Frame** = origin + orientation | **Orientation** = the orientation only |

A request therefore carries a **target** *and* a **want** (`cgb_core.WANT_FULL` /
`WANT_DIRECTION` / `WANT_ORIENTATION`). A **button that requests a specific entity
MUST be captioned with what it requests** — *Axis*, *Direction*, *Frame*, or
*Orientation* (`cgb_core.want_label`) — while activating the underlying mode (Axis
or Frame) with that constraint. The CGB bar shows the request name too, so a
direction-only / orientation-only pick reads unambiguously.

| Entity | What it is | How it is built |
|---|---|---|
| **Point** | a position | *enumerated* (Point section) |
| **Direction** | a bare direction (no position) | **an Axis consumed for its direction only** (`WANT_DIRECTION`) |
| **Axis** | a positioned direction (origin + direction) | *enumerated* (Axis section) |
| **Plane** | origin + normal (bounded rect/disc) | *enumerated* (Plane section) |
| **Orientation** | a direction-only orthonormal X/Y/Z frame | **a Frame consumed for its orientation only** (`WANT_ORIENTATION`) |
| **Frame** (internal token `basis`) | a full pose = origin + orientation | *enumerated* (Frame section). Every construction there yields an **origin** as well as the axes, so a Frame needs no composition — but a command that wants an *arbitrary* origin (any Point construction) with an *arbitrary* orientation still composes the two (`FrameBuilder`, e.g. ReOrigin) |

---

## How to read the tables

Each section has one construction table with columns **E · E · E · Default ·
Description · Filter**. These four tables are the **generated reference view** of the
*Feature-Exposure Model* (the canonical rule set — see that section).

- The three **E** columns are **Selection Slots** (Slot 1 / 2 / 3) — the
  selections that feed the construction. Labeled identically ("E") on purpose:
  **slots may be filled in any order.** The *role name* inside each cell (not the
  pick order) determines what a slot's pick contributes.
- A cell is either `None` (that slot is unused) or `role: Primitive[Kind]`:
  - **`role`** — the semantic part the slot's pick contributes (`point`, `axis`,
    `plane`, `normal`, `reference`, …). See *Role names*.
  - **`Primitive[Kind]`** — the *pythonic* selection primitive + kind, matching the
    SF's vocabulary (mode + kind filter). "Primitive" is the outer category; "Kind"
    is the bracket sub-classification (the same word as the SF's *Face Kind* /
    *Edge Kind* filters).
- **`Default`** — `True`/`False`: whether this construction is **offered by
  default**, derived from the *SF Option Defaults*. `False` = hidden by default, not
  invalid. See *Default derivation*.
- **`Filter`** — the **real-time SF constraint applied to the remaining slots once
  earlier slots are filled** (e.g. after one flat face, only *parallel* flat faces
  are selectable for the second). `—` = no constraint. See *Filters*.
- Each section's **Selection types available** table has a **Tess-only** column:
  whether that primitive is available on a tessellation-only (mesh) model. The old
  `No¹` face rows are now **Yes** — **Fit Primitives (F1) is implemented** (a mesh
  face is fitted to an analytic plane/cylinder/sphere in a subprocess on pick), so
  analytic faces work on meshes too; edges/points already worked (reconstructed). Row
  order follows the *Selection primitives* table.

### Selection primitives (the thing you pick)

Row order here defines the table sort order everywhere below.

| Primitive | Kind (bracket) | Provides |
|---|---|---|
| `Point[Any]` | Any | a **point** |
| `Edge[Line]` | Line | a **line** (a point on it + direction) |
| `Edge[Arc]` | Arc | an **arc** (center + axis/normal + the arc's plane) |
| `Edge[Other]` | Other (spline / BSpline / …) | a **point** on the curve (+ tangent); **no single axis** |
| `Face[Flat]` | Flat | a **plane** (origin + normal) |
| `Face[Cylinder]` | Cylinder | an **axis** (the cylinder axis) + radius |
| `Face[Other]` | Other (sphere / cone / NURBS / torus / …) | a **surface point** (+ local normal); **no single axis/plane** |
| `Body[Any]` | Any | a **component** (its centroid / bounding box) |
| `Datum[Point/Axis/Plane/Frame]` | — | a previously-**constructed** or saved reference (see *Datums*); provides the same features as its kind |

### Qualifier axes

**Representation** — which model a pick resolves against:

| Representation | Meaning |
|---|---|
| `B-Rep` | the analytic model — exact faces / edges / vertices |
| `Tess` | the triangle mesh — one facet, or the nearest mesh node |

> Edges come from analytic topology (STEP) **or** reconstructed feature edges
> (mesh); the reconstructed ones behave like B-Rep edges for selection and snapping.
> A mesh-only import has no B-Rep *faces*. STEP offers both.

**Point Snap** — for a `Point`, the snap sub-mode and (for Edge) the target:

| Snap sub-mode | Target | Meaning |
|---|---|---|
| `Edge` | `End` | an edge **endpoint** — a true **Vertex** on B-Rep; a reconstructed endpoint (Point) on mesh |
| `Edge` | `Mid` | the edge midpoint |
| `Edge` | `Center` | the arc / circle center |
| `Tess` | — | nearest mesh node (**no** End/Mid/Center) |
| `Free` | — | arbitrary surface point (no snap) |

> **End/Mid/Center belong to the `Edge` sub-mode only.** `Tess` returns the nearest
> raw mesh node; `Free` returns an arbitrary surface hit. (`Free` is the current
> code's `VertexSubMode.NONE`, to be renamed `FREE`.)

### Role names (closed vocabulary)

| Role | Meaning |
|---|---|
| `point` | contributes a position |
| `center` | a position that is specifically a circle / arc / sphere center |
| `line` | a straight directed line the result lies **along** or **contains** |
| `axis` | a directed line used as the result's **axis** / rotation axis / primary direction |
| `direction` | a bare direction (no position) — a command may consume an Axis for its direction only |
| `normal` | a direction the result is **perpendicular** to (a plane normal) |
| `plane` | a full plane the result uses (a flat face's plane; an arc's own plane) |
| `tangent` | a face the result must be tangent to |
| `primary` / `secondary` / `reference` | Frame-specific roles (see that section) |

### Config modifiers (NOT selections)

Bar controls, not E columns; they appear only in Descriptions:

- **Tilt A / Tilt B** — world-axis tilt angles (Rodrigues), to finish
  under-constrained definitions.
- **Offset** — shift a plane along its normal.
- **Flip** — negate the resulting axis direction / plane normal / basis primary.
- **Shape + extents** — a Plane's bounded footprint: `rect` (u/v) or `disc`
  (diameter + center). Cosmetic to the frame.
- **Numeric input (opt-in).** A **Numeric input** checkbox (**default OFF** —
  mouse-picking is the intuitive default) reveals fields to type exact values for
  the active construction: coordinates (a point), a direction, a distance/offset, an
  angle, a radius. Off by default so the bar stays uncluttered.

### Reference frame (correctness-critical)

All directions/angles — Tilt A/B, "world X/Y/Z", the global-origin datum — are in
the **displayed (oriented) frame** (the model's export/Main orientation as shown),
**not** the raw source frame. Under a Source→Main orientation these differ, and
conflating them silently rotates the result (this caused the "Butler origin" bug).

### Validity, preview & feedback

- **Live preview** as soon as the picks make the construction valid; updates on
  every further pick / angle / offset.
- **Validity states** per slot (awaiting / satisfied / not-needed); Accept enabled
  only when valid.
- **Degenerate cases** — the `Filter` column prevents most; residual degeneracy
  fails with a **clear message**, never a silent wrong result.

### Status tags (in Description)

- `[impl]` — resolvable by the CGB (originally the hardcoded resolvers).
- `[snap]` — delivered via a **Point Snap** (End/Mid/Center), not a distinct
  multi-select construction.
- `[new]` — geometrically sound; authored as its own tag when the spec was written.

> **UPDATE:** the **Feature-Exposure engine** (`cgb_recipes`) now resolves the
> `[new]` multi-slot constructions too — midpoint, centroid, point-projections,
> line∩plane / arc-axis∩plane / cylinder-axis∩plane (all via `LINE_KINDS ∩ PLANE`),
> three-plane intersection, face-normal axis, plane∩plane axis, two-plane mid-plane,
> and the datum/analytic-face rows (sphere center, cylinder axis) — because a recipe
> reads standard SlotEntity fields, not the kind. A few remain genuinely unbuilt
> (e.g. two-line / two-cylinder-axis intersection, body-centroid point,
> tangent-cylinder plane); the `[new]` tag now means "engine-eligible — verify the
> specific recipe exists in `cgb_recipes.RECIPES`", not "unimplemented".

### `Edge[Other]` / `Face[Other]` / `Body[Any]`

- `Edge[Other]` (splines) and `Face[Other]` (sphere/cone/NURBS/torus) yield only a
  **`point`** (on the curve/surface at the pick). **Fit Primitives (F1)** could
  sub-classify an `Other` and unlock its axis/center.
- `Body[Any]` contributes a derived **point** (centroid / bbox center).

---

## Datums & constructed-entity reuse

A construction result can be **kept as a datum** and **reused** — as a visual
reference and as an **input to later constructions** (chaining).

- **Where they live.** Datums render as **pickable glyphs in the viewport** (a point
  marker / axis line / plane quad / triad) and are listed in a small **Datums
  panel** (rename · hide · delete), extending today's global-origin datum aid.
- **How the user selects one.** Click its **glyph in the 3D view**, or its **row in
  the Datums panel**. When a slot accepts a matching feature, an available datum is
  selectable there.
- **Persistence.** A **named** datum is saved per-model in a new `datums` config map
  (alongside `origins`/`joints`), surviving reopen; a **transient** datum lives only
  for the current command.
- **Chaining (datum as input).** A `Datum[Plane]` feeds any slot needing a `plane`,
  a `Datum[Axis]` any slot needing an `axis`/`line`, etc. (see the *Feature-Exposure
  Model*). This is how complex references are built step by step — and the backbone
  of the Unbend workflow.

---

## SF Option Defaults (the tunable knobs)

**Exclusive selectors** — radio-like; **exactly one** active (Point Snap also
allows *neither* = `Free`). Only the **default selection** matters.

| Selector | Options (mutually exclusive) | Default |
|---|---|---|
| Face Representation | `B-Rep` ⊕ `Tess` | `B-Rep` |
| Point Snap | `Edge` ⊕ `Tess` ⊕ `Free` (Edge/Tess are the two buttons; neither = Free) | `Edge` |

**Independent toggles** — checkboxes, each `On`/`Off`. **Everything `On` today**;
later we switch some uncommon ones `Off` to reduce overwhelm.

| Group | Toggle | Default | Candidate to disable later? |
|---|---|---|---|
| Mode | Body / Face / Edge / Point | On | (modes are usually command-driven) |
| Face Kind (B-Rep only) | Flat | On | |
| Face Kind (B-Rep only) | Cylinder | On | |
| Face Kind (B-Rep only) | Other | On | **likely** |
| Edge Kind | Line | On | |
| Edge Kind | Arc | On | |
| Edge Kind | Other | On | **likely** |
| Snap Target (Edge snap only) | End | On | |
| Snap Target (Edge snap only) | Mid | On | |
| Snap Target (Edge snap only) | Center | On | |

### Default derivation

1. A **primitive**'s default = the exclusive selectors' defaults **AND** the
   toggles it requires (shown per section in *Selection types available*).
2. A **construction row**'s `Default` = **AND** of its slots' primitive defaults.
3. **Everything resolves to `True` today.**

### Filters

The `Filter` column is the **live constraint the SF applies to the not-yet-filled
slots**, given what is already picked — it keeps the user from a pick that can't
produce a valid result and makes each construction self-documenting. When
implemented, the CGB translates it into an SF predicate that narrows the remaining
slots. `—` = no constraint.

---

## Point

A **Point** is a single 3D position.

### Selection types available (defaults)

| Primitive | Default | Tess-only | Requires (SF options) |
|---|---|---|---|
| `Point[Any]` | `True` | Yes | Mode·Point + any Point Snap |
| `Edge[Line]` | `True` | Yes | Mode·Edge + Edge Kind·Line |
| `Edge[Arc]` | `True` | Yes | Mode·Edge + Edge Kind·Arc |
| `Face[Flat]` | `True` | No¹ | Mode·Face + Face Rep = B-Rep + Face Kind·Flat |
| `Face[Cylinder]` | `True` | No¹ | Mode·Face + Face Rep = B-Rep + Face Kind·Cylinder |
| `Face[Other]` | `True` | No¹ | Mode·Face + Face Rep = B-Rep + Face Kind·Other |
| `Body[Any]` | `True` | Yes | Mode·Body |

¹ Now **Yes** — **Fit Primitives (F1)** is implemented: a mesh face is fitted to an analytic plane/cylinder/sphere in a subprocess on pick.

### Constructions

| E | E | E | Default | Description | Filter |
|---|---|---|---|---|---|
| `point: Point[Any]` | `None` | `None` | `True` | A directly-picked point — snap `Edge`·**End**/**Mid**/**Center**, `Tess`, or `Free`. `[impl]` | — |
| `point: Point[Any]` | `point: Point[Any]` | `None` | `True` | The **midpoint** between two points. `[new]` | E2 distinct from E1 |
| `point: Point[Any]` | `point: Point[Any]` | `point: Point[Any]` | `True` | The **centroid** of three points. `[new]` | E2, E3 distinct |
| `point: Point[Any]` | `line: Edge[Line]` | `None` | `True` | The point **projected onto** the line. `[new]` | — |
| `point: Point[Any]` | `plane: Face[Flat]` | `None` | `True` | The point **projected onto** the plane. `[new]` | — |
| `line: Edge[Line]` | `line: Edge[Line]` | `None` | `True` | Intersection of two lines (nearest-approach midpoint if skew). `[new]` | E2 not parallel to E1 |
| `line: Edge[Line]` | `plane: Face[Flat]` | `None` | `True` | **Line ∩ plane** intersection point. `[new]` | plane not parallel to the line |
| `axis: Edge[Arc]` | `plane: Face[Flat]` | `None` | `True` | **Arc-axis ∩ plane** intersection point. `[new]` | plane not parallel to the arc axis |
| `plane: Face[Flat]` | `plane: Face[Flat]` | `plane: Face[Flat]` | `True` | Intersection of **three planes**. `[new]` | each plane non-parallel to the others |
| `center: Face[Cylinder]` | `None` | `None` | `True` | The **axis midpoint** of a cylindrical face. `[new]` | — |
| `axis: Face[Cylinder]` | `plane: Face[Flat]` | `None` | `True` | **Cylinder-axis ∩ plane** intersection point. `[new]` | plane not parallel to the cylinder axis |
| `axis: Face[Cylinder]` | `axis: Face[Cylinder]` | `None` | `True` | Intersection / nearest approach of two cylinder axes. `[new]` | E2 axis not parallel to E1 |
| `center: Face[Other]` | `None` | `None` | `True` | The **center** of a spherical face (once Fit Primitives recognizes it). `[new]` | — |
| `point: Body[Any]` | `None` | `None` | `True` | The **centroid** (or bbox center) of a whole component. `[new]` | — |

---

## Axis

An **Axis** is a directed line: **origin + direction**. `Flip` negates the direction.

### Selection types available (defaults)

| Primitive | Default | Tess-only | Requires (SF options) |
|---|---|---|---|
| `Point[Any]` | `True` | Yes | Mode·Point + any Point Snap |
| `Edge[Line]` | `True` | Yes | Mode·Edge + Edge Kind·Line |
| `Edge[Arc]` | `True` | Yes | Mode·Edge + Edge Kind·Arc |
| `Face[Flat]` | `True` | No¹ | Mode·Face + Face Rep = B-Rep + Face Kind·Flat |
| `Face[Cylinder]` | `True` | No¹ | Mode·Face + Face Rep = B-Rep + Face Kind·Cylinder |
| `Face[Other]` | `True` | No¹ | Mode·Face + Face Rep = B-Rep + Face Kind·Other |

¹ Now **Yes** — **Fit Primitives (F1)** recovers the analytic face on a mesh (implemented).

### Constructions

| E | E | E | Default | Description | Filter |
|---|---|---|---|---|---|
| `point: Point[Any]` | `None` | `None` | `True` | Through one point; direction from **Tilt A + Tilt B**. `[impl]` | — |
| `point: Point[Any]` | `point: Point[Any]` | `None` | `True` | The line **through two points**, anchored at their midpoint. `[impl]` | E2 distinct from E1 |
| `point: Point[Any]` | `line: Edge[Line]` | `None` | `True` | Through the point, **parallel** to the edge direction. `[new]` | — |
| `point: Point[Any]` | `normal: Face[Flat]` | `None` | `True` | Through the point, **perpendicular** to the face. `[new]` | — |
| `point: Point[Any]` | `axis: Face[Cylinder]` | `None` | `True` | Through the point, **parallel** to the cylinder axis. `[new]` | — |
| `line: Edge[Line]` | `None` | `None` | `True` | Along a straight edge, anchored at its midpoint. `[impl]` | — |
| `axis: Edge[Arc]` | `None` | `None` | `True` | The arc's **axis (normal)**, through its center. `[impl]` | — |
| `normal: Face[Flat]` | `None` | `None` | `True` | The face **normal**, through the face origin. `[new]` | — |
| `plane: Face[Flat]` | `plane: Face[Flat]` | `None` | `True` | The **intersection line** of two planes. `[new]` | E2 plane not parallel to E1 |
| `axis: Face[Cylinder]` | `None` | `None` | `True` | The **cylinder's axis**. `[new]` | — |
| `axis: Face[Other]` | `None` | `None` | `True` | The **cone's axis** (once Fit Primitives recognizes it). `[new]` | — |

---

## Plane

A **Plane** is an **origin + normal** (bounded `rect`/`disc`, optional `Offset`
along the normal). `Flip` negates the normal.

### Selection types available (defaults)

| Primitive | Default | Tess-only | Requires (SF options) |
|---|---|---|---|
| `Point[Any]` | `True` | Yes | Mode·Point + any Point Snap |
| `Edge[Line]` | `True` | Yes | Mode·Edge + Edge Kind·Line |
| `Edge[Arc]` | `True` | Yes | Mode·Edge + Edge Kind·Arc |
| `Face[Flat]` | `True` | No¹ | Mode·Face + Face Rep = B-Rep + Face Kind·Flat |
| `Face[Cylinder]` | `True` | No¹ | Mode·Face + Face Rep = B-Rep + Face Kind·Cylinder |

¹ Now **Yes** — **Fit Primitives (F1)** recovers the analytic face on a mesh (implemented).

### Constructions

| E | E | E | Default | Description | Filter |
|---|---|---|---|---|---|
| `point: Point[Any]` | `None` | `None` | `True` | Through one point; normal from **Tilt A + Tilt B**. `[impl]` | — |
| `point: Point[Any]` | `point: Point[Any]` | `None` | `True` | A plane **containing the P1–P2 line**, tilted by **Tilt A**. `[impl]` | E2 distinct from E1 |
| `point: Point[Any]` | `point: Point[Any]` | `None` | `True` | The **perpendicular-bisector** (mid) plane of two points. `[new]` | E2 distinct from E1 |
| `point: Point[Any]` | `point: Point[Any]` | `point: Point[Any]` | `True` | The plane **through three points** (origin = centroid). `[impl]` | E2 distinct; E3 non-collinear with E1,E2 |
| `axis: Edge[Line]` | `None` | `None` | `True` | A plane **containing** the line, rotatable by **Tilt A**. `[impl]` | — |
| `axis: Edge[Line]` | `point: Point[Any]` | `None` | `True` | The plane **through the line and the point**. `[impl]` | point not on the line |
| `normal: Edge[Line]` | `point: Point[Any]` | `None` | `True` | A plane **perpendicular** to the edge, through the point. `[new]` | — |
| `line: Edge[Line]` | `line: Edge[Line]` | `None` | `True` | The plane containing two lines. `[new]` | E2 not collinear with E1 |
| `axis: Edge[Arc]` | `None` | `None` | `True` | A plane **containing** the arc's axis line, rotatable by **Tilt A**. `[impl]` | — |
| `plane: Edge[Arc]` | `None` | `None` | `True` | The plane the **arc lies in** (⊥ its axis, through the center). `[new]` | — |
| `axis: Edge[Arc]` | `point: Point[Any]` | `None` | `True` | The plane **through the arc-axis line and the point**. `[impl]` | point not on the arc axis |
| `plane: Face[Flat]` | `None` | `None` | `True` | The face's own plane. `[impl]` | — |
| `normal: Face[Flat]` | `point: Point[Any]` | `None` | `True` | A plane **parallel** to the face, through the point. `[new]` | — |
| `plane: Face[Flat]` | `plane: Face[Flat]` | `None` | `True` | The **mid-plane / symmetry plane** between two faces. `[new]` | E2 face must be parallel to E1 |
| `axis: Face[Cylinder]` | `None` | `None` | `True` | A plane **containing** the cylinder axis, rotatable by **Tilt A**. `[new]` | — |
| `axis: Face[Cylinder]` | `point: Point[Any]` | `None` | `True` | The plane **through the cylinder axis and the point**. `[new]` | point not on the cylinder axis |
| `tangent: Face[Cylinder]` | `point: Point[Any]` | `None` | `True` | A plane **tangent** to the cylinder, toward the point. `[new]` | — |

---

## Frame (Basis / Orientation)

A **Frame** (UI label **Frame**; internal token `basis`) is an **orthonormal X/Y/Z
frame plus an origin**. Consumed for its axes alone it is an **Orientation**
(`WANT_ORIENTATION`) — the same construction, minus the position; that is why the
older name for this section was *Basis (Orientation)* and why its anchor point used
to be described as "for drawing only". The user chooses
which axis the **primary** defines (`basis_primary_axis`, default **Z**) and which
the **secondary/reference** defines (`basis_secondary_axis`, default **X**, ≠
primary); the **third** follows by the **right-hand rule**. `Flip` negates primary.

- **`primary`** — pins the primary axis direction.
- **`reference`** — an in-plane point the secondary points toward (projected ⊥ primary).
- **`secondary`** — a selection giving the secondary direction directly.

**Two independent flips.** `Flip` (the params row) negates the **primary**;
a second **`Flip`** checkbox — sitting between the Primary X/Y/Z buttons and the
*Secondary Axis* label — negates the **secondary** (`basis_secondary_flip`). The
third axis follows the right-hand rule, so it reverses with whichever is flipped, and
the frame stays right-handed. The secondary Flip is **shown only when a selection
PINS the secondary**: with a free secondary, angle A ±180° already is that flip.

**⭐ Where the ORIGIN comes from — the FIRST-PICKED-POINT rule.** A Frame anchors at
**the first point the user picked**, in every row that includes one — one point or
two, with or without a face. A picked point is a position the user *means to place*,
so it beats any derived location. Only when a row has **no** point at all does the
frame fall back to the primary's own anchor: an **edge/axis** → its midpoint/centre;
a **face** → the face origin.

This makes the origin **independent of which selection is primary**, so the same
three picks in a different order anchor identically (they still differ in *which axis
is exact* — see below).

> **Axis and Plane are NOT affected**: an Axis from two points stays anchored at
> their midpoint and a 3-point Plane at their centroid (see those sections). For a
> line or a plane the anchor is incidental; for a Frame it is a pose.

**Which selection is PRIMARY — slot 1 (pick order matters).** The primary axis comes
from **E1**, and the other selections supply the secondary (projected ⊥ primary). So
`Plane·Point·Point` and `Point·Point·Plane` are BOTH fully defined but are DIFFERENT
frames: the first makes the face normal exact, the second makes the P1→P2 line exact.
Pick first whichever axis must be exact.

### Selection types available (defaults)

| Primitive | Default | Tess-only | Requires (SF options) |
|---|---|---|---|
| `Point[Any]` | `True` | Yes | Mode·Point + any Point Snap |
| `Edge[Line]` | `True` | Yes | Mode·Edge + Edge Kind·Line |
| `Edge[Arc]` | `True` | Yes | Mode·Edge + Edge Kind·Arc |
| `Face[Flat]` | `True` | No¹ | Mode·Face + Face Rep = B-Rep + Face Kind·Flat |
| `Face[Cylinder]` | `True` | No¹ | Mode·Face + Face Rep = B-Rep + Face Kind·Cylinder |

¹ Now **Yes** — **Fit Primitives (F1)** recovers the analytic face on a mesh (implemented).

### Constructions

| E | E | E | Default | Description | Filter |
|---|---|---|---|---|---|
| `primary: Point[Any]` | `None` | `None` | `True` | Single point — primary from **Tilt A + Tilt B**; secondary auto-perpendicular. `[impl]` | — |
| `primary: Point[Any]` | `primary: Point[Any]` | `None` | `True` | Primary = line through the two points; secondary from **rotation angle A**. `[impl]` | E2 distinct from E1 |
| `primary: Point[Any]` | `primary: Point[Any]` | `reference: Point[Any]` | `True` | Primary = line through the two points; secondary toward the reference. `[impl]` | E2 distinct; reference off the E1–E2 line |
| `primary: Edge[Line]` | `None` | `None` | `True` | Primary = line direction; secondary from **rotation angle A**. `[impl]` | — |
| `primary: Edge[Line]` | `reference: Point[Any]` | `None` | `True` | Primary = line direction; secondary toward the reference (⊥ primary). `[impl]` | reference not on the line |
| `primary: Edge[Line]` | `secondary: Edge[Line]` | `None` | `True` | Primary = first edge; secondary = second edge direction (⊥ primary). `[new]` | E2 edge not parallel to E1 |
| `primary: Edge[Arc]` | `None` | `None` | `True` | Primary = arc axis; secondary from **rotation angle A**. `[impl]` | — |
| `primary: Edge[Arc]` | `reference: Point[Any]` | `None` | `True` | Primary = arc axis; secondary toward the reference. `[impl]` | reference not on the arc axis |
| `primary: Face[Flat]` | `None` | `None` | `True` | Primary = face **normal**; secondary from **rotation angle A**. `[new]` | — |
| `primary: Face[Flat]` | `reference: Point[Any]` | `None` | `True` | Primary = face **normal**; secondary toward the reference. `[new]` | reference off the face normal |
| `primary: Face[Flat]` | `secondary: Edge[Line]` | `None` | `True` | Primary = face normal; secondary = the in-plane edge direction. `[new]` | edge not perpendicular to the face |
| `primary: Face[Flat]` | `secondary: Face[Flat]` | `None` | `True` | Primary = first face normal; secondary = second face normal (⊥ primary). `[new]` | E2 face not parallel to E1 |
| `primary: Face[Flat]` | `point: Point[Any]` | `point: Point[Any]` | `True` | Primary = face **normal**; secondary = the **P1→P2 direction** (projected ⊥ primary); **origin = P1**. The workhorse row: a mounting face gives the exact primary axis, two features give the in-plane reference, and the first point gives the position. `[new]` | E3 distinct from E2; P1→P2 not parallel to the normal |
| `primary: Face[Cylinder]` | `reference: Point[Any]` | `None` | `True` | Primary = cylinder **axis**; secondary toward the reference. `[new]` | reference not on the cylinder axis |

---

## Composed Frame (an arbitrary Point + an arbitrary Orientation)

The Frame table above always yields an origin, but that origin is whatever the
construction anchors at. When a command needs an **arbitrary** origin (any Point
construction — a midpoint, a centroid, a projection) paired with an **arbitrary**
orientation, it **composes** the two instead:

- **No new construction table** — it reuses the Point and Frame enumerations.
- **What composes Frames.** ReOrigin (`origin_window`) and joint-frame authoring;
  Unbend will share the same flow.
- **UI.** Two grouped pickers in one command: *Origin* (a Point construction, full
  `WANT_FULL`) and *Orientation* (a Frame construction consumed with
  `WANT_ORIENTATION`), each with its own slots; Accept emits the combined 4×4.
- Implementation: `cgb_command.FrameBuilder` → `ConstructedEntity(kind="frame")`,
  4×4 via `cgb_recipes.frame_matrix4`.

---

## Feature-Exposure Model (generative spec)

> **Status: adopted — the canonical source.** The four construction tables above are
> the **generated reference view** of these rules; when they disagree, these rules
> win. We keep the enumerated tables for human review — regenerate them from these
> rules as selections / recipes change.

The big tables above are the **expanded enumeration**. This is the **compact
generative rule set that produces them**: (A) what geometric **features** each
selection exposes, and (B) each target's **recipes over features**. Substituting —
for each feature slot in a recipe — every selection that exposes it (Table A)
regenerates the big tables. Adding a new selection (or a `Datum`) auto-slots into
every recipe that needs its features.

**Feature vocabulary:** `point` (position) · `direction` (unit direction) · `line`
(point + direction) · `plane` (origin + normal) · `radius` (scalar) · `orientation`
(3 directions).

### Table A — features each selection exposes

| Selection | Features exposed |
|---|---|
| `Point[Any]` | point |
| `Edge[Line]` | point · direction · line |
| `Edge[Arc]` | center (point) · axis (line) · plane · radius |
| `Edge[Other]` | point |
| `Face[Flat]` | origin (point) · normal (direction) · plane |
| `Face[Cylinder]` | axis (line) · radius |
| `Face[Other]` | point |
| `Body[Any]` | centroid (point) |
| `Datum[Point]` | point |
| `Datum[Axis]` | line · direction |
| `Datum[Plane]` | plane · origin (point) · normal |
| `Datum[Frame]` | orientation |

### Table B — target recipes over features

Each recipe expands to the big-table rows by substituting Table-A providers.

| Target | Recipe (role: feature) | + modifier | Notes |
|---|---|---|---|
| **Point** | `{point}` | | direct pick |
| **Point** | `{point, point}` | | midpoint |
| **Point** | `{point, point, point}` | | centroid |
| **Point** | `{project: point, onto: line}` | | foot on the line |
| **Point** | `{project: point, onto: plane}` | | foot on the plane |
| **Point** | `{line ∩ line}` | | two-line intersection |
| **Point** | `{line ∩ plane}` | | line–plane intersection |
| **Point** | `{plane ∩ plane ∩ plane}` | | three-plane intersection |
| **Point** | `{center}` | | arc / cylinder / sphere center |
| **Axis** | `{line}` | | along a directed line |
| **Axis** | `{point, point}` | | through two points |
| **Axis** | `{through: point, along: direction}` | | through a point, along a direction |
| **Axis** | `{normal-of: plane}` | | a plane's normal line |
| **Axis** | `{plane ∩ plane}` | | two planes' intersection line |
| **Axis** | `{through: point}` | Tilt A,B | direction from tilts |
| **Plane** | `{plane}` | Offset | use a plane directly |
| **Plane** | `{point, point, point}` | | through three points |
| **Plane** | `{contains: line, through: point}` | | through a line and a point |
| **Plane** | `{contains: line}` | Tilt A | containing a line, rotated |
| **Plane** | `{contains: point, point}` | Tilt A | containing the 2-point line, rotated |
| **Plane** | `{through: point}` | Tilt A,B | normal from tilts |
| **Plane** | `{normal: line, through: point}` | | ⊥ a line, through a point |
| **Plane** | `{parallel: plane, plane}` | | mid-plane (two parallel planes) |
| **Plane** | `{parallel: plane, through: point}` | | parallel to a plane, at a point |
| **Plane** | `{tangent: cylinder, side: point}` | | tangent toward a point |
| **Frame** | `{primary: line}` | ref-point \| angle A | primary from a directed line |
| **Frame** | `{primary: point, point}` | ref-point \| angle A | primary from two points |
| **Frame** | `{primary: point}` | Tilt A,B | primary from tilts |
| **Frame** | `{primary: normal-of plane}` | ref-point \| angle A | primary from a face normal |
| **Frame** | (any primary) `+ {secondary: direction}` | | secondary from an edge / face-normal / datum |

**Worked example.** Plane recipe `{contains: line, through: point}` expands — the
`line` providers are `Edge[Line]`, `Edge[Arc]·axis`, `Face[Cylinder]·axis`,
`Datum[Axis]`; the `point` providers are every `point`-exposing selection — giving
the enumerated "through the line/arc-axis/cylinder-axis and the point" rows for free
(plus datum variants).

---

## Selection Filter layer & command contract

The SF is the input layer beneath the CGB. Commands consume it two ways
(architectural distinction — the user just picks):

- **Construct** — picks feed the CGB → **one** derived entity
  (Point/Axis/Plane/Frame, + the reduced Direction/Orientation). Used by ReOrigin,
  joints, cuts, Measure, Unbend.
- **Collect** — picks return the **set of picked model entities themselves** (no
  construction): a bag of faces / bodies / edges. Used by per-face color override
  (faces), link grouping (bodies), suppress/hide (subtrees). This is the SF's Multi
  mode; Select-Similar / Loop / Marquee build the set.

**SF configuration (per pick request):** Modes (Body / Face / Edge / Point — Body
exclusive with the F/E/V group) · Quantity (Single / Multi) · sub-modes + kind
filters · priority fall-through when several modes are active (Vertex > Edge > Face
> Body) · capability gating (`has_brep` / `has_edges`).

**Command contract (documented in code — types + docstrings — at minimum):** a
command declares a `SelectionSpec` (Collect) or a CGB request (Construct — which
target + slots); the subsystem returns a typed result — a `SelectionResult`
(Collect) or a `ConstructedEntity` (Construct) — with provenance for re-edit. One
place to wire every command's selection needs. This doc is the design overview; the
enforced contract lives in code.

---

## Cross-cutting notes

- **Capability gating (mesh vs B-Rep).** Analytic faces + cylinder/arc axes need
  B-Rep; a mesh has only reconstructed edges + tessellation points, so on a mesh the
  constructions collapse to the `Point[Any]`/reconstructed-edge rows until
  **Fit Primitives (F1)**. This hard *capability* gate is distinct from the soft
  *SF Option Defaults*.
- **Anchoring.** Axis/Plane rows note where the result is anchored (axis of two
  points = their midpoint; 3-point plane = their centroid). A **Frame** anchors at
  the **first picked point** if the row has one, else at the primary's own anchor —
  see the Frame section's *Where the ORIGIN comes from*.
- **Under-constrained → parameters.** Spare DOF is finished by **Tilt A/B** or
  **rotation angle A**, not an extra pick.
- **A picked `reference`/point pins over an angle** for the same DOF — and once
  pinned the angle is INERT: the bar hides its field and ring
  (`cgb_recipes.basis_secondary_pinned`, the one predicate both the resolver and the
  UI gates consult).
- **Order independence — with ONE exception.** Meaning comes from roles, not pick
  order, *except* that **slot 1 names the primary axis**. Two orders of the same
  picks therefore give two valid but different frames (which axis is exact); the
  ORIGIN is order-independent (first picked point).

---


## Implementation status & future work

The **Todo Now** checklist that used to live here is **all shipped** (headless/offscreen-verified; GL live-test pending) — see `../reference/selection-and-cgb.md` for the as-built. The **Short-Term** and **Long-Term** todos (joint/mate inference, unbend/pose, per-face color override, Select-Similar, loops, marquee, symmetry/mid-plane, constraint relations, saved selection sets) are tracked in `../status.md` under "Future SF/CGB commands."
