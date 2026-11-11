"""`src/__version__.py` is the single source of truth — guard how it is READ.

WHY THIS IS A REAL TEST AND NOT A SCRATCH PROBE (`CS-158`)
    Four things read that file, by two different mechanisms:

        exec-and-print   build.bat, makefile, packaging/debian/make_deb.sh,
                         packaging/cellsmith.spec        (correct, always was)
        text parse       .github/workflows/{ci,release}.yml via
                         .github/scripts/read-version.sh

    Both workflows used to inline `grep -oP '"\\K[^"]+' src/__version__.py`, which
    is UNANCHORED — it matches inside the module DOCSTRING's triple-quote opener
    and returns the docstring's first line ahead of the version. The first PR into
    a release branch died on it:

        __version__ 'Single source of truth for the application version.
        0.1.0-alpha.1' is not valid semver

    So the release guard had never worked, and both copies were wrong the same
    way. These tests pin the two properties that keep any reader honest: the file
    has exactly ONE version assignment, and no workflow re-inlines a parse.

Pure file reads — no bash, no PyInstaller, no Qt. CI-eligible (no marker).
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
VERSION_FILE = REPO / "src" / "__version__.py"
READER = REPO / ".github" / "scripts" / "read-version.sh"
WORKFLOWS = [
    REPO / ".github" / "workflows" / "ci.yml",
    REPO / ".github" / "workflows" / "release.yml",
]

#: Mirrors the BRE in read-version.sh. This is not a second source of truth for
#: the version — it asserts the SHAPE of the file that every reader depends on.
ASSIGNMENT = re.compile(r'^__version__\s*=\s*"([^"]*)"', re.MULTILINE)
SEMVER = re.compile(r"^\d+\.\d+\.\d+(-[0-9A-Za-z.-]+)?$")


@pytest.fixture(scope="module")
def body() -> str:
    return VERSION_FILE.read_text(encoding="utf-8")


def test_exactly_one_version_assignment(body: str) -> None:
    """Two assignments and the readers disagree: `exec` keeps the LAST, a text
    parse takes the FIRST. Then the tag and the payload carry different versions.
    """
    found = ASSIGNMENT.findall(body)
    assert len(found) == 1, \
        f"expected exactly one __version__ assignment, found {len(found)}: {found}"


def test_version_is_semver(body: str) -> None:
    version = ASSIGNMENT.findall(body)[0]
    assert SEMVER.match(version), \
        f"__version__ {version!r} is not MAJOR.MINOR.PATCH[-PRERELEASE]"


def test_text_parse_and_exec_agree(body: str) -> None:
    """The two mechanisms must return the same string for the same file."""
    ns: dict = {}
    exec(compile(body, str(VERSION_FILE), "exec"), ns)
    assert ns["__version__"] == ASSIGNMENT.findall(body)[0]


def test_the_docstring_does_not_leak_into_an_anchored_parse(body: str) -> None:
    """The actual regression: the file opens with a triple-quoted docstring, and
    an unanchored `"..."` match reads prose out of it. Anchoring is what fixes it,
    so keep the collision present and prove anchoring survives it.
    """
    assert body.lstrip().startswith('"""'), \
        "docstring gone — this test no longer reproduces the collision it guards"
    unanchored = re.findall(r'"([^"]+)"', body)
    assert len(unanchored) > 1, "no collision to guard against any more"
    assert ASSIGNMENT.findall(body) == [ns_version(body)]


def ns_version(body: str) -> str:
    ns: dict = {}
    exec(compile(body, "<version>", "exec"), ns)
    return ns["__version__"]


@pytest.mark.parametrize("workflow", WORKFLOWS, ids=lambda p: p.name)
def test_workflows_read_the_version_via_the_shared_script(workflow: Path) -> None:
    text = workflow.read_text(encoding="utf-8")
    if "__version__.py" not in text and "read-version.sh" not in text:
        pytest.skip(f"{workflow.name} does not read the version")
    assert "read-version.sh" in text, \
        f"{workflow.name} must read the version via .github/scripts/read-version.sh"
    # An inlined parse is what broke twice. `paths:` filters and comments may name
    # the file; a `grep`/`sed`/`awk` pipeline over it may not.
    for line in text.splitlines():
        if "__version__.py" not in line or line.lstrip().startswith("#"):
            continue
        assert not re.search(r"\b(grep|sed|awk|cut|head|tail)\b", line), \
            (f"{workflow.name} inlines a version parse:\n    {line.strip()}\n"
             f"use .github/scripts/read-version.sh instead")


def test_the_reader_exists_and_avoids_pcre_grep() -> None:
    """`grep -P` is not portable: Git Bash on Windows refuses it outright
    ("-P supports only unibyte and UTF-8 locales"), which would make the reader
    untestable on a dev machine even though it works on the runner.
    """
    assert READER.exists(), f"missing {READER}"
    for line in READER.read_text(encoding="utf-8").splitlines():
        if line.lstrip().startswith("#"):
            continue
        assert not re.search(r"grep\s+-[A-Za-z]*P", line), \
            f"read-version.sh uses PCRE grep, which is not portable:\n    {line}"
