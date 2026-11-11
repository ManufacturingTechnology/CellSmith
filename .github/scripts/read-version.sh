#!/usr/bin/env bash
# Print CellSmith's single source-of-truth version, validated as semver.
#
#     version=$(bash .github/scripts/read-version.sh)   # -> 0.1.0-alpha.1
#
# WHY THIS EXISTS
#     ci.yml and release.yml each parsed src/__version__.py with
#
#         version=$(grep -oP '"\K[^"]+' src/__version__.py)
#
#     which is UNANCHORED. The file opens with a module DOCSTRING, so the third
#     quote of `"""` starts a match and the docstring's first line comes out
#     ahead of the version. The first PR into a release/X.Y branch died on it:
#
#         __version__ 'Single source of truth for the application version.
#         0.1.0-alpha.1' is not valid semver
#
#     i.e. the guard had never actually worked, and BOTH copies were wrong in
#     the same way — which is the argument for one shared reader instead of a
#     snippet pasted per workflow. (The build scripts — build.bat, makefile,
#     packaging/debian/make_deb.sh — read the value by exec'ing the file and
#     printing ns['__version__'], so they never had this bug.)
#
# Diagnostics go to stderr; ONLY the version goes to stdout, so the caller can
# use $(...) safely.
set -uo pipefail

ROOT="${1:-$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)}"
FILE="$ROOT/src/__version__.py"

die() { echo "::error::$1" >&2; exit 1; }

[ -f "$FILE" ] || die "version file not found: $FILE"

# Anchored to the start of a line, so docstring quotes cannot match.
#
# ⚠️ POSIX `sed`, deliberately NOT `grep -oP`: PCRE grep is not portable. Git Bash
# on Windows refuses it outright — "grep: -P supports only unibyte and UTF-8
# locales" — which would make this reader untestable on a dev machine even though
# it works on the runner. BRE costs nothing here.
mapfile -t matches < <(
    sed -n 's/^__version__[[:space:]]*=[[:space:]]*"\([^"]*\)".*/\1/p' "$FILE")

case "${#matches[@]}" in
    0) die "no '__version__ = \"...\"' assignment found in $FILE" ;;
    1) ;;
    # Ambiguity is a hard error, not a first-match-wins: two assignments mean
    # the build scripts (which exec the file, so LAST wins) and this reader
    # (first wins) would disagree about the version being shipped.
    *) die "expected exactly one __version__ assignment in $FILE, found ${#matches[@]}: ${matches[*]}" ;;
esac

version="${matches[0]}"
if [[ ! "$version" =~ ^[0-9]+\.[0-9]+\.[0-9]+(-[0-9A-Za-z.-]+)?$ ]]; then
    die "__version__ '$version' is not valid semver (expected MAJOR.MINOR.PATCH[-PRERELEASE])"
fi

printf '%s\n' "$version"
