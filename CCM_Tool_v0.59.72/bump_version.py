#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-or-later
# Copyright (c) 2026 Eui Soo SON
# -*- coding: utf-8 -*-
"""
bump_version.py — update all version strings across the CCM Tool project.

Usage:
    python bump_version.py <new_version>

Example:
    python bump_version.py 0.59.3

This script:
1. Updates ccm_version.py's VERSION line
2. Finds and updates VERSION = "..." in all ~27 production modules
3. Renames the toolbox .pyt file and .pyt.xml sidecars
4. Renames the User Manual filename
5. Updates version references in build manifests

WARNING: This is a destructive, real release action. Commit your work first.
The script will rename files that ArcGIS Pro may have registered.
"""

import sys
import re
from pathlib import Path

def get_current_version():
    """Read current version from ccm_version.py."""
    version_file = Path("ccm_version.py")
    if not version_file.exists():
        raise FileNotFoundError("ccm_version.py not found. Run from CCM Tool root directory.")

    with open(version_file, "r", encoding="utf-8-sig", newline="") as f:
        content = f.read()

    match = re.search(r'^VERSION\s*=\s*["\']([0-9.]+)["\']', content, re.MULTILINE)
    if match:
        return match.group(1)
    raise ValueError("Could not parse current VERSION from ccm_version.py")

def update_ccm_version_py(new_version):
    """Update the VERSION string in ccm_version.py."""
    version_file = Path("ccm_version.py")
    with open(version_file, "r", encoding="utf-8-sig", newline="") as f:
        content = f.read()

    # Replace the current VERSION assignment with the requested release
    # value. Anchored to the START of a line (re.MULTILINE + ^) so this only
    # touches the real code assignment -- NOT any illustrative
    # `VERSION = "0.59.2"` example quoted mid-sentence inside this module's
    # own docstring (this file's docstring explains the VERSION convention
    # using that exact literal text as an example several times). An
    # unanchored version of this pattern previously rewrote those
    # documentation examples on every bump, quietly corrupting the
    # docstring's own history lesson release after release.
    old_pattern = r'^VERSION\s*=\s*"[0-9.]+"'
    new_content = re.sub(old_pattern, f'VERSION = "{new_version}"', content,
                         flags=re.MULTILINE)

    with open(version_file, "w", encoding="utf-8", newline="") as f:
        f.write(new_content)
    print(f"✓ Updated ccm_version.py to version {new_version}")

def update_module_versions(new_version):
    """Update VERSION = "..." in all Python modules."""
    count = 0
    root = Path(".")

    # Match VERSION assignments with either quote style and any normal
    # spacing -- anchored to the start of a line (see the comment in
    # update_ccm_version_py above) so a docstring/comment that merely
    # mentions the pattern as text is never rewritten.
    pattern = re.compile(r'^(VERSION\s*=\s*)["\']([0-9.]+)["\']', re.MULTILINE)

    for py_file in root.rglob("*.py"):
        # Skip this maintenance script, generated content, and historical
        # one-off verification scripts that intentionally retain their
        # original release identity.
        if (py_file.name == "bump_version.py"
                or "verification_artifacts" in py_file.parts
                or any(part.startswith("_backup") for part in py_file.parts)
                or py_file.name.startswith("verify_v")):
            continue

        # Explicit UTF-8 is required here: on Windows, a bare open(..., "r")
        # decodes using the system's ANSI codepage (e.g. cp1252), not UTF-8,
        # and this project's sources are UTF-8 (several contain non-ASCII
        # punctuation/symbols). utf-8-sig also tolerates a BOM if a file has
        # one. Without this, any such file crashes the whole bump partway
        # through, leaving some modules updated and others not.
        try:
            with open(py_file, "r", encoding="utf-8-sig", newline="") as f:
                content = f.read()
        except UnicodeDecodeError as exc:
            print(f"  ! Skipped {py_file.name}: not valid UTF-8 ({exc})")
            continue

        new_content = re.sub(pattern, rf'\1"{new_version}"', content)

        if new_content != content:
            with open(py_file, "w", encoding="utf-8", newline="") as f:
                f.write(new_content)
            print(f"  - {py_file.name}")
            count += 1

    if count > 0:
        print(f"✓ Updated {count} module files")
    return count

def rename_toolbox_files(old_version, new_version):
    """Rename the toolbox .pyt file and its .pyt.xml sidecar."""
    old_name = f"CCM_Tool_v{old_version}.pyt"
    new_name = f"CCM_Tool_v{new_version}.pyt"
    old_xml = f"{old_name}.xml"
    new_xml = f"{new_name}.xml"

    root = Path(".")
    old_pyt = root / old_name
    old_xml_path = root / old_xml
    new_pyt = root / new_name
    new_xml_path = root / new_xml

    # Rename .pyt file
    if old_pyt.exists():
        old_pyt.rename(new_pyt)
        print(f"✓ Renamed toolbox: {old_name} → {new_name}")
    elif new_pyt.exists():
        print(f"  (toolbox already named {new_name})")
    else:
        candidates = sorted(root.glob("CCM_Tool_v*.pyt"))
        if len(candidates) == 1:
            old_pyt = candidates[0]
            old_xml_path = root / f"{old_pyt.name}.xml"
            old_pyt.rename(new_pyt)
            print(f"✓ Renamed toolbox: {old_pyt.name} → {new_name}")
        else:
            print(f"  WARNING: toolbox file not found ({old_name} or {new_name})")

    # Rename .pyt.xml sidecar
    if old_xml_path.exists():
        old_xml_path.rename(new_xml_path)
        print(f"✓ Renamed toolbox metadata: {old_xml} → {new_xml}")
    elif new_xml_path.exists():
        print(f"  (toolbox metadata already named {new_xml})")
    else:
        print("  (toolbox metadata file not found; may not exist yet)")

def rename_user_manual(old_version, new_version):
    """Rename the current release User Manual in either supported format."""
    patterns = [
        f"CCM_Tool_v{old_version}_User_Manual.docx",
        f"CCM_Tool_v{old_version}_User_Manual.pdf",
        f"CCM_User_Manual_v{old_version}.pdf",
        "CCM_User_Manual.pdf",
    ]

    root = Path(".")
    found = False

    for pattern in patterns:
        old_path = root / pattern
        if old_path.exists():
            new_path = root / pattern.replace(old_version, new_version)
            old_path.rename(new_path)
            print(f"✓ Renamed User Manual: {pattern} → {new_path.name}")
            found = True
            break

    if not found:
        candidates = sorted(list(root.glob("CCM_Tool_v*_User_Manual.docx"))
                            + list(root.glob("CCM_Tool_v*_User_Manual.pdf")))
        if len(candidates) == 1:
            old_path = candidates[0]
            new_path = root / old_path.name.replace(
                old_path.name.split("_User_Manual", 1)[0].split("_v", 1)[1],
                new_version, 1)
            old_path.rename(new_path)
            print(f"✓ Renamed User Manual: {old_path.name} → {new_path.name}")
            found = True

    if not found:
        print("  (User Manual file not found; may not be in root directory)")

def main():
    if len(sys.argv) != 2:
        print("Usage: python bump_version.py <new_version>")
        print("Example: python bump_version.py 0.59.2")
        sys.exit(1)

    new_version = sys.argv[1]

    # Validate version format (basic)
    if not re.match(r"^[0-9]+\.[0-9]+\.[0-9]+$", new_version):
        print(f"ERROR: Invalid version format '{new_version}'. Use X.Y.Z format (e.g., 0.59.2)")
        sys.exit(1)

    print(f"\n{'='*60}")
    print(f"CCM Tool Version Bump: {new_version}")
    print(f"{'='*60}\n")

    # Read current version
    old_version = get_current_version()
    print(f"Current version: {old_version}")
    print(f"Target version:  {new_version}\n")

    if old_version == new_version:
        print("ERROR: Target version is the same as current version. Nothing to do.")
        sys.exit(1)

    print("Updating...\n")

    # Step 1: Update ccm_version.py
    update_ccm_version_py(new_version)

    # Step 2: Update all module VERSION lines
    update_module_versions(new_version)

    # Step 3: Rename toolbox files
    rename_toolbox_files(old_version, new_version)

    # Step 4: Rename User Manual
    rename_user_manual(old_version, new_version)

    print(f"\n{'='*60}")
    print(f"✓ Version bump to {new_version} complete!")
    print(f"{'='*60}")
    print("\nNext steps:")
    print("  1. Review all changes with: git diff")
    print("  2. Run portable verification:")
    print("     python package_ccm.py --verify-only")
    print("  3. Run licensed ArcPy smoke tests (ArcGIS Pro open + signed in):")
    print("     RUN_ARCGIS_SMOKE_TEST.bat")
    print(f"  4. Commit with: git commit -m 'Release v{new_version}'")
    print()

if __name__ == "__main__":
    main()

# <<< END OF FILE >>>
