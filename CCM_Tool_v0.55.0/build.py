# SPDX-License-Identifier: GPL-2.0-or-later
# Copyright (c) 2026 Eui Soo SON
"""
build.py — CCM syntax check + zip packager (version-agnostic).

The release version is read from ccm_project_config.VERSION so a version
bump only ever touches the module VERSION constants — this script, the
toolbox filename it checks, and the zip name all follow automatically.

Run from the project folder:
    python build.py

Outputs:
    CCM_Tool_v<VERSION>.zip  (created in this folder)

v0.55.0 changes
---------------
  - Filename/version bump only. No packaging logic changed. This script
    itself already carried every v0.54.2 packaging-safety fix below; the
    project's other, code-fix-bearing line (independently rebranded/
    relicensed as "CCM_Tool_v0.54.1", without those fixes) had an older,
    pre-v0.54.2 build.py that had regressed back to shipping unfiltered
    zips with no stale-toolbox guard. v0.55.0 keeps *this* file. See
    CHANGELOG_v0.55.md.

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


def read_version():
    """Read VERSION from ccm_project_config.py without importing arcpy deps."""
    cfg = os.path.join(ROOT, "ccm_project_config.py")
    with open(cfg, encoding="utf-8") as fh:
        m = re.search(r'^VERSION\s*=\s*"([^"]+)"', fh.read(), re.MULTILINE)
    if not m:
        print("ERROR: VERSION constant not found in ccm_project_config.py")
        sys.exit(1)
    return m.group(1)


VERSION = read_version()

# Derived from VERSION — never hardcode the toolbox filename here (v0.54.2).
TOOLBOX_NAME = f"CCM_Tool_v{VERSION}.pyt"

PY_FILES = [
    TOOLBOX_NAME,
    "ccm_step0_mgcp.py",
    "ccm_step1_setup.py",
    "ccm_step2_mobility.py",
    "ccm_step3_advanced.py",
    "ccm_vehicle_compare.py",
    "ccm_soil_preprocess.py",
    "ccm_veg_preprocess.py",
    "ccm_soil_validator.py",
    "ccm_obstacle_detect.py",
    "ccm_waypoints.py",
    "ccm_isochrone.py",
    "ccm_reason_map.py",
    "ccm_coords.py",
    "ccm_weather.py",
    "ccm_project_config.py",
    "ccm_mgcp_catalog.py",
    "ccm_map_display.py",
    "ccm_data_discovery.py",
    "tests/test_ccm.py",
    "tests/test_v050.py",
]

INCLUDE_PATTERNS = [
    ".py", ".pyt", ".xml", ".csv", ".lyrx", ".md", ".docx",
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
# Matches a _v1.2 / _v1.2.3 version tag anywhere in a filename.
_VER_TAG = re.compile(r"_v(\d+\.\d+(?:\.\d+)?)")
# Filenames whose version tag denotes a SERIES, not a build, and which must
# always ship.  CHANGELOG_v0.45.md .. CHANGELOG_v0.55.md are the project's
# release-note history; the version-tag screen would otherwise drop every one
# of them, including the current release's own notes.
VERSION_TAG_EXEMPT_PREFIXES = ("CHANGELOG_",)

END_MARKER = "# <<< END OF FILE >>>"
MARKER_EXEMPT = {"build.py", "test_ccm.py"}  # files not required to carry the marker


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
    print(f"  CCM v{VERSION} Build Script  —  {datetime.datetime.now():%Y-%m-%d %H:%M:%S}")
    print("=" * 60)

    # ── Syntax / integrity check ─────────────────────────────────────────────
    print("\n── Syntax & Integrity Check ─────────────────────────────────")
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
            print(f"  ERROR    {rel_path}  →  {msg}")
            errors.append(rel_path)

    print(f"\nCheck: {len(PY_FILES) - len(errors)}/{len(PY_FILES)} files OK")
    if errors:
        print(f"ERRORS in: {errors}")
        print("Fix errors before packaging.")
        sys.exit(1)

    # ── Stale-toolbox guard (v0.54.2) ────────────────────────────────────────
    print("\n── Stale Artifact Check ─────────────────────────────────────")
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
    print(f"\n── Building {zip_name} ──────────────────────────────────────")
    n_added, skipped = 0, []
    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for dirpath, dirnames, filenames in os.walk(ROOT):
            # Skip hidden dirs, __pycache__, .git
            dirnames[:] = [
                d for d in dirnames
                if not d.startswith(".") and d != "__pycache__"
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
        print(f"\n── Excluded from the package ({len(skipped)}) ───────────────")
        for fname, reason in skipped:
            print(f"  - {fname}  →  {reason}")

    size_kb = os.path.getsize(zip_path) / 1024
    print(f"\nOK  Created {zip_path}  ({n_added} files, {size_kb:.1f} KB)")
    print("=" * 60)


if __name__ == "__main__":
    main()
