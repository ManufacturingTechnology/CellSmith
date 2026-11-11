"""The content check (`.github/scripts/check-content.py`, ADR-0011): no personal paths, email addresses, secrets,
this machine's identity or confidentiality stamps in any file git would commit.

`test_repository_is_clean` is the enforcement: it is CI-eligible, so `test-linux` and `test-windows` fail on a
finding. The other tests pin the rules, so a regex edit can't silently stop catching (or start over-catching).

This file spells the patterns on purpose (fictional samples), so the policy EXEMPTs it, as it does itself.
"""
import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / ".github" / "scripts" / "check-content.py"

_spec = importlib.util.spec_from_file_location("check_content", SCRIPT)
check_content = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(check_content)

BS = "\\"
WIN = "C:" + BS + "Users" + BS          # a Windows profile root
AT = "@"


def rules(text: str, rel: str = "docs/page.md") -> list[str]:
    return [name for _, name, _ in check_content.scan_file(rel, text, denylist=[])]


@pytest.mark.parametrize("text", [
    WIN + "jdoe" + BS + ".ssh" + BS + "config",
    WIN + "jdoe/.ssh/config",                                  # mixed separators, as git-for-windows prints them
    "c:/Users/jdoe/AppData/Local/Temp",
    "C:" + BS + BS + "Users" + BS + BS + "jdoe" + BS + BS + "x",  # escaped in a string literal
    "/home/jdoe/.bashrc",
    "/Users/jdoe/Library/",
    "/mnt/c/Users/jdoe/Programming/",
])
def test_personal_paths_are_flagged(text):
    assert any(r.startswith("personal path") for r in rules(text)), text


@pytest.mark.parametrize("text", [
    "/home/runner/.bash_logout",                                # GitHub's CI runner account
    WIN + "Public" + BS + "Desktop",
    WIN + "<you>" + BS + ".ssh",
    WIN + "%USERNAME%" + BS + "x",
    "/home/$USER/.cache/",
    "%LOCALAPPDATA%" + BS + "anaconda3",
    "~/.ssh/config",
    "src/home/page/",                                           # not a home folder
])
def test_non_personal_paths_pass(text):
    assert not any(r.startswith("personal path") for r in rules(text)), text


@pytest.mark.parametrize("text, flagged", [
    ("C:" + BS + "Windows" + BS + "Fonts" + BS + "segoeui.ttf", True),
    ("D:" + BS + "a" + BS + "CellSmith" + BS + "build", True),            # a CI runner's work folder
    ("C:/Applications/isaac-sim/python.bat", True),
    (BS + BS + "fileserver" + BS + "share" + BS + "x", True),            # UNC
    ("/mnt/c/Program Files/x", True),
    ("%WINDIR%" + BS + "Fonts" + BS + "segoeui.ttf", False),
    ("<isaac-sim-install>" + BS + "python.bat", False),
    ("<drive>:" + BS + "Users" + BS + "<name>", False),                   # a placeholder
    ("https://example.org/a:b", False),
    ("/usr/share/applications", False),                                  # POSIX system paths are allowed
    ("/opt/cellsmith/CellSmith", False),
])
def test_absolute_machine_paths(text, flagged):
    assert ("absolute machine path (drive letter / UNC)" in rules(text)) is flagged, text


def test_one_path_is_one_finding():
    assert rules(WIN + "jdoe" + BS + "x" + BS) == ["personal path (Windows user profile)"]


@pytest.mark.parametrize("text, flagged", [
    ("jdoe" + AT + "company.org", True),
    ("Maintainer: A Person <a.person" + AT + "mail.co.uk>", True),
    ("git" + AT + "github.com:owner/repo.git", False),
    ("noreply" + AT + "anthropic.com", False),
    ("123+jdoe" + AT + "users.noreply.github.com", False),
    ("someone" + AT + "example.com", False),
    ("AMT <technology" + AT + "amtonline.org>", False),           # ALLOWED_EMAILS: a public role address
    ("person" + AT + "amtonline.org", True),                     # ...but not every address at that domain
])
def test_email_rule(text, flagged):
    assert ("email address" in rules(text)) is flagged, text


def test_license_texts_may_contain_emails():
    assert rules("contact: dev" + AT + "project.org", rel="packaging/licenses/X.txt") == []


@pytest.mark.parametrize("text, rule", [
    ("-----BEGIN " + "RSA PRIVATE KEY-----", "private key"),
    ("AKIA" + "ABCDEFGHIJKLMNOP", "AWS access key"),
    ("ghp_" + "a1B2" * 9, "GitHub token"),
    ("glpat-" + "a1B2" * 5, "GitLab token"),
    ("xoxb-" + "1234567890-abcdef", "Slack token"),
    ("AIza" + "S" * 35, "Google API key"),
    ("sk-" + "proj-" + "Ab3" * 8, "OpenAI or Anthropic key"),
    ("eyJ" + "hbGciOiJIUzI1" + ".eyJ" + "zdWIiOiIxMjM0" + ".SflKxwRJSMeKKF2QT4", "JSON web token"),
    ("mqtt://alice:" + "Hunter2Hunter2" + AT + "broker.local:1883", "password in a URL"),
    ('api_key = "' + "q8Zr" + "71LmXp0a" + '"', "secret assigned a literal"),
    ('token = "' + "latest" + "Q8zr71Lm" + '"', "secret assigned a literal"),   # "latest" is not a placeholder
])
def test_secrets_are_flagged_and_masked(text, rule):
    found = check_content.scan_file("src/x.py", text, denylist=[])
    assert rule in [name for _, name, _ in found], text
    for _, name, excerpt in found:
        if name == rule:
            assert excerpt.endswith("...") and len(excerpt) == 7, excerpt  # never the secret itself


@pytest.mark.parametrize("text", [
    "mqtt://user:<password>" + AT + "broker:1883",
    "postgres://app:${DB_PASSWORD}" + AT + "db/app",
    'token = "<your-token-here>"',
    'password = "example-password"',
    'api_key = "test-api-key-123"',
    "token: str = secrets.token_urlsafe(32)",
    'api_key = "my_test_key_123"',
])
def test_secret_placeholders_pass(text):
    assert not [n for n in rules(text, rel="src/x.py") if n in check_content.SECRET_NAMES], text


def test_identity_rule_matches_this_machine_off_ci(monkeypatch):
    monkeypatch.delenv("CI", raising=False)
    monkeypatch.setenv("USERNAME", "qzxwvut")
    found = check_content.scan_file("docs/page.md", "written by qzxwvut", denylist=check_content.load_identity())
    assert "this machine's identity" in [name for _, name, _ in found]


def test_identity_rule_is_off_on_ci(monkeypatch):
    monkeypatch.setenv("CI", "true")
    assert check_content.load_identity() == []


@pytest.mark.parametrize("text", [
    "the user\nsaid to always rebase",          # wraps across a line break
    "The maintainer wants fewer prompts.",
    "Per the user, use 127.0.0.1.",
    "Symptom from a live report: the pane closed.",
    "I want the agent to stop guessing.",
    "Respect my preference for short replies.",
])
def test_transcripts_are_flagged_in_agent_docs(text):
    assert any(n in ("guidance attributed to a person", "first-person quote")
               for n in rules(text, rel="docs/src/AI/page.md")), text


@pytest.mark.parametrize("text", [
    "user decision, 2026-11-11",
    "The UI shows the user a dialog.",
    "If I/O fails, retry once.",
    "Search for `the user said` and rewrite it.",   # code spans are data
    "Symptom (live GUI test): the pane closed.",
    "When the user wants a subtree, right-click it.",   # the when/do instruction form
    "If the user\nasks for a rebuild, run make.",
    "The MQTT client reports the pose every 100 ms.",   # a software client, not a person
])
def test_instructions_pass(text):
    assert not [n for n in rules(text, rel="docs/src/AI/page.md")
                if n in ("guidance attributed to a person", "first-person quote")], text


def test_transcript_rule_covers_only_agent_docs():
    assert rules("the user said so", rel="src/gui/x.py") == []
    assert rules("the user said so", rel="CLAUDE.md") == ["guidance attributed to a person"]


def test_confidentiality_stamp():
    assert "confidentiality stamp" in rules("This document is " + "CONFIDENTIAL" + ".")


def test_denylist_terms_match_case_insensitively():
    found = check_content.scan_file("a.md", "Hello SecretProject", denylist=[
        ("denylisted term", __import__("re").compile("secretproject", __import__("re").IGNORECASE))])
    assert [name for _, name, _ in found] == ["denylisted term"]


def _run_hook(file_path: str, content: str) -> subprocess.CompletedProcess:
    event = {"cwd": str(ROOT), "tool_input": {"file_path": file_path, "content": content}}
    return subprocess.run([sys.executable, str(SCRIPT), "--hook"], input=json.dumps(event).encode(),
                          capture_output=True, cwd=ROOT)


def test_hook_blocks_a_tracked_write():
    result = _run_hook(str(ROOT / "docs" / "new-page.md"), "see " + WIN + "jdoe" + BS + "x")
    assert result.returncode == 2, result.stderr.decode()
    assert b"Blocked by the content check" in result.stderr


def test_hook_blocks_even_when_the_report_is_not_ascii():
    # cp1252 (Windows' default) can't encode "→": if printing the report raised, the exit would be 1, which does
    # not block the write.
    result = _run_hook(str(ROOT / "docs" / "new-page.md"), "→ " + WIN + "jdöe" + BS + "x →")
    assert result.returncode == 2, result.stderr.decode("utf-8", "replace")


def test_hook_allows_a_clean_write():
    assert _run_hook(str(ROOT / "docs" / "new-page.md"), "see %LOCALAPPDATA%").returncode == 0


def test_hook_allows_a_gitignored_write():
    # scratchpad/ is gitignored: private material may live there
    assert _run_hook(str(ROOT / "scratchpad" / "note.txt"), WIN + "jdoe" + BS + "x").returncode == 0


def test_repository_is_clean():
    findings = check_content.collect()
    assert not findings, "private or confidential material in files git would commit:\n" + "\n".join(
        f"  {rel}:{line}: {name}: {excerpt!r}" for rel, line, name, excerpt in findings)
