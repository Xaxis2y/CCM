# SPDX-License-Identifier: GPL-2.0-or-later
# Copyright (c) 2026 Eui Soo SON
"""
build.py — CCM syntax check + zip packager (version-agnostic).

The release version is read from ccm_version.VERSION so a version bump only
ever touches that one constant — this script, the toolbox filename it
checks, and the zip name all follow automatically.

Run from the project folder:
    python build.py

Outputs:
    CCM_Tool_v<VERSION>.zip  (created in this folder)

v0.57 post-review changes ("5.1" / "M-5")
------------------------------------------
  - VERSION now comes from the new ccm_version.py (previously read via regex
    out of ccm_project_config.py — a second, independent place the number
    could drift from package_ccm_v0582.py's own separate "0.57" literal).
  - PY_FILES is now DERIVED from package_ccm_v0582.CODE_FILES instead of
    being a second, hand-maintained list. The two had already drifted:
    package_ccm_v0582.py listed 4 arcpy smoke tests build.py's PY_FILES did
    not, and build.py listed tests/test_ccm.py + tests/test_v050.py that
    package_ccm_v0582.py's version-check list did not. See CHANGELOG_v0.57.md
    "M-5". The toolbox filename is still computed fresh here (not imported)
    since it must come first in the zip listing either way.

v0.58.2 changes
---------------
  - Integrates the validated Data Intelligence Step 0b modules, tests, GUI,
    Anaconda setup script, and logged launchers into the v0.57 toolbox.
  - The release ZIP includes user-facing .bat launchers so a new operator can
    prepare the environment and run the verification workflow from Anaconda
    Prompt. Generated logs and verification artifacts remain excluded.

v0.55.0 changes
---------------
  - Filename/version bump only. No packaging logic changed. This script
    itself already carried every v0.54.2 packaging-safety fix below; the
    project's other, code-fix-bearing line (independently rebranded/
    relicensed as "CCM_Tool_v0.54.1", without those fixes) had an older,
    pre-v0.54.2 build.py that had regressed back to shipping unfiltered
    zips with no stale-toolbox guard. v0.55.0 keeps *this* file. See
    CHANGELOG_v0.57.md.

v0.54.2 changes
---------------
  - FIX: the packager walked the whole project folder and included every
    file matching an extension, with no version filter.  The v0.54.1 zip
    therefore shipped 17 stale files — including TWO obsolete toolboxes
    from an earlier product naming, two superseded user manuals, twelve
    orphan .pyt.xml sidecars, and a Word lock file (~$...docx).  A user
    unzipping it saw three toolboxes and three manuals.  Files are now
    screened by should_include(), which rejects Office lock files and
    anything carrying a _v<version> tag that is not the current release.
  - FIX: PY_FILES hardcoded "CCM_Tool_v0.54.1.pyt" despite the
    module docstring claiming version-agnosticism, so every bump silently
    required editing this literal.  The toolbox filename is now derived
    from VERSION.
  - The integrity check now also fails when a stale toolbox is found next
    to the current one, so the packaging defect cannot silently recur.
"""

import os
import re
import sys
import ast
import zipfile
import datetime

ROOT = os.path.dirname(os.path.abspath(__file__))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)


def read_version():
    """Read VERSION from ccm_version.py (single source of truth, "5.1")."""
    from ccm_version import VERSION as _v
    return _v


VERSION = read_version()

# Derived from VERSION — never hardcode the toolbox filename here (v0.54.2).
TOOLBOX_NAME = f"CCM_Tool_v{VERSION}.pyt"

# PY_FILES is derived from package_ccm_v0582.py's own manifest ("M-5") so
# there is exactly one list of "files whose VERSION/content this release
# cares about" instead of two independently hand-maintained ones. Only the
# toolbox filename is treated specially: TOOLBOX_NAME above is computed the
# same way package_ccm_v0582.TOOLBOX_FILENAME is (from the same VERSION), so
# the two never disagree even though each computes it locally.
from package_ccm_v0582 import CODE_FILES as _PKG_CODE_FILES  # noqa: E402

PY_FILES = [TOOLBOX_NAME] + [f for f in _PKG_CODE_FILES if not f.endswith(".pyt")]

INCLUDE_PATTERNS = [
    ".py", ".pyt", ".xml", ".csv", ".lyrx", ".md", ".docx", ".html", ".bat",
]

# ── Packaging exclusions (v0.54.2) ───────────────────────────────────────────
# Office lock/temp files.
EXCLUDE_PREFIXES = ("~$", ".~")
# Internal development documents that should not ship to end users.
EXCLUDE_EXACT = {
    "CLAUDE.md",
    "CODE_REVIEW_v0.49.3.md",
    "CCM_Improvement_Research.md",
}
EXCLUDED_DIRS = {
    "verification_artifacts", "verification_logs", "_pytest_runtime",
    "_docx_render", "build", "dist", ".pytest_cache",
}
# Matches a _v1.2 / _v1.2.3 version tag anywhere in a filename.
_VER_TAG = re.compile(r"_v(\d+\.\d+(?:\.\d+)?)")
# Filenames whose version tag denotes a SERIES, not a build, and which must
# always ship.  CHANGELOG_v0.45.md .. CHANGELOG_v0.57.md are the project's
# release-note history; the version-tag screen would otherwise drop every one
# of them, including the current release's own notes.
VERSION_TAG_EXEMPT_PREFIXES = ("CHANGELOG_",)

END_MARKER = "# <<< END OF FILE >>>"
MARKER_EXEMPT = {"build.py", "test_ccm.py", "test_v050.py"}  # files not required to carry the marker


def should_include(fname):
    """
    Decide whether *fname* belongs in the release zip.

    Returns (True, None) to include, or (False, reason) to skip.
    """
    if fname.endswith(".zip"):
        return False, "zip archive"
    if not any(fname.endswith(ext) for ext in INCLUDE_PATTERNS):
        return False, "extension not packaged"
    if fname.startswith(EXCLUDE_PREFIXES):
        return False, "Office lock/temp file"
    if fname in EXCLUDE_EXACT:
        return False, "internal development document"
    if not fname.startswith(VERSION_TAG_EXEMPT_PREFIXES):
        m = _VER_TAG.search(fname)
        if m and m.group(1) != VERSION:
            return False, f"stale version tag v{m.group(1)} (current v{VERSION})"
    return True, None


def find_stale_toolboxes():
    """Return .pyt files in ROOT that are not the current toolbox."""
    stale = []
    for fname in sorted(os.listdir(ROOT)):
        if fname.endswith(".pyt") and fname != TOOLBOX_NAME:
            stale.append(fname)
    return stale


def syntax_check(path):
    with open(path, "rb") as fh:
        raw = fh.read()
    if b"\x00" in raw:
        return False, "contains NULL bytes (truncated/corrupt file)"
    try:
        source = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        return False, f"invalid UTF-8: {exc}"
    try:
        ast.parse(source, filename=path)
    except SyntaxError as exc:
        return False, f"Line {exc.lineno}: {exc.msg}"
    base = os.path.basename(path)
    if base not in MARKER_EXEMPT and END_MARKER not in source:
        return False, f"missing '{END_MARKER}' terminator (file truncated?)"
    # v0.50.2: the EOF marker alone is not proof of completeness — two files
    # were once truncated *before* a marker was re-appended, and still parsed
    # as valid Python.  pyflakes' undefined-name check catches code that
    # calls helpers lost to truncation.
    try:
        from pyflakes.api import check as _pf_check
        from pyflakes.reporter import Reporter as _pf_Reporter
        import io as _io
        _out, _err = _io.StringIO(), _io.StringIO()
        _pf_check(source, path, _pf_Reporter(_out, _err))
        undefined = [ln for ln in _out.getvalue().splitlines()
                     if "undefined name" in ln]
        if undefined:
            return False, "undefined name(s): " + "; ".join(undefined[:3])
    except ImportError:
        pass  # pyflakes not installed — marker/syntax checks still apply
    return True, None


def main():
    print("=" * 60)
    print(f"  CCM v{VERSION} Build Script  -  {datetime.datetime.now():%Y-%m-%d %H:%M:%S}")
    print("=" * 60)

    # ── Syntax / integrity check ─────────────────────────────────────────────
    print("\n-- Syntax & Integrity Check ----------------------------------")
    errors = []
    for rel_path in PY_FILES:
        full = os.path.join(ROOT, rel_path)
        if not os.path.isfile(full):
            print(f"  MISSING  {rel_path}")
            errors.append(rel_path)
            continue
        ok, msg = syntax_check(full)
        if ok:
            print(f"  OK       {rel_path}")
        else:
            print(f"  ERROR    {rel_path}  ->  {msg}")
            errors.append(rel_path)

    print(f"\nCheck: {len(PY_FILES) - len(errors)}/{len(PY_FILES)} files OK")
    if errors:
        print(f"ERRORS in: {errors}")
        print("Fix errors before packaging.")
        sys.exit(1)

    # ── Stale-toolbox guard (v0.54.2) ────────────────────────────────────────
    print("\n-- Stale Artifact Check --------------------------------------")
    stale_tb = find_stale_toolboxes()
    if stale_tb:
        print("  ERROR  obsolete toolbox file(s) present in the project folder:")
        for s in stale_tb:
            print(f"           {s}")
        print("  A release folder must contain exactly one .pyt.  Delete the")
        print("  obsolete toolbox(es) and their .pyt.xml sidecars, then re-run.")
        sys.exit(1)
    print(f"  OK       exactly one toolbox present: {TOOLBOX_NAME}")

    # ── Build zip ─────────────────────────────────────────────────────────────
    zip_name = f"CCM_Tool_v{VERSION}.zip"
    zip_path = os.path.join(ROOT, zip_name)
    print(f"\n-- Building {zip_name} --------------------------------------")
    n_added, skipped = 0, []
    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for dirpath, dirnames, filenames in os.walk(ROOT):
            # Skip hidden dirs, __pycache__, .git
            dirnames[:] = [
                d for d in dirnames
                if not d.startswith(".") and d != "__pycache__"
                and d not in EXCLUDED_DIRS
            ]
            for fname in sorted(filenames):
                include, reason = should_include(fname)
                if not include:
                    if reason not in ("extension not packaged", "zip archive"):
                        skipped.append((fname, reason))
                    continue
                full_src = os.path.join(dirpath, fname)
                arc_name = os.path.join(
                    f"CCM_Tool_v{VERSION}", os.path.relpath(full_src, ROOT)
                )
                zf.write(full_src, arc_name)
                print(f"  + {arc_name}")
                n_added += 1

    if skipped:
        print(f"\n-- Excluded from the package ({len(skipped)}) ----------------")
        for fname, reason in skipped:
            print(f"  - {fname}  ->  {reason}")

    size_kb = os.path.getsize(zip_path) / 1024
    print(f"\nOK  Created {zip_path}  ({n_added} files, {size_kb:.1f} KB)")
    print("=" * 60)


if __name__ == "__main__":
    main()

# <<< END OF FILE >>>
