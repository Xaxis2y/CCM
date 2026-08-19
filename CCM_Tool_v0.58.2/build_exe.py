# SPDX-License-Identifier: GPL-2.0-or-later
# Copyright (c) 2026 Eui Soo SON
r"""
build_exe.py -- freeze the CCM Data Scanner into a standalone Windows .exe
==========================================================================
Updated for the factual v0.57 release.

Produces ONE self-contained executable that needs no Python installed on the
target machine:

    dist\CCM_Data_Scanner.exe

Run it from the **Anaconda Prompt**, in the dedicated environment:

    conda activate ccm_tool
    pip install pyinstaller
    python build_exe.py

IMPORTANT: always type "python build_exe.py", never bare "build_exe.py".
Windows resolves a bare .py filename through the file-extension association
(often a different, standalone Python install), NOT through the activated
conda environment's PATH -- even while the prompt shows "(ccm_tool)".
That mismatch is exactly what makes this script print the wrong Python
version and report PyInstaller as "not installed" when it is actually
installed in ccm_tool.

Options
-------
    --onedir      build a folder instead of a single file.  Starts noticeably
                  faster (no self-extraction on every launch) -- prefer this
                  when you will copy the whole folder to a shared drive.
    --console     keep the console window (useful for diagnosing a launch
                  failure; the default hides it, as a GUI app should).
    --clean       remove build/ dist/ and the .spec before building.
    --no-verify   skip the pre-build test run.

Which Python to freeze with
---------------------------
PyInstaller bundles the interpreter it RUNS under, so build with the Python
you want shipped.  Freezing inside the ArcGIS Pro clone works and is the most
faithful to the analyst's machine, but it produces a much larger executable
because that environment carries a large scientific stack.  The scanner needs
NONE of that -- it is pure standard library.  A plain python 3.11/3.12
environment yields a far smaller exe and behaves identically, because the
engine falls back to its own header readers when arcpy is absent.

Note on arcpy: arcpy CANNOT be redistributed inside an exe (it is licensed
with ArcGIS Pro).  A frozen build therefore always uses the pure-Python
metadata path.  To get arcpy-measured metadata, run the GUI as a script inside
ArcGIS Pro's Python instead of using the exe.
"""

import os
import sys
import shutil
import argparse
import subprocess
import importlib.util

VERSION = "0.58.2"  # v0.58.2 -- bumped by bump_version.py from v0.57. Review this line's comment.
APP_NAME = "CCM_Data_Scanner"
ENTRY = "CCM_Data_Scanner_GUI.py"
ICON = "ccm.ico"

ROOT = os.path.dirname(os.path.abspath(__file__))

# Engine modules the GUI imports dynamically enough that PyInstaller should be
# told about them explicitly.
HIDDEN_IMPORTS = [
    "ccm_data_catalog",
    "ccm_data_sources",
    "ccm_data_report",
]

# Large packages that may live in the build environment (especially an ArcGIS
# Pro clone) but which the scanner never uses.  Excluding them keeps the
# executable small and the startup fast.
EXCLUDES = [
    "numpy", "scipy", "pandas", "matplotlib", "PIL", "IPython", "jupyter",
    "notebook", "pytest", "setuptools", "pip", "sqlalchemy", "cryptography",
    "arcpy", "arcgis", "osgeo", "gdal", "PyQt5", "PySide2", "PySide6",
    "tornado", "zmq", "sklearn", "numba", "llvmlite", "h5py", "networkx",
]


def log(msg):
    print("[build] %s" % msg)


def check_prereqs():
    problems = []
    for rel in [ENTRY] + ["%s.py" % m for m in HIDDEN_IMPORTS]:
        if not os.path.isfile(os.path.join(ROOT, rel)):
            problems.append("missing source file: %s" % rel)
    if importlib.util.find_spec("PyInstaller") is None:
        problems.append(
            "PyInstaller is not installed in this environment.\n"
            "        Install it into the dedicated environment (never base):\n"
            "            conda activate ccm_tool\n"
            "            pip install pyinstaller")
    return problems


def run_verification():
    """Never freeze code that does not pass its own tests."""
    test_file = os.path.join(ROOT, "tests", "test_v057_data_intelligence.py")
    if not os.path.isfile(test_file):
        log("tests/test_v057_data_intelligence.py not found -- build is blocked")
        return False
    if importlib.util.find_spec("pytest") is None:
        log("pytest not installed -- build is blocked")
        return False
    log("running the test suite before freezing...")
    proc = subprocess.run([sys.executable, "-B", "-m", "pytest", test_file,
                           "-q", "-p", "no:cacheprovider"],
                          cwd=ROOT, capture_output=True, text=True)
    tail = (proc.stdout or "").strip().splitlines()
    log("  %s" % (tail[-1] if tail else "(no output)"))
    if proc.returncode != 0:
        for line in (proc.stdout or "").splitlines()[-20:]:
            print("        %s" % line)
    return proc.returncode == 0


def clean():
    for name in ("build", "dist", "__pycache__"):
        path = os.path.join(ROOT, name)
        if os.path.isdir(path):
            shutil.rmtree(path, ignore_errors=True)
            log("removed %s/" % name)
    spec = os.path.join(ROOT, APP_NAME + ".spec")
    if os.path.isfile(spec):
        os.remove(spec)
        log("removed %s" % os.path.basename(spec))


def build(onedir=False, console=False):
    cmd = [
        sys.executable, "-m", "PyInstaller",
        "--noconfirm",
        "--name", APP_NAME,
        "--onedir" if onedir else "--onefile",
        "--console" if console else "--windowed",
        "--distpath", os.path.join(ROOT, "dist"),
        "--workpath", os.path.join(ROOT, "build"),
        "--specpath", ROOT,
    ]

    icon_path = os.path.join(ROOT, ICON)
    if os.path.isfile(icon_path):
        cmd += ["--icon", icon_path]
        # Ship the icon alongside so the window titlebar can use it too.
        cmd += ["--add-data", "%s%s." % (icon_path, os.pathsep)]
    else:
        log("no %s found -- building without an icon" % ICON)

    for mod in HIDDEN_IMPORTS:
        cmd += ["--hidden-import", mod]
        src = os.path.join(ROOT, mod + ".py")
        if os.path.isfile(src):
            cmd += ["--add-data", "%s%s." % (src, os.pathsep)]

    for mod in EXCLUDES:
        cmd += ["--exclude-module", mod]

    cmd.append(os.path.join(ROOT, ENTRY))

    log("PyInstaller command:")
    print("        " + " ".join(
        ('"%s"' % c if " " in c else c) for c in cmd))
    print()
    proc = subprocess.run(cmd, cwd=ROOT)
    return proc.returncode == 0


def report_result(onedir):
    if onedir:
        target = os.path.join(ROOT, "dist", APP_NAME, APP_NAME + ".exe")
        folder = os.path.join(ROOT, "dist", APP_NAME)
    else:
        target = os.path.join(ROOT, "dist", APP_NAME + ".exe")
        folder = os.path.join(ROOT, "dist")

    # On a non-Windows build host PyInstaller emits an extension-less binary.
    if not os.path.isfile(target):
        alt = target[:-4]
        if os.path.isfile(alt):
            target = alt

    print()
    print("=" * 70)
    if os.path.isfile(target):
        size_mb = os.path.getsize(target) / (1024.0 * 1024.0)
        print("  BUILD OK")
        print("  %s  (%.1f MB)" % (target, size_mb))
        print()
        print("  To distribute: copy %s" % (
            "the whole %s folder" % os.path.basename(folder) if onedir
            else "this single file"))
        print("  The target machine needs NO Python installed.")
        print()
        print("  Note: a frozen build always uses the pure-Python metadata")
        print("  readers -- arcpy cannot be redistributed inside an exe.")
        print("  For arcpy-measured metadata, run the GUI as a script in")
        print("  ArcGIS Pro's Python environment instead.")
    else:
        print("  BUILD FAILED -- no executable at:")
        print("  %s" % target)
        print("  Check the PyInstaller output above.")
    print("=" * 70)
    return os.path.isfile(target)


def main(argv=None):
    ap = argparse.ArgumentParser(
        description="Freeze the CCM Data Scanner GUI into a standalone "
                    "executable (v%s)." % VERSION)
    ap.add_argument("--onedir", action="store_true",
                    help="Build a folder instead of a single file "
                         "(starts faster).")
    ap.add_argument("--console", action="store_true",
                    help="Keep the console window (for diagnosing launch "
                         "failures).")
    ap.add_argument("--clean", action="store_true",
                    help="Remove build/, dist/ and the .spec first.")
    ap.add_argument("--no-verify", action="store_true",
                    help="Skip the pre-build test run.")
    args = ap.parse_args(argv)

    print("=" * 70)
    print("  CCM Data Scanner -- executable build   v%s" % VERSION)
    print("  Python: %s" % sys.version.split()[0])
    print("  Folder: %s" % ROOT)
    print("=" * 70)
    print()

    problems = check_prereqs()
    if problems:
        print("Cannot build:")
        for p in problems:
            print("  - %s" % p)
        return 1

    if args.clean:
        clean()

    if not args.no_verify:
        if not run_verification():
            print()
            print("Tests failed -- refusing to freeze a broken build.")
            print("Re-run with --no-verify to override (not recommended).")
            return 1
        print()

    if not build(onedir=args.onedir, console=args.console):
        print()
        print("PyInstaller reported a failure.")
        return 1

    return 0 if report_result(args.onedir) else 1


if __name__ == "__main__":
    sys.exit(main())

# <<< END OF FILE >>>
