# SPDX-License-Identifier: GPL-2.0-or-later
# Copyright (c) 2026 Eui Soo SON
# -*- coding: utf-8 -*-
# tests/arcpy_smoke_test_v060_single_root.py
# CCM v0.60.0 — End-to-end verification of the single-root rewrite on a REAL
# ArcGIS Pro installation.
#
# WHAT THIS DOES
# --------------
# test_single_root_pure_python.py (project root) already verifies everything
# that does NOT need arcpy. The six existing tests/arcpy_smoke_test_*.py
# scripts call each tool's execute() directly via
# ccm_project_config.run_tool(), which proves the tools RUN correctly but
# never exercises updateParameters()/updateMessages() — the dialog-time
# callbacks ArcGIS Pro's Geoprocessing pane calls continuously as you fill in
# a tool, and the ONLY place the single-root rewrite's most user-visible
# behavior actually lives:
#   * Step 0's "just choosing a Project Root Folder creates the layout,
#     before you click Run" behavior
#   * Step 2's Vehicle dropdown populating (or not) — the original bug
#     report this whole rewrite exists to fix
#   * Step 3's project-GDB resolution fallback when a speed surface's own
#     workspace is unusable
#
# This script drives those dialog callbacks directly — arcpy.Parameter
# objects and updateParameters()/updateMessages() work identically whether
# called from this script or from ArcGIS Pro's own dialog, since the dialog
# is just calling these same Python methods. No manual GUI interaction is
# exercised end-to-end here; MANUAL_TEST_CHECKLIST.md Section B still
# has value as a real-eyes check on the actual Pro dialog, but everything it
# describes checking is now also asserted automatically here.
#
# SECTIONS
# --------
#   1. Step 0 — dialog-time single-root layout creation (updateParameters()
#      alone, execute() never called)
#   2. Step 1 — build a real project via execute() (reused as the Scenario A
#      fixture for section 3)
#   3. Step 2 — Vehicle dropdown Scenarios A / B / C + the Step-0b-file
#      negative control, each via updateParameters()+updateMessages()
#   4. Step 3 — _derive_output_path() GDB-resolution fallback: config-first,
#      then either GDB name on disk, then scratchGDB
#
# HOW TO RUN (2-3 minutes)
# ------------------------
# Option A — ArcGIS Pro Python window:
#     exec(open(r"C:\...\CCM_Tool_v0.60.0\tests\arcpy_smoke_test_v060_single_root.py").read())
# Option B — ArcGIS Pro conda prompt / propy.bat:
#     propy.bat tests\arcpy_smoke_test_v060_single_root.py
# (RUN_ARCGIS_SMOKE_TEST.bat runs this alongside the other six automatically.)
#
# Output: PASS/FAIL lines and a final SMOKE TEST PASSED / FAILED verdict.
# Scratch projects are left on disk (paths printed) for inspection.
#
VERSION = "0.60.8"

import io
import json
import os
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


class _FakeMessages:
    """Minimal stand-in for the arcpy `messages` object passed to execute()."""
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


def _apply_params_by_name(params, **kwargs):
    """
    Set arcpy.Parameter values by NAME rather than positional index — the
    same convention ccm_project_config.run_tool() uses, but WITHOUT calling
    execute() at the end, so updateParameters()/updateMessages() can be
    driven directly (dialog-time behavior, never exercised by run_tool()).
    """
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


def make_square(x0, y0, size=100.0, sr=None):
    sr = sr or arcpy.SpatialReference(32618)  # UTM 18N — projected CRS
    pts = [(x0, y0), (x0 + size, y0), (x0 + size, y0 + size), (x0, y0 + size)]
    return arcpy.Polygon(arcpy.Array(arcpy.Point(*p) for p in pts), sr)


def build_step1_fixtures(root):
    """
    Already-CCM-ready soil / veg / slope / hydro feature classes, mirroring
    tests/arcpy_smoke_test_step1.py's proven fixture set, so Step 1's config
    ends up with soil_fc/veg_fc/slope_fc all populated (no "missing layers"
    warning to muddy the Vehicle-dropdown checks in Section 3).
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
    with arcpy.da.InsertCursor(soil_fc, ["SHAPE@", "soilType"]) as cur:
        for c, code in enumerate(["GW", "CH", "Pt"]):
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


# =============================================================================
# 1. Step 0 — dialog-time single-root layout creation
# =============================================================================

def test_step0_dialog_layout(scratch):
    print("\n" + "-" * 64)
    print("  1. Step 0 — dialog-time layout creation (updateParameters only)")
    print("-" * 64)

    import ccm_step0_mgcp as step0

    root0 = os.path.join(scratch, "DialogOnly_Project")
    os.makedirs(root0, exist_ok=True)

    tool = step0.CCMStep0MGCPTool()
    params = tool.getParameterInfo()
    _apply_params_by_name(params, project_root=root0)

    # updateParameters() alone — this is what ArcGIS Pro calls on every
    # keystroke/selection in the dialog, BEFORE Run is ever clicked.
    tool.updateParameters(params)

    data_root_dir = os.path.join(root0, "01_Input_Data")
    scan_index_dir = os.path.join(root0, "02_Scan_Index")
    check("Step 0: 01_Input_Data/ created by updateParameters() alone (no execute())",
          os.path.isdir(data_root_dir), data_root_dir)
    check("Step 0: 02_Scan_Index/ created by updateParameters() alone (no execute())",
          os.path.isdir(scan_index_dir), scan_index_dir)

    cfg_path = os.path.join(root0, "ccm_project.json")
    check("Step 0: ccm_project.json written by updateParameters() alone",
          os.path.isfile(cfg_path), cfg_path)

    by_name = {p.name: p for p in params}
    out_gdb_param = by_name.get("output_gdb")
    expected_gdb = os.path.join(root0, "03_Project.gdb")
    check("Step 0: Output Geodatabase auto-fills to <root>\\03_Project.gdb",
          out_gdb_param is not None and out_gdb_param.valueAsText == expected_gdb,
          out_gdb_param.valueAsText if out_gdb_param else "output_gdb param missing")

    if os.path.isfile(cfg_path):
        with io.open(cfg_path, encoding="utf-8") as f:
            cfg = json.load(f)
        check("Step 0: ccm_project.json project_root matches", cfg.get("project_root") == root0,
              cfg.get("project_root"))
        check("Step 0: ccm_project.json data_root matches", cfg.get("data_root") == data_root_dir,
              cfg.get("data_root"))
        check("Step 0: ccm_project.json scan_index_dir matches",
              cfg.get("scan_index_dir") == scan_index_dir, cfg.get("scan_index_dir"))
        check("Step 0: ccm_project.json project_gdb matches auto-filled Output Geodatabase",
              cfg.get("project_gdb") == expected_gdb, cfg.get("project_gdb"))


# =============================================================================
# 2. Step 1 — build a real project (Scenario A fixture)
# =============================================================================

def build_real_project(scratch, name="Project_A"):
    import ccm_project_config as cfg_mod
    import ccm_step1_setup as step1

    root = os.path.join(scratch, name)
    extent_fc, soil_fc, veg_fc, slope_fc, hydro_fc = build_step1_fixtures(scratch)

    vehicle_csv = os.path.join(_ROOT, "Vehicle_Data", "Vehicles_Can.csv")
    check("Step 1 fixture: real Vehicles_Can.csv found", os.path.isfile(vehicle_csv), vehicle_csv)

    cfg_mod.run_tool(
        step1.CCMStep1SetupTool(), _FakeMessages("[Step1]"),
        project_root=root,
        extent_fc=extent_fc,
        slope_regions_fc=slope_fc,
        soil_moisture="wet",
        soil_gap_fill="Smart (auto)",
        soil_preproc_fc=soil_fc,
        veg_preproc_fc=veg_fc,
        hydro_fcs=[hydro_fc],
        vehicle_csv=vehicle_csv,
    )

    cfg_path = os.path.join(root, "ccm_project.json")
    check(f"Step 1 ({name}): ccm_project.json written", os.path.isfile(cfg_path), cfg_path)
    cfg = cfg_mod.load_config(root) if os.path.isfile(cfg_path) else {}
    check(f"Step 1 ({name}): project_gdb recorded and exists",
          bool(cfg.get("project_gdb")) and arcpy.Exists(cfg.get("project_gdb")),
          cfg.get("project_gdb"))
    check(f"Step 1 ({name}): vehicle_csv recorded", cfg.get("vehicle_csv") == vehicle_csv,
          cfg.get("vehicle_csv"))
    return root, cfg


# =============================================================================
# 3. Step 2 — Vehicle dropdown Scenarios A / B / C + negative control
# =============================================================================

def _vehicle_dropdown(project_root):
    """Run Step 2's updateParameters()+updateMessages() and return
    (dropdown_names, p_folder) for inspection."""
    import ccm_step2_mobility as step2

    tool = step2.CCMStep2MobilityTool()
    params = tool.getParameterInfo()
    _apply_params_by_name(params, project_root=project_root)
    tool.updateParameters(params)
    tool.updateMessages(params)

    by_name = {p.name: p for p in params}
    p_vehicle = by_name["vehicle_name"]
    p_folder = by_name["project_root"]
    names = list(p_vehicle.filter.list) if p_vehicle.filter and p_vehicle.filter.list else []
    return names, p_folder


def test_step2_vehicle_dropdown(scratch, project_a, cfg_a):
    print("\n" + "-" * 64)
    print("  3. Step 2 — Vehicle dropdown Scenarios A / B / C (the original bug)")
    print("-" * 64)

    import ccm_project_config as cfg_mod
    from ccm_step2_mobility import load_vehicles_csv, _BUNDLED_VEHICLE_CSV

    real_names = set(load_vehicles_csv(cfg_a["vehicle_csv"]).keys())
    bundled_names = set(load_vehicles_csv(_BUNDLED_VEHICLE_CSV).keys())

    # ── Scenario A: normal case — a real, complete Step 1 project ──────────
    names_a, folder_a = _vehicle_dropdown(project_a)
    check("Scenario A: Vehicle dropdown populates with real vehicle names",
          set(names_a) == real_names, sorted(names_a))
    check("Scenario A: no error/warning on Project Root Folder param",
          not folder_a.hasError() and not folder_a.hasWarning(),
          f"error={folder_a.hasError()} warning={folder_a.hasWarning()} message={folder_a.message}")

    # ── Scenario B: vehicle_csv path is stale (moved/previous install) ─────
    # Same basename as the bundled CSV (Vehicles_Can.csv) but a nonexistent
    # directory -- this is specifically the "previous install" warning
    # branch, not the generic "no longer exists" error branch (those are
    # two different messages in ccm_step2_mobility.py's updateMessages()).
    project_b = os.path.join(scratch, "Project_B_stale_csv")
    os.makedirs(project_b, exist_ok=True)
    stale_csv = os.path.join(project_b, "OldInstall_v0.55", "Vehicle_Data",
                              os.path.basename(_BUNDLED_VEHICLE_CSV))
    cfg_mod.save_config(
        project_b, project_root=project_b, project_gdb=cfg_a["project_gdb"],
        vehicle_csv=stale_csv,
        soil_fc="placeholder", veg_fc="placeholder", slope_fc="placeholder",
    )
    names_b, folder_b = _vehicle_dropdown(project_b)
    check("Scenario B: Vehicle dropdown still populates (bundled-CSV fallback)",
          set(names_b) == bundled_names, sorted(names_b))
    check("Scenario B: a WARNING (not error) explains the previous-install fallback",
          folder_b.hasWarning() and not folder_b.hasError(),
          f"error={folder_b.hasError()} warning={folder_b.hasWarning()} message={folder_b.message}")

    # ── Scenario C: THE reported bug — valid Step 1 config, vehicle_csv key
    # simply never recorded. project_gdb IS present (so this is NOT mistaken
    # for a Step 0b-only file); vehicle_csv is entirely absent. Before the
    # v0.60.0 fix this showed zero dropdown options AND zero explanation. ──
    project_c = os.path.join(scratch, "Project_C_no_vehicle_csv")
    os.makedirs(project_c, exist_ok=True)
    cfg_mod.save_config(
        project_c, project_root=project_c, project_gdb=cfg_a["project_gdb"],
        soil_fc="placeholder", veg_fc="placeholder", slope_fc="placeholder",
    )
    cfg_c_check = cfg_mod.load_config(project_c)
    check("Scenario C fixture: vehicle_csv key is genuinely absent",
          "vehicle_csv" not in cfg_c_check or not cfg_c_check.get("vehicle_csv"),
          cfg_c_check.get("vehicle_csv", "<absent>"))
    names_c, folder_c = _vehicle_dropdown(project_c)
    check("Scenario C (the reported bug): Vehicle dropdown now populates "
          "(bundled-CSV fallback) instead of showing nothing",
          set(names_c) == bundled_names, sorted(names_c))
    check("Scenario C: a WARNING now explains the fallback (previously: nothing at all)",
          folder_c.hasWarning() and not folder_c.hasError(),
          f"error={folder_c.hasError()} warning={folder_c.hasWarning()} message={folder_c.message}")

    # ── Negative control: point Step 2 at a Step-0b-only ccm_project.json
    # (no project_gdb, no vehicle_csv, has data_root) — must give a clear
    # ERROR naming the real problem, and must NOT mention the old
    # CCM_Project.gdb name (v0.60.0 uses 03_Project.gdb). ───────────────────
    project_d = os.path.join(scratch, "Project_D_step0b_only")
    os.makedirs(project_d, exist_ok=True)
    cfg_mod.save_config(
        project_d, project_root=project_d,
        data_root=os.path.join(project_d, "01_Input_Data"),
        data_catalog_json=os.path.join(project_d, "02_Scan_Index", "ccm_data_catalog.json"),
        # Placeholder soil/veg/slope so the separate "missing layers"
        # warning check further down in updateMessages() doesn't ALSO fire
        # and overwrite the Step-0b-file error this scenario is testing --
        # same reasoning as Scenarios B/C above.
        soil_fc="placeholder", veg_fc="placeholder", slope_fc="placeholder",
    )
    names_d, folder_d = _vehicle_dropdown(project_d)
    # Note: updateParameters() falls back to the bundled CSV for ANY folder
    # missing a resolvable vehicle_csv -- including this one -- so the
    # dropdown itself is harmlessly populated here too, same as Scenario C.
    # What actually distinguishes a Step-0b-only folder is updateMessages()
    # correctly identifying it as the wrong kind of folder entirely (an
    # ERROR, not the Scenario C warning) rather than treating it as a valid
    # but incomplete Step 1 project.
    check("Negative control: dropdown still safely falls back to bundled CSV "
          "(harmless; the real signal is the error message below)",
          set(names_d) == bundled_names, sorted(names_d))
    check("Negative control: an ERROR (not just a warning) explains this is a "
          "Step 0b scan, not a Step 1 project",
          folder_d.hasError(), f"warning={folder_d.hasWarning()} message={folder_d.message}")
    check("Negative control: error message does NOT cite the old CCM_Project.gdb name",
          "CCM_Project.gdb" not in (folder_d.message or ""), folder_d.message)


# =============================================================================
# 4. Step 3 — _derive_output_path() GDB-resolution fallback
# =============================================================================

def test_step3_gdb_resolution(scratch, project_a, cfg_a):
    print("\n" + "-" * 64)
    print("  4. Step 3 — _derive_output_path() GDB-resolution fallback")
    print("-" * 64)

    from ccm_step3_advanced import _derive_output_path

    # (a) config-first resolution: speed_fc's own workspace doesn't exist,
    # but folder_path has a real ccm_project.json with project_gdb set --
    # must resolve through the config, landing in 03_Project.gdb.
    fake_speed_fc = os.path.join(scratch, "nonexistent_ws.gdb", "speed_m1")
    result_a = _derive_output_path(fake_speed_fc, project_a, "isochrone")
    ws_a = os.path.dirname(result_a)
    check("Step 3 (a): config-first resolution lands in this project's 03_Project.gdb",
          os.path.normcase(ws_a) == os.path.normcase(cfg_a["project_gdb"]), result_a)

    # (b) no config at all, but 03_Project.gdb exists on disk directly under
    # folder_path -- must resolve via the hardcoded-name-guessing loop.
    project_e = os.path.join(scratch, "Project_E_no_config_new_name")
    os.makedirs(project_e, exist_ok=True)
    arcpy.management.CreateFileGDB(project_e, "03_Project.gdb")
    result_b = _derive_output_path(fake_speed_fc, project_e, "isochrone")
    ws_b = os.path.dirname(result_b)
    check("Step 3 (b): no config, falls back to 03_Project.gdb found on disk",
          os.path.normcase(ws_b) == os.path.normcase(os.path.join(project_e, "03_Project.gdb")),
          result_b)

    # (c) no config, only the OLD-style CCM_Project.gdb name on disk (a
    # pre-v0.60.0 project) -- must still resolve via the same loop's
    # backward-compatible second name.
    project_f = os.path.join(scratch, "Project_F_legacy_gdb_name")
    os.makedirs(project_f, exist_ok=True)
    arcpy.management.CreateFileGDB(project_f, "CCM_Project.gdb")
    result_c = _derive_output_path(fake_speed_fc, project_f, "isochrone")
    ws_c = os.path.dirname(result_c)
    check("Step 3 (c): no config, falls back to legacy CCM_Project.gdb name for backward-compat",
          os.path.normcase(ws_c) == os.path.normcase(os.path.join(project_f, "CCM_Project.gdb")),
          result_c)

    # (d) neither a config nor any GDB at all -- must fall through to
    # arcpy.env.scratchGDB rather than raising.
    project_g = os.path.join(scratch, "Project_G_nothing")
    os.makedirs(project_g, exist_ok=True)
    result_d = _derive_output_path(fake_speed_fc, project_g, "isochrone")
    ws_d = os.path.dirname(result_d)
    check("Step 3 (d): neither config nor GDB present, falls back to arcpy.env.scratchGDB",
          os.path.normcase(ws_d) == os.path.normcase(arcpy.env.scratchGDB), result_d)


# =============================================================================
# Main
# =============================================================================

def main():
    print("=" * 64)
    print("  CCM v0.60.0 — single-root dialog-behavior smoke test")
    print("=" * 64)

    scratch = tempfile.mkdtemp(prefix="ccm_smoke_v060_")
    print(f"Scratch root: {scratch}")
    arcpy.env.overwriteOutput = True

    try:
        test_step0_dialog_layout(scratch)
    except Exception as exc:
        check("Section 1 (Step 0 dialog layout) raised an exception", False,
              f"{exc}\n{traceback.format_exc()}")

    project_a, cfg_a = None, None
    try:
        project_a, cfg_a = build_real_project(scratch, "Project_A")
    except Exception as exc:
        check("Section 2 (build real Step 1 project) raised an exception", False,
              f"{exc}\n{traceback.format_exc()}")

    if project_a and cfg_a and cfg_a.get("vehicle_csv") and cfg_a.get("project_gdb"):
        try:
            test_step2_vehicle_dropdown(scratch, project_a, cfg_a)
        except Exception as exc:
            check("Section 3 (Step 2 Vehicle dropdown) raised an exception", False,
                  f"{exc}\n{traceback.format_exc()}")
        try:
            test_step3_gdb_resolution(scratch, project_a, cfg_a)
        except Exception as exc:
            check("Section 4 (Step 3 GDB resolution) raised an exception", False,
                  f"{exc}\n{traceback.format_exc()}")
    else:
        check("Sections 3+4 skipped because Section 2's fixture project did not build correctly",
              False, f"project_a={project_a} cfg_a={cfg_a}")

    print("\n" + "=" * 64)
    if FAIL:
        print(f"  SMOKE TEST FAILED — {len(FAIL)} failure(s):")
        for f in FAIL:
            print(f"    - {f}")
    else:
        print(f"  SMOKE TEST PASSED — {len(PASS)} checks OK")
    print(f"  Inspect results in: {scratch}")
    print("=" * 64)
    return not FAIL


if __name__ == "__main__":
    sys.exit(0 if main() else 1)
# <<< END OF FILE >>>
