# SPDX-License-Identifier: GPL-2.0-or-later
# Copyright (c) 2026 Eui Soo SON
# -*- coding: utf-8 -*-
# tests/arcpy_smoke_test_v0602_fixes.py
# CCM v0.60.2 — REAL ArcGIS Pro verification of the six fixes made in this
# release. Everything test_single_root_pure_python.py and the pytest suites
# already cover does NOT need re-proving here; this script exists only for
# the parts that genuinely need a licensed arcpy to exercise:
#
#   Fix 1  arcpy.env.mask / arcpy.env.extent leak
#          ccm_veg_preprocess.py set arcpy.env.mask at 4 sites and never
#          cleared it; ccm_soil_preprocess.py reset arcpy.env.extent inside
#          the try instead of finally. Because ArcGIS Pro shares one Python
#          process across every open tool, a mask/extent left set here
#          silently clipped every LATER Spatial Analyst call in the same
#          session — Step 2's speed surface, Step 3's isochrones — to a
#          stale AOI, with no error of any kind.
#          Section 1 below proves both the direct code-level fix (env.mask
#          IS restored immediately after the call returns) and the
#          production symptom it prevents (an unrelated raster op run right
#          afterward, at a DIFFERENT location, is not silently masked out).
#
#   Fix 2 "Project GDB not found: None"  (the originally reported bug)
#          Step 0b writes a ccm_project.json with no project_gdb key at
#          all; save_config() materializes it as None; build_speed_surface()
#          used to raise a RuntimeError containing only that bare word.
#          Section 2 proves the runtime error now names the real cause in
#          both its forms (never recorded vs. recorded-but-moved), and
#          Section 3 proves the Step 2 DIALOG guard — which used to require
#          cfg["data_root"] to also be set, so a config with NEITHER key
#          triggered no error at all — now fires on the real condition.
#
# Fixes 3 (project_root/project_folder lock-step), 4 (packaging walk), 5
# (stale .pyt header) and 6 (bump_version.py sidecar rename) need no arcpy
# and are already covered by test_single_root_pure_python.py and the
# pytest suites; they are not repeated here.
#
# HOW TO RUN (1-2 minutes, no external data needed)
# --------------------------------------------------
# Option A — ArcGIS Pro Python window:
#     exec(open(r"C:\...\CCM_Tool_v0.60.2\tests\arcpy_smoke_test_v0602_fixes.py").read())
# Option B — ArcGIS Pro conda prompt / propy.bat:
#     propy.bat tests\arcpy_smoke_test_v0602_fixes.py
#
# Output: PASS/FAIL lines and a final SMOKE TEST PASSED / FAILED verdict.
# Scratch projects are left on disk (path printed) for inspection.
#
VERSION = "0.60.8"

import inspect
import os
import re
import sys
import tempfile
import traceback

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_HERE)
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

# Same pytest-collection guard as the other arcpy_smoke_test_*.py scripts.
if "pytest" in sys.modules:                                   # noqa: E402
    import pytest                                              # noqa: E402
    arcpy = pytest.importorskip(
        "arcpy", reason="requires a licensed ArcGIS Pro install")
else:
    import arcpy  # noqa: E402  (requires a licensed ArcGIS Pro install)

PASS, FAIL = [], []


def check(label, cond, detail=""):
    if cond:
        PASS.append(label)
        print(f"  PASS  {label}")
    else:
        FAIL.append(label)
        print(f"  FAIL  {label}  {detail}")


def make_square(x0, y0, size=100.0, sr=None):
    """Return an arcpy.Polygon square with lower-left corner (x0, y0)."""
    sr = sr or arcpy.SpatialReference(32618)  # UTM 18N — projected CRS
    pts = [(x0, y0), (x0 + size, y0), (x0 + size, y0 + size), (x0, y0 + size)]
    return arcpy.Polygon(arcpy.Array(arcpy.Point(*p) for p in pts), sr)


def _apply_params_by_name(params, **kwargs):
    """Set arcpy.Parameter values by NAME — same helper as the other
    v0.60 dialog-level smoke test."""
    by_name = {p.name: p for p in params}
    unknown = [k for k in kwargs if k not in by_name]
    if unknown:
        raise KeyError(f"unknown parameter(s) {unknown}; valid: {sorted(by_name)}")
    for name, value in kwargs.items():
        p = by_name[name]
        if isinstance(value, (list, tuple)) and getattr(p, "multiValue", False):
            p.values = list(value)
            p.value = ";".join(str(v) for v in value)
        else:
            p.value = value


# =============================================================================
# 1. Fix 1 — arcpy.env.mask / arcpy.env.extent leak
# =============================================================================

def _make_classified_raster(gdb, name, xmin, ymin, size=200, cell=10, value=3):
    """Build a small constant-value integer raster at (xmin, ymin)..(xmin+size,
    ymin+size), saved into gdb, in UTM 18N. Uses NumPyArrayToRaster, the same
    fixture technique ccm_soil_preprocess.py itself uses to build a raster
    from scratch (see its Step 5 / uscs_ras)."""
    import numpy
    sr = arcpy.SpatialReference(32618)
    n = size // cell
    arr = numpy.full((n, n), value, dtype=numpy.int32)
    ras_path = os.path.join(gdb, name)
    if arcpy.Exists(ras_path):
        arcpy.management.Delete(ras_path)
    # No value_to_nodata: every cell in this fixture must be real data, so
    # a masked-out cell (NoData) can only mean the leak actually happened.
    ras = arcpy.NumPyArrayToRaster(arr, arcpy.Point(xmin, ymin), cell, cell)
    ras.save(ras_path)
    arcpy.management.DefineProjection(ras_path, sr)
    return ras_path


def test_env_mask_leak(scratch):
    print("\n" + "-" * 64)
    print("  1. Fix 1 — arcpy.env.mask / arcpy.env.extent leak")
    print("-" * 64)

    import ccm_veg_preprocess as veg

    sa_ok = False
    try:
        sa_ok = (arcpy.CheckExtension("Spatial") == "Available")
    except Exception:
        pass
    if not sa_ok:
        check("Spatial Analyst extension available", False,
              "Section 1 skipped — Spatial Analyst is required to exercise "
              "ExtractByMask/Reclassify and could not be checked out.")
        return
    arcpy.CheckOutExtension("Spatial")

    try:
        root = os.path.join(scratch, "MaskLeak")
        os.makedirs(root, exist_ok=True)
        gdb = os.path.join(root, "Source.gdb")
        arcpy.management.CreateFileGDB(root, "Source.gdb")
        sr = arcpy.SpatialReference(32618)

        # Two DISJOINT areas, far enough apart that one being masked out
        # cannot be mistaken for reprojection/snapping noise from the other.
        raster_a = _make_classified_raster(gdb, "height_a", 0, 0, size=200, value=5)
        raster_b = _make_classified_raster(gdb, "landcover_b", 10000, 10000,
                                            size=200, value=7)

        extent_a = os.path.join(gdb, "extent_a")
        arcpy.management.CreateFeatureclass(gdb, "extent_a", "POLYGON",
                                            spatial_reference=sr)
        with arcpy.da.InsertCursor(extent_a, ["SHAPE@"]) as cur:
            cur.insertRow([make_square(0, 0, 200, sr)])

        # ── 1a. _reclass_height_raster() — GEDI clip site (fix site 1) ──────
        prior_mask = arcpy.env.mask
        classified_path, _lookup = veg._reclass_height_raster(
            raster_a, extent_fc=extent_a, messages=None)
        check("Fix 1a: _reclass_height_raster() ran",
              classified_path is not None and arcpy.Exists(classified_path),
              classified_path)
        check("Fix 1a: arcpy.env.mask restored after _reclass_height_raster()",
              arcpy.env.mask == prior_mask,
              f"env.mask left as {arcpy.env.mask!r}, expected {prior_mask!r}")

        # Production symptom: with the mask now correctly cleared, a plain
        # map-algebra read on raster_b (a location _reclass_height_raster()
        # never touched) must see real data. Before the fix this cell came
        # back NoData, because the leaked mask (extent_a, nowhere near
        # raster_b) silently zeroed the whole raster.
        probe = arcpy.sa.Raster(raster_b) + 0
        val = arcpy.management.GetCellValue(
            probe, f"{10100} {10100}").getOutput(0)
        check("Fix 1a symptom check: unrelated raster at a different AOI "
              "is NOT silently masked out afterward",
              val not in ("NoData", None, ""), f"GetCellValue returned {val!r}")

        # ── 1b. _apply_veg_lookup() — generic landcover clip (fix site 4) ──
        lookup = {7: (0.5, 3.0, 15.0, "test class")}
        out_fc = os.path.join(gdb, "veg_out")
        prior_mask2 = arcpy.env.mask
        result = veg._apply_veg_lookup(
            raster_path=raster_a, lookup=lookup, source_name="TestSource",
            output_fc=out_fc, extent_fc=extent_a, messages=None)
        check("Fix 1b: _apply_veg_lookup() ran", result is not None)
        check("Fix 1b: arcpy.env.mask restored after _apply_veg_lookup()",
              arcpy.env.mask == prior_mask2,
              f"env.mask left as {arcpy.env.mask!r}, expected {prior_mask2!r}")

    finally:
        try:
            arcpy.CheckInExtension("Spatial")
        except Exception:
            pass

    # ── 1c. Structural regression guard for the 2 sites NOT behaviorally
    # exercised above (CanadaBio Closure / LAI refinement — both need a
    # bio_folder with real raster files to reach), plus the soil env.extent
    # fix. Confirms the exact save/restore pattern is present at all 4 + 1
    # sites, so a future edit cannot silently drop the fix at the sites this
    # script does not run live. ─────────────────────────────────────────────
    veg_src = inspect.getsource(veg)
    n_prev_mask = len(re.findall(r"_prev_mask\s*=\s*arcpy\.env\.mask", veg_src))
    n_set_mask = len(re.findall(r"arcpy\.env\.mask\s*=\s*extent_fc", veg_src))
    n_restore_mask = len(re.findall(r"arcpy\.env\.mask\s*=\s*_prev_mask", veg_src))
    check("Fix 1 structural: all 4 env.mask sites save prior value",
          n_prev_mask == 4, f"found {n_prev_mask} _prev_mask saves, expected 4")
    check("Fix 1 structural: all 4 env.mask sites still set the mask",
          n_set_mask == 4, f"found {n_set_mask} sites, expected 4")
    check("Fix 1 structural: all 4 env.mask sites restore it afterward",
          n_restore_mask == 4,
          f"found {n_restore_mask} restores, expected 4")

    import ccm_soil_preprocess as soil
    soil_src = inspect.getsource(soil)
    check("Fix 1 structural (soil): env.extent is saved before use",
          "_prev_extent = arcpy.env.extent" in soil_src)
    check("Fix 1 structural (soil): env.extent restore sits in a finally "
          "block, not inside the try",
          re.search(
              r"finally:\s*\n\s*arcpy\.env\.extent\s*=\s*_prev_extent",
              soil_src) is not None,
          "expected 'arcpy.env.extent = _prev_extent' as the first line "
          "of a finally: block")


# ============================================================================
# 2. Fix 2 (runtime) — build_speed_surface() names the real cause
# ============================================================================

def test_build_speed_surface_error_messages(scratch):
    print("\n" + "-" * 64)
    print("  2. Fix 2 (runtime) — build_speed_surface() GDB error messages")
    print("-" * 64)

    import ccm_project_config as cfg_mod
    import ccm_step2_mobility as step2

    # ── Scenario: Step 0b-only config — project_gdb was never recorded ──────
    project_none = os.path.join(scratch, "Project_GDB_None")
    os.makedirs(project_none, exist_ok=True)
    cfg_mod.save_config(
        project_none, project_root=project_none,
        data_root=os.path.join(project_none, "01_Input_Data"))
    cfg_check = cfg_mod.load_config(project_none)
    check("Scenario fixture: project_gdb is genuinely absent (None)",
          cfg_check.get("project_gdb") is None, cfg_check.get("project_gdb"))

    msg_none = ""
    try:
        step2.build_speed_surface(project_none, "AnyVehicle")
        check("build_speed_surface() raised for missing project_gdb", False,
              "no exception was raised")
    except RuntimeError as exc:
        msg_none = str(exc)
        check("build_speed_surface() raised RuntimeError for missing project_gdb",
              True)
    check("Error message no longer just the bare word 'None'",
          msg_none.strip() != "Project GDB not found: None", msg_none)
    check("Error message says Step 1 has not been run",
          "Step 1" in msg_none and "has not" in msg_none, msg_none)
    check("Error message names this Project Root Folder",
          project_none in msg_none, msg_none)

    # ── Scenario: valid Step 1 config, but the GDB path no longer resolves
    # (the folder was moved/copied — the CHANGELOG's other real-world case) ──
    project_moved = os.path.join(scratch, "Project_GDB_Moved")
    os.makedirs(project_moved, exist_ok=True)
    missing_gdb = os.path.join(project_moved, "03_Project.gdb")
    real_vehicle_csv = os.path.join(_ROOT, "Vehicle_Data", "Vehicles_Can.csv")
    cfg_mod.save_config(
        project_moved, project_root=project_moved, project_gdb=missing_gdb,
        vehicle_csv=real_vehicle_csv)
    check("Scenario fixture: recorded project_gdb does not exist on disk",
          not arcpy.Exists(missing_gdb), missing_gdb)

    msg_moved = ""
    try:
        step2.build_speed_surface(project_moved, "AnyVehicle")
        check("build_speed_surface() raised for a moved/missing GDB", False,
              "no exception was raised")
    except RuntimeError as exc:
        msg_moved = str(exc)
        check("build_speed_surface() raised RuntimeError for a moved/missing GDB",
              True)
    check("Error message says the GDB does not exist on disk",
          "does not exist on disk" in msg_moved, msg_moved)
    check("Error message names the recorded (stale) GDB path",
          missing_gdb in msg_moved, msg_moved)
    check("Error message tells the analyst to re-run Step 1",
          "Step 1" in msg_moved, msg_moved)
    check("The two error messages are meaningfully different from each other",
          msg_none != msg_moved and "does not exist on disk" not in msg_none,
          f"none={msg_none!r}\nmoved={msg_moved!r}")


# =============================================================================
# 3. Fix 2 (dialog) — updateMessages() closes the neither-key gap
# ============================================================================

def test_step2_dialog_neither_key_gap(scratch):
    print("\n" + "-" * 64)
    print("  3. Fix 2 (dialog) — the exact gap this release closes")
    print("-" * 64)
    print("  Before v0.60.2 the guard required BOTH 'not project_gdb' AND")
    print("  'data_root truthy' to fire. A config with NEITHER key set (no")
    print("  project_gdb, no data_root — e.g. an almost-empty or hand-edited")
    print("  ccm_project.json) matched neither this guard nor the Scenario")
    print("  C fallback-warning branch, so updateMessages() said NOTHING at")
    print("  all and the analyst's first signal was the bare runtime error.")

    import ccm_project_config as cfg_mod
    import ccm_step2_mobility as step2

    project_e = os.path.join(scratch, "Project_E_neither_key")
    os.makedirs(project_e, exist_ok=True)
    # Deliberately minimal: no project_gdb, no data_root, no vehicle_csv.
    cfg_mod.save_config(project_e, project_root=project_e)
    cfg_e = cfg_mod.load_config(project_e)
    check("Fixture: project_gdb is absent", not cfg_e.get("project_gdb"),
          cfg_e.get("project_gdb"))
    check("Fixture: data_root is ALSO absent (the specific gap case)",
          not cfg_e.get("data_root"), cfg_e.get("data_root"))

    tool = step2.CCMStep2MobilityTool()
    params = tool.getParameterInfo()
    _apply_params_by_name(params, project_root=project_e)
    tool.updateParameters(params)
    tool.updateMessages(params)

    by_name = {p.name: p for p in params}
    p_folder = by_name["project_root"]
    check("Fix 2 (dialog): an ERROR is now shown for this config "
          "(previously: nothing at all)",
          p_folder.hasError(),
          f"error={p_folder.hasError()} warning={p_folder.hasWarning()} "
          f"message={p_folder.message!r}")
    check("Error message explains Step 1 was never completed here",
          "Step 1" in (p_folder.message or ""), p_folder.message)


def main():
    print("=" * 64)
    print(f"  CCM Tool v{VERSION} — v0.60.2 fix verification (real arcpy)")
    print("=" * 64)

    with tempfile.TemporaryDirectory(prefix="ccm_v0602_fixes_") as scratch:
        print(f"  Scratch root: {scratch}")
        for fn in (test_env_mask_leak,
                   test_build_speed_surface_error_messages,
                   test_step2_dialog_neither_key_gap):
            try:
                fn(scratch)
            except Exception as exc:
                check(f"{fn.__name__}() completed without raising", False,
                      f"{exc}\n{traceback.format_exc()}")

        print("\n" + "=" * 64)
        if FAIL:
            print(f"  SMOKE TEST FAILED — {len(FAIL)} failure(s): {FAIL}")
        else:
            print(f"  SMOKE TEST PASSED — {len(PASS)} checks OK")
        print("=" * 64)
    return not FAIL


if __name__ == "__main__":
    sys.exit(0 if main() else 1)
# <<< END OF FILE >>>
