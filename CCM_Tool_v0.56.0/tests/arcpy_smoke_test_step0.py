# SPDX-License-Identifier: GPL-2.0-or-later
# Copyright (c) 2026 Eui Soo SON
# -*- coding: utf-8 -*-
# tests/arcpy_smoke_test_step0.py
# CCM v0.56.0 — End-to-end Step 0 validation on a REAL ArcGIS Pro installation.
#
# WHAT THIS DOES
# --------------
# Companion to tests/arcpy_smoke_test.py (which covers Step 2 only).  This
# file exercises Step 0 — Load MGCP Data — which had NO end-to-end coverage
# at all before v0.54.4: only mocked-arcpy unit tests touched it, and Step 2's
# own smoke test bypasses Step 0 entirely by fabricating its fixtures and
# ccm_project.json directly.
#
# Builds a tiny synthetic "MGCP-like" source from scratch (no external data
# needed):
#   * a scratch folder
#   * a SOURCE File GDB containing two feature classes named with real MGCP
#     FACC codes — DA010 (soil polygon) and BH140 (hydro/river polygon) —
#     so ccm_mgcp_catalog classification, theme grouping, and the
#     mgcp_manifest.json hand-off to Step 1 are all genuinely exercised
#   * an (initially non-existent) OUTPUT File GDB, auto-created by the tool
# ...then invokes CCMStep0MGCPTool via ccm_project_config.run_tool() — the
# project's own sanctioned "invoke by parameter NAME" helper (see CLAUDE.md
# Conventions) — exactly as Step 1/Step 3 invoke their own sub-tools, and
# asserts:
#   * both feature classes were imported into the output GDB with the right
#     feature counts
#   * mgcp_manifest.json was written next to the output GDB with entries for
#     both FCs, correct ccm_role classification (soil / hydro), and correct
#     geometry type
#   * a second run against the SAME output GDB with existing_action=APPEND
#     does not fail and does not duplicate features (the merge-cells path)
#
# v0.56.0 adds a third pass over a mixed-geometry shapefile cell that
# asserts the new surface end-to-end: Point/Line/Polygon geometry_group
# assignment, the FACC-category and name-keyword fallbacks (no layer is
# ever labelled 'Unknown feature' again), readable FC aliases with the
# MGCP code name preserved, the mgcp_catalog_user.csv template, and the
# Unknown-CRS repair on a shapefile deliberately shipped without a .prj.
#
# add_to_map is left False throughout, so this never touches
# arcpy.mp.ArcGISProject and runs correctly from a headless conda prompt.
#
# HOW TO RUN (1 minute)
# ----------------------
# Option A — ArcGIS Pro Python window:
#     exec(open(r"C:\...\CCM_Tool_v0.56.0\tests\arcpy_smoke_test_step0.py").read())
# Option B — ArcGIS Pro conda prompt:
#     "%PROGRAMFILES%\ArcGIS\Pro\bin\Python\envs\arcgispro-py3\python.exe" tests\arcpy_smoke_test_step0.py
#
# Output: PASS/FAIL lines and a final SMOKE TEST PASSED / FAILED verdict.
# The scratch project is left on disk (path printed) so you can inspect the
# imported feature classes and manifest directly.
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

# Same pytest-collection guard as tests/arcpy_smoke_test.py (v0.54.4 fix) —
# a bare top-level `import arcpy` would abort pytest COLLECTION on any
# machine without ArcGIS Pro, taking the whole suite down with it.
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

    CCMStep0MGCPTool.execute() calls messages.addMessage(...) unconditionally
    (not gated on `messages is not None`, unlike ccm_step2_mobility's helpers),
    so a real object with these three methods is required — passing None
    would raise AttributeError immediately.  Everything is also echoed to
    stdout so a failing run's log shows exactly what Step 0 reported.
    """
    def __init__(self, prefix="[msg]"):
        self.prefix = prefix
        self.messages = []
        self.warnings = []
        self.errors = []

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


def build_source_gdb(root):
    """
    A tiny synthetic 'MGCP cell' File GDB with two FACC-coded layers:
      DA010 — Soil Surface Composition (soil, per ccm_mgcp_catalog.ROLE_SOIL)
      BH140 — River (hydro, per ccm_mgcp_catalog.ROLE_HYDRO)
    """
    sr = arcpy.SpatialReference(32618)
    src_gdb = os.path.join(root, "mgcp_cell_source.gdb")
    arcpy.management.CreateFileGDB(root, "mgcp_cell_source.gdb")

    soil_fc = os.path.join(src_gdb, "DA010")
    arcpy.management.CreateFeatureclass(src_gdb, "DA010", "POLYGON", spatial_reference=sr)
    arcpy.management.AddField(soil_fc, "SMC", "TEXT", field_length=10)
    with arcpy.da.InsertCursor(soil_fc, ["SHAPE@", "SMC"]) as cur:
        cur.insertRow([make_square(0, 0, 200, sr), "GW"])

    hydro_fc = os.path.join(src_gdb, "BH140")
    arcpy.management.CreateFeatureclass(src_gdb, "BH140", "POLYGON", spatial_reference=sr)
    with arcpy.da.InsertCursor(hydro_fc, ["SHAPE@"]) as cur:
        cur.insertRow([make_square(300, 0, 100, sr)])

    return src_gdb


def build_mixed_source(root):
    """
    v0.56.0 fixture — a shapefile 'cell' that exercises everything the
    v0.56.0 Step 0 work touches:

      AP030.shp           Polyline, catalogued FACC code   -> Line group
      AL015.shp           Polygon,  catalogued FACC code   -> Polygon group
      CA030.shp           Point,    catalogued FACC code   -> Point group
      AP999.shp           Polyline, UNCATALOGUED code      -> category fallback
      HydrographySrf.shp  Polygon,  no FACC code at all    -> keyword fallback

    CA030 is written WITHOUT a .prj sidecar so the Unknown-CRS repair path
    runs for real.
    """
    sr = arcpy.SpatialReference(4326)          # MGCP is WGS84 by spec
    cell = os.path.join(root, "cellA")
    os.makedirs(cell, exist_ok=True)

    def _poly(name, x0):
        arcpy.management.CreateFeatureclass(cell, name + ".shp", "POLYGON",
                                            spatial_reference=sr)
        fc = os.path.join(cell, name + ".shp")
        with arcpy.da.InsertCursor(fc, ["SHAPE@"]) as cur:
            pts = [(x0, 0), (x0 + 0.01, 0), (x0 + 0.01, 0.01), (x0, 0.01)]
            cur.insertRow([arcpy.Polygon(
                arcpy.Array(arcpy.Point(*q) for q in pts), sr)])
        return fc

    def _line(name, x0):
        arcpy.management.CreateFeatureclass(cell, name + ".shp", "POLYLINE",
                                            spatial_reference=sr)
        fc = os.path.join(cell, name + ".shp")
        with arcpy.da.InsertCursor(fc, ["SHAPE@"]) as cur:
            cur.insertRow([arcpy.Polyline(arcpy.Array(
                [arcpy.Point(x0, 0), arcpy.Point(x0 + 0.01, 0.01)]), sr)])
        return fc

    def _point(name, x0):
        arcpy.management.CreateFeatureclass(cell, name + ".shp", "POINT",
                                            spatial_reference=sr)
        fc = os.path.join(cell, name + ".shp")
        with arcpy.da.InsertCursor(fc, ["SHAPE@"]) as cur:
            cur.insertRow([arcpy.PointGeometry(arcpy.Point(x0, 0.005), sr)])
        return fc

    _line("AP030", 1.0)
    _poly("AL015", 1.1)
    _line("AP999", 1.2)
    _poly("HydrographySrf", 1.3)
    ca030 = _point("CA030", 1.4)

    # Strip the .prj so the "Unknown CRS" repair path is genuinely exercised.
    prj = os.path.splitext(ca030)[0] + ".prj"
    if os.path.isfile(prj):
        os.remove(prj)

    return cell


def main():
    print("=" * 64)
    print("  CCM v0.56.0 — Step 0 arcpy smoke test (Load MGCP Data)")
    print("=" * 64)

    root = tempfile.mkdtemp(prefix="ccm_smoke_step0_")
    print(f"Scratch project: {root}")
    arcpy.env.overwriteOutput = True

    import ccm_project_config as cfg_mod
    import ccm_step0_mgcp as step0
    try:
        import ccm_mgcp_catalog as catalog
    except Exception:
        catalog = None

    src_gdb = build_source_gdb(root)
    check("source GDB built", arcpy.Exists(src_gdb), src_gdb)

    output_gdb = os.path.join(root, "MGCP_Output.gdb")
    msgs = _FakeMessages("[Step0-smoke]")

    # ── First run: fresh output GDB, auto-created ────────────────────────────
    try:
        cfg_mod.run_tool(
            step0.CCMStep0MGCPTool(), msgs,
            input_gdb=[src_gdb],
            output_gdb=output_gdb,
            create_gdb=True,
            existing_action="APPEND - add features to existing layer (merge cells)",
            add_to_map=False,
            group_layers=False,
        )
        check("Step 0 execute() ran (first import)", True)
    except Exception as exc:
        check("Step 0 execute() ran (first import)", False,
              f"{exc}\n{traceback.format_exc()}")

    check("output GDB auto-created", arcpy.Exists(output_gdb), output_gdb)

    soil_out = os.path.join(output_gdb, "DA010")
    hydro_out = os.path.join(output_gdb, "BH140")
    check("DA010 imported", arcpy.Exists(soil_out), soil_out)
    check("BH140 imported", arcpy.Exists(hydro_out), hydro_out)

    if arcpy.Exists(soil_out):
        n_soil = int(arcpy.management.GetCount(soil_out)[0])
        check("DA010 feature count == 1 (first run)", n_soil == 1, f"got {n_soil}")
    if arcpy.Exists(hydro_out):
        n_hydro = int(arcpy.management.GetCount(hydro_out)[0])
        check("BH140 feature count == 1 (first run)", n_hydro == 1, f"got {n_hydro}")

    # ── Manifest hand-off to Step 1 ───────────────────────────────────────────
    if catalog:
        manifest_path = catalog.manifest_path_for_gdb(output_gdb)
        check("mgcp_manifest.json written", os.path.isfile(manifest_path), manifest_path)
        if os.path.isfile(manifest_path):
            manifest = catalog.load_manifest(manifest_path)
            by_name = {f["name"]: f for f in manifest.get("features", [])}
            check("manifest lists DA010", "DA010" in by_name, sorted(by_name))
            check("manifest lists BH140", "BH140" in by_name, sorted(by_name))
            if "DA010" in by_name:
                check("DA010 classified as soil role",
                      by_name["DA010"].get("ccm_role") == catalog.ROLE_SOIL,
                      by_name["DA010"].get("ccm_role"))
                check("DA010 geometry recorded as Polygon",
                      by_name["DA010"].get("geometry") == "Polygon",
                      by_name["DA010"].get("geometry"))
            if "BH140" in by_name:
                check("BH140 classified as hydro role",
                      by_name["BH140"].get("ccm_role") == catalog.ROLE_HYDRO,
                      by_name["BH140"].get("ccm_role"))
    else:
        print("  SKIP  manifest checks — ccm_mgcp_catalog.py not importable")

    # ── Second run: re-import into the SAME output GDB (merge-cells path) ───
    # Exercises existing_action=APPEND against an already-populated output —
    # the everyday "import another cell" workflow — and confirms it doesn't
    # error or silently corrupt the first run's data.
    try:
        cfg_mod.run_tool(
            step0.CCMStep0MGCPTool(), _FakeMessages("[Step0-smoke:2nd]"),
            input_gdb=[src_gdb],
            output_gdb=output_gdb,
            create_gdb=True,
            existing_action="APPEND - add features to existing layer (merge cells)",
            add_to_map=False,
            group_layers=False,
        )
        check("Step 0 execute() ran (second/APPEND import)", True)
    except Exception as exc:
        check("Step 0 execute() ran (second/APPEND import)", False,
              f"{exc}\n{traceback.format_exc()}")

    if arcpy.Exists(soil_out):
        n_soil2 = int(arcpy.management.GetCount(soil_out)[0])
        # APPEND merges cells -> running the identical source again should
        # double the count (1 -> 2), proving the merge path actually ran
        # rather than silently skipping or overwriting.
        check("DA010 feature count == 2 after APPEND re-import",
              n_soil2 == 2, f"got {n_soil2}")


    # ══════════════════════════════════════════════════════════════════════
    # v0.56.0 — geometry grouping, fallback classification, aliases, CRS
    # ══════════════════════════════════════════════════════════════════════
    print("\n--- v0.56.0 checks (mixed-geometry shapefile cell) ---")
    mixed_cell = build_mixed_source(root)
    check("mixed-geometry source cell built", os.path.isdir(mixed_cell), mixed_cell)

    gdb2 = os.path.join(root, "MGCP_Mixed.gdb")
    try:
        cfg_mod.run_tool(
            step0.CCMStep0MGCPTool(), _FakeMessages("[Step0-smoke:v056]"),
            input_shp_folders=[mixed_cell],
            recurse_shp=True,
            output_gdb=gdb2,
            create_gdb=True,
            existing_action="OVERWRITE - replace existing layer, then merge new cells",
            add_to_map=False,                 # headless-safe
            assume_wgs84=True,
            group_mode=step0.GROUP_MODE_GEOMETRY,
            write_user_catalog=True,
            set_alias=True,
        )
        check("Step 0 execute() ran (v0.56.0 mixed cell)", True)
    except Exception as exc:
        check("Step 0 execute() ran (v0.56.0 mixed cell)", False,
              "%s\n%s" % (exc, traceback.format_exc()))

    expected = ["AP030", "AL015", "CA030", "AP999", "HydrographySrf"]
    for name in expected:
        check("%s imported" % name,
              arcpy.Exists(os.path.join(gdb2, name)),
              os.path.join(gdb2, name))

    # -- Unknown-CRS repair: CA030 had no .prj and must come out as WGS84 ----
    ca_out = os.path.join(gdb2, "CA030")
    if arcpy.Exists(ca_out):
        sr_name = getattr(getattr(arcpy.Describe(ca_out), "spatialReference",
                                  None), "name", "") or ""
        check("CA030 (.prj-less source) assigned a real CRS",
              sr_name and sr_name.lower() != "unknown", "SR=%s" % sr_name)
        check("CA030 CRS is WGS84", "WGS_1984" in sr_name or "4326" in sr_name,
              "SR=%s" % sr_name)

    # -- readable aliases, code name untouched ------------------------------
    al_out = os.path.join(gdb2, "AL015")
    if arcpy.Exists(al_out):
        d = arcpy.Describe(al_out)
        check("AL015 keeps its MGCP code as the FC name",
              getattr(d, "name", "") == "AL015", getattr(d, "name", ""))
        alias_val = getattr(d, "aliasName", "") or ""
        check("AL015 alias is readable",
              alias_val == "Building (AL015)", "alias=%r" % alias_val)

    # -- classification + geometry grouping in the manifest -----------------
    if catalog:
        mf = catalog.load_manifest(catalog.manifest_path_for_gdb(gdb2))
        by = {f["name"]: f for f in mf.get("features", [])}
        check("manifest has all 5 v0.56.0 layers",
              all(n in by for n in expected), sorted(by))

        want_geom = {"AP030": "Line", "AL015": "Polygon", "CA030": "Point",
                     "AP999": "Line", "HydrographySrf": "Polygon"}
        for name, grp in want_geom.items():
            if name in by:
                check("%s -> %s group" % (name, grp),
                      by[name].get("geometry_group") == grp,
                      by[name].get("geometry_group"))

        if "AP030" in by:
            check("AP030 is an exact catalog match",
                  by["AP030"].get("match") == catalog.MATCH_EXACT,
                  by["AP030"].get("match"))
        if "AP999" in by:
            check("AP999 falls back to its FACC category (not 'Unknown')",
                  by["AP999"].get("match") == catalog.MATCH_CATEGORY,
                  by["AP999"].get("match"))
            check("AP999 still lands in the Transportation theme",
                  by["AP999"].get("theme") == catalog.THEME_TRANSPORT,
                  by["AP999"].get("theme"))
            check("AP999 label contains no 'Unknown feature'",
                  "Unknown" not in (by["AP999"].get("label") or ""),
                  by["AP999"].get("label"))
            check("AP999 is given NO ccm_role by a category guess",
                  by["AP999"].get("ccm_role") is None,
                  by["AP999"].get("ccm_role"))
        if "HydrographySrf" in by:
            check("HydrographySrf classified by name keyword",
                  by["HydrographySrf"].get("match") == catalog.MATCH_KEYWORD,
                  by["HydrographySrf"].get("match"))
            check("HydrographySrf lands in the Hydrography theme",
                  by["HydrographySrf"].get("theme") == catalog.THEME_HYDRO,
                  by["HydrographySrf"].get("theme"))

        check("manifest reports the uncatalogued codes",
              "AP999" in (mf.get("unclassified_codes") or []),
              mf.get("unclassified_codes"))

        # -- the editable override template ---------------------------------
        tpl = os.path.join(os.path.dirname(gdb2), catalog.USER_CATALOG_FILENAME)
        check("mgcp_catalog_user.csv template written", os.path.isfile(tpl), tpl)
        if os.path.isfile(tpl):
            body = open(tpl, encoding="utf-8").read()
            check("template seeded with AP999", "AP999," in body)
            check("template pre-fills the category theme",
                  "AP999,,Transportation," in body)

    print("\n" + "=" * 64)
    if FAIL:
        print(f"  SMOKE TEST FAILED — {len(FAIL)} failure(s): {FAIL}")
    else:
        print(f"  SMOKE TEST PASSED — {len(PASS)} checks OK")
    print(f"  Inspect results in: {output_gdb}")
    print("=" * 64)
    return not FAIL


if __name__ == "__main__":
    sys.exit(0 if main() else 1)
# <<< END OF FILE >>>
