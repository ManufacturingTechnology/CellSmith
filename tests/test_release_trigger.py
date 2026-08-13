"""The release trigger fires on EVERY push to `release/*`, and the dedupe holds.

WHY THIS TEST EXISTS (`CS-163`)
    `release.yml` used to carry `paths: ['src/__version__.py']`. A PR merging
    `main` into `release/0.1` then did **nothing at all** — no run, no red X, no
    annotation — because GitHub evaluates a push's `paths` filter against a
    TWO-DOT diff of the push's before/after SHAs, and both tips carried the same
    version. A release that does not happen looked exactly like one that was
    never requested, and the first anyone noticed was "no release was created".

    So the filter is gone, and that is a DECISION, not an oversight — hence this
    test. Firing every time is only safe because the dedupe lives one layer down:
    the `version` job clears `should_release` when the tag implied by
    `__version__` already exists on the remote, and both build jobs are gated on
    it. Remove the filter without that guard and every doc push to a release
    branch re-releases. Remove the guard while the filter is gone and the same
    thing happens. The two are a pair, so the test asserts both.

    `ci.yml`'s `version-check` carries the PR-time half: a PR into `release/X.Y`
    whose version is already tagged is refused, because merging it could only
    produce a run that skips itself.

Pure YAML/text reads — no runner, no network. CI-eligible (no marker).
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Dict

import pytest
import yaml

REPO = Path(__file__).resolve().parent.parent
CI = REPO / ".github" / "workflows" / "ci.yml"
RELEASE = REPO / ".github" / "workflows" / "release.yml"


def _load(path: Path) -> Dict[str, Any]:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def _triggers(doc: Dict[str, Any]) -> Dict[str, Any]:
    """`on:` is YAML 1.1's boolean true, so PyYAML keys it as `True`."""
    on = doc.get(True, doc.get("on"))
    assert isinstance(on, dict), f"unexpected `on:` shape: {on!r}"
    return on


def test_release_fires_on_every_push_to_a_release_branch() -> None:
    push = _triggers(_load(RELEASE))["push"]
    assert "release/*" in push["branches"]
    assert "paths" not in push, (
        "release.yml's push trigger has a `paths` filter again. That makes a "
        "merge into release/* a SILENT no-op whenever the version did not change "
        "— the CS-163 failure. The tag check in the `version` job is what "
        "prevents duplicate releases; the paths filter is not needed for it.")
    assert "paths-ignore" not in push


def test_release_keeps_the_manual_escape_hatch() -> None:
    assert "workflow_dispatch" in _triggers(_load(RELEASE)), (
        "workflow_dispatch is how a broken release is re-run without inventing a "
        "version number")


def test_the_duplicate_release_guard_still_exists() -> None:
    """Without the paths filter this is the ONLY thing gating a re-release."""
    doc = _load(RELEASE)
    version_job = doc["jobs"]["version"]
    body = "\n".join(s.get("run", "") for s in version_job["steps"])
    assert "ls-remote --tags" in body, \
        "the `version` job no longer looks up the tag — every push would release"
    assert "should_release=false" in body, \
        "the tag lookup no longer clears should_release"
    for job in ("build-linux", "build-windows"):
        assert "should_release" in doc["jobs"][job].get("if", ""), \
            f"'{job}' is no longer gated on should_release"


def test_the_pr_gate_refuses_an_already_released_version() -> None:
    step = next(s for s in _load(CI)["jobs"]["version-check"]["steps"] if "run" in s)
    run = step["run"]
    assert "ls-remote --tags" in run, (
        "version-check no longer checks whether __version__ is already tagged; a "
        "PR into release/* that cannot release anything would merge green")
    assert "::error::" in run


@pytest.mark.parametrize("path", [CI, RELEASE], ids=lambda p: p.name)
def test_no_remote_lookup_is_piped_into_grep_q(path: Path) -> None:
    """`git ls-remote … | grep -q` reads a FAILED LOOKUP as "does not exist".

    Under `-o pipefail` it is worse than merely lossy: `grep -q` exits at the
    first match, so a producer that is still writing takes SIGPIPE and fails the
    pipeline that just succeeded. Both readings send a release the wrong way, so
    these queries assign first and test the variable.
    """
    # Scan the `run:` SCRIPTS with comment lines stripped, not the raw file: the
    # first version of this test read the whole text and flagged the comments
    # that WARN about the anti-pattern. The parity test made the same mistake in
    # reverse (it pinned `compgen`, and kept passing on a file whose only
    # `compgen` was in a comment). Match code, never prose about code.
    bad = []
    for job_name, job in _load(path)["jobs"].items():
        for step in job.get("steps", []):
            for line in (step.get("run") or "").splitlines():
                if line.lstrip().startswith("#"):
                    continue
                if re.search(r"ls-remote.*\|\s*grep", line):
                    bad.append(f"{job_name}: {line.strip()}")
    assert not bad, "pipe a remote lookup into grep:\n  " + "\n  ".join(bad)
