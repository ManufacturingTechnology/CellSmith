"""The PR gate must build exactly what the release build builds.

WHY THIS IS A REAL TEST AND NOT A SCRATCH PROBE (`CS-160`)
    `ci.yml` used to run PyInstaller only — no tar.gz, no `.deb`, no zip, no Inno
    installer — because that kept the gate ~15 min shorter. The cost of that trade
    showed up twice in a row, both times in the half the gate skipped:

      * `make_deb.sh` died with `printf: write error: Broken pipe` the first time
        it saw a REAL payload (a `printf | grep -q` over a 200 kB file listing).
      * the release version guard had never worked — an unanchored parse, in two
        inlined copies that were wrong identically.

    A step the gate does not run is a step nobody has tested until release day,
    and a step duplicated across two workflows drifts. So the build now lives in
    ONE composite action per OS, used verbatim by both workflows, and this test is
    what keeps that true. Release-SPECIFIC work (collect, upload, tag) stays in
    `release.yml` — parity is about the BUILD, not about publishing.

Pure YAML reads — no runner, no Docker. CI-eligible (no marker).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List

import pytest
import yaml

REPO = Path(__file__).resolve().parent.parent
CI = REPO / ".github" / "workflows" / "ci.yml"
RELEASE = REPO / ".github" / "workflows" / "release.yml"
ACTIONS = REPO / ".github" / "actions"

#: The build jobs that must be identical between the two workflows, and the
#: composite action each is required to delegate to.
BUILD_JOBS = {"build-linux": "./.github/actions/build-linux",
              "build-windows": "./.github/actions/build-windows"}

#: Commands that constitute "the build". If one of these appears inline in a
#: workflow, the two pipelines can diverge again — it belongs in the composite.
BUILD_COMMANDS = ("make build", "build.bat", "PyInstaller", "verify-payload.sh",
                  "make deb", "make_deb.sh")

#: Steps release.yml may add AFTER the shared build. Publishing, not building.
RELEASE_ONLY = ("Collect the artifacts", "actions/upload-artifact")


def _load(path: Path) -> Dict[str, Any]:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def _steps(workflow: Dict[str, Any], job: str) -> List[Dict[str, Any]]:
    return workflow["jobs"][job]["steps"]


def _label(step: Dict[str, Any]) -> str:
    return step.get("name") or step.get("uses") or "<unnamed>"


@pytest.fixture(scope="module")
def ci() -> Dict[str, Any]:
    return _load(CI)


@pytest.fixture(scope="module")
def release() -> Dict[str, Any]:
    return _load(RELEASE)


@pytest.mark.parametrize("job,action", sorted(BUILD_JOBS.items()))
def test_both_workflows_delegate_to_the_same_composite_action(
        job: str, action: str, ci: Dict[str, Any], release: Dict[str, Any]) -> None:
    for name, wf in (("ci.yml", ci), ("release.yml", release)):
        used = [s.get("uses") for s in _steps(wf, job)]
        assert action in used, (
            f"{name} job '{job}' does not use {action}; the PR gate and the "
            f"release build must run the SAME build steps")


@pytest.mark.parametrize("job", sorted(BUILD_JOBS))
def test_the_gate_adds_nothing_and_skips_nothing(
        job: str, ci: Dict[str, Any], release: Dict[str, Any]) -> None:
    """ci's build job = checkout + the shared action. release adds only publishing."""
    ci_labels = [_label(s) for s in _steps(ci, job)]
    rel_labels = [_label(s) for s in _steps(release, job)]

    assert ci_labels == rel_labels[:len(ci_labels)], (
        f"'{job}' diverges before the release-only tail:\n"
        f"  ci.yml      {ci_labels}\n  release.yml {rel_labels}")
    for extra in rel_labels[len(ci_labels):]:
        assert any(allowed in extra for allowed in RELEASE_ONLY), (
            f"release.yml '{job}' has build step {extra!r} that the PR gate never "
            f"runs — move it into the composite action or into the release tail")


@pytest.mark.parametrize("path", [CI, RELEASE], ids=lambda p: p.name)
def test_no_workflow_inlines_a_build_command(path: Path) -> None:
    """Inline build commands are how the two pipelines drifted apart before."""
    wf = _load(path)
    for job_name, job in wf["jobs"].items():
        for step in job.get("steps", []):
            run = step.get("run") or ""
            for cmd in BUILD_COMMANDS:
                assert cmd not in run, (
                    f"{path.name} job '{job_name}' step {_label(step)!r} runs "
                    f"{cmd!r} inline; it belongs in the shared composite action")


@pytest.mark.parametrize("action", sorted(set(BUILD_JOBS.values())))
def test_the_composite_action_actually_builds_and_verifies(action: str) -> None:
    # removeprefix, NOT lstrip("./") — lstrip takes a CHARACTER SET and would eat
    # the leading dot of `.github` too.
    path = REPO / action.removeprefix("./") / "action.yml"
    assert path.exists(), f"missing {path}"
    doc = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert doc["runs"]["using"] == "composite"
    body = path.read_text(encoding="utf-8")
    # The build, the payload verification, and the artifact assertion are the
    # three things the gate exists to run early.
    assert "verify-payload.sh" in body, f"{path.name} never verifies the payload"
    assert ("make build" in body) or ("build.bat" in body), \
        f"{path.name} never runs the packaging build"
    assert "compgen -G" in body, \
        f"{path.name} never asserts the artifacts were produced"
    # Composite steps do NOT inherit a job's `defaults.run.shell`.
    for step in doc["runs"]["steps"]:
        assert "uses" in step or "shell" in step, \
            f"{path.name}: step {_label(step)!r} has no explicit shell"
