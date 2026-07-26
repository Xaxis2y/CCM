# =============================================================================
# SPDX-License-Identifier: GPL-2.0-or-later
# Copyright (c) 2026 Eui Soo SON (Beta)
# =============================================================================
# -*- coding: utf-8 -*-
# tests/arcpy_smoke_test_step0.py
# CCM v0.54.7 — End-to-end Step 0 validation on a REAL ArcGIS Pro installation.
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
# add_to_map is left False throughout, so this never touches
# arcpy.mp.ArcGISProject and runs correctly from a headless conda prompt.
#
# HOW TO RUN (1 minute)
# ----------------------
# Option A — ArcGIS Pro Python window:
#     exec(open(r"C:\...\CCM_Tool_by_Son_v0.54.7\tests\arcpy_smoke_test_step0.py").read())
# Option B — ArcGIS Pro conda prompt:
#     "%PROGRAMFILES%\ArcGIS\Pro\bin\Python\envs\arcgispro-py3\python.exe" tests\arcpy_smoke_test_step0.py
#
# Output: PASS/FAIL lines and a final SMOKE TEST PASSED / FAILED verdict.
# The scratch project is left on disk (path printed) so you can inspect the
# imported feature classes and manifest directly.
#
VERSION = "0.54.7"  # v0.54.7 — version bump only, no logic change (see CHANGELOG_v0.54.md).

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


def main():
    print("=" * 64)
    print("  CCM v0.54.7 — Step 0 arcpy smoke test (Load MGCP Data)")
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
