# Status & open work (ledger)

The single running ledger: what's built (**Status / as-built**) and what's open (**OPEN TODO**), merged, plus the CGB spec's future commands. Volatile by design — this is where changelog/"how we got here" detail and pending work live, so the `Reference/` docs can stay stable.

- **last gardened:** 2026-07-27 (initial doc-split build)
- **Gardening rule:** garden this file (prune/collapse the as-built log, re-fold over-fragmented reference docs, refresh stale abstracts, bump this stamp) when the as-built log grows unwieldy or roughly monthly. The `garden-claude-docs` skill runs the checklist.

> **Stable-ID scheme (applied):** open/backlog items carry `CS-###` ids in the **Open backlog** table below (assigned once, never renumbered/reused). The as-built + completed-rounds sections are history (un-id'd).


> **SESSION NOTE (docs-only round, no `src/` changes).** A long design/documentation
> session produced: `docs/src/AI/Specs/model_formats.md` (format inventory + capability
> matrix, INACTIVE/WIP) and three user-doc pages under `docs/src/Misc/` —
> `intro-model-structure.md` (17 sections: the model taxonomy, STEP graph model,
> BOM-vs-motion, the Part/Assembly/Component/Body vocabulary, identity, standards,
> a workflow-analysis holding pen, an executive-narrative spec),
> `legacy-cellsmith-model-format.md` (the as-built cache format + the identity and
> container analyses), and `ai-metaanalysis.md` (how AI is used in this repo).
> **CS-024 … CS-039 below capture the decisions and open items from that session.**
> No `src/` was modified, so `Reference/*.md` is unchanged and still current.

---

## Open backlog (tracked)

Stable `CS-###` ids for open/actionable work — assigned once, **never renumbered or reused**. Priority / state / owner are separate fields, so reprioritizing never changes an id. The **as-built** and **completed-rounds** sections below are history (un-id'd); the "detail" column points into them.

- **next-id:** `CS-162`
- **State:** open · in-progress · blocked · live-test-pending · done · deferred
- **Priority:** P0 (do now) · P1 · P2 · P3 (someday)
- **Owner:** the agent/person on it, or `—` (unclaimed)

| ID | Title | State | Pri | Owner | Was / detail |
|----|-------|-------|-----|-------|--------------|
| CS-001 | STEP rebuild path → reconstruct a filtered ASSEMBLY doc (replace the flat-doc stopgap) | open | P2 | — | TODO #1 |
| CS-002 | Multi-select export (decide combine-vs-individual first) | open | P3 | — | #2 |
| CS-003 | Config↔model reconciliation across STEP revisions (fuzzy match + **change/delta highlighting**) — surface what changed between two deliveries (added / removed / moved / restructured / re-split) so a model update targets only the deltas. **Load-bearing, not cosmetic:** CellSmith is deterministic, not parametric, so an unnoticed change re-applies the old config silently and wrongly (no design intent to carry it). Rationale + the parametric-vs-deterministic framing: `docs/src/AI/Scratch/intro-model-structure.md` §3 | open | P2 | — | #3 |
| CS-004 | Revert the temporary Root node (`SHOW_IMPLIED_ROOT` → False) | open | P3 | — | #4 |
| CS-005 | Rigging: telemetry target-pose authoring + master Isaac stage + world-grounded base | blocked | P2 | — | #5 (awaits user spec) |
| CS-006 | Per-face colors in OBJ export | open | P3 | — | #6 |
| CS-007 | Alpha / transparency everywhere (color model → RGBA; OmniPBR MDL in USD; `d`/`Tr` in OBJ) | open | P1 | — | #7 / NEXT BIG TODO |
| CS-008 | Packaging follow-ups (frozen-GUI live-test; GitHub Actions CI/release) | open | P2 | — | #8 |
| CS-009 | Multiprocess tessellation (subprocess pool) | open | P3 | — | #9 (low) |
| CS-010 | Joint / mate inference (concentric cylinders → revolute; coplanar → hinge; suggest) | open | P2 | — | F10 |
| CS-011 | Unbend / Pose command scaffold (per-link axis + frames) | open | P2 | — | F11 |
| CS-012 | Unbend into orthogonal / home pose | open | P2 | — | SF/CGB short-term |
| CS-013 | Per-face color override (individual faces / face sets) | open | P2 | — | SF/CGB long-term; alpha-adjacent |
| CS-014 | Select Similar / Select By (color / kind / radius / size / prototype) | open | P3 | — | F2 |
| CS-015 | Loop / tangent-chain / boundary selection | open | P3 | — | F7 |
| CS-016 | Marquee + paint-drag + grow/shrink/invert | open | P3 | — | F8 |
| CS-017 | Symmetry / mid-plane / best-fit constructions | open | P3 | — | F9 |
| CS-018 | Constraint relations → auto-derived frame | open | P3 | — | F12 |
| CS-019 | Saved selection sets | open | P3 | — | F13 |
| CS-020 | SF/CGB selection roadmap (A3 fit-command polish, B/C/D/E tiers) | open | P3 | — | round -21 |
| CS-021 | USER live-GL verification of the uncommitted build (SF/CGB, mesh import, Component Editor, joints, composed export) | live-test-pending | P1 | user | recent rounds below |
| CS-022 | Promote `scratchpad/` probes → a committed `tests/` suite; split CI-runnable (GitHub Actions) vs GUI/GL-only, wire the runnable into CI/CD, and define a handling strategy for the rest (docs cite ~15 `scratchpad/*.py` as verification but they're gitignored) | open | P2 | — | scratchpad (item 8); relates CS-008 |

| CS-023 | **Terminology harmonization with the model taxonomy** (raised by `docs/src/AI/Scratch/intro-model-structure.md`): (a) prefer STEP's **product** over **prototype** when discussing STEP data — "prototype" is USD's word (`GetPrototype`, verified) and the mismatch confuses; (b) `Component.prototype` holds a NAME, deliberately, because one real component is often exported as several products sharing a name (posed-variant re-exports) — that concept ("the real-world thing this stands for, spanning several products") is genuinely unnamed and needs a name, not a find-and-replace; (c) **redefine "Asset" in those settled terms** — today it's a name-keyed product group, neither a product nor an occurrence nor a link; (d) decide whether **bodies deserve first-class tree visibility**, since links are body-level groupings and USD exports one mesh per body | open | P2 | — | intro-model-structure.md §11 (vocabulary), §12.4, §12.5 |

| CS-024 | **Identity redesign (Cluster 2 = fingerprint-first)** — the decided path for the successor format. Order: (1) move per-node placements from ABSOLUTE WORLD to PARENT-RELATIVE (the one invasive change, sequence it first); (2) specify a versioned tolerance-aware FINGERPRINT (volume, area, sorted bbox, face/edge/vertex counts, centroid in the node's own frame, optional inertia, child-fingerprint set for assemblies) — NOT a cryptographic hash, which reports spurious change on re-export; (3) make identity scopes structural (ids are parse-local and must never key user intent); (4) traceability/provenance DROPPED from the format (moved to the CI/CD discussion); (5) delta baking DEFERRED — it falls out of 1–3. GUIDs explicitly rejected: a fresh parse has no GUIDs, so they need fingerprints anyway | open | P1 | — | `docs/src/AI/Scratch/legacy-cellsmith-model-format.md` → "The Identity Problem"; blocks CS-003, per-body/per-face color, incremental bake, asset substitution |
| CS-025 | **Geometry layout + container redesign** — one decision, not two. Measured (5k components, 99 MB raw): current compressed npz is the slowest realistic option (~25× write, ~26× read vs concatenated); a single-file container is NOT the problem, **compression is** (npz *is* a zip); SQLite scores best on every axis incl. best partial read (1.1 ms); float32/int32 is free. Two surviving candidates: **SQLite blobs** or **concatenated blob + offset index + patch layer**. Non-optional either way: don't compress the working cache, store float32/int32 display geometry, store in the shape the renderer consumes. **Re-benchmark on REAL test files (incl. the ~20k-component model) before committing** — cold open, warm open, single-component read AND write, whole-model write, size | open | P2 | — | same page → "Geometry Layout and Container" |
| CS-026 | **Color model: RGBA + multi-level overrides.** Add alpha (RGBA from the start — widening stored RGB later means a schema bump + migration of every cache). Overrides must address **face / body / part / assembly / instance / global rule**. Precedence = ONE principle ("most specific wins") over TWO hierarchies: granularity (face>body>part>assembly) and tree depth (child>parent); **instance beats definition** as an orthogonal third axis. Export collapses DOWN to the finest granularity the target supports (per-body → per-face is lossless in USD/OBJ/PLY/glTF; STL loses it — warn). **Blocked on CS-024** (per-face/per-body identity) | open | P1 | — | same page → "Color: Where Overrides Can Be Set" |
| CS-027 | **Edit history as a general mechanism.** Keep + expand the ordered replayable op sequence beyond body editing — candidates: Component Definition editing, **restructuring (highest value)**, origins/transforms, joint authoring, asset marking. Unifying idea: if every user action is an entry in an ordered log keyed to stable identities, "re-apply my work to a new delivery" becomes ONE mechanism instead of a per-feature special case. **Depends on CS-024**; pair with a **change-visibility view + repair UI** for unresolved entries (refuse to apply rather than guess) — that repair UI is what makes determinism defensible | open | P1 | — | legacy-model-format page → provenance/edit-history callouts |
| CS-028 | **Terminology + taxonomy harmonization (supersedes/absorbs CS-023 scope).** Adopt the CellSmith vocabulary: Body (no independent identity) / Part (collection of bodies, moves as one unit) / Assembly (collection of components, children may move) / Component (the ABSTRACTION = Part ∪ Assembly; identity IS the part's/assembly's). Suffix **Definition** vs **Instance** wherever ambiguous. Prefer STEP's *product* over USD's *prototype* when discussing STEP. Drop "leaf" as a synonym for Part (position-in-tree only); "folder" → **group node**. Direction of travel: a **Component Definition Tree** + **Component Instance Tree**; trees have **nodes**, not rows. Four unresolved tensions logged (link sits on the Part/Assembly boundary; giving bodies identity may make them components; the vocabulary is B-rep-shaped and the mesh path only approximates it; two trees imply two config keying schemes) | open | P1 | — | `docs/src/AI/Scratch/intro-model-structure.md` §11, §12, §16.12 |
| CS-029 | **Robot orientation convention: X-forward, Y-left, Z-up** (ROS REP-103; nothing in USD declares a forward axis, so nothing catches a violation). Existing assets authored +Y-forward need re-orienting. Make forward an explicit authoring/verification step in rigging; document as a user-facing convention. **Units RESOLVED (triple-verified 2026-07-30, see CS-041)** — degrees is a USD-wide serialization convention, radians is the ecosystem; store SI, confine degrees to the USD writer. Name fields `_deg`/`_rad` so mismatches are visible | open | P1 | — | intro-model-structure §13.5, §16.15.1 |
| CS-030 | **Material passthrough + physics materials (plan now, implement post-Oct-2026).** Chain CAD → STEP → XCAF → USD is technically COMPLETE (probe-verified: OCC has a material tool with `GetDensityForShape` + reader/writer material modes; USD has `UsdPhysics.MaterialAPI` density/friction/restitution and `MassAPI` mass/inertia, separate from `UsdShade`). Correct level: **body** (conceptually) + **asset** (pragmatically). USD separates material DEFINITION (a prim) from REFERENCE (a binding relationship), supports per-face binding via `GeomSubset` in the `materialBind` family, separate visual/physics **purposes**, and **binding strength** for precedence. **The digital-shadow scope expires 2026-10-01**; after that gear toward simulation. Until then: don't foreclose it — RGBA, per-body property bag, body-level identity, an export path that can emit a bound material. Cheap experiment: export a multi-material part and see what STEP actually carries | open | P2 | — | intro-model-structure §8.11, §16.13 |
| CS-031 | **Textures — research item.** Can CellSmith define them at all (needs UVs, which B-rep tessellation doesn't currently produce)? Which outputs receive them (USD `UsdShade`, OBJ `map_Kd`, glTF PBR; not STL)? Does Isaac actually use them — note the sibling project found a full texture material "brittle in Isaac's renderer" and baked per-vertex color instead. Assignment level likely body/face-group (same identity prerequisite as per-face color). **Speculative follow-on:** AI-generated textures, motivated by LICENSING (own your textures) rather than novelty; strictly gated on assign+export working first | open | P3 | — | intro-model-structure §8.11 "Textures" |
| CS-032 | **Analytic vs numeric kinematics — NOT a fork in the model, a fork in the consumer.** Both need the same DECLARED structure (links/joints/axes/origins/limits). Isaac does NOT infer kinematic structure from geometry — it reads declared `UsdPhysics` joints or a URDF import; density/geometry only give it mass+inertia. Analytic consumers (MTConnect viewer, three.js, digital shadow) need the structure and nothing else; numeric consumers additionally need mass/inertia/collision/friction. So: author the structure now, leave slots for dynamics. **Both former ❓ now RESOLVED (2026-07-30):** Isaac CAN pose with physics fully off — `isaacsim.robot.schema` (Apache-2.0) ships a pure-Python `KinematicChain` with `compute_fk`, `compute_fk_and_jacobian`, and `teleport` (docstring: *use when simulation is stopped*), all verified importable/runnable headless; and its URDF importer DOES convert radians→degrees (`math.degrees` in `urdf_usd_converter/_impl/link.py`). See CS-041/043/045/046 | open | P2 | — | intro-model-structure §8.12 |
| CS-033 | **Asset library topology: project / local / remote.** Build in order — **start local + project, defer remote** — because the hard part is the DATA FORMAT not the transport, and a folder lets it iterate freely where a server schema does not. Design so remote is additive: self-contained assets (one dir/archive carrying geometry+rig+metadata, interpretable with no DB), stable asset identity independent of path, resolution order project>local>remote, a version/fingerprint per asset. Remote backing is open: dedicated server (web-sim's model) vs PDM (Vault-viewable analogy) vs git (LFS for bytes) — a hybrid is plausible. Note web-sim is **remote-only by construction** (Postgres+MinIO+Docker), which is wrong as the only option for an offline desktop tool | open | P2 | — | intro-model-structure §16.16.8 |
| CS-034 | **web-sim harmonization + grafting analysis.** Two projects built in parallel/semi-isolation for the same larger project; already merging ad-hoc (web-sim reaching for CellSmith's rigging; CellSmith wanting web-sim capability), with CellSmith possibly the "end product". Confirmed overlaps: USD authoring, trimesh, an OpenCASCADE CAD path (`cascadio` vs pythonocc — DUPLICATION), a face-indexed mesh rigger in `blender-renderoff` (DUPLICATION + opportunity), MTConnect, Isaac as target. web-sim already has: ontology-keyed asset catalog + Claude-vision classifier + match-vs-reconstruct, an MTConnect `Devices.xml` generator, an Isaac WebRTC viewport. **Proposed split:** capture/classification → web-sim; **structure/splitting/rigging/joints → CellSmith**; asset library → ONE of them; MTConnect device model → wherever joints are defined. **Q1–Q5 + Q7 EXECUTED 2026-07-30** (see CS-049 for the conclusions); **Q6 still BLOCKED — needs `blender-renderoff` repo access** | open | P2 | — | intro-model-structure §16.16 (esp. §16.16.9 queue) |
| CS-035 | **AI-workflow improvements for this repo** (from the meta-analysis). Ranked: (1) **promote `scratchpad/` probes to a committed `tests/` suite**, split CI-runnable vs GL-only, and give agents one "did I break anything" command — THE biggest gap, since without a check "looks done" is the only signal (= CS-022, elevate); (2) doc-map pointer + an **authority rule** (reference wins on facts, user doc wins on framing); (3) define 2–4 subagents (`occ-prober`, `code-reviewer`, `doc-auditor`, `format-explorer`) — `.claude/agents/` is empty; (4) a **second mkdocs site whose `docs_dir` points at `docs/src/AI/`** for rendered internal reading WITHOUT moving specs; (5) a compaction directive naming what must survive; (6) a `src/`-edit hook reminding which `Reference/*.md` to update; (7) spec-conformance review as a closing step. **Decision: do NOT move `Specs/` into `docs/`** — the disconnection risk is a LOADING problem (agents don't read `docs/`), not a location problem | open | P2 | — | `docs/src/AI/Scratch/ai-metaanalysis.md` |
| CS-036 | **Scale-to-reference tool.** Pick two points, state the real distance, derive a uniform scale factor. Motivated by unscaled reconstruction imports (a generative model cannot discern scale) but applies to **any** unscaled mesh import. The Selection Filter + Measure machinery for picking points and computing distances already exists, so this is small | open | P3 | — | intro-model-structure §16.16.5 |
| CS-037 | **`Interface_Static.SetCVal("write.step.schema", "AP214")` is REJECTED** (probe-verified: returns False; plain `"AP214"` is not a valid value). Output is AP214IS only because that is OCC's default, so the code's stated intent isn't enforced and would break silently if a future OCCT changed the default. Use `"AP214IS"` and check the return. Accepted values: AP203, AP214CD, AP214DIS, AP214IS, AP242DIS | open | P3 | — | `docs/src/AI/Specs/model_formats.md` → Actionable Now #3 |
| CS-038 | **`.3mf` / `.dae` are advertised but broken.** Both are in `io_mesh.formats.TRIMESH_EXTENSIONS` and appear in the Open dialog, but loading raises in `CellSmithEnv`: trimesh's 3MF path needs `networkx`, its COLLADA path needs `pycollada`, neither is in `packaging/environment.yml` (probe-verified: both registered as `ExceptionWrapper`, excluded from `trimesh.available_formats()`; live loaders are obj/stl/stl_ascii/ply/off/gltf/glb/xyz). Either add the two pure-Python deps or drop the extensions. Live user-facing failure | open | P2 | — | `docs/src/AI/Specs/model_formats.md` → Known Gaps |
| CS-039 | **USD export: set `subdivisionScheme = "none"`.** The USD schema default is `catmullClark`; our meshes are tessellations, never subdivision cages, so `none` is simply what we mean. Removes a latent smoothing risk without waiting on Isaac refinement research. Also flagged: a `.usdz` export target raises a raw pxr `ErrorException` (`Stage.CreateNew` refuses `.usdz`, probe-verified) — guard it with a clear message | open | P3 | — | `docs/src/AI/Specs/model_formats.md` → Actionable Now #2, #4 |
| CS-040 | **Doc-flush automation is BUILT** (this repo's `.claude/` infra, uncommitted). Three pieces: a `SessionStart` hook stamping `.claude/.session-flush-marker`; a `PreCompact` hook → `.claude/hooks/precompact-gate.sh` that **BLOCKS a manual `/compact`** when no file under `CLAUDE.md`/`docs/src/AI` is newer than the marker, and **only warns on an automatic compaction** (blocking auto-compact could wedge an out-of-context session); and a new **`/precompact` skill** (`.claude/skills/precompact/SKILL.md`) holding the flush checklist. Single-use bypass: `touch .claude/.skip-flush-gate`. All four gate paths (manual-block / auto-warn / bypass-consumed / allow) tested + JSON validated. Marker files gitignored. **Root cause it addresses:** the `Stop` hook watched `src/` mtimes, so it could never catch a docs-or-design-only session where a dozen decisions existed only in chat — which is exactly what happened over 2026-07-29/30 | done | P1 | — | `.claude/skills/precompact/SKILL.md`; hook capability confirmed at https://code.claude.com/docs/en/hooks (PreCompact can block + inject) |
| CS-041 | **USD angular units: DEGREES — triple-verified, and the ecosystem line is now settled.** (1) Normative: the OpenUSD physics schema *"adopts degrees as the standard angular unit"*; (2) probe of `usd-core` 26.5 — the ONLY unit metadata USD exposes is `metersPerUnit` + `kilogramsPerUnit`, there is **no angular knob anywhere**, which is why a convention had to be fixed; (3) NVIDIA's own shipped UR10e authors `physics:lowerLimit = -360` / elbow `-180` under `metersPerUnit = 1`, matching the real robot's degree ranges. **Reframe:** degrees is not a physics quirk but **USD-wide** — probe-verified that `xformOp:rotateZ = 90` rotates (1,0,0)→(0,1,0), and `PointInstancer.angularVelocities` is degrees/sec. **The line:** ROS/URDF/SDF/MJCF = radians; Isaac's **Python API** = radians; USD **file bytes** = degrees; UI = degrees. Isaac itself converts on write (`set_joint_attributes(π/2)` → `targetPosition = 90`), so degrees is a **serialization detail** — align with the ecosystem, confine degrees to the writer. **Subtler trap:** angular drive `stiffness` is mass·dist²/**degree**/s², so gains convert by the RECIPROCAL rule (`1/rad2deg(1/k)` in Isaac's own code) — converting limits but not gains looks right at rest and is wrong when driven | open | P1 | — | intro-model-structure §13.5; supersedes the units half of CS-029 |
| CS-042 | **`JointDef.lower`/`.upper` are POLYMORPHIC IN UNIT** — the same field means **degrees** when `joint_type == "revolute"` and **millimeters** when `"prismatic"`. Only the docstring says so. A latent 57× (or 1000×) error for the first consumer that reads the field without reading the comment: a URDF exporter, a soft-sensing estimator, a limit validator. Cheap + safe fix: put the unit in the NAME or carry an explicit unit tag (the repo already does this well — `z_rotation_deg`, `angular_deg` — the joint fields are the exception). Do NOT move the model to SI yet: with a single consumer that already wants degrees, converting is pure overhead. Revisit when a second consumer appears | open | P2 | — | `src/model/geometry_edits.py` `JointDef`; intro-model-structure §13.5 |
| CS-043 | **A setpoint-driven shadow RUNS THE SOLVER — so "a digital shadow needs no mass/inertia" is FALSE as currently implemented.** Shadows are driven by drive setpoints, not teleport; a drive is a PD controller inside the physics solve (`F = k(q_target − q) + c(q̇_target − q̇)`), so the displayed pose is the solver's *response* to telemetry, and tracking fidelity depends on stiffness, damping, `maxForce`, and the mass/inertia of everything downstream. (The repo's own damping 10000→1000 tuning is the fingerprint of this.) Three genuinely different products: **(a) switch to `teleport`** — pose equals telemetry exactly, no gains, no tracking error, loses force info; **(b) keep setpoints + author mass properly** — tracking error becomes physically meaningful, enabling CS-044; **(c) keep setpoints, stiff gains, treat lag as noise** — today's default; fine visually, forces untrustworthy. **Decide before simulation enters scope (post-2026-10-01)** | **deferred** | P1 | — | intro-model-structure §8.12.1; **user deferred 2026-07-30 until after the 2026-10-01 digital-shadow breakpoint** |
| CS-044 | **Soft sensing (virtual torque sensors) is the strongest argument for the material/mass work** — stronger than render fidelity, which was CS-030/031's original motivation. With the chain + mass properties, joint torques can be estimated from measured positions via inverse dynamics (recursive Newton–Euler), with NO torque sensors on the machine. Buys: payload estimation, **condition monitoring** (torque drift over weeks for the same commanded motion — highest value, needs zero new hardware), collision/jam detection, energy accounting. Honest limits: CAD density gives geometric mass well but not rotor inertia / gearbox ratio+efficiency / belt compliance, so **absolutes are biased but TRENDS are valid** — aim at trending first; friction dominates at low speed and drifts with temperature; double numerical differentiation of position telemetry needs real filtering. Note `compute_fk_and_jacobian` already covers the static case (τ = Jᵀ F) = gravity/payload load without full inverse dynamics. **Design consequence: do not foreclose mass — and body-level identity is the prerequisite that is expensive to retrofit** | open | P2 | — | intro-model-structure §8.12.2; depends on CS-024 (body identity), pairs with CS-030 |
| CS-045 | **TOOLING (verified): `C:\Applications\isaac-sim\python.bat` runs plain Python scripts WITHOUT launching Isaac Sim** — it is a thin wrapper (`setup_python_env.bat`, sets `CARB_APP_PATH`/`ISAAC_PATH`/`EXP_PATH`, execs `kit/python/kit.exe`, a renamed CPython). No app, no window, no GPU context. This materially widens what can be verified headlessly in a dev env with no GL. Gotchas found by probe: interpreter is **Python 3.12.13** (same minor as `CellSmithEnv`); **`pxr` is NOT on the default path** — it ships in `extscache/omni.usd.libs-*`; importing it needs `os.add_dll_directory` for `kit/` + the ext dir or it fails `DLL load failed while importing _tf`; the robot-schema import root is `exts/isaacsim.robot.schema` (the **parent** of `usd/`, a namespace package). **USD version skew: Isaac ships USD 0.25.11, `CellSmithEnv` has usd-core 0.26.5** — we write with the newer library and Isaac reads with the older | open | P1 | — | intro-model-structure §8.12.3; probes in scratchpad (`isaac_probe1.py`, `isaac_fk_probe.py`) |
| CS-046 | **Isaac ships an Apache-2.0 robot schema + analytic kinematics we could target directly.** `isaacsim.robot.schema` contains `RobotSchema.usda` (`IsaacRobotAPI`, `IsaacLinkAPI`, `IsaacJointAPI`, `IsaacSiteAPI`, `IsaacNamedPose`, `IsaacSurfaceGripper`) plus pure-Python `kinematic_chain.py` (`compute_fk`, `compute_fk_and_jacobian`, `teleport`, `set_joint_attributes`, `read_joint_states`) and `ik_solver.py`/`lm_ik.py` (Levenberg–Marquardt IK). Notable schema fields that overlap our own open questions: `IsaacNamedPose` (a pose library — home positions), `IsaacSiteAPI` (named frames with a `forwardAxis`, cf. CS-029), and `isaac:source`/`version`/`changelog`/`license` (asset provenance, cf. CS-033). **Finding to act on:** a bare `UsdPhysics`-only stage gave `KinematicChain` **ZERO joints** (Jacobian `(6,0)`) — discovery goes through the Isaac schema relationships, with a secondary path off the **articulation root**. CellSmith DOES author `ArticulationRootAPI`, so the fallback may cover us, but this is **NOT yet verified against a real CellSmith export** (the probe used a minimal hand-built stage). **Cheap high-value next step: run a genuine CellSmith export through `KinematicChain`.** If it needs the schema APIs, they are additive metadata, not a restructuring | **deferred** | P1 | — | intro-model-structure §8.12.3; **user deferred 2026-07-30 until after the 2026-10-01 breakpoint** |
| CS-047 | **Joints and telemetry channels are NOT 1:1 — there is a mapping layer, and it is not geometry.** Every mismatch occurs in real machines: one channel → many joints (telescoping mast, proportional stages); many channels → one pose (closed-loop cylinder); a channel that is not an angle (turret **station index** → needs a discrete-state→value map that lives nowhere in the geometry); a joint with no channel (passive gas strut — **unobservable**, freeze or infer); a channel with no useful joint (spindle RPM — correctly **discarded**, it aliases); one definition with divergent joints (mirrored gripper fingers — the joint belongs to the INSTANCE, never the definition). Two consequences: **(a)** argues for a **channel-binding / MTConnect metadata editor** hung off the joints, since CellSmith is where joints get named; **(b)** sets a floor — a model whose joints cannot be **named and addressed stably** cannot be bound to telemetry at all, making stable joint identity a hard requirement, not a nicety | open | P1 | — | intro-model-structure §11.3; depends on CS-024, feeds CS-034 |
| CS-048 | **Closed kinematic loops: URDF CANNOT express them, `UsdPhysics` CAN.** A cylinder pinned at both ends (excavator boom, and most hydraulic/pneumatic actuation) forms a loop; URDF is strictly a tree, so published excavator URDFs cut the loop with a mimic relation or drop the cylinder to visual-only. `UsdPhysics` joints are relationships between two bodies with no acyclicity requirement. **So a model CellSmith can legitimately author may be inexpressible in URDF** → argues for **USD as the primary target and URDF as a lossy convenience export**, and for stating this as a known limitation rather than letting a user discover it as a floating cylinder. ❓ Unverified: whether PhysX's articulation reducer takes a loop directly or needs it as an extra constraint on a spanning tree | open | P2 | — | intro-model-structure §11.3 |
| CS-049 | **web-sim harmonization: Q1–Q5 + Q7 conclusions.** **(Q1)** 11-component pipeline mapped with per-seam contracts; the decisive property for reconstruction is not visual quality but **whether the output can be trusted as a dimension** → **generative reconstruction is for visual CONTEXT (guarding, enclosures, surroundings) and must NEVER be dimension-bearing (tooling, fixtures, machine envelope)** — which lands well, since dimension-bearing objects are the ones that have CAD. **(Q2)** Apache-2.0 filter: TRELLIS **MIT** ✔ (submodules `diffoctreerast`/Flexicubes ❓ need checking), trimesh/manifold3d/usd-core/VTK ✔, OCCT LGPL + Qt LGPL ✔ *with dynamic linking*, COLMAP BSD ✔; **Blender is GPL-2+ → NOT compatible if linked** — and it sits exactly where web-sim depends on it (`usd_export.build_usda`), which is the one thing we already do natively with Apache-2.0 `usd-core`, so **drop Blender rather than negotiate it**. Isaac Sim itself is proprietary but `isaacsim.robot.schema` is Apache-2.0 (CS-046). **(Q3)** The approaches are complementary: scan-for-scale + generate-for-completion is the highest-value pairing; CAD-for-machines + reconstruction-for-the-room is the pragmatic default; **parametric proxies for the boxy long tail are under-rated and cheap**; retrieval-before-generation beats reconstructing. **Do NOT build automatic sensor fusion** — the useful version needs one scalar + one rigid transform, which a human supplies in seconds (CS-036). **(Q4)** Only **3 of 11** components can't ship in a desktop app: reconstruction (**Linux-only, CUDA, ≥16 GB VRAM**), hosted annotation, streaming — and all three are someone else's service anyway → **CellSmith stays a desktop app with an OPTIONAL reconstruction backend** over a file-in/file-out HTTP seam, in three shapes (none / local container / remote endpoint). Rule: **no existing feature may become backend-dependent.** **(Q5)** TRELLIS multi-image is real but **tuning-free and untrained** — a *quality knob, not a correctness fix*; it does NOT fix scale and has no multi-view-consistency objective. **(Q7)** 14 decisions/assumptions audited; the single most important **unvalidated** assumption in EITHER project is that **reconstruction is good enough on industrial subjects** (large, specular, dark grey, partly enclosed — near worst-case) — **test on a real machine photo before designing around it.** **Harmonization = 4 steps:** reconstruction becomes an optional ingest; CellSmith's structuring replaces web-sim's single-link rigger; the semantic layer moves OWL → **MTConnect device model** as an editor where joints are named; streaming/web client stay separate consumers of the USD | open | P2 | — | intro-model-structure §16.16.9; parent CS-034 |
| CS-050 | **Two external-access blockers, both with the user.** (1) **Q6 — what Blender is actually used for in web-sim: BLOCKED** on `blender-renderoff` repo access; evidence so far is only call sites (`pipeline.usd_export.build_usda`, `load_glb_mesh`, a socket/headless-spawn USD export). Resolving it would confirm CS-049's "drop Blender" recommendation. (2) **MTConnect normative angular units + enumerations: still ❓** — the model browser at https://model.mtconnect.org/ is JS-rendered and the spec PDFs yielded no text. Load-bearing because MTConnect is the telemetry alignment target (CS-047) | blocked | P2 | — | intro-model-structure §13.5, §16.16.9 |
| CS-051 | **Move `.claude/docs/` → `docs/src/AI/` and drop the symlink** (supersedes CS-035's "second mkdocs site" recommendation, and the interim `docs/src/AI` → `../../.claude/docs/` symlink). **Decisive reason: `git config core.symlinks` is `false` here**, so a committed symlink materializes as a TEXT FILE containing the target path on checkout — the docs silently vanish from the site. Secondary reason: relative links from the AI tree out to `docs/src/Misc/` escape `docs_dir` and cannot be rewritten by mkdocs, so they break in the browser (the problem that prompted this). **Nothing required the docs to live under `.claude/`** — the harness only special-cases `settings.json`/`skills/`/`hooks/`/`agents/`/`commands/`; `docs/` there is found *only* via the `CLAUDE.md` pointer. The real split is **executable vs prose**: machinery stays in `.claude/`, documents move with documents. Costs: (a) **one-way link rule** — AI docs may link to user docs, user docs must NEVER link into `AI/` (excluded from the public build), worth a `make` check; (b) ~15 cross-tree refs + every `.claude/docs/...` path in `CLAUDE.md`/`status.md`/skills/memory needs a scripted rewrite. Keep `AI/` excluded in the DEFAULT config (already true: `make` excludes, `make dev` opts in) — safe-by-default. **Revisit if** the harness ever gains auto-loading for a `.claude/docs/` path | **done** | P1 | — | ai-metaanalysis §2.4; **EXECUTED 2026-07-30, see CS-056** |
| CS-052 | **The verification loop IS possible — the blocking assumption in `CLAUDE.md` was WRONG.** That file claimed the VTK render path "can't run headlessly (no GPU/OpenGL context)", which is why an agent-facing visual loop was never attempted. Probe-verified in `CellSmithEnv` with `QT_QPA_PLATFORM=offscreen`: `QApplication` constructs (`platformName()=="offscreen"`); **`pyvista.Plotter(off_screen=True).screenshot()` produced a correctly shaded, depth-ordered, edge-rendered image** (visually confirmed, not just non-empty); `QWidget.grab()` captures widgets; `PySide6/opengl32sw.dll` (software GL) ships in the env. **Gotcha, diagnosed + fixed:** offscreen Qt reports **0 font families** → text renders as tofu; `QFontDatabase.addApplicationFont(r"C:\Windows\Fonts\segoeui.ttf")` fixes it (0→4 families, re-captured widget fully legible). `CLAUDE.md` corrected. ❓ Unconfirmed whether hardware or software GL was used. **Missing deps: `pytest`, `pytest-qt`, `imagehash` (Pillow + numpy ARE present, enough for a tolerance compare).** No `tests/` dir; **92 `scratchpad/` probes evaporate**. **Build order:** (1) `tests/` + pytest in `packaging/environment.yml`, move Tier-1 probes, `print()`→`assert`; (2) one "did I break anything" command; (3) ~30-line offscreen fixture (font + pinned camera/size); (4) tolerance image-compare writing `expected/actual/diff`; (5) goldens for orientation, color override, hide/suppress, joint viz, selection highlight; (6) `Stop` hook once a suite exists; (7) add `pytest-qt` for real click/key simulation. **Do NOT change stacks** — PySide6+VTK already supports a closed loop | open | **P0** | — | ai-metaanalysis §3.1; supersedes/absorbs CS-022 |
| CS-053 | **Two loops, not one — goldens guard, vision judges.** Golden-image compare answers *"did it change?"* (deterministic, CI, catches regressions, **happily locks in a bug forever**); agent vision review answers *"is it right?"* (judgment, non-deterministic, catches wrong-from-the-start, **cannot see a 2-pixel shift**). Neither substitutes for the other. Requirements for the golden half: pin window size + explicit `camera_position` + background + font + seeds; **compare with tolerance, never `==`** (GL differs across drivers and between software/hardware paths); emit the diff image as an artifact (that's what makes vision review possible); one assertion per view. Generate goldens in the same environment that checks them. Keep Tier-2 scenes small — software GL is slow, so never the 875 MB file. **CI targets:** Windows/local = `QT_QPA_PLATFORM=offscreen` (verified); Linux container = offscreen for widgets + `xvfb-run` with `LIBGL_ALWAYS_SOFTWARE=1` for GL (`pyvista.start_xvfb()` exists for this); Tier-3 (real driver, depth peeling, interaction latency) stays local-only and that is fine | open | P1 | — | ai-metaanalysis §3.1.3–3.1.5 |
| CS-054 | **Exploration is a first-class workflow stage, currently unnamed and therefore unmanaged.** This repo has TWO scratch spaces that are the same stage in different media, failing in OPPOSITE directions: **prose scratch** (`docs/src/Misc/`, committed → **ossifies**, becomes the de-facto reference — already happening, one page is 4.7k lines) and **code scratch** (`scratchpad/`, gitignored → **evaporates**, 92 probes lost). Both need a graduation step, in opposite directions. **Workflow (diagrammed):** reality → probes → scratch → *matures* → specs + user docs; specs → tests + code; code → reference docs; probes → **graduate into** tests; `status.md` tracks decisions continuously and never holds content. **Two edges currently missing: probe→test and spec→test** — the strongest form of the latter is *a spec names the test that proves it*, making "is this implemented?" runnable instead of a reading exercise. **Four rules:** name the stage (folder or frontmatter `status: exploratory`) so a scratch page can't become the reference by default; graduation is a real edit (split by Diátaxis quadrant), not a copy; extract decisions continuously (already automated via CS-040); give code scratch an expiry — promote the load-bearing probes, delete the rest, don't promote all 92 | open | P1 | — | ai-metaanalysis §3.7 |
| CS-055 | **Diátaxis adopted as the organizing principle — including for the agent docs.** Four quadrants (tutorial / how-to / reference / explanation) kept SEPARATE. Mapping reveals the agent docs already fit accidentally: `Reference/*.md`+`invariants`+`glossary` = **reference**; `decisions.md` (ADR) + `Specs/*.md` = **explanation**; **`skills/*/SKILL.md` = how-to** (a skill IS a how-to guide for an agent — so write them as procedures, and don't merge them into `Reference/`); **tutorial deliberately absent** (agents don't onboard); **`status.md` is NOT documentation** — it's a ledger, Diátaxis has no such quadrant, and forcing it in is how ledgers rot into changelog prose. **The repo `CLAUDE.md` mixes all four**, which is the cardinal Diátaxis error but correct for a hub — the rule that keeps it honest: **`CLAUDE.md` may contain pointers to any quadrant but prose from none.** **The real gap: the entire user-facing left column is missing** — `docs/src/` is three long *explanation* pages and nothing else (no tutorial, no how-to, no user reference), i.e. one quadrant pretending to be a manual. Also fixed this round: the **repo-vs-personal `CLAUDE.md` distinction** was blurred in the meta-analysis; now an explicit table (personal = how to talk to this user, travels by machine; repo = how to work on CellSmith, travels by git; test = *"would I want this on an unrelated Rust project?"*) | open | P2 | — | ai-metaanalysis §2.5, §1 |
| CS-056 | **DONE — the doc tree moved.** `.claude/docs/` → **`docs/src/AI/`** (user deleted the symlink first). Renames for the mkdocs nav: `reference/`→**`Reference/`**, `specs/`→**`Specs/`**, `README.md`→**`index.md`** (so it is the AI section's index page). The three big design pages moved `docs/src/Misc/` → **`docs/src/AI/Scratch/`**; `docs/src/Misc/index.md` left behind as a user-doc placeholder stub, and `Pipeline/` (nascent scaffolding, all `asdf` placeholders) was moved into `Scratch/` by the user, so `Misc/` is now the stub alone. Scripted rewrite of **15 files** (CLAUDE.md, all AI docs, both skills, the gate script, settings.json, 4 agent-memory files); **zero `.claude/docs` references remain**. `.claude/` now holds only machinery (`settings.json`, `skills/`, `hooks/`) — the executable-vs-prose split. **New rule, and it is load-bearing: AI docs may link OUT to user docs; user docs must NEVER link into `AI/`** (excluded from the public build → broken link). A `make` check is wanted; the naive `grep -rn '](.*AI/' docs/src --exclude-dir=AI` false-positives on inline code spans and needs refining | done | P1 | — | `docs/src/AI/index.md` |
| CS-057 | **DONE — test scaffold built and green.** New `tests/` (`conftest.py` + `test_hello.py`), root `pytest.ini`, and two Makefile targets: **`make test`** (everything) and **`make test-ci`** (`-m "not local_only"`, plus `LIBGL_ALWAYS_SOFTWARE=1`). Added `pytest>=8.0`, `pytest-qt>=4.4`, `pillow` to `packaging/environment.yml` and installed them. **Verified: 8 passed; `test-ci` → 7 passed, 1 deselected.** **Marker POLARITY is the design decision:** a test is **CI-eligible BY DEFAULT** and must opt out with `@pytest.mark.local_only`, so a forgotten marker fails loudly in CI rather than silently never running. Markers: `local_only` (needs display/GPU/interaction), `slow`, `gl` (offscreen GL — still CI-eligible). `conftest` provides the session `qapp` fixture (offscreen + **per-platform font registration** + pinned point size) and a stable `_artifacts/` dir for images. The hello-world GL test guards against the classic false pass with `arr.std() > 5.0` (a blank frame). **`scratchpad/`'s 92 probes NOT yet promoted** — deliberate, per user. NOTE: `make` is not on `PATH` in PowerShell here; run the targets from WSL or invoke pytest directly | done | **P0** | — | `tests/`, `pytest.ini`, `Makefile` |
| CS-058 | **The offscreen font problem is WINDOWS-ONLY** (probe-verified both OSes 2026-07-30, Debian WSL2). Windows offscreen = **0 font families** → tofu text; **Linux offscreen = 6** (DejaVu ×3, Monospace, Sans Serif, Serif) and needs **no fix at all**. Cause: on Linux the font DB comes from **fontconfig**, independent of the windowing system; on Windows it is supplied by the **platform plugin** (GDI/DirectWrite), which `offscreen` does not provide. So CI on Linux "just works" for fonts. **BUT the bigger consequence: widget golden images are PER-PLATFORM**, for TWO independent reasons — different font (Segoe UI vs DejaVu → different glyph advance widths → different layout) AND different Qt **style** (same stylesheet gave a flat button on Windows, a **gradient** one on Linux). A Windows-captured widget golden will never match a Linux CI render at any tolerance. Preference order: **(1) assert structure not pixels** (geometry/visibility/enabled/text via the API — most UI regressions are logic); (2) vendor a `.ttf` + force `app.setStyle("Fusion")` to remove both divergence sources; (3) per-platform golden sets (2× maintenance, last resort). The 3D viewport has its own version: software-GL vs hardware-GL differ, so viewport goldens must be generated in the env that checks them | open | P1 | — | ai-metaanalysis §3.1.1 |
| CS-059 | **Golden images and vision review are sequential PHASES, not competing options.** Golden = *"did it change?"*: needs a certified baseline, deterministic, ideal for CI, catches any regression, **blind to a baseline that was already wrong**, and its real failure mode is **false alarms** → teams blanket-approve diffs and it stops catching anything. Vision = *"is it correct?"*: no baseline, non-deterministic (bad CI gate), catches inverted axes / mirrored geometry / nonsense scale, **blind to small shifts**, failure mode is **false confidence**. **The rule: vision review WHILE BUILDING (no baseline exists, correctness is open), freeze a golden ONCE VERIFIED (correctness settled, regression is open).** Also a cheaper-first ladder that beats both in most cases: numeric assertion on the data (matrix/volume/bbox/counts) → structural assertion on the scene graph (actor count, visibility, color arrays) → sampled pixels → image statistics → full golden. **Test: if the assertion could be written as a number, write it as a number.** Reserve goldens for genuinely pictorial properties (depth ordering, edge rendering, glyph placement) | open | P1 | — | ai-metaanalysis §3.1.3, §3.1.6 |
| CS-060 | **Test-fixture specification written — 15 code-generated OCC fixtures + a proprietary-file anonymization pipeline.** Principle: **generate wherever possible** (a fixture is a ~20-line function, not a file someone authors in SolidWorks) and **each fixture isolates exactly ONE structural property**, because a fixture varying two things cannot say which broke. The set: single solid; two disjoint solids in one part (multi-body); 3-deep nested assembly; **instanced part ×3** (definition-vs-instance); unnamed components ("Solid1…"); per-face colors (also guards the preorder-traversal trap); no colors; mm-vs-m units; **fused two lumps** (the seam-loss case); deep transform chain (float error); tiny+huge together (deflection across scales); non-manifold shell; duplicate sibling names; revolute pair (joints + FK); wide-flat 1000 parts (scale without an 875 MB file). Each carries **expected values as data** (counts, volumes, bboxes) so assertions are exact. Mesh equivalents via trimesh incl. a single fused blob (the reconstruction case) and an unscaled mesh (CS-036). **For proprietary inbound files: characterize, don't copy.** A probe emits a *structural-statistics* anomaly report (counts, flags like unnamed/duplicate/non-manifold/non-orthonormal-transform, size and transform distributions, AP203/214/242 schema facts) — **no geometry, no strings** — which is safe to commit and usually enough to write a generator. Only if the anomaly needs real bytes: minimize + scrub, then a **MANDATORY human IP gate** (never automated); uncleared files go to a gitignored `tests/fixtures/private/` with `@pytest.mark.local_only`. **The anomaly report, not the file, is the durable artifact** — same principle as `status.md` outliving the conversation | open | P1 | — | ai-metaanalysis §3.1.7 (incl. the mermaid pipeline) |
| CS-061 | **⭐ ISAAC SIM IS NOW OPEN SOURCE — and CellSmith's use needs NO NVIDIA licence.** Researched 2026-07-30 against NVIDIA's own docs. **Source code = Apache 2.0** (`github.com/isaac-sim/IsaacSim`), free to use/modify/redistribute incl. commercially. **Additional NVIDIA-owned components** (Omniverse **Kit SDK**, 3D models, textures) are covered separately by the **NVIDIA Isaac Sim Additional Software and Materials License** and **may not be modified or redistributed** except as its terms permit. **Free, no extra licence:** internal R&D and development; running sims on your own machines; **selling simulation outputs** (videos, reports, datasets); and — decisively for us — **selling custom Python code and USD assets where the client runs their own Isaac Sim**. No per-user or team-size restriction. **NVIDIA AI Enterprise licence required ONLY to:** redistribute Isaac Sim (with Kit) inside your application, deliver it as a service to third parties, or do turn-key installs on a client's hardware. **Conclusion: CellSmith authors USD assets and does not redistribute Isaac → no licence needed.** Also relevant: `isaacsim.robot.schema` is Apache-2.0 (CS-046), so its FK/IK/`teleport` code is usable independently. Sources: https://docs.isaacsim.omniverse.nvidia.com/latest/common/license-faq.html · https://github.com/isaac-sim/IsaacSim · https://docs.isaacsim.omniverse.nvidia.com/latest/common/redistributable-ov-software.html | open | P1 | — | supersedes the "Isaac Sim = proprietary, not redistributable" line in CS-049 |
| CS-062 | **Blender's role clarified by the user — it edits/cleans the MESH that TRELLIS outputs**, nothing more (this partially answers the Q6 block without repo access). That makes the GPL problem trivially avoidable: **call the `blender` executable as a separate process** rather than importing `bpy`. Proposed pipeline step: **CellSmith exports the mesh → Blender loads/edits/cleans → CellSmith re-imports → continue down the CellSmith pipeline.** Process-boundary invocation of a GPL program is the standard way to stay licence-clean, and it also keeps Blender optional rather than a hard dependency. **Revised CS-049 conclusion:** Blender is no longer a *licence blocker*; it is an *optional external mesh-cleanup tool*. Still worth asking whether `trimesh`/`manifold3d` already cover the cleanup we need (they are bundled and Apache/MIT) — if so, skip Blender entirely | open | P2 | — | user statement 2026-07-30; ai-metaanalysis / intro §16.16 **not yet updated with this** |
| CS-063 | **NOT DONE this round — carried forward explicitly so it is not lost.** (a) **§11.3 → new §11.4:** move the "joints vs telemetry channels" material out of §11.3 into its own subsection *before* the existing §11.4, then broaden it across the **whole engineering-design / manufacturing / supply-chain network** and keep mining **format mismatch + incompatibility** insights. (b) **§16.16 edits:** the Blender clarification (CS-062); a **missing image-segmentation stage** in the Q1 pipeline (narrowing to one object — ❓ is that inside TRELLIS or a separate step? unresearched); §16.16.4 needs the **"reusable simulatable asset skeleton"** lens — CellSmith should produce the base a controller/behavior script attaches to for robots/CNC/AGV, behavior deliberately out of scope for now; §16.16.5 needs the **four deployment shapes** the user listed (button-downloads-deps with UI pre-built · docker backend that CellSmith points at · web-sim as a separate process exchanging files · web-sim as a separate process exposing an API). (c) **TRELLIS bottleneck deep dive NOT done** — the specific question: can it be loaded in-process like a HuggingFace GGUF, or does it genuinely need a container/remote service, and *precisely where* the bottleneck is (Linux-only? CUDA extension builds? the custom `diffoctreerast`/Flexicubes CUDA kernels? VRAM?). Prior evidence: its README says Linux-only, CUDA 11.8/12.2, ≥16 GB VRAM. (d) **"CellSmith in a container with a web UI"** — whether a Qt desktop app is still the right shell, and whether one container could hold everything. **Assume an NVIDIA GPU + CUDA is available** (user's stated premise) | open | P1 | — | intro-model-structure §11.3/§16.16; ai-metaanalysis §3.1.5 |
| CS-064 | **⭐ Isaac Sim redistribution: the user's memory was RIGHT — an enterprise licence is still required, and CS-061 needs this qualification.** What changed is the **source code** (now Apache-2.0); what did **not** change is the **redistributability of anything you can actually run**. The `NVIDIA Isaac Sim Additional Software and Materials License` (covering the Omniverse **Kit SDK**, models, textures — i.e. everything needed to make the Apache-2.0 source *run*) grants only "a limited, non-exclusive, revocable, non-transferable, and non-sublicensable … license to install and use copies of the Software in systems with NVIDIA GPUs"; **§2.2** forbids "Sell, rent, sublicense, transfer, distribute or otherwise make available to others … any portion of the Software"; **§2.4** forbids "Modify or create derivative works of the Software"; **§3** limits access to employees and contractors of your own entity. **Answering the custom-image question directly: BUILDING one is supported — NVIDIA ships the tooling (`./tools/docker/build_docker.sh --tag my-isaac-sim:v1.0`), the Dockerfiles repo is Apache-2.0, and adding your own layers is ordinary Docker. DISTRIBUTING the resulting image to third parties is NOT permitted** — the built image contains Kit SDK + assets, which §2.2 covers. Also note the "Redistributable Omniverse Software" page is NARROW: it lists only the **Connect SDK** and **Kit kernel/extensions for Configurator Runtimes on GDN** — Isaac Sim containers are not on it. **The workaround, and it is a standard pattern: ship the RECIPE, not the image** — publish a Dockerfile/compose file that the customer builds, so the customer pulls from NGC under their own acceptance of NVIDIA's terms. Still fine without any licence: internal use on your own GPUs (employees + contractors), selling sim outputs, and **selling USD assets + Python where the client runs their own Isaac** = CellSmith's model. ⚠ This is a reading of the licence text, **not legal advice** — get review before any distribution decision. Sources: https://docs.isaacsim.omniverse.nvidia.com/latest/common/license-isaac-sim-additional.html · https://docs.isaacsim.omniverse.nvidia.com/latest/common/license-faq.html · https://docs.isaacsim.omniverse.nvidia.com/latest/common/redistributable-ov-software.html · https://github.com/isaac-sim/IsaacSim · https://github.com/NVIDIA-Omniverse/IsaacSim-dockerfiles | open | P1 | — | **qualifies CS-061** |
| CS-065 | **DONE — `test.bat` + `test-ci.bat` created and verified**, mirroring `make test` / `make test-ci` so the suite runs on Windows without `make` on `PATH`. Both auto-locate `conda.exe` (PATH, then `%LOCALAPPDATA%`, `%USERPROFILE%`, `%ProgramData%` anaconda/miniconda), set `QT_QPA_PLATFORM=offscreen` (and `LIBGL_ALWAYS_SOFTWARE=1` for the CI variant), pass extra pytest args through, and propagate the exit code. **Verified: `test.bat` → 8 passed; `test-ci.bat` → 7 passed, 1 deselected.** Both platforms are now first-class for testing | done | P1 | — | `test.bat`, `test-ci.bat`, `Makefile` |
| CS-066 | **DONE — gardening SCOPE nailed down** (the ambiguity the doc move created, since AI docs now sit beside user docs). Written into `.claude/skills/garden-claude-docs/SKILL.md` as a permissions table: **edit freely** = `status.md`, `Reference/*.md`, `AI/index.md`, `CLAUDE.md`; **light touch only** = `Specs/*.md` (refresh abstracts, fix cross-refs and formatting — a spec is authored *design intent*, so propose rather than rewrite); **DO NOT EDIT, report only** = **`AI/Scratch/**`** (condensing exploration destroys the half-formed material it exists to hold — gardening may *observe* "this page is 4.7k lines, §11 looks ready to graduate" and log it) and **`docs/src/` outside `AI/`** (user docs: different audience, different genre). Default when unsure: **report, don't edit.** **No separate user-docs gardening skill yet** — the user docs are a stub, so a skill for them would be speculative; revisit when real tutorials/how-tos exist, since their rules are Diátaxis-shaped and unrelated to tracking `src/`. The **one-way link rule is now an enforced gardening step**, with a grep that skips both the `AI/` tree and inline code spans (the naive version false-positived on documented examples) | done | P1 | — | `.claude/skills/garden-claude-docs/SKILL.md` scope section |
| CS-067 | **The Windows font issue is NOT a font-choice problem — picking a different font cannot fix it.** `QFontDatabase.families()` returns **0** under `QT_QPA_PLATFORM=offscreen` on Windows: there is no font database at all, so *no* font renders, whichever you name. The only fix is to **register** a font file (`addApplicationFont`), which works and is what `tests/conftest.py` does. (Linux needs nothing — fontconfig is independent of the windowing system; 6 families by default.) **The productive version of the question turned out to be different and better:** since Windows requires an explicit registration anyway, **vendor ONE font in the repo and register it on BOTH platforms** — that removes font divergence as a variable instead of working around it. Done: `tests/fixtures/fonts/DejaVuSans.ttf` (759 KB) is now a repo asset. ❓ Untested: whether `QT_QPA_FONTDIR` or the `minimal` platform plugin would populate the DB on Windows | open | P2 | — | ai-metaanalysis §3.1.1 |
| CS-068 | **Visual acceptance criteria — test images embedded in the spec (design settled).** The manufacturing-inspection analogy is the right frame: a spec states the criterion **in pictures**, the test enforces it. **One mkdocs constraint forces the layout:** files must live inside `docs_dir`, so a spec cannot reference `../../tests/goldens/*.png` (the same escape-the-root problem that forced the `AI/` move). Therefore **goldens live in the docs tree and tests reference them** — dependency direction is **tests → docs**: `docs/src/AI/Specs/_images/<spec>/{golden-*,counter-*,actual-*,diff-*}.png`. Three image classes, only one of which is a test input: **golden** (committed, compared — the acceptance criterion); **counter-example** (committed, **never compared** — authored "here is what wrong looks like", e.g. the same scene rendered Y-forward; this is what elevates the directory from a baseline to a *specification*, and it gives a re-baseline reviewer something to compare against); **actual/diff** (gitignored, written only on failure — the red half of red-green). `.gitignore` updated accordingly (`_images/**/actual-*.png`, `diff-*.png`, `tests/_artifacts/`, `tests/fixtures/private/`). **Cost to respect: binary blobs in git** — keep goldens small (200×150, not 1920×1080), few (obey the CS-059 ladder: if it can be a number, write a number), and never commit actual/diff | open | P1 | — | ai-metaanalysis §3.1.8 |
| CS-069 | **MEASURED: one widget golden CAN serve both platforms — with a tolerance, not exact match.** Rendered identical widget code offscreen on Windows and Debian WSL2 with three things pinned: vendored `DejaVuSans.ttf` registered on both, `app.setStyle("Fusion")`, fixed widget size. Result: **layout, text position and widget arrangement IDENTICAL**; not byte-identical — **mean abs diff 10.4/255, 11.1% of pixels differing by >8**, and the difference is confined to **glyph edges and the button's gradient band** (FreeType vs Qt's Windows font rasterizer; slightly different gradient interpolation). **So pinning font+style eliminated the *layout* divergence, which was the real problem;** what remains is sub-pixel intensity, not position. Consequences: an exact-match compare will never pass cross-platform; a mean-abs-diff threshold works but 10.4/255 is high enough that a loose tolerance could mask a real change — **prefer a metric insensitive to edge intensity but sensitive to position** (compare blurred/downsampled, or bound the *fraction* of pixels over a per-pixel threshold). ❓ **Worth trying: `QFont::PreferNoAntialias`** — binary glyphs might make the platforms byte-identical and remove the tolerance problem entirely. **Still prefer structural assertions for widgets** (text/geometry/enabled state via the API, no image). **The 3D viewport is the good golden case** — VTK draws geometry, so no font/style divergence, only software-vs-hardware GL | open | P1 | — | ai-metaanalysis §3.1.8; supersedes the "widget goldens are per-platform" conclusion in CS-058 |
| CS-070 | **Isaac Sim licence-status ROLLING LEDGER — re-check every 3 months.** Terms are changing fast (the source going Apache-2.0 is recent), so this needs monitoring rather than a one-time answer. **The recurring reminder itself lives in a DIFFERENT repo** (user's note, so it is not forgotten there) — this entry is the *status record* it points at. **Status as of 2026-07-30:** source = Apache-2.0; Kit SDK + assets = `NVIDIA Isaac Sim Additional Software and Materials License`; **redistribution of any runnable artifact (incl. a custom container image) NOT permitted without NVIDIA AI Enterprise / Omniverse Enterprise**; building a custom image for internal use IS supported; "ship the recipe not the image" is the clean workaround; no licence needed to sell USD assets + Python to clients running their own Isaac. Full citations in CS-064. **Ledger format for future checks — append, never overwrite:** `YYYY-MM-DD · checked by · what changed (or "no change") · source URLs · impact on CellSmith`. **Next check due: 2026-10-30** | open | P2 | — | ai-metaanalysis; see CS-061 + CS-064 for the detail |
| CS-071 | **Vendored UI font — 8 open-licence candidates rendered and compared** (Qt-rendered specimen, CAD-relevant sample text: `0O o / 1lI\| / 5S / 8B / 2Z / rn m`, plus `Ø ± ° Δ µ mm² ⌀ ×` and decimal dimensions). **All 8 rendered every CAD symbol** — no glyph gaps. Sizes: JetBrains Mono 182 KB · Fira Sans 446 KB · IBM Plex Sans 524 KB · Open Sans 520 KB · Source Sans 3 631 KB · DejaVu Sans 741 KB (current) · Inter 856 KB · Noto Sans 2001 KB. **RECOMMENDATION (awaiting user approval): IBM Plex Sans for UI + JetBrains Mono for numeric fields (~706 KB total).** Reasoning: Plex has the clearest `1`/`l`/`I`/`\|` disambiguation of the proportional candidates and was designed for technical/UI use — for a CAD tool, misreading a digit in a dimension or a component name is a *correctness* risk, so disambiguation beats aesthetics. Inter is the most modern-looking but has the **weakest** `I`/`l` distinction, which is the wrong trade here. Fira Sans is the runner-up (smallest full sans, 446 KB). **Key finding from the mono row: only JetBrains Mono column-aligns digits** — proportional fonts render `1` narrower, so numeric tables/spin boxes misalign. ❓ Worth testing: Qt 6.7+ `QFont::setFeature("tnum")` to get tabular figures from a proportional font instead of shipping a second file. Candidates staged in `scratchpad/fonts/`; only DejaVu is committed so far (`tests/fixtures/fonts/`) | open | P2 | — | **needs user approval of the visual** |
| CS-072 | **Doc screenshots = BUILD OUTPUT, not committed content** (the answer to UI screenshots in user docs, and it removes the blob problem at the root). Four approaches ranked: manual+audit (the default, and why most product docs show a two-versions-old UI) → manual+LFS (fixes repo size, not staleness) → avoid raster via annotated SVG/mermaid (genuinely right for *structure*, useless for *appearance*) → **⭐ generate at build time, never commit**. Feasible cheaply *because* offscreen capture already works (CS-052): `docs/generate_screenshots.py` is committed (it is code), `docs/src/**/_screenshots/*.png` is gitignored and regenerated by a `make screenshots` step before `mkdocs build`. Gains: zero blobs, never stale by construction, and a screenshot change reviews as a *code* diff. Degrade gracefully (skip + placeholder) so docs-only contributors aren't blocked. **THE UNIFICATION: a doc screenshot and a test golden are the same artifact with two consumers** — both are "drive the UI to a known state and capture it". Define a **named scene** once; the test asserts against it, the doc embeds it, the counter-example documents its failure — so one UI edit surfaces in both places. **Growth controls, in priority order:** generate-don't-commit; cap the *count* (a doc needing 40 screenshots needs one annotated diagram); cap the *size* (crop to the region discussed); detect staleness mechanically (same mtime pattern as the existing `Stop` hook — screenshot older than the GUI source that makes it); prefer mermaid when the subject is structure. ❓ Unverified whether mkdocs-material has a first-class build-time asset hook, or whether this is just a `make` ordering (the latter always works) | open | P2 | — | ai-metaanalysis §3.1.9; unifies with CS-068 |
| CS-073 | **Font licences VERIFIED — all candidates are SIL OFL 1.1** (checked by fetching each font's own `OFL.txt` from the `google/fonts` repo, not by assertion): IBM Plex Sans (IBM Corp, reserved name "Plex") · JetBrains Mono (JetBrains) · Fira Sans (Mozilla Foundation + Telefonica) · Source Sans 3 (Adobe, reserved name "Source") · Open Sans · Inter · Noto Sans. DejaVu Sans is under the permissive **Bitstream Vera** licence. **OFL 1.1 permits bundling in an application, including commercially, with no royalty** — the practical constraints are: keep the copyright + licence notice with the font file, and if you *modify* a font you must rename it (the Reserved Font Name clause). Bundling unmodified fonts is the normal, intended use, so this is compatible with an Apache-2.0 CellSmith. Licence text: https://openfontlicense.org/ · per-font: `https://github.com/google/fonts/blob/main/ofl/<name>/OFL.txt`. **Two large comparison sheets rendered for approval** (same UI text; ambiguity + digit alignment) | open | P2 | — | pairs with CS-071 (the recommendation) |
| CS-074 | **Screenshot refresh: THREE layered triggers, and `mkdocs serve` needs the first one.** A build-time step does not fire under `serve --livereload`, which is how docs are actually written. Layers: **(1) mkdocs `hooks`** — verified **new in 1.4**, takes "a list of paths to Python scripts … loaded and used as plugin instances", so an `on_files`/`on_pre_build` handler runs on **every** build incl. each serve rebuild; **(2) VS Code `preLaunchTask`** — added, staleness-gated so F5 stays fast; **(3) on-demand** `make screenshots` / a debuggable launch config — both added. **Two VERIFIED caveats:** (a) "for `mkdocs serve` the hook module will *not* be reloaded on each build" → keep the hook thin and delegate to `docs/generate_screenshots.py`, which IS re-read; (b) **there is NO watch-exclusion** (`watch` only *adds* dirs), so writing a PNG into `docs_dir` triggers one more rebuild — **staleness-gating is what makes this settle after one extra cycle instead of looping forever, so the gate is mandatory, not an optimization.** **Speed plan:** manifest staleness check must be **stat-only** in the common case (no Qt import); batch ALL stale scenes in **one** process (Qt startup + model load is the cost, capture is ms); hash *inputs* (generator + the GUI modules that scene touches + fixture) not outputs; scene-level granularity; capture at display size. **Fallback if still annoying: invert to WARN instead of regenerate** — print "3 screenshots are stale — run `make screenshots`", keeping serve instant; same polarity as the existing `Stop` hook. **BUILT:** `.vscode/tasks.json` (4 tasks: stale/force screenshots, tests all/ci) + 2 new launch configs. **NOT BUILT: `docs/generate_screenshots.py` itself** — the tasks reference it and will fail until written; it needs the named-scene definitions, which is the same work as CS-068's visual-test scenes. Source: https://www.mkdocs.org/user-guide/configuration/ | open | P2 | — | ai-metaanalysis §3.1.9 |
| CS-075 | **DONE — fonts vendored and wired end-to-end.** **IBM Plex Sans** (UI) + **JetBrains Mono** (numeric fields), both SIL OFL 1.1, in `src/resources/fonts/` with their OFL notices beside them (a licence requirement). New `src/gui/fonts.py` is the ONE registration path shared by the app, the tests, and the screenshot generator: `UI_FAMILY`/`MONO_FAMILY`/`UI_POINT_SIZE`, `font_dir()` (frozen-aware via `sys._MEIPASS`, mirroring `main._icon_path`), `register_fonts()`, `apply_app_font()`, `mono_font()`. `src/main.py` applies it right after `QApplication`; `packaging/cellsmith.spec` bundles `src/resources/fonts` → `resources/fonts`; `tests/conftest.py` now prefers the vendored fonts (system fonts only as fallback) and sets **Fusion** style. **Do not modify these .ttf files** — OFL's Reserved Font Name clause would require renaming them. Verified: generated `ui-widgets.png` shows Plex text and a visibly monospaced `12.70 mm` spin box; 8 tests still green | done | P2 | — | closes CS-071 + CS-073 |
| CS-076 | **⭐ HARD CONSTRAINT: a live GL widget CANNOT be captured offscreen — and it CRASHES, it does not raise.** Capturing the real `MainWindow` dies with an access violation (`0xC0000005` / rc 3221225477): `vtkWin32OpenGLRenderWindow` reports "failed to get valid pixel format" because the embedded `pyvistaqt` interactor has no real window to bind a GL context to. **`try/except` cannot contain a segfault**, so `docs/generate_screenshots.py` gained `isolate=True` → the scene runs in a **subprocess**, turning the crash into a catchable non-zero exit. Failures are also **cached against the scene's input hash** so a known-broken scene is not retried every run (otherwise a staleness-gated `preLaunchTask` pays a ~1.5 s process launch every time). **Consequence for the `offscreen` plugin specifically: full-window screenshots are not achievable there — but see CS-077, which SOLVES this via the native plugin.** What works is the two halves separately — pure-Qt widget trees via `QWidget.grab()`, and standalone `pyvista` offscreen plotters — so compose docs from **panel-level** captures, not whole-window ones. ❓ **Untested: whether Xvfb + Mesa on Linux succeeds where Windows offscreen fails** — worth trying, since it would restore whole-window capture in CI. **BUILT: `docs/generate_screenshots.py`** (named scenes with declared deps, SHA-256 input hashing, single-process batching for the cheap scenes, subprocess isolation for the crashy ones, `--check`/`--force`/`--only`/`--list`/`--stale-only`, graceful skip when the GUI env is absent). Verified: 2 scenes generate, the crashing one is contained, a second run is a clean no-op, `--check` exits 0 when current and 1 when stale | open | P1 | — | ai-metaanalysis §3.1.10; closes the build half of CS-074 |
| CS-077 | **⭐ SOLVED: full-window capture works with the NATIVE platform plugin — supersedes CS-076's "not achievable".** The problem was never "Qt cannot capture a window containing GL", it was "there is no GL context because there is no real window". Verified with `QT_QPA_PLATFORM` **unset** (native `windows` plugin), window moved to `(-4000,-4000)` and shown: `MainWindow()` constructs with **no crash**, and `win.grab()`, `centralWidget().grab()`, `QWidget.render()` and `QScreen.grabWindow()` **all succeed**. The 2560×1369 capture contains the ENTIRE UI — menu bar, Model Tree, Component Tree, viewport settings strip, CGB bar, the full Selection Filter with every checkbox, status bar — **only the viewport rectangle is black.** **The container idea was tested and is NOT the fix:** `centralWidget().grab()` works and a whole-window grab already includes every Qt child, so containment is not what is missing — the viewport is black because `QWidget.grab()` renders through Qt's **raster** engine, which cannot read back a **native** OpenGL surface; re-parenting changes nothing. **THE FIX = composite two captures:** (1) chrome via native-plugin `grab()`; (2) compute the viewport rect via `vp.mapTo(win, QPoint(0,0))` and `vp.size()`, scaled by `devicePixelRatioF()`; (3) render the same scene with an OFFSCREEN `pv.Plotter` at exactly that pixel size; (4) `QPainter.drawImage(rect, shot)`. Right rather than hacky because the offscreen plotter is the already-proven render path, the geometry comes from Qt so the seam is exact, both halves are independently testable, and the deterministic chrome can carry a **tighter tolerance** than the GL half in a golden compare. **Implementation gotchas:** move the window OFF-SCREEN rather than hiding it (a hidden window may never realize the native handle VTK needs); expect **device-pixel scaling** — `resize(1100,680)` yielded a 2560×1369 pixmap. **Capture method by target:** widget/panel → `QWidget.grab()` (headless ✔); viewport alone → offscreen `pv.Plotter` (headless ✔); **full window → native plugin + composite (needs a real window or Xvfb)**. CI keeps the first two tiers; full-window shots generate locally and, being build output, never need committing. ❓ **Untested and worth it: Xvfb + Mesa on Linux** (would bring full-window capture into CI), and a **Mesa `opengl32.dll`** beside the interpreter on Windows (would give VTK software GL under `offscreen`, removing the real-window requirement). **NOT YET IMPLEMENTED in `generate_screenshots.py`** — the composite scene type is designed, not built | open | P1 | — | ai-metaanalysis §3.1.10 |
| CS-078 | **DONE — captures are now DARK and deterministic.** New `src/gui/theme.py`: `dark_palette()`, `apply_dark(app)` (Fusion style + explicit dark `QPalette` incl. Disabled-state roles, or disabled text is unreadable), and `VIEWPORT_BG = #1e1e1e` so an offscreen 3D render matches the dark chrome instead of punching a white hole. Wired into `docs/generate_screenshots.py` (both the batched and the isolated-child paths) and `tests/conftest.py`; the widget scene no longer hardcodes `#f4f4f4` and instead inherits the palette. **WHY it was needed:** the app sets **no palette at all** — Qt 6 inherits the **OS** color scheme, so CellSmith is dark on a dark-mode desktop and light on a light one. Correct for a user, wrong for a capture (same code, different pixels per machine). **`QStyleHints.setColorScheme(Qt.ColorScheme.Dark)` exists in Qt 6.11 but is a NO-OP under `offscreen`** — probe-verified: `colorScheme()` stays `Unknown` and the palette stays `#efefef`, because the platform plugin must implement it. **So a stable capture pins THREE variables: style + palette + font.** `theme.py` is deliberately NOT used by the app (an in-app theme toggle would be a separate decision). Verified: regenerated `ui-widgets.png` matches the app's dark look; 8 tests green | done | P2 | — | ai-metaanalysis §3.1.10 |
| CS-079 | **⭐ ROOT CAUSE of the black viewport — and it CORRECTS CS-077's explanation.** Controlled experiment (a `QOpenGLWidget` clearing to magenta inside a normal window, grabbed, center pixel sampled), run on **both** OSes: plain Qt widgets capture everywhere; **`QOpenGLWidget` is LOST under `offscreen` but CAPTURED under the native plugin** (magenta came through, on Windows `windows` AND Linux `wayland`); `QVTKRenderWindowInteractor` is **lost in both**. **So "Qt's raster engine cannot read back a native OpenGL surface" was TOO BROAD** — Qt composites a `QOpenGLWidget` into `grab()` fine. The real cause is the widget class: `pyvistaqt.QtInteractor` → `pyvistaqt.rwi.QVTKRenderWindowInteractor` → **plain `QWidget`** (verified MRO), whose native handle is given to VTK to render into directly — a surface **foreign to Qt's composition**, so Qt paints around it with nothing to read back. A `QOpenGLWidget` renders into an FBO Qt owns, hence the difference. **REAL FIX PATH: VTK's `QVTKOpenGLNativeWidget` IS a `QOpenGLWidget` subclass** — swapping the viewport onto it would make a single-call full-window `grab()` capture everything, no compositing. Cost: pyvistaqt offers no such backend, so it means wiring a pyvista plotter to a VTK-native widget ourselves — a viewport-architecture change, worth it only if full-window capture matters beyond docs. ❓ untested whether it works under `offscreen`. **ANSWER to "capture a full window WITHOUT a real window": NO, not with the current viewport** — `offscreen` loses GL in every configuration and the VTK interactor also crashes at construction. **But "without a real window" ≠ "without a desktop session", and the second is what CI needs: WSLg already provides `DISPLAY=:0` + Mesa, and the native path was VERIFIED working there** — so full-window capture IS available in a Linux container with a virtual display. Also corrected: the earlier 2560×1369 grab was **`MainWindow` restoring a saved geometry, not DPI scaling** (measured `devicePixelRatio` = 1.0). ❓ Still untested: a Mesa `opengl32.dll` beside the interpreter to give VTK software GL under `offscreen` | open | P1 | — | ai-metaanalysis §3.1.10; corrects CS-077 |
| CS-080 | **CLOSED by evidence: the Mesa `opengl32.dll` idea is a DEAD END** — the offscreen blocker is not the GL implementation, it is the absence of a window. Probed with ctypes under `QT_QPA_PLATFORM=offscreen`: `winId()` returns **1** (a fake handle), `IsWindow(winId)` is **False**, `GetDC()` returns **0**. Under the native plugin the same widget gives a real HWND, a valid DC, and **220 available pixel formats**. `vtkWin32OpenGLRenderWindow` needs an HWND + DC to choose a pixel format, so **no OpenGL implementation — Mesa, ANGLE, software or otherwise — can help**; the failure is upstream of GL entirely. Saved a ~50 MB download and closes the last ❓ on CS-079 | done | P2 | — | ai-metaanalysis §3.1.10 |
| CS-081 | **DONE — the COMPOSITE full-window capture works.** `docs/generate_screenshots.py` gained `native=True` on `Scene` (implies `isolate`): the child subprocess is spawned with `QT_QPA_PLATFORM` **removed** and `CELLSMITH_SHOT_NATIVE=1`, so the module-level offscreen default is skipped and GL gets a real window. The `main-window` scene now: constructs `MainWindow` natively at `(-4000,-4000)`, `grab()`s the chrome (viewport black), computes the GL rect, renders the same scene with an **offscreen `pv.Plotter`** at exactly that pixel size on `VIEWPORT_BG`, and `QPainter.drawImage`s it in. **Result verified: a complete dark full-window screenshot** — menu, Model Tree, Component Tree, viewport settings strip, CGB bar, full Selection Filter, status bar, and seamless 3D content. **BUG found and fixed in the process:** the rect must target **`win._viewport.plotter.interactor`**, NOT `win._viewport` — the latter is a container that also holds the settings strip and the selection/construction bars, so pasting over the whole panel silently ERASED them from the screenshot. Also confirmed the dpr formula (`chrome.width() / win.width()`) is self-correcting: `MainWindow` restores a saved geometry (2560×1369 despite `resize(1280,800)`), and comparing the grab to the *actual* widget size handles that. **`QVTKOpenGLNativeWidget` was therefore NOT needed** — kept as the eventual structural fix (it would remove the seam entirely) but not required for docs | done | P1 | — | ai-metaanalysis §3.1.10; supersedes CS-077's "designed, not built" |
| CS-082 | **DONE — repo layout tidied.** (a) `cellsmith_entry.py` → **`src/__entrypoint__.py`**; (b) `cellsmith.spec`, `environment.yml`, `requirements.txt` → **`packaging/`** (root `requirements.txt` was referenced by nothing and is now `packaging/requirements.txt`; `docs/requirements.txt` is a separate mkdocs file and untouched). Scripted rewrite updated 11 files (`Makefile`, `dev.bat`, `build.bat`, the spec itself, `CLAUDE.md`, and 6 docs); zero leftover references. Spec-internal relative paths still resolve because PyInstaller is invoked from the repo root. (c) **`mkdocs.dev.yml` now truly excludes `AI/Reference/`** via `exclude_docs` — the previous `not_in_nav` only hid those pages from navigation while still building them. Reference pages are `audience: agent` (dense, terse), so rendering them wastes build time and clutters the nav; everything else under `AI/` is `audience: both` and still builds | done | P2 | — | `packaging/`, `docs/mkdocs.dev.yml` |
| CS-083 | **DONE — `docs/src/AI/Scratch/ai-history.md` "AI Input" section written** as a dated case-study timeline reconstructed from git. **Three eras:** (1) *No memory* (Jul 9–10, 0→5,942 LOC, no `CLAUDE.md`) — pure vibe coding at ~3k lines/day; (2) *The monolith* (Jul 10–27, →34,374 LOC) — `CLAUDE.md` appears at **901 lines** (written reactively, all at once) and grows to **4,550**; (3) *Restructure* (Jul 27–31, all UNCOMMITTED) — `CLAUDE.md` collapses **4,550 → 134 lines (34×)** and the content redistributes into hub/Reference/Specs/status/Scratch + skills + hooks + tests. **The key quantitative finding: instruction density ROSE from 113 to 132 doc-lines per 1k LOC** — a working hub would flatten as early instructions generalize; rising density is the signature of instructions being *appended rather than reconciled*, which explains "adding one feature would break another" (contradictions 2,000 lines apart are undetectable). Also: **~25% of each large commit is deletions** (rework, not accretion), and **`.claude/` and `docs/` appear in ZERO commits** — the whole workflow apparatus is uncommitted. **Meta-finding: the commit log is information-free** (6× `updated`, plus `big update` / `lots of updates` covering ~28k lines), so git was never the decision record — which is itself the best explanation for why `status.md` and the flush gate became necessary. ❓ **Missing primary source: the session transcripts** — prompts, correction counts, and discarded code are unrecoverable from the tree; capturing them going forward would be worth more than further archaeology. ❓ Also unmeasured: whether Era 3's apparatus actually lowers the defect rate (it is 4 days old and `src/` has barely changed under it) | done | P2 | — | `docs/src/AI/Scratch/ai-history.md` |
| CS-084 | **Composite paste-rect bug: FIXED + GUARDED, class does not carry forward silently.** The specific bug (rect targeted `_viewport`, a container, instead of `_viewport.plotter.interactor`) is fixed. Because the failure mode was **a plausible-looking screenshot with UI silently erased**, a guard is now in the scene: the GL hole is a uniform block in the chrome grab, so all four corners of the computed rect are sampled and compared to the hole's center color — any mismatch raises with a message naming the correct attribute. Fails loudly instead of producing a wrong image. Verified: passes with the correct rect, all 3 scenes regenerate. **Residual risk is low but real:** the guard catches "rect too big" (the dangerous direction) and not "rect too small" (which would leave a black border — visible, self-evident). A golden image would catch both once one exists (CS-068) | done | P1 | — | `docs/generate_screenshots.py` |
| CS-085 | **CI SUPPORT IS NOT COMPLETE — honest matrix.** Verified working: Tier-1 logic (OCC/numpy/pxr) on both OSes; offscreen `QWidget.grab()` on both; offscreen `pv.Plotter` on Windows **and** in WSL. **Verified NOT possible under `offscreen`:** anything needing the VTK interactor (no window → no DC → no pixel format, CS-080). **UNTESTED and the actual gaps:** (a) **offscreen `pv.Plotter` inside a real Docker container** — WSLg supplied a display and Mesa, so the WSL result does NOT prove a bare container works; needs `libgl1-mesa-dri` (+ maybe `xvfb-run` / `pyvista.start_xvfb()`); (b) **the full-window composite in CI** — needs a virtual display (Xvfb), untested; (c) **no GitHub Actions workflow exists at all** — `make test-ci` is runnable but nothing runs it automatically. Also a real gap: the `main-window` scene is `optional=True`, so a genuine CI failure there would **not** fail the build — acceptable while the scene is new, must be flipped once it is load-bearing. **So: the two cheap test tiers are CI-ready in principle; nothing is CI-verified in practice.** Next step is a minimal workflow running `make test-ci` in a Linux container, which would settle (a) immediately | **superseded** | P1 | — | ai-metaanalysis §3.1.2, §3.1.4; **resolved by CS-090** |
| CS-086 | **`exclude_docs` alone does NOT hide a directory when `include_dir_to_nav` is in use** — root cause found by reading the plugin source. `IncludeDirToNav.on_files` builds the nav by walking the **filesystem** (`os.walk`, `os.path.isdir`) with no knowledge of mkdocs' `exclude_docs`, so a bare `- AI Docs: AI` entry still inserted nav links for the excluded `AI/Reference/*` pages. Those links pointed at files mkdocs never built → titles rendered as **"None"** and clicking one **404'd**. (`not_in_nav` is also wrong here: it only hides pages from navigation while still building them.) **FIX: write the AI nav longhand** in `mkdocs.dev.yml` so the plugin never auto-expands that one directory, while still letting it expand `Specs/` and `Scratch/`. **Verified by building the dev site:** `AI/` now contains only `index.html`, `status.html`, `Specs/`, `Scratch/`; zero `>None<` in the nav. **Maintenance consequence: adding a new top-level folder under `AI/` now requires a line in `mkdocs.dev.yml`** — the cost of bypassing the plugin | done | P2 | — | `docs/mkdocs.dev.yml`; plugin at `docs/venv/.../mkdocs_include_dir_to_nav/` |
| CS-087 | **`pytest.ini` MUST stay in the repo root — it is a rootdir anchor, not clutter.** Tested by moving it to `packaging/` and running `pytest` from the root: it did not merely lose the config, it **crashed with `INTERNALERROR`**. pytest derives `rootdir` from where it finds `pytest.ini` / `pyproject.toml` / `tox.ini` / `setup.cfg` by walking **up** from the invocation path; from `packaging/` it is never found, so `testpaths`, `addopts`, and crucially **`--strict-markers`** all stop applying — meaning a typo'd marker would silently pass and a test would never run. Restored; 8 tests green. **If the goal is fewer root files, the correct move is folding the config into a root `pyproject.toml`** under `[tool.pytest.ini_options]` (still root, but conventional, and it could later hold ruff/mypy config too). There is no `pyproject.toml` today | done | P3 | — | `pytest.ini` |

| CS-088 | **Explicit PIVOT PICKER for the main-window Transform.** The pivot is currently chosen automatically — the node's CUSTOM ORIGIN when it has one, else the subtree world-AABB **centre**, else the node frame (`_transform_pivot`) — and is shown in the pane title but NOT user-settable. Add a CGB **Point** request (like From/To Point) so any pivot is reachable: `_xform_cmd["pivot_world"]` + `pivot_src` already drive the preview and are stored as `ComponentTransform.pivot` provenance, so the picker only has to write those two and call `_on_transform_pane_changed()`. User-requested, deliberately deferred | open | P2 | — | round 11; `_transform_pivot` / `_refine_transform_pivot_async` |
| CS-093 | **DONE — `nav_exclude` implemented: include-by-default, exclude-by-exception.** Replaces CS-086's longhand-nav workaround, which required a config line per new folder. `docs/hooks/nav_merge.py` gained: `extra.nav_exclude` (a list of path prefixes), pruned from the nav in an **`on_files` handler decorated `@event_priority(-100)`** — the priority is the whole trick, because `include_dir_to_nav` generates its directory entries in its own `on_files` by walking the filesystem, so pruning must run AFTER it (pruning in `on_config` cannot work — the entries do not exist yet). The same hook also appends those prefixes to `config.exclude_docs` in `on_config`, so excluded pages are **not built at all** rather than left as unlinked live URLs (mkdocs compiles `exclude_docs` into a `PathSpec` at load time, so the hook extends the compiled spec using the non-deprecated `"gitignore"` factory). Empty sections are dropped so excluding a directory removes its heading. **`mkdocs.dev.yml` is back to `- AI Docs: AI` (auto-expanded) + `nav_exclude: [AI/Reference/]`** → adding a new folder under `AI/` now needs **no config change**. **Verified by building the dev site:** `AI/` contains only `index.html`, `status.html`, `Specs/`, `Scratch/`; zero `>None<`; no `AI/Reference` in the nav; no new warnings | done | P2 | — | `docs/hooks/nav_merge.py`, `docs/mkdocs.dev.yml` |
| CS-089 | **`pyproject.toml` — worth adding LATER, and it must never become a second dependency list.** What it would provide: (a) **one config home** — pytest, ruff, mypy, coverage, isort all read `[tool.*]`, so it consolidates instead of adding a root file per tool; (b) **PEP 621 metadata** enabling `pip install -e .`, which would make `from src.gui...` imports work without depending on pytest injecting rootdir into `sys.path` (today `tests/conftest.py` relies on exactly that); (c) a **console-script entry point** (`cellsmith` instead of `python -m src.main`); (d) **single-sourced version** via `dynamic = ["version"]` reading `src/__version__.py`. **The catch specific to this project: the env is conda and `pythonocc-core` has no pip wheel**, so `packaging/environment.yml` must remain the dependency source of truth — declaring deps in `pyproject.toml` too would create a second, silently divergent list. Use it for **tool config + metadata only**. Also note it does **not** advance the "fewer root files" goal (it must live in root, same as `pytest.ini` — one file replaces one file). **Recommendation: add it when a linter is introduced** (so it consolidates 2+ configs), or sooner only if an editable install / console script is wanted | open | P3 | — | pairs with CS-087 |
| CS-090 | **⭐ CONTAINER GL RESOLVED — Mesa is NOT enough; `xvfb-run` is required (tested in a real `python:3.12-slim` container).** Three configurations, offscreen `pv.Plotter().screenshot()`: **(1) bare container → SEGFAULT (exit 139)**; **(2) + `libgl1`/`libglx-mesa0`/`libgl1-mesa-dri` + `LIBGL_ALWAYS_SOFTWARE=1` → STILL SEGFAULT (139)**; **(3) + `xvfb-run -a` → `RENDER_OK shape=(150,200,3) std=31.64`, a real image, exit 0.** VTK's own warnings name the cause exactly: it tries **X11 → EGL → OSMesa** in order and all three fail in a slim container (`bad X server connection. DISPLAY=`, `Failed to load EGL`, `libOSMesa not found`). **So installing Mesa's GL driver does nothing without a display or an alternative backend.** Two ways to avoid Xvfb, both untested: install **`libegl1`** (VTK's second path) or **`libosmesa6`** (its third), or use the `vtk-osmesa` / EGL wheels — either would give truly headless rendering. **CI-critical robustness point: the failure is a SEGFAULT, not an exception**, so a test cannot catch it — the runner dies. Xvfb (or EGL/OSMesa) must be provided at the *environment* level in CI, not defended against in Python. `make test-ci` should therefore be invoked under `xvfb-run` on Linux, and `tests/conftest.py` could call `pyvista.start_xvfb()` as a belt-and-braces fallback | done | P1 | — | supersedes the gaps in CS-085 |
| CS-091 | **⭐ CORRECTS CS-090 — `libegl1` beats Xvfb for offscreen rendering; Xvfb is only needed for a native WINDOW.** Tested in `python:3.12-slim`: **offscreen `pv.Plotter` works with `libegl1` installed and NO display and NO Xvfb** (`std=31.64`, real image, exit 0). VTK tries **X11 -> EGL -> OSMesa**; supplying the *second* path is enough, so the earlier "Xvfb is required" conclusion was too strong — it was required only because the slim image had none of the three. `libosmesa6` also works (third path). **But a native Qt window still needs a display:** with EGL present and no Xvfb, `QApplication` fails with `qt.qpa.xcb: could not connect to display`. **Under `xvfb-run` the full composite path WORKS** — `platform: xcb`, and a `QOpenGLWidget` inside a grabbed window returns `#ff00ff` = **GL CAPTURED**. So both CI tiers are viable: **`libegl1` for the cheap offscreen tier, `xvfb-run` additionally for full-window composites.** Also learned: the first composite attempt failed only on a missing `libglib-2.0.so.0` — a packaging gap, not a capability limit; full Qt system deps for a slim image are `libglib2.0-0`, `libgl1`, `libglx-mesa0`, `libgl1-mesa-dri`, `libegl1`, `libxkbcommon0`, `libxkbcommon-x11-0`, `libxrender1`, `libxext6`, `libfontconfig1`, `libdbus-1-3`, and the `libxcb-*` set. ❓ Untested: Qt's `minimalegl` / `eglfs` plugins, which might give a native-ish platform with no X server at all | done | P1 | — | supersedes CS-090's requirement claim |
| CS-092 | **Telemetry VALUE analysis done — cut the metric list from 15 to 3.** Ran Section A (zero-collection) against real git data and asked what telemetry adds beyond it. **Finding: descriptive history is ~90% recoverable with NO collection** — the entire three-era narrative, instruction density (113→132 per 1k LOC), and rework rate (3–22%, peaking in the two "big update" commits) all came from git alone. **Telemetry buys nothing for reconstructing the past and is the only way to close loops on the present.** Keep exactly three: **(1) doc-read distribution** — highest value, nothing else observes it, immediately actionable (which of 18 Reference/Specs pages are dead weight), and it also validates the doc map; **(2) verification ratio** — Era 3's premise that a test harness changes outcomes is currently **unfalsifiable**; **(3) corrective-turn rate** — the causal companion to the density correlation, and the difference between "rewrite CLAUDE.md" and "the project just got bigger", which imply opposite fixes. **CUT: turns-per-task** (task difficulty dominates, nothing to normalize against at N=1 project) and **all per-contributor breakdowns** (N=2). Strongest single argument found for telemetry: the `CLAUDE.md` headless-rendering claim was **confidently wrong and suppressed visual testing for weeks** — doc-read counts + corrective-turn rate together are the signature of a confidently-wrong doc, which is the dominant docs failure mode at scale (plausible staleness, not absence). Section C projects what matters as docs grow 18→60+ (synthetic chart, labeled as such). Written with **inline SVG charts** (theme-aware via CSS vars, no JS dependency) | done | P2 | — | `ai-history.md` → "Telemetry Value Analysis" |
| CS-094 | **TODO: adopt `ruff` + `mypy` with strict settings.** Both read `[tool.*]` from `pyproject.toml` (now created, config stubs left commented). **ruff** = fast Rust linter/formatter replacing flake8+isort+pyupgrade+parts of pylint; **mypy** = static type checker. **Why they matter HERE specifically:** (a) `CLAUDE.md` already mandates "type hints" and "keep OCC, VTK/PyVista, and USD imports isolated to their layers" — mypy makes the first enforceable and ruff's `flake8-tidy-imports` per-file banned-api makes the second **mechanical instead of a convention an agent can violate silently**; (b) after 18 days of rework at 3–22% deletion rates, dead code is near-certain; (c) it gives agents a **second automated check** — `make test` answers "did I break behavior", a linter answers "did I break convention", and it needs no GL so it is trivially CI-safe. **Quantifiable expectations (estimates, not measured):** first `ruff check` on ~35k unlinted lines will surface **several hundred** findings, the large majority auto-fixable with `--fix` (import order, unused imports, f-string/`pathlib` modernization); genuine bugs found will be a **small fraction** but skewed toward the valuable kind (unused variables masking typos, shadowed names, mutable default args). `mypy --strict` on a codebase with partial annotations typically reports **thousands** initially — so **do not start strict**; start on the layer seams and `pydantic` models where a wrong type becomes a wrong export. Recommended path: ruff with a small rule set → `--fix` → widen rules → mypy per-module | open | P2 | — | `pyproject.toml` |
| CS-095 | **DONE — `pytest.ini` consolidated into `pyproject.toml`** (`[tool.pytest.ini_options]`), `pytest.ini` deleted. Verified both tiers still work: 8 passed / 7 passed + 1 deselected, so `testpaths`, `addopts`, and `--strict-markers` all still apply. Scope note written into the file: it configures **tools only** and must **never** become a dependency list — the env is conda (`pythonocc-core` has no pip wheel), so `packaging/environment.yml` stays the source of truth and a second list would silently diverge. It must stay in the repo ROOT (pytest derives `rootdir` from it; see CS-087) | done | P3 | — | `pyproject.toml` |
| CS-096 | **DONE — CI system dependencies documented where tests live: new `docs/src/AI/Reference/testing.md`** (audience: agent), pointed at from `tests/conftest.py`'s module docstring and added to the `CLAUDE.md` doc map. Contains the tier table, marker polarity, the exact `apt-get` lines, and the configuration matrix proving **Mesa's GL driver is not a GL backend** (`libgl1-mesa-dri` + `LIBGL_ALWAYS_SOFTWARE=1` still segfaults; **`libegl1`** is what fixes offscreen rendering, and `xvfb` is needed only for full-window captures). Also records the two traps: VTK **segfaults rather than raising** when no backend exists (so a test cannot catch it — the runner dies, and the dependency must be supplied at the environment level), and a missing loader library (`libglib-2.0.so.0`) reads as a capability limit if you stop at the first error | done | P1 | — | `docs/src/AI/Reference/testing.md` |
| CS-097 | **Inline SVG in mkdocs must NOT be wrapped in `<div markdown="1">`.** The charts in `ai-history.md` rendered as **flowing unstyled text with no graphics** — cause: `markdown="1"` tells the `md_in_html` extension to parse the div's *contents as markdown*, which escapes/strips the SVG tags and leaves only the text nodes. Fix: plain `<div style="overflow-x:auto">` (no `markdown` attribute) and keep each `<svg>` block free of blank lines so Python-Markdown treats it as one raw-HTML block. **Verified by building and grepping the output:** 4 × `viewBox="0 0 760 300"` present, 5 polylines, 37 circles, **0 occurrences of `&lt;svg`**. General rule for this repo: **inline SVG is the right charting choice** (theme-aware via CSS custom properties, no JS dependency, diffable) — but it is raw HTML and must be passed through untouched | done | P2 | — | `docs/src/AI/Scratch/ai-history.md` |
| CS-098 | **Telemetry analysis REVISED — the recommendation is now "build none of it yet".** Re-examined each remaining metric for a **zero-instrumentation side channel**, and two of three have one: **verification ratio** → *instrument the TEST RUNNER, not the agent* (a one-line counter appended by `make test`, plus `pytest_sessionfinish` for authoritative pass/fail) — same number, no privacy surface; **corrective-turn rate** → the `precompact` skill **already requires "Corrections" to be recorded in `status.md`**, and the Developer Log's `felt-like` field captures the subjective version, so counting those entries gives the trend for free (undercounts, human-filtered, but the *direction* is what the decision needs); **doc-read distribution** → partial free proxy from **citation count in `status.md`/commit messages + inbound link count + edit staleness**, which answers the actionable question (what to prune) if not the precise one. **`turns per task` dropped entirely.** ❌ Rejected proxy: filesystem `atime` — NTFS delays it, Linux mounts use `relatime`, and any tool touching a file pollutes it. **So the honest conclusion is that the analysis argued the instrumentation is not yet needed** — build the derived-metrics script, add the test-runner counter, keep the Developer Log. **Revisit trigger: when a specific decision is blocked by a number no proxy gives** — most likely doc pruning at 40+ pages, where "which of these is dead" stops being answerable by inspection. Every plot now carries **what it shows / conclusion / what to do about it + impact**, per the data-driven-AI-use narrative | done | P2 | — | `ai-history.md` → Telemetry Value Analysis |
| CS-099 | **Chart rendering conventions for these docs (learned the hard way, twice).** (1) **Never wrap inline SVG in `<div markdown="1">`** — `md_in_html` parses the contents as markdown and strips the tags, leaving unstyled flowing text (CS-097). (2) **Legends must live in a reserved header band above the plot, ONE ENTRY PER LINE.** First attempt put them inside the plot area (overlapped the data and the y-axis labels); second attempt laid them out horizontally, which needs a text-width estimate — any estimate slightly low makes labels collide, and mine did. Stacking needs no measurement. (3) Body type at **5.5px**, titles 7px, in a 720×250 viewBox — roughly half the original size. (4) **Verify by RENDERING, not by counting tags:** `scratchpad/render_svgs.py` extracts every `<svg>` from the markdown, substitutes concrete colors for the CSS custom properties (which have no value outside a browser), rasterizes via `QSvgRenderer`, and stacks them into one sheet to read back. Note the harness needs a font registered or all text is tofu — the layout is still judgeable through tofu because the boxes occupy the real text's bounding box | done | P2 | — | `scratchpad/charts2.py`, `scratchpad/render_svgs.py` |
| CS-100 | **New-design item added to `intro-model-structure.md` §16.17: enforce layer boundaries MECHANICALLY from day one.** The OCC / VTK / `pxr` / GUI separation is currently a convention that `CLAUDE.md` states and nothing checks — the failure mode being that a violation *produces working code* and only becomes a problem later. `ruff`'s `flake8-tidy-imports` supports **per-file banned imports**, so the layer map becomes a config table (a populated table is in the section); `mypy` on the **seam signatures** covers the other half, since a wrong type at a layer boundary is how a wrong export happens. **Why it must start with the redesign rather than follow it:** retrofitting means triaging hundreds of pre-existing violations before the check can be enabled, and a check that cannot be enabled provides nothing — applied from the first commit it costs ~zero. Four rules recorded, including the important one: **a needed exception is a design signal, not a config edit** — either the layer map is wrong or the module is in the wrong layer, so it goes in `decisions.md` rather than quietly widening the allowlist | open | P2 | — | intro-model-structure §16.17; implements CS-094 |
| CS-101 | **Chart/analysis presentation contract for `ai-history.md`.** Every plot now ends with **three** labelled blocks, in order: *What it shows* -> *Conclusion* -> *What to do about it* -> **What this gets me** (on its own line, answering the reader's actual question rather than restating the action). Also moved the three triangulating doc metrics into **Part A / A5** where they belong (citation count in `status.md`+commit messages, inbound-link count vs `CLAUDE.md` map rank, and commit/mtime edit frequency) because they need **zero collection** - none is convincing alone, but *never cited + zero inbound links + unedited for months* is a strong deletion candidate and *heavily cited + poorly ranked* is a strong promotion candidate. **That triangulation is what demotes doc-read telemetry from necessary to optional**, since pruning was its main justification. Part B rewritten as **B4 = expected RESULTS, not actions**: doc pruning -> fewer `Read` calls before the first `Edit`; verification ratio -> defects appear as CI failures instead of user reports (this session shipped three found only by a human looking); corrective-turn rate -> fewer repeat corrections, and since two failed corrections on one issue means the session should be restarted, each avoided repeat saves a **session**, not a turn | done | P2 | - | `ai-history.md` |
| CS-102 | **A5 readouts built on REAL repo data - and they DISPROVED the A5 rule.** Computed citations (status.md + commit messages), inbound links, and mtime age for all 28 AI docs; rendered a scatter (citations vs inbound, point area = page length) and a descending inbound-link bar chart, both with native SVG `<title>` **hover tooltips** showing filename + all metrics (56 tooltips, no JS). **Result: 17 of 28 docs have ZERO citations and 15 of those are `Reference/` pages** - `node-state-and-color.md` scores worst on every axis, and the rule says delete it. **The rule is wrong:** it documents a real working subsystem, and a doc for a FINISHED feature is *supposed* to be quiet. Two unfixable biases: **task bias** (citations live in status.md, which records what THIS session touched - recent sessions were docs/workflow-focused so code-reference pages could not be cited; measure during a geometry sprint and the ranking inverts) and **stability bias** (low activity on a reference doc is evidence the SUBSYSTEM is stable, the opposite of evidence the doc is worthless). **A5 demoted from decision rule to anomaly detector**, trusting only the two combinations stability does not explain: **orphaned** (zero inbound links - nobody can find it) and **mismatched** (heavily cited but poorly ranked in the CLAUDE.md map) | done | P2 | - | `ai-history.md` A5.1 |
| CS-103 | **GOAL REFRAME (B5) - the whole metric suite was measuring housekeeping, not outcomes.** Instruction density, doc reads, verification ratio, citations, links, edit frequency: **every one measures the state of the PROCESS, none measures whether the WORK got better.** A5 proved the failure concretely by nearly deleting 15 legitimate docs. The tell: **A3 (rework rate) is the only outcome metric in the set**, which is exactly why it reads as the most useful chart. **The right question is not "is the doc system healthy" but "is the human doing less work per unit of correct delivered output, and what is now possible that was not?"** Two axes, different in kind: **EFFICIENCY** = a rate = **human interventions per delivered outcome** - which is the user's own phrase *"I have to keep riding you"*, and it decomposes into four types that each name a DIFFERENT fix (*that's wrong* -> reconcile instructions; *why did you stop* -> persistence rule/diagnose skill; *did you check X* -> cheaper verification; *where does this go* -> doc map). **CAPABILITY** = a ledger, not a rate = dated list of newly-feasible things; this session added offscreen render verification, full-window composite, container GL CI, Isaac headless probing, and mechanical layer enforcement - **none of which moved any process metric**, which is decisive evidence the process metrics were the wrong target. **Actions: track interventions by type in the Developer Log (one line per session); keep a dated capability ledger; demote A1-A5 to tripwires reported only when they trip; DROP the telemetry question entirely** - it was scoped to serve the housekeeping goal | done | **P1** | - | `ai-history.md` B5; supersedes the framing of CS-092/CS-098/CS-101 |
| CS-104 | **DONE - persistence rule + `diagnose` skill implemented, split by SCOPE not convenience.** The earlier personal/repo split was incidental; corrected. The two locations are different **distribution channels** (`~/.claude/` = all your projects, shared with nobody; repo `.claude/` = all contributors, via git), so "use everywhere AND share with the team" needs both. Placement: **`.claude/skills/diagnose/SKILL.md`** = canonical full procedure, body written generically with repo-specific examples marked so it copies to `~/.claude/skills/` unedited; **repo `CLAUDE.md`** = the **RED LIST** (project-specific: names OCC/VTK/USD layers, `decisions.md`, the B-rep path) + skill pointer; **personal `CLAUDE.md`** = the universal habit only, so it still works in repos with no skill. **Maintenance rule: the repo copy is canonical, improvements flow repo -> personal, one direction, so drift has a defined resolution.** Rejected: `CLAUDE.md`'s `@path` import - resolves only on one machine, so it cannot distribute to teammates. Skill fires **automatically** (description names the symptoms and the phrases about to be used); stop-digging threshold is **four consecutive attempts revealing nothing new**, deliberately diverging from the guide's "two failed corrections" because that counts human interventions while this counts autonomous dry attempts | done | P1 | - | `.claude/skills/diagnose/`, both `CLAUDE.md` files |
| CS-105 | **DONE - `Scratch/ai-self-analysis-research-method.md`: SPEC for the `ai-retrospective` skill** (skill NOT built). Structured as a research paper: context, problem, intended outcome, RQ1-RQ6, methodology, report template, iteration mechanics, carried-in learnings, game plan. **The central design decision is a three-class metric taxonomy that resolves the user's air-filter correction:** **outcome** metrics (rework rate, interventions/tokens/calendar-time per outcome) may justify action alone; **drag indicators** (instruction density, orphaned docs, verification ratio, best-practice alignment) are **kept, not discarded** - individually inconclusive but cheap to read and cheap to fix, each with a known remedy - yet **subordinated by one rule: a drag indicator is a HYPOTHESIS about why an outcome is poor, so act on it only when an outcome metric is degraded or the fix costs less than the measurement**; **capability** is a dated ledger, recorded not scored. That rule is exactly what would have prevented the A5 near-miss. Efficiency explicitly has **three unevenly-measurable dimensions** (human intervention / token use / calendar time) that **must not be aggregated** - they trade against each other and the trade is the subject of study. Falsifiability is enforced structurally: **an action without a predicted measurable outcome is not an action, it is an open question**, and each report's section 8 grades the previous report's predictions CONFIRMED/REFUTED/INCONCLUSIVE. Reports are immutable and date-stamped so knowledge stacks. **Game plan phase 4 (build the skill) deliberately follows phase 3 (do it by hand once)** - writing the skill first would encode guesses about the procedure | done | P1 | - | `ai-self-analysis-research-method.md` |
| CS-106 | **Research-method spec REVISED - three structural corrections.** (1) **Research methodology and experimental procedure are now separate sections.** They were conflated: **Sec.5 = methodology** = the *reasoning framework* (metric taxonomy + the gating rule, the three efficiency dimensions, inference rules incl. task/stability bias, the mandatory data-source preference order, the alignment-audit scoring); **Sec.6 = procedure** = the *executable* steps P1-P10 (go/no-go, run the snapshot script, tabulate the Developer Log, diff vs previous, classify, gate drag findings, grade prior predictions, write, commit) plus the mechanics table. Judgment lives in 5, mechanics in 6. (2) **ALL TELEMETRY REMOVED and dropped going forward** - no instrumented collection, no rollups, no per-session counters; data sources are now 6 tiers (git, status.md, filesystem, CI logs, Developer Log, published best-practice docs) and **tier 5 is the only new input: one human-written line per session, not instrumentation**. Snapshots moved out of a `telemetry/` path to `AI/research/snapshots/`. (3) **The report template IS the document's own Sec.1-10 outline**, and each report **re-states all ten sections rather than referencing back** - because context, problem framing, methodology and procedure all evolve, so a report must be a standalone snapshot of the entire research effort at that date. The spec is explicitly labelled as iteration 0 of its own template; spec-only material moved to Appendices A-C. **NEW deliverable: Sec.8.3 = skill revision recommendations** (what to change in the `ai-retrospective` skill, why the current version was insufficient, how to verify the change helped) - a first-class output, because the skill will be wrong in ways only running it reveals, and **a method with no self-revision channel decays exactly like an instruction file that is only ever appended to**. Added to the failure-modes list: *a frozen method* - if 8.3 is ever empty, the method is being applied rather than improved | done | P1 | - | `ai-self-analysis-research-method.md` |

| CS-107 | **UNANSWERED QUESTION (asked 2026-07-31, user moved on before replying).** Making Measure DIRECT-PICK (round 10, `set_auto_accept`) also changed Distance / Coordinate / BBox: because the FIRST valid construction is delivered immediately, a Measure point can no longer be a CONSTRUCTED point (a midpoint, a projection, an intersection) — only a directly-picked one. Asked whether to keep that simplification or add an explicit "construct a point" escape hatch for Measure. **No answer given.** Keeping it is the status quo and needs no work; the escape hatch would mean a per-mode opt-out of auto-accept | open | P2 | — | round 10; `viewport_panel._arm_measure` |
| CS-108 | **UNANSWERED QUESTION (asked 2026-07-31, user moved on before replying).** Should the **Source Editor** also offer **Transform** on a folder? Today Transform is a MAIN-WINDOW command only (the Source Editor's menus are Add Child / Rename / Delete / Reset / Edit Bodies / Show-Hide). Since round 7 a folder's transform is STORED in the structure map — the Source Editor's own data — which is what prompted the question. My recommendation was to leave it out (one command in one place); the user asked where the command lived and then moved on | open | P3 | — | round 7-8; `main_window._start_transform` |
| CS-109 | **User DATUMS are not hit-testable in the 3D VIEWPORT — panel-only picking.** Round 8 wired `DatumsPanel.pickRequested` so a row CLICK feeds the active command, which is the only way to pick one. Their actors are created `pickable=False`, and the SF's viewport datum resolvers (`datum_origin_point` / `datum_edge_infos` / `datum_plane_hit` / `_resolve_datum`) still consult ONLY the fixed global-origin six. Clicking a user datum in the 3D view does nothing. Deliberately scoped out of round 8 rather than silently extended | open | P2 | — | round 8; `Reference/selection-and-cgb.md` (user-datum layer) |
| CS-110 | **Edit-capture compensation gap: an ANCESTOR FOLDER's transform can be missed.** `_accum_transform_source` finds transforms by tree PATH; restructure-folder transforms are keyed by folder id and are found only via the `provenance["path"]` that `_apply_folder_transform` stamps on them. So a folder that has NO transform of its own cannot be path-resolved synchronously (`folder_key` lives on the PLANNED tree, not on `Component`) — if such a folder has an ANCESTOR FOLDER that IS transformed, that ancestor is missed and a ReOrigin on it would be under-compensated. Narrow, but it is the one hole left in the otherwise order-independent capture. **FIXED round 18** — and it was NOT narrow: live-hit on testB2's `/Lid`, whose transform carries `provenance: {}`. Three closures: (1) `_origin_target_path` prefers `self._origin_cid`, the node whose ReOrigin window is open — authoritative, no stamp needed; (2) `restructure.folder_tree_path(smap, fid)` DERIVES the path from the folder chain (`parent` = `""` root / `"nK"` folder / `"/path"` carried node), used as a fallback everywhere a stamp is read; (3) an unstamped entry is therefore never dropped again | done | P2 | — | round 12 → 18; `main_window._origin_target_path`, `model/restructure.folder_tree_path`; `scratchpad/folder_path_recovery_test.py` |
| CS-111 | **Pending-edit preview moved only the SHADED mesh — edge overlays lagged.** `apply_pending_pose` offset the combined mesh's points only; the feature-edge overlay, tess wireframe and pickable-edge layer are separate world-baked polys and stayed in the BAKED pose, so a moved subtree's edges appeared left behind. Accepted at P3 in round 13 — then **live-reported** (*"edges didn't move, still in the original position"*), which is the correct reading: a wireframe wrapped around where the body used to be says the transform did not take. **FIXED round 17**: one `_posed_points` kernel drives all four layers (per-cell→per-point map for the overlay, tess rebuilt when visible, pick layer moved **and its locator rebuilt**). **PARTLY closed only** — round 20 REVERTED the pick-layer half: posing it corrupted the heap (`0xc0000374`), because `selection_filter._apply_info_mask` wraps its point array zero-copy into every armed subset. The pick layer keeps the baked pose (wireframe lags, hit test resolves to the old position); never write `_edge_pick_mesh.points` | partial | P3 | — | round 13 → 17; `Reference/geometry-edits.md` (deferred bake); `scratchpad/pending_pose_edges_test.py` |
| CS-112 | **Research spec upgraded against the user's own published papers (8 papers in `Documents/McCormick Papers Overleaf`) - spec 299 -> 583 lines.** Structural gaps found by reading their section outlines and closed: **Related Work** (Sec.4 - the first draft reinvented a taxonomy without checking the literature; now cites **DORA**, **SPACE**, Goodhart, **PDSA/action-research** as the closest methodology family, since a conventional paper is one-shot while this is longitudinal and self-revising); **Gaps & Contributions** paired explicitly (Sec.5.1, restated each iteration so contributions that FAILED get marked rather than dropped); **Experimental Setup distinct from Procedure** (Sec.7 - the papers split three ways where the spec split two; records repo state, window, **model version**, tool versions, apparatus in force, and **task mix**, the dominant confounder that lets a future reader REJECT an invalid comparison); **Method Limitations** + **Generalizations** (Sec.11); **Definitions** (Sec.1.1); and from farahani-2023 specifically: **Motivation / Scope / Organization** (Sec.1.2-1.4) and a **finding-screening funnel** (Sec.6.6, S1-S6, modelled on systematic-review inclusion/exclusion staging - **most observations should be discarded on purpose**, and the discard counts are themselves a finding: a window where everything survives means the screen is not working), plus **Guidelines** and **Vision** as distinct from actions (Sec.10.4-10.5 - a guideline is standing guidance that outlives the iteration and accumulates across the series). Honest note: the analyst here inhabits the system being measured, so **self-report bias is structural, not incidental** - a departure from every paper's situation | done | P1 | - | `ai-self-analysis-research-method.md` |
| CS-113 | **[SUPERSEDED IN PART by CS-114 - the two-file snapshot scheme it describes was replaced by a single self-contained report]** **Report identity + provenance + citation policy added (spec Sec.0/0.1).** **Series ID** scheme so iterations link and so a SKILL correlates with every report it generated (there will be more research skills sharing `AI/Research/reports/`): Report ID = `<SERIES>-<ITER>` e.g. `AIRETRO-003`; filename `<ID>_<YYYY-MM-DD>_<slug>.md`; matching snapshot stem. Front matter carries `series`, `iteration`, `generated_by`, **`skill_sha256`**, `skill_snapshot`, **`previous_report`** (a backward chain walkable to iteration 1 without a directory listing), `snapshot`, `window`. **Cross-report references use the Report ID, never a filename or date** - filenames can be corrected, IDs cannot. A **series register** table now lives in `AI/Research/index.md`; a new research skill gets a NEW series. **New procedure step P11: copy the generating skill's file VERBATIM into Appendix D and record its sha256** - not a summary and **not a link**, because a link resolves to whatever the skill has since become, which is exactly the failure being prevented; two reports can then be compared knowing whether the method changed between them. **Sec.0.1 citation policy is the strictest rule in the method**: primary sources first, **a probe is a source** (name the command and its output), mark unverified claims ❓, cite internal artifacts too (numbers cite their snapshot, decisions cite their `CS-###`, prior findings cite their Report ID), inline links or section-local footnotes with superscript markers, and **over-cite by default**. Rationale recorded: the first attempt asserted headless rendering was impossible, **uncited**, and that one unsourced claim suppressed a whole capability for weeks | done | P1 | - | spec Sec.0, Sec.0.1, P11-P12; `AI/Research/index.md` |
| CS-114 | **Research spec hardened: metrics embedded, folders capitalized, method-delta section added, and 13 procedural defects fixed across two audit passes** (spec 646 -> 784 lines). **(a) ONE self-contained report, no snapshots directory** - the earlier canonical-`.json`-plus-embedded-copy scheme was wrong; the argument for it (*a script would have to parse markdown*) does not hold, since recovering a delimited fenced block is a few lines of code. Metrics now live only in **Appendix E**, schema specified in Sec.0.2.1 incl. a **`perishable`** key list naming the values that cannot be recomputed later. **(b) Folder names are nav labels** -> `Reports/` capitalized, convention recorded in `AI/index.md` for the whole tree. **(c) NEW Sec.0.3 method delta** - required from iteration 2: skill hash then vs now, each change with its reason and originating Sec.10.3 recommendation, and critically **which metrics the change makes DISCONTINUOUS** (if a definition changes, its delta across that boundary is meaningless - a '20% improvement' may be pure counting artifact; adding the screening funnel mechanically reduces finding counts). Read in series order these sections are **the changelog of the method itself**. **(d) NEW Sec.0.4 errata** - the ONE permitted post-write edit is an append-only `superseded-by` pointer under the front matter: add only, never alter, name the superseding Report ID, state what is wrong but not the corrected value. Preserves the content's immutability while fixing the reader's problem. **(e) NEW Sec.3.1 series stopping rule** - a series that cannot end becomes a ritual; terminates on two consecutive action-free iterations, all RQs answered/retired, a static subject, or cost > value. **(f) NEW Sec.6.7 deferred-findings register** - a DEFERRED drag finding no longer evaporates; **deferred three times is itself a finding** (either the indicator does not affect outcomes here, or the outcome metric that would reveal it is missing). **(g) NEW Sec.8.2/8.3** - ownership table (user invokes and commits, agent executes) and an explicit validation-cannot-pass path: **abort the iteration and write nothing rather than freeze a report missing its provenance**, because that looks authoritative and cannot be interpreted later; never lower the standard to let a report through. **(h) Procedure rebuilt P0-P16**: ID assigned FIRST (filename and front matter depend on it - it was previously assigned after the report was written); `derive_metrics.py` precondition + its own hash as `derive_version`; empty Developer Log recorded as an explicit **DATA GAP** with RQ2 marked unanswerable so an absent log never reads as zero interventions; iteration-1 branches on the two steps that need a baseline; **P15 validate-before-freeze**; metric/finding retirement given a step (P14). **(i) Funnel de-duplicated** - it restated classify+gate, which are P6/P7, so two authorities existed for one decision; it now cites them. **Audit method: a scripted re-review checking all 9 reported defects plus 11 regression classes** (step numbering contiguity, appendix production-vs-heading, Sec.-reference resolution, P-step reference resolution, funnel stage contiguity, immutability consistency); it caught a **dangling Sec.8.3 reference** left by an earlier renumber, now repaired. All checks pass; one reported 'gap' was a false negative in the checker's own regex | done | P1 | - | `ai-self-analysis-research-method.md` |
| CS-115 | **Research spec: front-matter declutter, iteration semantics, and series declared LINEAR; plus a real flush-gate bug fixed.** **(a) Removed `skill_snapshot` and `metrics` from the front matter** - both were the constant strings `"Appendix D"`/`"Appendix E"` in EVERY report, so they carried zero information and located things that are trivial to locate. **Rule established: front matter carries what a machine needs to index a report WITHOUT reading its body, and nothing that is a fixed pointer into that body** - if the answer is the same in every report it belongs in the spec. Each surviving field now has a justification; notably **`skill_sha256` is kept as an INTEGRITY CHECK on Appendix D, not a locator** (detects a tampered/truncated appendix, and makes "did the method change?" a string compare instead of a re-hash), and `series`/`iteration` are kept DESPITE being derivable from `report_id` because an explicit field survives an ID-scheme change where string-splitting breaks. **(b) Sec.0.0.1: `iteration` IS a plain monotonic gap-free sequence**; the word *iteration* is kept over *sequence* because each run re-asks the same stable RQs and grades the prior run's predictions - meaning a sequence number does not carry. **An aborted run (Sec.8.3) does NOT consume a number**, or gaps appear and "iteration 5" stops meaning "the fifth time this was done", which is the number's only property. **(c) Sec.0.0.2: series are LINEAR - no branching, no merging, deliberately.** A merge is unrepresentable (`previous_report` is single-valued) and two reports sharing a predecessor would collide on `iteration`. All four apparent needs are already covered more cheaply: different methodology -> **Sec.0.3 method delta** (a branch would obscure what the delta clarifies); different subject -> **a new series**; combine findings -> **cross-series citation by Report ID**; supersede wholesale -> **close the series (Sec.3.1)**. Verdict: **not worth building** - multi-parent chains bring ambiguous numbering, a which-branch-is-authoritative question, and merge semantics nothing needs; cost certain, benefit speculative. **Zero-cost door left open:** IDs are stable and never reused, so if branching were ever required the migration is making `previous_report` a LIST and treating existing values as one-element lists - a backward-compatible field change, not a redesign, which is exactly why not building it now is safe. **(d) BUG FIXED in the flush gate:** `precompact-gate.sh` documented that SessionStart does not re-stamp the marker on `source=compact\|resume`, but `settings.json` had **no matcher**, so it fired on every source and DID re-stamp - meaning a post-compaction session had its flush evidence erased and the next manual `/compact` blocked a session whose docs were current. Added `"matcher": "startup\|clear"` so the comment and the behavior agree. Re-tested: blocks with no doc newer than the marker, allows after a doc is touched | done | P1 | - | spec Sec.0; `.claude/settings.json` |
| CS-116 | **Third audit pass on the research spec - 5 real defects found and fixed, plus 3 false positives traced to my own checker.** Probed NEW issue classes the earlier checker did not cover (structural coherence, duplicated normative content, inter-section logical conflict, procedure completeness, cross-file consistency). **Real defects: (1) orphan section numbering** - `0.0.1`/`0.0.2` had no `0.0` parent; the whole Sec.0 subtree was renumbered via placeholders to `0.1`-`0.6` (+`0.4.1`) with every cross-reference updated. **(2) The report-template range claim was wrong** - it said "sections 1-13" while Sec.0.5 is explicitly required report content; now states **Sec.0 + Sec.1-13**, with Sec.0 carrying identity/provenance/method-delta/errata. **(3) A procedure step cited a SPEC-ONLY appendix** - P2's precondition pointed at Appendix B (game plan), which will not exist in a report; now points at Sec.8.3's abort path. **(4) Success criterion vs stopping rule conflicted silently** - Sec.3 needs three iterations to be testable, but Sec.3.1 could close a series after two action-free ones, ending it before it could answer its own question. Fixed with an **iteration >= 3 floor** on that rule, plus an explicit "**if a series closes before the criterion could be evaluated, record it as *criterion not met*, NOT as success**". **(5) I deleted a legitimate admonition title** with an over-broad regex while removing a supposedly stale `skill_snapshot` reference - the occurrence was the note EXPLAINING the field's removal. Restored. **False positives, all in my own audit tooling, now corrected so future runs are trustworthy: (a)** the heading regex was not fence-aware, so a worked example inside a ```markdown block registered as a duplicate section number - the checker now strips fenced blocks before counting headings, and gained a real duplicate-number test; **(b)** the staleness test flagged a removed field named in its own removal note - narrowed to match its use AS A FIELD (`skill_snapshot:`); **(c)** two checks referenced pre-renumber headings and phrasings I had not used. **Lesson worth keeping: when an audit disagrees with the artifact, verify which one is wrong before editing the artifact** - acting on false positive (5) caused the only content damage in this pass. Final state: audit-2 23/23, audit-3 23/23, doc validator clean | done | P1 | - | `ai-self-analysis-research-method.md`; audit scripts in `scratchpad/` |

| CS-117 | **FIXED: the doc-flush gate was broken for CONCURRENT AGENTS in one repo.** The old design compared doc mtimes against a single shared `.claude/.session-flush-marker`, which fails in **both** directions with two agents: **(a)** agent A writes a doc, so agent B's gate passes and **B compacts having flushed nothing of its own**; **(b)** agent B starts later and re-stamps the shared marker, so **A's earlier writes stop counting and A is blocked despite having flushed**. The shared `.skip-flush-gate` had the same class of bug: whichever agent compacted first consumed the other's bypass. The mtime heuristic also credited writes made by editors and linters as if the agent had made them. **New design: per-session, attributable evidence.** New `PostToolUse(Write\|Edit\|NotebookEdit)` hook `.claude/hooks/flush-mark.sh` sets `.claude/.flush/<session_id>.wrote` when **this** session edits `CLAUDE.md` or anything under `docs/src/AI` (narrow on purpose: editing `src/` or `scratchpad/` is not flushing decisions). The gate checks only its own session's flag, extracting `session_id` from the hook payload with `sed`, and the bypass is now `.claude/.flush/<session_id>.skip`. **The mtime comparison and the shared marker are gone entirely** because the flag is exact and needs no inference. Stale flags pruned after 14 days; `.claude/.flush/` gitignored; obsolete shared files deleted. **Deliberately left repo-global: the `Stop` drift warning** - *is this repo's `src/` newer than its docs?* is a genuinely global question; with concurrent agents it may warn about the other agent's edits, which is noise rather than error. **Verified by simulating two agents:** A writes a doc -> B's compact BLOCKED and A's compact ALLOWED; B's skip consumed by B with A's flag untouched; an edit to `src/main.py` sets no flag | done | **P1** | - | `.claude/hooks/flush-mark.sh`, `precompact-gate.sh`, `settings.json`, `precompact/SKILL.md` |
| CS-118 | **BUILT: `docs/derive_metrics.py` + `AI/Research/developer-log.md` - the two prerequisites that blocked a first research iteration.** The script emits the tier 1-4 metrics object that becomes **Appendix E** of a report: tier 1 git (commits, insertions/deletions, **rework rate**, src LOC/files, hub lines, **instruction density**, HEAD, dirty count), tier 2 `status.md` (CS totals by state, max id, next-id, and **duplicate-id / gap detection** - both have been real defects here), tier 3 filesystem (doc count, **orphan** and >90d-stale lists, unpromoted probe count, test-file count, plus per-doc inbound links / age / lines), tier 4 test outcome. **Design decisions:** it **does NOT run the test suite** - a metrics script with side effects cannot be safely re-run for verification, so it reads a recorded result and reports `source: null` when absent; it emits its **own sha256 as `derive_version`** so a number is always paired with the code that produced it; **human-authored tier-5/6 fields are emitted as explicit `null`** and listed under `human_authored_nulls` (models, task_mix, delivered_items, interventions, best_practice, capability_added, funnel) so a missing value can never masquerade as a measured zero; and a **`perishable`** key list names what cannot be recomputed later. Placed at `docs/` beside `generate_screenshots.py`, deliberately OUTSIDE `docs/src/` so mkdocs never copies it into the site. **First real run:** src 38,777 LOC / 71 files, rework rate **15.8%**, **instruction density 3.8 per 1k LOC** (down from a peak of 132 - the restructure's effect quantified for the first time), 30 AI docs with **0 orphaned and 0 stale**, **97 unpromoted probes vs 1 test file**, ledger clean (117 items, no dupes, no gaps). **Developer log created with its first entry** (7 interventions, agent-drafted with verbatim triggering quotes, `felt like` left **unconfirmed** because only the user can author it, confidence **low** and flagged as almost certainly an undercount since it was drafted retrospectively by the party being measured). Also recorded: this window's **task mix is heavily skewed to docs/infrastructure**, so its rate metrics are NOT comparable to a feature window | done | P1 | - | `docs/derive_metrics.py`, `AI/Research/developer-log.md` |
| CS-119 | **PRECOMPACT FLUSH 2026-07-31 - session state, and the one gap the per-turn flushes missed.** This session recorded decisions per-turn (CS-101..CS-118), so the ledger was already current; the skill's step-3 check found the real omission: **`src/` DID change this session** (new `src/gui/fonts.py`, `src/gui/theme.py`, `src/__entrypoint__.py`; edited `src/main.py`) and **none of the new modules appeared in any `Reference/*.md`** - the living-documentation rule had silently not fired because attention was on the Scratch/spec work. **Now synced:** `Reference/architecture.md` documents `fonts.py`/`theme.py` as Qt-only leaf modules (why fonts are vendored - Qt's `offscreen` platform ships **zero font families on Windows**; and that `theme.py` is used ONLY by the test harness and screenshot generator because **the app follows the OS colour scheme**); `Reference/packaging.md` documents the bundled `resources/fonts` data, the frozen-vs-dev path resolution, and the **do-not-modify-the-ttf** OFL constraint. **UNCOMMITTED STATE: 49 paths, 29 of them under `src/`** - the large pre-existing build plus this session's additions (`docs/src/AI/**` tree move, `tests/`, `pyproject.toml`, `packaging/`, vendored fonts, 3 skills, 4 hooks, `docs/generate_screenshots.py`, `docs/derive_metrics.py`, `docs/src/AI/Research/**`). **Still PENDING and unchanged by this session: all live-GL / interactive verification** - offscreen capture is proven but camera feel, depth peeling and hover still need the user. **UNANSWERED questions carried forward:** (a) the `felt like` field and confirmation of the 7 intervention types in `developer-log.md` - only the user can author them; (b) CS-043 teleport-vs-setpoint shadow decision (deferred past 2026-10-01); (c) Q6 blender-renderoff repo access; (d) MTConnect standard access. **NOT recorded, deliberately:** no `Reference/` edits for the 25 `src/` files modified in earlier sessions - those predate this session and their docs were already written | done | P1 | - | `Reference/architecture.md`, `Reference/packaging.md` |
| CS-120 | **AI-RETROSPECTIVE PREREQS: 4 metric defects fixed, tier 4 wired, and the method's self-contradiction resolved (user-approved 2026-07-31).** A from-scratch re-analysis before a first report run found the spec forbade its own first iteration and the metrics script was reporting wrong numbers. **(1) Appendix D now embeds the *authority that produced the report*, not necessarily a skill.** P12 + §8.3 required Appendix D = the generating skill verbatim and **aborted** when no skill file existed - while Appendix B phase 3 requires iteration 1 to be written BY HAND before the skill is built (so the skill encodes an executed procedure, not a guess). Fix: `generated_by: manual` embeds **the spec file** verbatim; `skill_sha256` renamed **`method_sha256`** (it hashes whichever authority was used); '`no skill file`' removed as an abort condition; a **manual->skill transition is an authority-kind change** that §0.5 must declare and that makes every metric suspect across the boundary. **(2) `rework_rate_pct` renamed `churn_ratio_pct`** - §1.1 defined rework as deletions *of lines added in the same window* (needs line-level blame) but the code computed ALL deletions / ALL insertions. §1.1 now carries both terms: rework = the concept, churn ratio = the measured proxy that **over-reports** it. Renamed while ZERO reports exist - the only free moment. Two distortions documented: file **moves** inflate it (now mitigated with `git log -M`) and **untracked** work contributes nothing. **(3) tier-2 parser silently dropped 5 of 119 `status.md` rows** - 4 with **bold** states (`**deferred**` CS-043/046, `**done**` CS-051, `**superseded**` CS-085) and CS-021's undeclared `live-test-pending`. `done` read **39 when it was 40**; anything derived from it was wrong with no sign. Rewritten to anchor on the `\| <state> \| P<digit> \|` pair (**positional column splitting is unsafe** - several descriptions contain a literal `\|`, e.g. `Write\|Edit\|NotebookEdit`), taking the LAST match per row, stripping emphasis, and hardcoding **no** state vocabulary so an undeclared state appears in the tally instead of vanishing. New `cs_state_tallied` + `cs_state_unparsed` make the invariant checkable: **tallied must equal cs_items_total**. **(4) `tools.python` reported the interpreter that ran the script** (3.13.14 system) not the project's pinned 3.12 - now emits `python_project` (parsed from `packaging/environment.yml`) AND `python_running_metrics`. **(5) `apparatus` was 3 skill names**; now `{skills, hook_events, runnable_check}` with hook events read from `settings.json` - counting files in `.claude/hooks/` under-reported by half (2 of 4 events are inline commands). **(6) tier 4 populated:** new `pytest_sessionstart`/`pytest_sessionfinish` in `tests/conftest.py` write `tests/_artifacts/last-run.json` (passed/failed incl. collection errors/skipped/xfailed/duration/exit status/platform/QT_QPA_PLATFORM), entirely inside one `except Exception: pass` so bookkeeping can never turn a green run red. The metrics script still **never runs the suite** (a script with side effects cannot be re-run to verify its own number). Gitignored -> `drag.tests` stays **perishable**. **(7) §0.4.1 regenerated from real output** - the hand-written schema had drifted (`docs.total` vs emitted `docs.docs_total`, phantom `tools.claude_code`, phantom `tests.{passed,failed,duration_s}`), which breaks P5 because it diffs **by key**. **Verified end-to-end under CellSmithEnv:** 8 tests pass, `119 == 119` tallied with `[]` unparsed, `done` now 40, both python fields correct, tier 4 reading 8-passed, churn 15.8%, doc validator ALL CLEAN (also fixed a **ragged Appendix-B table** - a stray 4th `**DONE**` cell in a 3-column table; the table now has a real Status column, phases 0+1 done). **Placement decisions (user asked, answered NO-CHANGE):** `developer-log.md` **stays** at `Research/` root - the immutability boundary already falls at the folder line (`Research/Reports/` frozen, `Research/` root live), a one-file `Data/`/`Input/` folder is premature, and the path is cited in 3 places; **revisit only if a second human-authored input appears**. Ownership is **split** per §8.1 (agent drafts count + verbatim quotes + capabilities; user authors *felt like* + confidence + confirms type). **mkdocs premise corrected:** `Research/` is NOT hidden - only `AI/Reference/` is pruned (`mkdocs.dev.yml` `nav_exclude`), and all of `AI/` is excluded from the PUBLIC build; no nav change needed | done | P1 | - | `docs/derive_metrics.py`, `tests/conftest.py`, `Scratch/ai-self-analysis-research-method.md`, `Research/index.md`, `Reference/testing.md` |
| CS-121 | **STILL OPEN before a first `AIRETRO-001` run** - **(a) window, (c) alignment audit and (e) hygiene are RESOLVED by CS-122; (b) and (d) remain, both USER-OWNED.** Original entry (from the same 2026-07-31 re-analysis). **(a) The window is empty of commits.** Last commit `34062bb` **2026-07-27**; `git log --since=2026-07-27` returns **0 commits**, so every windowed tier-1 metric is `null`. The uncommitted-tree fallback is WORSE, not better: `git diff --numstat HEAD` gives 3,223 ins / **5,463 del** (churn 169%, an artifact of the doc-tree MOVE) and the **22 untracked paths contribute nothing** (`tests/`, `derive_metrics.py`, the whole moved `AI/` tree). `-M` changes nothing because the moves are uncommitted. **Proposed, NOT yet approved:** iteration 1's window = 2026-07-09 (inception) -> report date, churn computed over **committed history only** (15.8%), uncommitted tree declared an explicit DATA GAP, plus a §11.1 limitation that this repo commits rarely so windowed churn will often have n=0 - making iteration 2's windowed figure **discontinuous** against iteration 1's lifetime figure. **(b) `delivered_items` has no derivable source** - §1.1 fixes it at one completed `CS-###`, but `cs_by_state` is a LIFETIME tally and `status.md` has no per-item completion date, so a windowed count needs either the user's hand count or a new date column. **(c) P4 alignment audit (tier 6) not run** -> RQ5 unanswerable; needs the published Claude Code best-practices doc fetched. **(d) Developer-log fields are USER-OWNED and unwritten**: *felt like*, *confidence*, and confirmation of the 5 intervention types on the 2026-07-31 entry (note: that entry has **7 interventions across 5 types** - an earlier note miscounted this as '7 types'). **(e) Hygiene, deliberately deferred:** `AI/index.md` has **no `Research/` row in its Layout table and no `Research/` block in its Index** (`Scratch/Pipeline/` is unindexed too); `garden-claude-docs`' scope table has **no row for `AI/Research/**`**, so nothing currently forbids a gardening pass from rewriting an immutable report or the append-only log; and spec **§8.1 is physically located after §8.3** | open | P2 | user + agent | `Scratch/ai-self-analysis-research-method.md`, `AI/index.md`, `.claude/skills/garden-claude-docs/SKILL.md` |
| CS-122 | **DONE 2026-07-31 (user-approved): empty-window rule, the SEED ALIGNMENT AUDIT, and the deferred doc hygiene - clearing 3 of the 5 blockers in CS-121.** **(1) B2/B10 window rule encoded.** Iteration 1's window = **inception -> report date**, tier 1 over **committed history only**, figures labeled **lifetime** not windowed. New `!!!danger` block in Sec.8 makes the forbidden fallback explicit: **never substitute a working-tree diff for a commit window** - measured here `git diff --numstat HEAD` gives 3,223 ins / **5,463 del** = **169% churn** purely because a tree REORGANIZATION reads as mass deletion, while the **22 untracked paths contribute nothing** (so `tests/`, `derive_metrics.py` and the entire moved doc tree are invisible). A number that is both inflated AND incomplete is worse than a declared gap. P2 now says 0 commits -> every tier-1 metric `null` + a stated DATA GAP + RQ1 unanswerable; Sec.1.1 + Sec.7 carry the iteration-1 case; new Sec.11.1 limitation records that **work done but not committed is invisible to every tier-1 metric**; iteration 2's windowed churn is **discontinuous** against iteration 1's lifetime churn. **(2) P4 SEED AUDIT RUN** against the fetched primary source (`code.claude.com/docs/en/best-practices`, 2026-07-31) -> new `AI/Research/alignment-audit.md`, append-only, one dated section per audit; Sec.6.4 tier 6 and P4 now name it, and reports still embed their own tier-6 table so they stay self-contained. **Result: 5 aligned / 3 partial / 5 diverged / 0 rejected.** Aligned: hub size (149 lines, density 3.8 vs peak 132), skills-over-always-loaded-context, hooks-for-must-happen, **compaction customization in CLAUDE.md** (the docs prescribe exactly what this repo does), evidence-over-assertion. Partial: **a runnable check exists but covers 1 of 71 source files with 98 probes unpromoted** - it closes the loop on the harness, not the product; explore/plan/code practiced but **5 of 14 commit messages are the single word 'updated'**; CI intent documented, no workflow checked in. Diverged: **no `/clear` discipline** (this session ran fonts -> screenshots -> tests -> doc move -> research method in ONE context through 2 compactions and 7 interventions - the docs' own term is *the kitchen sink session*); **subagents refused with no recorded rationale** (so it scores `diverged`, not `rejected`); **no adversarial fresh-context review** - the agent that writes is the one grading, which Sec.4 already flags as STRUCTURAL self-report bias; **concurrent agents share ONE working tree with 49 uncommitted paths** (2 live session flags observed) where the docs prescribe git worktrees; no permissions allowlist. **`0 rejected` is itself the finding**: 5 divergences and not one recorded rationale means the repo never DECIDED against this guidance, it just hasn't done it. Per the Sec.P7 gate **none justify action yet** (no outcome metric is degraded - the A5 doc-deletion near-miss is the precedent); flagged as cheaper-to-fix-than-measure: the shared working tree (data-loss risk, fix is one `git worktree` call) and recording the subagent rationale. Confounder recorded: the window is almost all docs/infra, inflating the hub/skills scores and depressing the test/commit ones. **(3) Hygiene:** `AI/index.md` gained an `AI/Research/` Layout row, a full `Research/` index block, a `Scratch/Pipeline/` block, and `Research/*.md` in the audience table; `Research/index.md` now states the **folder boundary IS the immutability boundary** (`Reports/` frozen, root live) + split ownership; **spec Sec.8.1 moved before Sec.8.2** (it sat after Sec.8.3) with a length-preserving assert; and `garden-claude-docs` gained 3 scope rows - `Research/Reports/**` **NEVER EDIT** (immutable), the two logs **APPEND ONLY** with *never author the felt-like field*, `Research/index.md` editable. Doc validator ALL CLEAN across 8 files | done | P1 | - | `AI/Research/alignment-audit.md`, `Research/index.md`, `AI/index.md`, `Scratch/ai-self-analysis-research-method.md`, `garden-claude-docs/SKILL.md` |
| CS-123 | **PILOT RUN DONE: `AIRETRO-001` written and P15-VALIDATED** - `Research/Reports/AIRETRO-001_2026-07-31_ai-retrospective.md`, 1,743 lines, `generated_by: manual`, `method_sha256` 4cc3b66a..., Appendix D = the 930-line spec verbatim, Appendix E = the filled metrics. Series register updated. **THE finding: the user's *felt like* - 'flip flopping: fix one thing, another thing breaks' - corroborates audit A6 (1 test file vs 71 source files, 98 unpromoted probes) = regression-without-detection. Two independent sources, one mechanism, and ONLY the human-authored field caught it.** Tagged JUSTIFIED with a stated caveat: no derived outcome has a baseline, so the P7 gate was satisfied by a **tier-5 subjective** outcome - flagged as method defect Sec.10.3-2 to resolve. **The pilot found 6 defects in its own apparatus before producing a number** - most importantly **finding 6: three `derive_metrics.py` runs MINUTES APART gave src_loc 38,837 / 38,914 / 38,875** because a CONCURRENT AGENT was editing `src/gui/viewport_panel.py` + `main_window.py` mid-run. That is audit A11 (shared working tree) materializing INSIDE the measurement. Response: cite a RANGE, add `measurement_stability.tree_stable: false` to Appendix E, and Sec.10.3-6 = pin the tree (fixed commit or `git worktree`) before measuring. **Chasing the number was wrong; recording that it cannot be pinned was right.** Also **NEW unplanned metric - communication density**: average assistant reply grew **40-57 words (2026-07-09..15, code work) -> 160-197 (2026-07-27..28, docs/AI work)**, single reply peak **2,895 words**; user reported it directly ('super dense with content that isn't registering'). Measured from session transcripts, recorded in Appendix E as `drag.communication_density`, and a **6th intervention type `too-dense`** proposed. User notes capacity **varies by day**, so the target must be a user-set DIAL, not a fixed number. Actions with predictions: (A) promote probes -> tests, predict `test_files`>5 and probes<90 and *felt like* stops naming regression; (B) cap reply density, predict avg <=80 words next window; (C) `git worktree` per agent. **Numbers: churn 15.8% lifetime, 14 commits/22 days, density 3.8 per 1k LOC (peak 132), 42 of 122 CS done, 7 interventions (thats-wrong 3 / premature-stop 2 / wrong-framing 2), 8 tests green, funnel 14->9->2->3, alignment 5 aligned / 3 partial / 5 diverged / 0 rejected.** Sec.12 correctly empty (no prior iteration). **Decided: the spec GRADUATES** - once the `ai-retrospective` skill exists the Scratch spec moves into it and is DELETED; its content survives permanently as AIRETRO-001's Appendix D, which is why embedding it verbatim matters | done | P1 | - | `Research/Reports/AIRETRO-001_*.md`, `Research/index.md`, `Research/developer-log.md` |
| CS-124 | **OPEN: response density needs a tunable dial + a metric, and the item-ledger format needs iteration.** User feedback 2026-07-31, verbatim: *'super dense with content that isn't registering with me'*, *'I'm not reviewing every line of the docs you are generating (likewise code)'*, *'I don't have the ability to process broad+deep at the scale that you are throwing at me'*, and critically *'this may also be a temporal thing, where depending on the day I can process more or less context'*. **Measured baseline** (assistant words per reply, from session transcripts): 2026-07-09 **53** / 2026-07-09 **132** / 2026-07-20 **57** / 2026-07-10 **40** / 2026-07-15 **51** / 2026-07-27 **197** / 2026-07-28 **160**; max single reply **2,895 words**. So the recent docs/AI-workflow sessions run **3-4x denser** than the code-building sessions. **Two candidate causes, not yet separated:** the task shifted from code (evidence = a diff) to design (evidence = prose), AND the item-ledger format mandates re-rendering scaffolding every turn. **What is NOT yet decided:** the dial mechanism (a per-turn depth setting? a standing default with opt-in expansion? a short-form ledger variant?), where the rule lives (`~/.claude/CLAUDE.md` owns the ledger format - editing the user's GLOBAL file needs explicit approval), and the target (fixed vs user-set per day). Recorded as **RQ7** in AIRETRO-001 Sec.13 and as Sec.10.3-3 (add density as a first-class metric + the `too-dense` intervention type). Prediction on record: **avg <=80 words/reply next window** | open | **P1** | user + agent | AIRETRO-001 Sec.9.6, Sec.10.3, `Research/developer-log.md` |
| CS-125 | **FIXED (live-GL verify pending): assembly Edit-Bodies baked the bodies displaced by the target's origin frame.** Live report on testB2's `/Body` asset (a restructure FOLDER marked as an asset, carrying a custom ReOrigin + a Transform in Main): Transform Source → Edit Bodies on the asset root → Apply → the rebake put the whole robot ~4.6 m away and rotated, while the Component Editor had shown it correctly. **Root cause: `apply_splits`' merge-then-edit branch read its geometry from `st.GetShape(product)`, an XCAF CACHE that goes stale after a re-origin's child-location surgery** (`UpdateAssemblies()` does not reliably refresh it — ❓ trigger unexplained, see `occ-vtk-gotchas.md`). The frames were always right (root at identity, each link at its picked origin); the geometry moved out from under them. **THREE fixes, all verified:** (a) `apply_splits`' assembly branch builds the compound from the WALK via the shared `build_assembly_edit_compound` (same helper the window uses), product-local and occurrence-independent — 0 mm on the real asset, and the user's own re-Apply (19:56) confirmed the live asset now matches its source stage exactly; (b) **the underlying OCC defect is now also fixed at source** — `geometry_edits_build.refresh_assembly_compound` force-rebuilds the product compound after the assembly re-origin surgery (called from `apply_origins` + `restructure_build._reorigin_assembly_once`), because the measured rule is that **`UpdateAssemblies()` sees a location change only on a LEAF child, never on an ASSEMBLY child** (`probe_updateassemblies_matrix.py`, 6 cases; free-vs-component root, multi-instancing and a root location make no difference); (c) `_split_face_colors` now keys colors by the SHAPE-MAP INDEX instead of a parallel append list (`Add` no-grows on a duplicate → every later color shifted) — a latent fragility, provably no-op on testB2. **The 30-face color change (a) caused was a CORRECTION**: checked against the color sidecar as independent ground truth, NEW correct 28 / OLD correct 0 / 2 ambiguous (`probe_body_color_truth.py`) — the old `known` map was built over the STALE compound whose face order differed from the walk preorder, and the counts matched so the old drift guard never fired. **Users must re-Apply Transform Source on any asset baked with the old code** (config recipe unaffected). 15 suites green | live-test-pending | P1 | agent | `Reference/geometry-edits.md` (merge-then-edit), `Reference/occ-vtk-gotchas.md`; `scratchpad/assembly_split_stale_compound_test.py`, `assembly_reorigin_compound_test.py`, `probe_body_fast_rebuild.py`, `probe_body_livecheck.py`, `probe_body_vertexbbox.py`, `probe_body_colormap_compare.py`, `probe_body_color_truth.py`, `probe_updateassemblies_matrix.py`, `probe_stale_compound_cause.py` |

| CS-126 | **FIXED (live-GL probe-verified): three Component-Editor Transform defects.** Live report. (a) **The offset fields ROUNDED** — `QDoubleSpinBox` quantises to `decimals()` on `setValue` too, and the pane round-trips a stored `BodyTransform` through them, so re-opening an existing transform degraded it (2 dp on mm, 1 dp on degrees). New `src/gui/num_field.PreciseDoubleSpinBox` (decimals=12, trailing zeros trimmed in `textFromValue`, `C` locale) now backs both the Orient a/b/c and Translate X/Y/Z groups. (b) **No preview when editing an existing transform** and (c) **the translate arrows could not be dragged** — ONE root cause: `_meshes` holds only FINAL bodies, while `_start_edit_op` targets `op.targets[0]`, the op's CONSUMED input body → `_build_xform_preview_actors` returned early (no `_xform_actor` → `_update_xform_preview` short-circuits) and `_refresh_gizmo` hit the `1.0 mm` size floor (sub-pixel arrow vs a 12-px hit gate). New `_display_mesh(lid)` tessellates from `_all_states` on demand into `_aux_meshes` (cleared by `_replay`). Verified `scratchpad/probe_xform_edit_preview.py` (20 checks, real window): exact round-trip, preview actor built when editing, gizmo size identical to a fresh transform (103.9 vs the old 1.0), X arrow hit-testable and a left press claims the gesture. ❓ The CGB bar's own spinboxes quantise the same way — deliberately left alone (not reported; their values come from picks, not a round-trip). ❓ Whether (c) also occurred on a NEW transform is unconfirmed — the probe shows a fresh transform's arrows were already grabbable | live-test-pending | P1 | agent | `Reference/geometry-edits.md` (Component-Editor Transform bullets) |

| CS-127 | **FIXED (live-GL probe-verified): Component-Editor Transform pivoted about the CENTROID and picked on the UN-oriented body.** Live report. (a) **Pivot** — `pivot="origin"` fell back to the body's volumetric CENTROID when the body had no custom origin ("rotated about some random point"); now it falls back to the **component's LOCAL FRAME ORIGIN** (what the editor draws + anchors its datum at), changed in all four places that must agree (`body_transform_world4`, `mesh_slice.body_transform_world`/`_local`, `_gizmo_pivot_world`). ⚠️ **Not backward-neutral** — an existing transform op on a body with no custom origin now bakes differently (that WAS the bug). Companion: the origin lookup now tries the op's INPUT **and** RESULT lid (`_origins`/`recipe.origins` are FINAL-keyed while the op names its input, so a body WITH an origin silently lost its pivot). (b) **Move picks** — the pick view now poses the target by the pending **orient only** (`_render_xform_pick_bodies`; the Move offset is consumed after the orient, and including the translation would double it), draws the CONSUMED INPUT rather than the stale RESULT when editing, and orient-maps an UNPICKED default From-point. (c) **Pick scope** — every body stays pickable during a Transform pick (no hide / body filter / edge exclude) and the command now defaults to **All Bodies** visibility; a From→To move is normally onto ANOTHER body. Verified `scratchpad/probe_xform_pivot_pick.py` (11) + 12 suites/probes green | live-test-pending | P1 | agent | `Reference/geometry-edits.md` (Component-Editor Transform bullets) |
| CS-128 | **NOT a regression — "Create Joint" is gated, not removed. Awaiting the user's call on widening it.** Live report: *"the ability to add joints has disappeared"*. The menu code in `_exec_component_menu` is **byte-identical to HEAD**; it is gated (as designed + documented in `kinematic-joints.md`) on `active_model != MODEL_SOURCE` **and** `target not in implied_root_ids()`. Measured on the real testB2 (`scratchpad/probe_joint_menu_gate.py`): in the **Body asset** every one of `/Base`,`/Link1`…`/Link6` DOES offer Create Joint; the asset ROOT `/` does not; **Main offers it nowhere**. So the open question is whether joints should become authorable on **Main** (a deliberate design decision — joints are export metadata on a GENERATED model, and Main is the pre-split scene) and/or on a model ROOT (currently impossible: the root can't be a rigid body without nesting the articulation root) | **open** | P1 | user | `Reference/kinematic-joints.md`; `scratchpad/probe_joint_menu_gate.py` |

| CS-129 | **FIXED (probe-verified): a re-origin MOVED an already-transformed body in the Component Editor.** Live report — the authoring order should be arbitrary. Cause: the transform op's Orient pivot was resolved at REPLAY time from `recipe.origins`, so adding a body origin retroactively re-pivoted an existing op (363 mm on the fixture) — contradicting `_commit_origin`'s own comment that "origins don't change geometry". FIX: **`BodyTransform.pivot_point`** (new optional field, default-omitted → existing configs byte-identical and reproduce their old result) freezes the RESOLVED world pivot at commit, taken from `_gizmo_pivot_world()` = the point the gizmo draws. `body_transform_world4` + both mesh twins prefer it; `_preload_transform`/`_gizmo_pivot_world` restore it on **Edit** so re-opening an op can't make the body jump either. Same "decide once, then freeze" rule as the main-window `ComponentTransform.pivot`. **ROUND 2 (the first fix did nothing for the live case):** freezing on COMMIT leaves every op authored before the field existed at `pivot_point=None`, still re-resolving — testB2's **Lid** asset has six such transforms, and adding a ReOrigin to `Link2` still displaced it **274.3 mm**. Added **`_freeze_legacy_pivots`** (`EditBodiesWindow.__init__`, before the Reset snapshot): resolves each legacy transform's pivot ONCE with the current rule (needs no geometry, so it is geometry-neutral) and writes it in; Apply persists it. Also, per the same report, the Body Tree now nests the op lineage **under** the `ReOrigin` node instead of beside it (bake order is ops → origins, so the re-origin is last and the ops are its inputs). Verified `scratchpad/body_xform_origin_order_test.py` (5, with a discriminating LEGACY case that still moves) + `probe_lid_link2_reorigin.py` (2, the real Lid asset: 274.3 mm → 0 mm) + `probe_xform_pivot_pick.py` (19) + 16 suites/probes green | live-test-pending | P1 | agent | `Reference/geometry-edits.md` (Transform pivot bullets) |

| CS-130 | **DONE (real-file verified): the composed SCENE now gets the same base/override split as each asset.** User request — persistent settings in `main.usda` must not be overwritten every export. `write_composed_main` writes the occurrences to **`{stem}_base.usda`** (overwritten each time) and the user-chosen file becomes a create-once **override wrapper** referencing it, so scene-level edits (stage metadata, added lights/cameras, per-occurrence `over`s) survive. `write_asset_override_wrapper` → **`write_override_wrapper`** (old name aliased) + a `customLayerData` **stamp** (`WRAPPER_STAMP`) so a **legacy** full-scene `main.usda` — which used to be overwritten every export, so leaving it would make a re-export look like a no-op — is REPLACED via `replace_unstamped=True`. Never set for the ASSET wrappers (theirs predate the stamp and hold real overrides). The GUI completion message names the rewritten vs persistent file, since `QFileDialog`'s "overwrite?" prompt implies the opposite. Chain is now 4 arcs: `main.usda`→`main_base.usda`→`{slug}.usda`→`{slug}_base.usd`. Verified `scratchpad/compose_main_override_test.py` (16) + `probe_testb2_main_layer.py` (8, real testB2: 2022 meshes resolve from `main.usda`, a user edit survives a 2nd full export) + compose/USD suites green | live-test-pending | P1 | agent | `Reference/asset-splitting-and-compose.md` (Export Composed → USD) |

| CS-131 | **FIXED: a restructure Apply WIPED every folder `origin` + `transform` — the root cause of "one Main restructure shredded everything downstream".** `diff_edited_tree` rebuilt each `NewAssembly` from the editor's rows, which carry only `(ident,parent,name)`, so the map-only `origin`/`transform` reset to `None` on EVERY Apply. Evidence (testB2, after one Apply moving `41099-01-060-01-*` into `/MoldTending`): all six folders `origin: null, transform: null`; root bake stamp `folder_origin_frame_paths: []` (was all six) → `asset_root_declares_origin` False → **every** asset regenerated WITHOUT de-rotation → its local frame moved under the authored body origins. FIX = `diff_edited_tree(..., prior=)` carrying them forward by FOLDER ID (stable across rename/re-parent); `TransformSourceWindow._saved_map` supplies it. Verified `scratchpad/restructure_folder_frame_survives_test.py` (8) + 8 suites green. ⚠️ Values already lost are NOT recoverable from the config — re-author. n1/n2/n3's exact values were captured in this session's transcript and can be restored on request | live-test-pending | P1 | agent | `Reference/restructure-and-transform-source.md` (`diff_edited_tree`) |
| CS-132 | **(a)+(b) DONE, (c) still OPEN: Edit-Bodies recipes are keyed by SOLID INDEX + `initial_count`, so any membership change to the target subtree DROPS the whole recipe.** Second, independent defect behind the same live report. `/MoldTending` went from 15 solids (one 15-solid compound leaf) to **141** when the drone was moved in; `initial_count=15` no longer fits, so `apply_splits(tolerant=True)` dropped the recipe — and the drop is only `print`ed inside the generation subprocess, whose stdout the GUI reads **only on failure**, so it is INVISIBLE. Consequence: the asset lost `/Base`…`/Link6`, so its 6 body origins and all **7 joints dangle** (joints are keyed by main-stage path; the config entries survive and would come back if the recipe did). Only MoldTending drifted — the other five recipes still FIT (probe-measured). Three fixes, escalating: **(a)** surface the dropped-recipe report in the GUI (also report dangling joint paths) — small; **(b)** warn at Transform Source Apply time, BEFORE baking, when a move changes the membership of a subtree a generated model's recipe targets — small/medium, prevents the loss rather than reporting it; **(c)** content-addressed initial-body identity (`body_sort_key`'s volume+centroid, or owning-leaf `product_entry` + within-leaf index) so a recipe re-binds across membership changes and reports only genuinely new/missing solids — LARGE, changes the durable `SplitRecipe` format + needs migration + op-target remapping (RED LIST: on-disk format). **(a) SHIPPED** — `_record_drop` → a `drops=` list threaded to `assets_build._emit_warnings`, which prints a `CELLSMITH-WARN <json>` record (model, authored→actual counts, the body paths NOT created, and the exact joints left dangling); `main_window._report_build_warnings` scans stdout on a SUCCESSFUL build and shows a warning. Note the single-model FAST rebuild path was already STRICT and raised loudly — only full Generate swallowed it. **(b) SHIPPED** — `_confirm_recipe_membership_change` plans the OLD vs NEW structure map at Transform Source Apply on Main, BEFORE any write, diffs the base components under each recipe-bearing asset root, and offers Cancel (default). **(c) STILL OPEN** — content-addressed body identity so a recipe re-binds instead of dropping; the user WANTS it, timing TBD. Verified `scratchpad/recipe_drop_visibility_test.py` (15) + `probe_b2_warn_tolerant.py` (3, real MoldTending 15→141, all 7 joints) + 26 suites green. Diagnostic: `scratchpad/probe_b2_restructure_damage.py` | **done** (a+b; (c) split out as **CS-133**) | P1 | agent | this ledger; `Reference/geometry-edits.md` (merge-then-edit) |

| CS-133 | **OPEN (user WANTS it; timing TBD): content-addressed Edit-Bodies body identity, so a recipe RE-BINDS across a membership change instead of being dropped.** The remaining half of the testB2 restructure incident (CS-132 shipped the two guards; ADR-0007 records why warn-don't-rebind is only an INTERIM). **Problem:** `SplitRecipe` names its initial bodies `i0..iN` = indices into `_solids_of(target_compound)` in PREORDER, plus an `initial_count` fingerprint, and every `BodyOp.targets` references those ids. So a recipe is bound to the exact solid SET it was authored on: a membership change to the target subtree either drops the whole recipe (count differs — testB2 `/MoldTending` 15→141) or, worse, a count-PRESERVING change silently re-maps `i*` onto DIFFERENT solids, which nothing detects. **Proposed:** give each initial body a stable content key — `geometry_edits.body_sort_key`'s rounded (volume, centroid) already exists and is the deterministic ordering key, or the owning leaf's `product_entry` + a within-leaf solid index (more robust to a geometry edit, needs the leaf→solid mapping the assembly-edit compound already builds). Then at replay: re-bind surviving keys, report NEW solids as extra un-merged bodies and MISSING ones per-body, and only drop the ops whose inputs genuinely vanished. **Scope (why it is not a slot between bug fixes):** (1) durable format change to `SplitRecipe` + a migration for every existing recipe (index ids → content ids) — RED LIST: on-disk format; (2) `run_body_ops` / `run_body_ops_mesh` replay both re-keyed, plus `replay_ids`/`working_before`/`ordered_final_ids`/`_prune_ops`; (3) op targets, `names`, `origins`, `body_order` all keyed by lineage id → all need remapping; (4) `split_stub_assembly`'s synthetic entries and the planner's expectations; (5) the Component Editor's Body Tree + Edit-Merge candidate logic; (6) re-verify every merge/split/transform/delete suite AND the mesh twin. **Estimate:** multiple days, wants its own window. **Decide with:** how often re-grouping happens after rigging (the metric the user is deliberately gathering) — see ADR-0007's Revisit-if | open | **P2** | user | ADR-0007; `Reference/geometry-edits.md`, `Reference/invariants.md`; diagnostic `scratchpad/probe_b2_restructure_damage.py` |

| CS-134 | **FIXED: "Pick Color" blanked the entire app.** Live report — clicking the color picker's screen eyedropper made *"all CellSmith windows close"*. Cause: `color_picker._on_pick_screen` faded `parentWidget()` to `setWindowOpacity(0)` so the chooser would not appear in the frozen capture — but EVERY caller passes a `QMainWindow` as parent (MainWindow's Override Body Color, the Component Editor's Cut Surface Color, and via Recolor), so the whole app went invisible. It also defeated the eyedropper's most natural use: sampling from CellSmith's OWN viewport, which is impossible if the viewport is not in the capture. FIX = `_windows_to_dim()` dims THIS dialog plus any ancestor **`QDialog`** only, never an application window — the Recolor flow still gets its chooser hidden (`RecolorDialog` is a QDialog); plus the deferred launch now RESTORES opacity if the grab throws (a dialog left at opacity 0 is indistinguishable from a closed one). Verified `scratchpad/color_picker_dim_test.py` (11, offscreen: window-parent not dimmed, dialog-parent dimmed, parentless case). **USER-CONFIRMED 2026-08-04** ("10) good") — the fix is accepted on a real screen; nothing outstanding | done | P2 | agent | `Reference/node-state-and-color.md` (unified color picker) |

| CS-135 | **SESSION STATE — compaction-critical facts.** ⛔⛔ **READ `CS-156` FIRST: EVERY COMMIT SHA IN THIS ENTRY IS DEAD.** The history was rewritten some time after 2026-08-04; `eafad8e` and `34062bb` no longer exist in the object store (`git cat-file -t` fails on both) and the repo is now two commits (`23e7c8d`, `7353006`) on branch `feature/init`. The *file lists* below remain useful as a record of what that work touched; the SHAs and the "working tree is completely clean" claim do not. ⛔ **THE GIT-STATE PART OF THIS ENTRY IS SUPERSEDED: on 2026-08-04 the user COMMITTED EVERYTHING as `eafad8e` ("updated", on top of `34062bb`) — 132 files, +33258/-5450, and the working tree is now COMPLETELY CLEAN (`git status --porcelain` = 0 lines).** That single commit landed the entire long-running uncommitted build *plus* this session's work: `.github/` (2 workflows + `verify-payload.sh` + `find-iscc.ps1`), `packaging/debian/` (5), `packaging/licenses/` (7), `gen_third_party_notices.py`, `environment.yml`, `tests/test_{packaging_spec,third_party_notices}.py`, the `.claude/skills/flush/` rename, 40 files under `docs/src`, and 35 under `src/`. **So "everything is uncommitted" is no longer true of this repo — do not repeat it.** The file list below is retained only as the record of WHAT that commit contained. **(1) WAS UNCOMMITTED (now in `eafad8e`):** HEAD is still `34062bb`; 56 dirty paths. `src/` modified: `export/{compose_cli,usd_writer}.py`, `gui/{color_picker,construction_geometry,edge_pick,edit_bodies_window,main_window,model_tree_panel,origin_window,sel_icons,selection,selection_filter,transform_source_window,viewport_panel}.py`, `io_mesh/mesh_slice.py`, `io_step/{assets_build,geometry_edits_build,restructure_build,writer}.py`, `main.py`, `model/{geometry_edits,restructure,scene_config}.py`. `src/` NEW/untracked: `__entrypoint__.py`, `gui/{cgb_command,cgb_core,cgb_features,cgb_filters,cgb_recipes,datums_panel,fit_primitives,fit_primitives_worker,fonts,num_field,theme}.py`, `resources/`. **`gui/num_field.py` is new THIS session** (CS-126). Plus all of `docs/` and `CLAUDE.md`. **(2) LIVE-GL STILL PENDING** (dev env has no GPU; offscreen + real-windowed probes only): every Component-Editor Transform change (CS-126/127/129) — the arrow drag FEEL, the oriented pick view, the gizmo at the origin; the composed USD base/override pair opened in **Isaac/usdview** (CS-130); the "Pick Color" FROZEN CAPTURE appearance (CS-134 — the offscreen test proves the right window is dimmed, but whether the compositor settles the 150 ms opacity before `grabWindow` needs a real screen); the CS-131/132 guards exercised through the real GUI. **(3) testB2 CACHE/BAKE STATE as measured:** Main fresh (`main_rebuild_required` False), `assets_up_to_date` True, Static main present, 6 asset variants on disk. BUT the CONTENT is damaged: all six folders `origin: null, transform: null`; root bake stamp `folder_origin_frame_paths: []`; `asset-MoldTending` main is the raw 126-component subtree (its recipe drifted 15→141 and was dropped) so its 7 joints dangle; the other five recipes still FIT. The user separately re-baked `asset-Body` main (19:56) and the Lid recipe now carries migrated `pivot_point` values. **(4) RECOVERY PROCEDURE + the only copy of the recoverable folder-frame values:** `Scratch/testb2-folder-frame-recovery.md` (n1/n2/n3 exact; n4 fragment only; n5/n6 must be re-authored). **UPDATE 2026-08-04 (next session, after a compaction; all of it now committed in `eafad8e`):** no `src/` file changed in that session — the only tree delta was `packaging/cellsmith.spec` (CS-138), `Reference/{packaging,invariants}.md`, this ledger, and the new gitignored probe `scratchpad/spec_paths_test.py`; the 56-path list above still stands. `dist/` was REGENERATED by a full `build.bat ci` (CellSmith.exe + `-win64.zip` 494 MB + `-setup.exe` 294 MB, v0.1.0-alpha.1) — gitignored, but it means the on-disk `dist/` now matches the working tree rather than HEAD. The user CONFIRMED CS-134 and CS-138 on a real machine ("10) good", "11) good"). ⭐ **2026-08-04 RE-CLASSIFICATION of what "live-GL pending" actually means here — it is NOT a crash-risk list.** CS-126/CS-127 are marked *live-GL probe-verified*, CS-129 *probe-verified*, CS-130 *real-file verified*: every code path was exercised, several through real-GL WINDOWED probes. What is genuinely outstanding on those four is **subjective/UX confirmation only** — does the arrow drag FEEL right, does the base/override layering look right when opened in Isaac/usdview. No crash class. **The one real crash-class unknown is a DIFFERENT item: the FROZEN build's GUI has never been launched on any machine** (`packaging.md`: "Windows GUI live-test pending"; the dev env has no GPU). Everything live-tested to date was the DEV run (`run.bat` / `python -m src.main`), never `dist\CellSmith\CellSmith.exe`. A frozen app can die at startup on a missing Qt plugin or DLL that a dev run never touches; `verify-payload.sh` proves the plugins are PRESENT but cannot launch a GUI headlessly. ✅ **CLOSED 2026-08-04 — the user launched `dist/CellSmith/CellSmith.exe` and it "launched fine"** (see `CS-148`), so the frozen-GUI crash class is retired and this paragraph is history rather than an open risk. (The `0xC06D007F` BLAS ban is still respected in code, so it adds no new risk — RELAXING it is what would.) testB2's cache/bake state is UNCHANGED from the measurement above — the recovery pass in CS-136(b) has still not been run | open | **P1** | agent | this ledger; `Scratch/testb2-folder-frame-recovery.md` |
| CS-136 | **OPEN QUESTIONS put to the user and NOT answered (2026-08-03).** Recorded because a compaction summary drops them. **(a)** Restore n1 Body / n2 Connector / n3 Lid folder origin+transform from `Scratch/testb2-folder-frame-recovery.md` into `test_files/testB2.cellsmith.json`? Offered; no answer. (n4-n6 must be re-authored regardless.) **(b)** Has the testB2 recovery pass (restore/re-author frames → Rebuild Main → Clear+Generate → re-author MoldTending's recipe) been run? Not as of the last measurement. **(c)** Where should **Create Joint** be available — asset/Static only (today), also on Main, also on a model ROOT? This is `CS-128`; the agent pushed back on the ROOT case (a rigid body on the root nests the articulation root) and declined to widen a documented design decision unilaterally. **(d)** Should the **Construction-Geometry bar's** own spinboxes get `num_field.PreciseDoubleSpinBox` too? They still quantise (`setDecimals(1)`/`(3)`); left alone because they are re-derived from picks rather than round-tripped, but flagged. **(e)** Timing for `CS-133` — the user said they *do* want content-addressed body identity, decision deferred pending how often re-grouping happens after rigging (ADR-0007's Revisit-if) | open | **P1** | user | this ledger; CS-128, CS-133 |
| CS-137 | **CORRECTIONS made this session — the WRONG version is what a summary tends to keep.** **(a) `brepbndlib.Add(shape, box, useTriangulation=False)` INFLATES** on an untriangulated shape (it bounds each face's untrimmed SURFACE). It read 3x too large on testB2 leaves and sent the CS-125 diagnosis down the wrong path for three probes; bound exact VERTICES instead. Recorded in `occ-vtk-gotchas.md`. **(b) The `_split_face_colors` parallel-list DESYNC was NOT the cause** of the 30 recoloured faces — measured 0 duplicates, maps aligned. The real cause was the STALE compound's face ORDER differing from the walk preorder while the counts matched (so the old drift guard never fired). The desync was still fixed as a latent fragility. **(c) The 30 face changes were a CORRECTION, not a regression** — adjudicated against the colour sidecar as independent ground truth: NEW correct 28, OLD correct 0, 2 ambiguous. **(d) Round 24's exoneration of the merge-then-edit path rested on a FALSE premise** ("the bodies come from `GetShape(prod)`, which already composes the compensated children"). Corrected in the as-built log. **(e) The tolerant recipe drop was NOT fully silent** — the single-model FAST rebuild path is strict and raised loudly; only full Generate swallowed it (ADR-0007). **(f) `plan_tree` REQUIRES label entries** — a fixture without `label_entry`/`product_entry` fails with "model was loaded without label entries", which a broad `except` will swallow into a silent no-op. **(g) `TopTools_IndexedMapOfShape.Add` returns the 1-based index and NO-GROWS on a duplicate** (probe-verified) — never pair it with an unconditionally-appended parallel list. **(h) `cache.main_rebuild_required` takes `(step, variant, expected_inputs)`** — three args, not two | done | P2 | agent | `Reference/occ-vtk-gotchas.md`, `Reference/geometry-edits.md`, ADR-0007 |

| CS-138 | **FIXED: the frozen build was BROKEN — `packaging/cellsmith.spec` used repo-relative paths after being moved out of the repo root.** `build.bat` / `make build` died at Analysis with `ERROR: script '…\AMT-CellSmith\packaging\src\__entrypoint__.py' not found` — the doubled `packaging\src` is the fingerprint. Cause: PyInstaller anchors relative paths in a spec to **three different bases** — `Analysis(scripts=)`, `Analysis(datas=/binaries=)` and `EXE(icon=/version=)` to the **spec's directory** (`build_main.py` script loop; `format_binaries_and_datas(workingdir=spec_dir)`; `api.py::EXE._makeabs`), while `hookspath`/`runtime_hooks`/`pathex` and plain `open()` resolve against the **CWD** (never spec-anchored). A spec that does not sit at the repo root therefore cannot use one relative convention. The move fixed only the invocation path in `build.bat`/`makefile`; the spec body was left alone, so beyond the hard failure it would ALSO have mis-anchored `datas` (icon + vendored fonts), `EXE(icon=)`, and the generated `build/version_info.txt`. **FIX:** derive `ROOT = SPECPATH/..` (with a `NameError` fallback for a non-PyInstaller exec) + an `R(*parts)` helper, and make EVERY path absolute — scripts, `pathex`, `datas`, `hookspath`, `runtime_hooks`, `EXE(icon=, version=)`, and the three `open()` calls (`src/__version__.py`, `src/main.py`, `build/version_info.txt`). `--distpath`/`--workpath` are CWD-based CLI defaults, so `dist/` + `build/` still land at the repo root and `build.bat`'s `dist\CellSmith` expectation holds. **Verified** `scratchpad/spec_paths_test.py` (21) — exec's the spec with stub PyInstaller classes from three different CWDs (repo root, `packaging/`, `C:\`) and asserts every collected path is absolute, exists, is inside the repo, and has no doubled spec-dir segment; plus the contents survived (entry script, 26 hiddenimports incl. the mesh workers, PyQt excludes, onedir, `console=False`, version resource). **Then a full `build.bat ci` END-TO-END: exit 0**, `dist/CellSmith/` + `CellSmith-v0.1.0-alpha.1-win64.zip` (494 MB) + `-setup.exe` (294 MB) all produced; the spec-dir-anchored `datas` landed correctly (`_internal/resources/fonts/{IBMPlexSans,JetBrainsMono}.ttf` + both OFL notices, `_internal/cellsmith.ico`) and the pxr wheel layout is intact (`_internal/pxr/{Ar,Gf,Kind,Pcp,Plug,…}`); frozen smoke test `CellSmith.exe --version` → `cellsmith 0.1.0-alpha.1` (exit 0) and an unknown `--worker` → exit 2 listing all **14** registered workers. The rest of the documented headless-from-`dist/` matrix (edges_build, STEP/USD/OBJ export, `cache_build` + `.xbf`, restructure bake) was NOT re-run — the spec change moves no code. **Invariant recorded in `Reference/packaging.md`: every path in the spec must be built with `R(...)`, never a bare relative string** | done | **P1** | agent | `Reference/packaging.md` (⭐ absolute-paths table); `packaging/cellsmith.spec` |

| CS-139 | **OPEN QUESTION (asked 2026-08-04, unanswered): promote `scratchpad/spec_paths_test.py` into `tests/`?** CS-138's build breakage was invisible to **every** test tier because nothing in `tests/` exercises the PyInstaller spec — `make test` and `make test-ci` both pass on a tree whose `build.bat` cannot even reach `COLLECT`. That is a genuine coverage hole, not a one-off: the spec is executable Python with three path-resolution bases, a `_WORKERS`-derived hiddenimports list, and an `exec` of `src/main.py`, so it can break from a pure `src/` refactor (rename a worker module, move `__version__.py`, drop `_WORKERS`) with no build attempted. The probe is a good fit for CI — ~1 s, stubs `Analysis`/`EXE`/`PYZ`/`COLLECT` so **nothing is frozen**, pure Python, no Qt/GL/OCC ⇒ **CI-eligible with no `local_only` marker**. Work = convert the 21 `check()` calls to pytest asserts in `tests/test_packaging_spec.py`, ~40 lines, no production code touched. Options: promote / leave in `scratchpad/` / skip. **NOT done unilaterally** — the user approved the CS-138 item, not this extra | open | P2 | user | `Reference/packaging.md`, `Reference/testing.md`; `scratchpad/spec_paths_test.py`; CS-138 |

| CS-140 | **LICENSE AUDIT (2026-08-04): Apache-2.0 outbound is SOUND; the frozen BUILD has six unmet attribution obligations, one of them a real conflict.** Full analysis + ordered remediation in `Reference/licensing.md`; measured with `scratchpad/probe_licenses.py` → `licenses.json` from `conda-meta/*.json` (74 pkgs), `importlib.metadata` (61 dists) and **`build/cellsmith/COLLECT-00.toc`** (the 1991 files actually bundled — installed-package metadata proves nothing about distribution). **Nothing blocks Apache-2.0 for first-party code**: every copyleft dep is WEAK copyleft (Qt/PySide6 `LGPL-3.0-only OR GPL-2/3`, OCCT `LGPL-2.1-only` + its header exception, pythonocc-core `LGPL-3.0-or-later`, libiconv `LGPL-2.1-only`) consumed as SEPARATE DLLs in onedir, which LGPL-2.1 §6 / LGPL-3.0 §4 expressly permit; the "Apache-2.0 vs GPLv2" incompatibility is about MERGING SOURCE and never arises; and the ASF's Category-X ban on LGPL is **ASF project policy, not an Apache-2.0 term** (verified at apache.org/legal/resolved.html) so it does not apply here. **The gaps (L1-L6):** L1 Qt/PySide6 LGPLv3 text + prominent notice + source offer are ABSENT — there is **no `PySide6*.dist-info` in the bundle at all** (of 1991 files only 28 are license texts, 26 incidental); L2 the OCCT exception's own "prominent notice in supporting documentation" condition is unmet; **L3 `FreeImage.dll` ships with NO license elected** (`GPL-2.0-or-later OR GPL-3.0-or-later OR FIPL`) — the one item that is a CONFLICT not paperwork, and `TKService.dll` imports it at LOAD TIME (PE-import-table measured) so it cannot just be deleted; L4 **25 Intel MKL DLLs** under `LicenseRef-IntelSimplifiedSoftwareOct2022` incl. useless `scalapack`/`blacs`/`cdft` MPI libs; L5 BSD/MIT/Apache/ISC/**TOST-1.0** (usd-core is the *Tomorrow Open Source Technology License* = Apache-2.0 with §6 Trademarks replaced) notices not reproduced — VTK alone is 209 BSD-3 DLLs; L6 freetype has no FTL election/credit. **Repo side is nearly clean** — the one gap is that `LICENSE.TXT` is the STOCK Apache text whose appendix still reads `Copyright [yyyy] [name of copyright owner]`, and zero `src/` files carry an SPDX header. OFL fonts are already compliant. **Recommendations R1-R8** with effort + release-blocking flags in the topic doc; R1 (fill the copyright line + add `NOTICE`) is BLOCKED on a user decision — **who is the copyright holder, the user personally or AMT as work-for-hire?** R2(a) elect FIPL is minutes and should happen regardless of R2(b). Deliberately NOT implemented: no `NOTICE`/`THIRD-PARTY-NOTICES.md` written and `LICENSE.TXT` untouched — authoring a copyright claim is the user's call, not the agent's | open | **P1** | user | `Reference/licensing.md`; `scratchpad/probe_licenses.py` |

| CS-141 | **DONE: license remediation R3+R4+R5 shipped (CS-140's follow-through).** User dispositions 2026-08-04: **R1 SKIPPED for now** (the `LICENSE.TXT` copyright holder stays unfilled — still the one repo-side gap); **R2 = an open QUESTION** the user asked back ("what does resolving FreeImage mean"), so `FREEIMAGE_ELECTION = None` in the generator and every build reports exactly ONE gap by design; **R3+R4 implemented**; **R5 implemented + verified**; **R6-R8 = explanation requested**, not yet dispositioned. **(a) R3+R4 — `packaging/gen_third_party_notices.py`** generates `build/THIRD-PARTY-NOTICES.md` (~645 KB, 93 verbatim texts, 132 inventory rows) from `importlib.metadata` + `<env>/conda-meta/*.json`, and the spec ships it **plus `LICENSE.TXT`** at the payload root. ⭐ **Invoked FROM THE SPEC, deliberately, not from `build.bat`/`makefile`** — both OSes run the same spec, so Windows and Linux cannot diverge and neither script can forget it; loaded by PATH via `importlib` because `import packaging.…` collides with the pip `packaging` module. Discharges: Qt named as LGPLv3 + the dynamic-linking/relink statement, the OCCT exception's prominent notice VERBATIM, a 3-year written source offer for the LGPL components, the FreeType FTL credit, and every discoverable BSD/MIT/Apache/ISC/TOST text. **Curated texts** live in `packaging/licenses/` (LGPL-2.1, LGPL-3.0, GPL-3.0, FTL, FreeImage-FIPL, OCCT-LGPL-EXCEPTION) because conda does NOT extract license text into the prefix — fetched verbatim from upstream; cross-checked: fetched `LGPL-3.0.txt` vs the env's own `OCC/LICENSE` differ by ONE character (`http` vs `https` in the FSF URL). **Fail-soft by design:** never breaks a build; unresolved items become `NOTICE-WARN:` on stderr AND a *Gaps* section INSIDE the shipped document. Includes a **rot guard** scanning every conda license string for GPL/AGPL/`LicenseRef-IntelSimplified`/SSPL/BUSL. **(b) R5 — MKL REMOVED:** `libblas=*=*openblas` pinned in `packaging/environment.yml` + applied to the live env; `mkl`, `onemkl-license`, `tbb` uninstalled, `libopenblas` 0.3.33 (BSD-3) installed, **0 `mkl_*.dll`** left in the env AND in the rebuilt bundle (was 25). Payload now **972 MB / 1957 files** (`du -sh`; the docs' older "~1.4 GB" was never re-measured ❓). **VERIFIED:** `scratchpad/openblas_env_test.py` **8/8** (numpy backend not MKL; no `mkl_*` module mapped in-process; OCCT geometry; the real STEP→XCAF→`.xbf`→reopen round trip = the `CSF_*` hard-fail path; Qt+pyvista offscreen render; trimesh/scipy/shapely; pxr; BLAS matmul beside OCC+VTK) · `scratchpad/notices_test.py` **17/17** · **55/55 scratchpad suites** (`scratchpad/run_all_tests.py`, new) · **8/8 pytest** · full `PyInstaller` build exit 0 with both attribution files confirmed present in `dist/CellSmith/_internal/`. ⚠️ **SIDE FINDING, deliberately NOT acted on:** `pv.Sphere()` and `a @ a` — both banned as hard `0xC06D007F` crashes — now SURVIVE in a process with Qt + OCC + a rendered VTK scene, so the ban was likely an MKL delay-load artifact. The ban STAYS IN FORCE (windowed GUI + frozen build untested); recorded as a ⚠️ note in `occ-vtk-gotchas.md` rather than a change | done | **P1** | agent | `Reference/licensing.md` (As built), `Reference/packaging.md`, `Reference/occ-vtk-gotchas.md`; CS-140 |

| CS-142 | **FINAL DISPOSITIONS 2026-08-04 — the licence work is CLOSED, and three earlier items were DECLINED by the user.** Recorded because a declined item looks identical to a forgotten one after a compaction. **(1) Licence remediation (CS-140/141) complete:** **R2 = FIPL ELECTED** (`FREEIMAGE_ELECTION = "FIPL"` in `packaging/gen_third_party_notices.py`; FreeImage ships UNMODIFIED as a mere load-time dep of OCCT `TKService`, so FIPL's source clause — which reaches only FreeImage files WE modify — costs nothing; the notices now state the election affirmatively and the generator reports **0 gaps**). **R8 DONE** — read the installed Inno Setup 6 `license.txt`: zlib-style permissive, commercial use expressly granted, **no issues**; its only binary-form condition is to RETAIN notices already present, and measurement confirms `Setup.e32`/`SetupLdr.e32` carry `Jordan Russell`/`jrsoftware.org` as UTF-16LE strings (an ASCII grep finds NOTHING — that is why an earlier check looked negative) while `build.bat` does no post-processing, so they survive verbatim; the optional acknowledgement is now given via a new **Build tooling** section in the notices (PyInstaller's bootloader exception + Inno). `packaging/licenses/InnoSetup.txt` vendored. Verified `scratchpad/notices_test.py` **22/22** (grown from 17: now also proves the gap machinery STILL FIRES by regenerating with the election forced back to `None` — otherwise the FreeImage check would be vacuous once elected). **(2) DECLINED — do not re-propose without new information:** **R1** fill the `LICENSE.TXT` copyright holder ("skip for now") — the repo therefore still grants under `Copyright [yyyy] [name of copyright owner]`; evidence for the eventual answer, not an assumption: `packaging/cellsmith.iss` sets `AppPublisher=AMT`. **R6** SPDX headers ("skip it"). **R7** a CI licence gate ("skip it") — ⚠️ the consequence is that the rot-detection logic exists but only WARNS; nothing FAILS when a GPL/non-OSI package re-enters the env, which is precisely how MKL got in unnoticed. **CS-139** promote `spec_paths_test.py`/`notices_test.py` into `tests/` ("skip") — so the PyInstaller spec and the notices generator remain covered ONLY by gitignored `scratchpad/` suites that no CI runs. **CS-136(a)+(b)** the testB2 folder-frame restore + recovery pass ("good, skip") — the frames will NOT be restored from `Scratch/testb2-folder-frame-recovery.md`; **that doc is still the only copy and must NOT be deleted** on the "restored or re-authored" rule, since neither happened. **(3) ❓ NEVER MEASURED, flagged not fixed:** whether an end user can REACH the shipped notices — they install to `{app}/_internal/` (the `.iss` uses `Source: {#DistDir}\*` + `recursesubdirs`, so both files land on disk) but the app has no About box, so nothing surfaces them; LGPL's "prominent notice" is arguably weaker for a file the user must go find | done | P1 | agent | `Reference/licensing.md`; CS-140, CS-141, CS-136, CS-139 |

| CS-143 | **BUILT: GitHub Actions CI + Release workflows, a Debian package, and the packaging tests promoted into `tests/`.** Ported from the sibling `MTConnectExplorer` repo; the release *procedure* (branch flow, version-driven trigger, rulesets) is documented for humans in the repo-root `CONTRIBUTING.md`, the CellSmith-specific mechanics in `Reference/packaging.md` → *GitHub Actions*. **(a) `.github/workflows/ci.yml`** — PR gate on `main`/`dev/*`/`release/*`: `version-check` (ported verbatim), `test-linux`/`test-windows` (`pytest -m "not local_only"`), `build-linux`/`build-windows` (**PyInstaller only** — no zip/installer/`.deb`/upload, keeping the gate ~15 min shorter) each followed by the payload verifier. **(b) `.github/workflows/release.yml`** — `version` → `build-linux` (tar.gz + `.deb`) ‖ `build-windows` (zip + installer) → `release` (tag, GitHub Release, seed `dev/X.Y`). **(c) NEW `.github/scripts/verify-payload.sh`** shared by both so the gate and the shipped artifact are held to the same standard: Qt plugins + a Qt PLATFORM plugin, OCCT libs + the `opencascade/resources` tree, pxr, VTK, notices + LICENSE + OFL, `--version` exits 0, and an unknown `--worker` rejected listing all 12 workers. **(d) NEW `packaging/debian/`** (`make deb`, chained from `make build`): `control.in`, `copyright.in`, `cellsmith.desktop`, `ico_to_png.py`, `make_deb.sh`. Payload at `/opt/cellsmith` + `/usr/bin` symlink + desktop entry + hicolor icon + `/usr/share/doc/cellsmith/{copyright,THIRD-PARTY-NOTICES.md,changelog.gz}`; 9 self-checks + informational lintian. **(e) `CS-139` DONE** — `tests/test_packaging_spec.py` (spec paths/contents from 3 CWDs) + `tests/test_third_party_notices.py` (obligations, election, spec `datas`, licence rot guard) replace the two `scratchpad/` suites, which were DELETED. **pytest went 8 → 49 tests.** **Adaptations that are NOT in MTConnectExplorer's version** (it is a pip-venv onefile build): conda via `conda-incubator/setup-miniconda@v3` + `shell: bash -el {0}`; conda pushed onto `$GITHUB_PATH` because `build.bat`/`dev.bat` call **bare `conda`** and setup-miniconda only wires bash/pwsh; the Linux apt set installed **BEFORE** the build (a failed PySide6 import silently yields ZERO Qt plugins); disk reclamation + `df -h` + deleting `dist/CellSmith`+`build/` pre-upload; no notices step (the spec generates them); `compression-level: 0`. **VERIFIED (measured, not assumed):** ⭐ GitHub's caps — **<2 GiB per asset, 1000 assets max, NO cap on release total or bandwidth** (docs.github.com), largest asset ~494 MB ⇒ ~4× headroom, and the `release` job asserts it anyway; **Inno Setup 6.7.1 + Miniconda 26.5.3 are PREINSTALLED** on `windows-latest` (runner-image manifest) — but ❓ the manifest gives no Inno PATH and `build.bat` only WARNS when ISCC is missing, so the release job **fails explicitly** if no `*-setup.exe` appears; both YAML files parse; both shell scripts pass `bash -n`; `make -n deb`/`build` expand correctly; the verifier passes against the real 972 MB Windows `dist/`; `make_deb.sh` built a real `.deb` end-to-end in a **WSL Debian sandbox** (synthetic payload) with 9/9 self-checks. **TWO BUGS FOUND BY TESTING, both fixed:** (1) `sed` templating died with ``unknown option to `s'`` because `Depends` contains `\|` and the maintainer contains `<>@` — every plausible delimiter appears in some value, so templating moved to Python; (2) the verifier's Qt-plugin glob was **Linux-only** (`PySide6/Qt/plugins/`) and FAILED against a known-good Windows build, whose path is `PySide6/plugins/` — now matched loosely. ⭐ **Semver→Debian: `-` MUST become `~`** — `0.1.0-alpha.1` parses `alpha.1` as the debian revision and `dpkg --compare-versions` ranks it **NEWER** than `0.1.0`; proven both directions in the sandbox. **STILL NOT DONE:** ❓ no Linux build has ever run here, so the tar.gz/`.deb` sizes are unmeasured and the `.deb` has never been tested against a REAL payload; CI has never executed (needs the repo on `main`) | done | **P1** | agent | `Reference/packaging.md` (GitHub Actions + Debian package), `Reference/testing.md`; `CONTRIBUTING.md` |
| CS-144 | **TODO, user-deferred 2026-08-04: reproducible release builds.** `packaging/environment.yml`'s `pip:` block is UNPINNED (`PySide6`, `pyvista`, `pyvistaqt`, `usd-core`, `trimesh`, `manifold3d`, `mapbox_earcut`, `scipy`, `shapely`, `pyinstaller>=6.10`, `pytest*`, `pillow`), so two builds of the same git tag can bundle different upstream versions and a release can silently pick up a breaking change — e.g. a PySide6 minor that moves the Qt plugin layout, which is exactly what the verifier's platform-path bug was about. Options: pin exact versions in `environment.yml`; add a `conda-lock`/`pip freeze` lockfile consumed only by `release.yml`; or accept it and record the resolved set as a release asset. Interacts with `CS-143` (the release workflow is where it matters) and with the conda env cache key. **Explicitly deferred by the user — do not action without being asked** | open | P2 | user | `Reference/packaging.md`; CS-143 |
| CS-145 | **TODO, user-deferred 2026-08-04: code signing for the Windows artifacts.** `CellSmith.exe` and `CellSmith-v*-setup.exe` are unsigned, so SmartScreen/Defender warn on every download and the reputation clock never starts. Needs an OV/EV code-signing certificate (an EV cert or one with SmartScreen reputation is what actually clears the warning), a secret-managed key in the release workflow, and a `signtool` step after `build.bat` but before the zip + installer (the installer must sign the payload it wraps AND itself). Consider Azure Trusted Signing / a cloud HSM rather than a file-based `.pfx` in Actions secrets. **Explicitly deferred by the user — do not action without being asked** | open | P2 | user | `Reference/packaging.md`; CS-143 |

| CS-146 | **DONE 2026-08-04: `precompact` skill renamed to `flush`; repo URLs settled on `ManufacturingTechnology/CellSmith`; the Inno-Setup-path unknown from CS-143 closed.** **(a) SKILL RENAME** — `.claude/skills/precompact/` → `.claude/skills/flush/`, frontmatter `name: flush`, and the live references updated (`SKILL.md`, the 3 user-facing messages in `.claude/hooks/precompact-gate.sh`, `CLAUDE.md`, `docs/src/AI/index.md`, `Scratch/ai-metaanalysis.md`, `Scratch/ai-self-analysis-research-method.md`). ⭐ **The HOOK FILE keeps the name `precompact-gate.sh`** — it is named after the `PreCompact` **event**, not after the skill, and `.claude/settings.json` binds it by path. **Deliberately NOT rewritten:** `Research/Reports/*` (immutable), `Research/alignment-audit.md` (append-only), `Scratch/ai-history.md` (a dated timeline), and the historical ledger entries `CS-040`/`CS-098`/`CS-115` — those record what the repo looked like at the time, and editing them would falsify the record. **So `precompact` remains the correct name in anything dated before 2026-08-04**; this entry is the mapping. **(b) REPO URL** — canonical is now `https://github.com/ManufacturingTechnology/CellSmith` (the old `m-r-mccormick/AMT-CellSmith` is gone from every URL). Present in `docs/mkdocs.yml` `repo_url`, `packaging/debian/{control.in,copyright.in}`, and NEW in `packaging/cellsmith.iss` (`AppPublisherURL`/`AppSupportURL`/`AppUpdatesURL` → the Apps & features entry). Surviving `AMT-CellSmith` strings are LOCAL FILESYSTEM paths (`scratchpad/*`, and a quoted PyInstaller error in `packaging.md`/`tests/test_packaging_spec.py`) — the working directory really is `AMT-CellSmith`, so those are correct and must not be rewritten. ⚠️ **`git remote origin` still points at `git@github.com:m-r-mccormick/AMT-CellSmith.git`** — deliberately left alone; changing a push target is the user's call. **(c) INNO PATH** — two-layer fix so nothing depends on an undocumented runner path: `build.bat` now **honours a pre-set `%ISCC%`** (and gained `%ProgramFiles%\Inno Setup 6` to its probe list), and NEW `.github/scripts/find-iscc.ps1` locates ISCC via PATH → both Program Files → `%LOCALAPPDATA%\Programs` → the three uninstall registry keys → a depth-2 scan, exports it to `$GITHUB_ENV`, and **fails the job with the install command** if absent. Wired into `release.yml` before the build; the existing "no `*-setup.exe` ⇒ fail" assertion stays as the second layer. Tested locally: found the per-user install. Also fixed there — ISCC.exe carries no version resource, so the script says "unknown" rather than printing a meaningless `0.0.0.0`. **(d) FLAGGED, NOT CHANGED** (user's own edits): the Debian `Description:` is now a single synopsis line ending in a full stop with no extended description — lintian will likely emit `extended-description-is-empty` and a synopsis-phrasing tag; and `cellsmith.desktop` `GenericName=Manuacturing Rigging Tool` is missing an `f` | done | P2 | agent | `Reference/packaging.md`; `.claude/skills/flush/SKILL.md`; CS-143 |

| CS-147 | **DONE 2026-08-04: the `flush` skill is RE-SCOPED from "pre-compaction" to "flush knowledge to disk", plus two small fixes.** **(a) RE-SCOPE (user's framing):** the skill is for **flushing all knowledge to disk**, not specifically for compaction. A conversation ends in one of two ways and **BOTH lose the transcript** — the session closes, or the context is compacted into a lossy summary — so the rule is *flush before the knowledge can be lost*, not *flush before compacting*. ⚠️ **Load-bearing asymmetry now stated in all three places:** the `PreCompact` gate guards ONLY the compaction path; **NOTHING guards a session simply being closed**, so that case rests entirely on the agent remembering — which is why it is now the skill's FIRST listed trigger. Trigger order: before ending/closing a session · before `/compact` · when the gate blocks · mid-session after a dense stretch ("a disconnect is not a trigger you get to plan for"). Rewritten: `SKILL.md` (frontmatter description, title *Flush the session's knowledge to disk*, a **When to run it** table, a **What it is not for** section, and step 5 reframed from "compaction-critical" to "must-survive — equally what a NEXT SESSION needs"), `CLAUDE.md` (§ retitled *⭐ Run the `flush` skill — what must survive the conversation ending*), `docs/src/AI/index.md` (*Knowledge flush (partly enforced, mostly your job)*). **(b)** `packaging/debian/cellsmith.desktop` `GenericName` typo `Manuacturing` → `Manufacturing` (user-visible in some desktop environments). The Debian `Description:` stays a single synopsis line **by explicit user instruction** — accept the resulting lintian `extended-description-is-empty`/synopsis tags rather than "fixing" them. **(c)** The five open questions of CS-128/CS-133/R1/CI-gate-scope/`git remote` were re-put to the user and **explicitly SKIPPED ("not now")** — they stay open in their own entries; do not re-raise unprompted. Also see the ⭐ re-classification appended to **CS-135**: the four "live-GL pending" items are UX confirmation, not a crash class, and the real unverified crash risk is that the **frozen GUI has never been launched** | done | P2 | agent | `.claude/skills/flush/SKILL.md`; `CLAUDE.md`; `docs/src/AI/index.md`; CS-135, CS-146 |

| CS-148 | **✅ VERIFIED 2026-08-04: the FROZEN Windows GUI launches.** User ran `dist/CellSmith/CellSmith.exe` — *"launched fine"*. This retires the **last crash-class unknown in the build** and the longest-standing one: `packaging.md` had carried *"Windows GUI live-test pending"* since the packaging work began, because every live test to date — including the whole testB2 session — was the **DEV** run (`run.bat` / `python -m src.main`), never the frozen exe. That distinction mattered: a frozen app fails in ways a dev run cannot (a Qt platform plugin the hook silently didn't collect, a DLL missing from `_internal/`, an OCC resource path that only resolves under `sys._MEIPASS`), and `.github/scripts/verify-payload.sh` can prove the plugins are PRESENT but cannot launch a GUI headlessly. **What this does and does not cover:** it covers Windows onedir startup + Qt platform plugin + GL context on a real driver. It does NOT cover the **installed** build from `CellSmith-v*-setup.exe` (a different `{app}` path with per-user privileges), nor the **Linux** frozen GUI (never built anywhere). Those remain open but are much lower risk now that the frozen-payload story is proven once | done | **P1** | user | `Reference/packaging.md`; supersedes the frozen-GUI risk in CS-135 |
| CS-149 | **⭐ GOTCHA: the MKL→OpenBLAS pin does NOT reach an existing `CellSmithEnv` — `dev.bat` only CREATES an env, it never UPDATES one.** `CS-141` added `libblas=*=*openblas` to `packaging/environment.yml` and applied it to *this* machine's env by hand (`conda install -n CellSmithEnv "libblas=*=*openblas"`). But `dev.bat` short-circuits with *"conda env CellSmithEnv already exists"* and `build.bat` only ever `pip install`s a few packages — **neither touches the conda-level BLAS pin**. Consequence: anyone (or any CI cache, or the user on a second machine) with a `CellSmithEnv` created before 2026-08-04 **still has Intel oneMKL**, will still bundle **25 proprietary DLLs** into their build, and their `tests/test_third_party_notices.py::test_environment_has_no_unresolved_copyleft_package` will **FAIL** — which is the guard working correctly, not a broken test. **Fix for such an env:** `conda install -n CellSmithEnv -c conda-forge "libblas=*=*openblas"` (removes `mkl`, `onemkl-license`, `tbb`; installs `libopenblas`), or `conda env remove -n CellSmithEnv` + `dev.bat`. **Not fixed in `dev.bat` deliberately** — making it run `conda env update` on every invocation would slow the common path and re-solve the env unexpectedly; the failing test is a loud enough signal. CI is unaffected: the runners create the env fresh from the yml | open | P2 | — | `Reference/licensing.md` (R5), `Reference/testing.md`; CS-141 |
| CS-150 | **CORRECTIONS + gotchas from the CI/licensing session (2026-08-04) — the wrong version is what a summary keeps.** **(a) A probe of mine PASSED VACUOUSLY and I nearly cited it as evidence.** `openblas_env_test.py`'s "no `mkl_*` module is loaded in-process" check enumerated **ZERO** modules on its first run and reported PASS: `ctypes` defaults `restype` to `c_int`, which truncated the 64-bit `GetCurrentProcess()` handle, so `EnumProcessModules` silently returned nothing. Fixed by declaring `restype`/`argtypes` **and** asserting `n > 10` so it can never pass on an empty enumeration. **Lesson: any probe whose evidence is "I found none of X" must first assert it found ANYTHING.** **(b) `scratchpad/svd_dll_test.py` exits 0 no matter what** — it catches the exception and prints `svd EXC …` — so its `PASS` in `run_all_tests.py` is **not** evidence about the `0xC06D007F` BLAS crash, which is what I was about to cite it for. The sweep reports process exit status, so an exception-swallowing script always shows PASS. **(c) `conda run` cannot execute a `python -c` containing NEWLINES** — it raises `NotImplementedError: Support for scripts where arguments contain newlines not implemented`. Write the snippet to a file (that is why `openblas_env_test.py` exists as a file). **(d) `TDocStd_Application.SaveAs` on a doc the app never opened fails** with *"this document has not yet been opened by any application"* and a `(3, '')` status — a doc built by hand via `TDocStd_Document("BinXCAF")` + `XCAFDoc_DocumentTool` is NOT registered; only a doc a `STEPCAFControl` reader `Transfer`-ed (or `app.Open`-ed) is. Use the repo's real path (`reader._doc_from_step` → `cache.save_cache`). **(e) `reader._doc_from_step` returns FOUR values** `(doc, colors_ok, part_colors, face_colors)`, not three. **(f) `PySide6.QtGui` has no `qVersion`** — it is `QtCore.qVersion()`. **(g) I overstated the live-GL items as a crash risk**; they were already probe-verified and the real risk was elsewhere (see the re-classification in CS-135 and `CS-148`) | done | P2 | agent | `Reference/invariants.md`, `Reference/occ-vtk-gotchas.md`, `Reference/testing.md` |
| CS-151 | **DONE 2026-08-04: `pytest` and `python -m pytest` disagreed, and CI ran the one nobody tested.** ⭐ **THE FIRST-EVER CI RUN WENT RED, AND THE SUITE HAD BEEN GREEN LOCALLY THE WHOLE TIME.** Only `python -m pytest` prepends the **CWD** to `sys.path`; a bare `pytest` prepends the *test file's* dir (`tests/`), so `import src` raises `ModuleNotFoundError`. The makefile and `test.bat` both use the `-m` form; `ci.yml` runs a bare `pytest` — so `tests/conftest.py`'s `qapp` fixture died at `from src.gui.theme import apply_dark` on **both** runners (2 errors each). **Fix:** `pythonpath = ["."]` in `pyproject.toml`'s `[tool.pytest.ini_options]` (resolved against rootdir), which makes both invocations identical. ⛔ **Deliberately NOT "fixed" by changing CI to `python -m pytest`** — that leaves the divergence armed for the next person who types `pytest`. **Reproduced locally before fixing** (bare `pytest` → same 2 errors) and re-verified after (51 passed) | done | **P1** | agent | `Reference/testing.md` § *`pytest` and `python -m pytest` are NOT interchangeable* |
| CS-152 | **DONE 2026-08-04: `test_version_resource_is_written_under_the_repo_build_dir` was a Windows-only assertion in a cross-platform test.** The spec passes `EXE(version=…)` only under `sys.platform == "win32"` (a VSVersionInfo resource is a Windows PE concept), so on the Linux runner the kwarg is `None` and the test failed with *"no VSVersionInfo file passed to EXE"*. It had never run anywhere but Windows. **Split into two:** the original now asserts the fact that IS cross-platform — the spec **writes** `build/version_info.txt` on every OS — and a new `test_version_resource_is_wired_into_exe_only_on_windows` asserts the platform branch itself (absolute path + content on Windows; `version` **and** `icon` both `None` elsewhere). The second is the more valuable one: it pins the branch rather than skipping it | done | P1 | agent | `tests/test_packaging_spec.py`; `Reference/packaging.md` |
| CS-153 | **DONE 2026-08-04: eight GPL-3.0 conda rows exist ONLY on Linux, and the licence rot guard had never seen them.** All prior licensing analysis was done on Windows. `test-linux` failed on `ld_impl_linux-64`, `readline`, and six GCC runtime libs. **None is an obligation — but for three different reasons, all now encoded AND rendered into the notices** (a copyleft row suppressed by name with no published reason is an unauditable claim). **(a) `_spdx_exception()`** — a general rule that SPDX `<license> WITH <exception-id>` clears the check, covering `libgcc`/`libgcc-ng`/`libgomp`/`libstdcxx`/`libgfortran`/`libgfortran5` (`GPL-3.0-only WITH GCC-exception-3.1`) via the [GCC Runtime Library Exception](https://www.gnu.org/licenses/gcc-exception-3.1.html). Chosen over allowlisting the six names so `Classpath-exception`/`LLVM-exception` resolve the same way; each is listed **with its exception id** in the notices. **(b) `_BUILD_ONLY`** — `ld_impl_linux-64` is GNU `ld`, used only while conda installs; conda-meta describes the **env**, not the payload. **(c) `_EXCLUDED_FROM_PAYLOAD`** — `readline` is `GPL-3.0-only` with **no** exception, the one genuine Apache-2.0 conflict had it shipped; resolved by keeping it out (spec `excludes=` + a new `verify-payload.sh` assertion that no `readline*.so`/`.pyd`/`libreadline*` is under `_internal/`). ⭐ **`unresolved_reason(row)` is now ONE predicate called by both the generator's Gaps section and the test** — they were separate copies of the rule, i.e. guaranteed to diverge eventually. **Verified without a Linux box** by running the generator against a synthetic `conda-meta` holding the exact 8 offending rows **plus a planted bare-`GPL-3.0-or-later` control**: all 8 resolved, the control still gapped. ~~❓ **Unverified:** that `readline` was ever actually in the payload — nothing in `src/` imports it, so the exclusion may be a no-op.~~ **✅ ANSWERED 2026-08-04 by the first real Linux CI run, and the guess was BACKWARDS: readline WAS in the payload (3 hits) *with* `excludes=["readline"]` already in the spec.** Nothing importing it is irrelevant — it arrives as another binary's `DT_NEEDED`. See `CS-157`. The verifier did exactly the job it was added for | done | **P1** | agent | `Reference/licensing.md` § *The Linux toolchain rows*; `packaging/gen_third_party_notices.py`; user chose both recommended options |
| CS-154 | **DONE 2026-08-04: `conda-incubator/setup-miniconda@v3` → `@v4` + two deprecated inputs, across BOTH workflows (6 call sites).** `v3` targets Node 20, which GitHub force-runs on Node 24 and annotates. [`v4.0.0`](https://github.com/conda-incubator/setup-miniconda/releases/tag/v4.0.0)'s only breaking changes are the Node 24 runtime and an ESM build — **no input renamed or removed** — checked before bumping. Also `auto-activate-base: false` → `auto-activate: false` (the former is deprecated; each job already sets `activate-environment: CellSmithEnv`, so no `activate-environment: base` companion is needed), and **added `conda-remove-defaults: true`** — otherwise the action adds the `defaults` channel implicitly, and `environment.yml` pins `conda-forge` **only**, deliberately: a silent second channel is exactly how a differently-licensed package gets back in (cf. the MKL story, L4/R5). Both files re-parsed with `yaml.safe_load` after the rewrite | done | P2 | agent | `Reference/packaging.md` § *GitHub Actions* |
| CS-155 | **OPEN: `gl` tests are DESELECTED on the Windows CI runner — restore them with a Mesa llvmpipe `opengl32.dll`.** `windows-latest` has no GPU, and Windows' fallback `opengl32.dll` is the GDI **generic** renderer (OpenGL 1.1) while VTK 9's OpenGL2 backend needs 3.2+; `pv.Plotter.screenshot()` took an **access violation** and the runner died with **exit 139**, so no test could catch it. The Windows job now runs `-m "not local_only and not gl"`; **Linux still runs the full `-m "not local_only"`**, so the `gl` tier is covered — what is lost is Windows-native GL coverage in CI. ⚠️ **Two traps this cost a red run to learn:** `LIBGL_ALWAYS_SOFTWARE=1` was set on that job and does **nothing** on Windows (a *Mesa* variable; Windows VTK goes through WGL) — it made the job *look* like software rendering was handled, and has been removed; and the Linux fix (`libegl1`) has no Windows equivalent. **To close:** add a CI step dropping a Mesa3D llvmpipe `opengl32.dll` beside `python.exe`, then delete the `not gl` from that one job. ❓ Untested. Not done unilaterally — it adds a download step to CI. ⭐ **UNANSWERED QUESTION put to the user 2026-08-04 and not yet answered: "attempt the Mesa llvmpipe shim now, or leave this on the backlog?"** Do not treat silence as "leave it" — re-ask if the topic comes up | open | P3 | — | `Reference/testing.md` § *`windows-latest` has no OpenGL VTK can use* |

| CS-156 | **⛔ CORRECTION + SESSION STATE 2026-08-04: the git history was REWRITTEN, and every SHA in `CS-135` is dead.** `git log --all` is now exactly **two commits — `23e7c8d` "first commit" and `7353006` "initial commit" — on branch `feature/init`**, and `git cat-file -t` FAILS on both `eafad8e` and `34062bb`, the commits `CS-135` builds its entire git narrative on. So `CS-135`'s headline claim — *"the user COMMITTED EVERYTHING as `eafad8e` … the working tree is now COMPLETELY CLEAN"* — is no longer checkable and must not be repeated. Its **file lists are still valuable** as the record of what that work touched; its SHAs and its clean-tree assertion are not. This entry is the correction; `CS-135` now points here. **Do not attempt to "restore" anything** — a rewritten history is the user's prerogative and this is a record, not a defect report. ⭐ **UNCOMMITTED FILE LIST as of this flush (12 paths, all from the CI-fixing session `CS-151`…`CS-155`; `src/` is CLEAN — `git status --porcelain src/` returns nothing):** `.github/scripts/verify-payload.sh`, `.github/workflows/ci.yml`, `.github/workflows/release.yml`, `docs/src/AI/Reference/{licensing,packaging,testing}.md`, `docs/src/AI/status.md`, `packaging/cellsmith.spec`, `packaging/gen_third_party_notices.py`, `pyproject.toml`, `tests/test_packaging_spec.py`, `tests/test_third_party_notices.py`. **Because no `src/` file changed, every `Reference/*.md` that mirrors `src/` is still accurate** — the three touched above mirror `packaging/`, `tests/` and `.github/`, not `src/`. **Other must-survive state is UNCHANGED and still as recorded elsewhere:** live-GL pending list → `CS-135` §(2) + the re-classification there (UX confirmation, not a crash class; the frozen-GUI crash class was retired by `CS-148`); testB2 cache/bake state → `CS-135` §(3), still damaged, recovery procedure in `Scratch/testb2-folder-frame-recovery.md`, **the CS-136(b) recovery pass has still not been run** | done | **P1** | agent | supersedes the git-state half of `CS-135` |
| CS-157 | **`build-linux` FAILED the payload verifier: `no GPL readline in the payload (3 hits)` — `excludes=` is not an exclusion for a shared library.** `readline` was already in `packaging/cellsmith.spec`'s `excludes=` (added by `CS-153`) and the frozen Linux payload contained readline anyway. **Root cause:** `excludes=` filters the **module graph** only; PyInstaller's binary dependency analysis then collects `libreadline` because another bundled binary lists it in **`DT_NEEDED`** — no module-level exclusion can reach that. (Probe: `readelf -d` over every `.so` in a stock Debian `/usr/lib/x86_64-linux-gnu` + `lib-dynload` — the *only* consumer is CPython's own `readline` extension module, so that module is almost certainly what dragged the library in; the CI log printed a bare count, not names, so the exact 3 paths are still unread — the new diagnostics will print them.) **Fix, 4 files:** (a) `cellsmith.spec` now filters `a.binaries` after `Analysis` — drop any entry whose dest basename starts `readline`/`libreadline`/`libhistory`, printing what it dropped (list-comprehension filtering is PyInstaller's documented TOC mechanism; `COLLECT` accepts any "TOC-like iterable" — checked in `PyInstaller/building/api.py`, 6.21.0). (b) `verify-payload.sh` now **names the hits** (payload-relative) and, via `readelf`, the collected libs whose `DT_NEEDED` pulled them in — a bare "3 hits" is not actionable — **and warns in the opposite direction**: payload clean but a bundled `.so` still `NEEDED` readline ⇒ that lib will fail to `dlopen`. Patterns extended to `readline*.so*` + `libhistory*`. (c) `gen_third_party_notices.py` — the `_EXCLUDED_FROM_PAYLOAD` prose now describes **both** halves, since the notices file is the legal claim. (d) `test_third_party_notices.py` now also asserts the spec filters `a.binaries` — the old assertion (`"readline"` appears in the spec) was satisfied by the very config that shipped readline. **Verified:** 26/26 notices tests pass; both verifier branches probed against synthetic payloads built from **real ELF files under WSL** (dirty → error + 3 named hits + the needer; clean-but-dangling → the warning); `bash -n` + spec compiles. **⭐ RUN 2 (commit `01d56ea`) — the `a.binaries` filter WORKED but was only HALF the story; a SECOND route shipped readline, and the new diagnostics identified it in one run.** Run 2: **4 hits — `lib{readline,history}.so{,.8}`, the extension module GONE (filter reached it), payload 2111→2109 files, and ZERO `DT_NEEDED` reverse dependencies.** Nothing linked them ⇒ they were **swept**, not pulled. ⭐ **Culprit is PyInstaller's OWN numpy hook:** `PyInstaller/hooks/hook-numpy.py` → `if numpy_installer == 'conda': datas += conda_support.collect_dynamic_libs("numpy", dependencies=True)`; `dependencies=True` walks numpy's conda dependency **graph** (numpy → python → readline, `numpy`'s `depends` confirmed from local `conda-meta`) and `conda.collect_dynamic_libs` **globs `*.so`/`*.so.*` out of the env's shared `lib/`**, symlinks included (`resolved_file.is_file()` follows them) — all four files, filed as **`a.datas`**, which is why an `a.binaries`-only filter missed them (read from `PyInstaller/utils/hooks/conda.py:288-328`, 6.21.0). **Fix:** the spec now filters **both** `a.binaries` and `a.datas` via one `_drop_gpl_readline()` helper that prints the full `(dest, src, typecode)` of each dropped entry (the *src path* is what names the contributing package); `COLLECT` places files from exactly `EXE` + `a.binaries` + `a.datas`, so filtering both is **exhaustive**. Verifier also now states when `readelf` is **missing** instead of letting "didn't look" read as "nothing needs it" — an empty needers list was the evidence that cracked run 2. Test tightened to require BOTH lists be reassigned (the old `"a.binaries = ["` assertion broke on the refactor — good, it was too literal). **Verified:** 44/44 packaging+notices tests; the filter helper unit-exercised on synthetic run-1 + run-2 TOC entries (5 dropped, `libopenblas`/nested `pxr/plugInfo.json` untouched, no-op path returns the same object); verifier re-probed under WSL against a payload shaped **exactly like run 2** (4 hits + the "swept, not linked" line) and with `readelf` hidden behind a minimal `PATH`. ❓ **Unverified on a runner:** that the payload is now clean — needs run 3. 💡 **Generalizable lesson:** on a conda build `hook-numpy` rakes the whole env `lib/` for numpy's dependency closure and files it as *data*, so a payload file need not have been imported or linked by anything | live-test-pending | **P1** | agent | `Reference/packaging.md` § *Payload verifier*; `Reference/licensing.md` § *The Linux toolchain rows*; answers the ❓ in `CS-153` |
| CS-158 | **The release version guard had NEVER worked: both workflows parsed `src/__version__.py` with an UNANCHORED regex that matched the module docstring.** Surfaced by the first PR into a `release/X.Y` base: `__version__ 'Single source of truth for the application version.\n0.1.0-alpha.1' is not valid semver`. **Root cause:** `version=$(grep -oP '"\K[^"]+' src/__version__.py)` in **both** `ci.yml:44` and `release.yml:38` — the file opens with a docstring, so the third quote of `"""` starts a match and line 1 of the prose is emitted ahead of the version (two matches → a two-line `$version`). The four `exec`-and-print readers (`build.bat`, `makefile`, `packaging/debian/make_deb.sh`, `cellsmith.spec`) never had it. **Fix:** new **`.github/scripts/read-version.sh`** — one shared reader (the same argument that already made `verify-payload.sh` shared; two inlined copies were wrong identically). It anchors to `^__version__`, semver-validates, and hard-errors on **0 or >1** assignments (⭐ *why >1 matters:* `exec` readers keep the **last**, text parsers the **first**, so a duplicate silently decouples the git tag from the payload version); diagnostics → stderr so `$(...)` stays clean. Both workflows now call it and keep only their own branch-comparison logic. ⚠️ **Uses POSIX `sed`, NOT `grep -P`** — PCRE grep is not portable, Git Bash refuses it (`grep: -P supports only unibyte and UTF-8 locales`), which would make the reader untestable on a dev machine though fine on the runner. **Discovered by probing the reader locally — the first version used `-P` and failed immediately here.** New **`tests/test_version_source.py`** (7 tests, tier-1, pure file reads): one assignment, semver, text-parse == `exec`, no workflow re-inlines a parse, reader avoids PCRE grep, plus a self-check that the docstring collision still exists (fails loudly rather than becoming a no-op). **Verified:** 57 passed under the CI marker expression; the reader probed against real + 4 synthetic files (missing / none / duplicate / bad-semver / docstring-shaped → all correct); ⭐ **the real `version-check` and release `version` job bodies EXTRACTED FROM THE YAML with PyYAML and executed locally** — `base=release/0.1` now passes (`OK: __version__ '0.1.0-alpha.1' matches target branch 'release/0.1'`), `release/0.2` errors on the minor mismatch, `main`/`dev/*` skip, and the release job derives `tag=v0.1.0-alpha.1 prerelease=true`; all four new guards **mutation-verified** in a scratch tree copy | done | **P1** | agent | `Reference/packaging.md` § *Version reading is a SHARED SCRIPT*; `Reference/testing.md` |
| CS-159 | **`make build` failed AFTER successfully building the `.deb`: `make_deb.sh` line 200, `printf: write error: Broken pipe`.** Two independent defects in the self-check block, both invisible until a REAL payload. **(1) SIGPIPE:** checks were `printf '%s\n' "$contents" \| grep -q PAT`; `grep -q` exits at the first match and closes the pipe, and the real listing (2111 files, ~200 kB) is far past the 64 kB pipe buffer, so `printf` was still writing. ⭐ **The bug fires only when the check SUCCEEDS** (an early match is what closes the pipe) **and only when the listing is big enough to block** — precisely why the WSL synthetic-payload verification missed it. **(2) `set -e` made `check()` unreachable:** with `-e`, a bare `cmd; check $?` aborts before `check` runs, so `fail`, every `FAIL` line and the "self-checks failed" summary were dead code — a failing check surfaced as a bare `make: *** Error 1` naming nothing. **Fix:** `dpkg-deb --contents` written to a file once (inside `$STAGE`, so the EXIT trap cleans it) and `grep -q` the FILE via a `has()` helper whose failure is TESTED, never bare. Added a **10th check — no GPL readline in the `.deb`** (the payload verifier only ever sees `dist/CellSmith`; the `.deb` is a separate distribution), filename-anchored so "history" can't false-positive. **Verified in WSL:** the old form exits **141** (SIGPIPE) printing nothing; the new form passes; a deliberately-broken payload prints `FAIL Qt plugins collected`, still runs the remaining checks, and exits 1 with the summary; and a **full synthetic `.deb` build ran the REAL script end-to-end** (2200-file padded payload to exceed the pipe buffer, `PYTHON=` shim standing in for Pillow) — all 10 checks ok | done | **P1** | agent | `Reference/packaging.md` § the `.deb` |
| CS-160 | **⭐ THE PR GATE NOW BUILDS THE FULL RELEASE ARTIFACTS — one composite action per OS, used by both workflows (ADR-0009, user-requested).** `ci.yml` ran PyInstaller only ("~15 min shorter"), so tar.gz / `.deb` / zip / Inno installer, the conda-on-PATH-for-cmd step, the ISCC discovery step and the artifact assertions all ran for the first time **during a release**. Both of the week's costliest defects lived in that unrun half (`CS-158`, `CS-159`). **As-built:** `.github/actions/build-{linux,windows}/action.yml` hold free-space + system libs (incl. `dpkg-dev fakeroot`) + conda + `make build` / `build.bat ci` + `verify-payload.sh` + **artifact-existence assertions**; both workflows `uses:` them; `release.yml` keeps only collect + upload + tag. ⭐ The "no installer was produced" assertion **moved out of release's collect step into the shared action** — `build.bat` only WARNS when ISCC is missing, so that check has to be where the gate sees it. Also: `version-check` now validates parse+semver on **every** PR (branch-match still release-only), and the spec's own prints got `flush=True` (PyInstaller logs to stderr unbuffered while the spec's stdout is block-buffered, which had put the readline-drop lines *after* "Build complete!"). **New `tests/test_ci_release_parity.py` (8 tests) enforces the parity**: same composite action in both workflows, ci's build job a prefix of release's, release's extra steps limited to collect/upload, no inline `make build`/`build.bat`/`PyInstaller`/`verify-payload.sh` in either workflow, and the action really builds + verifies + asserts. **Verified:** 4 YAML files parse; step lists diffed programmatically; parity guard **mutation-tested** (inline freeze → 3 failures; an extra release-only build step → 1); the rewritten `version-check` body extracted from the YAML and run for `release/0.1` ✓, `release/0.2` ✗, `main`/`dev/*` skip. ⚠️ **Cost: the gate is ~15 min longer per PR** — escape hatch if that bites is a `paths`-filter or label-gated job, NOT a cheaper build. ~~❓ **Unverified on a runner:** composite-action resolution~~ **✅ CONFIRMED on the Linux runner:** `Run ./.github/actions/build-linux` resolved, and every step ran — free space (1m23s), system libs (10s), conda (1m9s), `make build` (5m41s, **all 10 `.deb` self-checks ok** ⇒ `CS-159` is runner-confirmed), `verify-payload.sh` **fully green incl. `no GPL readline in the payload (0 hits)`** ⇒ `CS-157` is runner-confirmed. Only the last step failed → `CS-161`. ❓ Still unverified: the Windows `shell: cmd` step inside a composite | live-test-pending | **P1** | agent | ADR-0009; `Reference/packaging.md` § *The PR gate runs the RELEASE build* |
| CS-161 | **⛔ UNEXPLAINED: my own `Assert both … artifacts were produced` step printed both `ok` lines and then exited 1.** Log: `ok dist/CellSmith-v0.1.0-alpha.1-linux-x86_64.tar.gz (481M)` / `ok dist/cellsmith_0.1.0~alpha.1_amd64.deb (315M)` / `Error: Process completed with exit code 1`. Both branches took the success path, so `rc` was never set to 1 and no `::error::` was emitted — yet the step failed. **NOT REPRODUCIBLE LOCALLY:** the script extracted verbatim from the YAML and run as `bash -e -l script` in WSL, with files of the same names (including the `~` in the `.deb`), exits **0**. Ruled out by probe: CRLF (file and committed blob are LF-only, no `.gitattributes`), YAML mangling (extracted bytes match the file), a stray third loop iteration, and an `::error::` hidden in the annotation stream. **Fix = remove the two variables I could not inspect, and make the next occurrence decisive** rather than guess: the step now uses **`shell: bash`** (`bash --noprofile --norc -eo pipefail`) instead of `bash -el {0}` — it only globs and stats files, so loading the conda login profile was never justified — drops **`compgen -G`** for a plain glob loop, and **prints `verdict: rc=N` before exiting**. ⭐ If a future log shows `verdict: rc=0` and the step still fails, the cause is provably the shell wrapper and not the script; the first version could not distinguish those, which is what cost the round-trip. ⚠️ The glob loop uses `if [ -e "$f" ]; then …; fi`, **never** `[ -e "$f" ] && hit=$f` — under `-e` the no-match path would abort the script, the same trap as `CS-159`(2). **Verified:** both scripts extracted from the YAML and run under GitHub's exact `shell: bash` invocation across all 6 cases (both present → rc=0; each one missing; both missing → **both** errors reported, not just the first). Parity test tightened: it pinned `compgen -G`, which kept passing on a file whose only `compgen` was in a COMMENT — it now asserts the step exists, can emit `::error::`, and prints its verdict. ❓ **Root cause still unknown** — the fix is a variable-elimination, not a diagnosis | live-test-pending | **P1** | agent | `Reference/packaging.md` § *The PR gate runs the RELEASE build* |

> ⚠️ **CS-151…CS-155 are verified LOCALLY ONLY** (Windows, 51 passed bare-`pytest`; 50 passed under the Windows-CI marker expression; the licensing fix against a synthetic Linux `conda-meta`). **No CI run has been made since.** The Linux-specific halves — the `pythonpath` fix on the Linux runner, the eight real GPL rows, the `@v4` bump, the new `verify-payload.sh` readline assertion against a real frozen payload — are all **unconfirmed on a runner**. Next session: push and read the run.
>
> **PARTIAL UPDATE (2026-08-04):** **two** `build-linux` runs have now happened. Both got all the way to the payload verifier, which passed **every** check (Qt platform plugin, 150 OCCT libs, OCCT resources, 112 pxr files, 382 VTK libs, notices + LICENSE + OFL, `--version`, all 12 workers) **except the readline assertion — run 1: 3 hits, run 2: 4 different hits by a different route → `CS-157`**. So the freeze itself, the Linux system-library list, and the worker/hiddenimports derivation are now runner-confirmed **twice**; the `pythonpath` fix and the eight GPL rows in `test-linux` are still unread.

New backlog items take the next `CS-` id and bump **next-id**. On start, set Owner + State; on ship, mark it done (it migrates to history on the next gardening pass).

---

## Status (as built — all user-live-tested unless noted; no GPU in dev env)
- **ROUND 25 — the round-24 "5b" hunt is CLOSED: it was `GetShape(product)` staleness
  (CS-125).** ⚠️ Round 24's exoneration of the merge-then-edit path below rests on the
  claim that *"the bodies it rebuilds come from `GetShape(prod)`, which already composes
  the `T⁻¹`-compensated children."* **That premise is FALSE** — on the real testB2 docs
  `GetShape(product)` returned the PRE-re-origin frame (measured with exact vertices;
  the round-24 probe used a synthetic fixture, where OCC *does* refresh the compound,
  and a `brepbndlib` bbox that inflates without triangulation). The bodies were baked
  displaced by the whole `/Body` origin frame F. Round 24's *other* findings still hold
  (the asset root IS identity in both stages; the asset carries only `splits`) — they
  were just measuring the frames, and the frames were never the problem. Detail: CS-125.
  The OCC rule behind it is now measured, not ❓: **`UpdateAssemblies()` sees a
  component-location change only when the component references a LEAF, never an
  ASSEMBLY** — so a re-origin (pure child-location surgery) leaves the parent product's
  compound stale on disk. Fixed at source too (`refresh_assembly_compound`).
- **ROUND 24 — 5b probed, three mechanisms ELIMINATED, defect not yet located.**
  Two scratchpad probes, both artifact-based:
  `scratchpad/assembly_split_origin_probe.py` (synthetic XCAF fixture) —
  `_replace_assembly_children` preserves **both** the instance location (where
  `_reorigin_assembly_once` stores the FRAME: `inst' = inst·T`) and the composed
  product bbox. It never touches the instance label, and the bodies it rebuilds come
  from `GetShape(prod)`, which already composes the `T⁻¹`-compensated children. **So
  that function is exonerated** — my round-23 hypothesis was wrong.
  `scratchpad/asset_body_root_frame_probe.py` (the REAL `asset-Body` cache, which has
  both stages on disk) — the asset ROOT's 4x4 is **identity in `geometry-source.xbf`
  AND in `geometry-main.xbf`**; rotation and translation both preserved across its
  own split bake. Its bake stamp shows `origins {}`, `transforms {}`, `structure {}` —
  **the asset model carries nothing but `splits`**, so nothing at the asset level can
  re-frame its root. The split does apply the recipe's per-body origins (Link1 lands
  at `(0, 0, 122.7)` = the stored `o2:0` origin), which is correct.
  **What this leaves:** an asset root's frame is identity BY CONSTRUCTION —
  `asset_root_declares_origin` → generation uses `R_root=identity` so the asset is
  authored IN the chosen origin's frame. Viewing that asset, the root's origin
  indicator therefore draws at the world origin with world axes, which may be exactly
  what the user is calling "wrong" — the chosen origin is expressed as the asset's
  local frame, not as a visible triad. NEEDS: which node's indicator, in which model.
  ⚠️ Note for future comparisons: `asset-Lid` has ONLY a `bake-stamp.json` (no
  geometry), so Lid is not a valid without-edits control.
  **A gap worth its own fix regardless:** `TDocStd_Document` created without an owning
  application SEGFAULTS on the first XCAF call with no traceback — probes must build
  the doc via `cache._application().NewDocument(...)`.
- **ROUND 23 — badge REVERTED (option C); merge selects its result; and a CORRECTION
  to round 22's root cause.**
  - **⭐ CORRECTION, and it matters: round 22 claimed the `/Body` asset's split recipe
    was a stale ROBOT-ARM recipe wrongly attached. That is probably WRONG.** `/Body`
    genuinely contains `41099_Fanuc_CRX-10iA_Zero Position#2`, so `initial_count: 117`
    with bodies named `Base/Link1…Link6` is plausibly CORRECT for it — and per-body
    origins near `(0, 0, 122)` are LOCAL coordinates, which is what an asset authored
    with `R_root=identity` should have. The user then re-authored body edits and got
    the same shape, which is the tell. Do not treat "origins look small" as evidence
    of staleness. The real 5b defect (asset origin right in the Source/Component
    editors, wrong in Main) is **UNDIAGNOSED**.
  - **Badge removed (5a → option C).** Gating on "a recipe exists" fired the instant a
    LEGITIMATE edit was authored. A warning that is always on is worse than none.
    `set_assets` no longer prefixes ⚑ or sets a tooltip; the note now only gates and
    labels *Clear Body Edits…*. Distinguishing stale from fresh needs the recipe to
    record what geometry it was authored against — a stored-format change, deferred to
    the fingerprinting redesign (option A, offered and declined for now).
  - **Component Editor: a merge now SELECTS its result** (`_select_body_lids`, called
    from `_cmd_merge` with `f"{op.op_id}:0"`). `_refresh_bodies_tree` clears and
    rebuilds, so any command that PRODUCES a body must re-assert the selection —
    otherwise the thing you just made is the one thing not selected.
  - **Process:** three wrong root-cause calls today (round 20's pick-layer, round 22's
    stale-recipe, plus the `r_inv` guess for USD). Every one came from reading code and
    inferring; every correction came from reading an ARTIFACT (crash log, `main.usda`,
    the config). Read the artifact first.
- **ROUND 22 — OPEN, two user-reported issues; no code written yet.**
  1b. **ROOT CAUSE CONFIRMED + interim fix SHIPPED (option A).** Config evidence:
     `assets["Body"].splits["/"]` carries `initial_count: 117`, 8 merge ops, body
     names `Base/Link1…Link6`, and **6 per-body `origins` in LOCAL coordinates**
     (`~(0,0,86)`, `~(0,-120,245)`) — while `/Body`'s Main origin is
     `(-4600, 1050, 770)`. That recipe belongs to the robot-arm asset (`Drone_Body`
     and `Drone Body` carry the same 117-body shape), not to the `/Body` folder.
     `splits` run FIRST in the bake, so those local origins re-frame the bodies and
     the asset lands **near the world origin** — exactly the report. **A split
     recipe carrying `origins` is not a body edit, it is a placement.**
     Shipped: `MainWindow._asset_body_edit_note` + a ⚑ badge and tooltip on the
     Model-Tree asset row, and a narrow **Clear Body Edits…** item that drops ONLY
     the split map (origins/joints/restructure kept), behind a confirm. Passive by
     design — it makes the state visible; the user decides. Verified
     `scratchpad/asset_body_edit_badge_test.py` (**12 checks**, incl. the real
     testB2 section). Options B (prompt at generation) and C (auto-invalidate) were
     offered and NOT taken; C was advised against (destroys work automatically).
     **Two follow-up bugs in that first cut, both mine, both fixed:** (a) the handler
     called `store.save_active()`, which takes a required `config` argument — it
     RAISED after the config write but before `_refresh_model_tree()`, so the clear
     persisted while the badge looked stuck ("clicked yes, nothing happened").
     `_set_raw_map` already calls `_write()`; there is nothing to save afterwards.
     (b) the note was looked up with `_model_label(model)` (`"Asset: Body"`) instead
     of the bare NAME — an empty note, and worse, `_section()` CREATED a junk
     `"Asset: Body"` config section (removed; it was empty). New `_asset_name_of`
     keeps the DISPLAY label and the KEY apart. The dialog now offers **Clear and
     Regenerate** / **Clear Only** and states that the on-disk asset keeps the old
     edits until regenerated — `_on_update_assets` would NOT have helped, since it
     only regenerates the MARK DIFF and leaves kept assets untouched.
     ⚠️ **The fixture is live**: this suite asserted against the real `Body` section
     and broke the instant the user cleared it — the SECOND time that happened today.
     Real-config assertions are now invariant-shaped (synthetic recipe + an
     opportunistic sweep of whatever still has splits).
  1. **Stale asset-section BODY EDITS silently win.** User: assets all looked right in
     Main, but the generated `/Lid` asset had a wrong origin position *and*
     orientation. Cause found by the user: body edits authored in the generated asset
     long ago were still in that asset's config section and were re-applied over the
     current geometry. Nothing warns. Fingerprinting will fix it properly in the
     redesign; the interim question is warn-vs-invalidate (options in the ledger:
     prompt at generation, a stale badge + explicit clear, or auto-drop). **User work
     must not be destroyed automatically** — prefer surfacing over invalidating.
  2. **Asset origin ORIENTATION in USD — NOT a defect; the rotations ARE exported.**
     Settled by reading the actual output (`testB2.cellsmith.output/main.usda`, written
     18:18 this session), not by reasoning: every occurrence prim carries a full
     `matrix4d xformOp:transform` with rotation — e.g. `Lid` = 180° about Z at
     `(-3.1, 1.75, 0.7696)` m, matching the stored origin `(-3100, 1750, 769.6)` mm;
     `Connector` 90° Z; `MoldTop` −90° Z. The per-asset wrapper (`Lid.usda`) is a
     typeless `def "Root"` with only a reference and NO xformOp, so it correctly
     inherits the occurrence placement. Remaining explanation is on the VIEWER side:
     Isaac's gizmo in **World/Global** mode always draws scene-aligned axes regardless
     of the prim's rotation, and a child MESH prim legitimately has an identity local
     transform (frame-vs-baked invariant — only frame'd prims get a live Xform), which
     matches "all children too". **Lesson repeated: read the artifact.** My two
     candidate mechanisms (`r_inv` de-rotation, the root-frame discard) were both
     wrong, and one `grep` of the output file settled what a chain of code reading
     could not. HISTORICAL, superseded — original note follows:
     **Asset origin ORIENTATION does not survive USD export.** In Isaac each asset's
     geometry lands correctly and its origin POSITION is right, but the origin's
     ORIENTATION is the scene's, not Main's. Established so far: `write_composed_main`
     authors a full 4x4 via `_set_transform_op`, so rotation *can* be exported;
     `compose_cli` sets `r_inv = I` (full `W_occ`, rotation kept) only when
     `asset_root_declares_origin` is True, else de-rotates with
     `_rot_inv4(occurrence_pose(...))` and bakes the rotation into the points — which
     is exactly this symptom. testB2's root stamp DOES list all six folders in
     `folder_origin_frame_paths`, so that predicate should be True — **so the simple
     explanation does not hold and the cause is NOT yet identified.** Second candidate:
     `_compose_usd` drops the single asset root from the live-frame set
     (`frames.discard(_croots[0])`, compose_cli ~line 181) on the assumption that the
     placement absorbs its frame — that interacts with the `R_root=identity` geometry.
     ⚠️ Also noticed: `folder_origin_frame_paths` lists folders whose `origin` is
     `null` (Butler/MoldTending/MoldTop) — if that key is meant to list only folders
     WITH a custom origin it is over-inclusive, which would make
     `asset_root_declares_origin` true for assets that declare nothing. Unverified.
- **ROUND 21 — the heap-corruption crash: real cause found (round 20's was WRONG).**
  The crash repeated after the round-20 revert, same stack, same `0xc0000374`, this
  time picking a DATUM during ReOrigin. So posing the pick layer was **not** the cause
  — it was one instance of the hazard, not the source.
  **⛔ THE INVARIANT: an edge-pick subset must OWN its point buffer.** Both subset
  builders installed another mesh's points without copying —
  `selection_filter.pv_polydata_lines` (`sub.points = np.asarray(points)`, callers pass
  `poly.points`) and `edge_pick.subset_arrays` (`sub.points = poly.points`). Those are
  live views onto the source's VTK buffer, and **pyvista installs a numpy array into a
  new mesh zero-copy** — probe-verified: with `np.asarray`,
  `np.shares_memory(sub.points, src.points)` is `True`; with `copy=True` it is `False`.
  So the CACHED whole-model layer and every armed subset shared one buffer; dropping any
  one can free it under the others, and the fault surfaces later at an unrelated read
  (`poly.lines`) with no Python traceback. Both sites now deep-copy.
  **⭐ WHY NO TEST CAUGHT IT — the generalizable lesson.** Every edge suite asserted
  numpy **values**, and values are identical whether a buffer is shared or copied.
  Aliasing is invisible to a value assertion; it needs a **memory** assertion
  (`np.shares_memory`). New `scratchpad/edge_poly_aliasing_test.py` (**16 checks**)
  asserts non-sharing for both builders, for a subset-of-a-subset chain (which
  `_append_datum_edges` creates), and survives the build-drop-read ordering that
  triggers the use-after-free.
  **Process note: I called a root cause twice from a stack trace and was wrong the
  first time.** The stack named the *victim*, not the writer. What actually settled it
  was a probe (`shares_memory` before/after), not more reading. 25-suite sweep green.
  ❓ Whether this was the ONLY writer on that path is unverified until the user retests.
- **ROUND 20 — my round-17 edge fix CRASHED THE PROCESS; reverted.** User hit a hard
  crash starting a ReOrigin: `cellsmith_crash.log` shows Windows `0xc0000374`
  (**heap corruption**), no Python traceback, current thread in
  `pyvista …/pointset.py:1018 in lines` ← `selection_filter._apply_info_mask` ←
  `_subset_edge_data` ← `_arm_edge_layer` ← the CGB re-arming after an edge pick.
  **Cause:** round 17 posed the pickable-edge layer by assigning
  `_edge_pick_mesh.points`. That layer is **not privately owned** —
  `_apply_info_mask` builds every armed subset with `pv_polydata_lines(poly.points, …)`,
  which wraps the array **zero-copy**, so several PolyData share one buffer. Replacing
  it frees memory the others still hold; the fault then surfaces at the next read, far
  from the write. **Reverted** (`_apply_pending_pose_pick_layer` deleted). The pick
  layer stays in the baked pose while an edit is pending — its wireframe lags and its
  hit test resolves against the old position. **CS-111 is therefore only PARTLY
  closed**: the shaded mesh, the feature-edge overlay and the tess wireframe still move
  together (that was the visible symptom); the pick layer is out of scope for good.
  **⭐ INVARIANT, recorded at the call site and in `geometry-edits.md`: never write
  `_edge_pick_mesh.points`.** A lagging overlay is cosmetic; heap corruption is not, and
  it is invisible to every headless test — the suite that "covered" the pick-layer pose
  asserted numpy values and could not see the aliasing. **Lesson: mutating a
  VTK-backed buffer that another subsystem may have wrapped zero-copy is not a local
  change**, and "it passes headless" is not evidence of memory safety.
  Also fixed this round, and confirmed by the user: `/Body`'s origin orientation
  (re-applying ReOrigin corrected the stored value written under the round-19 bug).
  23-suite sweep green.
- **ROUND 19 — the origin indicator DOUBLE-APPLIED a pending transform (found by the
  user's own diagnosis; headless-verified, GL re-test PENDING = CS-021).** Report:
  *"it did rotate 90 Z, but the origin preview rotated 90 Z further than the
  component"*, unchanged after a rebake; `/Body` the same, `/Connector` fine.
  **⭐ THE RULE: the pending-origin branch of `_pending_frame_map` is ABSOLUTE.**
  `_origin_capture_frame(to_display=True)` already maps the stored frame through the
  FULL stored transform (`Φ·T_stored`); composing the pending pose delta
  (`Φ·T_stored·T_baked⁻¹·Φ⁻¹`) on top applies that transform a SECOND time. Position
  looked right because both terms carry the same translation — only the doubled
  ROTATION was visible, which is why this survived a suite that only checked
  positions. The no-custom-origin branch is unchanged (baked frame × delta) — the two
  branches are computed differently and must never be mixed. `/Connector` was fine
  because its origin predates its transform, so the frames coincided.
  **Second half, why a rebake did not clear it:** the success path reset
  `_pending_frames` but left the `set_frame_override` CLOSURE installed, and that
  closure captured the old map by value — the indicator kept drawing the pre-bake
  frame for the rest of the session. Now dropped explicitly at the bake.
  **A test was WRONG, not just missing:** `deferred_bake_test`'s `FrameHost` stubs
  `_origin_capture_frame` to identity, so "origin + transform compose" passed *because
  of* the double-apply. Corrected to model the real capture frame, plus an assertion
  that the answer is NOT the doubled one. **Menu gates + a frame READOUT** shipped in
  the same round (see ROUND 18 below and `_report_selected_frame` — the user had no
  in-app way to measure an origin, so a live bug could be described but never
  quantified). 21-suite sweep green.
- **ROUND 18 — a restructure FOLDER's edits must be findable BY PATH, always
  (headless-verified against the REAL testB2 config + bake stamp; GL re-test PENDING
  = CS-021).** Live report: ReOrigin on `/Connector` and `/Lid` showed no origin
  before rebake; after rebake `/Connector` was right and `/Lid` was wrong.
  **Evidence first** — reading `test_files/testB2.cellsmith.json` and
  `testB2.cellsmith.cache/bake-stamp.json` (they AGREE, so this is not stamp drift):
  `/Body` and `/Connector` transforms carry `provenance: {"path": …}`, **`/Lid`'s
  carries `{}`**. Two independent holes:
  1. **A folder origin is not in the origin map.** It rides the STRUCTURE map, keyed
     by folder id — and `_pending_frame_map` read only `get_origin_map`, so a folder
     ReOrigin had no pending frame to show. New `_origins_by_path()` unions both; the
     Transform pivot reads the same union (one parse, replacing the old
     origin-map + `_folder_origin_paths` pair).
  2. **An unstamped entry was invisible to every by-path consumer** — absent from
     `_transforms_by_path`, so it took no part in ancestor compensation and a ReOrigin
     inside it was stored uncompensated. New `restructure.folder_tree_path(smap, fid)`
     DERIVES the path from the folder chain; a stamp still wins (rename-safe), and
     `_origin_target_path` now prefers `self._origin_cid` — the actual open node —
     over any stamp at all. **This closes CS-110**, which had been filed as narrow.
  Also: the already-baked identity skip is now scale-aware. **Correction to my own
  first claim** — I asserted a fixed `atol=1e-12` was failing on mm-scale models;
  probing both real testB2 matrices REFUTED that (`/Body` inverts exactly; the 135°
  `/Connector` leaves 9.1e-13, inside budget). It is a thin margin, not a live bug,
  and the change is preventive. Verified: new `scratchpad/folder_path_recovery_test.py`
  (**24 checks**, incl. assertions against the real config + stamp), plus stale
  assertions corrected in `origin_order_test.py` (it encoded CS-110 as intended
  behaviour). 21-suite sweep green.
  **Menu gates are now PER NODE.** *Clear Origin* was gated on
  `_model_has_any_origin` and *Clear Transform* fell back to "does the model have ANY
  folder transform?" — so once one folder anywhere had been edited, both appeared on
  every node, where they could only no-op. Both were coarse because "which folder is
  this node?" had no synchronous answer; by-path resolution supplies one, so
  `_node_has_origin` / `_node_has_transform` are exact (new `_node_path` helper).
  Remaining gap, unchanged: a structure-MOVED component is keyed by its
  pre-structure path and still won't match — same as the tree glyph.
  **`/Lid` origin still wrong in Main — diagnosed as far as the data allows, NOT
  fixed.** Ruled out by measurement: (a) not a stale bake — config (16:56) and stamp
  (16:57) hold byte-identical folder entries, so Main reflects what is stored;
  (b) not a missing stamp — `/Lid`'s origin carries `path: /Lid`; (c) not transform
  compensation — the user has since CLEARED `/Lid`'s transform, so the capture frame
  is orientation-only; (d) the stored value round-trips exactly under the model's
  `up_direction: +Y` frame — source `(-3100, 769.6, -1750)` ↔ Main
  `(-3100, 1750, 769.6)`. The stored number is therefore self-consistent, which puts
  the fault between where the user PLACED the origin and that coordinate. Needs the
  drawn-vs-intended Main coordinates to go further. **⚠️ The fixture is LIVE** — the
  suite originally asserted "Lid is the unstamped one" and broke when the user
  cleared it; real-config assertions must state INVARIANTS, not snapshots.
  **STILL UNEXPLAINED:** *"rotating /Connector made /Body translate to a new wrong
  position"* in the pending preview. Ruled out by measurement, not argument: config
  and stamp read to the SAME by-path transforms (asserted in the new suite), so there
  is no phantom `T_stored · T_baked⁻¹` delta for `/Body`. Needs a narrower repro.
  Separately explained WITHOUT a code defect: `/Body`'s stored `pivot`
  (`-4600, 1050, 770`) is its bbox centre, not its custom origin (`-4147, 770, -1300`
  source → `-4147, 1300, 770` Main) — that transform was authored under the round-17
  stale-pivot bug, so its origin legitimately bakes to the wrong place until the
  transform is re-applied.
- **ROUND 17 — two live reports on the deferred-bake preview (headless-verified, GL
  re-test PENDING = CS-021).** Round 16's hang is CONFIRMED FIXED by the user.
  1. *"edges didn't move (still in the original position like before the transform)"* —
     **CS-111**, previously accepted at P3. The report reframes it: an edge wireframe
     left around the body's old position doesn't read as "an overlay lags", it reads as
     "the transform didn't take". Now every world-baked layer moves together through one
     `ViewportPanel._posed_points` kernel — combined mesh, feature-edge overlay
     (per-cell map scattered onto endpoints, cached), tess wireframe (rebuilt only when
     visible), and the pickable-edge layer (**locator rebuilt too** — moved points with
     a stale locator mis-hit silently). Deliberately skipped above `_EDGE_DRAW_MAX`,
     where the layer draws nothing: a locator rebuild over 1.1M edges has no business on
     a preview tick. Every overlay failure is swallowed — cosmetic, never fatal.
  2. *"the /Body component translated when it shouldn't have"* — **the pivot was read
     from the BAKED frame.** With the deferred bake, an unbaked ReOrigin does not touch
     `comp.transform`, so `_transform_pivot` pivoted about the node's OLD origin and a
     rotate became a rotate-plus-swing. New `_current_node_frame(cid, comp)` returns the
     cached `_pending_frames[cid]` first; it feeds both the pivot and the pane's
     *from*-basis. The cache is filled by `_refresh_pending_state` (which computes those
     frames anyway for the origin indicator) and dropped when a bake lands — **not**
     recomputed on pane open, which is the round-16 mistake again.
  Verified: new `scratchpad/pending_pose_edges_test.py` (**31 checks**, incl. a guard
  that the pose kernel stays BLAS-free and that the over-cap path pays nothing) +
  `transform_gui_offscreen.py` → **33**; 20-suite sweep green. Stale doc corrected:
  the PIVOT section still described the deleted `_refine_transform_pivot_async`.
- **TOOLING — the doc-flush gate was self-defeating.** `SessionStart` re-stamped
  `.claude/.session-flush-marker` on `source=compact|resume`, so compacting erased the
  evidence that the session had already flushed and the *next* `/compact` blocked a
  session whose docs were current. Guarded (`matcher: "startup|clear"` + an inline
  `case` on the payload). The block now also emits a **`systemMessage`** — `reason` is
  addressed to Claude, and someone new to this repo needs to be told in their own words
  what the gate is, why it fired, and both ways forward (`/precompact`, or
  `touch .claude/.skip-flush-gate`). Both marker files are gitignored (`.gitignore:4-5`)
  and must stay so: one is a per-session timestamp, the other a single-use consumed flag.
  All four hook branches probe-verified as valid JSON.
- **ROUND 16 — opening the Transform pane hung for minutes (my round-11 regression;
  headless-verified, GL re-test PENDING = CS-021).** User: setting a transform on
  testB2 `/Body` popped *"Loading base structure…"* and sat there. **Cause:**
  `_resolve_base_path` shows a busy dialog and background-loads the PRISTINE BASE
  whenever a structure map exists; round 11's `_refine_transform_pivot_async` called
  it from EVERY `_start_transform` (and the round-14 Edit preload could fire a second
  one). Before round 11 it ran only on Apply/Clear. **Fix:** a folder's custom origin
  is now found SYNCHRONOUSLY — `_apply_folder_origin` stamps `provenance["path"]`
  (same trick as folder transforms) and `_folder_origin_paths()` reads it, so
  `_transform_pivot` needs no resolve; **`_refine_transform_pivot_async` deleted**.
  Plus `_resolve_base_path(..., allow_load=False)` for opportunistic callers (returns
  None rather than loading) — used by the Edit preload. Only Apply / Clear / opening
  ReOrigin still load. LEGACY caveat: a folder origin written before the stamp has no
  path and is missed until re-applied. Verified: `transform_gui_offscreen.py` **30
  checks** incl. a guard that opening the pane resolves NOTHING; full sweep **47/47**.
  **Pattern worth remembering: three of my last four regressions were an expensive
  call added to a hot/interactive path** (per-component config parse, stamp I/O on
  every UI sync, and now a base-structure load on pane open).
- **ENV FIX — `conda run` HANGS FOREVER on non-ASCII test output under Git Bash
  (root-caused; not a code bug).** A test "ran for 34 minutes" that completes in ~3 s
  under PowerShell. **Chain:** `conda run` (without `--no-capture-output`) CAPTURES the
  child's stdout and re-prints it via `print(response.stdout, file=sys.stdout)`
  (`conda/cli/main_run.py:120`) → under Git Bash that stdout is **cp1252** → any
  non-ASCII in the suite's output (`→ ⊥ · ✓ —`, which most suites here use) raises
  `UnicodeEncodeError` INSIDE conda → conda prints an ERROR REPORT and **prompts**
  *"Would you like conda to send this report…? [y/N]"* → with no interactive stdin that
  blocks indefinitely. **Fix: always `conda run --no-capture-output`** (streams the
  child, no re-encode), plus `< /dev/null` and `CONDA_REPORT_ERRORS=false` so any
  *other* conda crash fails fast instead of hanging. Verified: the previously "hung"
  suite now runs in 3 s and the **full sweep is 47/47 green IN BASH** (the shell that
  was hanging). Recorded in `Reference/invariants.md` (with the recognise-it symptom:
  hangs in bash, passes in PowerShell) and in the CLAUDE.md verify line, since every
  agent is told to use `conda run`.
- **ROUND 15 — PERF: round 14's refresh hung the UI (headless-verified; GL re-test
  PENDING = CS-021).** User: "that task was running forever." **My defect:**
  `_refresh_pending_state` was O(components × full config parse) —
  `_pending_frame_map` walked EVERY component and called `_origin_capture_frame`,
  which re-parsed the transform + structure maps on each call (thousands of parses per
  refresh on testB2), and `_edits_pending()` read the bake stamp off DISK on every
  `_refresh_rebuild_action`, which fires on every UI sync. **Fixed:** parse once in
  `_refresh_pending_state` and thread `stored=`/`baked=` (plus a `by_path=` on
  `_accum_transform_source` / `_origin_capture_frame`); `_pending_pose_map` skips
  components not at/under an affected prefix; `_pending_frame_map` visits only nodes
  with a pending origin or pose; `_edits_pending()` memoized via `_pending_cache` +
  `_invalidate_pending_cache()` (edit / bake / model commit). Extracted
  `_baked_transforms_by_path()`. **Guarded by a test**, so this can't silently return:
  a refresh over **3000 components parses the config once and takes ~0.1 s** (was
  effectively unbounded). `deferred_bake_test.py` now **62 checks**; full sweep
  **47/47 green**. Also added a `borrow()` helper to the suite —
  `getattr(cls, name)` on a `@staticmethod` silently degrades it to an instance
  method, a trap that had now bitten three separate suites.
- **ROUND 14 — the pending preview now moves the ORIGIN INDICATOR too + a stamp bug
  (headless-verified; GL re-test PENDING = CS-021).** User: "I just ReOrigined /Body but
  Show Component Origin is still at the original location." **Cause:** the triad is
  drawn from the BAKED `comp.transform` (`selection._primary_frame`), so round 13's
  geometry preview couldn't move it — and a pending ORIGIN has no geometry delta at all.
  **Fix:** `_pending_frame_map()` → `SelectionController.set_frame_override` +
  `refresh_origin_indicator`; per node it composes a pending origin's stored frame
  mapped forward (`_origin_capture_frame(to_display=True)`) with any pending transform
  delta, so origin-only, transform-only and both-together all move the indicator.
  **Second bug found while checking:** `_pending_pose_map`'s BAKED side read only
  `stamp["transforms"]`, missing folder transforms (which live in `stamp["structure"]`)
  — an already-baked FOLDER move would have been previewed a second time on top of
  itself. Both sides now go through one static `_transforms_by_path(tmap, smap)`.
  **Answered (user was right to ask, and the invariant already holds):** the bake is
  ABSOLUTE — every bake restarts from the pristine source stage and applies only the
  stored maps, one entry per path, so repeated edits cannot compound; the preview delta
  is display-only and never feeds the bake. Documented, with the authoring caveat that
  an existing transform must be re-opened via *Edit Transform…* (preloads recipe +
  original pivot) rather than a fresh *Transform…*.
  Verified: `deferred_bake_test.py` at **56 checks**; full sweep **47/47 green**. Hit
  the `@staticmethod`-via-`getattr` degradation trap again in a test harness (now
  commented in place).
- **ROUND 13 — DEFERRED main-window bake (part 2 of 2; headless-verified, GL re-test
  PENDING = CS-021).** Main-window ReOrigin/Transform no longer re-bake Source→Main on
  every Apply: the config is written, the change is PREVIEWED, and the bake runs once on
  **Rebuild** (or implicitly via the existing generate/open-asset prompts).
  Built: `_DEFERRED_KEYS` + deferral in `_apply_geometry_edit` and both folder writers;
  a `_pending_edits` **ledger** (each entry carries an `undo`); `_edits_pending()`
  preferring the durable `cache.main_rebuild_required` so pending state survives a
  restart; `_pending_pose_map()` computing the **unbaked remainder only**
  (`T_stored · T_stamped⁻¹`, accumulated over self+ancestors, pushed to the display
  frame); `ViewportPanel.apply_pending_pose` / `clear_pending_pose` moving the rendered
  points from a pristine snapshot (exact restore, no drift, elementwise);
  `_on_rebuild_clicked` + a `Rebuild (N pending)` label; and
  `_report_pending_bake_failure` which **keeps the config**, names what the bake blamed,
  lists the batch and offers **Undo last edit** (never an automatic batch revert).
  Unchanged by design: the Source Editor's restructure Apply and the Component Editor's
  body edits still bake immediately (splits aren't reachable from the main window).
  **Known caveat:** the preview moves only the shaded mesh — the pickable-edge and
  tess-edge overlays stay in the baked pose until a real rebuild.
  Verified: NEW `scratchpad/deferred_bake_test.py` (31 checks: no-bake-on-edit,
  splits-still-bake, no-op rejection, undo restoring the PREVIOUS value then removing
  the entry, the stamp-delta math, and the viewport preview's exact reversibility) +
  `transform_gui_offscreen` updated to the new contract (**25 checks**); full sweep
  **47/47 green**. Two test-authoring slips caught in the same turn (`rot_about_axis`
  takes RADIANS; a stale grep string).
- **LIVE-TEST FIX ROUND 12 — EDIT-CAPTURE FRAMES: authoring order is now irrelevant
  (headless-verified; GL re-test PENDING = CS-021). ⚠️ PART 1 OF 2 — the deferred
  main-window re-bake (agreed in the same plan) is NOT yet implemented.**
  User report: ReOrigin→Transform rotated about the origin correctly, but
  Transform→ReOrigin put "the part off in some other place". **Cause:** the bake order
  is fixed (`splits→origins→transforms→structure→orientation`) but the capture boundary
  undid only the root Source→Main frame — never a per-node transform. An origin picked
  on a MOVED part was stored as if it had never moved, and the origins stage (which
  runs BEFORE transforms) placed it where the part used to be. **Fix (the user chose
  full compensation over the cheap refuse-with-messagebox):**
  `_origin_capture_frame(base_path, to_display)` composes the Source→Main frame AND
  `_accum_transform_source(path)`, and is used in BOTH directions (store + re-open for
  edit). `_accum_transform_source` walks path PREFIXES composing outermost-first
  (`T_a1·…·T_self`) — derived from `apply_transforms`, where a child ends at
  `T_parent·T_child·W`; `_stored_transforms_by_path` unions the transform map with
  restructure-FOLDER transforms, which `_apply_folder_transform` now stamps with
  `provenance["path"]` so they are findable by path. **Provably inert** when no
  transform exists (identity factor) → no risk to existing projects. **Scope
  correction:** only ORIGINS need this — transforms are applied last, and **split
  planes are safe** because the Component Editor opens from the SOURCE Editor on
  source-stage geometry (my earlier "latent split bug" speculation was wrong).
  **Known gap:** a folder with no transform whose ANCESTOR folder has one isn't
  path-resolvable synchronously. Verified: NEW `scratchpad/origin_order_test.py`
  (19 checks incl. a round-trip identity, and a REPRODUCTION of the reported bug
  through the old code path); full sweep **46/46 green**. Fixed a closure-shadowing
  slip (`raw` rebound inside `_go`) that the offscreen suite caught.
- **LIVE-TEST FIX ROUND 11 — Transform pivots about a node's CUSTOM ORIGIN
  (headless-verified; GL re-test PENDING = CS-021).** User asked what a Main transform
  rotates about; the answer was "the subtree's world-AABB **centre**, always" — which
  for an origin-bearing node is wrong: rotating about the box centre CARRIES the custom
  origin to a new world position, so the part points the right way but its deliberately
  placed link/joint frame **drifts**. New `_transform_pivot(cid, comp)` →
  `(pivot, source_label)` with precedence **custom origin → AABB centre → node frame**;
  the custom-origin case just uses the node's baked frame origin (`apply_origins`
  already re-framed it, so no config lookup is needed to place it). A restructure
  FOLDER's origin lives in the structure map under an id only `_resolve_base_path` can
  name, so `_refine_transform_pivot_async` upgrades the pivot when that lands (and
  moves the pivot-seeded `from_point` with it, unless the user has since picked their
  own). The pane title now NAMES the pivot (`· pivot: custom origin | bbox centre |
  node frame`) since it is not user-settable yet. Existing stored transforms are
  unaffected — each carries its own `pivot`. **Deferred by user request → CS-088:** an
  explicit pivot picker (a CGB Point request in the pane).
  Verified: `transform_gui_offscreen.py` **23 checks** (all four precedence cases incl.
  an origin on a DIFFERENT node not stealing the pivot, + the title/async wiring);
  full sweep **45/45 green**. Caught and fixed a refactor slip in the same turn (the
  bbox-preview local was removed with the old pivot code).
- **LIVE-TEST FIX ROUND 10 — Measure is DIRECT-PICK (auto-accept), not construction
  (headless-verified; GL re-test PENDING = CS-021).** Round 9 armed AXIS for ANGLE but
  that was NOT enough: the user picked the YZ plane + a plane Datum and got "the UI
  looks more like it's defining an axis". **Cause:** the CGB keep-picks — the first
  plane filled E1 and ARMED E2, so the second plane completed ONE
  `axis_plane_intersect` (their intersection LINE, the Y axis in that case) instead of
  being a second axis; nothing was ever delivered, and the bar showed a half-built
  axis with its params/rings. A direct consequence of the Phase-6 keep-picking
  redesign meeting a tool that wants direct selection. **Fix:**
  `ConstructionGeometry.set_auto_accept(bool)` — deliver the FIRST valid construction
  as soon as a pick makes one (deferred one event-loop tick so the pick signal
  completes), no Accept and no further slots; `_arm_measure` sets it plus
  `set_want(WANT_DIRECTION)` for ANGLE so the bar names the request "Direction".
  `set_mode(None)` clears both, so a normal command can never inherit them.
  **Trade-off (documented):** a Measure pick can no longer use a MULTI-slot
  construction (2-point axis, midpoint) because the single-pick form is already valid.
  Verified: `cgb_spec_modes_test.py` **87 checks** — including a side-by-side proof
  that keep-picking turns two planes into their intersection line while auto-accept
  delivers one axis per pick, and that the flag never leaks; full sweep **45/45**.
- **LIVE-TEST FIX ROUND 9 — Measure ANGLE now takes two AXES (two planes work)
  (headless-verified; GL re-test PENDING = CS-021).** User report: "I should be able
  to select two planes in the measure tool to measure the angle between them."
  **Cause:** ANGLE was specified as the 3-POINT apex form (`_MEASURE_NEEDS[ANGLE]=3`,
  armed as POINT), so a FACE pick carried no `.point`, hit the `pt is None` branch and
  was silently re-armed — nothing happened. **Fix:** ANGLE arms **AXIS** and collects
  **2**. The CGB's AXIS target already resolves a flat face to its NORMAL
  (`axis_face_normal`), an edge line, an arc/cylinder axis, or two points — so two
  planes, two edges, edge-vs-plane and cylinder axes all work under ONE rule, and an
  apex angle stays expressible as two axes sharing the apex (4 picks instead of 3 —
  the one convenience regression, accepted for the generality).
  `_draw_measure_angle` rewritten for two axes (stub lines + origin markers, label at
  the midpoint) and **reports θ AND its supplement**, because a picked direction's
  sign is arbitrary (a normal may point either way) — for two planes the acute value
  is the usual answer. New `_measure_axes` state, cleared on mode enter/leave/switch.
  Verified: `measure_modes_test.py` grown to 18 checks (perpendicular / 45° /
  anti-parallel / single-pick-waits / non-directional-pick-ignored / apex-as-two-axes);
  full sweep **45/45 green**.
- **LIVE-TEST FIX ROUND 8 — a user Datum couldn't be picked from the Datums panel
  (headless-verified; GL re-test PENDING = CS-021).** User report: "I can't click a
  Datum (plane) in the Datums pane while selecting with the Measure tool."
  **Cause:** the whole pipeline existed — `viewport.datum_pick_by_key("user:<id>")`
  → `_user_datum_pick` → `SelectionFilter._vp_datum_key_pick` → `item_to_entity` —
  but had **no trigger**: only the fixed global-origin CORNER TREE ever fired
  `on_datum_key_pick`, and `DatumsPanel` emitted only add/rename/delete/visibility.
  A gap from the Datums round, not a regression. **Fix:** `DatumsPanel.pickRequested`
  (row click, with a one-shot `_check_toggled` guard so a checkbox toggle doesn't
  also pick — mirroring the corner tree) → `main_window._on_datum_pick` →
  `on_datum_key_pick(f"user:{id}")`. Visibility ≠ pickability (a hidden datum still
  picks); an unusable datum is a harmless no-op via the SF mode-gate.
  **❗ Known remaining gap:** user datums are still NOT hit-testable in the 3D
  viewport (actors are `pickable=False`; the SF's viewport datum resolvers only
  consult the fixed six) — picking them requires the panel. Recorded in
  `Reference/selection-and-cgb.md`.
  Verified: NEW `scratchpad/datum_panel_pick_test.py` (17 checks, incl. the
  checkbox-vs-pick guard and end-to-end key→descriptor→SelectionItem→SlotEntity for
  a plane AND a basis datum); full sweep **45/45 green**.
- **LIVE-TEST FIX ROUND 7 — Transform on a restructure FOLDER was silently dropped
  (headless-verified; GL re-test PENDING = CS-021).** User report: rotating testB2's
  `/Body` (a Source-Editor folder carrying a custom origin) in Main did nothing.
  **Cause:** the `transforms` map is keyed by a path in the post-split,
  **PRE-STRUCTURE** walk, where a folder doesn't exist yet — so `main_window._go()`
  rejected every `folder:<nK>` key with a status-bar line and wrote nothing (an
  unresolved key would otherwise `raise GeometryEditError` in `apply_transforms`).
  The guard traded a loud crash for a silent discard.
  **Fix (option A, chosen by the user):** a folder transform now rides the STRUCTURE
  map like its origin — `restructure.NewAssembly.transform` + a new
  `restructure_build._apply_folder_transforms` run right AFTER `_apply_folder_origins`
  (origins→transforms, matching the main bake), so the folder's custom joint frame
  moves WITH the part and is unchanged *relative* to it — exactly the requested
  semantics. Pure instance relocation (`T·W`), subtree rides along, planned worlds
  (folder + descendants) restated for `compare_planned`. GUI: `_apply_folder_transform`
  (+ rollback), Clear routing, the coarse `_model_has_any_folder_transform` menu gate
  (mirroring the folder-origin precedent, since `folder_key` lives on the PLANNED
  tree), and an async pane preload via `_fill_transform_pane`. **Any unresolved path
  is now a LOUD QMessageBox** — a built-then-discarded transform must never look like
  a no-op. Existing projects can't be force-rebuilt (the stamp reads the RAW stored
  map, re-dumped only on a structure edit, which rebuilds anyway).
  Verified: NEW `scratchpad/folder_transform_test.py` (24 checks: config round-trip +
  legacy-config load, stage order, relocation math incl. a non-identity parent,
  children riding along, and the origin-unchanged-relative-to-the-part invariant);
  full sweep **44/44 green**. Also repaired two doc-move casualties in the harness
  (`cgb_spec_modes_test` spec path; `transform_gui_offscreen` borrowed-method list).
- **LIVE-TEST FIX ROUND 6 — SECONDARY-axis Flip in the CGB (headless-verified; GL
  re-test PENDING = CS-021).** User-requested: a second **Flip** checkbox for the
  Frame's secondary axis, placed **between the Primary X/Y/Z buttons and the
  "Secondary Axis" label**, visible only when a secondary actually exists.
  `CgbParams.basis_secondary_flip` + `ConstructionGeometry.set_basis_secondary_flip` /
  `basis_secondary_flip()` (reset by `set_mode`/`clear`, threaded through `_params`);
  `_c_basis` negates `ref` AFTER the Reference/angle resolves, so it is a clean 180°
  of the RESOLVED secondary, and the third axis follows the right-hand rule (the frame
  stays right-handed). The bar hides the checkbox unless `basis_secondary_enabled()` —
  with a free secondary, angle A ±180° IS this flip, so it would be redundant. The two
  flips are independent (`flip` = primary). Verified: `cgb_spec_modes_test.py` **80
  checks** (negation, primary untouched, RH third axis, right-handedness, origin
  untouched, both-flips independence, default off, visibility gate, controller→engine
  plumbing); full sweep **43/43**.
- **LIVE-TEST FIX ROUND 5 — the FIRST-PICKED-POINT Frame origin + an Item-Ledger
  format fix (headless-verified; GL re-test PENDING = CS-021).**
  (a) **Frame origin rule is now UNIVERSAL** (user: "make first picked win as origin
  rather than midpoint"): a Frame anchors at the **first point picked** in every row
  that includes one; only a point-less row falls back to the primary's own anchor
  (edge midpoint / face origin). The plain **2-point Frame moved midpoint → P1** —
  an INTENTIONAL divergence from the retained `_resolve_basis` oracle. Rather than
  edit the oracle (which would erase the parity evidence), `cgb_regression_test`
  gained `case(..., expect_diff=("origin",), why=…)`: the named field may differ
  (reason printed), **every other field stays guarded**, and a field declared to
  differ that MATCHES also fails — so a silent revert of the change is caught too.
  **Axis/Plane anchors are untouched** (2-point axis = midpoint, 3-point plane =
  centroid): for a line/plane the anchor is incidental, for a Frame it is a pose.
  Consequence: the origin is now **order-independent**, while slot 1 still names the
  primary axis — so the two pick orders differ only in *which axis is exact*.
  (b) **`~/.claude/CLAUDE.md` Item-Ledger format fixed**: the Dismissed-Items
  template put `1) Name` and its result on two bare consecutive lines, which Markdown
  collapses into ONE paragraph — the whole section rendered as a run-on. It is now
  **one bullet per item** (`- **#) Name** — result`), with the failure mode spelled
  out so it can't regress; the `response-item-reminders` memory was updated to match.
  Verified: `cgb_spec_modes_test.py` **68 checks**, `cgb_regression_test` green with
  the two intended diffs annotated, full sweep **43/43**.
- **LIVE-TEST FIX ROUND 4 — terminology cohesion + the stale basis-gate bug
  (headless-verified; GL re-test PENDING = CS-021).**
  (a) **Terminology sweep** (user: "revise the spec, docs, src/ … so everything is
  cohesive"): every user-facing "Basis"/"Vertex" string is gone — Component-Editor
  ReOrigin **Orientation**/**Point** buttons, Transform **From / To Orientation**
  (Component Editor + main window), the Add-Datum kind list, the SF's "Edge Vertex"
  group → **Edge Point**, `ConstructedEntity.describe()`. `cgb_core`'s target
  comments now state plainly that **`BASIS` IS the Frame builder** and `FRAME` is the
  COMPOSED variant. `Reference/selection-and-cgb.md` opens with a ⭐ **Terminology
  table** (say → code token) covering both renames, a historical note explaining why
  the `basis`/`frame` split exists, and the **known wart** that two kinds now
  describe the same shape (collapsing them is a deliberate non-goal — it would touch
  `TARGET_KIND`, every kind-guard and `frame_matrix4`). The spec's tables/roles were
  re-headed Frame; `geometry-edits.md` carries a stale-terminology warning.
  (b) **BUG (user-found): Point·Point·Plane left angle A live** — it RESOLVED
  correctly, but three UI gates (`basis_secondary_enabled` / `angle_a_enabled` /
  `_basis_rot_axes`) hardcoded `e3.kind == "point"`, so every non-point secondary
  (a plane normal, an edge direction, the plane-primary E2 slot) still drew the
  angle-A ring — reading as "an axis is undefined". Fixed by giving
  `cgb_recipes` **one shared source of truth**, `_basis_secondary_slots()` +
  `basis_secondary_pinned()`, used by BOTH `_c_basis` and all three gates, so a new
  secondary kind can never leave a stale ring behind again. (Deliberately NOT an
  `assert` cross-check — `resolve()` swallows exceptions, so an assert would silently
  null the construction; the invariant is a test instead.)
  **Answered:** the two pick orders are NOT equivalent by design — **E1 sets the
  primary** — so Plane·Point·Point gives normal-primary/origin-at-P1 and
  Point·Point·Plane gives line-primary/origin-at-midpoint. Both are now fully
  defined. Verified: `cgb_spec_modes_test.py` at **65 checks**, including a 14-case
  matrix asserting `basis_secondary_pinned` ⟺ "sweeping angle A does not move the
  frame"; full sweep **43/43 green**.
- **LIVE-TEST FIX ROUND 3 — the Axis↔Direction / Frame↔Orientation reduction model
  + a Plane·Point·Point Frame row (headless-verified; GL re-test PENDING = CS-021).**
  The user resolved round 2's naming conflict with a better model: *just as an Axis
  can be consumed as a Direction, a Frame can be consumed as an Orientation*, so
  **Frame** is the builder/mode name and **Orientation** is its reduced consumption —
  one pattern applied twice, no separate builders. A **button that requests a
  specific entity must be captioned with what it requests** (Axis / Direction /
  Frame / Orientation) and activate the underlying mode with that constraint.
  Built: `cgb_core.WANT_FULL/WANT_DIRECTION/WANT_ORIENTATION` + `WANT_LABEL` +
  `want_label()`; `CgbCommandBinder.register(..., want=)` → `cg.set_want()`;
  `ConstructionGeometry.want()/request_label()`; the bar titles its params group
  with the request name. Applied to the two mis-captioned consumers: ReOrigin's
  **Orientation** (BASIS + `WANT_ORIENTATION`) and the joint pane's **"Pick
  Direction…"** (AXIS + `WANT_DIRECTION`, was "Pick Axis…" though a joint stores only
  the direction). The spec's entity table was restructured around the reduction rule
  (so the round-2 ⚠️ label divergence is RESOLVED, not merely flagged), the Basis
  section became **Frame (Basis / Orientation)**, and the old "Frame is composed"
  section became **Composed Frame** (an arbitrary Point + an arbitrary Orientation —
  what `FrameBuilder`/ReOrigin does, still needed when the origin must not be the
  construction's own anchor).
  Also: **Frame ORIGIN rule** — a construction anchors at the most specific position
  it was given, and when a row mixes a face with points the **FIRST PICKED POINT
  wins**. New `[new]` row **`Face[Flat]` + `point` + `point`**: primary (Z) = the
  face normal (exact), secondary (X) = P1→P2 projected ⊥ primary, **origin = P1** —
  answering the user's "or do I have this backward?": the normal should stay primary
  (it is the axis you want exact, and the points usually lie IN the plane so the
  projection is a no-op), and the origin need not come from the primary at all. A
  PLANE primary now advances E1→E2→E3 (one point = the `reference` row keeping the
  face origin, two = the direction row); an EDGE primary still skips E2.
  And **ReOrigin's existing origin indicator drops to 25% opacity while the
  Orientation is picked** (`_ORIENT_GHOST_ALPHA`) — two solid triads were
  indistinguishable. Verified: `cgb_spec_modes_test.py` grown to 47 checks (it still
  PARSES the spec's tables) + full sweep **43/43 green**.
- **LIVE-TEST FIX ROUND 2 — ReOrigin naming/pane cleanup + a CGB↔spec SF-arming
  audit (headless-verified; GL re-test PENDING = CS-021).** User-requested:
  (a) the main-window command **"Set Origin…" → "ReOrigin…"** (matching the
  Component Editor; the 4 `QMessageBox` titles too);
  (b) its pane buttons are now **Point** / **Orientation** (were Vertex / Basis);
  (c) the CGB bar's BASIS button is captioned **"Frame"** — ⚠️ diverges from the
  spec, which calls the entity Basis/Orientation and reserves *Frame* for the
  composed pose; internal token stays `basis`, and the divergence is flagged in
  both the spec's entity table and `Reference/selection-and-cgb.md`;
  (d) the **"Origin Orientation Source" (Global/Custom) group is REMOVED** — the
  source is INFERRED (`OriginWindow._orient_source` is now a derived property: no
  Orientation ⇒ Global, one ⇒ Custom), the orientation is OPTIONAL for Apply, and
  right-click → Clear returns to Global (the Butler explicit-world-basis rule on
  Apply is preserved);
  (e) the yellow origin ball is hidden while the Orientation is being picked (new
  `CgbCommandBinder.pending_key`).
  Then the requested **spec audit** of what each CGB mode arms in the SF, which
  found two real drifts making enumerated rows UNREACHABLE: **Basis withheld Face**
  (all five `primary: Face[...]` rows) and **no target offered Body**
  (`point: Body[Any]`). Fixed by generating the offer from ONE spec-derived table
  (`cgb_features.TARGET_KINDS`/`MODE_OF_KIND`/`sf_modes_for_target`), plus the
  engine work to make those picks actually resolve: `_c_basis` gained a PLANE-kind
  primary (primary = the face normal) and LINE/PLANE secondary support in slot 3
  (the POINT-reference branch is byte-identical → `[impl]` parity intact);
  `_basis_z_defined` now uses the kind-sets; `item_to_entity` maps a Body pick to a
  `body` SlotEntity; and `SelectionFilter._finish_body` BYPASSES the tree body-sink
  while a command owns/requests the bar (the sink used to eat the pick and hand the
  command a stale result) while attaching the component's world centroid.
  Verified: NEW `scratchpad/cgb_spec_modes_test.py` (25 checks — it PARSES the
  spec's own tables and asserts the code matches, so this drift can't recur
  silently) + updated `cgb_bar_reachability_test` / `origin_window_migration_test`
  (both asserted the removed behavior) + the full sweep **43/43 green**.
- **LIVE-TEST FIX ROUND 1 (first real GL feedback on the SF/CGB build)** — the user
  reported that in Point→Edge mode hovering an edge no longer dim-highlighted it and
  clicking a point showed nothing, and that in Edge mode hover + click had no visual
  at all. Root cause (confirmed by their log: `edge-pick: 1108091 edges over the draw
  cap (40000)`): the edge hover highlight was a WHOLE-MODEL per-cell-RGBA mesh that
  `set_edge_pick_data` only created *under* `_EDGE_DRAW_MAX`, so on any real model the
  highlight actor never existed and `_set_edge_highlight` returned immediately.
  **Not** a rename/redesign regression — a latent hole in the earlier edge-pick
  pre-calc round, exposed once the pre-calc made big-model edge snapping reachable.
  Fixed, all in `viewport_panel` + `selection_filter`:
  (a) the highlight is now a SMALL one-edge actor (`_make_seg_mesh` /
  `_edge_segment_points` / `_EDGE_HL_SEGS`), created OUTSIDE the draw-cap branch and
  mutated in place (observer-safe) → highlighting works at ANY edge count, and the
  whole-model duplicate highlight mesh (a per-edge point copy + depth-peeled
  translucent actor) is GONE — a memory + render win;
  (b) NEW persistent **selected = orange** overlay for non-Body picks
  (`set_selected_edges` / `set_selected_points`, driven by SF
  `_refresh_selection_visuals`) — non-Body picks previously had no visual at all,
  only a status-bar line; skipped while a CGB command owns the bar so command
  visuals are unchanged;
  (c) Point→Edge hover now shows the dim courtesy edge even when nothing snapped
  (mid-span past the 15px gate), applied only if nothing more specific resolved;
  (d) `viewport.set_datum_records` only re-arms the SF on a REAL change (an arm is a
  full teardown + locator rebuild over every model edge — the log showed it firing
  19×);
  (e) `usd_writer._joint_axis_vec` — the writer's raw-dict contract now tolerates a
  legacy `"X"/"Y"/"Z"` axis token (mirrors `JointDef._v_axis`) instead of raising
  mid-export; this also fixed `joint_test_usd`, a stale casualty of the Phase-5
  axis→vector migration that the earlier sweep missed (the CLIs always passed a
  validated vector, so no production path was broken).
  Verified: NEW `scratchpad/edge_highlight_test.py` (26 checks: segment-mesh
  geometry, one-edge extraction/padding/truncation, source assertions that the
  highlight is uncapped, SF overlay push + owned-skip, courtesy-cue precedence) +
  the FULL headless sweep **42/42 green**. GL re-test PENDING (CS-021).
- **Selection Filter + Construction Geometry Builder REDESIGN — FULLY IMPLEMENTED
  (engine + GUI; headless/offscreen-verified over 38 green `scratchpad/*` suites; GL
  live-test PENDING = CS-021)**: feature-exposure engine (`cgb_core`/`cgb_features`/
  `cgb_recipes`), command contract + Collect (`cgb_command`), filter narrowing
  (`cgb_filters`), Fit Primitives + live mesh **FitService** (`fit_primitives`
  +`_worker`; a mesh face is fitted to an analytic primitive out-of-process on pick),
  **Frame** (`FrameBuilder`), **Set Origin** migrated onto the binder (which fixed a
  `"vertex"`→`"point"` rename bug that had silently broken the ReOrigin / Transform
  Move-Point / Set-Origin vertex picks), joint **free-axis** picker, **numeric entry**,
  **Measure modes** (distance/coordinate/angle/radius/bbox), and **Datums** (config +
  a persistent viewport user-datum layer + `datums_panel.DatumsPanel` dock +
  `datum_basis` chaining). Authoritative as-built: `Reference/selection-and-cgb.md`;
  spec `Specs/construction_geometry_builder_definitions.md`; the ReOrigin/Move-Point
  fix + Set-Origin migration are also noted in `Reference/geometry-edits.md`.
  Deliberate follow-ups (not done): the `edit_bodies_window` ReOrigin binder-dedup
  (3 intertwined CGB consumers, no offscreen harness) + a standalone CGB-bar Frame
  button (no consumer). The **CLAUDE.md → `docs/src/AI/` doc-split** (other agent) is
  verified **behavior-neutral** — the `src/` reference changes are docstring/comment-
  only (no runtime doc reads), all 38 headless suites green, and the stale
  `"vertex"`/`VertexSubMode` rename casualties in `scratchpad/` (`edge_rearm_test` +
  the 6 GL `probe_*` scripts) are fixed. Nothing committed.
- **Measure tool + Component Transform (NEW; engine + GUI logic COMPLETE,
  headless/offscreen-verified — GL live-test PENDING)**: a viewport **Measure**
  button (pick 2 vertices via the CGB → direct + X/Y/Z distances in meters, 3D
  billboard labels + status readout) and a main-window **Transform…** command
  (move a component/subtree's placement; bakes; non-destructive; assembly-capable;
  Orient/Translate via offsets or CGB Basis/Point; moving bbox preview; green
  move-cross glyph). See "Component Transform" + the Measure bullet under
  "Viewport interaction". Verified: `transform_test.py` (24), `transform_gui_
  offscreen.py` (16); STEP/mesh regressions green.
- **Load/cache**: conda env; tree-first load; subprocess parse (responsive first
  load); `.xbf` geometry cache + mesh cache + edge cache + color sidecar (all in a
  sibling `<base>.cellsmith.cache/` dir); auto-Show-3D after load.
- **Render**: on-demand Show 3D (adjustable deflection); single merged-actor
  rendering (scales to 20k parts); tinted background; **"Show Edges"
  settings-strip toggle defaults ON** (global `show_edges=True`) so feature
  edges auto-build on first load; edges precomputed once (subprocess) +
  cached → instant toggle/hide, no freeze; transient opacity slider.
- **Tree/selection**: implied root normally hidden (children are the top-level rows);
  **TEMPORARILY shown** (`tree_panel.SHOW_IMPLIED_ROOT=True`, for whole-scene export;
  paths unaffected — OPEN TODO to revert);
  tree↔3D highlight (subtree) + 3D→tree pick (ray, skips hidden/suppressed, clicks
  through invisible to the visible behind); mouse = LEFT select, CTRL+LEFT multi-select
  (tree AND viewport), MIDDLE-drag rotate, RIGHT-drag pan, wheel zoom; LEFT-click empty
  space or **Esc** deselects everything.
- **Per-node state**: Hide/Show (gray dot), Suppress (red dot), color override
  (purple dot), caret on ancestors of modified nodes; scene config persisted as
  `<base>.cellsmith.json`, keyed by `/`-rooted tree PATH (internal id = `component_id`).
  The **right-click menu (tree AND viewport) acts on the WHOLE selection** (shared
  `_exec_component_menu` → bulk
  `_set_hidden_nodes`/`_set_suppressed_nodes`/`_override_color`/`_clear_color_override`):
  Hide/Show, Suppress/Unsuppress, and **"Override Body Color…"** / **"Clear Body Color
  Override"** all apply to every selected node (aggregate bulk-toggle: "Show" only when
  ALL are hidden, else "Hide"). Single-selection-only items: **Copy Component Path**
  (copies the `/a/b/c` tree path to the clipboard — diagnostic aid), and the Export
  items (multi-select export is deferred —
  OPEN TODO).
- **Colors**: base part-color loading (top-level StepVisual style preferred over
  per-instance override; test2 axis2 → yellow) PLUS **per-face colors** for multi-
  colored parts (test1's 112k face styles → per-cell RGBA in the viewport); v4 color
  sidecar (base + per-face) + `tri_faces` in the mesh cache. Per-node overrides (win)
  and the global per-color **Recolor** dialog (per-cell in the viewport, purple-square
  indicator) layer on top. Exports remain one-color-per-component (OPEN TODO).
- **Source→Main pipeline** (NEW — headless E2E-verified on a testB1 scratchpad
  copy; GUI live-test PENDING): two-stage model dirs + one-time layout
  migration, always-baked Main with bake stamps (`main_rebuild_required`),
  orientation + Z-datum baked into the Main geometry (Transform Source
  window; toolbar combos removed), stamp-driven open flow (silent bake /
  warn+clear / regen offer), fresh-parse auto-generation, per-asset source
  stages + ~1s fast rebuilds, recipe frame conversion. See the pipeline section.
- **Orientation/datum**: Source→Main bake inputs edited in the Transform
  Source window's settings pane (pending-until-Apply, source-stage preview);
  baked into geometry — the main viewport and all exports see the finished
  frame.
- **Export** (right-click subtree; options popup = origin global/local + USD/OBJ scale):
  - **STEP** — faithful `Transfer(root_label)` copy; rebuild path (flat doc) when
    suppression/override/local-origin present (loses names+instancing —
    see OPEN TODO #1); always `layers=False`.
  - **USD** — `src/export/usd_writer.py`: default prim = selected component (no /Root),
    transform BAKED into points (reference-safe), meters + `metersPerUnit=1` (adjustable
    `export_scale`, 0.001 confirmed correct), colors, suppressed excluded.
  - **OBJ** — `src/export/obj_writer.py`: `.obj` + `.mtl`, same baked transform.
  - All three CLIs export from the ACTIVE model's MAIN stage via `--model=`
    (see Asset splitting); no orientation/global-offset application. The
    COMPOSED whole-scene exports are separate (`export_composed` worker; the
    options dialog takes `show_origin=False` there — origin is meaningless
    composed, and STEP skips the dialog entirely).
- **Asset splitting — PROTOTYPE-BASED (reworked 2026-07; headless-verified on
  the e2e_b1 fixture + offscreen GUI tests; user live-test PENDING)**: marking
  any occurrence marks the whole prototype GROUP (name-grouped, useless names
  fall back to product identity; nested fan-out refuses loudly; config marks
  stay normalized); ONE asset per group, named by the prototype, built from
  the canonical occurrence with **that occurrence's Main ORIENTATION baked
  into the root (rotation only, own origin — `R_root`)** so a standalone
  asset matches how it sits in Root.Main; Static removes EVERY occurrence. `assets-stamp.json` +
  `cache.assets_up_to_date` drive the Assets-menu matrix: **Update Assets**
  (incremental — only the mark diff regenerates; kept variants untouched,
  name continuity) and the **Export Composed USD/OBJ/STEP** gate. Per-model
  configs (schema v3) in the one `name.cellsmith.json`, per-model mesh/edge
  caches, direct-`.xbf` generation, Clear Assets. Generation always splits
  the root MAIN stage and writes BOTH stages per model; **Main-suppressed
  subtrees are physically excluded from every generated model**. See the
  "Asset splitting" section.
- **Export Composed (NEW; headless-verified — USD worlds ≤2.4e-7 m over 1905
  meshes, STEP reparse exact, OBJ parsed; user live-test in Isaac/SolidWorks
  PENDING)**: Assets-node menu → one worker (`export_composed`) re-composes
  all assets + Static at their Root.Main occurrence poses — USD = TWO files
  per asset (`{slug}_base.usd` overwritten each export + a persistent
  `{slug}.usda` override wrapper referencing it) and a relocatable `main.usda`
  PAYLOADING the wrappers (N occurrences → one wrapper; user overrides in the
  wrapper survive re-exports); OBJ merged; STEP hierarchy/instancing/names/
  colors preserved via the explicit-assembly `compose_step` builder. See
  "Asset splitting".
- **Body Editing on Assemblies round (NEW; headless bake + offscreen verified;
  user live-test PENDING)**: **edit-at-Root-flows-down** — Root body edits bake
  into Main and assets inherit them by pruning (the earlier marked-asset Edit
  Bodies block + `source_to_main_inputs` filter are REMOVED; generation
  self-heals a stale double-edit via `apply_geometry_edits(tolerant=True)`).
  **Merge-then-edit on assemblies** — Edit Bodies now works on a node WITH
  children: its descendant solids (positioned compound) are decomposed/cut and
  the subtree is REPLACED with the bodies (`_replace_assembly_children`),
  nearest-leaf colors, deterministic identity (headless-verified on a
  29-solid/2-occurrence assembly, geometry preserved 4.6e-13); the edited
  assembly stays an opaque, movable node (children + same-prototype occurrences
  collapsed). Plus: Transform Source toolbar button REMOVED (Model Tree menu
  only); tree headers "Source Structure (Read-Only)" / "Main Structure
  (Editing)"; the settings pane rebuilt (Settings heading, Z-Origin Orientation
  frame + Clear, editable X/Y/Z datum rows + per-axis Pick + orientation-change
  yellow highlight); the datum/global-origin marker now follows the Show Global
  Origin toggle; the Edit Bodies "Edit" pane (Define Plane side-by-side, tilt/
  offset sliders, tool-aware enabling, swatch cut-color, auto-testing Add Cut,
  body Hide/Show with gray dot); and the Edit Bodies orientation gizmo cue.
  Tests: test_root_flows_to_asset (5), test_assembly_merge_edit (11, real bake),
  test_assembly_edit_gui_offscreen (8), test_transform_ui_offscreen (21),
  test_edit_bodies_offscreen / test_transform_source_offscreen extended.
- **UI-polish round + asset-part geometry-edit crash fix (NOTE: the marked-asset
  crash guard below was SUPERSEDED by edit-at-Root-flows-down above;
  headless + offscreen verified — 16 + 29 checks; user live-test PENDING)**:
  toolbar reorder (Transform Source FIRST; **Rebuild** replaces Show/Clear 3D,
  stale-gated + auto-rebuild; **Recolor Registry…** rename); mesh quality moved
  off every viewport strip into an **Adjust Visual Quality** modal (Apply →
  bus → persist + live re-mesh); a **Copy button** on the worker-failure error
  dialogs (`_error_box`); and the **marked-asset geometry-edit** rule — the
  Main bake DROPS split/origin keys under a marked-asset subtree
  (`source_to_main_inputs`, self-healing via the stamp) and both Edit Bodies
  (Transform Source) and Set Origin (main window) refuse marked-asset parts
  with a redirect to the asset model. See Viewport interaction + Geometry edits.
- **Edit Bodies: disc cuts + draggable outline handles (NEW; unit/bake/
  offscreen/real-GL verified; user live-test PENDING)**: Rectangle|Circle
  shape toggle (`Cut.shape`/`diameter`, backward-compatible), disc tool face
  in the splitter, hover/drag-recolored rect-edge + disc-rim handles that
  resize the pending cut live. See "Geometry edits".
- **Transform Source window (unified editor — NEW; offscreen + real-GL
  verified, user live-test PENDING)**: ONE window edits the ACTIVE model's
  entire source→main at BOTH levels — 4 columns (source tree | edit tree |
  source-stage viewport | root-only settings), Edit Bodies in its context
  menus (pending recipes), refusal reasons for gated moves, ONE Apply → ONE
  bake. Replaces the Transform Main window, the Restructure window/button,
  and the main window's Split Bodies context items (all deleted). See the
  pipeline + "Tree restructure" sections.
- **Per-viewport settings strip** (NEW; offscreen-verified): quality/edges/
  origins/opacity on EVERY viewport via the shared `ViewSettingsBus`; the
  main toolbar's settings row is GONE. See "Viewport interaction".
- **Tree restructure / Feature A** (backend COMPLETE — headless-verified on
  testB1 incl. full E2E + export smoke + generate-from-Main + offscreen window
  checks; **GUI node-moving showed a red no-drop cursor on the user's machine
  — parked as OPEN TODO #0a; the merged window now SURFACES the refusal
  reason, so the next live-test names the cause**): Model Tree shows **Main**
  instead of Source; the editor lives in the Transform Source window
  (manual-gesture moves, green new/red empty folders, blue moved nodes,
  gray containers, carets, transient Hide/Show, per-node Reset); Apply bakes
  the root's MAIN stage (or single-model regenerates an asset/Static — fast
  path from its own source stage); maps re-apply on every regeneration.
  Everything EXCEPT the move gesture behaved in the user's live testing (of
  the pre-merge windows). See the "Tree restructure" section.
- **Geometry edits / Edit Bodies + Custom Origins (Features C+D)** (backend +
  window logic COMPLETE — probes P1–P6 + unit tests + Main-bake E2E + asset-edits
  E2E + USD live-Xform verification + offscreen window tests + zero-cut
  decompose bake tests (M-710iD70 15 solids × 6 occurrences; moved split
  leaf carries its bodies), all on testB1; **user live-test pending** — no GL
  in the dev env): Edit Bodies via the Transform Source window (auto-test on
  open, zero-cut decompose, JOIN/merge groups — bake-verified, model-color
  bodies + Tint toggle, in-process edge overlay, tree↔viewport selection
  sync + right-click rename, Esc/re-click tool cancel, Clear Bodies button);
  "Set Origin…" in the main
  window; recipes in config (`splits`/`origins` maps — key names kept);
  baked into variants (order splits→origins→structure); split bodies are real
  components groupable by the same model's restructure; origins become real local
  frames (Local exports, asset root frames, USD live joint Xforms). See the
  "Geometry edits" section.
- **Packaging** (BOTH OSes built + worker-verified; Windows GUI live-test pending):
  `build.bat` → `CellSmith-v<ver>-win64.zip`; WSL2 `make build` →
  `-linux-x86_64.tar.gz`; unified `--worker` dispatch (all 7 worker CLIs re-launch
  the frozen exe); custom OCC/pxr PyInstaller hooks + runtime hooks; every worker
  verified from dist without conda on both OSes; frozen GUI verified under WSLg
  (Linux). See the "Packaging" section.


## OPEN TODO (in priority order — capture for post-compaction)
-22. **✅ DONE (this round — headless + real-GL probe-verified; GL live-test
   PENDING): Global-origin DATUM aid pick-integration + styling + colors + a
   Vertex 'None' sub-mode + persistent CGB slot markers + removed the Transform
   centre-of-gravity dot.** Four live-test items from the user:
   1. **CGB slot markers** — every filled E1/E2/E3 shows a PERSISTENT smaller
      orange dot; hovering a slot shows the LARGER blue hover dot (so you can tell
      which is which, and all picks are always visible). `set_slot_markers` (pooled
      spheres) + `ConstructionGeometry._refresh_slot_markers`.
   2. **Datum aid** — the corner tree now BLENDS into the viewport (transparent, no
      border/scrollbars, sized to all rows); axes+planes SKY BLUE, origin a darker
      blue dot; and it is now PICKABLE (the pick-integration that was OPEN):
      origin→Vertex (`_snapped_vertex` + `_datum_origin_candidate`), axes→Edge
      (`_append_datum_edges` into `_arm_edge_layer`; re-armed via
      `on_datum_changed`/`_notify_datum_changed` when an axis toggles), planes→Face
      (`_resolve_face` composes the model face vs `datum_plane_hit_at_cursor`,
      nearer-camera wins). Hover recolor via `set_datum_hover` (planes). See the
      "GLOBAL-ORIGIN DATUM aid" note for the full contract + the v1 overlap limit.
   3. **SF Vertex 'None'** sub-mode (`VertexSubMode.NONE`) — an arbitrary,
      un-snapped surface point; always available; never a CGB default.
   4. **Transform centre dot REMOVED** (`_refresh_gizmo_sphere` no-ops the sphere).
   Verified: `scratchpad/sf_datum_test.py` (11 headless) + `scratchpad/probe_datum.py`
   (22 real-GL, incl. the SF edge layer carrying the 3 datum axes). **GL live-test
   PENDING:** open a model, start a CGB command (e.g. Axis/Plane), toggle datum
   planes on, and confirm the origin snaps as a vertex, an axis picks as an edge, a
   plane picks as a face, the slot dots persist + the hover dot is larger, the tree
   blends in, and the Transform gizmo has no white centre dot.
-21. **Selection + Construction-Geometry → B-rep-parity & model-manipulation
   roadmap (user-designated 2026-07-16).** The Selection Filter + Construction
   Geometry Builder (CGB) exist to turn real geometry into the three rigging
   primitives — a **frame** (link origin), an **axis** (joint), a **plane**
   (cut/datum) — plus inspection (measure) + bulk grouping (thousands of parts →
   links). Rank features by "how few clicks to a frame/axis/plane". Mesh vs B-rep
   selection gap: mesh can pick Body / one-triangle-Face / mesh-Vertex only;
   B-rep adds classified Edge (line/arc→direction/center) + analytic Face
   (kind + normal/cyl-axis). **ARCHITECTURE NOTE: all mesh analytic recovery
   (edge reconstruction, surface fitting) is `numpy.linalg` = the BLAS ban → it
   MUST run in the mesh WORKER (import-time or on-demand) + be CACHED; the GUI
   only consumes precomputed entities (like it consumes `edge_pick` for STEP).**
   - **DONE (this round — headless + real-GL-probe verified; user GL live-test
     PENDING; UNCOMMITTED):**
     - **A1 — mesh EDGE reconstruction (`src/gui/mesh_edges.py`, STRICTLY
       BLAS-FREE, in-GUI, no worker/cache in v1):** weld verts by position →
       dihedral-crease + boundary edges → chain (split at degree≠2 junctions;
       closed loops) → classify LINE (straight) / CIRCLE (Kasa fit in the summed-
       chord-cross plane, 3x3 by Cramer) / other → emit the SAME
       `edge_pick.EdgeInfo` contract (`.edge=None`). New capability
       `SelectionCapabilities.has_edges` (= B-rep OR any mesh) SEPARATE from
       `has_brep`: Edge mode + Vertex→Edge now gate on `has_edges` (work on
       meshes), Face→B-Rep stays on `has_brep`. `_ensure_edge_data` branches
       (has_brep→edge_pick, else→mesh_edges); `_leaves` includes vertex-bearing
       comps; CGB `_slot_spec` drops only Face for a mesh (Edge kept). Verified:
       box→12 axis-aligned lines, cylinder→2 rim circles (r/axis/center exact);
       STEP still routes through edge_pick (TopoDS edges). BLAS-free is CRITICAL
       (runs in the VTK process): no `@`/dot/matmul/`np.linalg` — cross/sum/sqrt
       + Cramer only. (Slow on a 20k-part mesh's first Edge arm, like STEP's
       edge_pick — a worker+cache is the documented future optimization.)
     - **A2 — whole-group Face→Tessellation:** a mesh (and STEP) Face→Tess pick
       now selects/highlights the whole `tri_faces` facet GROUP, not one triangle
       (`_ensure_global_tri` + `prepare_face_highlight` armed for Tess too; hover
       resolves the global face id for both submodes). Verified (6 groups × 2
       tris → whole face highlighted).
     - **B2 — MARQUEE (box) selection:** a left-DRAG rubber-bands a rectangle
       (`_CADInteractorStyle`: handle-drag > box-drag > click, decided in
       `_left_up` by start↔release DISTANCE; `QRubberBand` overlay is cosmetic/
       guarded, driven from the viewport's INTERACTOR-level hover observer) and
       on release selects every component whose WORLD centroid projects inside
       the box — `ViewportPanel.on_box_select(box, additive)` → `SelectionFilter.
       _on_box_select` (holds the assembly; `world_to_display` in VTK display
       coords — no Qt/DPI needed for the selection; plain box = replace, Ctrl =
       add). Enabled by `_arm` only while Body selection is active. Verified
       (real VTK events): single/multi/exclusion/empty-clear + replace-then-add,
       AND that rotate/pan/click/context-menu are unregressed. (The rubber-band
       VISUAL is user-live-test.)
       **⚠️ VTK GOTCHA (regression the user hit + fixed): do NOT
       `AddObserver("MouseMoveEvent")` on the interactor STYLE — it REPLACES the
       base `OnMouseMove`, which drives rotate/pan AND keeps the poked renderer
       current for clicks (wheel zoom uses a separate handler, so it survives and
       MASKS the break → "rotate/pan + left/right click all dead, wheel still
       zooms"). Motion-driven logic (rubber-band, handle-drag, hover) belongs on
       the INTERACTOR observer (`iren.AddObserver("MouseMoveEvent")`), which
       coexists with the base `OnMouseMove`.**
     - **Toggle renames:** "Show B-Rep Edges"→**"Show Face Edges"**,
       "Show Tess Edges"→**"Show Tessellation Edges"** (labels only; config keys
       `show_edges`/`show_tess_edges` unchanged).
   - **FUTURE (all TODO — explore in detail; user: "all matter, hash out later"):**
     - **A3 — primitive/surface FITTING as an OPT-IN, UNDOABLE Component-Editor
       COMMAND** (NOT automatic import — user wary of bad auto-fits): select a
       body → run the command → fit plane/cylinder/cone/sphere to its facet
       groups → get the Face kind filter + **cylinder AXIS** (hole/shaft →
       revolute joint axis) + plane normal + sphere center; easily undone if a
       fit is bad. **NAME: "Fit Primitives"** (recommended; alt "Recognize
       Features"/"Detect Primitives"). Biggest remaining mesh-parity + rigging win.
     - **B1** loop / tangent-chain select (hole rim, face boundary, fillet chain).
     - **B3** Select Similar / Select By (prototype, color, surface kind, radius,
       size). **B4** grow/shrink/invert, paint-drag add.
     - **C — richer CGB:** C1 points (midpoint, centroid, axis∩plane, projection,
       point-at-distance); C2 axes (two-plane intersection, face normal, through
       two hole centers, cyl axis); C3 planes (**mid-plane between two faces** =
       symmetry, tangent-to-cylinder, normal-to-edge); C4 full coordinate frame
       from mixed refs (origin + X-from-edge + Z-from-face) extending Basis.
     - **D — rigging shortcuts** (ties into the DEFERRED rigging milestone #5 —
       geometry groundwork only; joint/physics authoring waits for the user's
       spec): D1 joint axis from a cylindrical face/hole in one click (revolute) /
       two planar faces → intersection (hinge); D2 mate-style refs (concentric/
       coincident/symmetric) → auto-frame; D3 link-frame presets (bbox center,
       centroid, selected-face frame).
     - **E — measure:** distance/angle/radius/coordinate/bbox readouts (verify
       joint offsets + imported scale).
   - Build representation-agnostic where possible; STEP stays byte-neutral; the
     A-tier are the mesh parity fills.
-20. **Mesh-file import (OBJ/STL/USD + more) — BUILT, FULL PARITY, headless-
   verified; UNCOMMITTED; user GUI/GL live-test PENDING.** See the "Mesh-file
   import" section above for the architecture. Status + what remains:
   - **What works** (headless-verified, 9 green `scratchpad/mesh_test_*.py`
     suites): open/render, per-node state, colors (incl. per-face from the
     file), Transform Source (restructure + orientation/datum), Component Editor
     (Edit Bodies: decompose/split/merge/transform), Set Origin, Generate/Update/
     Clear Assets + Composed USD/OBJ, subtree USD/OBJ export. STEP path is
     byte-neutral (regression-guarded).
   - **Four live-bug fixes across this + the follow-up round** (all mine, caught
     by the user's live-test because import/compile checks don't exercise live GL
     paths):
     (1) `construction_geometry._slot_spec` called `.capabilities()` on a
     PROPERTY → `TypeError` broke ALL CGB commands (STEP + mesh) → `.capabilities`.
     (2) the Component Editor ran the mesh CUT (trimesh→`numpy.linalg.svd`) IN THE
     GUI/VTK process → `0xC06D007F` BLAS crash → route split-bearing replays +
     `_commit_split` count to the `mesh_ops_worker` SUBPROCESS (decompose/merge/
     transform stay in-process, BLAS-free). (3) CAD tessellations are UNWELDED at
     face boundaries → decompose made one body per face → weld by position in
     `_connected_components(tris, verts)`.
     (4) the `mesh_ops_worker` subprocess ITSELF crashed with exit `-1066598273`
     (= `0xC06D007F`): a QProcess-spawned worker gets `sys.executable` but NOT
     conda activation, so `<env>\Library\bin` (MKL/LAPACK) is off PATH; OCC
     survives via `add_dll_directory` but MKL delay-loads via PATH ONLY
     (probe-verified) → svd crash. FIX: `src/main._ensure_worker_dll_path()` (top
     of `_run_worker`, before any numpy/trimesh import) prepends the env's
     activation DLL dirs to `PATH` (dev/Windows; skipped when frozen). Verified:
     env-python-direct `--worker mesh_ops_worker` now returns `{"count":2}`; the
     real-GL `probe_split.py` cuts a mesh box → 2 bodies, no crash.
     (Considered + REVERTED: briefly disabled "Show B-Rep Edges" for meshes, but
     the user re-enabled it — for a mesh the toggle overlays VTK dihedral
     feature-edges, a useful clean-contour approximation; see the mesh section.
     `probe_brep_edges_btn.py` now confirms the toggle is enabled for both STEP
     and mesh.)
   - **USER LIVE-TEST (the only thing headless probes can't confirm — GL
     picking/preview RENDER):** open `testD1.obj` + `testE1.usd`; render+colors+
     Show-B-Rep-Edges (mesh → dihedral feature edges) + Show-Tess-Edges;
     STEP-export/quality/analytic-snapping greyed w/ tooltips; face picking;
     Transform Source; Component Editor Split(→Plane→pick→Accept→Add Cut — now
     succeeds; expect a ~1-2 s pause per cut = the subprocess, NOT a hang, NOT a
     crash)/ReOrigin/Merge/Transform → Apply; Set Origin; Generate Assets →
     Composed USD/OBJ (open in Isaac/usdview); re-open uses the fast cache; STEP
     unchanged.
   - **Deferred (documented)**: per-FACE color OVERRIDE persistence + whole-group
     highlight for Face→Tessellation — cross-cutting (needs a per-face-override
     config schema), belongs with the alpha/transparency round (NEXT BIG TODO).
   - **DEV GOTCHAS** (hard-won): run ALL headless dev/tests via
     `conda run -n CellSmithEnv` (running the env python DIRECTLY leaves BLAS DLLs
     off PATH → even plain numpy `@` crashes exit 127); NOTHING that calls trimesh
     OR `numpy.linalg` (svd/matmul/solve) may run in the GUI/VTK process — route
     to a subprocess worker; drive GUI commands with a REAL-GL windowed probe
     (`scratchpad/probe_*.py` pattern) before claiming they work — import/compile
     never exercises `_slot_spec`/`run_one_cut`.
-19. **Component Editor: operation-sequence model + lineage tree (9b/9e) — code
   COMPLETE (headless + offscreen verified; user live-test PENDING; live-drag
   grips items 5/6 DEFERRED). Closes OPEN TODO -16.** Edit Bodies is rebuilt as a
   command-driven **Component Editor** over an ORDERED op sequence:
   - **Data model** (`geometry_edits.py`): `SplitRecipe` v2 = `initial_count`,
     `ops:[BodyOp]` (`split`/`merge`/`transform`/`delete`), `names`, `origins`,
     `body_order`, `next_id` (dropped cuts/body_count/merges/bodies/body_origins).
     New `BodyOp`/`BodyTransform`/`OrientAlign`/`AxisDef`/`PointDef`. STABLE
     lineage-ids: initial `i0..`, op results `{op_id}:{k}` by `body_sort_key`.
     **Custom body-order preservation** (`_order_keeping`): a merge/split/transform
     used to dump its NEW body at the END of the tree — the replay's natural order
     puts the result last, and the stale `body_order` (referencing consumed lids)
     failed `ordered_final_ids`'s permutation check → fell back to natural. Now
     `_cmd_merge` + `_commit_op` (new ops) rewrite `_body_order` to put the result
     WHERE its first target sat in the current display order (`_final_lids`),
     dropping the other targets — so the new body keeps the user's custom position.
     Delete already preserved order (its targets just drop from the pruned order).
     Verified `scratchpad/merge_order_test.py` (6).
     `replay_ids`/`final_ids`/`ordered_final_ids`/`display_names`/
     `body_origin_paths` (now over `origins`+display names). `load_split_map`
     DROPS legacy flat recipes (no `initial_count`) + logs; new
     `split_map_legacy_paths` for the UX notice.
   - **Engine** (`geometry_edits_build.py`): `run_one_cut` (ONE plane), `merge_bodies`,
     `_split_face_colors`, `_BodyState`, `run_body_ops` (replay; strict raise /
     tolerant→None on count drift), `_resolve_body_trsf` (BodyTransform→local
     gp_Trsf: Orient-then-Translate built world-frame + conjugated `W⁻¹·T·W`,
     pivot = origin-frame-if-set else centroid). `apply_splits` drives
     `run_body_ops`; body-origin injection keyed by lineage-id→display name.
     `orientation.py`: `euler_matrix`/`min_rotation`/`align_axes`(dual-axis)/
     `rot_about_axis`/`axis_target_vec`/`mat4_orient_about` (elementwise).
     Decisions: ONE plane per Split; Delete/Edit an op = cascade-remove downstream
     + warn; Transform = Orient(offset a/b/c | dual-axis align) then
     Translate(offset X/Y/Z | move-to-point on sibling bodies); re-author old
     recipes (one format). A Transform (1 body in → 1 out) CARRIES the input
     body's custom name onto its result by default (`_commit_transform`: copy
     `_names[src_lid]` → `_names[{op_id}:0]`; the consumed input's name is pruned
     on replay; an un-renamed input → the positional `Body-N`).
   - **GUI** (`edit_bodies_window.py`, class name kept): window title "Component
     Editor - {name}"; menu bar View→Tint Bodies; lineage Body Tree (final bodies
     + disabled `[Split N]`/`[Merge N]`/`[Transform]`/`[Origin]` children);
     right-click commands (Split/Merge/Transform…/Edit Origin…/Rename/Hide;
     op-node Edit/Delete cascade); empty-until-active Edit pane with per-command
     Apply/Cancel; window Apply/Reset/Cancel; Reset reverts to open-state. **Split
     is CGB-driven (item 9)**: the Define-Plane group is a SINGLE **"Plane"** button
     that requests a plane from the viewport CGB (like ReOrigin — `_request_split_cgb`
     → `set_mode(PLANE)`; `_on_split_cgb_finished` stores the returned entity as the
     pending `Cut` and previews it), plus the kept **Cut Surface Color** group; the
     old Point-Snap / Plane-Shape / Transform-Plane / Resize-Plane groups + the 5
     tool buttons are GONE (their tool methods remain but are dead — unreachable
     without the widgets). The `ConstructedEntity` plane now self-describes its
     bounded extents (rect `u/v_min/max`, or disc Ø+`center`), so `_current_cut`
     builds the `Cut` straight from `_pending`. Apply → `_commit_split` runs
     `run_one_cut`. **Transform pane — each of Orient/Translate is a RADIO between an
     Offset method and a CGB method** (`_sync_transform_enabled` toggles the sub-UIs).
     Orient: **Offset a/b/c** (`_orient_abc` spinboxes + gizmo rotation RINGS, DEFAULT)
     OR **From / To Basis** — To Basis (above) + From Basis CGB Basis buttons, rotation
     `R = Rt·Rfᵀ` (`orient_method="basis"` + `orient_from_basis`/`orient_to_basis`
     `BasisDef`s; engine `_mat3_mul`). Translate: **Offset X/Y/Z** (`_trans_xyz` +
     gizmo translation ARROWS w/ cone heads, DEFAULT) OR **Move Point** — To Point +
     From Point CGB Vertex buttons (`translate_method="move"`). **From Basis/Point
     DEFAULT to the body's current origin frame/position** so the user just sets the
     To: From Point = `_body_origin_point`; From Basis = **`_body_origin_basis`** —
     the body's CUSTOM origin frame when one is set, ELSE the body's actual current
     basis (the component's world orientation), ALWAYS a concrete `{x,z}` (never None)
     so the From Basis button shows defined. The offset methods keep the
     interactive gizmo grips (`_refresh_gizmo` shows arrows/rings for whichever offset
     radio is checked, none for the basis/point methods; item 17); the CGB buttons
     seed with the current value (item 12) + disable Apply/Cancel while picking
     (item 15). `_build_body_transform` dispatches per radio; `_preload_transform`
     restores the radio + values when editing an op. Legacy split recipes surface a
     one-time notice in the Source Editor (`_notify_legacy_recipes`) + are cleared.
     **Transform CGB pick presents pickable geometry (`_begin_xform_pick` /
     `_end_xform_pick`):** the Transform command renders the target as a MOVING
     preview actor (`pickable=False`) + reloads a context-only assembly, so under
     'Target Body' `_combined` is EMPTY — the SF/CGB had NOTHING to hover/select (the
     To-Basis / From-Point "dead viewport" bug; ReOrigin/Split never hit it because
     they keep the bodies loaded via `_apply_command_visibility`). Fix: on a Transform
     CGB request, `_begin_xform_pick` tears down the preview (`_teardown_xform_actors`)
     + `_render_bodies` (all bodies PICKABLE + edges) + `_apply_command_visibility`
     (hides others per the toggle, target stays pickable, rebuilds the CGB edge-pick);
     `_on_transform_cgb_finished` calls `_end_xform_pick` (restore the moving-preview
     view). `_end_command` clears `_xform_pending_cgb` BEFORE `cg.cancel()` so the
     teardown-time cancel early-returns instead of re-creating the preview. Toggling
     Visibility MID-PICK (`_on_visibility`, transform branch) re-applies the hide via
     `_apply_command_visibility` (no reload) rather than `_render_transform_context`,
     which would re-blank the pick.
   - **Editing an EXISTING CGB definition (item 12):** the ReOrigin Vertex/Basis
     and Split Plane buttons, when a definition already exists, SEED the CGB with it
     (`ConstructionGeometry.load_entity(mode, entity)` → the CGB `_direct` seed) so
     the user edits it instead of starting blank; the CGB **Clear** button restarts
     from scratch, a fresh pick discards the seed, and a PLANE seed keeps its
     extents/offset/shape editable via the bar (`_direct_entity` applies them).
     Each button also has a right-click **"Clear"** menu (`_install_clear_menu`/
     `_clear_cgb_button`) that removes just that definition.
   - **ReOrigin is an INLINE command** (renamed from "Edit Origin"; was: right-click
     → open the separate `OriginWindow`). Right-click a single body → **ReOrigin…**
     activates an
     `_origin_pane` in the Edit pane — an **Origin Datum** Vertex button + an
     **Origin Orientation** Basis button + Clear Origin, both driven by the SAME
     viewport CGB (`_request_origin_cgb`/`_on_origin_cgb_finished`,
     `constructionFinished` connected once in `_initial_load`). **NO Global/Custom
     source radio (item 7)**: no Basis → Global; a Basis → Custom. ReOrigin is VALID
     as soon as the Vertex is set (`_origin_valid` = vertex + no pending pick);
     `_commit_origin` writes `axis`+`xdir` only when a basis exists. The command's
     Apply (`_commit_origin`) stores an `OriginFrame` in `self._origins[lid]` (teal
     dot, baked via the origins map like before). Item-7 polish: the target body is
     NOT selection-highlighted while editing (`_apply_command_visibility` clears
     `set_highlighted`); the origin-frame preview is HIDDEN while the CGB is picking
     (`_request_origin_cgb` clears it) and is drawn as a standard triad + cone
     arrowheads at the component-triad size `model·0.06` (`viewport.add_triad_actors`,
     no sphere). `OriginWindow` STAYS for the main
     window's whole-component **Set Origin…**; only the Component Editor's per-body
     path went inline. The ReOrigin lands in the Body Tree as a **"ReOrigin N"** node
     (op-lineage convention, SAME gray as Split/Merge nodes) with a child = the body
     it derived from — like "Split 1"/"Merge 1" (`_refresh_bodies_tree`, `origin_num`
     counter). **Visibility
     group** (top of the Edit pane, `_vis_box`, HIDDEN until a command starts —
     `setVisible`, shown for EVERY command): mutually-exclusive **Target Body**
     (default) / **All Bodies** (`_cmd_visibility`, `_on_visibility`) sets whether
     only the edited body or every body is shown during split/transform/origin —
     Split adds the others as pickable context (`_context_components`; picks still
     define the plane by world points, the cut hits only the target), Transform
     toggles the static-sibling context (`[]` vs `_xform_context_lids`). **ReOrigin
     toggles visibility via `set_hidden` — NO reload, so the camera NEVER re-adjusts**
     (item 7; picks skip hidden = select-THROUGH; `_apply_command_visibility` also
     re-seeds the CGB edge-pick from only the visible bodies). Refinements: the
     ReOrigin "N" node has its own right-click menu (`_origin_node_menu`: **Edit
     ReOrigin…** / Delete); and the selected-body origin INDICATOR shows the CUSTOM basis
     orientation (`show_component_origin(point, axes)` + `_triad_poly`/
     `_add_triad_cones` gained an optional `axes` arg = rows X/Y/Z; the Component
     Editor passes `_body_origin_axes(lid)` = `basis_matrix(...).T`). The Component
     Editor's SF + CGB bars are MOVED out of the viewport (middle column) into a
     FULL-WIDTH bottom strip (`_bottom_bars`) in `_initial_load` (reparent the bar
     `.widget`s — controllers still point at `viewport.selection_filter`/
     `construction_geometry`), so the Selection Filter spans the whole window and the
     Edit pane sits ABOVE it, not beside it. Offscreen-verified
     (`test_inline_origin_offscreen`, 107 checks incl. a real-OCC CGB-plane cut +
     a real-engine basis→basis rotation); GL live-test pending.
   - **Later polish (items 13-16):** the ReOrigin node menu says **"Edit
     ReOrigin…"** (item 13); with Visibility='Target Body' the SF's edge-pick layer
     EXCLUDES the hidden bodies (item 14 — a pass-through
     `ConstructionGeometry.set_edge_exclude(cids)` → `SelectionFilter.set_edge_exclude`
     → `_leaves` filter + cache invalidate; the command passes the hidden set in
     `_apply_command_visibility`), so only the target's edges show/snap; the Edit
     pane's Apply/Cancel are DISABLED while the CGB is active (item 15 —
     `_set_origin_controls_enabled` + the split request/finish toggle `_cmd_cancel`);
     and the CGB plane default size is ~20% bigger (`_init_extents` `d = s·0.18`,
     item 16) so a small plane doesn't shrink off the part when rotated.
   - **Transform live preview + gizmo (built)**: the target body renders as a
     SEPARATE movable actor in its OWN colors — `_build_xform_preview_actors`
     builds a single-body `mesh_ops.build_combined` (per-cell base+per-face RGBA,
     NO tint — a tint/flat color washed detail out) + a feature-edge overlay
     (`extract_edges`, added only when the viewport's Show Edges is on);
     `_update_xform_preview` sets BOTH actors' `user_matrix =
     body_transform_world4(...)` on every param/pick/grip change. The GIZMO
     (handle layer) shows 3 translation ARROWS (Translate=Offset) + 3 rotation
     RINGS (Orient=Offset) — the neutral centre-of-gravity SPHERE was REMOVED
     (user: "annoying"; `_refresh_gizmo_sphere` now only tears down any leftover
     actor, `_gizmo_sphere` stays None). **`_refresh_gizmo` MUST guard
     `_xform_target_state is None`** (like `_gizmo_pivot_world` /
     `_update_xform_preview` do): `_start_transform` calls `_tr/_or_offset_rb.
     setChecked(True)` — firing `idToggled → _sync_transform_enabled →
     _refresh_gizmo` — BEFORE it sets `_xform_target_state` (a few lines later), so
     an unguarded `_xform_target_state.lid` there raised an UNCAUGHT AttributeError
     in the Qt slot, which left the SF/CGB half-owned → "all the mouse buttons
     break" (repro: click the datum origin during a Transform Move-Point pick). The
     grips are AXIS-COLORED via the ONE
     viewport helper `ViewportPanel.axis_color_for_dir(model_dir)` — which keys a
     model-space direction to the EXPORT axis it maps to under `self._orient`
     (`_export_dir`, elementwise). So the gizmo arrow/ring for model-axis a is
     colored to match the corner orientation gizmo AND the viewcube face pointing
     the same visual way — one global orientation input for every axis-colored
     thing (the viewcube recolors on `set_orientation` via `_recolor_viewcube` /
     `_viewcube_cell_color(d, orient)`; `_GIZMO_AXIS_RGB` is only a fallback). This
     fixed the Y/Z gizmo+viewcube color swap that appeared under a non-identity
     Source→Main orientation (X was right, Y/Z read backward vs the corner gizmo).
     **Gizmo/sphere follow rules:** they follow the previewed body's pivot
     (moves by `T_world`) when NOT dragging AND during a TRANSLATE (arrow) drag —
     but the drag-REFERENCE pivot (`_gizmo_pivot`) stays fixed mid-drag (only the
     visible geometry translates) so the arrow math stays stable; during an
     ORIENT (ring) drag the follow is SKIPPED so the gizmo neither moves nor
     spins (the body rotates in place about the fixed pivot). Left-drag is fully
     intercepted by the interactor (no camera on left — camera is middle/right),
     so a grip drag never moves the camera; the body rotates about its OWN pivot,
     not the world origin. Drag math: arrow = `_line_ray_param` closest-approach →
     set X/Y/Z offset; ring = ray∩plane polar-angle delta → set about-X/Y/Z
     rotation. **(item 17) The gizmo drags under Visibility='Target Body' too** — that
     path loads only the movable preview actor (empty `_combined.mesh`), and the
     viewport's MouseMove observer used to `return` early when `_combined.mesh is
     None`, killing the handle drag; the observer now runs the viewcube-hover +
     handle drag/hover BEFORE that guard (only the model-space edge/face/point hovers
     need the mesh). The translate arrows also get **cone arrowheads**
     (`_gizmo_arrow_specs` → `viewport.set_construction_arrows`, in-place
     `update_construction_arrows` on the follow-drag; shaft stops at the cone base).
     **(The offset gizmo grips are RETAINED** — item 18 added From/To Basis + From/To
     Point as a RADIO ALTERNATIVE to the Offset methods, which keep their translate
     arrows/cones + rotation rings; `_refresh_gizmo` shows them only for whichever
     offset radio is checked. The item-17 MouseMove-observer reorder — handle
     drag/hover before the `_combined.mesh is None` guard — is what makes those grips
     draggable under Visibility='Target Body'.) A Merge op node's right-click menu
     now offers **"Edit Merge…"** (add/remove members) alongside Delete — an INLINE
     command in the Edit pane (`_merge_pane`, was a modal dialog): checkboxes
     (`_HoverCheckBox`) over `SplitRecipe.working_before(op_id)` (the bodies AVAILABLE
     at the merge's position; members pre-checked, "dissolved" name view). **HOVERING
     a checkbox highlights that body** — the command renders every candidate as its
     OWN body (`_render_candidate_bodies`, DISSOLVE-for-display from `_all_states`)
     so the members (otherwise fused inside the merged compound) are individually
     visible + highlightable via `set_highlighted`. Apply (`_commit_merge_edit`, via
     the shared cmd row) replaces the op's `targets` (keeping its op_id + position,
     so the merge RESULT id `{op_id}:0` + any downstream op targeting it stay valid;
     order preserved by `_replay`'s prune) → `_prune_ops` cascade (a body added that
     a LATER op still targets drops that op, same rule as Delete) → replay. ≥2 members
     (else warn; Delete removes the merge). `_end_command` clears the hover +
     checkboxes and restores the normal bodies view. Verified
     `scratchpad/edit_merge_test.py` (12 — the pure transform logic; the inline pane
     + hover render is GL live-test). STILL DEFERRED:
     plane Tilt/Offset drag
     grips for the SPLIT command (spinbox + outline-handle driven meanwhile).
     KNOWN (needs live re-test): the rotation rings use a ray∩ring-plane angle, so
     a ring viewed EDGE-ON (its plane ∥ the view) is hard/impossible to drag — from
     some views only the face-on axis responds. Each ring drives a DISTINCT euler
     axis in code (`orient_abc[a]`, `a=hid-3`); if two rings still appear to rotate
     the same axis after the color unification, rework the rings to a
     view-independent trackball drag.
   - **Split-vs-merge (diagnosis — engine is CORRECT):** a split op consumes ONLY
     its own target body (`op.targets[0]`), so splitting a body NEVER drops a merge
     of OTHER bodies (proven `scratchpad/merge_split_test.py`, 9/9: model + real-OCC
     `run_body_ops`). The ONE case where a split "undoes a merge" is splitting the
     MERGED body ITSELF — a merge is a COMPOUND grouping of N solids, and a plane cut
     necessarily re-decomposes that compound (you can't cut a group apart and keep it
     grouped). If the merged body grouped many solids, splitting it exposes them all
     ⇒ looks like "undoes all the merges." WORKFLOW: split FIRST (bodies separate),
     then merge into link-groups LAST; Edit Merge adjusts membership after.
   - **Arbitrary-order split/merge — FUTURE rearchitecture (ideated, not built):**
     the wart above (can't split an already-merged body) is because a merge does TWO
     things at once — logical grouping AND eager geometry compounding. The clean fix
     = make **merge a DEFERRED LINK-GROUP membership**, not an eager compound: a
     `groups: {name: {member lineage-ids}}` map replaces merge ops; bodies stay the
     atomic split/transform/delete units (always individually addressable); splitting
     a grouped body keeps its pieces in the group (lineage-propagate membership through
     the split); the compound is authored only at BAKE (one compound per group →
     link). Then split/group are fully order-independent. Cost: a real `SplitRecipe`
     schema change (drop merge ops, add `groups`, migrate) + engine + GUI; the current
     op model works, so this is a "when the ordering wart hurts enough" upgrade.
   - **Delete-body (IMPLEMENTED — headless-verified `scratchpad/delete_body_test.py`
     8/8; GL live-test PENDING):** a `BodyOp` kind `"delete"` (`targets=[lids]`,
     `result_count=0`). `replay_ids`/`working_before`/`ordered_final_ids` handle the
     0-result op natively (empty `result_ids()` → the targets just leave the working
     set; states STAY in `all_states` for undo/preview). `run_body_ops` +
     `run_body_ops_mesh` got a `delete` branch (drop targets from `order`, append
     nothing); `BodyOp._v_kind` allows `"delete"`; `is_effective()` is TRUE whenever
     any delete op exists (else a delete-to-one-body recipe would drop on dump +
     revert). GUI: body context-menu **"Delete Body/Bodies"** → `_cmd_delete(lids)`
     (append + replay; refuses to delete the LAST body). The deleted bodies show under
     a top-level **"Delete N"** tree node with dim-red **struck-through** children
     (`_refresh_bodies_tree`) — selecting one previews its geometry (`_show_temp` via
     `all_states`); right-click the node → **"Restore Deleted"** removes the op
     (`_op_menu` labels delete-op Delete as "Restore Deleted", no "Edit"). Bake omits
     the deleted body (final list excludes it; `split_stub_assembly` reads
     `ordered_final_ids()`/`display_names()` → already excluded, so the restructure
     planner's `compare_planned` matches). Distinct from Hide (view-only). USD/OBJ/STEP
     inherit (a deleted body is simply not among the authored bodies).
   - **Old-body preview (item 6)** = OVERLAY, not a new view (no camera move):
     `_show_temp` keeps the camera, hides the solid bodies + shows edges, overlays
     the old body (a COMMAND node shows its INPUT bodies); Esc/background-click
     restores. **FIXED "shows for some bodies, not others" (testC1 Link4→Merge 1:
     i3 rendered nothing):** the overlay RESHAPED `tessellate_shape`'s faces to
     `(-1,3)` and rebuilt VTK connectivity — but that array is ALREADY VTK format
     `[3,i,j,k,...]`, so the reshape scrambled indices (some stayed in-range and
     drew, others went out-of-range and VTK silently dropped them). `_overlay_mesh`
     now meshes the WHOLE state shape (handles a merged compound), passes faces
     STRAIGHT to `PolyData`, retries a deflection ladder, and falls back to
     per-solid meshing; a 0-triangle result reports per-lid tri counts in the
     status line.
   - **Also (viewcube/origin tweaks)**: viewcube corners bigger — rebuilt as a
     TRUNCATED chamfered cube (6 octagon faces + 12 quad edges + 8 HEXAGON
     corners, still 26 cells) `cf=0.4`/`ct=0.2`, per-facet angle-sorted winding;
     global-origin triad `0.12→0.06` (matches the component triad). Settings strip:
     Show Bodies toggle (persisted `GlobalConfig.show_bodies` + `set_bodies_visible`),
     Show Global Origin default ON + moved left of Show Component Origin. Titles:
     "Source Editor - {Root|asset}", "Origin Editor - {name}". Origin Editor
     Edge-datum hover previews a point dot.
   - Tests: `test_op_sequence_engine` (8), transform math (5), `test_ops_asset_prune`
     (2), `test_component_editor_offscreen` (15). Old scratchpad tests using the
     old schema are OBSOLETE.
*** NEXT BIG TODO — ALPHA / TRANSPARENCY EVERYWHERE (user-designated 2026-07):
   Change ALL colors in the app + ALL color pickers to carry an ALPHA channel,
   and have it flow through to the USD and OBJ exports.
   - **DONE (groundwork): the UNIFIED color picker (`color_picker.ColorPickerDialog`)
     now SHOWS an alpha slider and returns RGBA** (`selected_color`/`selected_rgba`).
     Every color chooser was consolidated onto it (main-window Override Body Color,
     Recolor replacement, Edit Bodies cut color) and each has the "Pick Color"
     screen eyedropper. Callers still read RGB only (alpha dropped) — the REMAINING
     work is to consume that alpha: extend the color MODEL end-to-end to RGBA (below).
   - Per-cell RGBA already exists in the viewport (`_refresh_cells` uses the
     alpha for hide/opacity); extend the COLOR MODEL end-to-end to RGBA: base +
     per-face colors (`Component.color`/`face_colors`), node overrides, the
     Recolor registry, the eyedropper, and the color-picker CALLERS (stop
     dropping `ColorPickerDialog`'s alpha in main_window/recolor_dialog/
     edit_bodies_window).
   - Carry alpha into `scene_config.bake_effective_appearance` (extend to RGBA),
     the color sidecar (v5), and the export bake.
   - USD: this is where the OmniPBR-material work (TODO #7) lands — author an
     OmniPBR material per distinct RGBA (opacity_constant = alpha), likely
     ALWAYS per-face via `UsdGeomSubset` (see #7's design note). OBJ: `.mtl`
     `d`/`Tr` per material (+ per-face `usemtl` groups — TODO #6).
   - STEP already supports `SURFACE_STYLE_RENDERING.transparency` (TODO #7).
   - Big cross-cutting change (schema + every color surface + 3 exporters) —
     scope it as its own multi-phase round. See TODO #7 for the Isaac/OmniPBR
     specifics (both patterns confirmed working).
-18. **Asset-export inherited-frames round (code COMPLETE — real-OCC + pxr E2E
   verified):**
   (2a) **FIXED: an ASSET USD export (Assets→Export USD, or
   Asset.ComponentTree.<part>→Export USD) LOST the body/link joint origins** —
   every body fell to the assembly origin — while the SAME export from
   Root.Main kept them (testC1 'Igus Rebel 6'). Root cause: body/link origins
   authored at ROOT bake into Root.Main and flow into the asset by PRUNING, so
   the asset's OWN origin/split maps are EMPTY; `usd_cli`/`compose_cli` built the
   live-Xform frame set only from the model's own maps (`get_origin_map(model) |
   body_origin_paths(split_map(model))`) → empty for the asset → no `xformOp`.
   The geometry was correct (frames baked into `comp.transform` by the prune);
   only the frame SET was unknown. Fix: new shared helper
   `src/export/frame_paths.py` `inherited_frame_paths(store, model, stamp)` —
   reconstruct the ROOT frame paths (`origin_map(SOURCE) | body_origin_paths(
   split_map(SOURCE))`) and TRANSLATE into the model's own tree (asset = strip
   the canonical-occurrence prefix from the assets-stamp `occurrence_paths`;
   Static = keep root paths not under any removed asset occurrence). Both CLIs
   union it into the frame set. Now an asset/Static export authors the SAME live
   Xforms as a Root.Main export of the same occurrence. pxr-E2E verified
   (`test_asset_export_frames.py`: bake Root split w/ body_origins → generate
   asset (empty asset map) → asset USD's body prim carries `xformOp:transform`;
   a body without an origin has none). NOTE: reads only KEYS/paths, never a bake
   input — no config pollution, no regen required.
-17. **Body/link origins → USD live Xforms round (code COMPLETE — real-OCC +
   pxr E2E verified):**
   (2a) **Body/link joint origins now export as USD live Xforms** (both the
   Root.Main subtree export AND the composed Assets→USD export). They were
   MISSING because `usd_cli`/`compose_cli` derived the live-Xform frame set only
   from the config origin map (`get_origin_map`), but body origins live in
   `SplitRecipe.body_origins` — injected into the origin map ONLY at bake, never
   persisted. New pure helper `geometry_edits.body_origin_paths(split_map)`
   reconstructs the body paths; both CLIs now union it into the frame set. The
   geometry was already baked at the joint frame (so it rendered right); this
   adds the poseable live Xform for rigging. Verified pxr-E2E
   (`test_usd_body_origin_frames.py`: the body prim carries `xformOp:transform`).
   Also fixed a latent DOUBLE-SLASH bug: `body_path(split_path, name)` (shared by
   the bake injection AND the exporters) normalizes `"/"` (implied-root split) so
   `//Body` → `/Body` — previously an implied-root split's body origins were
   silently skipped at bake (path didn't resolve). Nested splits (the common
   case, e.g. `/Igus Rebel 6`) were already single-slash and unaffected.
-16. **Edit-Bodies re-warn + asset-name-propagation diagnosis round (code
   COMPLETE — real-OCC + offscreen verified):**
   (11) The Transform Source "Editing bodies REPLACES this assembly's contents"
   warning now shows ONLY the FIRST time (when no recipe exists); re-editing an
   existing recipe (`saved is not None`) skips the prompt (`_open_edit_bodies`).
   (2a) **DIAGNOSIS — asset body names/order/origins DO propagate; a
   "Body-1..N default names in the asset" symptom means a RE-SPLIT from a recipe
   in the ASSET's OWN config section, NOT a Root inheritance bug.** Verified via
   the FULL generation path (`test_build_asset_names.py`): Root.Main baked with
   custom names {Base,Elbow,Wrist} + `body_order [3,1,2]`, an EMPTY asset split
   map → the generated asset keeps the custom names in the reordered order.
   assets_build reads ONLY `get_split_map(asset_model_id)` (the asset section) +
   `MODEL_STATIC` — NEVER `MODEL_SOURCE` — so a ROOT body edit reaches the asset
   purely by PRUNING the baked bodies (names/order/frames intact). Therefore
   default-named asset bodies ⇒ the asset section has its OWN (bare) split
   recipe — most likely from doing Edit Bodies while the ASSET model was active
   (a duplicate of the Root edit); at generation it re-decomposes the
   Root-baked bodies into fresh Body-1..N. FIX PENDING confirmation: either drop
   a redundant asset-section recipe when the same product was body-edited at
   Root, or clear the asset's Edit Bodies recipe. (Do NOT re-diagnose this as a
   prune/inheritance bug — that path is proven correct.)
   **9b/9e DIRECTION (user question): SINGLE-BODY cuts would solve the cut
   provenance crux.** If each cut operates on ONE selected body (sequential,
   `body X → [Cut N] → pieces`) instead of the current simultaneous
   `BRepAlgoAPI_Splitter` over the whole part, every body has a clean parent +
   producing-cut → the lineage tree (9b) is accurate + the Transform (9e)
   lineage is natural. Cost: an operation-SEQUENCE recipe redesign (ordered
   per-body cut/merge/transform ops) replacing the flat cut-list + body_count,
   with migration; still deterministic if each op's target body is identified by
   a stable lineage key (not a transient index). This is the foundation for a
   proper 9b+9e round — confirm before building.
-15. **Body-origin asset propagation + body-order-into-Main round (code
   COMPLETE — real-OCC + offscreen verified; live-test pending):**
   (2a) **Body/link origins now PROPAGATE into generated assets** — this was the
   SAME root cause as the "-14 explosion": without `_bake_location`, the body's
   Set-Origin geometry rewrite silently failed, so the body kept its
   un-re-origined position, and the pruned asset showed it at the assembly
   origin (not the joint frame). With the `_bake_location` fix, the body's joint
   frame BAKES into Main AND the asset PRUNE inherits it — verified real-OCC
   (`test_asset_body_origin_prune.py`: Main has Body-1 at its joint origin per
   occurrence; after pruning to one occurrence the asset's Body-1 keeps
   (3,3,3)). NOTE: the asset must be REGENERATED after adding body origins
   (Update's staleness guard re-prunes; a full Generate always does).
   (10) **Body drag-REORDER now bakes into Main.** The recipe `body_order`
   round-trips through the config (`model_dump(exclude_defaults)` → JSON →
   `load_split_map` — verified) and `apply_splits`/`split_stub_assembly` apply
   it (round -13). The GAP was the WINDOW CAPTURE: a QTreeWidget `InternalMove`
   reorder emits remove+insert (`rowsInserted`), not always `rowsMoved`, so the
   handler never fired — now `_on_bodies_reordered` is connected to BOTH
   `rowsMoved` AND `rowsInserted` (guarded by `_rebuilding_bodies`, validates
   the permutation). Offscreen-verified the capture (take/append a row →
   `_body_order` updates) + Apply persists it.
-14. **2a explosion fix + Edit-Bodies UI round (code COMPLETE — real-OCC +
   offscreen verified; live-test pending):**
   (2a) **FIXED "the assembly exploded" when baking a body/link origin.** Root
   cause: a body from a merge-then-edit (`GetShape(assembly)`) carries the
   source child's assembly-local LOCATION, and `XCAFDoc_ShapeTool.SetShape`
   SILENTLY NO-OPS on a located master — so the Set-Origin geometry rewrite
   (`T⁻¹·G`) never applied while the instance-loc compensation (`·t_loc`) did,
   moving the body by the offset. Fix: `_bake_location(shape)` (strip the
   location via `.Located(identity)`, re-apply it through `BRepBuilderAPI_Transform`
   → fresh IDENTITY-location master) at BOTH body `AddShape` sites
   (`_replace_assembly_children` + the leaf-split branch). SetShape then sticks;
   world geometry preserved for single AND multi-instance (real-OCC verified —
   `test_split_then_origin_mi.py`). NOTE: this was a latent bug in
   assembly-merge body origins, exposed now that multi-instanced origins bake
   (round -13); leaf-split body origins already worked (their masters had no
   location).
   (7) The Edit Bodies assembly color-mode chooser (Full per-face vs Flat base)
   is REMOVED — always **Full per-face** now (`_open_edit_bodies` passes
   `per_face=True`; `_ask_assembly_color_mode` is kept but unused). Rationale:
   per-face keeps each sub-part's decals/patches and is the single code path; if
   we ever want flat-base again, restore the chooser (the recipe field
   `assembly_color_mode` still exists).
   (9a) Body Tree header is just **"Body Tree"**. (9c) The cuts list header is
   **"Cuts Tree"**. (9d) Added a **"Merge Tree"** list (each row = a JOIN group +
   the final body it produced, from `_refresh_merge_label`).
   **(9b) BODY-LINEAGE tree — HELD OFF (per the user's "warn me and hold off").**
   Showing each body's operation ancestry as recursive DISABLED child nodes
   (`{name} [Cut N]` / `[Merge N]` / `[Transform]`, renamed bodies as
   `{name} <old>`) needs PER-BODY operation PROVENANCE that the splitter engine
   does not currently track (which cut sliced which body; the pre-cut body
   identity). `run_split`/`apply_merges` would need to thread a lineage tree.
   It's display-only (won't change the deterministic bake), but it's a real
   engine+UI addition — propose as its own round.
   **(9e) TRANSFORM feature (per-body X/Y/Z offset + a/b/c rotation) — HELD OFF.**
   A new deterministic body-transform op: schema (e.g. `SplitRecipe.body_transforms`),
   engine (apply the rigid transform to the body geometry at bake, like a body
   origin but a free transform), a **"Transform"** group in the Edit pane (wrap
   Define Plane→Add Cut in a **"Cut"** group + divider + Transform group), and a
   lineage node (depends on 9b). Substantial new feature — propose alongside 9b.
-13. **Main indicators + clear-on-edit + body reorder + origin-into-Main round
   (code COMPLETE — real-OCC + offscreen verified; live-test pending):**
   (4) The MAIN-window Edit Bodies orange diamond now shows on EVERY occurrence
   of a recipe's product (`_refresh_geometry_edit_indicators` → `resolve_split`
   expands by `product_entry`), like the Transform Source tree.
   (5) A Main edit that changes what BAKES into generated models
   (suppress/unsuppress, color override/clear, Recolor) now warns + CLEARS the
   assets first so they never go stale — `_confirm_edit_clears_assets` (Source
   active + assets exist → prompt; accept clears + proceeds, cancel aborts),
   wired into the suppress/color context-menu branches + `_open_recolor`.
   (6) **Body drag-REORDER in Edit Bodies** — `SplitRecipe.body_order` (a
   permutation of the 1-based FINAL indices) applied at bake in BOTH
   `apply_splits` (reorders bodies+infos after `_body_colors`) AND
   `split_stub_assembly` (iterates `recipe.ordered_indices()`), so the
   restructure planner's walk still matches. The Body Tree is InternalMove
   (flat reorder only — items have ItemIsDropEnabled cleared); `rowsMoved` →
   `_on_bodies_reordered` captures the order, `_refresh_bodies_tree` rebuilds in
   `_display_order`, a re-Test drops a now-invalid order, Apply persists it.
   Real-OCC verified (bake order == stub prediction == [Gamma,Alpha,Beta]).
   LIVE-TEST the actual drag interaction (no GL here).
   (2a) **Multi-instanced joint origins now BAKE INTO MAIN** (was skipped).
   `apply_origins` re-origins the shared product ONCE and compensates EVERY
   distinct instance label by the same `t_loc`, so all occurrences keep their
   world geometry; `expected` is populated for ALL occurrence paths (each moves
   to `W_k·t_local`) so `verify_origins` checks them instead of flagging drift.
   The joint frame becomes a PROPERTY OF THE PROTOTYPE (all occurrences share
   it — correct for rigging); it flows into each asset via pruning. `skip_shared`
   is now a no-op (kept for signature compat). Real-OCC verified (2 Robot
   occurrences, Link re-origined, world preserved + frame at the picked point).
   Supersedes the TODO -10/-11 "set origins in the asset" workflow.
-12. **Suppressed-split crash + suppress-transparency round (code COMPLETE —
   real-OCC-verified for the crash; the render fix needs GL live-test):**
   (2) **FIXED the testC1 crash** "split of /: geometry produced 7 bodies but
   the recipe was authored with 8" when a Main-suppressed part (Link2) that fed
   a split was excluded from the asset source stage. `apply_splits` now takes
   `tolerant` (asset/static generation passes it, threaded from
   `apply_geometry_edits`): a body-count drift DROPS the recipe (logged) instead
   of raising, and `apply_geometry_edits` recomputes the `split_stub_assembly`
   prediction from only the APPLIED recipes (report keys) so the post-split walk
   check doesn't false-fail. The dropped-recipe subtree keeps its surviving
   children un-decomposed; re-author Edit Bodies to re-decompose the reduced
   geometry. Real-OCC verified (strict raises, tolerant drops + keeps the 2
   surviving children). The Main bake stays strict.
   (3) **FIXED (pending GL live-test): suppressing a body turned other
   components transparent.** Hiding/suppressing sets a component's per-cell
   alpha to 0; once ANY cell is <255 VTK renders the whole merged actor in the
   TRANSLUCENT pass, and without depth peeling the opaque cells behind others
   blend through → glassy. `ViewportPanel.__init__` now calls
   `plotter.enable_depth_peeling(number_of_peels=8, occlusion_ratio=0)` (guarded)
   so alpha-255 cells stay solid. No GPU in the dev env — USER must confirm the
   look (and that perf is fine on the 20k-part main view).
   (1) **Body reorder in Edit Bodies — ANSWER, still deferred.** Body order is
   derived deterministically (`body_sort_key` = volume/centroid); names key off
   the pre-merge member tuple and body PATHS are `{split}/{name}`, so names — not
   order — are the durable identifier. A DISPLAY-only reorder would diverge from
   the bake order (confusing); a BAKE-affecting reorder needs a persisted order
   field (member-tuple keyed) threaded through `split_stub_assembly` +
   `apply_splits` so the restructure planner's predicted walk still matches
   (`compare_planned`). Offer to implement if the user wants it.
-11. **Shared-recipe access + asset body-propagation round (code COMPLETE —
   offscreen/real-OCC-verified; testC1 live-test pending):**
   (1a) **Edit Bodies recipes are now shown + editable on EVERY occurrence of
   their product** (Transform Source). Recipes resolve per `product_entry` at
   bake (`resolve_split_targets`), so `_refresh_split_indicators` paints the
   orange diamond on all occurrences sharing a recipe's product, and right-click
   Edit Bodies/Clear on ANY occurrence routes to the SINGLE shared recipe:
   `_open_edit_bodies` redirects to the recipe's OWNING occurrence
   (`_recipe_owner_for`) so the geometry + key stay stable; Clear pops the
   owner's path. (`_recipe_products`/`_recipe_owner_for`; offscreen-tested.)
   (2b) **FIXED: body edits (split/merge/rename) baked into Main didn't reach a
   regenerated asset** when the asset was rebuilt via the FAST path
   (`_fast_rebuild` — "Update Assets" / per-asset rebuilds), which reuses the
   asset's OWN source stage without re-pruning root Main. A root Main re-bake
   makes that source stage STALE (it was pruned from the OLD Main). `_fast_rebuild`
   now compares the asset stamp's `base_main_mtime` against the current root main
   mtime and FALLS BACK to a full re-prune when Main is newer — so post-edit body
   changes flow in. (Verified real-OCC that a merge-then-edit assembly split
   bakes bodies+names into BOTH occurrences AND survives the asset prune — the
   core was always correct; the gap was the stale fast-rebuild.)
   (2a) **Per-body/link joint origins on a MULTI-INSTANCED prototype cannot bake
   at Main** (re-origining a shared product only compensates one occurrence —
   the `apply_origins(skip_shared)` skip from TODO -10). WORKFLOW: set those
   joint frames in the ASSET model (activate the asset — where the prototype is
   single-instance — and use Set Origin on each body component). FOLLOW-UP (not
   done, needs testC1 verification): auto-route the ROOT split recipe's
   `body_origins` into asset generation (map the body path root→asset and the
   frame through R_root) so they bake without the manual step.
-10. **Edit-Bodies + Set-Origin polish round (code COMPLETE —
   offscreen/unit/real-OCC-verified, no GL in dev env; USER LIVE-TEST pending):**
   (1a) Edit Bodies **rejects a rename to an existing body name** (unique names;
   revert + status). (1b) **Merging selects ONLY the newly-merged body**
   (`_select_only_body`, matched by pre-merge member tuple). (1c) The Set Origin
   window opens **zoom-extents keeping the opener's orientation** (inherit pose
   → `reset_camera` refits/centres — not the opener's offset/zoom). (1d) After a
   body-origin Apply, Edit Bodies **selects that body + shows its origin triad**.
   (1g) Edit Bodies **Apply is gated on `_bodies_valid()`** (current Test, ≥2
   bodies, UNIQUE names). (1h) The Main-bake regen prompt's second button is
   relabelled **"Apply + Clear Assets"** (was "Apply Only") — same behavior
   (bake + clear generated models, no regen), clearer intent. (1i) **FIXED the
   testC1 Igus Rebel 6 crash**: per-body/link origins that flow into the Main
   bake on a MULTI-INSTANCED asset used to raise `GeometryEditError` and abort
   the whole restructure (losing tree edits). `apply_origins` now takes
   `skip_shared` (the bake passes True): a multi-instanced origin target is
   SKIPPED + reported (set that joint frame in the single-instance ASSET model)
   instead of failing; `apply_geometry_edits` iterates the APPLIED set
   (`expected`) for reload/verify/mesh-strip so skipped origins are a clean
   no-op. Real-OCC verified (strict raises, skip_shared skips). (2a) Origin
   window **Point Snap enabled only while the Point datum tool is active** (Edge
   datum snaps to the edge itself). (2b) Edit Bodies **body tree header → "Body
   Tree"** and its indicator dot is now painted at the **RIGHT edge** (a
   `_BodyDotDelegate`, `_BODY_DOT_ROLE`) like the main component tree.
   **1e (drag-reorder bodies) — ANSWER, deferred:** body identity is
   deterministic (`body_sort_key`), names key off the pre-merge member tuple,
   and body PATHS are `{split}/{name}` (order-independent), so a DISPLAY-only
   reorder in the window is low-risk and cosmetic (names are the durable key).
   A BAKE-affecting reorder would need a persisted order field (member-tuple
   keyed) threaded through `split_stub_assembly` + `apply_splits` so the
   restructure planner's predicted walk still matches (`compare_planned`) —
   medium effort + planner-match risk; not done.
   **1f (Test button vs auto-Test-on-Add-Cut) — ANSWER, kept:** Add Cut and
   Merge/Unmerge auto-Test, but REMOVING a cut bumps the serial WITHOUT a test
   (Apply then disabled until re-Test), so Test is the manual re-validate /
   refresh escape hatch. Kept.
   **FOLLOW-UP (body/link joint frames on a multi-instanced asset):** today
   they're skipped at Main and must be re-set in the asset model. A nicer future
   fix = route those body-origin frames into the asset's own origin map at
   generation (asset is single-instance → applies cleanly), OR a
   multi-instance-aware re-origin (rewrite the shared product frame + compensate
   EVERY instance location). Needs real-OCC verification on testC1.
-9. **Viewcube-blank + F2-rename + Set-Origin-window round (code COMPLETE —
   offscreen/unit-verified, no GL in dev env; USER LIVE-TEST pending):**
   (7) **FIXED: clicking the viewcube blanked the ENTIRE viewport** (no
   bodies/cube/gizmo). Root cause = `_animate_to` used `vtkCameraInterpolator`,
   which linearly blends the view-up and passes through ~zero magnitude when
   start/end ups are near-antiparallel (a 180° roll) → a degenerate camera →
   a blank render that PERSISTED because the un-guarded `tick` then threw
   before reaching t=1, so the QTimer looped forever on the bad pose. Rewrote
   `_animate_to` to interpolate elementwise HERE (nlerp + renormalise the up;
   hold the END up when antiparallel; lerp position/focal/parallel-scale),
   wrap `tick` in try/except that stops the timer + lands EXACTLY on the end
   pose, and always animate FROM start. Dropped the now-unused `vtkCamera`/
   `vtkCameraInterpolator` imports. (viewport_panel.py)
   (10) Edit Bodies: **F2 renames the selected body** whether the tree OR the
   viewport has focus (a viewport pick selects the body's tree row) — a
   `WindowShortcut` `QShortcut(F2)` → `_on_rename_shortcut` → `editItem` on the
   selected/current body row. (edit_bodies_window.py)
   (11) **Set Origin window reworked** (origin_window.py, all offscreen-tested):
   Origin Datum gains an **Edge** button (BEFORE Point, the default — activated
   on open when no saved frame; arc→its centre, line→its midpoint) and both
   datum buttons carry drawn **icons** (`_point_icon`/`_edge_icon`); the Point
   datum + both axis-point tools now **highlight the snap target on hover** like
   Edit Bodies (`_hover_snap` → `highlight_pick_edge` / `set_face_highlight`;
   tess-face highlight armed only for a SINGLE-leaf subtree, where the per-cell
   face map is unambiguous — `_leaf_tri`); **Flip** moved BELOW the Point Snap
   group and now applies to ALL THREE axis methods (unflipped `_axis_base` +
   `_apply_flip`, set via the shared `_set_axis_base`); **Clear Axis** now
   switches the orientation source to **Global**; **Clear Origin** now just
   clears the in-window selection (no close, no emit — removing a SAVED frame
   is done from the node's context menu, `_clear_geometry_edit(.., "origins")`
   / `_clear_body_origin`, unchanged); **Apply is gated** on `_is_valid()` =
   origin set AND (Global OR a Custom axis defined). LIVE-TEST: edge-datum hole
   centres, snap highlights on hover, Flip on point/points/edge, Apply
   enable/disable, Clear Axis→Global, Clear Origin keeps the window open.
   (9) **Isaac transparency CONFIRMED** — both `opacity_material_test.usda`
   patterns render (per-prim + split-mesh subset). Design note recorded (TODO
   #7): likely author colors ALWAYS per-face (per-`UsdGeomSubset`, N≥1) so
   single/multi-color collapse to one path; implement OmniPBR authoring +
   RGBA alpha next. NOT YET IMPLEMENTED — writers still emit displayColor.
-8. **Transparency + asset-propagation + Set-Origin-redesign round (code
   COMPLETE — offscreen/unit-verified; USER LIVE-TEST + the Isaac transparency
   check pending):**
   (a) **Isaac transparency (item 9) — CONFIRMED working (2026-07-14):**
   `displayColor`/`displayOpacity` are ignored by RTX; a bound **OmniPBR MDL
   material** (opacity_constant) works. `test_files/opacity_material_test.usda`
   PATTERN A (per-prim material) + PATTERN B (per-`UsdGeomSubset` material) BOTH
   verified in Isaac by the user. Implementation still pending: OmniPBR
   authoring in `usd_writer`/compose (see the expanded plan in TODO #7 —
   likely ALWAYS per-face) + an alpha channel from the viewport per-cell RGBA.
   (b) **Asset-occurrence propagation (item 5):** node edits fan out to all
   occurrences (`_expand_asset_occurrences`) — live-test hide/suppress/color on
   one instance updates the others (testC1 Igus Rebel 6, testB1 CRX/M-20iD25).
   (c) **Set Origin redesign (item 6):** right-pane groups (Origin Datum / Point
   Snap / Orientation Source Global|Custom / Orientation Transform: Axis from
   Point/Points/Edge+Flip + nested Point Snap / Clear Axis) — live-test picking
   + the axis tools + Flip.
   (d) **Camera animation (item 7):** viewcube/roll/home/zoom animate — TODO:
   settings menu to enable/disable + set duration (`_anim_enabled`/
   `_anim_duration_ms` already exist).
   (e) items 4 (Transform Source column widths), 8 (Tint Bodies → Identify
   Bodies group, visual-only) — live-test the widths + tint.
-7. **Viewcube-polish + Edit-Bodies fixes (code COMPLETE — offscreen/unit
   verified; GL look = live-test):** (1) viewcube gains HOVER highlight
   (`_cube_set_hover`) + axis colors now come from the shared `_AXIS_RGB` used by
   the bottom-left gizmo too (change palette in one place); (2) body NAMES now
   carry through MERGE (keyed by pre-merge member tuple, not final index —
   `_name_key`/`_body_label`); (3) FIXED "Set Origin… does nothing" — root cause
   was a missing `self._model_label` (AttributeError swallowed by Qt; now stored
   + defensive try/except surfaces future failures); (4) Transform Source
   splitter re-fits in `showEvent` so the two trees open at proper width (were
   collapsed until maximize). Plus Q1: `test_files/opacity_test.usda` awaits the
   user's Isaac check (see #7). LIVE-TEST: viewcube hover/colors, merge names,
   body Set-Origin window, Transform Source initial column widths.
-6. **Viewcube-rebuild + Edit-Bodies round (code COMPLETE — headless/offscreen/
   unit-verified incl. a real-OCC body-origin bake; USER LIVE-TEST pending, no GL
   here). Six items:** (0) viewcube rewritten as a VISIBLE chamfered-facet cube
   (26 cells, pick-by-cell) — fixes dead clicks (opacity-0 pick cube was skipped)
   AND shows edges/corners; the cube cam is now PARALLEL + fit-each-sync so it's
   no longer cropped, and a face click SNAPS the up to the nearest 90°
   (`_snapped_up`); live-test the click→reorient + look. (1) 2-Point cut
   tool (line + Tilt-A rotation). (2) Point-Snap hover now previews the SNAPPED
   point + highlights the edge/tess face (`set_hover_snap`). (3) disc Center U/V
   in Resize Plane. (4) selected-body origin triad under "Show Component Origin".
   (5) per-body Set/Clear Origin → Origin window (view inherited) →
   `SplitRecipe.body_origins` → baked via the origins map. LIVE-TEST all on
   testB1/testC1; the ⟲/⟳ roll direction + viewcube look need eyes. Roll-arrow
   L/R still swappable. Face labels (+X…) on the chamfered cube were dropped for
   now (axis-tinted faces instead) — add billboard labels if the user wants them.
-5. **Editor-polish round (code COMPLETE — headless/offscreen-verified; USER
   LIVE-TEST pending, no GL in dev env). Six items:**
   (a) **Assembly body-color chooser is TEMPORARY.** Opening Edit Bodies on an
   assembly pops `_ask_assembly_color_mode` (Full per-face vs Flat base) so the
   user can COMPARE the two; the pick persists in
   `SplitRecipe.assembly_color_mode` and drives both the window preview and the
   bake (unified via `_assembly_face_colors`). REMOVE the chooser once a default
   is settled (likely default to per-face and drop the popup) — decide after the
   user compares on testC1's Igus Rebel 6 / Rebel 6 Posed.
   (b) The per-face bake alignment assumes `walked.descendants` order ==
   `GetShape(product)` face order; a face-count-drift guard degrades to
   base-only + logs. Confirm on a multi-colored assembly in live testing.
   (c) Point-Snap hover PREVIEW isn't snapped (only the committed click is) —
   the viewport hover marker shows the raw surface point; snapping the preview
   would need the snap logic pushed into the viewport hover observer.
   (d) Viewcube is now a CUSTOM overlay-renderer cube (replaced
   `vtkCameraOrientationWidget` after live oddities: +X→−X mis-pick, absolute
   reorientation, no roll). Snap-to-26-directions + relative-up are unit-tested;
   UNVERIFIED visually (no GL) — live-test that it renders top-right, mirrors
   orientation, faces/edges/corners reorient RELATIVE to the current view, and
   the ⟲/⟳ 90° roll arrows work. Left/right roll direction (currently ⟲=+90,
   ⟳=−90) is trivially swappable if it feels backwards.
   (e) Roll ±90 + Home/Zoom-Extents live on the settings STRIP (top), not
   floating beside the cube — reconsider placement if the user wants them
   literally by the cube (would need VTK button widgets, untestable headless).
   (f) Face-hover highlight overlays a copy of the target mesh — fine for the
   single-part Edit Bodies target; never enable it on a 20k-part main view.
-4. **Prototype assets / Update / Composed / disc+handles follow-ups (code
   COMPLETE — see the Asset splitting + Geometry edits sections)**:
   (a) USER LIVE-TEST on testB1 — mark/unmark fan-out (3× CRX-20iAL merge
   into one asset; nested refusal), Generate (5 assets from the 9 legacy
   marks after normalization), mark/unmark something → italic Assets root →
   Update Assets (kept assets untouched), Export Composed USD (open
   main.usda in Isaac/usdview: placements + shared references + live joint
   Xforms) / STEP (SolidWorks: tree + names + colors) / OBJ, and Edit Bodies
   disc cuts + handle dragging (hover yellow / drag orange).
   (b) **Asset standalone orientation = its Root.Main ORIENTATION** (the
   canonical occurrence's rotation, baked rotation-only at the own origin;
   `R_root`). A part whose Main placement isn't upright (e.g. the Cooling
   Plate platen, or a "Free Drag" arm) appears in that as-placed orientation
   standalone — intended (matches Main); NOT forced axis-aligned. Composed
   exports compensate `W_occ·R_root⁻¹`. (This reverted the brief design-frame
   experiment: a design-frame asset only looked right when the part's design
   frame happened to be Z-up — robots — and showed the raw Source look for
   parts modeled in the scene frame, e.g. the platen.)
   (c) Composed exports load every model at export quality — a cold cache
   re-tessellates per model (progress prints per model; the generate-then-
   export flow hits the display-quality cache).
   (d) `assets_up_to_date` reads dirty for hand-edited partial mark sets
   (safe direction; self-heals on the next load's normalization).
-3. **Transform Source redesign follow-ups (code COMPLETE — offscreen +
   real-GL verified; see the pipeline/"Tree restructure"/"Geometry edits"
   sections)**: (a) USER LIVE-TEST the full workflow on testB1 — Transform
   Source on Main (tree edits + Edit Bodies incl. the M-710iD70 auto-
   decompose + orientation/datum → ONE Apply → bodies appear in Main) →
   Generate → per-asset Transform Source (fast rebuild) → joint origins via
   the main-window menu → exports. (b) **REVISIT (user explicitly asked):
   should multi-solid components be auto-decomposed at STEP PARSE time,
   and/or should the Transform Source window offer a CHECKBOX that
   decomposes ALL multi-solid components into the Main tree?** (today:
   per-component, via Edit Bodies). (c) Edge overlay for the ORIGIN window's
   viewport — the strip's Show Edges toggle only affects viewports that have
   an overlay; Edit Bodies builds one in-process (`build_edges_from_loaded`
   — fine for a single part, NOT a 20k-part mesh) and Transform Source loads
   the stage's edge cache / builds it once via the subprocess
   (`_ts_prepare_and_show`). (d) DONE — body-level origins inside Edit Bodies
   (`SplitRecipe.body_origins`, Set/Clear Origin per body → the existing Origin
   window inheriting the view, baked via the origins map; real-OCC verified).
   (e) A structure map that references BODY paths (authored pre-merge with
   split stubs) fails plan validation in the new window — none exist in the
   user's files; re-author if ever hit.
-2. **Source→Main pipeline follow-ups (code COMPLETE + headless-verified —
   see the pipeline section)**: (a) USER LIVE-TEST — open testB1 (expect the
   one-time layout migration + a rebuild prompt since the old main bake has no
   stamp), Generate Assets from the oriented Main, exports; also delete a
   cache and reopen to exercise fresh-parse auto-generation. (The Transform
   Main window items folded into #-3a.)
   (b) Asset rows could grey/annotate when their stamp's `base_main_mtime`
   predates the current root main (informational; today greyed rows are
   UNCLICKABLE, so this needs a different affordance than `setEnabled(False)`).
   (c) Split-cut PROVENANCE picks are not frame-converted (display-only) — a
   re-edit of an old cut under a CHANGED orientation shows stale pick markers;
   the resolved plane is converted and correct (moot for NEW recipes — the
   Edit Bodies window now authors on the source stage directly). (d) A
   split/origin recipe authored under one orientation stays valid after an
   orientation change (stored source-frame) — no action, just intent.
-1. **Features C+D follow-ups (Edit Bodies + Custom Origins; code COMPLETE —
   see "Geometry edits")**: (a) USER LIVE-TEST (Edit Bodies from the
   Transform Source window: auto-decompose + all four cut tools + extents +
   Test + rename + Apply; origin picks incl. arc-center snap + axis tools;
   verify rebuilds land, indicators show, and the USD joint Xform reads
   correctly in Isaac/usdview); (b) the v1 limits listed in that section
   (structure-moved nodes: no glyph + baked USD; asset exports read only the
   asset's origin map; OBJ has no frames); (c) re-editing an EXISTING cut
   re-uses provenance only for display — cuts are remove+re-add (per-cut
   re-edit UX later).
0. **Feature A follow-ups (backend DONE — see "Tree restructure")**:
   (a) **BUG (parked): moving nodes showed a red no-drop circle on the user's
   machine** — works in offscreen tests at every depth, fails live. History:
   four attempts ending in the manual gesture (Qt's drag stack fully removed,
   `setDragDropMode(NoDragDrop)`) — so the red circle can only be (i) a STALE
   BUILD, or (ii) OUR `ForbiddenCursor`, i.e. the drag/drop was legitimately
   REFUSED (prime suspects: node inside a MULTI-INSTANCED subtree — 60% of
   testB1 Main-level nodes — or a shared-product target; both were silently
   gated). **DONE since: the merged Transform Source window now SURFACES the
   refusal REASON in its status label** (`show_refusal`;
   `draggable_selection`/`drop_target_at` return reasons) — the next live
   attempt will name the cause; live-debug from there.
   (transform_source_window.py `_EditTree`, `drop_target_at`,
   `draggable_selection`)
   (b) restructure across STEP revisions inherits the config-reconciliation
   stopgap (#3) — origin paths that stop matching are reported + dropped, no
   fuzzy matching; (c) moving nodes inside MULTI-INSTANCED assemblies is
   refused by design (XCAF products are shared) — a future "make instance
   unique" (product clone) op would lift that at Main level; per-asset
   restructure already sidesteps it.
1. **STEP rebuild path should reconstruct a filtered ASSEMBLY doc** (products +
   instancing + names + colors mirroring the source), then ONE `Transfer` — replacing
   the flat-doc stopgap. Now used whenever there's suppression, a color override, OR a
   non-identity export orientation/local-origin, so it degrades authored names/
   instancing in more cases → higher priority. Colors DO get written (as StepVisual
   styles; overrides verified in-file). `RemoveComponent`+`Transfer(root)` is broken
   (see gotchas). (writer.py `_transfer_filtered_doc`)
   **The machinery now EXISTS**: `io_step/compose_step.py` builds exactly such
   an explicit assembly doc from a walked model (products deduped by
   `product_entry`, relative locations, names, per-face colors incl. the
   compound-leaf face-fill) — adapt it with an excluded set + the local-origin
   pre-transform to replace `_transfer_filtered_doc`.
2. **Multi-select export.** The tree right-click menu now acts on the whole
   selection for visibility/suppress/color, but EXPORT items are shown only for a
   single selection (`_on_tree_menu` hides them when `len(targets) > 1`). Before
   enabling multi-select export, decide the semantics: do we COMBINE the selected
   subtrees into one exported asset, or export each selected subtree INDIVIDUALLY
   (sequential files)? Answer that, then wire it through `_export_subtree`.
3. **Config↔model reconciliation across STEP revisions (make robust).** Current
   behavior is intentionally MINIMAL: `/`-rooted paths + exact-match on load, with
   unmatched entries listed and an Apply-matched / Cancel-opening prompt
   (`_confirm_config_mismatch`). This is a stopgap until partners send real revised
   STEP files — only then will we know how structure actually drifts. FUTURE, once we
   have samples: fuzzier matching (renamed/moved parts, bbox/geometry hints, not just
   name-path equality); a proper diff report; and **change highlighting** so the user
   can see in the TREE (and maybe the viewport) exactly what was added / removed /
   moved / renamed since the last version of the file. Also consider a config backup
   before the first overwrite of a reused config. (scene_config.py `load_scene_config`
   / `_resolve_node_key`; main_window `_confirm_config_mismatch`)
4. **Revert the temporary Root node.** `tree_panel.SHOW_IMPLIED_ROOT` is TEMPORARILY
   `True` so the implied assembly root shows as a tree row (added back at the user's
   request so they can right-click it → export the WHOLE scene as one subtree). The
   intended long-term behavior is to hide it (children as top-level rows). Flip the
   flag back to `False` when the whole-scene-export need is done. Paths are unaffected
   either way (`build_path_maps` always omits the implied root).
5. **Rigging — PARTIALLY DONE.** Prismatic/revolute **JOINT DEFINITION** (with
   USD drive APIs + optional limits + full articulation authoring) is BUILT — see
   the "Kinematic joints" section (headless-verified; GUI/GL live-test pending).
   Link GROUPING uses the existing restructure (link folders). STILL open / await
   the user's spec: joint TARGET-POSITION authoring from telemetry, a master
   Isaac stage wiring, world-grounded base joints (empty Body0), and any
   mass/inertia if a real physics articulation (not a kinematic shadow) is ever
   wanted. Do NOT expand joint scope beyond what's built without the user's ask.
6. **Per-face colors in OBJ export.** USD + STEP are DONE. USD: `usd_writer` authors
   per-face `displayColor` (`uniform` = one color/triangle via `tri_faces`+`face_colors`).
   STEP: `writer._transfer_filtered_doc` sets per-FACE `SetColor` on the rebuilt shapes
   (mapped via `BRepBuilderAPI_Transform.ModifiedShape`), so the writer emits per-face
   styles (verified: SS040 → ~1832 styled items). Both CLIs bake node overrides (→
   constant) + global recolor (→ per-face remap). STILL per-component: **OBJ** (would
   need `usemtl` groups keyed by `tri_faces` color; obj_writer/obj_cli use
   `resolve_effective_colors`) — face-only recolor rules show in viewport/USD/STEP but
   not OBJ until this lands.
7. **Alpha / opacity (transparency).** NOT addressed yet by request. STEP/USD/OBJ all
   support it as a SEPARATE channel from RGB (STEP `SURFACE_STYLE_RENDERING.transparency`;
   USD `primvars:displayOpacity` parallel to displayColor; OBJ `.mtl` `d`/`Tr`
   per-material). Neither test file uses any (0 transparency entities). The render layer
   already reserves per-cell **alpha** (used for hide=0 + the opacity slider). WHEN
   wanted (e.g. see-through **windows**): read the rendering-style transparency in the
   same style traversal (`_decode_style_color`/`_iter_style_colors`) into an optional
   per-face alpha, fold it into the alpha channel (`source_alpha × slider × hidden`),
   carry through exports (displayColor+displayOpacity / `d`), and extend the RGB-keyed
   matching (recolor/eyedropper) to RGBA. Keep colors RGB until then.
   **Isaac transparency — FINDING (user-verified):** Isaac's RTX renderer
   IGNORES `displayColor`/`displayOpacity` for transparency (those are usdview/
   Storm-preview only) — `test_files/opacity_test.usda` came up solid. It DOES
   honor a bound **OmniPBR MDL material**: the user's working "CubeCustom" uses
   `MaterialBindingAPI` → Material → Shader (`info:mdl:sourceAsset=@OmniPBR.mdl@`,
   subIdentifier `OmniPBR`) with `diffuse_color_constant` + `enable_opacity` +
   `opacity_constant`. **Path forward for full color+alpha in Isaac:** author an
   OmniPBR material per color — single-color part → one bound material; our
   per-FACE colors → split the mesh into `UsdGeomSubset`s (one per distinct
   color) each bound to its own OmniPBR material (keep `displayColor` as the
   usdview fallback). Fact-finding file `test_files/opacity_material_test.usda`
   (generated via pxr `UsdShade`) authors BOTH patterns for the user to confirm
   in Isaac: PATTERN A (single-color cubes, opacity 1/.75/.5/.25) + PATTERN B
   (one mesh, 2 `UsdGeomSubset`s → opaque + translucent materials). Once
   confirmed, wire OmniPBR authoring into `usd_writer`/`compose` (per-prim for
   single color, per-subset for multi-color) + thread an alpha channel from the
   viewport's per-cell RGBA.
   **CONFIRMED (2026-07-14): BOTH patterns render correctly in Isaac** — the
   per-prim material AND the split-mesh `UsdGeomSubset` blue/red translucent
   cube both work. So OmniPBR-material authoring is the committed path; the
   remaining work is the writer implementation (below), not more fact-finding.
   **DESIGN NOTE for the implementation — likely ALWAYS author colors per-face
   (per `UsdGeomSubset`), even for single-color parts.** Rationale the user
   raised: it collapses the single-vs-multi-color branch into ONE code path
   (every mesh = N subsets, N≥1, each bound to one OmniPBR material), so
   there's no special case and adding alpha is uniform. Concretely: (1) group
   a mesh's triangles by quantized RGBA (reuse `_quantize` / the per-cell RGBA
   the viewport already computes — base+per-face+recolor+overrides+the alpha
   channel); (2) one `UsdGeomSubset` (elementType=face, familyName="materialBind")
   per distinct color, indices = that color's triangle ids; (3) one OmniPBR
   `Material`/`Shader` per distinct color (dedupe file-wide by RGBA so N cubes
   of the same color share one material) with `diffuse_color_constant`,
   `enable_opacity`, `opacity_constant=alpha`; (4) bind per-subset via
   `MaterialBindingAPI`; keep `displayColor`/`displayOpacity` (uniform) as the
   usdview/Storm fallback. A 1-color part is then just the N=1 case (single
   subset spanning all faces, or bind the whole gprim). Cost: more subsets/
   materials in the file — acceptable (materials dedupe; subsets are cheap
   index arrays). Do this in the shared `usd_writer` mesh-authoring path so
   BOTH the per-asset writer and `compose` (`write_model_usd` /
   `write_composed_main`) inherit it, and the alpha comes from the SAME
   per-cell RGBA `bake_effective_appearance` already produces (extend it to
   RGBA — TODO #7's alpha-channel work). Decide during implementation whether
   to gate OmniPBR behind a config flag (Isaac target) vs keep pure
   displayColor for non-Isaac USD consumers.
8. **Packaging follow-ups** (Windows onedir build DONE + headless-verified — see the
   "Packaging" section for how everything works): (a) **user live-test of the frozen
   GUI** from `dist/CellSmith/CellSmith.exe` on a machine/shell WITHOUT the conda env
   — open a STEP with its cache deleted (parse worker + .xbf write), Show 3D + edges,
   exports, Generate Assets, a restructure Apply, reopen (fast cache load); (b) DONE
   — `console=False` (windowed, no console window; `_ensure_std_streams()` guards the
   None stdio; robust fail-loud `make_zip.ps1` archiver); (c) Linux DONE (tar.gz built + workers +
   WSLg GUI smoke verified under WSL2 Debian) — remaining: live-test on a real Linux
   desktop when one exists; (d) LATER: GitHub Actions ci/release workflows
   per the MTConnectExplorer pattern (`windows-latest` + `ubuntu-latest` runner jobs
   publishing both archives to a versioned GitHub Release; version gate on
   `src/__version__.py`).
9. **[LOW PRIORITY] Multiprocess tessellation.** Show-3D meshing is ~2× faster via the
   in-process compound `BRepMesh` (`tessellate_many`), but the Python triangle
   EXTRACTION stays serial (GIL; threads don't help — confirmed). True parallelism =
   a subprocess POOL: N workers each load the `.xbf`, mesh+extract a slice of
   components, write a partial mesh cache the parent merges (mirror `cache_build`/
   `edges_build`). Est. ~3–4× on 16 cores. RISK: each worker holds the full OCC doc
   (~1–2 GB for the 875 MB model) → cap workers (4–6) to avoid thrashing; plus
   partial-cache-merge + cross-process progress plumbing. Not urgent.


---

## Future SF/CGB commands (migrated from the CGB spec)

These were the CGB spec's Short-/Long-Term todos (its Todo-Now is all shipped — see `Reference/selection-and-cgb.md`). Kept here as the single ledger; the spec now points here.

**Short-term (commands to build next):**
- **Joint / mate inference (F10)** — concentric cylinders → a revolute axis; coplanar faces → a hinge; *suggest*, don't auto-apply. Uses Fit Primitives.
- **Unbend / Pose command scaffold (F11)** — per-link joint-axis detection + per-link frames + sequential straightening.
- **Unbend into orthogonal pose** — straighten an imported robot into a home pose so joints/frames are easy to author. Depends on F11 + Fit Primitives + Frame + Measure.

**Long-term (capabilities & commands):**
- **Per-face color override** — override colors on individual faces / face sets. Depends on Collect/face-set output + Select-Similar + Loop + Marquee.
- **Select Similar / Select By (F2)** — pick by color, surface kind, radius, size, prototype.
- **Loop / tangent-chain / boundary selection (F7)** — hole rim, face loop, fillet chain in one click.
- **Marquee + paint-drag + grow/shrink/invert (F8)** — region selection ops.
- **Symmetry / mid-plane / best-fit constructions (F9)** — averaged axes/points through N features (uses a growable collector slot, D8).
- **Constraint relations (F12)** — concentric / coincident / tangent / perpendicular → an auto-derived frame.
- **Saved selection sets (F13)** — persist a Collect-mode set of faces/bodies for reuse.
