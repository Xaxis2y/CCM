# SPDX-License-Identifier: GPL-2.0-or-later
# Copyright (c) 2026 Eui Soo SON
# -*- coding: utf-8 -*-
# tests/arcpy_smoke_test_step3.py
# CCM v0.57 — End-to-end Step 3 validation on a REAL ArcGIS Pro installation.
#
# WHAT THIS DOES
# --------------
# Companion to tests/arcpy_smoke_test_step2.py (Step 2), arcpy_smoke_test_step0.py,
# and arcpy_smoke_test_step1.py.  Step 3 — Advanced Analysis — had NO
# end-to-end coverage before v0.54.4, despite bundling five distinct
# sub-analyses (Reason Map, Reachability/Isochrone, Vehicle Comparison,
# Obstacle Detection, Waypoint Routing) plus the map auto-load/styling path
# that received most of the ccm_map_display.py fixes in this release series.
#
# Builds the same proven 3x3-grid fixture as tests/arcpy_smoke_test_step2.py, runs
# TWO real Step 2 speed surfaces (TestTank, TestTruck), then invokes
# CCMStep3AdvancedTool via ccm_project_config.run_tool() with ALL FIVE
# analyses enabled in a single call — exactly how a user would run Step 3 with
# every checkbox ticked — and asserts real outputs for each:
#   A. Reason Map        — NO_GO_REASON / RESTRICT_CODE added to the speed
#                           surface IN PLACE (it has no separate output FC)
#   B. Isochrone          — reachability-ring FC with a TIME_BAND field
#   C. Vehicle Compare    — comparison FC with a COMPARE_RESULT field
#   D. Obstacle Detection — obstacle FC (zero obstacles is a valid outcome —
#                           see the User Manual's own Troubleshooting section)
#   E. Waypoint Routing   — route FC from a GO-cell corner to a NO-GO-cell
#                           corner, deliberately exercising ccm_waypoints.py's
#                           documented "No-Go snap fallback"; a route that
#                           legitimately cannot be found is also a valid,
#                           non-fatal outcome and is reported, not failed
#
# Also confirms the v0.54.2-v0.54.4 map-auto-load path degrades safely when
# there is no live ArcGIS Pro map session (arcpy.mp.ArcGISProject("CURRENT")
# is expected to raise here and IS caught internally by execute() itself —
# see ccm_step3_advanced.py's outer try/except around the auto-load block —
# so this whole run is expected to complete via a caught, non-fatal warning
# rather than a hard failure).
#
# HOW TO RUN (2-3 minutes)
# ------------------------
# Option A — ArcGIS Pro Python window (recommended — a live map session lets
#            the auto-load/styling path run for real instead of degrading):
#     exec(open(r"C:\...\CCM_Tool_v0.57\tests\arcpy_smoke_test_step3.py").read())
# Option B — ArcGIS Pro conda prompt (headless — auto-load degrades safely):
#     "%PROGRAMFILES%\ArcGIS\Pro\bin\Python\envs\arcgispro-py3\python.exe" tests\arcpy_smoke_test_step3.py
#
# Output: PASS/FAIL lines and a final SMOKE TEST PASSED / FAILED verdict.
# The scratch project is left on disk (path printed) so you can inspect every
# output feature class directly, or open the project in Pro and re-run Step 3
# interactively against the same data to see the styled map.
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

# Same pytest-collection guard as tests/arcpy_smoke_test_step2.py (v0.54.4 fix).
if "pytest" in sys.modules:                                   # noqa: E402
    import pytest                                             # noqa: E402
    arcpy = pytest.importorskip(
        "arcpy", reason="requires a licensed ArcGIS Pro install")
else:
    import arcpy  # noqa: E402  (requires a licensed ArcGIS Pro install)

PASS, FAIL, INFO = [], [], []


def check(label, cond, detail=""):
    if cond:
        PASS.append(label)
        print(f"  PASS  {label}")
    else:
        FAIL.append(label)
        print(f"  FAIL  {label}  {detail}")


def note(label, detail=""):
    """A non-fatal, informational outcome — reported but never fails the run."""
    INFO.append(label)
    print(f"  INFO  {label}  {detail}")


class _FakeMessages:
    """
    Minimal stand-in for the arcpy `messages` object passed to execute().
    Step 3 forwards this into every sub-tool it drives internally (Reason
    Map, Isochrone, Vehicle Compare, Obstacle Detection, Waypoint Routing),
    so a real object with these three methods is required throughout.
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


def _dd_string(x, y, sr):
    """
    Project a projected-CRS (x, y) to a hemisphere-formatted decimal-degrees
    string, e.g. "40.123456N 75.654321W" — the exact format
    ccm_step3_advanced.py builds internally for its own iso/waypoint
    parameters, so ccm_coords.detect_format()/any_to_latlon() are guaranteed
    to round-trip it correctly.
    """
    pt = arcpy.PointGeometry(arcpy.Point(float(x), float(y)), sr)
    ll = pt.projectAs(arcpy.SpatialReference(4326)).centroid
    lat, lon = ll.Y, ll.X
    return (f"{abs(lat):.6f}{'N' if lat >= 0 else 'S'} "
            f"{abs(lon):.6f}{'E' if lon >= 0 else 'W'}")


def build_fixtures(root):
    """Same proven 3x3-grid fixture as tests/arcpy_smoke_test_step2.py."""
    sr = arcpy.SpatialReference(32618)
    gdb = os.path.join(root, "CCM_Project.gdb")
    arcpy.management.CreateFileGDB(root, "CCM_Project.gdb")

    extent_fc = os.path.join(gdb, "extent")
    arcpy.management.CreateFeatureclass(gdb, "extent", "POLYGON", spatial_reference=sr)
    with arcpy.da.InsertCursor(extent_fc, ["SHAPE@"]) as cur:
        cur.insertRow([make_square(0, 0, 300, sr)])

    soil_fc = os.path.join(gdb, "soil_ccm")
    arcpy.management.CreateFeatureclass(gdb, "soil_ccm", "POLYGON", spatial_reference=sr)
    arcpy.management.AddField(soil_fc, "soilType", "TEXT", field_length=10)
    soil_cols = ["GW", "CH", "Pt"]
    with arcpy.da.InsertCursor(soil_fc, ["SHAPE@", "soilType"]) as cur:
        for c, code in enumerate(soil_cols):
            cur.insertRow([make_square(c * 100, 0, 100, sr).union(
                make_square(c * 100, 100, 100, sr)).union(
                make_square(c * 100, 200, 100, sr)), code])

    veg_fc = os.path.join(gdb, "veg_ccm")
    arcpy.management.CreateFeatureclass(gdb, "veg_ccm", "POLYGON", spatial_reference=sr)
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

    slope_fc = os.path.join(gdb, "slope_regions")
    arcpy.management.CreateFeatureclass(gdb, "slope_regions", "POLYGON", spatial_reference=sr)
    arcpy.management.AddField(slope_fc, "slope_pct", "DOUBLE")
    with arcpy.da.InsertCursor(slope_fc, ["SHAPE@", "slope_pct"]) as cur:
        cur.insertRow([make_square(0, 0, 300, sr), 5.0])

    hydro_fc = os.path.join(gdb, "water")
    arcpy.management.CreateFeatureclass(gdb, "water", "POLYGON", spatial_reference=sr)
    with arcpy.da.InsertCursor(hydro_fc, ["SHAPE@"]) as cur:
        cur.insertRow([make_square(110, 110, 80, sr)])

    return gdb, extent_fc, soil_fc, veg_fc, slope_fc, hydro_fc, sr


def main():
    print("=" * 64)
    print("  CCM v0.57 — Step 3 arcpy smoke test (Advanced Analysis)")
    print("=" * 64)

    root = tempfile.mkdtemp(prefix="ccm_smoke_step3_")
    print(f"Scratch project: {root}")
    arcpy.env.overwriteOutput = True

    import ccm_project_config as cfg_mod
    import ccm_step2_mobility as s2
    import ccm_step3_advanced as step3

    gdb, extent_fc, soil_fc, veg_fc, slope_fc, hydro_fc, sr = build_fixtures(root)
    check("fixtures built", all(arcpy.Exists(p) for p in
          (extent_fc, soil_fc, veg_fc, slope_fc, hydro_fc)))

    vehicle_csv = os.path.join(root, "vehicles.csv")
    with open(vehicle_csv, "w", encoding="utf-8") as fh:
        fh.write(
            "name,max_road_spd_kph,max_on_road_grad,max_off_road_grad,"
            "vehicle_width_m,max_override_diameter_m,vci_1,vci_50,"
            "min_turning_radius_m,locomotion_type\n"
            "TestTank,70,60,45,3.6,0.25,25,58,6.0,1\n"
            "TestTruck,80,55,30,2.4,0.05,26,59,5.5,0\n"
        )

    cfg_mod.save_config(
        root, extent_fc=extent_fc, soil_fc=soil_fc, veg_fc=veg_fc,
        slope_fc=slope_fc, hydro_fcs=[hydro_fc], vehicle_csv=vehicle_csv,
        moisture_default="wet", project_gdb=gdb,
    )

    # ── Two real Step 2 speed surfaces (needed for Vehicle Compare) ─────────
    try:
        speed_fc_a = s2.build_speed_surface(root, "TestTank", moisture="wet")
        speed_fc_b = s2.build_speed_surface(root, "TestTruck", moisture="wet")
        check("both Step 2 speed surfaces built", True)
    except Exception as exc:
        check("both Step 2 speed surfaces built", False,
              f"{exc}\n{traceback.format_exc()}")
        speed_fc_a = speed_fc_b = None

    if not (speed_fc_a and arcpy.Exists(speed_fc_a)):
        print("\nCannot continue without a speed surface — aborting.")
        print(f"  SMOKE TEST FAILED — {len(FAIL)} failure(s): {FAIL}")
        return False

    # Start point: middle of the (0,0)-(100,100) cell — best soil (GW) +
    # open vegetation (row 0) — very likely GO.
    start_dd = _dd_string(50, 50, sr)
    # End point: middle of the (200,200)-(300,300) cell — worst soil (Pt
    # peat) + blocking vegetation (row 2) — very likely NO GO.  Deliberately
    # chosen to exercise ccm_waypoints.py's documented "No-Go snap fallback"
    # rather than a trivially-easy same-cell route.
    end_dd = _dd_string(250, 250, sr)
    print(f"\nIsochrone / route start point : {start_dd}")
    print(f"Route end point               : {end_dd}")

    # ── Run Step 3 with ALL FIVE analyses enabled in one call ──────────────
    # msgs is kept (not inlined) so the Isochrone check below can inspect
    # msgs.warnings for the v0.54.6 SA->vector fallback notice.
    msgs = _FakeMessages("[Step3-smoke]")
    try:
        cfg_mod.run_tool(
            step3.CCMStep3AdvancedTool(), msgs,
            project_folder=root,
            speed_surface_fc=speed_fc_a,
            soil_moisture="wet",
            run_reason_map=True,
            rm_mobility_field="Mobility",
            run_isochrone=True,
            iso_start_point=start_dd,
            iso_time_intervals="15,30,60,120",
            iso_speed_field="SpeedKMH",
            run_vehicle_compare=True,
            vc_fc_b=speed_fc_b,
            vc_name_a="TestTank",
            vc_name_b="TestTruck",
            run_obstacle_detect=True,
            obs_hydro_fc=hydro_fc,
            run_waypoint_route=True,
            wp_start_point=start_dd,
            wp_end_point=end_dd,
            wp_speed_field="SpeedKMH",
        )
        check("Step 3 execute() ran (all 5 analyses enabled)", True)
    except Exception as exc:
        check("Step 3 execute() ran (all 5 analyses enabled)", False,
              f"{exc}\n{traceback.format_exc()}")

    # ── A. Reason Map — modifies the speed surface IN PLACE ────────────────
    fields_a = {f.name for f in arcpy.ListFields(speed_fc_a)}
    check("A. Reason Map: NO_GO_REASON field added", "NO_GO_REASON" in fields_a,
          sorted(fields_a))
    check("A. Reason Map: RESTRICT_CODE field added", "RESTRICT_CODE" in fields_a,
          sorted(fields_a))

    # ── B. Isochrone ─────────────────────────────────────────────────────────
    iso_fc = os.path.join(gdb, "testtank_wet_isochrone")
    if arcpy.Exists(iso_fc):
        check("B. Isochrone: output FC exists", True)
        iso_fields = {f.name for f in arcpy.ListFields(iso_fc)}
        check("B. Isochrone: TIME_BAND field present", "TIME_BAND" in iso_fields,
              sorted(iso_fields))
        n_iso = int(arcpy.management.GetCount(iso_fc)[0])
        check("B. Isochrone: has at least one ring", n_iso > 0, f"count={n_iso}")
        # v0.54.6: the Spatial Analyst path can fail (ERROR 160333) and fall
        # back to the vector method inside generate_isochrones() — that
        # still produces a valid, passing output FC above, so surface which
        # method actually ran rather than letting it pass silently either way.
        #
        # v0.54.7 fix: checking msgs.warnings here was wrong and, confirmed
        # by a real run, silently reported the WRONG path — ccm_isochrone.py
        # logs via the global arcpy.AddWarning(), not via the `messages`
        # object passed into run_tool(), so msgs.warnings never actually
        # receives that text and the check always fell through to the
        # "Spatial Analyst path" branch regardless of what really ran.
        # "gridcode" is a reliable discriminator instead: RasterToPolygon
        # (the SA path's last step) always adds it; Dissolve (the vector
        # path's last step) never does — this is read straight from each
        # method's own code, not inferred.
        if "gridcode" in iso_fields:
            note("B. Isochrone: produced via Spatial Analyst path (DistanceAccumulation)")
        else:
            note("B. Isochrone: produced via VECTOR fallback (Spatial Analyst path failed)")
    else:
        check("B. Isochrone: output FC exists", False, iso_fc)

    # ── C. Vehicle Compare ───────────────────────────────────────────────────
    vc_fc = os.path.join(gdb, "testtank_wet_vehicle_compare")
    if arcpy.Exists(vc_fc):
        check("C. Vehicle Compare: output FC exists", True)
        vc_fields = {f.name for f in arcpy.ListFields(vc_fc)}
        check("C. Vehicle Compare: COMPARE_RESULT field present",
              "COMPARE_RESULT" in vc_fields, sorted(vc_fields))
        if "COMPARE_RESULT" in vc_fields:
            values = set()
            with arcpy.da.SearchCursor(vc_fc, ["COMPARE_RESULT"]) as cur:
                for (v,) in cur:
                    values.add(v)
            valid = {"BOTH_GO", "A_ONLY", "B_ONLY", "NEITHER", "DATA_GAP"}
            check("C. Vehicle Compare: values are all valid categories",
                  values.issubset(valid), values)
    else:
        check("C. Vehicle Compare: output FC exists", False, vc_fc)

    # ── D. Obstacle Detection ────────────────────────────────────────────────
    # Zero obstacles is a documented, valid outcome (see the User Manual's
    # Troubleshooting section) — only the FC's existence is asserted.
    obs_fc = os.path.join(gdb, "testtank_wet_obstacles")
    if arcpy.Exists(obs_fc):
        check("D. Obstacle Detection: output FC exists", True)
        n_obs = int(arcpy.management.GetCount(obs_fc)[0])
        note("D. Obstacle Detection: feature count", f"count={n_obs}")
    else:
        check("D. Obstacle Detection: output FC exists", False, obs_fc)

    # ── E. Waypoint Routing ──────────────────────────────────────────────────
    # A route that cannot be found is also a valid, non-fatal outcome (see
    # ccm_step3_advanced.py: "produced no route output (no passable path
    # found) — nothing added to the map").  Only report, don't fail, unless
    # execute() itself raised (already caught above).
    route_fc = os.path.join(gdb, "testtank_wet_route")
    if arcpy.Exists(route_fc):
        n_route = int(arcpy.management.GetCount(route_fc)[0])
        check("E. Waypoint Routing: route FC exists with geometry",
              n_route > 0, f"count={n_route}")
    else:
        note("E. Waypoint Routing: no route FC",
             "no passable path found between the chosen GO/NO-GO corners — "
             "this is a valid outcome, not a failure; re-run with different "
             "start/end points to force a route if you need to inspect one")

    print("\n" + "=" * 64)
    if FAIL:
        print(f"  SMOKE TEST FAILED — {len(FAIL)} failure(s): {FAIL}")
    else:
        print(f"  SMOKE TEST PASSED — {len(PASS)} checks OK "
              f"({len(INFO)} informational note(s))")
    print(f"  Inspect results in: {gdb}")
    print("=" * 64)
    return not FAIL


if __name__ == "__main__":
    sys.exit(0 if main() else 1)
# <<< END OF FILE >>>
