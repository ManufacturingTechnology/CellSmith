---
title: 'Testing'
audience: agent
---

# Testing — tiers, commands, and the system dependencies CI needs

**Abstract.** How the suite is split (three tiers), the commands on each platform, and —
load-bearing for CI — the **exact Linux system packages** offscreen rendering requires,
established by testing in a real `python:3.12-slim` container rather than by guessing.
Read before adding a test that renders anything, and before writing a CI workflow.
Verify against `tests/`, `pytest.ini`, `Makefile`, `test.bat`, `test-ci.bat`; may lag.

## Commands

| Goal | Windows | Linux / make |
|---|---|---|
| Everything | `test.bat` | `make test` |
| CI-eligible only | `test-ci.bat` | `make test-ci` |

`make` is not on `PATH` in PowerShell here, which is why the `.bat` wrappers exist. Both
wrappers auto-locate `conda.exe` and set `QT_QPA_PLATFORM=offscreen`.

## Marker polarity — the one design decision to know

A test is **CI-eligible BY DEFAULT** and must opt out with `@pytest.mark.local_only`.
Chosen deliberately: a test whose author forgets to mark it then **fails loudly in CI**
rather than silently never running. Markers (registered in `pyproject.toml`, enforced by
`--strict-markers`):

| Marker | Meaning |
|---|---|
| `local_only` | needs a real display, GPU driver, or interactive input — excluded from `make test-ci` |
| `gl` | renders through OpenGL offscreen; **still CI-eligible**, but see the dependency table |
| `slow` | more than a few seconds; still CI-eligible |

## Three tiers

| Tier | Checks | Needs | CI? |
|---|---|---|---|
| **1 — Logic** | OCC/XCAF results, transforms, config round-trips, USD authoring | nothing | ✔ |
| **2 — Offscreen visual** | did a render change; do widgets lay out; picking hits the right cell | `QT_QPA_PLATFORM=offscreen` + the packages below | ✔ |
| **3 — Interactive** | camera feel, depth peeling, hover latency, real-driver GL | a real display + GPU | ✖ local only |

### Packaging is covered by tier 1 (was a hole; closed 2026-08-04)

`tests/test_packaging_spec.py` and `tests/test_third_party_notices.py` are **tier-1**: they
exec `packaging/cellsmith.spec` with stub `Analysis`/`EXE`/`PYZ`/`COLLECT` and run the
notices generator over metadata only, so **nothing is frozen** — no Qt, no GL, no OCC,
about a second. They were promoted out of `scratchpad/` (`CS-139`) because the hole they
close is real: **`make test` was green on a tree whose `build.bat` could not reach
`COLLECT`** (that is exactly how `CS-138` shipped). The spec is executable Python with
three path-resolution bases, a `_WORKERS`-derived hiddenimports list, and an `exec` of
`src/main.py`, so a pure `src/` refactor — renaming a worker module, moving
`__version__.py` — can break the build with no other test noticing.

`test_third_party_notices.py` additionally acts as the **licence rot guard**: it fails if a
copyleft or non-OSI package re-enters the environment (`CS-140` — Intel MKL arrived once as
a transitive dependency of conda-forge's numpy and shipped 25 proprietary DLLs unnoticed).

What is still **not** covered by any test: that the *frozen* payload works. That is
`.github/scripts/verify-payload.sh`, run by both workflows after PyInstaller — see
[packaging.md](packaging.md).

### ⚠️ `scratchpad/run_all_tests.py` reports EXIT STATUS, not correctness

The sweep runs each `scratchpad/*_test.py` in its own process and calls exit 0 a PASS. Two
ways that misleads, both hit for real (**CS-150**):

- **A script that catches its own exception still exits 0.** `svd_dll_test.py` prints
  `svd EXC …` and returns 0, so its `PASS` says nothing about whether SVD worked. Do not
  cite a sweep PASS as evidence for a specific behaviour without reading the script.
- **A check that counts things must assert it counted anything.** A probe asserting "no
  `mkl_*` module is loaded" passed while enumerating **zero** modules (a `ctypes` `restype`
  bug truncated the process handle). Any "I found none of X" evidence needs a companion
  assertion that the search found *something*.

`tests/` does not have this problem — pytest reports per-assertion. Prefer promoting a probe
into `tests/` when its result is load-bearing.

## ⭐ Linux system packages CI must install

Verified by running in `python:3.12-slim`, not inferred. **pip packages alone are not
enough** — VTK and Qt both need system libraries that no wheel provides.

```bash
# Offscreen VTK/pyvista rendering. libegl1 is the important one.
apt-get install -y libegl1 libgl1 libglx-mesa0 libgl1-mesa-dri

# Qt (PySide6) even under QT_QPA_PLATFORM=offscreen
apt-get install -y libglib2.0-0 libxkbcommon0 libxkbcommon-x11-0 libxrender1 \
                   libxext6 libfontconfig1 libdbus-1-3 \
                   libxcb-cursor0 libxcb-icccm4 libxcb-keysyms1 libxcb-shape0 libxcb-xkb1

# ONLY needed for full-window captures (a native Qt window requires a display)
apt-get install -y xvfb
```

### Why, and what breaks without it

VTK tries three render backends in order — **X11, then EGL, then OSMesa**. A slim image has
none, so it falls through all three and **segfaults** (exit 139). It does *not* raise, so a
test cannot catch it; the runner dies. Supplying any one backend fixes it.

| Configuration | Offscreen `pv.Plotter` | Full-window composite |
|---|---|---|
| bare slim image | ✖ **segfault** | ✖ |
| + Mesa driver only (`libgl1-mesa-dri`, `LIBGL_ALWAYS_SOFTWARE=1`) | ✖ **still segfault** | ✖ |
| **+ `libegl1`** (no display at all) | ✔ **works** | ✖ `qt.qpa.xcb: could not connect to display` |
| + `libosmesa6` | ✔ works | ✖ |
| **+ `xvfb-run`** | ✔ works | ✔ **works** (`platform: xcb`, GL captured) |

!!! warning "Two traps"

    1. **Mesa's GL *driver* is not a GL *backend*.** Installing `libgl1-mesa-dri` and
       setting `LIBGL_ALWAYS_SOFTWARE=1` still segfaults, because there is no display for
       X11 and no EGL/OSMesa library to fall back to. `libegl1` is what actually fixes it.
    2. **A missing library looks like a capability limit.** The first composite attempt
       failed with `ImportError: libglib-2.0.so.0` — trivially fixable, easily
       misread as "PySide6 can't run here". Check the loader error before concluding
       anything is impossible.

### CI invocation

```bash
# Tiers 1-2 (no display needed once libegl1 is present)
make test-ci

# If a test needs a native window (full-window capture), wrap it:
xvfb-run -a make test-ci
```

❓ Untested: Qt's `minimalegl` / `eglfs` platform plugins, which might provide a
native-capable platform with no X server, removing the Xvfb dependency entirely.

## Offscreen capture — what works where

Established by probe; see `../Scratch/ai-metaanalysis.md` §3.1 for the reasoning.

| Target | Method | Works under `offscreen`? |
|---|---|---|
| Widget / panel / dialog | `QWidget.grab()` | ✔ |
| 3D viewport content alone | `pv.Plotter(off_screen=True).screenshot()` | ✔ (needs `libegl1` on Linux) |
| **Full window** | native platform + composite paste | ✖ — needs a real or virtual display |

**Why full-window needs a real window:** `pyvistaqt.QtInteractor` derives from
`QVTKRenderWindowInteractor` → a plain `QWidget`, whose native handle VTK renders into
directly. That surface is foreign to Qt's composition, so `grab()` returns black for it —
and under `offscreen` the widget has no window at all (`winId()`→1, `IsWindow()`→False,
`GetDC()`→0), so VTK cannot even choose a pixel format and the process dies. A
`QOpenGLWidget` *is* captured correctly, which is why VTK's `QVTKOpenGLNativeWidget` is
the eventual structural fix.

## Fixtures

`tests/conftest.py` provides:

| Fixture | Gives |
|---|---|
| `qapp` | session-wide offscreen `QApplication`, **Fusion** style, dark palette, vendored fonts registered, pinned point size |
| `font_families` | families actually registered (skip a test when none) |
| `artifacts_dir` | stable `tests/_artifacts/` for images a human or agent will look at |

**Three things must be pinned for a capture to be comparable across machines: style,
palette, and font.** `src/gui/theme.py` and `src/gui/fonts.py` own those; the app itself
follows the OS color scheme, so captures must override it.

### Run outcome is recorded to disk

`pytest_sessionstart` / `pytest_sessionfinish` in the same file write
`tests/_artifacts/last-run.json` — passed / failed (assertions **plus** collection errors) /
skipped / xfailed / `duration_s` / `exit_status` / platform / `QT_QPA_PLATFORM`.

Why: `docs/derive_metrics.py` needs the suite result as its tier-4 metric but **deliberately
does not run the suite** — a metrics script with side effects cannot be safely re-run to verify
a number it already reported. It reads this file, and reports `source: null` when absent rather
than implying a green run.

- **Can never fail the suite** — the writer is entirely inside one `except Exception: pass`.
- **Gitignored** (`tests/_artifacts/`), so it records *one run*, not a re-derivable fact — hence
  `drag.tests` is **perishable** in the metrics snapshot. `duration_s` is wall-clock; do not
  compare across hosts.
