"""The PyInstaller spec must resolve every path it hands PyInstaller.

WHY THIS IS A REAL TEST AND NOT A SCRATCH PROBE (`CS-138`, `CS-139`)
    `packaging/cellsmith.spec` is executable Python that no other test touches, so
    `make test` stayed green while `build.bat` could not even reach `COLLECT`.
    The spec broke when it moved out of the repo root but kept repo-relative
    paths:

        ERROR: script 'C:\\...\\AMT-CellSmith\\packaging\\src\\__entrypoint__.py' not found

    PyInstaller resolves relative spec paths against THREE different bases:
      * `Analysis(scripts=)`, `Analysis(datas=/binaries=)`, `EXE(icon=/version=)`
        -> the SPEC's directory
      * `hookspath`, `runtime_hooks`, `pathex`, and plain `open()`
        -> the CWD
    so no single relative convention works. Every path must be absolute, built
    with the spec's own `R()` helper. Details: `Reference/packaging.md`.

The spec is exec'd with STUB PyInstaller classes, so nothing is frozen: no Qt, no
GL, no OCC, ~1 s. CI-eligible (no `local_only` marker).
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Dict, List, Tuple

import pytest

REPO = Path(__file__).resolve().parent.parent
SPEC = REPO / "packaging" / "cellsmith.spec"

#: Working directories the spec must tolerate. The `packaging/` case is the one
#: that used to double the path segment; the drive root proves CWD-independence.
CWDS = [
    pytest.param(REPO, id="repo-root"),
    pytest.param(REPO / "packaging", id="packaging-dir"),
    pytest.param(Path(os.path.abspath(os.sep)), id="foreign-cwd"),
]


class _Rec:
    """Stub that records the args a PyInstaller class was constructed with."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        self.args, self.kwargs = args, kwargs


def _run_spec(cwd: Path) -> Tuple[_Rec, _Rec]:
    """exec the spec from `cwd`; return its (Analysis, EXE) recorders."""
    captured: Dict[str, _Rec] = {}

    class Analysis(_Rec):
        def __init__(self, *a: Any, **kw: Any) -> None:
            super().__init__(*a, **kw)
            captured["analysis"] = self
            # PyInstaller reads these back after Analysis returns.
            self.pure = self.scripts = self.binaries = self.datas = []

    class EXE(_Rec):
        def __init__(self, *a: Any, **kw: Any) -> None:
            super().__init__(*a, **kw)
            captured["exe"] = self

    namespace: Dict[str, Any] = {
        "SPECPATH": str(SPEC.parent),
        "DISTPATH": str(REPO / "dist"),
        "workpath": str(REPO / "build"),
        "os": os,
        "Analysis": Analysis,
        "EXE": EXE,
        "PYZ": _Rec,
        "COLLECT": _Rec,
        "Tree": _Rec,
        "MERGE": _Rec,
        "BUNDLE": _Rec,
        "Splash": _Rec,
        "TOC": _Rec,
    }
    prev = os.getcwd()
    try:
        os.chdir(cwd)
        code = compile(SPEC.read_bytes(), str(SPEC), "exec")
        exec(code, namespace)
    finally:
        os.chdir(prev)
    return captured["analysis"], captured["exe"]


def _all_paths(analysis: _Rec, exe: _Rec) -> List[str]:
    scripts = analysis.args[0] if analysis.args else analysis.kwargs["scripts"]
    paths = list(scripts)
    paths += [src for src, _dest in analysis.kwargs.get("datas", ())]
    paths += list(analysis.kwargs.get("hookspath", ()))
    paths += list(analysis.kwargs.get("runtime_hooks", ()))
    paths += list(analysis.kwargs.get("pathex", ()))
    paths += [p for p in (exe.kwargs.get("icon"), exe.kwargs.get("version")) if p]
    return paths


def test_spec_file_exists() -> None:
    assert SPEC.is_file(), f"missing {SPEC}"


@pytest.fixture(scope="module")
def spec_from_root() -> Tuple[_Rec, _Rec]:
    return _run_spec(REPO)


@pytest.mark.parametrize("cwd", CWDS)
def test_every_path_is_absolute(cwd: Path) -> None:
    """A relative path here means one of the three bases will win by accident."""
    relative = [p for p in _all_paths(*_run_spec(cwd)) if not os.path.isabs(p)]
    assert not relative, f"relative paths in the spec: {relative}"


@pytest.mark.parametrize("cwd", CWDS)
def test_every_path_exists(cwd: Path) -> None:
    missing = [p for p in _all_paths(*_run_spec(cwd)) if not os.path.exists(p)]
    assert not missing, f"spec references paths that do not exist: {missing}"


@pytest.mark.parametrize("cwd", CWDS)
def test_no_doubled_spec_dir_segment(cwd: Path) -> None:
    """`packaging/src/...` or `packaging/packaging/...` is the CS-138 fingerprint."""
    sep = os.sep
    bad = [p for p in _all_paths(*_run_spec(cwd))
           if f"packaging{sep}src" in p or f"packaging{sep}packaging" in p]
    assert not bad, f"spec-dir-doubled paths: {bad}"


def test_paths_stay_inside_the_repo(spec_from_root: Tuple[_Rec, _Rec]) -> None:
    outside = [p for p in _all_paths(*spec_from_root)
               if os.path.commonpath([os.path.abspath(p), str(REPO)]) != str(REPO)]
    assert not outside, f"spec reaches outside the repo: {outside}"


def test_entry_script_is_the_shim(spec_from_root: Tuple[_Rec, _Rec]) -> None:
    """`src.main` uses relative imports, so the entry must be the shim."""
    analysis, _exe = spec_from_root
    scripts = analysis.args[0] if analysis.args else analysis.kwargs["scripts"]
    assert os.path.basename(scripts[0]) == "__entrypoint__.py"


def test_worker_modules_are_hidden_imports(spec_from_root: Tuple[_Rec, _Rec]) -> None:
    """Workers are reached only via importlib; static analysis cannot see them.

    The spec derives them by exec'ing `src/main.py` and reading `_WORKERS`, so a
    rename that breaks that derivation must fail here rather than at build time.
    """
    analysis, _exe = spec_from_root
    hidden = analysis.kwargs.get("hiddenimports", [])
    assert any(h.startswith(("src.io_step", "src.export", "src.io_mesh"))
               for h in hidden), f"no worker modules among {len(hidden)} hiddenimports"
    assert "src.io_mesh.mesh_ops_worker" in hidden, "mesh workers dropped"


def test_vtk_lazy_modules_are_hidden_imports(
        spec_from_root: Tuple[_Rec, _Rec]) -> None:
    analysis, _exe = spec_from_root
    hidden = analysis.kwargs.get("hiddenimports", [])
    assert "vtkmodules.all" in hidden
    assert "vtkmodules.qt.QVTKRenderWindowInteractor" in hidden


def test_second_qt_binding_is_excluded(spec_from_root: Tuple[_Rec, _Rec]) -> None:
    """qtpy probes every binding; a stray PyQt beside PySide6 breaks the app."""
    analysis, _exe = spec_from_root
    assert {"PyQt5", "PyQt6"} <= set(analysis.kwargs.get("excludes", ()))


def test_build_is_onedir_and_windowed(spec_from_root: Tuple[_Rec, _Rec]) -> None:
    """onefile would re-extract the ~1 GB payload on every worker launch."""
    _analysis, exe = spec_from_root
    assert exe.kwargs.get("exclude_binaries") is True, "not a onedir build"
    assert exe.kwargs.get("console") is False, "release build must be windowed"


def test_version_resource_is_written_under_the_repo_build_dir(
        spec_from_root: Tuple[_Rec, _Rec]) -> None:
    """`EXE(version=)` anchors to the SPEC dir, so this must be absolute."""
    _analysis, exe = spec_from_root
    version_file = exe.kwargs.get("version")
    assert version_file, "no VSVersionInfo file passed to EXE"
    assert os.path.exists(version_file)
    assert Path(version_file).parent == REPO / "build"
    assert "CellSmith.exe" in Path(version_file).read_text(encoding="utf-8")
