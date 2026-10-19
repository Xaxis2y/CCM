# SPDX-License-Identifier: GPL-2.0-or-later
# Copyright (c) 2026 Eui Soo SON
# -*- coding: utf-8 -*-
VERSION = "0.60.8"
"""
test_single_root_pure_python.py — v0.60.0 single-root architecture verifier.

Purpose
-------
CCM_Tool v0.60.0 replaces the old per-step folder parameters (Output
Geodatabase / Data Root Folder / Project Output Folder / Project Folder)
with a single `project_root` parameter that all pipeline steps share.
Most of the code that implements this (ccm_step0_mgcp.py, ccm_step1_setup.py,
ccm_step2_mobility.py, ccm_step3_advanced.py, the .pyt itself) imports
`arcpy` at module scope, so it cannot be exercised in an environment without
an ArcGIS Pro Python installation — including this sandbox.

This script instead verifies everything that does NOT require arcpy:

  1. Every edited/created .py file at least imports cleanly (catches syntax
     errors, indentation mistakes, and accidental top-level arcpy imports in
     files that are supposed to be arcpy-free).
  2. ccm_project_config.save_config()/load_config() round-trip correctly and
     keep `project_folder` and `project_root` in lock-step (the mechanism
     every step relies on to agree on where things are).
  3. ccm_project_init.py's headless `initialize_project()` core logic
     actually creates the 01_Input_Data / 02_Scan_Index / 03_Project.gdb
     (skipped, no arcpy) layout and a valid ccm_project.json with the
     expected keys.
  4. ccm_step0b_integration.py's Step0bIntegrator runs an end-to-end scan
     against synthetic fixture data and confirms report artifacts land
     under 02_Scan_Index/ while ccm_project.json stays at the root, with
     every path key in ccm_project.json actually pointing at a file that
     exists on disk.
  5. package_ccm.py's own validate_end_to_end() self-check passes.

It prints clear "[PASS]"/"[FAIL]" lines to stdout AND to a timestamped log
file (test_single_root_pure_python_<timestamp>.log, written next to this
script) so the results can be pasted back or attached. Exit code is 0 only
if every check passed.

This script deliberately does NOT attempt to import arcpy-dependent modules
(ccm_step0_mgcp, ccm_step1_setup, ccm_step2_mobility, ccm_step3_advanced,
the .pyt file, CCM_Data_Scanner_GUI's arcpy-touching bits). Those must be
verified inside ArcGIS Pro — see MANUAL_TEST_CHECKLIST.md.

Usage
-----
    python test_single_root_pure_python.py

Run from anywhere; it locates the CCM_Tool_v0.60.0 folder from its own
file location (it is meant to live inside that folder).
"""

import datetime
import importlib
import io
import json
import os
import shutil
import sys
import tempfile
import traceback

# ---------------------------------------------------------------------------
# Setup
# ---------------------------------------------------------------------------

THIS_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, THIS_DIR)

_TIMESTAMP = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
_LOG_PATH = os.path.join(THIS_DIR, "test_single_root_pure_python_%s.log" % _TIMESTAMP)

_results = []  # list of (name, passed: bool, detail: str)
_log_lines = []


def log(msg=""):
    print(msg)
    _log_lines.append(msg)


def record(name, passed, detail=""):
    _results.append((name, passed, detail))
    status = "[PASS]" if passed else "[FAIL]"
    log("%s %s%s" % (status, name, ("  -- " + detail) if detail else ""))


def section(title):
    log("")
    log("=" * 78)
    log(title)
    log("=" * 78)


# Files that are safe to import in a pure-Python (no arcpy) environment.
# These are exactly the v0.60.0-touched modules that do NOT import arcpy
# at module scope.
PURE_PYTHON_MODULES = [
    "ccm_version",
    "ccm_project_config",
    "ccm_project_init",
    "ccm_step0b_intelligence",
    "ccm_step0b_integration",
    "ccm_step1_recommendations_ui",
    "ccm_data_catalog",
    "ccm_data_quality",
    "ccm_data_fitness",
    "ccm_data_confidence",
    "ccm_data_readiness",
    "ccm_data_selector",
    "ccm_data_report",
    "package_ccm",
]

# Files that are known/expected to require arcpy and are intentionally
# NOT import-checked here (listed for documentation / grep-ability).
ARCPY_ONLY_MODULES = [
    "ccm_step0_mgcp",
    "ccm_step1_setup",
    "ccm_step2_mobility",
    "ccm_step3_advanced",
    "CCM_Tool_v0.60.0.pyt",
]


# ---------------------------------------------------------------------------
# 1. Import-check every pure-Python module touched by v0.60.0
# ---------------------------------------------------------------------------

def check_imports():
    section("1. Import-check pure-Python modules (arcpy-free)")
    for mod_name in PURE_PYTHON_MODULES:
        path = os.path.join(THIS_DIR, mod_name + ".py")
        if not os.path.isfile(path):
            record("import: %s" % mod_name, False, "file not found: %s" % path)
            continue
        try:
            if mod_name in sys.modules:
                importlib.reload(sys.modules[mod_name])
            else:
                importlib.import_module(mod_name)
            record("import: %s" % mod_name, True)
        except Exception as exc:
            record("import: %s" % mod_name, False,
                   "%s: %s" % (type(exc).__name__, exc))
            log(traceback.format_exc())

    log("")
    log("(Not import-checked here -- these require arcpy and must be "
        "verified inside ArcGIS Pro per MANUAL_TEST_CHECKLIST.md:)")
    for mod_name in ARCPY_ONLY_MODULES:
        log("   - %s" % mod_name)


# ---------------------------------------------------------------------------
# 2. ccm_project_config round-trip
# ---------------------------------------------------------------------------

def check_project_config_roundtrip():
    section("2. ccm_project_config.save_config() / load_config() round-trip")
    try:
        import ccm_project_config as cfg_mod
    except Exception as exc:
        record("project_config import", False, str(exc))
        return

    tmpdir = tempfile.mkdtemp(prefix="ccm_cfgtest_")
    try:
        # First write: only project_folder given -- project_root must be
        # auto-populated to match (this is the lock-step guarantee every
        # step's dropdown/default logic depends on).
        cfg_mod.save_config(tmpdir, data_root=os.path.join(tmpdir, "01_Input_Data"))
        cfg1 = cfg_mod.load_config(tmpdir)
        ok = cfg1.get("project_folder") == tmpdir and cfg1.get("project_root") == tmpdir
        record("save_config() auto-fills project_root == project_folder", ok,
               "project_folder=%r project_root=%r" % (cfg1.get("project_folder"), cfg1.get("project_root")))

        # Second write: merge semantics -- new key added, old keys preserved.
        cfg_mod.save_config(tmpdir, vehicle_csv=os.path.join(tmpdir, "vehicles.csv"))
        cfg2 = cfg_mod.load_config(tmpdir)
        ok2 = (cfg2.get("vehicle_csv", "").endswith("vehicles.csv")
               and cfg2.get("data_root") == cfg1.get("data_root")
               and cfg2.get("project_root") == tmpdir)
        record("save_config() merges without clobbering prior keys", ok2,
               "keys=%s" % sorted(cfg2.keys()))

        # ccm_project.json must exist and be valid JSON on disk.
        json_path = os.path.join(tmpdir, "ccm_project.json")
        exists = os.path.isfile(json_path)
        record("ccm_project.json written to project root", exists, json_path)
        if exists:
            with io.open(json_path, "r", encoding="utf-8") as f:
                raw = json.load(f)
            record("ccm_project.json is valid JSON with expected keys",
                   "project_root" in raw and "vehicle_csv" in raw,
                   "keys=%s" % sorted(raw.keys()))
    except Exception as exc:
        record("project_config round-trip", False, "%s: %s" % (type(exc).__name__, exc))
        log(traceback.format_exc())
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


# ---------------------------------------------------------------------------
# 3. ccm_project_init.py headless initialize_project()
# ---------------------------------------------------------------------------

def check_project_init():
    section("3. ccm_project_init.initialize_project() (standalone root-folder tool)")
    try:
        import ccm_project_init as init_mod
    except Exception as exc:
        record("project_init import", False, str(exc))
        return

    tmpdir = tempfile.mkdtemp(prefix="ccm_inittest_")
    try:
        log_msgs = []
        result = init_mod.initialize_project(tmpdir, log=log_msgs.append)

        expect_dirs = ["01_Input_Data", "02_Scan_Index"]
        for d in expect_dirs:
            p = os.path.join(tmpdir, d)
            record("initialize_project creates %s/" % d, os.path.isdir(p), p)

        json_path = os.path.join(tmpdir, "ccm_project.json")
        record("initialize_project writes ccm_project.json", os.path.isfile(json_path), json_path)

        if os.path.isfile(json_path):
            with io.open(json_path, "r", encoding="utf-8") as f:
                cfg = json.load(f)
            expect_keys = ["project_root", "data_root", "scan_index_dir"]
            missing = [k for k in expect_keys if k not in cfg]
            record("ccm_project.json has project_root/data_root/scan_index_dir",
                   not missing, "missing=%s keys=%s" % (missing, sorted(cfg.keys())))
            record("ccm_project.json project_root matches chosen folder",
                   cfg.get("project_root") == tmpdir,
                   "got %r expected %r" % (cfg.get("project_root"), tmpdir))

        record("initialize_project() returned a result dict with expected fields",
               isinstance(result, dict) and "config_path" in result and "warnings" in result,
               "result keys=%s" % (sorted(result.keys()) if isinstance(result, dict) else type(result)))

        # gdb_created should be False (no arcpy here) but must not raise --
        # this proves the function degrades gracefully without ArcGIS Pro.
        record("initialize_project() degrades gracefully without arcpy (no crash)",
               result.get("gdb_created") in (False, True),
               "gdb_created=%r warnings=%s" % (result.get("gdb_created"), result.get("warnings")))
    except Exception as exc:
        record("project_init.initialize_project", False, "%s: %s" % (type(exc).__name__, exc))
        log(traceback.format_exc())
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


# ---------------------------------------------------------------------------
# 4. Step0bIntegrator end-to-end scan against synthetic fixtures
# ---------------------------------------------------------------------------

def check_step0b_integration():
    section("4. ccm_step0b_integration.Step0bIntegrator end-to-end scan "
            "(direct class usage, same path CCM_Data_Scanner_GUI.py now uses)")
    try:
        import ccm_step0b_integration as integ_mod
    except Exception as exc:
        record("step0b_integration import", False, str(exc))
        return

    import subprocess

    tmpdir = tempfile.mkdtemp(prefix="ccm_step0btest_")
    try:
        # Reuse the project's own real fixture generator (tests/make_fake_data.py,
        # pure stdlib -- os/sys/csv/shutil/struct only) exactly the way
        # package_ccm.py's validate_end_to_end() does, so the catalog step
        # gets genuine GeoTIFFs/shapefiles instead of placeholder text files.
        fake_data_script = os.path.join(THIS_DIR, "tests", "make_fake_data.py")
        data_root = os.path.join(tmpdir, "01_Input_Data")
        proc = subprocess.run(
            [sys.executable, "-B", fake_data_script, data_root],
            capture_output=True, text=True)
        made_fixtures = proc.returncode == 0 and os.path.isdir(data_root)
        record("tests/make_fake_data.py builds synthetic fixture data",
               made_fixtures,
               proc.stdout.strip().splitlines()[-1] if made_fixtures and proc.stdout.strip()
               else (proc.stderr or "").strip()[-300:])

        if not made_fixtures:
            # Fall back to a trivial synthetic dataset so the rest of this
            # check can still run (though scoring will be weak/empty).
            os.makedirs(data_root, exist_ok=True)
            with io.open(os.path.join(data_root, "readme.txt"), "w", encoding="utf-8") as f:
                f.write("synthetic fixture placeholder\n")
            os.makedirs(os.path.join(data_root, "roads"), exist_ok=True)
            with io.open(os.path.join(data_root, "roads", "sample.csv"), "w", encoding="utf-8") as f:
                f.write("id,name\n1,Main St\n")

        aoi_path = os.path.join(data_root, "Extent", "AOI_Lebanon.shp")
        aoi_path = aoi_path if os.path.isfile(aoi_path) else None

        integrator = integ_mod.Step0bIntegrator(data_root, aoi_path=aoi_path, project_folder=tmpdir)
        integrator.run(verbose=False)

        report_dir = os.path.join(tmpdir, "02_Scan_Index")
        record("Step0bIntegrator creates 02_Scan_Index/ report dir",
               os.path.isdir(report_dir), report_dir)

        json_path = os.path.join(tmpdir, "ccm_project.json")
        record("Step0bIntegrator writes ccm_project.json at project root (not in 02_Scan_Index)",
               os.path.isfile(json_path), json_path)

        if os.path.isfile(json_path):
            with io.open(json_path, "r", encoding="utf-8") as f:
                cfg = json.load(f)

            record("ccm_project.json has scan_index_dir pointing at 02_Scan_Index",
                   cfg.get("scan_index_dir") == report_dir,
                   "got %r expected %r" % (cfg.get("scan_index_dir"), report_dir))

            path_keys = [k for k in cfg.keys()
                         if k.startswith("data_") and isinstance(cfg.get(k), str)
                         and cfg.get(k, "").lower().endswith((".json", ".html", ".txt", ".csv"))]
            all_exist = True
            for k in path_keys:
                p = cfg[k]
                exists = os.path.isfile(p)
                all_exist = all_exist and exists
                under_scan_index = os.path.dirname(os.path.abspath(p)) == os.path.abspath(report_dir)
                record("  ccm_project.json[%s] file exists on disk" % k, exists, p)
                record("  ccm_project.json[%s] lives under 02_Scan_Index/" % k, under_scan_index, p)

            record("All ccm_project.json report-artifact paths resolve to real files",
                   all_exist and len(path_keys) > 0,
                   "checked %d path keys" % len(path_keys))
    except Exception as exc:
        record("Step0bIntegrator end-to-end run", False, "%s: %s" % (type(exc).__name__, exc))
        log(traceback.format_exc())
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


# ---------------------------------------------------------------------------
# 5. package_ccm.py's own validate_end_to_end() self-check
# ---------------------------------------------------------------------------

def check_package_ccm_validation():
    section("5. package_ccm.validate_end_to_end() self-check")
    try:
        import package_ccm as pkg
    except Exception as exc:
        record("package_ccm import", False, str(exc))
        return

    if not hasattr(pkg, "validate_end_to_end"):
        record("package_ccm.validate_end_to_end exists", False, "function not found")
        return

    tmpdir = tempfile.mkdtemp(prefix="ccm_pkgtest_")
    try:
        # Capture stdout so PASS/FAIL noise from package_ccm doesn't
        # interleave confusingly with ours, but still show it in the log.
        buf = io.StringIO()
        old_stdout = sys.stdout
        sys.stdout = buf
        try:
            ok = pkg.validate_end_to_end(tmpdir)
        finally:
            sys.stdout = old_stdout
        log(buf.getvalue().rstrip())
        record("package_ccm.validate_end_to_end(tmp) returns truthy / PASS",
               bool(ok) if ok is not None else True,
               "return value=%r (None is treated as pass-by-no-exception)" % ok)
    except Exception as exc:
        record("package_ccm.validate_end_to_end", False, "%s: %s" % (type(exc).__name__, exc))
        log(traceback.format_exc())
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    log("CCM_Tool v0.60.0 -- pure-Python verification")
    log("Run at: %s" % datetime.datetime.now().isoformat())
    log("Script dir: %s" % THIS_DIR)

    check_imports()
    check_project_config_roundtrip()
    check_project_init()
    check_step0b_integration()
    check_package_ccm_validation()

    section("SUMMARY")
    n_pass = sum(1 for _, ok, _ in _results if ok)
    n_fail = sum(1 for _, ok, _ in _results if not ok)
    log("Total checks: %d   Passed: %d   Failed: %d" % (len(_results), n_pass, n_fail))
    if n_fail:
        log("")
        log("FAILED CHECKS:")
        for name, ok, detail in _results:
            if not ok:
                log("   - %s%s" % (name, ("  -- " + detail) if detail else ""))
    log("")
    log("Reminder: arcpy-dependent modules (ccm_step0_mgcp, ccm_step1_setup, "
        "ccm_step2_mobility, ccm_step3_advanced, the .pyt itself) are NOT "
        "covered by this script. Run MANUAL_TEST_CHECKLIST.md inside "
        "ArcGIS Pro to verify those.")

    with io.open(_LOG_PATH, "w", encoding="utf-8") as f:
        f.write("\n".join(_log_lines) + "\n")
    log("")
    log("Log written to: %s" % _LOG_PATH)

    return 0 if n_fail == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
# <<< END OF FILE >>>
