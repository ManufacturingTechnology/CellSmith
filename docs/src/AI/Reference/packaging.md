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
| Packaging | **identical to release** — both `build-*` jobs are the same composite action (see below) | same composite action, **plus** collect + upload |

### ⭐ The PR gate runs the RELEASE build — one composite action per OS (ADR-0009)

`.github/actions/build-{linux,windows}/action.yml` hold the entire build — free
space, system libs, conda env, `make build` / `build.bat ci`, `verify-payload.sh`,
and an assertion that the artifacts exist. **Both workflows `uses:` them**; only
publishing (collect, upload, tag) is release-specific.

This reverses an earlier trade — the gate used to run PyInstaller only, "~15 min
shorter" — because the two costliest defects of the 2026-08-04 release push were
*both* in the half the gate skipped: `make_deb.sh`'s SIGPIPE (only reproducible on a
real payload) and a version guard that had never worked (in two inlined copies).
**A step the gate does not run is a step nobody has tested**, and duplicated steps
drift. `tests/test_ci_release_parity.py` enforces it: same composite action in both
workflows, no inline `make build` / `build.bat` / `PyInstaller` / `verify-payload.sh`
in either, and nothing in release's build job that the gate does not also run.

Also early-surfacing, same push: `version-check` now validates that `__version__`
parses and is semver on **every** PR (the branch-match half still only applies to
`release/X.Y` bases) — a malformed version breaks `make build`, the `.deb` version
and the tag, none of which is release-branch-specific.

⚠️ **Cost:** the gate is ~15 min longer per PR. If that becomes intolerable, the
escape hatch is a `paths`-filter or a label-gated job — **not** a cheaper build,
which is the thing that failed.

!!! danger "⭐ NEVER call `exit` from a step whose shell is `bash -el {0}` — `~/.bash_logout` overwrites the exit status"

    **This is the cause of the `build-linux` failure of 2026-08-04**, where
    `Assert both Linux artifacts were produced` printed both of its `ok` lines,
    computed `rc=0`, ran `exit 0`, and the runner still reported *"Process
    completed with exit code 1"*. It was recorded here as **root cause unknown**;
    it is now proven, and it is not specific to that step.

    [bash(1), INVOCATION](https://www.gnu.org/software/bash/manual/html_node/Bash-Startup-Files.html)
    (verified locally against `/usr/share/man/man1/bash.1.gz`, line 347):

    > When an interactive login shell exits, **or a non-interactive login shell
    > executes the `exit` builtin command**, bash reads and executes commands from
    > the file `~/.bash_logout`, if it exists.

    `bash -el {0}` is a non-interactive **login** shell — that `-l` is what
    activates `CellSmithEnv`. So any step that calls `exit` sources
    `~/.bash_logout`, and **the status of that file's last command becomes the
    step's status**. On an Ubuntu runner `/home/runner/.bash_logout` is the
    `/etc/skel` default, ending in

    ```bash
    if [ "$SHLVL" = 1 ]; then
        [ -x /usr/bin/clear_console ] && /usr/bin/clear_console -q
    fi
    ```

    `SHLVL` is `1` (the runner spawns bash from a non-shell parent, so bash sets it
    itself) and no terminal is attached, so `clear_console -q` exits 1 — and so does
    the step, however it ended.

    **Probe** (2026-08-13, Debian/WSL, bash 5.2.37, `SHLVL` unset in the parent,
    skel `~/.bash_logout` in `HOME`):

    | Step shell | Script | Step exit |
    |---|---|---|
    | `bash -el {0}` | `exit 0` | **1** ← the CI failure, reproduced |
    | `bash -el {0}` | falls off the end | 0 ← why every *other* `-el` step passes |
    | `bash --noprofile --norc -eo pipefail {0}` | `exit 0` | 0 ← the fix |
    | `bash -el {0}` | `exit 1` | 1 (a real failure still fails) |
    | `bash -el {0}`, **no** `~/.bash_logout` | `exit 0` | 0 ← why it "could not be reproduced" |

    The two variables that decide it — the runner's `~/.bash_logout` and `SHLVL` —
    are both **outside the script**, which is why reading the script harder was
    never going to find it.

    **The rule:** a login-shell step must not call `exit`. Let the script fall off
    its end (the shell's status is then its last command's, and `~/.bash_logout` is
    never read), move the deciding logic into a called script (`bash foo.sh` is a
    child, non-login shell — its `exit` is unaffected, which is why
    `verify-payload.sh` was never hit by this), or drop the login shell. Both
    `Assert … artifacts were produced` steps take the last option: globbing and
    stat'ing files needs no conda env, so they are pinned to plain `shell: bash`
    (= `bash --noprofile --norc -eo pipefail {0}`).

    **Enforced by `tests/test_workflow_shell_hygiene.py`** across both workflows and
    both composite actions, including the job-level `defaults.run.shell` inheritance
    that makes the trap easy to walk into. Its negative control runs the detector
    against the pre-fix `action.yml` at `7d95a40` and requires it to flag exactly
    that step.

    The steps still print `verdict: rc=N` before exiting. That is now belt-and-braces
    rather than the only diagnostic: `verdict: rc=0` beside a red step would mean the
    wrapper, not the script.

    ⚠️ Their glob loop writes `if [ -e "$f" ]; then hit="$f"; fi`, never
    `[ -e "$f" ] && hit="$f"` — under `-e` the no-match path would abort the script
    instead of reporting the missing artifact. Same trap as the `.deb` self-checks.
    Behaviour re-verified 2026-08-13 by extracting both steps' scripts from the YAML
    and running them in WSL under GitHub's exact `shell: bash` against a fake `dist/`
    (including the `~` in the `.deb` name): both-present → 0, either missing → 1,
    nothing built → 1, for both actions.

**CellSmith-specific adaptations** (none of these apply to MTConnectExplorer, which is a
pip-venv onefile build):

- **conda, not `setup-python`** — `pythonocc-core` has no pip wheel.
  `conda-incubator/setup-miniconda@v4` with `environment-file: packaging/environment.yml`.
  Miniconda is preinstalled on both runner images, but the action is what wires the shell
  hook. Every job uses `shell: bash -el {0}` so the env is active.

    **Pinned at `@v4` (bumped from `@v3` 2026-08-04).** `v3` targets Node 20, which GitHub
    has [deprecated](https://github.blog/changelog/2025-09-19-deprecation-of-node-20-on-github-actions-runners/)
    and now force-runs on Node 24, annotating every job.
    [`v4.0.0`](https://github.com/conda-incubator/setup-miniconda/releases/tag/v4.0.0)'s only
    breaking changes are the Node 24 runtime and an ESM build — **no input was renamed or
    removed** — so the bump is mechanical. Two inputs were corrected at the same time:

    | Was | Now | Why |
    |---|---|---|
    | `auto-activate-base: false` | `auto-activate: false` | `auto-activate-base` is deprecated in favour of `auto-activate` (its default is now the sentinel `legacy-placeholder`). Each job also sets `activate-environment: CellSmithEnv`, so no `activate-environment: base` companion is needed. |
    | *(absent)* | `conda-remove-defaults: true` | Otherwise the action adds the `defaults` channel implicitly and annotates. `packaging/environment.yml` lists **`conda-forge` only**, deliberately — a silent `defaults` channel is exactly how a differently-licensed or differently-built package (the MKL story, L4/R5) sneaks back in. The action will default this to `true` itself eventually; setting it explicitly makes the intent readable. |
- ⭐ **Version reading is a SHARED SCRIPT, `.github/scripts/read-version.sh`** — never
  inline a parse of `src/__version__.py` in a workflow. Both workflows used to inline

    ```bash
    version=$(grep -oP '"\K[^"]+' src/__version__.py)
    ```

    which is **unanchored**: `src/__version__.py` opens with a module docstring, so the
    third quote of its triple-quote opener starts a match and the docstring's first line
    comes out *ahead of* the version. The guard therefore never worked, and the first PR
    into a `release/X.Y` branch died on it:

    ```text
    Error: __version__ 'Single source of truth for the application version.
    0.1.0-alpha.1' is not valid semver (expected MAJOR.MINOR.PATCH[-PRERELEASE])
    ```

    Two copies, both wrong the same way — which is the argument for one reader. It reads,
    semver-validates, and hard-errors on **zero or more than one** assignment (`exec`-based
    readers keep the *last*, a text parse takes the *first*, so two assignments mean the
    git tag and the payload could disagree). Diagnostics go to stderr so `$(...)` stays
    clean. The four `exec`-and-print readers — `build.bat`, `makefile`,
    `packaging/debian/make_deb.sh`, `cellsmith.spec` — never had the bug.

    ⚠️ **It uses POSIX `sed`, not `grep -P`, deliberately.** PCRE grep is not portable:
    Git Bash on Windows refuses it outright — `grep: -P supports only unibyte and UTF-8
    locales` — so a PCRE reader is untestable on a dev machine even though it works on the
    runner. `tests/test_version_source.py` pins all of this (see
    [testing.md](testing.md)).
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
  - The script ends with **10 self-checks** (archive readable, launcher, symlink, desktop
    entry, icon, copyright, notices, Qt plugins present, **no GPL readline**, no bare `-`
    in the version) and runs `lintian` informationally when available. The readline check
    is there because the payload verifier only ever sees `dist/CellSmith` — the `.deb` is
    a separate distribution and needs its own assertion.
  - ⛔ **TWO TRAPS in that self-check block; both fired only on a REAL payload.**
    1. **SIGPIPE.** The checks were `printf '%s\n' "$contents" | grep -q PAT`. `grep -q`
       exits at the first match and closes the pipe; the real listing is ~200 kB, well
       past the 64 kB pipe buffer, so `printf` was still writing and died —
       `printf: write error: Broken pipe`, and `make build` failed *after* successfully
       building the `.deb`. ⭐ Note the shape: **it fires only when the check SUCCEEDS**
       (an early match is what closes the pipe) and only when the listing is big enough
       to block — which is exactly why it passed against a small synthetic payload in the
       WSL sandbox and failed on the 2111-file build. Fix: `dpkg-deb --contents` to a
       file once, then `grep -q` the FILE. No pipe, no SIGPIPE.
    2. **`set -e` made `check()` unreachable.** With `-e`, a bare `cmd; check $?` aborts
       the moment `cmd` fails, so `fail`, the `FAIL` lines and the "self-checks failed"
       summary were all dead code — any failing check surfaced as a bare
       `make: *** Error 1` with no indication of *which*. Every check is now written so
       its own failure is TESTED (`if/then/else` via the `has()` helper). Re-verified in
       WSL against a synthetic payload padded to 2200 files: the old form exits **141**
       (SIGPIPE) before printing anything; the new form prints `FAIL <name>`, keeps
       running the remaining checks, and exits 1 with the summary.
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
  - **`no GPL readline in the payload`** (added 2026-08-04) — asserts zero
    `readline*.so*` / `readline*.pyd` / `libreadline*` / `libhistory*` under
    `_internal/`. This is the enforcement half of a **licensing** exclusion, not a size
    one: GNU Readline is `GPL-3.0-only` with no linking exception, it exists in the conda
    **Linux** env (`python` links it) and never appeared on Windows, and the generated
    notices *claim* it is absent. A claim in a legal notice needs a check behind it.
    See [licensing.md](licensing.md).
    - ⭐ **`excludes=` DOES NOT KEEP A SHARED LIBRARY OUT — two Linux runs proved it,
      by two different routes.** `readline` was in the spec's `excludes=` for both.
      `excludes=` filters the **module graph**; the payload is assembled from
      `a.binaries` + `a.datas`, and readline arrived in each:

        | Run | Hits | Route |
        |---|---|---|
        | 1 | 3 — incl. `readline.cpython-312-…so` | **`a.binaries`.** Binary dependency analysis collected the `readline` **extension module**, which is what drags `libreadline` in via **`DT_NEEDED`**. (On a stock Debian layout it is the *only* consumer of `libreadline` — probed with `readelf -d` over `/usr/lib/x86_64-linux-gnu` + `lib-dynload`.) |
        | 2 | 4 — `lib{readline,history}.so{,.8}`, **zero** reverse deps | **`a.datas`.** Nothing in the payload NEEDs them, so they were *swept* out of the conda env's shared `lib/`, not linked. Origin: PyInstaller's OWN numpy hook — `PyInstaller/hooks/hook-numpy.py` does `if numpy_installer == 'conda': datas += conda_support.collect_dynamic_libs("numpy", dependencies=True)`; `dependencies=True` walks numpy's conda dependency **graph** (numpy → python → readline) and `conda.collect_dynamic_libs` globs `*.so`/`*.so.*` out of `lib_dir`. |

        ⭐ **What run 3 corrected.** With the filter printing every entry it drops, the
        build log showed the two lists split the files by KIND, not by origin:

        ```text
        dropped from a.binaries: ('libhistory.so.8.3',  '…/envs/CellSmithEnv/lib/libhistory.so.8.3',  'BINARY')
        dropped from a.binaries: ('libreadline.so.8.3', '…/envs/CellSmithEnv/lib/libreadline.so.8.3', 'BINARY')
        dropped from a.datas:    ('libreadline.so.8',   'libreadline.so.8.3',  'SYMLINK')
        dropped from a.datas:    ('libhistory.so.8',    'libhistory.so.8.3',   'SYMLINK')
        dropped from a.datas:    ('libhistory.so',      'libhistory.so.8.3',   'SYMLINK')
        dropped from a.datas:    ('libreadline.so',     'libreadline.so.8.3',  'SYMLINK')
        ```

        The **real files** end up in `a.binaries` as `BINARY` — the hook files them under
        `datas`, then PyInstaller's *"Performing binary vs. data reclassification"* pass
        (visible in the same log) moves anything that is actually a shared library into
        `binaries`. The **symlinks** stay in `a.datas` with typecode `SYMLINK`, where
        `src` is the link target rather than a path. So filtering both lists was
        necessary for a reason neither run alone revealed, and dest-basename matching is
        the right predicate because it is the one field both kinds share.

      So the spec filters **both lists** (dest basename starting `readline` /
      `libreadline` / `libhistory`), printing the full `(dest, src, typecode)` of every
      entry it drops — the *source path* is what names the contributing package. Since
      `COLLECT` places files from exactly `EXE` + `a.binaries` + `a.datas`, filtering
      both is **exhaustive**. Filtering the TOC lists is PyInstaller's documented
      mechanism for undoing analysis
      ([spec-file docs](https://pyinstaller.org/en/stable/spec-files.html)); `COLLECT`
      accepts any "TOC-like iterable", so a plain list is fine (verified against
      `PyInstaller/building/api.py:1122`, 6.21.0).
    - 💡 **Generalizable:** on a **conda** build, `hook-numpy` alone rakes the entire
      env `lib/` for everything in numpy's dependency closure and files it as *data*.
      Expect other env libraries in `_internal/` that nothing links, and do not assume
      a payload file arrived because something imported or linked it.
    - The check **names the offending files** and, when `readelf` is available, the
      collected libraries whose `DT_NEEDED` pulled them in — a bare count ("3 hits")
      is not actionable, and it cost a whole CI round-trip to learn the filenames.
      An **empty** needers list is itself load-bearing evidence (it is what identified
      route 2), so the script says explicitly when `readelf` is missing rather than
      letting "didn't look" read as "nothing needs it". It also warns in the
      **opposite** direction: payload clean but some bundled `.so` still `NEEDED`
      readline ⇒ that library will fail to `dlopen`, i.e. the removal broke a real
      dependency. All branches probed against synthetic payloads built from **real ELF
      files** under WSL, including one shaped exactly like run 2.
    - `libhistory` is in the patterns because it ships from the **same GPL-3.0-only
      readline source package**; the notices name it too.
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

