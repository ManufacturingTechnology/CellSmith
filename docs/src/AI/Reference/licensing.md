---
title: 'Licensing'
audience: both
---

# Licensing — Apache-2.0 outbound vs. the third-party payload

**Abstract.** Whether CellSmith can ship its own code under Apache-2.0 given its dependency
set (**yes**), and the obligations the *frozen distributable* incurs. Contains the measured
license inventory of everything the onedir build actually bundles, the compatibility
reasoning per copyleft component, the six gaps found on 2026-08-04 (**all six now closed**),
and the as-built notices machinery. Read before changing `LICENSE.TXT`, adding a dependency,
or shipping a build to anyone outside the team. Verify against `packaging/environment.yml`
and a fresh build TOC; may lag.

!!! warning "Engineering analysis, not legal advice"

    This page records what was measured and how the licenses read on their face. Anything
    marked **❓** was not verified. A distribution decision with real exposure — especially
    an external release — should be reviewed by counsel. The recommendations are ordered by
    risk so the cheap, unambiguous ones can be done immediately.

---

## Verdict

| Question | Answer |
|---|---|
| Can CellSmith's **own source** be Apache-2.0? | **Yes.** No dependency constrains the license of first-party code. |
| Do any dependencies make Apache-2.0 outbound *impossible*? | **No.** Every copyleft dependency is **weak** copyleft (LGPL) consumed by dynamic linking, which LGPL expressly permits. |
| Is the **repository** currently compliant? | **Nearly** — one gap: `LICENSE.TXT` has no copyright holder (R1, deferred by the user 2026-08-04). |
| Is the **frozen distributable** currently compliant? | **Yes, to the extent measured.** All six gaps (L1-L6) were closed on 2026-08-04. The generator now reports **0 gaps**. Remaining items are hygiene the user declined (R6, R7) or the unfilled copyright line (R1). |

The distinction in the last two rows is the whole point of this page: the source tree is
almost fine; the **binary** is where the obligations live. Before 2026-08-04 the build
shipped ~1991 files with essentially no attribution; it now ships `LICENSE.TXT` plus a
generated `THIRD-PARTY-NOTICES.md` (see *As built* below).

## How this was measured

Primary sources only, on 2026-08-04:

- **conda packages** — `<env>/conda-meta/*.json` `license` / `license_family` fields (74
  packages). This is the only way to learn OCCT's and pythonocc's terms; neither has a pip
  wheel.
- **pip distributions** — `importlib.metadata` `License`, `License-Expression`, and
  `License ::` trove classifiers (61 distributions).
- **what is actually shipped** — `build/cellsmith/COLLECT-00.toc`, PyInstaller's own record
  of the 1991 files the last build collected. Metadata for an *installed* package proves
  nothing about distribution; the TOC does.
- **native import edges** — `grep -a` for DLL names in the PE import tables of
  `Library/bin/TK*.dll`, to find *which* OCCT library drags in FreeImage.

Probe: `scratchpad/probe_licenses.py` → `scratchpad/licenses.json`.

## Cross-sectional matrix — what is shipped, under what terms

### Copyleft and non-OSI components in the payload

| Component | Shipped as | License (measured) | Outbound-compatible with Apache-2.0? | Obligation |
|---|---|---|---|---|
| **Qt 6** (via PySide6 / shiboken6 6.11.1) | 44 DLLs + `plugins/` | `LGPL-3.0-only OR GPL-2.0-only OR GPL-3.0-only` | ✔ under LGPLv3, dynamic linking | license text + prominent notice + relink ability + source or written offer |
| **OCCT 7.9.3** | 50 `TK*.dll` | `LGPL-2.1-only` **plus the OCCT header exception** | ✔ | LGPL notice **+** the exception's own "prominent notice" condition |
| **pythonocc-core 7.9.3** | 645 `OCC/*.pyd` | `LGPL-3.0-or-later` | ✔ | license text (already bundled as `OCC/LICENSE`) + source offer |
| **FreeImage 3.18.0** | `FreeImage.dll` | `GPL-2.0-or-later OR GPL-3.0-or-later OR FreeImage (FIPL)` | ✔ — **FIPL elected 2026-08-04** | ✅ election stated + FIPL text reproduced in the generated notices (`FREEIMAGE_ELECTION = "FIPL"`) |
| **freetype 2.14.3** | `freetype.dll` (+ VTK's vendored copy) | `GPL-2.0-only OR FTL` | ✔ if FTL elected | FTL requires **credit in documentation** |
| **libiconv 1.18** | `iconv.dll` | `LGPL-2.1-only` | ✔ | license text + source offer |
| ~~Intel oneMKL 2026.0.0~~ | ~~**25** `mkl_*.dll`~~ | ~~`LicenseRef-IntelSimplifiedSoftwareOct2022`~~ | — | ✅ **REMOVED 2026-08-04** (R5). The env now uses OpenBLAS (BSD-3); `mkl`, `onemkl-license` and `tbb` are uninstalled and 0 `mkl_*.dll` remain. Kept in this table so the reason it is absent is discoverable. |

### Permissive components in the payload

All compatible; all require the copyright notice + license text to be **reproduced in the
distribution** (BSD §1–2 / MIT / Apache-2.0 §4).

| License | Components |
|---|---|
| BSD-3-Clause | **VTK 9.6.2 (209 DLLs)**, numpy 2.5.1, scipy 1.18.0, shapely 2.1.2, pooch |
| MIT / MIT-CMU | pyvista, pyvistaqt, pydantic (+`pydantic-core`), PyYAML, trimesh, platformdirs, scooby, annotated-types, Pillow 12.3.0 |
| Apache-2.0 | manifold3d 3.5.2, oneTBB 2023.0.0, OpenSSL 3 (`libssl-3`/`libcrypto-3`), `packaging` |
| **TOST 1.0** | **usd-core 26.5** (85 `pxr/*`) — the *Tomorrow Open Source Technology License*, textually Apache-2.0 with **§6 "Trademarks" replaced**. Permissive, but it is **not** Apache-2.0, so its own text must be reproduced. |
| ISC | mapbox_earcut 2.0.0 |
| PSF-2.0 / matplotlib | typing_extensions, matplotlib 3.11.0 (+ its DejaVu/STIX font licenses, already bundled) |
| Public domain | SQLite |
| **SIL OFL 1.1** | IBM Plex Sans + JetBrains Mono — **already compliant**: `src/resources/fonts/OFL-*.txt` ship beside the `.ttf`s and the files are unmodified (OFL's Reserved Font Name clause). See `packaging.md`. |

### Build-time components

| Component | License | Effect on CellSmith's license |
|---|---|---|
| **PyInstaller 6.21.0** | `GPL-2.0-or-later` **with a special exception** — verbatim from its metadata: *"with a special exception which allows to use PyInstaller to build and distribute non-free programs (including commercial ones)"* | **None.** The exception exists precisely so the bootloader compiled into `CellSmith.exe` does not infect the app. |
| **Inno Setup 6** | ✅ **VERIFIED 2026-08-04** by reading the installed `license.txt`: a **zlib-style permissive** licence. Copyright (C) 1997-2026 Jordan Russell; portions (C) 2000-2026 Martijn Laan. *"Permission is granted to anyone to use this software for any purpose, including commercial applications."* | **None, and CellSmith complies.** The only binary-form condition (2) is to *retain* copyright notices and web addresses already present — measured: `Setup.e32`/`SetupLdr.e32` carry them as UTF-16LE strings, and `build.bat` does no post-processing of the installer, so they survive verbatim. Condition 3's acknowledgement is *"appreciated but not required"*; it is given anyway in the generated notices. |

## Why LGPL dependencies do not block Apache-2.0

Three points, because this is the part most often got wrong:

1. **LGPL is designed for exactly this.** LGPL-2.1 §6 and LGPL-3.0 §4 permit combining the
   library with a work "under terms of your choice", provided the library stays separable
   and replaceable. CellSmith loads Qt, OCCT and pythonocc as **separate DLLs/PYDs** in a
   onedir layout — the strongest form of the arrangement LGPL contemplates. Nothing is
   statically linked.
2. **The "Apache-2.0 is incompatible with GPLv2" rule does not apply here.** That
   incompatibility is about *merging Apache-licensed source into a GPLv2 work* — Apache-2.0's
   patent-termination terms add a restriction GPLv2 forbids. CellSmith does not merge OCCT
   source into its own code; it calls a library. The GPL-conversion path is never exercised,
   so `LGPL-2.1-only` vs `-or-later` is moot for this use.
   ❓ *Unresolved:* conda-forge tags OCCT `LGPL-2.1-only`, while upstream's per-file notices
   are the usual "2.1 or, at your option, any later version". Not worth resolving unless
   someone wants to relicense a *derivative of OCCT itself*.
3. **OCCT adds its own exception that helps further.** From
   [`OCCT_LGPL_EXCEPTION.txt`](https://github.com/Open-Cascade-SAS/OCCT/blob/master/OCCT_LGPL_EXCEPTION.txt):
   object code incorporating material from OCCT headers may be distributed *"under terms of
   your choice, provided that you give prominent notice in supporting documentation to this
   code that it makes use of or is based on facilities provided by the Open CASCADE
   Technology software."* Note this is a **condition**, and it is an obligation CellSmith
   does not currently meet (L2).

!!! note "The ASF's Category-X ban on LGPL does **not** apply to CellSmith"

    [Apache legal policy](https://www.apache.org/legal/resolved.html) prohibits GPL and
    "GNU LGPL 2, 2.1, 3" in **Apache Software Foundation products**. That is ASF *project
    policy* for code the foundation itself ships — not a term of the Apache License. A
    non-ASF project that chooses Apache-2.0 as its outbound license is unaffected. Reading
    Category X as "Apache-2.0 forbids LGPL dependencies" would rule out this entire
    architecture for no reason.

## Unmet obligations in the frozen build

Measured against `COLLECT-00.toc`: of 1991 bundled files, exactly **28** are license/notice
texts, and 26 of those arrived incidentally inside `numpy`/`trimesh`/`pydantic` dist-info
folders. There is **no `PySide6*.dist-info` in the bundle at all**, so Qt's LGPL text is
absent.

| id | Gap | Status | Why it matters |
|---|---|---|---|
| **L1** | **Qt/PySide6 LGPLv3**: no license text, no notice, no source offer. | ✅ **closed** 2026-08-04 (R3+R4) | [Qt's own statement](https://www.qt.io/licensing/open-source-lgpl-obligations) of the obligation: *"A copy of the LGPL license text"* and *"a prominent notice about using the LGPL library – i.e. it is not allowed to hide the fact the LGPL library is used"*, plus complete corresponding library source **or a written offer**. The relink requirement is satisfied *in substance* by onedir (Qt DLLs are separate, user-replaceable files) but that is not stated anywhere. |
| **L2** | **OCCT exception's "prominent notice" is missing.** | ✅ **closed** 2026-08-04 (R4) | It is a condition of the exception being available. |
| **L3** | **`FreeImage.dll` ships with no license elected.** | ✅ **closed** 2026-08-04 — **FIPL elected** (R2) | Its default reading includes GPLv2/v3. Distributing an unelected GPL-or-FIPL binary alongside a non-GPL app is the one item here that is a *conflict* rather than a paperwork gap. **`TKService.dll` imports it at load time** (measured), so it cannot simply be deleted — see R2. |
| **L4** | **25 Intel MKL DLLs** under a proprietary license, unnecessary. | ✅ **closed** 2026-08-04 (R5 — MKL uninstalled) | `mkl_scalapack_*`, `mkl_blacs_*`, `mkl_cdft_*` are MPI/cluster libraries with no possible use here. Shipping a non-OSI binary is legal but adds an obligation and ~hundreds of MB for nothing. |
| **L5** | **BSD/MIT/Apache/ISC/TOST notices not reproduced.** | ✅ **closed** 2026-08-04 (R3) | VTK alone is 209 DLLs under BSD-3, whose §1–2 require the notice to accompany binary redistribution. Same for OpenUSD's TOST text, oneTBB, OpenSSL, manifold3d, mapbox_earcut. |
| **L6** | **freetype**: no FTL election, no credit line. | ✅ **closed** 2026-08-04 (R4) | The FTL requires credit in documentation; the alternative is GPLv2. |

## Recommendations, ordered by risk

| id | Action | Effort | Blocks a release? |
|---|---|---|---|
| **R1** | Fill in `LICENSE.TXT`'s appendix copyright line, and add a `NOTICE` file naming the project + copyright holder. **Needs a decision: who is the copyright holder** (the user personally, or AMT as work-for-hire)? | minutes | yes — a license with `[name of copyright owner]` unfilled grants nothing clearly |
| **R2** | ✅ **DONE 2026-08-04 — FIPL elected.** `FREEIMAGE_ELECTION = "FIPL"` in the generator; the notices file now states the election affirmatively and reproduces the FIPL text, and the build reports **0 gaps**. Rationale: FreeImage is shipped **unmodified** (it arrives only as a load-time dependency of OCCT's `TKService`), so FIPL's source-availability clause — which reaches only FreeImage files *we* modify — imposes nothing beyond reproducing the text. Route (b), dropping the DLL by narrowing `hook-OCC.py`, remains available purely as a **size** optimization. | — | resolved |
| **R3** | ✅ **DONE 2026-08-04.** `packaging/gen_third_party_notices.py` generates `THIRD-PARTY-NOTICES.md` from the live environment on every build; the spec ships it plus `LICENSE.TXT` at the payload root. See *As built* below. | — | resolved |
| **R4** | ✅ **DONE 2026-08-04**, in the same generated file — the LGPL-2.1/3.0 + GPL-3.0 texts, the written source offer, the dynamic-linking/relink statement, the OCCT prominent notice (L2) and the FreeType FTL credit (L6). | — | resolved |
| **R5** | ✅ **DONE 2026-08-04.** `libblas=*=*openblas` pinned in `packaging/environment.yml` and applied to the live env: **`mkl`, `onemkl-license` and `tbb` REMOVED, `libopenblas` (BSD-3-Clause) installed, 0 `mkl_*.dll` remaining**. L4 closed; the generator's non-OSI scan now returns empty. The ❓ bonus turned out **real but not conclusive** — see the ⚠️ note in [occ-vtk-gotchas.md](occ-vtk-gotchas.md). | — | resolved |
| **R6** | ⛔ **DECLINED by the user 2026-08-04** — no SPDX headers. Consequence to be aware of: a `src/` file copied out of the repo carries no licence statement of its own; `LICENSE.TXT` covers the repo, not a loose file. | — | declined |
| **R7** | ⛔ **DECLINED by the user 2026-08-04** — no CI licence gate. ⚠️ Consequence: the detection logic exists inside `gen_third_party_notices.py`, but it only *warns* at build time and writes a *Gaps* section; nothing **fails**. A future `conda install` / `pip install` that re-pulls MKL (or any GPL package) will be caught only if somebody reads the build log or the shipped notices file. This is exactly how MKL got in unnoticed the first time. | — | declined |
| **R8** | ✅ **DONE 2026-08-04** — Inno Setup's licence read and recorded in the *Build-time components* table above. **No issues found**; CellSmith already complies, and the optional acknowledgement is now given. | — | resolved |

**Ordering rationale:** R1 and R2(a) are minutes of work and remove the only two items that
are more than paperwork. R3+R4 are the bulk of the compliance work and should land together
in one generated file. R5–R8 are hygiene that make the state durable.

## As built (2026-08-04)

### The generated notices file

`packaging/gen_third_party_notices.py` → `build/THIRD-PARTY-NOTICES.md` → shipped at the
payload root beside `LICENSE.TXT`.

| Aspect | As built |
|---|---|
| **Invocation** | From **`packaging/cellsmith.spec`**, not from `build.bat`/`makefile`. Both OSes run the same spec, so Windows and Linux cannot diverge and neither script can forget it. Loaded by path via `importlib` — `import packaging.…` collides with the pip `packaging` module. |
| **Sources** | `importlib.metadata` for wheels (license expression, classifiers, and the verbatim text out of `*.dist-info/licenses/`) + `<env>/conda-meta/*.json` for conda packages. |
| **Curated texts** | `packaging/licenses/`: `LGPL-2.1`, `LGPL-3.0`, `GPL-3.0`, `FTL`, `FreeImage-FIPL`, `OCCT-LGPL-EXCEPTION`. conda does **not** extract license text into the prefix, so these cannot be discovered — they are checked in, fetched verbatim from upstream. Cross-check: the fetched `LGPL-3.0.txt` differs from the env's own `OCC/LICENSE` by exactly one character (`http` vs `https` in the FSF URL). |
| **Obligations discharged** | Qt named as LGPLv3 + dynamic-linking/relink statement; the OCCT exception's prominent notice verbatim; a three-year **written offer** for LGPL source; the FreeType FTL credit line; every discoverable BSD/MIT/Apache/ISC/TOST text reproduced. |
| **Fail-soft** | Never breaks a build. Unresolved items become `NOTICE-WARN:` on stderr **and** a *Gaps* section inside the shipped document, so an incomplete file is visibly incomplete. |
| **Rot guard** | Scans every conda license string for GPL/AGPL/`LicenseRef-IntelSimplified`/SSPL/BUSL and warns unless the component is in `_RESOLVED`. This is what catches MKL coming back. |
| **Size** | ~645 KB, 93 verbatim license texts, 132 inventory rows. |
| **Guarded by** | `tests/test_third_party_notices.py` — texts exist and are genuine (not stubs or HTML), every obligation string is present, the spec ships both files, and the env has no unresolved copyleft/non-OSI package. |

### The MKL removal

`libblas=*=*openblas` pinned in `packaging/environment.yml` and applied to the live env.
`mkl`, `onemkl-license` and `tbb` uninstalled; `libopenblas` 0.3.33 (BSD-3-Clause) in.
**0 `mkl_*.dll` remain.** Verified by `scratchpad/openblas_env_test.py` (8/8): numpy's
backend is not MKL, no `mkl_*` module is mapped into the process, OCCT geometry works, the
real **STEP → XCAF → `.xbf` → reopen** round trip works (the `CSF_*` hard-fail path), Qt +
pyvista render offscreen, trimesh/scipy/shapely and pxr work. The full `scratchpad/`
sweep and the pytest suite pass alongside it.

!!! tip "Side effect worth knowing about"

    `pv.Sphere()` and `a @ a` — both explicitly banned by
    [occ-vtk-gotchas.md](occ-vtk-gotchas.md) as hard `0xC06D007F` crashes — now **survive**
    in a process with Qt + OCC + a rendered VTK/pyvista scene. The ban may have been an MKL
    artifact all along. It stays in force until someone tests the windowed GUI and the
    frozen build; see the ⚠️ note there.

### The Linux toolchain rows (2026-08-04) — three ways a copyleft row is resolved

All of the analysis above was done on **Windows**. The first Linux CI run surfaced **eight
GPL-3.0 conda rows the Windows env simply does not have**, and the rot guard
(`test_environment_has_no_unresolved_copyleft_package`) failed on all eight. None turned
out to be an obligation, but the reasons differ, and the generator now encodes each one
**and renders it into the notices** — a copyleft row suppressed by name with no published
reason is an unauditable licensing claim.

| Rows | Resolution | Mechanism in `gen_third_party_notices.py` |
|---|---|---|
| `libgcc`, `libgcc-ng`, `libgomp`, `libstdcxx`, `libgfortran`, `libgfortran5` — all `GPL-3.0-only WITH GCC-exception-3.1` | The **[GCC Runtime Library Exception v3.1](https://www.gnu.org/licenses/gcc-exception-3.1.html)** grants "unlimited permission to propagate" the runtime as part of a compiled program regardless of that program's license. Every non-GPL binary compiled by GCC on Linux relies on it. | `_spdx_exception()` — a general rule: SPDX `<license> WITH <exception-id>` clears the check, because the exception *is* the grant. Rendered as a table naming each exception id. |
| `ld_impl_linux-64` (`GPL-3.0-only`) | GNU `ld` from binutils — the **linker**, used only while conda installs packages. PyInstaller links nothing and never copies it into `_internal/`. | `_BUILD_ONLY` — name → prose reason. conda-meta describes the **environment**, not the payload; that distinction has to be made by hand. |
| `readline 8.3` (`GPL-3.0-only`, **no exception**) | The one genuine conflict, had it shipped. Resolved by **keeping it out**: spec `excludes=`, plus a `verify-payload.sh` assertion. CellSmith has no REPL and imports it nowhere. | `_EXCLUDED_FROM_PAYLOAD` — name → prose reason. |

!!! warning "The substring match was always going to do this"

    `_NEEDS_DECISION` is a list of SPDX id **substrings**, so `"GPL-3.0-only"` matches
    `"GPL-3.0-only WITH GCC-exception-3.1"`. That is a false positive of the matcher, not a
    finding. The fix deliberately keeps the general rule (any linking/runtime exception
    clears) rather than allowlisting the six GCC names, so a future `Classpath-exception` or
    `LLVM-exception` package resolves the same way — and every one of them is **listed with
    its exception id** in the shipped notices, so the reliance is visible.
    `test_a_license_exception_resolves_a_gpl_row_but_bare_gpl_still_gaps` pins both halves:
    the exception clears, a bare `GPL-3.0-only` still gaps.

**One predicate, two callers.** `unresolved_reason(row)` is now the single definition of
"this is a gap", called by both the generator's Gaps section and the test's rot guard. They
used to be separate copies of the rule — a guarantee of eventual disagreement, in which the
*test* would have been the one that looked right.

### Still open

- **R1 — the only substantive one.** `LICENSE.TXT` is still the stock Apache text with
  `Copyright [yyyy] [name of copyright owner]` unfilled, so the repository grants nothing
  under a clearly identified holder. Deferred by the user 2026-08-04. Note as evidence,
  not as an assumption: `packaging/cellsmith.iss` sets `AppPublisher=AMT`.
- **R6, R7 declined** (see the table). R7's absence is the one that decays over time —
  nothing *fails* when a copyleft package re-enters the environment.
- ❓ **Never measured:** whether the shipped notices are *reachable* by an end user in the
  GUI. They install to `{app}/_internal/` (the installer's `[Files]` entry is
  `Source: {#DistDir}\*` with `recursesubdirs`, so both files do land on disk), but nothing
  in the app surfaces them — there is no About box. LGPL's "prominent notice" is arguably
  weaker for a file the user must go find. A Help ▸ About with the licence text would
  settle it.

## Related

- `packaging.md` — what the build bundles, the OFL font handling, the hooks that decide the payload.
- `occ-vtk-gotchas.md` — the no-BLAS-matmul ban that R5 might retire.
- `invariants.md` — R7 becomes an invariant once the check exists.
