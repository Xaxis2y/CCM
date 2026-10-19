# SPDX-License-Identifier: GPL-2.0-or-later
# Copyright (c) 2026 Eui Soo SON
r"""
build_project_init_exe.py -- freeze the CCM Project Initializer into a
standalone Windows .exe
========================================================================
v0.60.0 -- single-root architecture. Produces ONE self-contained
executable that needs no Python installed on the target machine:

    dist\CCM_Project_Init.exe

Run it from the Anaconda Prompt, in the dedicated environment (same one
build_exe.py already uses for CCM_Data_Scanner):

    conda activate ccm_tool
    pip install pyinstaller
    python build_project_init_exe.py

IMPORTANT: always type "python build_project_init_exe.py", never a bare
filename -- see build_exe.py's docstring for why (Windows can resolve a
bare .py through the wrong Python install even with the conda prompt
showing "(ccm_tool)").

This mirrors build_exe.py's structure but targets ccm_project_init.py
instead of CCM_Data_Scanner_GUI.py. It is a separate script rather than a
second mode bolted onto build_exe.py so each build stays simple and the
existing, working CCM_Data_Scanner build is not put at risk by this
addition.

Note on arcpy: arcpy CANNOT be redistributed inside an exe (licensed with
ArcGIS Pro). ccm_project_init.py already degrades gracefully when arcpy is
absent (see its initialize_project() docstring) -- the frozen exe creates
the folder layout and ccm_project.json, and leaves 03_Project.gdb for
Step 0 or Step 1 to create the first time either runs inside ArcGIS Pro.
"""

import os
import sys
import shutil
import argparse
import subprocess
import importlib.util

VERSION = "0.60.8"
APP_NAME = "CCM_Project_Init"
ENTRY = "ccm_project_init.py"
ICON = "ccm.ico"

ROOT = os.path.dirname(os.path.abspath(__file__))

# ccm_project_config is imported lazily inside ccm_project_init.py, so
# PyInstaller needs to be told about it explicitly.
HIDDEN_IMPORTS = [
    "ccm_project_config",
]

# Large packages that may live in the build environment (especially an
# ArcGIS Pro clone) but which this tiny GUI never uses. Excluding them
# keeps the executable small and startup fast -- same list build_exe.py
# uses for the Data Scanner.
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
    else:
        print("  BUILD FAILED -- no executable at:")
        print("  %s" % target)
        print("  Check the PyInstaller output above.")
    print("=" * 70)
    return os.path.isfile(target)


def main(argv=None):
    ap = argparse.ArgumentParser(
        description="Freeze the CCM Project Initializer GUI into a "
                    "standalone executable (v%s)." % VERSION)
    ap.add_argument("--onedir", action="store_true",
                    help="Build a folder instead of a single file "
                         "(starts faster).")
    ap.add_argument("--console", action="store_true",
                    help="Keep the console window (for diagnosing launch "
                         "failures).")
    ap.add_argument("--clean", action="store_true",
                    help="Remove build/, dist/ and the .spec first.")
    args = ap.parse_args(argv)

    print("=" * 70)
    print("  CCM Project Initializer -- executable build   v%s" % VERSION)
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

    if not build(onedir=args.onedir, console=args.console):
        print()
        print("PyInstaller reported a failure.")
        return 1

    return 0 if report_result(args.onedir) else 1


if __name__ == "__main__":
    sys.exit(main())
# <<< END OF FILE >>>
