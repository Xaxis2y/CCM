# SPDX-License-Identifier: GPL-2.0-or-later
# Copyright (c) 2026 Eui Soo SON
# -*- coding: utf-8 -*-
# tests/arcpy_smoke_test_step2.py
# CCM v0.57 — End-to-end Step 2 validation on a REAL ArcGIS Pro installation.
#
# v0.57 post-review "H-4": renamed from tests/arcpy_smoke_test.py (which this
# file's own header, incorrectly, still called "arcpy_smoke_test_step0b.py"
# — a name that collided with the real Step 0b test in this same folder).
# RUN_ARCGIS_SMOKE_TEST.bat previously ran that colliding name and so ran
# the Step 0b Data Intelligence test instead of this Step 2 test — the
# licensed launcher never actually exercised the mobility engine. See
# CHANGELOG_v0.57.md "H-4".
#
# WHAT THIS DOES
# --------------
# Builds a tiny synthetic CCM project from scratch (no external data needed):
#   * a scratch folder + File GDB
#   * a 3x3 grid of soil polygons covering strong/weak/unevaluated USCS codes
#   * a vegetation FC (open / dense / blocking stands)
#   * a slope-regions FC (flat / moderate / impassable)
#   * a water polygon overlapping one cell
#   * a 2-vehicle CSV and a ccm_project.json
# ...then runs ccm_step2_mobility.build_speed_surface() end-to-end and asserts:
#   * the speed-surface FC exists with the full field contract
#   * GO / RESTRICTED / NO GO counts are sane (water cell = NO GO, etc.)
#   * ccm_project.json was updated with mobility_map_fc
#
# HOW TO RUN (2 minutes)
# ----------------------
# Option A — ArcGIS Pro Python window:
#     exec(open(r"C:\...\CCM_Tool_v0.57\tests\arcpy_smoke_test_step0b.py").read())
# Option B — ArcGIS Pro conda prompt:
#     "%PROGRAMFILES%\ArcGIS\Pro\bin\Python\envs\arcgispro-py3\python.exe" tests\arcpy_smoke_test_step0b.py
#
# Output: PASS/FAIL lines and a final SMOKE TEST PASSED / FAILED verdict.
# The scratch project is left on disk (path printed) so you can inspect the
# speed surface visually in ArcGIS Pro and apply the Mobility symbology.
#
VERSION = "0.58.1"  # v0.58.1 -- bumped by bump_version.py from v0.57. Review this line's comment.

import os
import sys
import tempfile
import traceback

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_HERE)
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

# v0.54.4 — a bare top-level `import arcpy` made this module fail at pytest
# COLLECTION time on any machine without ArcGIS Pro, which interrupted the
# whole run ("Interrupted: 1 error during collection") so the 157 real tests
# in test_ccm.py / test_v050.py never executed.  Under pytest we now skip
# cleanly; run directly (python tests/arcpy_smoke_test_step0b.py) the import still
# raises normally, which is the right behaviour for a deliberate smoke run.
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


def make_square(x0, y0, size=100.0):
    """Return an arcpy.Polygon square with lower-left corner (x0, y0)."""
    sr = arcpy.SpatialReference(32618)  # UTM 18N — projected CRS
    pts = [(x0, y0), (x0 + size, y0), (x0 + size, y0 + size), (x0, y0 + size)]
    return arcpy.Polygon(arcpy.Array(arcpy.Point(*p) for p in pts), sr)


def main():
    print("=" * 64)
    print("  CCM v0.57 — Step 2 arcpy smoke test (Generate Mobility Map)")
    print("=" * 64)

    root = tempfile.mkdtemp(prefix="ccm_smoke_")
    print(f"Scratch project: {root}")
    sr = arcpy.SpatialReference(32618)
    arcpy.env.overwriteOutput = True

    gdb = os.path.join(root, "CCM_Project.gdb")
    arcpy.management.CreateFileGDB(root, "CCM_Project.gdb")

    # ── Extent: one 300x300 m square ─────────────────────────────────────────
    extent_fc = os.path.join(gdb, "extent")
    arcpy.management.CreateFeatureclass(gdb, "extent", "POLYGON", spatial_reference=sr)
    with arcpy.da.InsertCursor(extent_fc, ["SHAPE@"]) as cur:
        cur.insertRow([make_square(0, 0, 300)])

    # ── Soil: 3 columns — strong gravel / weak wet clay / peat ───────────────
    soil_fc = os.path.join(gdb, "soil_ccm")
    arcpy.management.CreateFeatureclass(gdb, "soil_ccm", "POLYGON", spatial_reference=sr)
    arcpy.management.AddField(soil_fc, "soilType", "TEXT", field_length=10)
    soil_cols = ["GW", "CH", "Pt"]
    with arcpy.da.InsertCursor(soil_fc, ["SHAPE@", "soilType"]) as cur:
        for c, code in enumerate(soil_cols):
            cur.insertRow([make_square(c * 100, 0, 100).union(
                make_square(c * 100, 100, 100)).union(
                make_square(c * 100, 200, 100)), code])

    # ── Vegetation: 3 rows — open / dense-overridable / blocking stand ───────
    veg_fc = os.path.join(gdb, "veg_ccm")
    arcpy.management.CreateFeatureclass(gdb, "veg_ccm", "POLYGON", spatial_reference=sr)
    for fname, ftype in [("vegetationTrafficImpact", "FLOAT"),
                         ("treeSpacing", "FLOAT"), ("stemDiameter", "FLOAT")]:
        arcpy.management.AddField(veg_fc, fname, ftype)
    veg_rows = [
        (0.05, 30.0, 5.0),    # row 0: open ground
        (0.50, 1.5, 10.0),    # row 1: dense but overridable (small stems)
        (0.90, 1.0, 60.0),    # row 2: blocking — narrow gaps, big stems
    ]
    with arcpy.da.InsertCursor(
        veg_fc, ["SHAPE@", "vegetationTrafficImpact", "treeSpacing", "stemDiameter"]
    ) as cur:
        for r, (vti, sp, st) in enumerate(veg_rows):
            strip = make_square(0, r * 100, 100).union(
                make_square(100, r * 100, 100)).union(
                make_square(200, r * 100, 100))
            cur.insertRow([strip, vti, sp, st])

    # ── Slope: flat everywhere (slope handled by veg/soil variety here) ──────
    slope_fc = os.path.join(gdb, "slope_regions")
    arcpy.management.CreateFeatureclass(gdb, "slope_regions", "POLYGON",
                                        spatial_reference=sr)
    arcpy.management.AddField(slope_fc, "slope_pct", "DOUBLE")
    with arcpy.da.InsertCursor(slope_fc, ["SHAPE@", "slope_pct"]) as cur:
        cur.insertRow([make_square(0, 0, 300), 5.0])

    # ── Hydro: water square over the centre cell ─────────────────────────────
    hydro_fc = os.path.join(gdb, "water")
    arcpy.management.CreateFeatureclass(gdb, "water", "POLYGON", spatial_reference=sr)
    with arcpy.da.InsertCursor(hydro_fc, ["SHAPE@"]) as cur:
        cur.insertRow([make_square(110, 110, 80)])

    # ── Vehicle CSV ───────────────────────────────────────────────────────────
    vehicle_csv = os.path.join(root, "vehicles.csv")
    with open(vehicle_csv, "w", encoding="utf-8") as fh:
        fh.write(
            "name,max_road_spd_kph,max_on_road_grad,max_off_road_grad,"
            "vehicle_width_m,max_override_diameter_m,vci_1,vci_50,"
            "min_turning_radius_m,locomotion_type\n"
            "TestTank,70,60,45,3.6,0.25,25,58,6.0,1\n"
            "TestTruck,80,55,30,2.4,0.05,26,59,5.5,0\n"
        )

    # ── ccm_project.json via Step 1's config writer ──────────────────────────
    import ccm_project_config as cfg
    cfg.save_config(
        root, extent_fc=extent_fc, soil_fc=soil_fc, veg_fc=veg_fc,
        slope_fc=slope_fc, hydro_fcs=[hydro_fc], vehicle_csv=vehicle_csv,
        moisture_default="wet", project_gdb=gdb,
    )
    check("ccm_project.json written", os.path.isfile(os.path.join(root, "ccm_project.json")))

    # ── Run Step 2 ────────────────────────────────────────────────────────────
    import ccm_step2_mobility as s2
    print(f"\nRCI table source: "
          f"{'soil_rci.csv' if os.path.isfile(os.path.join(_ROOT, s2.RCI_CSV_NAME)) else 'built-ins'}")
    try:
        out_fc = s2.build_speed_surface(root, "TestTank", moisture="wet")
        check("build_speed_surface() ran", True)
    except Exception as exc:
        check("build_speed_surface() ran", False, f"{exc}\n{traceback.format_exc()}")
        out_fc = None

    if out_fc:
        check("output FC exists", arcpy.Exists(out_fc), out_fc)

        fields = {f.name for f in arcpy.ListFields(out_fc)}
        for needed in [s2.FIELD_MOBILITY, s2.FIELD_SPEED, s2.FIELD_F1, s2.FIELD_F2,
                       s2.FIELD_F3, s2.FIELD_F4, s2.FIELD_F5, s2.FIELD_FHYDRO]:
            check(f"field {needed}", needed in fields)

        counts = {"GO": 0, "RESTRICTED": 0, "NO GO": 0}
        speeds = []
        with arcpy.da.SearchCursor(out_fc, [s2.FIELD_MOBILITY, s2.FIELD_SPEED,
                                            s2.FIELD_FHYDRO]) as cur:
            water_nogo_ok = True
            for mob, spd, fh in cur:
                counts[mob] = counts.get(mob, 0) + 1
                speeds.append(spd or 0.0)
                if fh == 0.0 and mob != "NO GO":
                    water_nogo_ok = False
        print(f"\n  Class counts: {counts};  max speed {max(speeds):.1f} km/h")
        check("has GO polygons", counts.get("GO", 0) > 0, str(counts))
        check("has NO GO polygons (water / blocking veg / wet peat)",
              counts.get("NO GO", 0) > 0, str(counts))
        check("water cells are NO GO", water_nogo_ok)
        check("speeds within vehicle max", max(speeds) <= 70.0 + 0.01)

        cfg2 = cfg.load_config(root)
        check("config updated with mobility_map_fc",
              cfg2.get("mobility_map_fc") == out_fc)
        check("last_vehicles records TestTank",
              "TestTank" in (cfg2.get("last_vehicles") or []))

        # Weather path: manual override should weaken soils (more NO GO or equal)
        try:
            out2 = s2.build_speed_surface(root, "TestTruck", moisture="wet",
                                          rainfall_override_mm=30.0)
            check("weather-override run", arcpy.Exists(out2))
        except Exception as exc:
            check("weather-override run", False, str(exc))

    print("\n" + "=" * 64)
    if FAIL:
        print(f"  SMOKE TEST FAILED — {len(FAIL)} failure(s): {FAIL}")
    else:
        print(f"  SMOKE TEST PASSED — {len(PASS)} checks OK")
    print(f"  Inspect results in: {gdb}")
    print("=" * 64)
    return not FAIL


if __name__ == "__main__":
    sys.exit(0 if main() else 1)
# <<< END OF FILE >>>
