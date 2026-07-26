# =============================================================================
# SPDX-License-Identifier: GPL-2.0-or-later
# Copyright (c) 2026 Eui Soo SON (Beta)
# =============================================================================
#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
CCM_Tool_by_Son_v0.54.7.pyt — ArcGIS Python Toolbox entry point
====================================================
Cross-Country Mobility (CCM) Assessment Tool  v0.54.7

Toolbox exposes five tool steps:
  Step 0  — Load MGCP Data               (CCMStep0MGCPTool)
  Step 1  — Project Setup & Pre-process   (CCMStep1SetupTool)
  Step 2  — Generate Mobility Map         (CCMStep2MobilityTool)
  Step 3  — Advanced Analysis             (CCMStep3AdvancedTool)
  Step 4  — Compare Two Vehicles          (CCMVehicleCompareTool)

The main() function at the bottom is kept for direct / command-line
testing outside the ArcGIS Pro GUI.

v0.54.7 changes (this file):
  - Filename/version bump only. The real fix this round is in
    tests/arcpy_smoke_test_step3.py: the diagnostic that reported which
    isochrone code path ran (Spatial Analyst raster vs. vector fallback)
    inspected msgs.warnings, but ccm_isochrone.py logs via the global
    arcpy.AddWarning(), not the messages object — so the check silently
    reported the wrong path. Fixed with a "gridcode" field-presence check.
    No logic in this entry-point file, nor in ccm_isochrone.py's actual
    isochrone generation, changed. See CHANGELOG_v0.54.md.

v0.54.6 changes (this file):
  - Filename/version bump only. A real ArcGIS Pro 3.7.1 re-run showed the
    v0.54.5 mitigation for ERROR 160333 fires but does not resolve it; the
    actual follow-up fix (in-memory Reclassify + vector-method fallback in
    generate_isochrones()) lives in ccm_isochrone.py, plus a smoke-test
    visibility improvement in tests/arcpy_smoke_test_step3.py; no logic in
    this entry-point file changed. See CHANGELOG_v0.54.md.

v0.54.5 changes (this file):
  - Filename/version bump only. The actual fix (ERROR 160333 on Reclassify
    in the Reachability Map / Isochrone tool, plus a vehicle-name bug in
    tests/arcpy_smoke_test_step1.py) lives in ccm_isochrone.py and the test
    suite; no logic in this entry-point file changed. See CHANGELOG_v0.54.md.

v0.54.1 changes (this file):
  - Rebrand: "MCE CCM Tool" -> "CCM Tool by Son" throughout (toolname,
    alias, filenames); toolbox renamed MCE_CCM_v0.54.0.pyt ->
    CCM_Tool_by_Son_v0.54.1.pyt (sidecars, build.py, tests, docs, and the
    user manual renamed/updated to match).
  - Relicensed under SPDX-License-Identifier: GPL-2.0-or-later
    (previously "All Rights Reserved"). New copyright line:
    Copyright (c) 2026 Eui Soo SON (Beta).
  - No functional / geoprocessing logic changed. See CHANGELOG_v0.54.md.

v0.54.0 changes (this file):
  - Filename/version bump only — smart CRS/projection warnings were added
    to the imported step modules (ccm_step0_mgcp.py, ccm_step1_setup.py,
    ccm_step3_advanced.py, ccm_vehicle_compare.py) and the shared
    ccm_coords.py helper; no logic in this entry-point file changed.
    See CHANGELOG_v0.54.md.

v0.46 changes (this file):
  - Added proper Toolbox class so ArcGIS Pro discovers all three steps.
  - Fixed module imports: all sub-tool classes now imported by their real
    names (CCMStep1SetupTool, CCMStep3AdvancedTool, CCMVehicleCompareTool).
  - Replaced all print() calls with arcpy.AddMessage() / arcpy.AddError().
  - Added _validate_distance() — warns on missing/invalid distance, detects units.
  - Added validate_feature_class() — checks existence, data type, geometry.
  - Added _create_unique_folder() — handles simultaneous-run race condition.
  - Added _resolve_obstacle_source() — auto-detects raster / FC / CSV input.
  - Added arcpy.SetLogMetadata(False) in CCMAssessment.execute() for perf.
  - Timestamps on all log messages via _log() helper.
  - summary.json uses UTC ISO-8601 timestamp.
"""

import arcpy
import os
import sys
import datetime
import json
import time
import random

# ── Ensure the toolbox directory is on sys.path ───────────────────────────────
_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

# Tool metadata
toolname    = "CCM_Tool_by_Son"
toolversion = "0.54.7"


# ── Stub-tool factory ─────────────────────────────────────────────────────────
def _make_stub_tool(label, import_error):
    """
    Build a placeholder tool class for a step whose module failed to import.

    Instead of silently dropping the tool from the toolbox (so the user never
    learns why it vanished), we register a stub that appears in the toolbox and
    reports the underlying import error when opened or run.
    """
    class _StubTool(object):
        def __init__(self):
            self.label = f"{label}  [UNAVAILABLE — failed to load]"
            self.description = (
                f"This tool could not be loaded due to an import error:\n\n"
                f"{import_error}\n\n"
                "Fix the underlying module (see the error above) and reload "
                "the toolbox."
            )
            self.canRunInBackground = False

        def getParameterInfo(self):
            return []

        def isLicensed(self):
            return True

        def updateParameters(self, parameters):
            pass

        def updateMessages(self, parameters):
            pass

        def execute(self, parameters, messages):
            arcpy.AddError(
                f"'{label}' is unavailable — module failed to import:\n{import_error}"
            )
            raise arcpy.ExecuteError(f"{label} failed to load: {import_error}")

    return _StubTool


# ── Import step tool classes (register a stub if any import fails) ────────────
try:
    from ccm_step0_mgcp import CCMStep0MGCPTool
except Exception as _e:
    CCMStep0MGCPTool = _make_stub_tool("Step 0.  Load MGCP Data", _e)
    arcpy.AddWarning(f"[CCM_Tool_by_Son] ccm_step0_mgcp not loaded: {_e}")

try:
    from ccm_step1_setup import CCMStep1SetupTool
except Exception as _e:
    CCMStep1SetupTool = _make_stub_tool("Step 1.  Project Setup & Pre-process", _e)
    arcpy.AddWarning(f"[CCM_Tool_by_Son] ccm_step1_setup not loaded: {_e}")

try:
    from ccm_step2_mobility import CCMStep2MobilityTool
except Exception as _e:
    CCMStep2MobilityTool = _make_stub_tool("Step 2.  Generate Mobility Map", _e)
    arcpy.AddWarning(f"[CCM_Tool_by_Son] ccm_step2_mobility not loaded: {_e}")

try:
    from ccm_step3_advanced import CCMStep3AdvancedTool
except Exception as _e:
    CCMStep3AdvancedTool = _make_stub_tool("Step 3.  Advanced Analysis", _e)
    arcpy.AddWarning(f"[CCM_Tool_by_Son] ccm_step3_advanced not loaded: {_e}")

try:
    from ccm_vehicle_compare import CCMVehicleCompareTool
except Exception as _e:
    CCMVehicleCompareTool = _make_stub_tool("Step 4.  Compare Two Vehicles", _e)
    arcpy.AddWarning(f"[CCM_Tool_by_Son] ccm_vehicle_compare not loaded: {_e}")


# =============================================================================
# TOOLBOX DEFINITION
# =============================================================================

class Toolbox(object):
    """ArcGIS Python Toolbox container — registers all CCM tool steps."""

    def __init__(self):
        self.label   = f"{toolname} v{toolversion}"
        self.alias   = "CCMToolBySon"
        # All steps are registered.  Steps whose module failed to import are
        # represented by a stub tool that reports the error (see _make_stub_tool)
        # rather than silently disappearing from the toolbox.
        self.tools   = [
            CCMStep0MGCPTool,
            CCMStep1SetupTool,
            CCMStep2MobilityTool,
            CCMStep3AdvancedTool,
            CCMVehicleCompareTool,
        ]


# =============================================================================
# HELPER UTILITIES (used by main() / CCMAssessment below)
# =============================================================================

def _log(msg: str) -> None:
    """Timestamp-prefixed ArcGIS message wrapper (replaces bare print() calls)."""
    ts = datetime.datetime.now().strftime("%H:%M:%S")
    arcpy.AddMessage(f"[{ts}] {msg}")


def _validate_distance(value_str, default_m: float = 500.0) -> float:
    """
    Parse and validate an analysis distance string.

    Falls back to *default_m* with a warning if the value is missing or empty.
    Raises arcpy.ExecuteError / ValueError for non-numeric or non-positive input.
    Emits a unit-mismatch warning when the workspace CRS is non-metric and the
    supplied value looks unexpectedly small.
    """
    if not value_str or not str(value_str).strip():
        arcpy.AddWarning(
            f"Analysis distance not specified — using fallback {default_m} m."
        )
        return float(default_m)
    try:
        val = float(value_str)
        if val <= 0:
            raise ValueError("Distance must be positive.")
        # Attempt a units sanity-check against the workspace CRS
        try:
            ws = arcpy.env.workspace
            if ws and arcpy.Exists(ws):
                sr_unit = arcpy.Describe(ws).spatialReference.linearUnitName.lower()
                if "foot" in sr_unit and val < 100:
                    arcpy.AddWarning(
                        f"Workspace CRS uses feet but analysis distance is {val} — "
                        "verify units are correct."
                    )
        except Exception:
            pass  # Unit check is advisory; never block execution
        return val
    except ValueError as exc:
        arcpy.AddError(f"Invalid analysisDistance value '{value_str}': {exc}")
        raise


def validate_feature_class(path: str) -> tuple:
    """
    Validate that *path* is an existing, usable feature class.

    Returns
    -------
    (True,  "OK")             — input is valid
    (False, error_message)    — input is invalid; caller should abort
    """
    if not path or not path.strip():
        return False, "Input features path is empty."
    if not arcpy.Exists(path):
        return False, f"Input features do not exist: {path}"
    try:
        desc = arcpy.Describe(path)
        if desc.dataType not in ("FeatureClass", "ShapeFile", "FeatureLayer"):
            return False, (
                f"Input is not a feature class or shapefile "
                f"(got dataType='{desc.dataType}')."
            )
        if getattr(desc, "featureType", "") == "Annotation":
            return False, (
                "Input is an annotation layer — "
                "CCM requires point, line, or polygon features."
            )
        # Zero-extent warning (non-fatal)
        try:
            ext = desc.extent
            if ext and ext.width == 0 and ext.height == 0:
                arcpy.AddWarning(
                    "Input feature has zero spatial extent; "
                    "analysis may produce no results."
                )
        except Exception:
            pass
    except Exception as exc:
        return False, f"Could not describe input features: {exc}"
    return True, "OK"


def _create_unique_folder(base_path: str, prefix: str) -> str:
    """
    Create a uniquely named output subfolder under *base_path*.

    The name is <prefix>_YYYYMMDD_HHMMSS_NNN where NNN is a random suffix.
    Retries up to 10 times to tolerate simultaneous parallel runs that might
    create folders with the same second-resolution timestamp.

    Returns the full path to the created folder.
    Raises RuntimeError if a unique name cannot be found after 10 attempts.
    """
    for _ in range(10):
        ts   = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        rand = random.randint(100, 999)
        name = f"{prefix}_{ts}_{rand}"
        full = os.path.join(base_path, name)
        try:
            arcpy.management.CreateFolder(base_path, name)
            return full
        except arcpy.ExecuteError as exc:
            msg = str(exc).lower()
            if "already exists" not in msg and "duplicate" not in msg:
                arcpy.AddError(f"Failed to create output folder: {exc}")
                raise
            time.sleep(0.1)   # Brief back-off before retry
    raise RuntimeError(
        f"Could not create a unique output folder under '{base_path}' "
        "after 10 attempts."
    )


def _resolve_obstacle_source(obstacle_path: str) -> tuple:
    """
    Auto-detect whether *obstacle_path* is a raster, feature class, or CSV.

    Returns
    -------
    (path, type_str)  where type_str is 'raster', 'featureclass', or 'csv'
    (None, None)      if obstacle_path is empty

    Raises ValueError when the source type cannot be determined.

    Note: document the expected formats in the tool help text:
      - Raster dataset (e.g. DEM .tif / .img)
      - Feature class or shapefile (polygon / line obstacles)
      - CSV with columns: x, y  or  lat, lon
    """
    if not obstacle_path or not obstacle_path.strip():
        return None, None

    if arcpy.Exists(obstacle_path):
        desc = arcpy.Describe(obstacle_path)
        if desc.dataType == "RasterDataset":
            return obstacle_path, "raster"
        if desc.dataType in ("FeatureClass", "ShapeFile", "FeatureLayer"):
            return obstacle_path, "featureclass"

    # Attempt CSV detection via header inspection.  Parse the header into
    # individual column names so that x / y (or lat / lon) are detected
    # regardless of their column position — including as the first columns.
    try:
        with open(obstacle_path, "r", encoding="utf-8", errors="ignore") as fh:
            header = fh.readline().lower()
        cols = {c.strip().strip('"').strip("'") for c in header.split(",")}
        has_xy      = {"x", "y"}.issubset(cols)
        has_latlon  = ({"lat", "lon"}.issubset(cols)
                       or {"latitude", "longitude"}.issubset(cols))
        if has_xy or has_latlon:
            return obstacle_path, "csv"
    except Exception:
        pass

    raise ValueError(
        f"Cannot determine obstacle source type for: {obstacle_path}\n"
        "Supported formats: raster dataset, feature class / shapefile, "
        "or CSV with x/y or lat/lon columns."
    )


# =============================================================================
# CCMAssessment — thin orchestrator used by main() / command-line mode
# =============================================================================

class CCMAssessment(object):
    """
    Command-line orchestration wrapper for the CCM tool.

    For the ArcGIS Pro GUI, use the Toolbox class above — it exposes
    CCMStep1SetupTool, CCMStep3AdvancedTool, and CCMVehicleCompareTool
    directly as separate, self-contained tool steps.
    """

    def __init__(self):
        self.name        = "CCM Assessment Tool"
        self.description = (
            "Cross-Country Mobility Assessment for Military "
            "and Emergency Response applications."
        )

    # -------------------------------------------------------------------------
    def execute(
        self,
        inputFeatures,
        analysis_folder,
        analysisDistance,
        vehicleType,
        obstacleFile,
        soilType,
        weatherCondition,
        vegetationType,
    ):
        arcpy.SetLogMetadata(False)   # Suppress GDB history metadata accumulation
        _log("Starting CCM Analysis...")

        try:
            arcpy.env.workspace = analysis_folder

            # ── Parse & validate parameters ──────────────────────────────────
            analysis_dist     = _validate_distance(analysisDistance, default_m=500.0)
            vehicle_type      = (vehicleType      or "").strip() or "Light Vehicle"
            soil_type         = (soilType         or "").strip() or "Normal"
            weather_condition = (weatherCondition or "").strip() or "Clear"
            vegetation_type   = (vegetationType   or "").strip() or "Mixed"

            _log(f"Analysis distance : {analysis_dist} m")
            _log(f"Vehicle type      : {vehicle_type}")
            _log(f"Soil type         : {soil_type}")
            _log(f"Weather           : {weather_condition}")
            _log(f"Vegetation        : {vegetation_type}")

            # ── Obstacle file ─────────────────────────────────────────────────
            obs_path, obs_type = (
                _resolve_obstacle_source(obstacleFile)
                if obstacleFile else (None, None)
            )
            if obs_path:
                _log(f"Obstacle source   : {obs_path} (type={obs_type})")

            # ── Note on full analysis ─────────────────────────────────────────
            _log(
                "For the complete multi-step analysis, open the toolbox "
                "in ArcGIS Pro and run Steps 1 → 2 → 3 sequentially."
            )
            _log("This command-line path generates a summary JSON only.")

            self._generate_output(
                analysis_folder, inputFeatures,
                analysis_dist, vehicle_type, soil_type,
                weather_condition, vegetation_type,
            )

        except Exception as exc:
            arcpy.AddError(f"CCM Assessment failed: {exc}")
            raise

    # -------------------------------------------------------------------------
    def _generate_output(
        self,
        analysis_folder,
        inputFeatures,
        analysis_dist,
        vehicle_type,
        soil_type,
        weather_condition,
        vegetation_type,
    ):
        """Write the analysis summary to a JSON file."""
        _log("Generating summary output...")

        start_time = datetime.datetime.now(datetime.timezone.utc)

        summary = {
            "timestamp"        : start_time.isoformat(),
            "ccm_version"      : toolversion,
            "input_features"   : inputFeatures,
            "analysis_dist_m"  : analysis_dist,
            "vehicle_type"     : vehicle_type,
            "soil_type"        : soil_type,
            "weather_condition": weather_condition,
            "vegetation_type"  : vegetation_type,
        }

        summary_file = os.path.join(analysis_folder, "summary.json")
        with open(summary_file, "w", encoding="utf-8") as fh:
            json.dump(summary, fh, indent=4)

        _log(f"Summary written → {summary_file}")


# =============================================================================
# COMMAND-LINE ENTRY POINT
# =============================================================================

def main():
    _log(f"Cross-Country Mobility Analysis Tool v{toolversion}")
    _log(f"Working directory: {os.getcwd()}")

    # ── Get ArcGIS parameters ─────────────────────────────────────────────────
    inputFeatures    = arcpy.GetParameterAsText(0)
    outputFolder     = arcpy.GetParameterAsText(1)
    analysisDistance = arcpy.GetParameterAsText(2)
    vehicleType      = arcpy.GetParameterAsText(3)
    obstacleFile     = arcpy.GetParameterAsText(4)
    soilType         = arcpy.GetParameterAsText(5)
    weatherCondition = arcpy.GetParameterAsText(6)
    vegetationType   = arcpy.GetParameterAsText(7)

    _log(f"Input Features    : {inputFeatures}")
    _log(f"Output Folder     : {outputFolder}")
    _log(f"Analysis Distance : {analysisDistance}")
    _log(f"Vehicle Type      : {vehicleType}")
    _log(f"Obstacle File     : {obstacleFile}")
    _log(f"Soil Type         : {soilType}")
    _log(f"Weather Condition : {weatherCondition}")
    _log(f"Vegetation Type   : {vegetationType}")

    # ── Validate required inputs ──────────────────────────────────────────────
    if not inputFeatures:
        arcpy.AddError("Input Features parameter is required.")
        return
    if not outputFolder:
        arcpy.AddError("Output Folder parameter is required.")
        return

    is_valid, msg = validate_feature_class(inputFeatures)
    if not is_valid:
        arcpy.AddError(msg)
        return
    _log(f"Input validated: {inputFeatures}")

    # ── Create unique output folder (race-condition safe) ─────────────────────
    try:
        analysis_folder = _create_unique_folder(outputFolder, "CCM_Analysis")
        _log(f"Output folder created: {analysis_folder}")
    except Exception as exc:
        arcpy.AddError(f"Could not create output folder: {exc}")
        return

    # ── Run assessment ────────────────────────────────────────────────────────
    try:
        ccm = CCMAssessment()
        ccm.execute(
            inputFeatures, analysis_folder, analysisDistance,
            vehicleType, obstacleFile, soilType, weatherCondition, vegetationType,
        )
        _log("Analysis completed successfully.")
    except Exception as exc:
        arcpy.AddError(f"Analysis failed: {exc}")


if __name__ == "__main__":
    main()
# <<< END OF FILE >>>
