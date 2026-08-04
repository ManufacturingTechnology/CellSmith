#!/usr/bin/env bash
# Build the CellSmith .deb from an already-built onedir payload in dist/CellSmith.
#
# Usage (from the repo root, AFTER `make build` has produced dist/CellSmith):
#     packaging/debian/make_deb.sh [OUTPUT_DIR]
# Output:
#     dist/cellsmith_<debver>_amd64.deb
#
# WHY A HAND-ROLLED dpkg-deb AND NOT dh_make/debhelper
#     This is a self-contained PyInstaller onedir tree, not a source package built
#     from a tarball. There is nothing for debhelper's build/install phases to do:
#     the payload already exists and merely needs laying out under /opt plus the
#     desktop-integration files. `dpkg-deb --build` on a staged tree is the whole
#     job, needs no build-dependency chain, and works from any distro.
#
# LAYOUT
#     /opt/cellsmith/                              the onedir payload, verbatim
#     /usr/bin/cellsmith                           -> /opt/cellsmith/CellSmith
#     /usr/share/applications/cellsmith.desktop
#     /usr/share/icons/hicolor/256x256/apps/cellsmith.png
#     /usr/share/doc/cellsmith/{copyright,THIRD-PARTY-NOTICES.md,changelog.gz}
#
#     /opt is correct for a vendored-runtime application (FHS 3.0 s3.13: "add-on
#     application software packages"); /usr/lib would imply distro-managed
#     libraries. The /usr/bin symlink is safe because PyInstaller resolves
#     sys.executable through /proc/self/exe, so worker subprocesses re-launch the
#     REAL binary, not the symlink -- asserted below.
#
# See docs/src/AI/Reference/packaging.md.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
DEBIAN_DIR="$ROOT/packaging/debian"
DIST="$ROOT/dist"
PAYLOAD="$DIST/CellSmith"
OUT_DIR="${1:-$DIST}"

PKG=cellsmith
ARCH=amd64
MAINTAINER="${DEB_MAINTAINER:-AMT <mmccormick@amtonline.org>}"

# Interpreter used for the version read and the icon extraction. The icon step
# needs Pillow, so the makefile passes the CellSmithEnv python; a bare `python3`
# is fine for everything else.
PY="${PYTHON:-python3}"
command -v "$PY" >/dev/null 2>&1 || PY=python

# Runtime system libraries. X11/OpenGL libs are NEVER bundled by PyInstaller --
# they must match the host display stack -- so they are real Depends. Sourced from
# the verified Debian set in docs/src/AI/Reference/packaging.md.
#
# `a | b` alternatives cover the Debian 13 / Ubuntu 24.04 t64 transition renames;
# without them the package refuses to install on the other side of the rename.
DEPENDS="libc6, \
libxcb1, libxcb-cursor0, libxcb-icccm4, libxcb-image0, libxcb-keysyms1, \
libxcb-randr0, libxcb-render-util0, libxcb-shape0, libxcb-xfixes0, libxcb-xkb1, \
libxkbcommon-x11-0, libgl1, libegl1, libfontconfig1, libdbus-1-3, libxrender1, \
libxext6, libsm6, libice6, libglib2.0-0t64 | libglib2.0-0, \
libwayland-client0, libwayland-cursor0, libwayland-egl1, libx11-xcb1, \
libxcomposite1, libxdamage1, libxrandr2, libxtst6, libxcursor1, libxi6, \
libxinerama1"

# ---------------------------------------------------------------- preconditions
for tool in dpkg-deb fakeroot; do
    command -v "$tool" >/dev/null 2>&1 || {
        echo "ERROR: $tool not found. On Debian/Ubuntu: apt-get install -y dpkg fakeroot" >&2
        exit 1
    }
done
[ -x "$PAYLOAD/CellSmith" ] || {
    echo "ERROR: $PAYLOAD/CellSmith not found. Run \`make build\` first." >&2
    exit 1
}

# ---------------------------------------------------------------- version
# Read the single source of truth. `exec`, not import, so no package deps.
VERSION="$("$PY" -c "ns={}; exec(open('$ROOT/src/__version__.py').read(), ns); print(ns['__version__'])")"
[ -n "$VERSION" ] || { echo "ERROR: could not read __version__" >&2; exit 1; }

# ⭐ SEMVER -> DEBIAN VERSION. A semver prerelease MUST map `-` to `~`:
#   0.1.0-alpha.1  as a Debian version parses `alpha.1` as the *debian revision*,
#                  which sorts AFTER plain 0.1.0 -- i.e. dpkg would consider the
#                  prerelease NEWER than the final release.
#   0.1.0~alpha.1  sorts BEFORE 0.1.0, because `~` sorts before everything,
#                  including the empty string. This is the documented mechanism
#                  for prereleases in Debian Policy 5.6.12.
DEBVER="${VERSION/-/\~}"

STAGE="$(mktemp -d)"
trap 'rm -rf "$STAGE"' EXIT

# Template substitution. NOT `sed`: the Depends list contains `|` (alternatives)
# and the maintainer contains `<`/`>`/`@`, so every plausible sed delimiter
# appears in some value -- the first version of this script died with
# "unknown option to `s'". Literal replacement in Python has no such hazard.
render() {
    local template="$1" output="$2"; shift 2
    "$PY" - "$template" "$output" "$@" <<'PYEOF'
import sys
template, output = sys.argv[1], sys.argv[2]
with open(template, encoding="utf-8") as fh:
    body = fh.read()
for pair in sys.argv[3:]:
    key, _, value = pair.partition("=")
    body = body.replace(key, value)
leftover = [w for w in ("@VERSION@", "@INSTALLED_SIZE@", "@MAINTAINER@",
                        "@DEPENDS@", "@YEAR@") if w in body]
if leftover:
    sys.exit(f"ERROR: unsubstituted placeholders in {output}: {leftover}")
with open(output, "w", encoding="utf-8", newline="\n") as fh:
    fh.write(body)
PYEOF
}

# ---------------------------------------------------------------- stage the tree
install -d -m 0755 "$STAGE/opt/cellsmith"
cp -a "$PAYLOAD/." "$STAGE/opt/cellsmith/"
chmod 0755 "$STAGE/opt/cellsmith/CellSmith"

install -d -m 0755 "$STAGE/usr/bin"
ln -s /opt/cellsmith/CellSmith "$STAGE/usr/bin/$PKG"

install -d -m 0755 "$STAGE/usr/share/applications"
install -m 0644 "$DEBIAN_DIR/cellsmith.desktop" \
    "$STAGE/usr/share/applications/$PKG.desktop"

# Icon: extract the largest frame from the checked-in multi-resolution ICO rather
# than shipping a second source of truth for the artwork.
install -d -m 0755 "$STAGE/usr/share/icons/hicolor/256x256/apps"
"$PY" "$DEBIAN_DIR/ico_to_png.py" "$ROOT/packaging/cellsmith.ico" \
      "$STAGE/usr/share/icons/hicolor/256x256/apps/$PKG.png"

# ---------------------------------------------------------------- docs
install -d -m 0755 "$STAGE/usr/share/doc/$PKG"
render "$DEBIAN_DIR/copyright.in" "$STAGE/usr/share/doc/$PKG/copyright" \
    "@YEAR@=$(date -u +%Y)" "@MAINTAINER@=$MAINTAINER"
chmod 0644 "$STAGE/usr/share/doc/$PKG/copyright"
# The generated attributions travel with the payload; surface them where Debian
# users look. (Copy, not symlink: /opt is not guaranteed present at unpack order.)
if [ -f "$PAYLOAD/_internal/THIRD-PARTY-NOTICES.md" ]; then
    install -m 0644 "$PAYLOAD/_internal/THIRD-PARTY-NOTICES.md" \
        "$STAGE/usr/share/doc/$PKG/THIRD-PARTY-NOTICES.md"
else
    echo "WARNING: _internal/THIRD-PARTY-NOTICES.md missing from the payload" >&2
fi
printf '%s (%s) unstable; urgency=medium\n\n  * Release %s. See the GitHub release notes.\n\n -- %s  %s\n' \
    "$PKG" "$DEBVER" "$VERSION" "$MAINTAINER" "$(date -uR)" \
    | gzip -9n > "$STAGE/usr/share/doc/$PKG/changelog.gz"
chmod 0644 "$STAGE/usr/share/doc/$PKG/changelog.gz"

# ---------------------------------------------------------------- control
install -d -m 0755 "$STAGE/DEBIAN"
INSTALLED_SIZE="$(du -sk "$STAGE" | cut -f1)"
render "$DEBIAN_DIR/control.in" "$STAGE/DEBIAN/control" \
    "@VERSION@=$DEBVER" "@INSTALLED_SIZE@=$INSTALLED_SIZE" \
    "@MAINTAINER@=$MAINTAINER" "@DEPENDS@=$DEPENDS"
chmod 0644 "$STAGE/DEBIAN/control"

# Refresh the desktop/icon caches. Non-fatal: a headless or minimal target may not
# have either tool, and the package is still perfectly usable from the CLI.
cat > "$STAGE/DEBIAN/postinst" <<'SH'
#!/bin/sh
set -e
if [ "$1" = configure ]; then
    command -v update-desktop-database >/dev/null 2>&1 && \
        update-desktop-database -q /usr/share/applications || true
    command -v gtk-update-icon-cache >/dev/null 2>&1 && \
        gtk-update-icon-cache -q -t -f /usr/share/icons/hicolor || true
fi
exit 0
SH
cat > "$STAGE/DEBIAN/postrm" <<'SH'
#!/bin/sh
set -e
if [ "$1" = remove ] || [ "$1" = purge ]; then
    command -v update-desktop-database >/dev/null 2>&1 && \
        update-desktop-database -q /usr/share/applications || true
    command -v gtk-update-icon-cache >/dev/null 2>&1 && \
        gtk-update-icon-cache -q -t -f /usr/share/icons/hicolor || true
fi
exit 0
SH
chmod 0755 "$STAGE/DEBIAN/postinst" "$STAGE/DEBIAN/postrm"

# ---------------------------------------------------------------- build
mkdir -p "$OUT_DIR"
DEB="$OUT_DIR/${PKG}_${DEBVER}_${ARCH}.deb"
# xz is what Debian uses for large payloads; -Sextreme is not worth the minutes on
# an already-compressed ~1 GB tree.
fakeroot dpkg-deb --build -Zxz -z6 "$STAGE" "$DEB" >/dev/null
echo "Built $DEB ($(du -h "$DEB" | cut -f1))"

# ---------------------------------------------------------------- self-checks
# Cheap assertions that catch the ways this silently goes wrong.
fail=0
check() { if [ "$1" = 0 ]; then echo "  ok   $2"; else echo "  FAIL $2" >&2; fail=1; fi; }

# ⛔ TWO TRAPS HERE, BOTH HIT ON THE FIRST REAL (non-synthetic) PAYLOAD. Do not
# rewrite these checks as `cmd; check $?` over a pipe.
#
# 1. SIGPIPE. This block used to be `printf '%s\n' "$contents" | grep -q PAT`.
#    `grep -q` exits at the FIRST match, closing the pipe; the real payload's
#    file list is ~200 kB, well past the 64 kB pipe buffer, so printf was still
#    writing and died with `printf: write error: Broken pipe`. ⭐ Note the shape
#    of that bug: it fires only when the check SUCCEEDS (an early match is what
#    closes the pipe) and only when the listing is big enough to block — which is
#    exactly why it passed against a small synthetic payload in the WSL sandbox
#    and failed on the 2111-file build. Grep a FILE; no pipe, no SIGPIPE.
#
# 2. `set -e` vs `check $?`. With `-e`, a bare `cmd; check $?` aborts the script
#    the moment cmd fails, so check() never runs: `fail`, the FAIL lines, and the
#    "self-checks failed" summary below were all unreachable, and any failure
#    surfaced as a bare `make: *** Error 1`. Every check must therefore be
#    written so its own failure is TESTED (if/then/else), never bare.
CONTENTS="$STAGE/.deb-contents.txt"   # inside STAGE, so the EXIT trap cleans it
dpkg-deb --contents "$DEB" > "$CONTENTS"

if dpkg-deb --info "$DEB" >/dev/null 2>&1
    then check 0 "the archive is a readable .deb"
    else check 1 "the archive is a readable .deb"; fi

has() {  # has <pattern> <label> -- never returns non-zero; see trap 2 above
    if grep -q -- "$1" "$CONTENTS"; then check 0 "$2"; else check 1 "$2"; fi
}

has ' ./opt/cellsmith/CellSmith$'                      "payload launcher present"
has './usr/bin/cellsmith -> /opt/cellsmith/CellSmith'  "/usr/bin symlink present"
has './usr/share/applications/cellsmith.desktop$'      "desktop entry present"
has 'cellsmith.png$'                                   "icon present"
has './usr/share/doc/cellsmith/copyright$'             "copyright present"
has 'THIRD-PARTY-NOTICES.md$'                          "third-party notices present"
# Qt plugins: the silent-failure fingerprint from packaging.md -- Qt's lib/ present
# but plugins/ absent. Linux nests them under PySide6/Qt/, Windows directly under
# PySide6/; match loosely so a PySide6 layout change fails for the right reason.
has '_internal/PySide6/.*plugins/' "Qt plugins collected (not the empty-plugins failure)"
# The GPL readline exclusion, asserted on the SHIPPED artifact too: the payload
# verifier only ever sees dist/CellSmith, and the .deb is a separate distribution.
# Anchored to the FILENAME, mirroring verify-payload.sh's patterns -- a loose
# match on "history" would hit unrelated package files.
if grep -qE '/(readline[^/]*\.(so|pyd)[^/]*|lib(readline|history)[^/]*)$' "$CONTENTS"
    then check 1 "no GPL readline in the .deb"
    else check 0 "no GPL readline in the .deb"; fi
case "$DEBVER" in *-*) check 1 "debian version has no bare '-' (prerelease must use '~')";; *) check 0 "debian version uses '~' for any prerelease";; esac

if command -v lintian >/dev/null 2>&1; then
    echo "lintian (informational, not gating):"
    lintian --no-tag-display-limit "$DEB" 2>&1 | sed 's/^/    /' || true
fi

[ "$fail" = 0 ] || { echo "ERROR: .deb self-checks failed" >&2; exit 1; }
echo "All .deb self-checks passed."
