# SPDX-License-Identifier: GPL-2.0-or-later
# Copyright (c) 2026 Eui Soo SON
# -*- coding: utf-8 -*-
# tests/arcpy_smoke_test_step1.py
# CCM v0.56.0 — End-to-end Step 1 validation on a REAL ArcGIS Pro installation.
#
# WHAT THIS DOES
# --------------
# Companion to tests/arcpy_smoke_test.py (Step 2 only) and
# tests/arcpy_smoke_test_step0.py (Step 0 only).  Step 1 had NO end-to-end
# coverage before v0.54.4: Step 2's own smoke test fabricates ccm_project.json
# directly via ccm_project_config.save_config(), bypassing Step 1's execute()
# entirely, so the real Step 1 -> Step 2 hand-off had never actually been
# exercised.
#
# Builds a tiny synthetic CCM project from scratch (no external data needed):
#   * a scratch output folder
#   * an Analysis Extent polygon (Projected CRS)
#   * an ALREADY-preprocessed soil FC, vegetation FC, and slope-regions FC —
#     supplied via Step 1's own soil_preproc_fc / veg_preproc_fc /
#     slope_regions_fc "use existing / skip pre-processing" parameters, so
#     this exercises Step 1's config-writing and hand-off logic without also
#     re-testing the six soil-source and seven vegetation-source preprocessing
#     branches (those already have dedicated coverage in test_ccm.py)
#   * a hydrology (water) polygon
#   * the real Vehicles_Can.csv shipped in Vehicle_Data/
# ...then:
#   1. invokes CCMStep1SetupTool via ccm_project_config.run_tool() (the
#      project's own "invoke by parameter NAME" convention) and asserts
#      ccm_project.json was written with every field pointing at what was
#      supplied;
#   2. feeds that REAL ccm_project.json straight into
#      ccm_step2_mobility.build_speed_surface() — proving the actual
#      Step 1 -> Step 2 hand-off works end-to-end, not just that each step
#      works in isolation against a hand-crafted config.
#
# HOW TO RUN (1-2 minutes)
# ------------------------
# Option A — ArcGIS Pro Python window:
#     exec(open(r"C:\...\CCM_Tool_v0.56.0\tests\arcpy_smoke_test_step1.py").read())
# Option B — ArcGIS Pro conda prompt:
#     "%PROGRAMFILES%\ArcGIS\Pro\bin\Python\envs\arcgispro-py3\python.exe" tests\arcpy_smoke_test_step1.py
#
# Output: PASS/FAIL lines and a final SMOKE TEST PASSED / FAILED verdict.
# The scratch project is left on disk (path printed) so you can inspect the
# project GDB and ccm_project.json directly.
#
VERSION = "0.56.0"  # v0.56.0 -- MGCP loader (Step 0): Point/Line/Polygon map groups, FACC-category + name-keyword fallback classification (no more "Unknown feature"), readable GDB aliases, user-editable mgcp_catalog_user.csv override, .lyrx group templates, scale-dependent detail layers, and hardened Unknown-CRS repair. See CHANGELOG_v0.56.md.

import os
import sys
import tempfile
import traceback

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_HERE)
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

# Same pytest-collection guard as tests/arcpy_smoke_test.py (v0.54.4 fix).
if "pytest" in sys.modules:                                   # noqa: E402
    import pytest                                             # noqa: E402
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


class _FakeMessages:
    """
    Minimal stand-in for the arcpy `messages` object passed to execute().
    Step 1's own execute() logic uses plain arcpy.AddMessage/AddWarning and
    only forwards `messages` into nested run_tool() calls (soil/veg
    pre-processing) which we bypass here via soil_preproc_fc/veg_preproc_fc —
    but a real object is supplied regardless, matching the other two new
    smoke tests, so nothing downstream can be surprised by a bare None.
    """
    def __init__(self, prefix="[msg]"):
        self.prefix = prefix
        self.messages, self.warnings, self.errors = [], [], []

    def addMessage(self, text):
        self.messages.append(text)
        print(f"{self.prefix} {text}")

    def addWarningMessage(self, text):
        self.warnings.append(text)
        print(f"{self.prefix} WARNING: {text}")

    def addErrorMessage(self, text):
        self.errors.append(text)
        print(f"{self.prefix} ERROR: {text}")


def make_square(x0, y0, size=100.0, sr=None):
    """Return an arcpy.Polygon square with lower-left corner (x0, y0)."""
    sr = sr or arcpy.SpatialReference(32618)  # UTM 18N — projected CRS
    pts = [(x0, y0), (x0 + size, y0), (x0 + size, y0 + size), (x0, y0 + size)]
    return arcpy.Polygon(arcpy.Array(arcpy.Point(*p) for p in pts), sr)


def build_fixtures(root):
    """
    Build an Analysis Extent + already-CCM-ready soil / veg / slope / hydro
    feature classes, in the same schema ccm_step2_mobility.build_speed_surface
    expects (soilType / vegetationTrafficImpact+treeSpacing+stemDiameter /
    slope_pct) — mirroring tests/arcpy_smoke_test.py's proven fixture.
    """
    sr = arcpy.SpatialReference(32618)
    gdb = os.path.join(root, "CCM_Source.gdb")
    arcpy.management.CreateFileGDB(root, "CCM_Source.gdb")

    extent_fc = os.path.join(gdb, "extent")
    arcpy.management.CreateFeatureclass(gdb, "extent", "POLYGON", spatial_reference=sr)
    with arcpy.da.InsertCursor(extent_fc, ["SHAPE@"]) as cur:
        cur.insertRow([make_square(0, 0, 300, sr)])

    soil_fc = os.path.join(gdb, "soil_preproc")
    arcpy.management.CreateFeatureclass(gdb, "soil_preproc", "POLYGON", spatial_reference=sr)
    arcpy.management.AddField(soil_fc, "soilType", "TEXT", field_length=10)
    soil_cols = ["GW", "CH", "Pt"]
    with arcpy.da.InsertCursor(soil_fc, ["SHAPE@", "soilType"]) as cur:
        for c, code in enumerate(soil_cols):
            cur.insertRow([make_square(c * 100, 0, 100, sr).union(
                make_square(c * 100, 100, 100, sr)).union(
                make_square(c * 100, 200, 100, sr)), code])

    veg_fc = os.path.join(gdb, "veg_preproc")
    arcpy.management.CreateFeatureclass(gdb, "veg_preproc", "POLYGON", spatial_reference=sr)
    for fname, ftype in [("vegetationTrafficImpact", "FLOAT"),
                         ("treeSpacing", "FLOAT"), ("stemDiameter", "FLOAT")]:
        arcpy.management.AddField(veg_fc, fname, ftype)
    veg_rows = [(0.05, 30.0, 5.0), (0.50, 1.5, 10.0), (0.90, 1.0, 60.0)]
    with arcpy.da.InsertCursor(
        veg_fc, ["SHAPE@", "vegetationTrafficImpact", "treeSpacing", "stemDiameter"]
    ) as cur:
        for r, (vti, sp, st) in enumerate(veg_rows):
            strip = make_square(0, r * 100, 100, sr).union(
                make_square(100, r * 100, 100, sr)).union(
                make_square(200, r * 100, 100, sr))
            cur.insertRow([strip, vti, sp, st])

    slope_fc = os.path.join(gdb, "slope_preproc")
    arcpy.management.CreateFeatureclass(gdb, "slope_preproc", "POLYGON", spatial_reference=sr)
    arcpy.management.AddField(slope_fc, "slope_pct", "DOUBLE")
    with arcpy.da.InsertCursor(slope_fc, ["SHAPE@", "slope_pct"]) as cur:
        cur.insertRow([make_square(0, 0, 300, sr), 5.0])

    hydro_fc = os.path.join(gdb, "water")
    arcpy.management.CreateFeatureclass(gdb, "water", "POLYGON", spatial_reference=sr)
    with arcpy.da.InsertCursor(hydro_fc, ["SHAPE@"]) as cur:
        cur.insertRow([make_square(110, 110, 80, sr)])

    return extent_fc, soil_fc, veg_fc, slope_fc, hydro_fc


def main():
    print("=" * 64)
    print("  CCM v0.56.0 — Step 1 arcpy smoke test (Project Setup & Pre-process)")
    print("=" * 64)

    root = tempfile.mkdtemp(prefix="ccm_smoke_step1_")
    print(f"Scratch project: {root}")
    arcpy.env.overwriteOutput = True

    import ccm_project_config as cfg_mod
    import ccm_step1_setup as step1

    extent_fc, soil_fc, veg_fc, slope_fc, hydro_fc = build_fixtures(root)
    check("fixtures built", all(arcpy.Exists(p) for p in
          (extent_fc, soil_fc, veg_fc, slope_fc, hydro_fc)))

    vehicle_csv = os.path.join(_ROOT, "Vehicle_Data", "Vehicles_Can.csv")
    check("real Vehicles_Can.csv found", os.path.isfile(vehicle_csv), vehicle_csv)

    project_folder = os.path.join(root, "CCM_Project")

    # ── Run Step 1 for real, via the project's own run_tool() convention ────
    try:
        cfg_mod.run_tool(
            step1.CCMStep1SetupTool(), _FakeMessages("[Step1-smoke]"),
            project_folder=project_folder,
            extent_fc=extent_fc,
            slope_regions_fc=slope_fc,
            soil_moisture="wet",
            soil_gap_fill="Smart (auto)",
            soil_preproc_fc=soil_fc,
            veg_preproc_fc=veg_fc,
            hydro_fcs=[hydro_fc],
            vehicle_csv=vehicle_csv,
        )
        check("Step 1 execute() ran", True)
    except Exception as exc:
        check("Step 1 execute() ran", False, f"{exc}\n{traceback.format_exc()}")

    project_gdb = os.path.join(project_folder, "CCM_Project.gdb")
    check("project GDB created", arcpy.Exists(project_gdb), project_gdb)

    cfg_path = os.path.join(project_folder, "ccm_project.json")
    check("ccm_project.json written", os.path.isfile(cfg_path), cfg_path)

    cfg = cfg_mod.load_config(project_folder) if os.path.isfile(cfg_path) else {}
    check("config extent_fc matches", cfg.get("extent_fc") == extent_fc,
          cfg.get("extent_fc"))
    check("config soil_fc matches (soil_preproc_fc pass-through)",
          cfg.get("soil_fc") == soil_fc, cfg.get("soil_fc"))
    check("config veg_fc matches (veg_preproc_fc pass-through)",
          cfg.get("veg_fc") == veg_fc, cfg.get("veg_fc"))
    check("config slope_fc matches (slope_regions_fc pass-through — DEM "
          "derivation skipped)", cfg.get("slope_fc") == slope_fc,
          cfg.get("slope_fc"))
    check("config hydro_fcs matches", cfg.get("hydro_fcs") == [hydro_fc],
          cfg.get("hydro_fcs"))
    check("config vehicle_csv matches", cfg.get("vehicle_csv") == vehicle_csv,
          cfg.get("vehicle_csv"))
    check("config moisture_default == wet", cfg.get("moisture_default") == "wet",
          cfg.get("moisture_default"))

    # ── The real hand-off: feed Step 1's OWN ccm_project.json into Step 2 ───
    # This is the part Step 2's own smoke test cannot prove, since it builds
    # ccm_project.json directly rather than via a real Step 1 run.
    if os.path.isfile(cfg_path):
        import ccm_step2_mobility as s2
        try:
            # v0.54.5 fix: this call feeds the REAL Vehicles_Can.csv (see
            # vehicle_csv above), which does not contain "TestTank" — that
            # name only exists in the synthetic CSVs used by the Step 2 and
            # Step 3 smoke tests. "M1" is a real vehicle row in the shipped
            # CSV, confirmed against a live-run failure log that listed all
            # available names.
            out_fc = s2.build_speed_surface(project_folder, "M1", moisture="wet")
            check("Step 1 -> Step 2 hand-off: build_speed_surface() ran", True)
        except Exception as exc:
            check("Step 1 -> Step 2 hand-off: build_speed_surface() ran", False,
                  f"{exc}\n{traceback.format_exc()}")
            out_fc = None

        if out_fc:
            check("hand-off output FC exists", arcpy.Exists(out_fc), out_fc)
            fields = {f.name for f in arcpy.ListFields(out_fc)}
            check("hand-off output has Mobility field", s2.FIELD_MOBILITY in fields)
            check("hand-off output has SpeedKMH field", s2.FIELD_SPEED in fields)
            n = int(arcpy.management.GetCount(out_fc)[0])
            check("hand-off output has features", n > 0, f"count={n}")

    print("\n" + "=" * 64)
    if FAIL:
        print(f"  SMOKE TEST FAILED — {len(FAIL)} failure(s): {FAIL}")
    else:
        print(f"  SMOKE TEST PASSED — {len(PASS)} checks OK")
    print(f"  Inspect results in: {project_gdb}")
    print("=" * 64)
    return not FAIL


if __name__ == "__main__":
    sys.exit(0 if main() else 1)
# <<< END OF FILE >>>
