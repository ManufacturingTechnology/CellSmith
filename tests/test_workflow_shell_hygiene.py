"""No CI step may run the `exit` builtin under a LOGIN shell.

WHY THIS TEST EXISTS
    The `Assert both Linux artifacts were produced` step ran under
    `shell: bash -el {0}`, printed both of its `ok` lines, computed `rc=0`, ran
    `exit 0` — and the runner reported "Process completed with exit code 1".
    Nothing in the script could produce that, and it did not reproduce locally,
    so it was written off as an unexplained shell-wrapper fault.

    It is fully explained. bash(1), INVOCATION:

        "When an interactive login shell exits, or a non-interactive login shell
         executes the exit builtin command, bash reads and executes commands
         from the file ~/.bash_logout, if it exists."

        https://www.gnu.org/software/bash/manual/html_node/Bash-Startup-Files.html

    `bash -el {0}` is a non-interactive login shell, so calling `exit` sources
    `~/.bash_logout` — and the status of THAT file's last command becomes the
    shell's status. On an Ubuntu runner the file is the `/etc/skel` default,
    ending in `[ -x /usr/bin/clear_console ] && /usr/bin/clear_console -q`, which
    exits 1 with no terminal attached. Probed on bash 5.2.37 with SHLVL unset in
    the parent (the runner's situation, since bash is spawned by a non-shell
    parent and therefore sets SHLVL=1 itself):

        bash -el + `exit 0`, skel ~/.bash_logout        -> exit 1
        bash -el, script with no `exit` builtin         -> exit 0
        bash --noprofile --norc -eo pipefail + `exit 0` -> exit 0
        bash -el + `exit 1`                             -> exit 1

    So a login-shell step that never calls `exit` is safe, and the earlier local
    repro "passed" only because that HOME had no `~/.bash_logout`.

    THE RULE: if a step needs to `exit`, it must not use a login shell. If it
    needs the conda env AND an explicit exit, restructure so the script falls off
    its end (the shell's status is then the last command's, and `~/.bash_logout`
    is never read), or move the deciding logic into a called script — a child
    `bash script.sh` is not a login shell, so its `exit` is unaffected.

Pure YAML reads — no runner, no Docker. CI-eligible (no marker).
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Dict, Iterator, List, Tuple

import pytest
import yaml

REPO = Path(__file__).resolve().parent.parent
WORKFLOWS = sorted((REPO / ".github" / "workflows").glob("*.yml"))
ACTIONS = sorted((REPO / ".github" / "actions").glob("*/action.yml"))

#: `exit` as a COMMAND: at the start of a line or after `;`, `&&`, `||`, `then`,
#: `else`, `do`. Not `exit_code=…`, not the word inside a message.
EXIT_CALL = re.compile(
    r"(?:^|;|&&|\|\||\bthen\b|\belse\b|\bdo\b)\s*exit\b(?!\s*=)", re.MULTILINE)


def _is_login_shell(shell: str | None) -> bool:
    """True for a custom bash template whose flag cluster carries `-l`.

    `bash`, `sh`, `pwsh`, `cmd`, `python` (the GitHub keywords) are never login
    shells — the `bash` keyword expands to `bash --noprofile --norc -eo pipefail`.
    Only an explicit template such as `bash -el {0}` or `bash -l {0}` is.
    """
    if not shell:
        return False
    tokens = shell.split()
    if not tokens or Path(tokens[0]).name not in {"bash", "sh"}:
        return False
    return any(
        tok.startswith("-") and not tok.startswith("--") and "l" in tok[1:]
        for tok in tokens[1:]
    ) or "--login" in tokens[1:]


def _strip_comments(script: str) -> str:
    """Drop whole-line `#` comments so a commented-out `exit` is not a finding."""
    return "\n".join(ln for ln in script.splitlines()
                     if not ln.lstrip().startswith("#"))


def _label(step: Dict[str, Any]) -> str:
    return step.get("name") or step.get("uses") or "<unnamed>"


def _workflow_steps(path: Path) -> Iterator[Tuple[str, Dict[str, Any], str | None]]:
    """Yield (context, step, effective shell) for every `run:` step."""
    doc = yaml.safe_load(path.read_text(encoding="utf-8"))
    wf_default = (doc.get("defaults") or {}).get("run", {}).get("shell")
    for job_name, job in (doc.get("jobs") or {}).items():
        job_default = (job.get("defaults") or {}).get("run", {}).get("shell")
        for step in job.get("steps") or []:
            if "run" not in step:
                continue
            shell = step.get("shell") or job_default or wf_default
            yield f"{path.name} job '{job_name}' step {_label(step)!r}", step, shell


def _action_steps(path: Path) -> Iterator[Tuple[str, Dict[str, Any], str | None]]:
    """Composite-action steps. These do NOT inherit any job's `defaults`."""
    doc = yaml.safe_load(path.read_text(encoding="utf-8"))
    for step in doc["runs"].get("steps") or []:
        if "run" not in step:
            continue
        yield f"{path.parent.name} step {_label(step)!r}", step, step.get("shell")


ALL_FILES = WORKFLOWS + ACTIONS


def _steps_of(path: Path):
    return _action_steps(path) if path.name == "action.yml" else _workflow_steps(path)


@pytest.mark.parametrize("path", ALL_FILES, ids=lambda p: f"{p.parent.name}/{p.name}")
def test_no_login_shell_step_calls_exit(path: Path) -> None:
    offenders: List[str] = []
    for context, step, shell in _steps_of(path):
        if not _is_login_shell(shell):
            continue
        script = _strip_comments(step["run"])
        if EXIT_CALL.search(script):
            offenders.append(f"  {context}\n    shell: {shell}")
    assert not offenders, (
        "these steps call the `exit` builtin under a LOGIN shell, so bash sources "
        "~/.bash_logout and ITS last command's status replaces theirs — an "
        "`exit 0` is reported as exit 1 on an Ubuntu runner:\n"
        + "\n".join(offenders)
        + "\n\nFix: give the step `shell: bash` (no conda env), or let the script "
          "fall off its end instead of calling `exit`. See this module's docstring."
    )


# NOTE: a workflow step that declares no shell and inherits no default is fine
# here — it gets the runner default (`bash --noprofile --norc -eo pipefail` on
# Linux, `pwsh` on Windows), neither of which is a login shell. Composite-action
# steps DO require an explicit shell, and test_ci_release_parity.py asserts that.


def test_the_guard_would_actually_catch_the_regression() -> None:
    """Guard the guard: the detector must fire on the exact script that failed."""
    failed = (
        "set -uo pipefail\n"
        "rc=0\n"
        'echo "  ok    dist/CellSmith-v0.1.0-alpha.1-linux-x86_64.tar.gz"\n'
        "exit $rc\n"
    )
    assert _is_login_shell("bash -el {0}")
    assert _is_login_shell("bash -l {0}")
    assert _is_login_shell("bash --login {0}")
    assert not _is_login_shell("bash")
    assert not _is_login_shell("bash -eo pipefail {0}")   # `-e`, no `-l`
    assert not _is_login_shell("pwsh")
    assert EXIT_CALL.search(_strip_comments(failed))
    assert EXIT_CALL.search("if [ -z \"$x\" ]; then exit 1; fi")
    assert not EXIT_CALL.search(_strip_comments("# exit 1 was here\nls\n"))
    assert not EXIT_CALL.search('echo "the exit code was $rc"')
