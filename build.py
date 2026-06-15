"""
build.py — CCM syntax check + zip packager (version-agnostic).

The release version is read from ccm_project_config.VERSION so a version
bump only ever touches the module VERSION constants — this script and the
zip name follow automatically.

Run from the project folder:
    python build.py

Outputs:
    MCE_CCM_Tool_v<VERSION>.zip  (created in this folder)
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

PY_FILES = [
    "MCE_CCM_v0.46.pyt",
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
    "tests/test_ccm.py",
]

INCLUDE_PATTERNS = [
    ".py", ".pyt", ".xml", ".csv", ".lyrx", ".md", ".docx",
]

END_MARKER = "# <<< END OF FILE >>>"
MARKER_EXEMPT = {"build.py", "test_ccm.py"}  # files not required to carry the marker


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

    # ── Build zip ─────────────────────────────────────────────────────────────
    zip_name = f"MCE_CCM_Tool_v{VERSION}.zip"
    zip_path = os.path.join(ROOT, zip_name)

    print(f"\n── Building {zip_name} ──────────────────────────────────────")
    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for dirpath, dirnames, filenames in os.walk(ROOT):
            # Skip hidden dirs, __pycache__, .git
            dirnames[:] = [
                d for d in dirnames
                if not d.startswith(".") and d != "__pycache__"
            ]
            for fname in filenames:
                if fname.endswith(".zip"):
                    continue  # Never include zips (incl. this one)
                if not any(fname.endswith(ext) for ext in INCLUDE_PATTERNS):
                    continue
                full_src = os.path.join(dirpath, fname)
                arc_name = os.path.join(
                    f"MCE_CCM_Tool_v{VERSION}", os.path.relpath(full_src, ROOT)
                )
                zf.write(full_src, arc_name)
                print(f"  + {arc_name}")

    size_kb = os.path.getsize(zip_path) / 1024
    print(f"\nOK  Created {zip_path}  ({size_kb:.1f} KB)")
    print("=" * 60)


if __name__ == "__main__":
    main()
