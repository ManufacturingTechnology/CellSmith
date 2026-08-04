# Packaging (PyInstaller onedir)

The Windows + Linux PyInstaller onedir build: `build.bat` / `make build`, the `--worker` re-launch dispatch, the **spec's three path-resolution bases** (why every spec path is absolute), the custom OCC/pxr/trimesh PyInstaller hooks + runtime hooks, the generated third-party notices, the robust archive step, the Inno Setup installer + app icon, the **Debian package** (`packaging/debian/`, incl. the semver→Debian `~` mapping), the **payload verifier**, the **GitHub Actions CI/release workflows**, Linux system-lib requirements, and headless verification. Read when touching the build, spec, hooks, installer, `.deb`, or CI. Verify against `packaging/`, `.github/`, and `src/`; may lag.

---

## GitHub Actions — CI + Release

Ported from the sibling `MTConnectExplorer` repo; the release *procedure* (branch flow,
version-driven trigger, rulesets) is documented for humans in the repo-root
`CONTRIBUTING.md`. This section records only what is CellSmith-specific.

| | `ci.yml` (PR gate) | `release.yml` |
|---|---|---|
| Trigger | `pull_request` → `main`, `dev/*`, `release/*` | push to `release/*` touching `src/__version__.py`; plus `workflow_dispatch` |
| Jobs | `version-check`, `test-linux`, `test-windows`, `build-linux`, `build-windows` | `version`, `build-linux`, `build-windows`, `release` |
| Packaging | **none** — PyInstaller only, then `verify-payload.sh`. Skipping the zip/installer/`.deb` keeps the gate ~15 min shorter. | full: zip + installer (Windows), tar.gz + `.deb` (Linux) |

**CellSmith-specific adaptations** (none of these apply to MTConnectExplorer, which is a
pip-venv onefile build):

- **conda, not `setup-python`** — `pythonocc-core` has no pip wheel.
  `conda-incubator/setup-miniconda@v3` with `environment-file: packaging/environment.yml`.
  Miniconda is preinstalled on both runner images, but the action is what wires the shell
  hook. Every job uses `shell: bash -el {0}` so the env is active.
- **`build.bat`/`dev.bat` call bare `conda`**, which `setup-miniconda` only wires into the
  bash/pwsh profiles — so the Windows release job adds conda's dir to `$GITHUB_PATH`
  before the `shell: cmd` build step, or `dev.bat`'s `where conda` check fails.
- **Inno Setup 6 is PREINSTALLED on `windows-latest`** (6.7.1 per the runner-image
  manifest) — no install step. The manifest does **not** state its path, so nothing is
  allowed to depend on one. Two layers:
    1. `build.bat` honours an **already-set `%ISCC%`** in preference to its own probing
       (and now also probes `%ProgramFiles%\Inno Setup 6`).
    2. `.github/scripts/find-iscc.ps1` locates ISCC — PATH → both Program Files →
       `%LOCALAPPDATA%\Programs` → the three `Inno Setup 6_is1` uninstall registry keys →
       a depth-2 scan of Program Files — exports it to `$GITHUB_ENV`, and **fails the job
       with the install command** if absent. Runs before the build in `release.yml`.
    3. The release job still fails if no `*-setup.exe` appears, because `build.bat` only
       **warns** when ISCC is missing. Belt and braces: layer 2 fails early with a
       specific message, layer 3 catches anything else.
- **Linux system packages are installed BEFORE the build**, for the reason in the Linux
  section below (a failed PySide6 import silently yields zero Qt plugins).
- **Disk pressure is real**: conda env + `build/` + `dist/` + two archives on a runner with
  ~20–29 GB free. The release job removes the preinstalled Android/dotnet/GHC toolchains,
  prints `df -h` before and after, and deletes `dist/CellSmith` + `build/` before uploading.
- **No notices step** — the spec generates `THIRD-PARTY-NOTICES.md` itself.
- Artifacts upload with `compression-level: 0` (already-compressed archives).

**Release assets — exactly four, asserted by the `release` job:**

| Asset | From |
|---|---|
| `CellSmith-v{V}-setup.exe` | `build.bat` → ISCC |
| `CellSmith-v{V}-win64.zip` | `build.bat` → `make_zip.ps1` |
| `CellSmith-v{V}-linux-x86_64.tar.gz` | `make build` |
| `cellsmith_{debver}_amd64.deb` | `make deb` (note `~`, not `-`, for a prerelease) |

**GitHub's limits, verified:** each asset must be **under 2 GiB**, up to **1000 assets** per
release, and **no cap on the release total or bandwidth**
([docs](https://docs.github.com/en/repositories/releasing-projects-on-github/about-releases)).
Largest asset today is the ~494 MB zip, so there is ~4× headroom; the `release` job asserts
the limit anyway so future growth fails there rather than mid-upload.

---

---

## Packaging — PyInstaller ONEDIR distributable (Windows + Linux BUILT + worker-verified; **Windows frozen GUI LAUNCH-VERIFIED 2026-08-04** — see CS-148. Still unverified: the GUI from an *installed* `setup.exe`, and the Linux frozen GUI)
Modeled on `../MTConnectExplorer` (shared spec, local scripts, CI later) with one
deliberate deviation: **onedir, NOT onefile** — the app re-launches its own exe as
worker subprocesses; onefile would re-extract the ~1.4 GB payload per launch.
- **Build**: `build.bat` (Windows; arg `ci` suppresses the pause) / `make build`
  (Linux — run ON Linux, e.g. WSL2; PyInstaller can't cross-compile). Output
  `dist/CellSmith/` (launcher + `_internal/`, **972 MB / 1957 files**, `du -sh`-measured
  2026-08-04 after the MKL removal — the older "~1.4 GB" figures elsewhere on this page
  predate that and were never re-measured ❓) and the archive
  `dist/CellSmith-v<ver>-win64.zip` / `-linux-x86_64.tar.gz`. Version single-source
  = `src/__version__.py` (the spec `exec`s it — never imports the package; also
  feeds `--version` and archive names). PyInstaller **>=6.10** pinned in
  `packaging/environment.yml` pip (v6's parent-dir-preserving DLL collection is REQUIRED for
  pxr); build scripts also `pip install` it because dev.bat only CREATES a missing
  env, never updates an existing one. UPX off (huge native payload; AV risk).
  **`console=False`** (windowed release — NO console window on launch). A windowed
  frozen build sets `sys.stdout`/`sys.stderr` to `None` when Explorer-launched, so
  `src.main._ensure_std_streams()` (called FIRST in `main()`, before worker
  dispatch/logging) redirects ONLY the None streams to `os.devnull` — worker
  subprocesses keep their PIPED stdio (QProcess redirects → non-None → left alone),
  so worker↔GUI progress over stdout still flows, and native crashes / uncaught
  exceptions are still captured to `cellsmith_crash.log`; worker failures surface
  in-GUI via `_error_box`. (Flip back to `console=True` only to debug worker
  stderr live.)
- **Archive step is ROBUST + FAIL-LOUD** (`packaging/make_zip.ps1`, called by
  `build.bat`): the old `Compress-Archive` one-liner raised a NON-terminating error
  when antivirus still held a lock on PyInstaller's fresh output
  (`_internal\base_library.zip` "used by another process") — so it exited 0 and
  `build.bat` printed "Built …zip" with NO valid archive. `make_zip.ps1` uses one
  `[System.IO.Compression.ZipFile]::CreateFromDirectory(src, dst, Optimal,
  includeBaseDirectory=$true)` call (the `$true` keeps the top-level `CellSmith\`
  folder in the zip, matching the old `-Path dist\CellSmith` layout), RETRIES the
  transient lock (6× / 3 s), and **`exit 1` on real failure** so `build.bat`'s
  `IF ERRORLEVEL 1 goto :fail` actually fires. Persistent lock ⇒ exclude `dist\`
  from real-time AV or close a running `CellSmith.exe`.
- **`--worker` dispatch** (frozen-safe worker launches): `src.main.main` pre-scans
  argv for `--worker <name>` BEFORE argparse/any Qt import and routes to the
  worker's `main(argv)` via the `_WORKERS` table (`cache_build`, `edges_build`,
  `assets_build`, `restructure_build`, `export_step`, `export_usd`,
  `export_obj`, `export_composed` — all expose a uniform
  `main(argv: list[str]) -> int`; the spec derives hiddenimports from
  `_WORKERS.values()`, so a new worker needs NO spec edit).
  `main_window._setup_worker(proc, name, args)` builds every QProcess invocation:
  frozen → `CellSmith.exe --worker …` (env/rthook vars inherit); dev →
  `python -m src.main --worker …` + PYTHONPATH/workdir = repo root. NEVER launch
  `-m src.x.y` directly from the GUI anymore. Entry script for the freeze is
  `src/__entrypoint__.py` (src.main uses relative imports, so it can't be the entry).
- ⭐ **EVERY path in the spec must be ABSOLUTE** — build them with the spec's own
  `R("src", "…")` helper (`ROOT = SPECPATH/..`), never a bare relative string. The
  spec does NOT live at the repo root, and PyInstaller resolves relative paths
  against **three different bases**, so no single relative convention can work:

  | Spec field | Anchored to | Source |
  |---|---|---|
  | `Analysis(scripts=…)` | the **spec's dir** | `building/build_main.py` — *"If path is relative, it is relative to the location of .spec file"* |
  | `Analysis(datas=…, binaries=…)` | the **spec's dir** | `format_binaries_and_datas(…, workingdir=spec_dir)` |
  | `EXE(icon=…, version=…)` | the **spec's dir** | `building/api.py::EXE._makeabs` |
  | `hookspath`, `runtime_hooks`, `pathex` | the **CWD** (never spec-anchored) | `build_main.py` stores them verbatim (only `expanduser`) |
  | plain `open()` inside the spec | the **CWD** | ordinary Python |

  `--distpath`/`--workpath` are CWD-based CLI defaults, so `dist/` + `build/`
  land at the repo root either way. The symptom of getting this wrong is a
  doubled path segment: moving the spec into `packaging/` while leaving
  `["src/__entrypoint__.py"]` relative failed with `ERROR: script
  '…\AMT-CellSmith\packaging\src\__entrypoint__.py' not found`, and would then have
  mis-anchored `datas`, `EXE(icon=)`, and the generated `version_info.txt` the same
  way. Guarded by `tests/test_packaging_spec.py` — it exec's the spec with
  stub PyInstaller classes from three different working directories and asserts
  every collected path is absolute and exists.
  ([spec-file docs](https://pyinstaller.org/en/stable/spec-files.html))
- ⭐ **Third-party notices are GENERATED, and generated FROM THE SPEC.**
  `packaging/gen_third_party_notices.py` reads the licenses out of the live
  environment (`importlib.metadata` for wheels + `<env>/conda-meta/*.json` for conda
  packages, which is the only source for OCCT/pythonocc/freetype/libiconv) and writes
  `build/THIRD-PARTY-NOTICES.md`; the spec adds it plus `LICENSE.TXT` to `datas` at the
  payload root. **The spec is the invocation point on purpose** — `build.bat` and
  `make build` both run the same spec, so Windows and Linux cannot diverge and neither
  script can forget it. Loaded **by path via `importlib`**, never `import packaging.…`
  (that collides with the pip `packaging` module — same trap as `make_icon.py`).
  Verbatim texts that conda does **not** extract into the prefix live in
  `packaging/licenses/` (`LGPL-2.1`, `LGPL-3.0`, `GPL-3.0`, `FTL`, `FreeImage-FIPL`,
  `OCCT-LGPL-EXCEPTION`) and are embedded into the document. The generator is
  **fail-soft**: it never breaks a build, but unresolved items become `NOTICE-WARN:`
  lines on stderr **and** a *Gaps* section inside the shipped document, so an
  incomplete notice file is visibly incomplete. It also scans for copyleft/non-OSI
  licenses re-entering the environment. Obligations + rationale:
  [licensing.md](licensing.md). Guarded by `tests/test_third_party_notices.py`.
- **Spec + custom hooks** (`packaging/cellsmith.spec`, `packaging/hooks/`) — hooks-contrib has
  NO hook for `OCC` or `pxr`; ours carry the whole risk:
  - `hook-OCC.py`: `collect_submodules('OCC.Core')` (312 .pyd) + explicit
    `TK*.dll`/`libTK*.so*` glob (51 on win) + OCCT resource dirs →
    `_internal/opencascade/resources/`. `rthooks/pyi_rth_occ.py` sets `CASROOT` +
    the `CSF_*` set: **BinXCAF SaveAs/Open (our `.xbf` cache) HARD-FAILS without
    `CSF_PluginDefaults`/`CSF_StandardDefaults` → StdResource** ("Plugin: could not
    find resource file"); plain STEP translation would only silently fall back to
    compiled-in defaults (the dev conda env sets NO `CSF_*` at all — that's why dev
    never needed them). `CSF_UnitsLexicon`/`CSF_UnitsDefinition` point at FILES
    (`Lexi_Expr.dat`/`Units.dat`), the rest at dirs.
  - `hook-pxr.py`: `collect_submodules/data_files/dynamic_libs('pxr')` preserve the
    usd-core wheel layout — the plugin path `../pxr/pluginfo` is **BAKED into
    `usd_ms.dll` relative to the dir containing it**, so usd_ms + tbb must stay at
    `_internal/pxr/` (relocate them and every Sdf/Usd call dies "Failed to find
    plugin"). `rthooks/pyi_rth_pxr.py` adds `PXR_PLUGINPATH_NAME` belt-and-braces
    (Plug dedupes) + `PXR_USD_WINDOWS_DLL_PATH`.
  - **Worker modules MUST be hiddenimports** — they're reached only via
    `importlib.import_module` (invisible to static analysis). The spec `exec`s
    `src/main.py` (under a foreign `__name__`) and feeds `_WORKERS.values()` in.
    Without this the first build had NO workers and NO pxr at all (only
    `usd_cli` reaches pxr). VTK hiddenimports: `vtkmodules.all`,
    `vtkmodules.qt.QVTKRenderWindowInteractor` (pyvistaqt imports it dynamically),
    `vtkmodules.util.data_model`/`execution_model` (VTK>=9.4 lazy). Excludes
    `PyQt5`/`PyQt6` so qtpy can't drag a second Qt binding in.
- **Verified headlessly from `dist/`** (no conda env, no PYTHONPATH, neutral cwd,
  scratchpad fixtures): `--version`, unknown-worker rejection, `edges_build`,
  STEP/USD/OBJ exports (USD proves the pxr plugin registry), `cache_build` fresh
  STEP parse **+ `.xbf` write** (the CSF hard-fail case), `restructure_build` bake.
  GUI/viewport can't be tested here (no GPU) — user live-tests. **Done for Windows onedir
  on 2026-08-04: `dist/CellSmith/CellSmith.exe` launches (CS-148).**
- **Windows installer** (`dist/CellSmith-v<ver>-setup.exe`, VERIFIED: silent
  per-user install → exe + worker dispatch run → upgrade-over-existing → clean
  uninstall): `packaging/cellsmith.iss` (Inno Setup 6) — **per-user by
  default, NO admin/UAC** (`PrivilegesRequired=lowest` →
  `{localappdata}\Programs\CellSmith`, HKCU uninstall key) with an
  install-time choice to elevate for all-users
  (`PrivilegesRequiredOverridesAllowed=dialog`); Start-menu shortcut always,
  desktop icon behind an UNCHECKED task; LZMA2 (1.4 GB → ~259 MB, smaller
  than the zip); uninstall touches only `{app}` + shortcuts (user data lives
  beside the STEP files). Built by `build.bat` AFTER the zip when ISCC is
  found (`where iscc`, `%LOCALAPPDATA%\Programs\Inno Setup 6`, Program Files
  x86) — SKIPPED with a warning otherwise (`winget install
  JRSoftware.InnoSetup`, itself per-user). Version injected via
  `/DAppVersion`; AppId GUID fixed in the .iss (drives upgrade-in-place).
  Vendored UI fonts `src/resources/fonts/` (IBM Plex Sans + JetBrains Mono, plus their
  OFL notices) are bundled via the spec's `datas` as `resources/fonts`;
  `src/gui/fonts.py::font_dir()` resolves frozen (`sys._MEIPASS/resources/fonts`) vs
  dev. **Do not modify the .ttf files** - OFL's Reserved Font Name clause would then
  require renaming them. Missing fonts degrade to the system font, never a crash.
  App icon `packaging/cellsmith.ico` — GENERATED ONCE by
  `packaging/make_icon.py` (QPainter, multi-res PNG-in-ICO: a HAMMER hovering
  offset over an industrial articulated arm — orange joints, gray hammer, on a
  dark rounded badge — the "smith rigs a robot" premise) and CHECKED IN; wired
  into the exe (`packaging/cellsmith.spec` `EXE(icon=…)`, Windows only) and the
  installer/shortcuts. Re-run `make_icon.py` (via `importlib` by PATH, NOT
  `import packaging.…` — that name collides with the pip `packaging` module)
  to regenerate, then rebuild so the exe + installer pick it up.
  **`EXE(icon=…)` only sets the FILE icon (Explorer). The running WINDOW's
  title-bar + taskbar icon is separate** — `src/main.py` calls
  `QApplication.setWindowIcon(QIcon(_icon_path()))` (`_icon_path`: frozen →
  `sys._MEIPASS/cellsmith.ico` bundled via the spec's `datas`; dev →
  `packaging/cellsmith.ico`) AND, on Windows, sets a distinct
  `AppUserModelID` (`AMT.CellSmith`) BEFORE the first window shows so the
  taskbar uses our icon instead of grouping under `python.exe` (dev) / the
  host. Without both, the window/taskbar show Qt's default even when the exe
  file icon is correct.
- ⭐ **Debian package** (`make deb`, or `make build` which chains it after the tarball):
  `packaging/debian/make_deb.sh` stages an already-built `dist/CellSmith` payload and
  runs `fakeroot dpkg-deb --build -Zxz`. Deliberately **not** debhelper — there is no
  source package to build, only a layout to stage. Templates + the icon converter live
  in `packaging/debian/` (`control.in`, `copyright.in`, `cellsmith.desktop`,
  `ico_to_png.py`).
  - **Layout:** payload verbatim at `/opt/cellsmith/` (FHS 3.0 §3.13 — add-on
    application packages; `/usr/lib` would imply distro-managed libs), `/usr/bin/cellsmith`
    symlink, `/usr/share/applications/cellsmith.desktop`,
    `/usr/share/icons/hicolor/256x256/apps/cellsmith.png`, and
    `/usr/share/doc/cellsmith/{copyright,THIRD-PARTY-NOTICES.md,changelog.gz}`. The symlink
    is safe because PyInstaller resolves `sys.executable` through `/proc/self/exe`, so
    `_setup_worker`'s re-launch hits the real binary.
  - ⭐ **SEMVER → DEBIAN VERSION: map `-` to `~`.** `0.1.0-alpha.1` as a Debian version
    parses `alpha.1` as the *debian revision*, which sorts **after** plain `0.1.0` — dpkg
    would rank the prerelease as NEWER than the release. `0.1.0~alpha.1` sorts before it
    ([Policy §5.6.12](https://www.debian.org/doc/debian-policy/ch-controlfields.html#version)).
    Proven with `dpkg --compare-versions`: `0.1.0~alpha.1 lt 0.1.0` **true**, and
    `0.1.0-alpha.1 gt 0.1.0` also **true** — i.e. the naive mapping really does invert.
  - **`Depends:`** is the verified runtime X11/GL set below, with `a | b` alternatives for
    the Debian 13 / Ubuntu 24.04 `t64` renames (`libglib2.0-0t64 | libglib2.0-0`);
    without the alternative the package refuses to install across the rename.
  - **Templating uses Python, not `sed`.** The `Depends` list contains `|` and the
    maintainer contains `<`/`>`/`@`, so every plausible sed delimiter appears in some
    value — the first version died with ``unknown option to `s'``.
  - The script ends with **9 self-checks** (archive readable, launcher, symlink, desktop
    entry, icon, copyright, notices, Qt plugins present, no bare `-` in the version) and
    runs `lintian` informationally when available. Verified end-to-end in a WSL Debian
    sandbox against a synthetic payload.
- ⭐ **Payload verifier** (`.github/scripts/verify-payload.sh <dir> <launcher>`), shared by
  both workflows so the PR gate and the shipped artifact are held to the same standard.
  Asserts the payload is *usable*, not merely present: Qt plugins collected, a Qt
  **platform** plugin present, OCCT libs + the `opencascade/resources` tree, pxr, VTK,
  `THIRD-PARTY-NOTICES.md` + `LICENSE.TXT` + the OFL notices, `--version` exits 0, and an
  unknown `--worker` is rejected listing **all 12 expected workers**.
  - ⚠️ **The Qt plugin path differs by platform** — `_internal/PySide6/plugins/…` on
    Windows, `_internal/PySide6/Qt/plugins/…` on Linux. An over-specific glob made the
    check fail against a known-good Windows build; match on the `plugins/` segment under
    `PySide6` instead.
- **Windows batch gotcha**: .bat files MUST be CRLF — an LF-only `build.bat`
  misparses under cmd.exe (adjacent lines merge; `call` targets "not recognized").
  Keep `call "%~dp0dev.bat"` absolute.
- **Linux** (`make build`, run ON Linux — WSL2 Debian with Miniforge at
  `~/miniforge3` works; `pythonocc-core=7.9.3=novtk_*` exists on conda-forge
  linux-64, same packaging/environment.yml): X11-family libs are NEVER bundled by
  PyInstaller (they must match the host), so the app needs SYSTEM packages on
  both the BUILD and TARGET machine — Debian set:
  `libxcb1 libxcb-cursor0 libxcb-icccm4 libxcb-image0 libxcb-keysyms1
  libxcb-randr0 libxcb-render-util0 libxcb-shape0 libxcb-xfixes0 libxcb-xkb1
  libxkbcommon-x11-0 libgl1 libegl1 libfontconfig1 libdbus-1-3 libxrender1
  libxext6 libsm6 libice6 libglib2.0-0t64 libwayland-client0 libwayland-cursor0
  libwayland-egl1 libx11-xcb1 libxcomposite1 libxdamage1 libxrandr2 libxtst6
  libxcursor1 libxi6 libxinerama1`.
  (OCC's BinXCAFDrivers links libxcb even in novtk builds; PySide6 needs glib.)
  **Linux Qt platform = xcb, forced by the app** (`src/main.py` setdefaults
  `QT_QPA_PLATFORM=xcb` on Linux): VTK's QVTKRenderWindowInteractor has NO
  Wayland support — under a Wayland/WSLg session Qt otherwise picks wayland and
  VTK's X11 ConfigureWindow dies with a fatal BadWindow. xcb runs via XWayland.
  **GOTCHA: install these BEFORE building** — PyInstaller's Qt hook IMPORTS
  PySide6 at build time to locate the Qt plugin dirs; if that import fails
  (missing system glib/xcb), the hook silently collects NO Qt plugins → a dist
  whose workers all pass but whose GUI dies with "no Qt platform plugin could
  be initialized" (`_internal/PySide6/Qt/` has `lib/` but no `plugins/` —
  that's the fingerprint). Note both OSes write `dist/CellSmith/` — building
  one clobbers the other's folder; the versioned archives are the artifacts.
  glibc baseline = the build distro (Debian 13/trixie currently).

