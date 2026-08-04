"""Generate THIRD-PARTY-NOTICES.md for the frozen distributable.

WHY THIS IS GENERATED, NOT WRITTEN BY HAND
    A hand-maintained notices file is wrong the moment anyone runs `pip install`.
    This reads the licenses out of the live environment every build, so the file
    cannot drift from what is actually shipped.

WHAT IT COVERS
    * pip distributions      — `importlib.metadata`: name, version, license
                               expression / classifiers, and the license TEXT
                               out of `*.dist-info/licenses/` where the wheel
                               ships one.
    * conda packages         — `<env>/conda-meta/*.json` `license` field. This is
                               the ONLY source for OCCT / pythonocc / freetype /
                               libiconv, none of which have a pip wheel. conda
                               does NOT extract license texts into the prefix, so
                               their texts come from `packaging/licenses/`.
    * curated native entries — Qt, OCCT, FreeImage, freetype: components with
                               obligations that metadata cannot express (a
                               dual-license ELECTION, a required notice, a source
                               offer). See `_CURATED`.

INVOKED FROM `packaging/cellsmith.spec` so Windows (`build.bat`) and Linux
(`make build`) get it from ONE code path — neither build script calls it, so
neither can forget it. Also runnable standalone for inspection:

    python packaging/gen_third_party_notices.py --out build/THIRD-PARTY-NOTICES.md

Exit status is always 0: a notices file is not worth failing a build over. Real
problems are reported as `NOTICE-WARN:` lines on stderr and as a **Gaps** section
in the document itself, so an incomplete file is visibly incomplete rather than
quietly wrong.

Analysis + obligations: `docs/src/AI/Reference/licensing.md`.
"""

from __future__ import annotations

import argparse
import glob
import json
import os
import re
import sys
from importlib import metadata
from typing import Dict, List, Optional, Tuple

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, os.pardir))
LICENSE_DIR = os.path.join(HERE, "licenses")

# --------------------------------------------------------------------------
# FreeImage is offered under `GPL-2.0-or-later OR GPL-3.0-or-later OR FIPL`
# (https://freeimage.sourceforge.io/license.html). A distributor must ELECT one.
# Electing FIPL — an MPL-1.1-derived, file-level weak-copyleft license — is what
# keeps the bundle consistent with CellSmith's Apache-2.0 outbound license; the
# GPL options would not be.
#
# Set to None to state explicitly that no election has been made (the generator
# then warns and records it as a gap). "FIPL" is the only supported election.
#
# ELECTED: FIPL, by the project maintainers on 2026-08-04. FreeImage is shipped
# UNMODIFIED (it arrives only as a load-time dependency of OCCT's TKService), so
# FIPL's source-availability clause -- which reaches only FreeImage files that
# WE modify -- imposes nothing beyond reproducing the license text.
FREEIMAGE_ELECTION: Optional[str] = "FIPL"

# freetype is `GPL-2.0-only OR FTL`; the FTL requires credit in documentation.
FREETYPE_ELECTION = "FTL"

# Where a recipient can obtain the complete corresponding source of the LGPL
# libraries we ship, satisfying LGPL-2.1 s6 / LGPL-3.0 s4's source requirement.
SOURCE_OFFER_CONTACT = "the CellSmith maintainers (see the repository README)"

# --------------------------------------------------------------------------
# Native/curated components. `licenses` names files in packaging/licenses/.
_CURATED: List[Dict] = [
    {
        "name": "Qt 6",
        "via": "PySide6 / shiboken6",
        "spdx": "LGPL-3.0-only",
        "licenses": ["LGPL-3.0.txt", "GPL-3.0.txt"],
        "note": (
            "CellSmith uses the Qt toolkit under the **GNU Lesser General Public "
            "License version 3**. Qt is not modified. Qt is linked DYNAMICALLY: every "
            "Qt library ships as a separate file under `_internal/` (`Qt6*.dll` / "
            "`libQt6*.so*` plus `PySide6/plugins/`), so a recipient may replace those "
            "files with their own build of the same Qt version and re-run the "
            "application — this is the relink right LGPL-3.0 s4(d)(1) requires, and no "
            "technical measure prevents it.\n\n"
            "LGPL-3.0 incorporates the terms of GPL-3.0 by reference; both texts are "
            "reproduced below."
        ),
    },
    {
        "name": "Open CASCADE Technology (OCCT)",
        "via": "pythonocc-core",
        "spdx": "LGPL-2.1-only WITH the Open CASCADE exception",
        "licenses": ["LGPL-2.1.txt", "OCCT-LGPL-EXCEPTION.txt"],
        # This paragraph is the OCCT exception's own condition, verbatim in
        # substance: "provided that you give prominent notice in supporting
        # documentation to this code that it makes use of or is based on
        # facilities provided by the Open CASCADE Technology software."
        "note": (
            "**This software makes use of, and is based on, facilities provided by the "
            "Open CASCADE Technology software.**\n\n"
            "OCCT is used under the GNU Lesser General Public License version 2.1 "
            "together with the Open CASCADE exception (both reproduced below). OCCT is "
            "not modified, and is linked dynamically as separate `TK*.dll` / "
            "`libTK*.so*` files under `_internal/`."
        ),
    },
    {
        "name": "pythonocc-core",
        "via": "conda-forge",
        "spdx": "LGPL-3.0-or-later",
        "licenses": ["LGPL-3.0.txt", "GPL-3.0.txt"],
        "note": (
            "The Python bindings to OCCT, used unmodified under the GNU Lesser General "
            "Public License version 3 or later, as separate extension modules "
            "(`OCC/**/*.pyd` / `*.so`) under `_internal/`."
        ),
    },
    {
        "name": "GNU libiconv",
        "via": "conda-forge (OCCT dependency)",
        "spdx": "LGPL-2.1-only",
        "licenses": ["LGPL-2.1.txt"],
        "note": (
            "Used unmodified, dynamically linked as a separate library file under "
            "`_internal/`."
        ),
    },
    {
        "name": "FreeImage",
        "via": "conda-forge (OCCT `TKService` dependency)",
        "spdx": "GPL-2.0-or-later OR GPL-3.0-or-later OR FreeImage-1.0",
        "licenses": ["FreeImage-FIPL.txt"],
        "note": None,        # filled in by _freeimage_note()
        "id": "freeimage",
    },
    {
        "name": "The FreeType Project",
        "via": "conda-forge / VTK",
        "spdx": "FTL OR GPL-2.0-only",
        "licenses": ["FTL.txt"],
        "note": (
            f"Used under the **FreeType Project License (FTL)**, the elected option of "
            f"its dual license. Required credit: *Portions of this software are "
            f"copyright (c) The FreeType Project (https://www.freetype.org). All rights "
            f"reserved.* (election: {FREETYPE_ELECTION})"
        ),
    },
]

# Build tooling. Not shipped inside the app payload, but its own code IS embedded
# in artefacts we hand out (PyInstaller's bootloader becomes CellSmith.exe; Inno's
# stub becomes the setup.exe), so both belong in the record.
_BUILD_TOOLS: List[Dict] = [
    {
        "name": "PyInstaller",
        "spdx": "GPL-2.0-or-later WITH a bootloader exception",
        "licenses": [],
        "note": (
            "The frozen executable embeds PyInstaller's bootloader. PyInstaller is "
            "licensed GPL-2.0-or-later **with a special exception which allows to use "
            "PyInstaller to build and distribute non-free programs (including "
            "commercial ones)**, so this imposes no terms on CellSmith's own code."
        ),
    },
    {
        "name": "Inno Setup",
        "spdx": "Inno Setup License (zlib-style, permissive)",
        "licenses": ["InnoSetup.txt"],
        "note": (
            "The Windows installer (`CellSmith-*-setup.exe`) embeds Inno Setup's "
            "setup stub. Copyright (C) 1997-2026 Jordan Russell; portions copyright "
            "(C) 2000-2026 Martijn Laan; https://jrsoftware.org/. Its licence permits "
            "commercial use and requires only that copyright notices and web site "
            "addresses already present in the binary be retained — CellSmith does not "
            "post-process the installer, so they are. An acknowledgement is stated "
            "here because the licence says one *would be appreciated* (condition 3), "
            "not because it is required."
        ),
    },
]

# conda packages we must attribute even though metadata alone is thin. Anything
# NOT listed here still gets a metadata-only row.
_CONDA_INTEREST = {
    "occt", "pythonocc-core", "freeimage", "freetype", "libfreetype",
    "libfreetype6", "libiconv", "libintl", "libraw", "mkl", "onemkl-license",
    "libopenblas", "libblas", "libcblas", "liblapack", "numpy", "pydantic",
    "pyyaml", "tbb", "sqlite", "libpng", "libtiff", "libwebp", "openjpeg",
    "lcms2", "zlib", "zstd", "bzip2", "libexpat", "libxml2", "openssl",
    "libjpeg-turbo", "jpeg",
}

# SPDX ids / license strings that must never appear without a deliberate
# decision. A hit becomes a NOTICE-WARN and a Gaps entry.
_NEEDS_DECISION = (
    "GPL-2.0-only", "GPL-2.0-or-later", "GPL-3.0-only", "GPL-3.0-or-later",
    "AGPL", "LicenseRef-IntelSimplified", "SSPL", "BUSL", "Commons-Clause",
)
# ...unless the component is one we have explicitly resolved above.
_RESOLVED = {"freeimage", "freetype", "libfreetype", "libfreetype6",
             "pythonocc-core", "occt", "libiconv"}

# --------------------------------------------------------------------------
# Three further ways a `_NEEDS_DECISION` hit can be resolved. All THREE are
# rendered into the notices (see `render()`), never silently suppressed — the
# point is that a reader can audit the reasoning, and that a package which
# arrives later for a *different* reason still shows up as a gap.
#
# Added 2026-08-04 after `test-linux` went red: conda's Linux toolchain drags in
# eight GPL-3.0 rows that the Windows env simply does not have, so the substring
# check above had never fired before CI ran on Linux.

# 1. BUILD-ONLY — present in the build environment, never in `_internal/`.
#    conda-meta describes the ENV, not the payload, so this distinction has to be
#    made by hand.
_BUILD_ONLY: Dict[str, str] = {
    "ld_impl_linux-64": (
        "GNU `ld` from binutils — the *linker*, used only while conda builds and "
        "installs packages. PyInstaller does not link anything and never copies it "
        "into `_internal/`, so it is not distributed and its GPL-3.0 terms do not "
        "reach the payload."
    ),
}

# 2. EXCLUDED FROM THE PAYLOAD — genuinely GPL with no exception, so it is kept
#    out of the build rather than argued about. Enforced in two places:
#    `packaging/cellsmith.spec` (`excludes=`) and `.github/scripts/verify-payload.sh`.
_EXCLUDED_FROM_PAYLOAD: Dict[str, str] = {
    "readline": (
        "GNU Readline is **GPL-3.0-only with no linking exception**, which would be "
        "inconsistent with CellSmith's Apache-2.0 terms if it were distributed. "
        "CellSmith is a GUI application with no REPL and imports it nowhere, so it "
        "is kept out of the distributable in two places: the PyInstaller spec lists "
        "`readline` in `excludes=` (module graph) **and** filters `readline`, "
        "`libreadline` and `libhistory` out of both `a.binaries` and `a.datas` — the "
        "two lists the payload is actually assembled from, neither of which "
        "`excludes=` reaches — while "
        "`.github/scripts/verify-payload.sh` asserts that no `readline` extension "
        "module and no `libreadline`/`libhistory` library appears in the frozen "
        "payload. It is a build-environment package only."
    ),
}

# 3. A LINKING / RUNTIME EXCEPTION on the license itself. SPDX spells these
#    `<license> WITH <exception-id>`, and the exception is precisely the grant that
#    makes the component usable from non-GPL code — treating it as a gap is a
#    false positive of the substring match.
#
#    The case that matters here is the six GCC runtime libraries (libgcc, libgcc-ng,
#    libgomp, libstdcxx, libgfortran, libgfortran5), all `GPL-3.0-only WITH
#    GCC-exception-3.1`. The GCC Runtime Library Exception grants "unlimited
#    permission to propagate" the runtime code as part of a compiled program
#    regardless of that program's license — every non-GPL binary compiled by GCC on
#    Linux relies on it.
#    https://www.gnu.org/licenses/gcc-exception-3.1.html
_EXCEPTION_RE = re.compile(r"\bWITH\s+([A-Za-z0-9.\-]*[Ee]xception[A-Za-z0-9.\-]*)")


def _spdx_exception(license_str: str) -> Optional[str]:
    """The SPDX exception id in `license_str`, or None."""
    m = _EXCEPTION_RE.search(license_str or "")
    return m.group(1) if m else None


def unresolved_reason(row: Dict) -> Optional[str]:
    """Why this conda row is an UNRESOLVED licensing item, or None if it is fine.

    ⭐ ONE predicate, deliberately. `render()`'s Gaps section and
    `tests/test_third_party_notices.py`'s rot guard both call it, so the shipped
    notices and the test can never disagree about what counts as a gap — they used
    to duplicate the rule, and a fix to one would have left the other lying.
    """
    name = row.get("name") or ""
    lic = row.get("license") or ""
    if name in _RESOLVED or name in _BUILD_ONLY or name in _EXCLUDED_FROM_PAYLOAD:
        return None
    if not any(tok in lic for tok in _NEEDS_DECISION):
        return None
    if _spdx_exception(lic):
        return None
    return (f"conda package {name} {row.get('version', '?')} is licensed "
            f"'{lic}' - this needs a deliberate decision before shipping "
            f"(see docs/src/AI/Reference/licensing.md)")


WARN = "NOTICE-WARN: "


def _warn(msg: str, sink: List[str]) -> None:
    sink.append(msg)
    print(WARN + msg, file=sys.stderr)


def _freeimage_note(gaps: List[str]) -> str:
    if FREEIMAGE_ELECTION == "FIPL":
        return (
            "FreeImage is offered under a choice of the GNU General Public License "
            "(v2 or v3) or the **FreeImage Public License (FIPL)**. "
            "**CellSmith elects the FreeImage Public License version 1.0**, "
            "reproduced below. FreeImage is used unmodified and is linked dynamically "
            "as a separate library file under `_internal/`; it is present only as a "
            "load-time dependency of OCCT's `TKService` library."
        )
    _warn(
        "FreeImage is bundled but FREEIMAGE_ELECTION is None - no license has been "
        "elected. Its default reading includes GPLv2/GPLv3, which is inconsistent "
        "with CellSmith's Apache-2.0 terms. Set FREEIMAGE_ELECTION = 'FIPL' in "
        "packaging/gen_third_party_notices.py, or stop shipping FreeImage.",
        gaps,
    )
    return (
        "FreeImage is offered under a choice of the GNU General Public License "
        "(v2 or v3) or the FreeImage Public License. "
        "**NO ELECTION HAS BEEN RECORDED — see the Gaps section.** "
        "The FreeImage Public License text is reproduced below for reference."
    )


# --------------------------------------------------------------------------
def _read(path: str) -> Optional[str]:
    try:
        with open(path, encoding="utf-8", errors="replace") as fh:
            return fh.read()
    except OSError:
        return None


def _license_text(fname: str, gaps: List[str]) -> Tuple[str, Optional[str]]:
    """Return (display name, verbatim text or None) for packaging/licenses/<f>."""
    text = _read(os.path.join(LICENSE_DIR, fname))
    if text is None:
        _warn(f"missing license text packaging/licenses/{fname} - the notices file "
              f"will reference it without reproducing it", gaps)
    return fname, text


def collect_pip() -> List[Dict]:
    out = []
    for dist in metadata.distributions():
        md = dist.metadata
        name = md["Name"]
        if not name:
            continue
        lic = (md.get("License-Expression") or md.get("License") or "").strip()
        # Some projects dump the whole license text into the License field.
        inline = None
        if len(lic) > 120:
            inline, lic = lic, ""
        classifiers = [v.replace("License :: ", "").replace("OSI Approved :: ", "")
                       for k, v in md.items()
                       if k == "Classifier" and v.startswith("License ::")]
        texts = {}
        for f in (dist.files or []):
            p = str(f).replace("\\", "/")
            if ".dist-info/" not in p.lower():
                continue          # only the wheel's own metadata, not its payload
            leaf = p.rsplit("/", 1)[-1]
            if not ("/licenses/" in p.lower()
                    or leaf.lower().startswith(("license", "licence", "copying",
                                                "notice"))):
                continue
            # `locate_file` resolves against the distribution's install root and
            # is the only supported way to reach a listed file by absolute path.
            body = _read(str(dist.locate_file(f)))
            if body:
                texts[leaf] = body
        if inline and not texts:
            texts["(from package metadata)"] = inline
        out.append({
            "name": name, "version": md["Version"], "license": lic,
            "classifiers": classifiers, "texts": texts,
        })
    out.sort(key=lambda d: d["name"].lower())
    return out


def collect_conda(prefix: str) -> List[Dict]:
    out = []
    meta = os.path.join(prefix, "conda-meta")
    if not os.path.isdir(meta):
        return out
    for fn in sorted(glob.glob(os.path.join(meta, "*.json"))):
        try:
            with open(fn, encoding="utf-8") as fh:
                d = json.load(fh)
        except (OSError, ValueError):
            continue
        out.append({"name": d.get("name") or "?", "version": d.get("version") or "?",
                    "license": d.get("license") or "", "build": d.get("build") or ""})
    out.sort(key=lambda d: d["name"].lower())
    return out


def _render_resolved_copyleft(a, conda_rows: List[Dict]) -> None:
    """Document every copyleft row that `unresolved_reason()` clears, and why.

    Driven off the LIVE environment rather than a hardcoded list, so a GCC bump
    (16.1.0 -> whatever) needs no edit here, and a component that stops appearing
    stops being claimed.
    """
    by_exception: List[Tuple[Dict, str]] = []
    build_only: List[Dict] = []
    excluded: List[Dict] = []
    for r in conda_rows:
        lic = r.get("license") or ""
        if not any(tok in lic for tok in _NEEDS_DECISION):
            continue
        if r["name"] in _BUILD_ONLY:
            build_only.append(r)
        elif r["name"] in _EXCLUDED_FROM_PAYLOAD:
            excluded.append(r)
        elif r["name"] not in _RESOLVED and (exc := _spdx_exception(lic)):
            by_exception.append((r, exc))

    if not (by_exception or build_only or excluded):
        return

    a("### Copyleft components resolved by exception or by scope")
    a("")
    a("These packages carry a copyleft license in the build environment's metadata "
      "but impose no obligation on this distribution, for the reason given. They are "
      "listed here so the claim can be checked rather than taken on trust.")
    a("")

    if by_exception:
        a("**Resolved by a license exception.** SPDX writes these as "
          "`<license> WITH <exception>`; the exception is the grant that permits use "
          "from code under another license.")
        a("")
        a("| Component | Version | License | Exception |")
        a("|---|---|---|---|")
        for r, exc in by_exception:
            a(f"| {r['name']} | {r['version']} | `{r['license']}` | `{exc}` |")
        a("")
        a("The GCC runtime libraries above are covered by the "
          "[GCC Runtime Library Exception version 3.1]"
          "(https://www.gnu.org/licenses/gcc-exception-3.1.html), which grants "
          "\"unlimited permission to propagate\" the runtime code as part of a "
          "compiled program irrespective of that program's own license. They are "
          "used unmodified.")
        a("")

    for rows, table in ((build_only, _BUILD_ONLY), (excluded, _EXCLUDED_FROM_PAYLOAD)):
        for r in rows:
            a(f"**{r['name']} {r['version']}** — `{r['license']}`")
            a("")
            a(table[r["name"]])
            a("")


def render(pip_rows, conda_rows, version: str) -> Tuple[str, List[str]]:
    gaps: List[str] = []
    L: List[str] = []
    a = L.append

    a("# Third-party notices")
    a("")
    a(f"CellSmith {version} is distributed under the Apache License, Version 2.0 "
      "(see `LICENSE.TXT`).")
    a("")
    a("This distribution also contains third-party components under their own terms, "
      "listed below. Each component is used **unmodified** and is loaded as a separate "
      "file under `_internal/` unless stated otherwise. Nothing here restricts the "
      "Apache-2.0 terms of CellSmith's own code; the terms below apply to the named "
      "components only.")
    a("")
    a("**This file is generated by `packaging/gen_third_party_notices.py` at build "
      "time from the licenses recorded in the build environment. Do not edit it by "
      "hand — edit the generator.**")
    a("")

    # ---------------- copyleft / election-bearing components ---------------
    a("## Components with notice, election, or source-availability obligations")
    a("")
    for ent in _CURATED:
        note = ent["note"]
        if ent.get("id") == "freeimage":
            note = _freeimage_note(gaps)
        a(f"### {ent['name']}")
        a("")
        a(f"*Obtained via:* {ent['via']}  ")
        a(f"*License:* `{ent['spdx']}`")
        a("")
        a(note)
        a("")

    a("## Build tooling")
    a("")
    a("Not part of the distributed payload, listed as acknowledgement.")
    a("")
    for ent in _BUILD_TOOLS:
        a(f"### {ent['name']}")
        a("")
        a(f"*License:* `{ent['spdx']}`")
        a("")
        a(ent["note"])
        a("")

    # ---- copyleft rows resolved by scope or by a license exception ---------
    # Rendered, not suppressed: a reader must be able to audit WHY each GPL row in
    # the inventory below is not an obligation on this distribution.
    _render_resolved_copyleft(a, conda_rows)

    a("### Written offer for source code (LGPL components)")
    a("")
    a("For any component above licensed under the GNU Lesser General Public License, "
      "you may obtain the complete corresponding source code of that component, and "
      "the scripts used to control its compilation and installation, for a period of "
      f"three years, by contacting {SOURCE_OFFER_CONTACT}. The source for each "
      "component is also available from its upstream project at the exact version "
      "recorded in the inventory below.")
    a("")

    # ---------------- full inventory ---------------------------------------
    a("## Inventory — Python distributions")
    a("")
    a("| Component | Version | License |")
    a("|---|---|---|")
    for r in pip_rows:
        lic = r["license"] or "; ".join(r["classifiers"]) or "see text below"
        a(f"| {r['name']} | {r['version']} | {lic} |")
    a("")

    a("## Inventory — conda packages")
    a("")
    a("| Component | Version | Build | License |")
    a("|---|---|---|---|")
    for r in conda_rows:
        a(f"| {r['name']} | {r['version']} | {r['build']} | {r['license'] or '?'} |")
    a("")

    # ---------------- verbatim texts ---------------------------------------
    a("## License texts")
    a("")
    seen = set()
    for ent in _CURATED + _BUILD_TOOLS:
        for fname in ent["licenses"]:
            if fname in seen:
                continue
            seen.add(fname)
            disp, text = _license_text(fname, gaps)
            a(f"### {disp}")
            a("")
            if text is None:
                a(f"*(text not available at build time — `packaging/licenses/{fname}` "
                  "was missing)*")
            else:
                a("```text")
                a(text.replace("\r\n", "\n").rstrip())
                a("```")
            a("")

    for r in pip_rows:
        for fname, body in sorted(r["texts"].items()):
            a(f"### {r['name']} {r['version']} — {fname}")
            a("")
            a("```text")
            a(body.replace("\r\n", "\n").rstrip())
            a("```")
            a("")

    # ---------------- gaps -------------------------------------------------
    for r in conda_rows:
        reason = unresolved_reason(r)
        if reason:
            _warn(reason, gaps)

    a("## Gaps")
    a("")
    if gaps:
        a("The build that produced this file reported the following unresolved "
          "licensing items:")
        a("")
        for g in gaps:
            a(f"- {g}")
    else:
        a("None reported by the generator for this build.")
    a("")
    return "\n".join(L) + "\n", gaps


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out", default=os.path.join(ROOT, "build",
                                                  "THIRD-PARTY-NOTICES.md"))
    ap.add_argument("--prefix", default=sys.prefix,
                    help="environment prefix to read conda-meta from")
    args = ap.parse_args(argv)

    ns: Dict = {}
    with open(os.path.join(ROOT, "src", "__version__.py"), encoding="utf-8") as fh:
        exec(fh.read(), ns)

    body, gaps = render(collect_pip(), collect_conda(args.prefix),
                        ns.get("__version__", "?"))
    os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
    with open(args.out, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(body)
    print(f"wrote {args.out} ({len(body):,} bytes; {len(gaps)} gap(s))")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
