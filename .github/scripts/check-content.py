#!/usr/bin/env python3
"""Keep private and confidential material, and secrets, out of the repository (ADR-0011).

Adapted from the content check of the DTP-Isaac-Sim-Service repository (same policy shape, CellSmith's rules).
Standard library only, so it runs anywhere `python3` does: the agent hook, a bare CI runner, a pre-commit hook.

One policy, four callers:
  - the agent hook (`.claude/settings.json`, PreToolUse on Write/Edit/MultiEdit/NotebookEdit): `--hook` reads the
    hook's JSON on stdin and BLOCKS (exit 2) a write that would put a match into a tracked file;
  - `make content-check`: scans every tracked or to-be-tracked file (gitignored files are skipped);
  - `tests/test_content_check.py`: the same scan, so CI's `test-linux` / `test-windows` enforce it;
  - the pre-commit hook (`.githooks/pre-commit`, enabled per clone with `git config core.hooksPath .githooks`):
    `--staged` scans the staged versions.

WHAT IT FLAGS
    Personal paths: a Windows user-profile path (`<drive>:\\Users\\<name>`), and a home folder on Linux, macOS or
        WSL (`/home/<name>/`, `/Users/<name>/`, `/mnt/<drive>/Users/<name>/`), with either slash. They name a person
        and mean nothing on another machine. Not flagged: GitHub's CI runner account (`/home/runner/`), the shared
        Windows profiles (`Public`, `Default`, `All Users`), and placeholders (`<you>`, `$USER`, `%USERNAME%`, `you`,
        `user`, `username`, `name`).
    Email addresses: any, except no-reply addresses, `example.*` domains and `git@` SSH remotes. Third-party
        license texts (`packaging/licenses/`) are exempt: their contact addresses are part of the verbatim text.
    Secrets: private key blocks; the token formats of AWS, GitHub, GitLab, Slack, Google, Stripe, OpenAI and
        Anthropic, and JWTs; a password in a URL; a literal assigned to a secret-named key (`password`, `api_key`,
        `token`, ...). Placeholders pass (`<token>`, `${TOKEN}`, `changeme`, `example`, values containing `test`).
        A matched secret is masked in the report (its first four characters), so a CI log never repeats it.
    This machine's identity (outside CI): the OS username, the home folder's name, the hostname, and git's
        `user.name` and `user.email`, as whole words; generic values (`runner`, `user`) and ones shorter than four
        characters are skipped. CI has its runner's identity, so CI skips this rule.
    Transcripts: in CLAUDE.md, contributing.md, docs/src/ and the skills, guidance attributed to a person
        (`the user said`, `per the user`, `live report`) and first-person quotes, outside code spans and fenced
        blocks, wrapped lines included. The same patterns as the DTP-Isaac-Sim-Service content check and
        MTConnectExplorer's tests/test_agent_docs.py. Reviewed exceptions: ALLOW_TRANSCRIPT.
    Confidentiality stamps: generic document markings (STAMPS below).
    Local denylist terms: `.claude/confidential-terms.txt` in this repo (gitignored) and
        `~/.claude/confidential-terms.txt`, both outside git. One term per line, `#` comments; a plain line matches
        case-insensitively as a literal, a line starting with `re:` is a regular expression. Put your own names,
        usernames and addresses there. CI has neither file, so CI checks only the generic patterns.

WHAT IT DOESN'T CHECK
    Binary files (images, fonts, CAD, USD crate files): their strings can't be matched reliably. Text written by
    shell commands rather than the Write/Edit tools: the hook doesn't see it, but the other three callers do.
    History: a match already committed stays in git history; this only stops new ones.

A reviewed finding that is fine goes into ALLOW (path -> reason).

Usage: check-content.py [--hook | --staged]
"""
import json
import os
import re
import socket
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

# A user name inside a path: up to the next separator, quote, whitespace or markup character.
_NAME = r"[^\\/\s'\"`<>|:*?()\[\]{}]+"
# Names that are not a person: CI's account, Windows' shared profiles, and documentation placeholders.
_NOT_A_PERSON = r"(?!(?:runner|Public|Default|All Users|Shared|you|user|username|name|USERNAME|USER)(?:[\\/'\"`\s]|$))"

PRIVACY = [
    ("personal path (Windows user profile)",
     re.compile(r"(?i)\b[A-Z]:[\\/]+Users[\\/]+" + _NOT_A_PERSON + r"(?![$%{<])" + _NAME)),
    ("personal path (home folder)",
     # Starts a path (not `src/home/...`, not the `\Users` of a drive path the rule above already reported), or
     # follows WSL's `/mnt/<drive>`.
     re.compile(r"(?i)(?:(?<=[\\/]mnt[\\/][a-z])|(?<![\w.:\\/-]))[\\/](?:home|Users)[\\/]+" + _NOT_A_PERSON
                + r"(?![$%{<])" + _NAME + r"[\\/]")),
    # ANY other drive-letter or UNC path (`<drive>:\Windows\...`, an install folder, a network share): machine-specific
    # even when it names no person. Write `%WINDIR%`, `<install-dir>`, or a repo-relative path. (User profiles are
    # reported by the more specific rule above.) POSIX system paths (/usr, /opt, /etc) are NOT flagged: they are the
    # same on every machine and packaging needs them.
    ("absolute machine path (drive letter / UNC)",
     re.compile(r"(?i)(?<![A-Z0-9_])[A-Z]:[\\/]{1,2}(?!Users[\\/])(?=[A-Z0-9._~ -])"
                r"|(?<![\\\w])\\\\[A-Z0-9][A-Z0-9.-]*\\[A-Z0-9$]"
                r"|/mnt/[a-z]/(?!Users/)[A-Z0-9._-]")),
    ("email address",
     re.compile(r"(?i)\b(?!git@)(?![\w.+-]*no-?reply)[\w.+-]+@(?!example\.)(?!users\.noreply\.)"
                r"[A-Z0-9-]+(?:\.[A-Z0-9-]+)*\.[A-Z]{2,}\b")),
]

# Secrets. A rule is (name, pattern) or (name, pattern, accept); accept(match) is False for a placeholder. The same
# rules as the DTP-Isaac-Sim-Service content check and MTConnectExplorer's tests/test_privacy.py.
PLACEHOLDER = re.compile(r"(?i)^[<${%*]|example|placeholder|changeme|change[-_]me|your[-_]|xxx|dummy|fake|redacted|"
                         r"(?<![a-z])test|sample|^secret$|^password$|^token$|^none$|^null$")  # not "latest"


def _literal_value(match) -> bool:
    return not PLACEHOLDER.search(match.group("value"))


SECRETS = [
    ("private key", re.compile(r"-----BEGIN (?:[A-Z]+ )*PRIVATE KEY(?: BLOCK)?-----")),
    ("AWS access key", re.compile(r"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b")),
    ("GitHub token", re.compile(r"\bgh[pousr]_[A-Za-z0-9]{36,}\b|\bgithub_pat_[A-Za-z0-9_]{22,}")),
    ("GitLab token", re.compile(r"\bglpat-[A-Za-z0-9_-]{20,}")),
    ("Slack token", re.compile(r"\bxox[abprs]-[A-Za-z0-9-]{10,}")),
    ("Google API key", re.compile(r"\bAIza[0-9A-Za-z_-]{35}")),
    ("Stripe live key", re.compile(r"\b[rs]k_live_[0-9A-Za-z]{20,}")),
    ("OpenAI or Anthropic key", re.compile(r"\bsk-(?:ant-|proj-)?[A-Za-z0-9_-]{20,}")),
    ("JSON web token", re.compile(r"\beyJ[A-Za-z0-9_-]{10,}\.eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}")),
    ("password in a URL", re.compile(r"\b[a-z][a-z0-9+.-]*://[^\s/:@'\"<>]+:(?P<value>[^\s/@'\"<>]+)@"), _literal_value),
    ("secret assigned a literal", re.compile(
        r"(?i)\b(?:password|passwd|pwd|secret|api[_-]?key|access[_-]?key|auth[_-]?token|access[_-]?token|token|"
        r"client[_-]?secret)\b[\"']?\s*[:=]\s*[\"'](?P<value>[^\"'\s]{8,})[\"']"), _literal_value),
]
SECRET_NAMES = {rule[0] for rule in SECRETS}

GENERIC_IDENTITIES = {"user", "users", "admin", "administrator", "root", "runner", "ubuntu", "vscode", "dev",
                      "developer", "default", "guest", "public", "github-actions", "github actions", "localhost"}


def load_identity() -> list:
    """This machine's own identity, as whole words. Skipped on CI, whose identity is the runner's."""
    if os.environ.get("CI"):
        return []
    values = {os.environ.get("USERNAME", ""), os.environ.get("USER", ""), Path.home().name,
              socket.gethostname().split(".")[0]}
    for key in ("user.name", "user.email"):
        values.add(git("config", "--get", key).stdout.decode(errors="replace").strip())
    return [("this machine's identity", re.compile(r"(?<![\w.-])" + re.escape(v) + r"(?![\w-])", re.IGNORECASE))
            for v in sorted(v for v in values if len(v) >= 4 and v.lower() not in GENERIC_IDENTITIES)]


# Instructions, not transcripts (CLAUDE.md, "Recording guidance"; ADR-0011).
AGENT_DOCS = re.compile(r"^(CLAUDE\.md|contributing\.md|docs/src/.*\.md|\.claude/skills/.*\.md)$")
_S = r"\s+"
_CONDITION = re.compile(r"\b(?:if|when|whenever|unless|once|until|whether)\s+$", re.IGNORECASE)


def _not_a_condition(match) -> bool:
    """`When the user wants X, do Y` is the instruction form Recording guidance asks for, not an attribution."""
    return not _CONDITION.search(match.string[max(0, match.start() - 20):match.start()])


# `client` is left out of the subjects: here it is a software role (an MQTT or HTTP client "reports", "asks").
TRANSCRIPT = [
    ("guidance attributed to a person", re.compile(
        rf"\b(?:the{_S})?(?:user|maintainer|owner|customer)(?:'s)?{_S}"
        r"(?:said|says|asked|asks|reported|reports|wants|wanted|requested|complained|felt|feels|"
        r"prefers|preferred|insisted|told)\b", re.IGNORECASE), _not_a_condition),
    ("guidance attributed to a person", re.compile(rf"\b(?:user|customer){_S}feedback\b|\blive{_S}report\b",
                                                   re.IGNORECASE)),
    ("guidance attributed to a person", re.compile(rf"\b(?:per|as){_S}(?:the{_S})?user(?:{_S}(?:asked|requested))?\b",
                                                   re.IGNORECASE)),
    ("first-person quote", re.compile(rf"(?<![\w`'\"-])I(?:{_S}|'(?:m|ve|d){_S})"
                                      r"(?:want|wanted|don't|do\s+not|need|prefer|asked|said|think|feel|like|expect)\b")),
    ("first-person quote", re.compile(rf"\b[Mm]y{_S}(?:preference|feedback|machine|laptop|files?|account|workload)\b")),
]
# Reviewed transcript-rule exceptions: (path, matched text, whitespace collapsed) -> reason.
ALLOW_TRANSCRIPT: dict[tuple[str, str], str] = {}


def _outside_code(text: str) -> str:
    """The text with fenced blocks and code spans blanked, keeping every offset (so line numbers stay right)."""
    text = re.sub(r"^```.*?^```", lambda m: re.sub(r"[^\n]", " ", m.group(0)), text, flags=re.MULTILINE | re.DOTALL)
    return re.sub(r"`[^`\n]*`", lambda m: " " * len(m.group(0)), text)


def scan_transcript(rel: str, text: str) -> list:
    if not AGENT_DOCS.match(rel):
        return []
    found = []
    for line, name, excerpt in scan_text(_outside_code(text), TRANSCRIPT):
        excerpt = " ".join(excerpt.split())
        if (rel, excerpt) not in ALLOW_TRANSCRIPT:
            found.append((line, name, excerpt))
    return found


# Generic confidentiality markings. Case-sensitive where the marking is a stamp in capitals.
STAMPS = [
    ("confidentiality stamp", re.compile(r"\bCONFIDENTIAL\b")),
    ("confidentiality stamp", re.compile(r"(?i)\b(proprietary (and|&) confidential|confidential (and|&) proprietary)\b")),
    ("confidentiality stamp", re.compile(r"(?i)\binternal use only\b")),
    ("confidentiality stamp", re.compile(r"(?i)\bdo not (distribute|disclose|copy|reproduce)\b")),
    ("confidentiality stamp", re.compile(r"(?i)\b(under|subject to) (an? )?(NDA|non-disclosure agreement)\b")),
    ("confidentiality stamp", re.compile(r"(?i)\btrade secret\b")),
    ("export-control marking", re.compile(r"(?i)\bexport[- ]controlled\b|\bITAR\b")),
]

# Reviewed exceptions: repo-relative path -> reason. Keep this list short and explain each entry.
ALLOW: dict[str, str] = {}

# Public ROLE addresses that may appear anywhere (lowercase) -> reason. Never a person's address.
ALLOWED_EMAILS: dict[str, str] = {
    "technology@amtonline.org": "AMT's public technology role address; the package author in DTP-Isaac-Sim-Service "
                                "(iss/ and iscp/ pyproject.toml) and the Debian maintainer here",
}

# Files that spell the patterns themselves: this policy and its tests (whose samples are fictional).
EXEMPT = {".github/scripts/check-content.py", "tests/test_content_check.py"}

# Path prefixes whose files are verbatim third-party text: only the email rule is waived there.
EMAIL_EXEMPT_PREFIXES = ("packaging/licenses/",)

DENYLISTS = [ROOT / ".claude" / "confidential-terms.txt", Path.home() / ".claude" / "confidential-terms.txt"]


def load_denylist() -> list[tuple[str, re.Pattern]]:
    rules = []
    for path in DENYLISTS:
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except OSError:
            continue
        for line in lines:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            pattern = line[3:].strip() if line.startswith("re:") else re.escape(line)
            if not pattern:
                continue  # an empty pattern would match every write
            try:
                rules.append(("denylisted term", re.compile(pattern, re.IGNORECASE)))
            except re.error as error:
                print(f"check-content: skipping invalid denylist pattern in {path}: {error}", file=sys.stderr)
    return rules


def rules_for(rel: str, denylist: list) -> list:
    privacy = [r for r in PRIVACY if not (r[0] == "email address" and rel.startswith(EMAIL_EXEMPT_PREFIXES))]
    return privacy + SECRETS + STAMPS + denylist


def scan_text(text: str, rules: list):
    """Yield (line number, rule name, excerpt) for every match."""
    for name, pattern, *accept in rules:
        for match in pattern.finditer(text):
            if accept and not accept[0](match):
                continue
            line = text.count("\n", 0, match.start()) + 1
            excerpt = match.group(0)
            if name in SECRET_NAMES:
                excerpt = excerpt[:4] + "..."  # never repeat a secret in a log
            yield line, name, excerpt


def scan_file(rel: str, text: str | None, denylist: list) -> list:
    if rel in EXEMPT or rel in ALLOW or text is None:
        return []
    return sorted({f for f in scan_text(text, rules_for(rel, denylist))
                   if not (f[1] == "email address" and f[2].lower() in ALLOWED_EMAILS)} | set(scan_transcript(rel, text)))


def decode(data: bytes) -> str | None:
    """Text, or None for a binary file."""
    if b"\0" in data[:8192]:
        return None
    return data.decode("utf-8", errors="replace")


def git(*args, cwd=ROOT):
    return subprocess.run(["git", *args], cwd=cwd, capture_output=True, check=False)


def report(findings, stream=sys.stderr):
    for rel, line, name, excerpt in findings:
        where = f"{rel}:{line}" if line else rel
        print(f"  {where}: {name}" + (f": {excerpt!r}" if excerpt else ""), file=stream)


def collect(staged: bool = False) -> list:
    """Every finding in the files git would commit: (path, line, rule, excerpt)."""
    denylist = load_denylist() + load_identity()
    if staged:
        names = git("diff", "--cached", "--name-only", "-z", "--diff-filter=ACMR").stdout.decode().split("\0")
    else:
        names = git("ls-files", "-z", "--cached", "--others", "--exclude-standard").stdout.decode().split("\0")
    findings = []
    for rel in filter(None, names):
        if staged:
            data = git("show", f":{rel}").stdout
        else:
            path = ROOT / rel
            if not path.is_file():
                continue  # deleted in the working tree
            data = path.read_bytes()
        findings += [(rel, *f) for f in scan_file(rel, decode(data), denylist)]
    return findings


def check_repo(staged: bool) -> int:
    findings = collect(staged)
    if findings:
        print("Content check FAILED: private or confidential material in files git would commit:", file=sys.stderr)
        report(findings)
        print("Remove or generalize it (CLAUDE.md, 'Recording guidance, and keeping personal data out'). A secret "
              "that reached a tracked file must be rotated, so tell the user. A reviewed false positive goes into "
              "ALLOW in .github/scripts/check-content.py with a reason.", file=sys.stderr)
        return 1
    print("Content check passed.")
    return 0


def check_hook() -> int:
    """PreToolUse: block a Write/Edit/MultiEdit/NotebookEdit that would put a match into a tracked file."""
    event = json.loads(sys.stdin.buffer.read().decode("utf-8"))
    tool_input = event.get("tool_input") or {}
    target = tool_input.get("file_path") or tool_input.get("notebook_path")
    if not target:
        return 0
    path = Path(event.get("cwd") or os.getcwd(), target).resolve()
    parent = next((p for p in path.parents if p.is_dir()), None)
    top = git("rev-parse", "--show-toplevel", cwd=parent).stdout.decode().strip() if parent else ""
    if not top:
        return 0  # not in a git repository: the session scratchpad, Claude's memory
    repo = Path(top).resolve()
    if repo != ROOT:
        return 0  # another repository: its own rules apply
    rel = path.relative_to(repo).as_posix()
    if git("check-ignore", "-q", "--no-index", rel, cwd=repo).returncode == 0:
        return 0  # gitignored (scratch docs, local settings): private material may live there
    texts = [tool_input.get(key) for key in ("content", "new_string", "new_source")]
    texts += [edit.get("new_string") for edit in tool_input.get("edits") or [] if isinstance(edit, dict)]
    text = "\n".join(t for t in texts if isinstance(t, str))
    findings = scan_file(rel, text, load_denylist() + load_identity())
    if not findings:
        return 0
    print(f"Blocked by the content check: this write would put private or confidential material into the tracked "
          f"file {rel}:", file=sys.stderr)
    report([(rel, *f) for f in findings])
    print("Don't write it to a tracked file. Use a repo-relative path, an environment variable (%LOCALAPPDATA%, "
          "$HOME) or a generic location (~/.ssh/config, 'the session scratchpad'); a placeholder (<token>, <host>) "
          "or an environment variable for a secret; keep private material in a "
          "gitignored folder. If you believe it's a false positive, stop and ask the user; a reviewed exception goes "
          "into ALLOW in .github/scripts/check-content.py.", file=sys.stderr)
    return 2


if __name__ == "__main__":
    # Windows' console default (cp1252) can't encode most non-ASCII excerpts: printing the report would raise, the
    # hook would exit 1 instead of 2, and a non-2 exit does NOT block the write. Never let reporting fail.
    for stream in (sys.stdout, sys.stderr):
        stream.reconfigure(encoding="utf-8", errors="backslashreplace")
    if "--hook" in sys.argv[1:]:
        sys.exit(check_hook())
    sys.exit(check_repo(staged="--staged" in sys.argv[1:]))
