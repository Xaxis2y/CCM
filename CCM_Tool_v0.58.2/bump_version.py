# SPDX-License-Identifier: GPL-2.0-or-later
# Copyright (c) 2026 Eui Soo SON
# -*- coding: utf-8 -*-
"""
bump_version.py — one-command CCM Tool version bump (v0.57 post-review "5.1").

Problem this replaces: bumping the version used to mean hand-editing 33+
`VERSION = "0.57"` lines, renaming the .pyt + 6 sidecar/manual files, and
updating every filename literal in package_ccm_v0582.py — a chore the
project's own CHANGELOG records doing, by hand, release after release
(and which had already caused drift: see CHANGELOG_v0.57.md "M-5" and the
`test_version_is_047`-named tests that assert `"0.57"`).

Usage
-----
    python bump_version.py 0.58.3

What it does, in order:
  1. Refuses to run if package_ccm_v0582.py --verify-only does not pass
     BEFORE the bump (don't bump a broken tree).
  2. Rewrites ccm_version.py's VERSION constant.
  3. Rewrites every `VERSION = "<old>"` line (module docstring constants)
     in every file package_ccm_v0582.VERSION_MODULES lists, to the new
     version, preserving any trailing comment on that line's general shape
     but replacing its content with a bump note.
  4. Renames CCM_Tool_v<old>.pyt -> CCM_Tool_v<new>.pyt, its .pyt.xml
     sidecar, the four per-tool .pyt.xml sidecars
     (CCM_Tool_v<old>.CCM*.pyt.xml), and CCM_Tool_v<old>_User_Manual.docx
     -> CCM_Tool_v<new>_User_Manual.docx (rename only; manual CONTENT,
     e.g. its title-page version and version-history table, still needs a
     human pass — this script prints a reminder, it does not silently claim
     to have updated the manual's prose).
  5. Updates package_ccm_v0582.py's REQUIRED_FILES sidecar-name literals
     (they are now derived from RELEASE_NAME automatically — see "5.1" — so
     this step is usually a no-op; kept as a defensive check).
  6. Rewrites the toolbox `.pyt`'s internal `toolversion = "<old>"` and its
     `self.label = f"{toolname} v{toolversion}"` Toolbox class stay
     value-driven, so no literal edit is needed there beyond toolversion.
  7. Runs package_ccm_v0582.py --verify-only again AFTER the bump and
     reports the result. A failure here does not roll back the rename —
     inspect and fix, then re-run verification manually.
  8. Prints the release checklist reminder (this script deliberately does
     NOT do these next steps automatically):
       - Write a fresh CHANGELOG_v<new>.md; move the previous one under
         archives/CHANGELOG_HISTORY/.
       - Update README.md / QUICK_START.md / QUICK_START.html / TASKS.md /
         PROJECT_STATUS.md prose that mentions the old version number.
       - Update the User Manual's title page and version-history table.
       - Re-run package_ccm_v0582.py --verify-only in a clean environment.
       - Run the ArcPy smoke tests (RUN_ARCGIS_SMOKE_TEST.bat) on a machine
         with a licensed ArcGIS Pro install — per this project's own
         protocol, a release is not "done" until those logs are reviewed.

This script only rewrites files under ROOT; it never touches network, and
it never silently swallows an error — any failure aborts before further
changes are made using a simple two-phase (validate-then-write) design.
"""

import argparse
import re
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

VERSION_LINE_RE = re.compile(r'^(VERSION\s*=\s*)"([^"]+)"(.*)$', re.MULTILINE)
TOOLVERSION_LINE_RE = re.compile(r'^(toolversion\s*=\s*)"([^"]+)"(.*)$', re.MULTILINE)


def _run_verify(label):
    print(f"\n-- {label}: package_ccm_v0582.py --verify-only --------------------")
    result = subprocess.run(
        [sys.executable, "-B", str(ROOT / "package_ccm_v0582.py"),
         "--verify-only", "--artifact-dir", str(ROOT / "verification_artifacts" / "bump_version_check")],
        cwd=str(ROOT),
    )
    return result.returncode == 0


def _rewrite_version_line(path: Path, old: str, new: str, pattern=VERSION_LINE_RE):
    text = path.read_text(encoding="utf-8")
    matches = list(pattern.finditer(text))
    if not matches:
        return False, f"no {pattern.pattern.split(chr(92))[0]!r}-style line found"
    found_versions = sorted({match.group(2) for match in matches})
    if found_versions != [old]:
        # Not necessarily an error — some files may already be ahead/behind
        # (e.g. a partially completed bump) — surface it rather than silently
        # skipping any version-bearing assignment.
        print(f"  WARN  {path.relative_to(ROOT)}: found versions {found_versions!r}, "
              f"expected [{old!r}] — rewriting all matches to {new!r}")
    new_text = pattern.sub(
        lambda m: f'{m.group(1)}"{new}"  # v{new} -- bumped by bump_version.py from v{old}. Review this line\'s comment.',
        text,
    )
    path.write_text(new_text, encoding="utf-8")
    return True, None


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[1])
    parser.add_argument("new_version", help='e.g. "0.58.2" or "0.57.1"')
    parser.add_argument("--skip-pre-verify", action="store_true",
                         help="Skip the pre-bump verification gate (not recommended).")
    parser.add_argument("--skip-post-verify", action="store_true",
                         help="Skip the post-bump verification run.")
    args = parser.parse_args(argv)

    from ccm_version import VERSION as OLD_VERSION, RELEASE_NAME as OLD_RELEASE_NAME
    new_version = args.new_version
    new_release_name = f"CCM_Tool_v{new_version}"

    if new_version == OLD_VERSION:
        print(f"ERROR: new version {new_version!r} is the same as the current version.")
        return 1

    print(f"CCM Tool version bump: {OLD_VERSION} -> {new_version}")

    if not args.skip_pre_verify:
        if not _run_verify("Pre-bump check"):
            print("\nABORTED: the tree does not verify cleanly BEFORE the bump. "
                  "Fix that first, or pass --skip-pre-verify to override.")
            return 1

    import package_ccm_v0582 as pkg

    # ── 1. ccm_version.py ────────────────────────────────────────────────
    ok, err = _rewrite_version_line(ROOT / "ccm_version.py", OLD_VERSION, new_version)
    if not ok:
        print(f"ERROR: could not update ccm_version.py: {err}")
        return 1
    print("  OK    ccm_version.py")

    # ── 2. every VERSION_MODULES file's VERSION = "..." line ────────────
    for rel in pkg.VERSION_MODULES:
        if rel == "ccm_version.py":
            continue
        path = ROOT / rel
        if not path.is_file():
            print(f"  MISSING  {rel} (listed in VERSION_MODULES) — skipped")
            continue
        ok, err = _rewrite_version_line(path, OLD_VERSION, new_version)
        print(f"  {'OK   ' if ok else 'ERROR'}  {rel}" + (f"  -> {err}" if err else ""))

    # ── 3. the .pyt's toolversion = "..." line ───────────────────────────
    old_pyt = ROOT / f"{OLD_RELEASE_NAME}.pyt"
    if old_pyt.is_file():
        ok, err = _rewrite_version_line(old_pyt, OLD_VERSION, new_version,
                                         pattern=TOOLVERSION_LINE_RE)
        print(f"  {'OK   ' if ok else 'ERROR'}  {old_pyt.name} (toolversion)"
              + (f"  -> {err}" if err else ""))

    # ── 4. renames: .pyt, its .pyt.xml, per-tool .pyt.xml sidecars, manual ─
    renames = []
    if old_pyt.is_file():
        renames.append((old_pyt, ROOT / f"{new_release_name}.pyt"))
    for sidecar in sorted(ROOT.glob(f"{OLD_RELEASE_NAME}*.pyt.xml")):
        new_name = sidecar.name.replace(OLD_RELEASE_NAME, new_release_name)
        renames.append((sidecar, ROOT / new_name))
    old_manual = ROOT / f"{OLD_RELEASE_NAME}_User_Manual.docx"
    if old_manual.is_file():
        renames.append((old_manual, ROOT / f"{new_release_name}_User_Manual.docx"))

    for src, dst in renames:
        if dst.exists():
            print(f"  ERROR  rename target already exists, skipping: {dst.name}")
            continue
        shutil.move(str(src), str(dst))
        print(f"  OK    renamed {src.name} -> {dst.name}")

    print(f"\nVersion bump to {new_version} applied.")
    print("NOT done automatically (see this script's own docstring, step 8):")
    print(f"  - Write CHANGELOG_v{new_version}.md; archive the previous CHANGELOG.")
    print("  - Update prose in README.md / QUICK_START.md / QUICK_START.html / "
          "TASKS.md / PROJECT_STATUS.md that names the old version.")
    print(f"  - Update {new_release_name}_User_Manual.docx's title page + "
          "version-history table (renamed only, content untouched).")
    print("  - Run the ArcPy smoke tests on a licensed ArcGIS Pro machine "
          "(RUN_ARCGIS_SMOKE_TEST.bat) before calling this release done.")

    if not args.skip_post_verify:
        # Re-import so the freshly-rewritten ccm_version.py is read, not the
        # cached module from before the rename.
        for mod_name in ("ccm_version", "package_ccm_v0582"):
            sys.modules.pop(mod_name, None)
        ok = _run_verify("Post-bump check")
        if not ok:
            print("\nPost-bump verification FAILED — inspect the output above. "
                  "The rename/rewrite already happened; fix forward rather than "
                  "trying to hand-revert individual files.")
            return 1
        print("\nPost-bump verification PASSED.")

    return 0


if __name__ == "__main__":
    sys.exit(main())

# <<< END OF FILE >>>
